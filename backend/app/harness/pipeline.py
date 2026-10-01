"""The harness pipeline (a small state machine; each state is a traced span):

RECEIVED -> GUARD -> EXTRACT(student) -> VALIDATE -> [REPAIR] -> [ESCALATE(teacher)] -> RESOLVE(tools)
         -> DRAFT -> PENDING_APPROVAL      (APPROVED | EDITED | REJECTED -> SENT happen at decision time)

Budgets: max 1 student retry, max 1 teacher call, REQUEST_TIMEOUT_S total, MAX_COST_PER_REQUEST_USD.
On teacher failure/timeout the student result is returned flagged for human review (graceful degradation).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from evallib.postprocess import repair_missing_info
from evallib.prompt import chat_messages
from evallib.runner import student_cost_usd
from evallib.schema import Extraction, parse_extraction, semantic_errors

from ..config import get_settings
from ..db import Email, Quote, QuoteLine, Span, Trace, session_scope
from ..models import get_registry
from ..models.teacher import LLMError, get_teacher
from ..tools import get_catalog
from . import guard
from .draft import resolve_and_draft, suggested_action
from .router import confidence, should_escalate
from .tracing import Emit, Tracer

log = logging.getLogger("quotedesk.pipeline")


@dataclass
class ProcessRequest:
    sender: str
    subject: str
    body: str
    is_admin: bool = False
    sample_id: Optional[str] = None
    source: str = "pasted"


class PipelineError(Exception):
    pass


def _repair_messages(req: ProcessRequest, bad_output: str, error: str) -> list[dict]:
    msgs = chat_messages(req.sender, req.subject, req.body)
    msgs[1]["content"] += (f"\n\nYour previous answer was invalid ({error}). Previous answer:\n{bad_output[:1500]}\n"
                           "Reply again with one corrected JSON object only.")
    return msgs


def run_pipeline(req: ProcessRequest, emit: Optional[Emit] = None) -> dict:
    s = get_settings()
    tr = Tracer(emit)
    catalog = get_catalog()
    teacher = get_teacher()
    registry = get_registry()
    student = registry.get()
    flags: dict = {"prompt_injection_suspected": False, "injection_matches": [], "teacher_cached": False,
                   "would_escalate": False, "degraded": False, "needs_review_reasons": []}
    path = None
    escalated = False
    student_ext: Optional[Extraction] = None
    final_ext: Optional[Extraction] = None
    extraction_source = None

    # ---------------------------------------------------------------- RECEIVED
    with tr.span("RECEIVED", inputs={"sender": req.sender, "subject": req.subject, "chars": len(req.body),
                                     "source": req.source, "sample_id": req.sample_id}) as sp:
        customer = catalog.customer_for_sender(req.sender)
        sp.outputs = {"customer_id": customer["id"] if customer else None,
                      "customer": customer["company"] if customer else None}
        sp.summary = f"from {customer['company']}" if customer else "unknown sender (list prices)"

    # ---------------------------------------------------------------- GUARD
    with tr.span("GUARD") as sp:
        g = guard.check(req.body, req.subject, s.max_email_chars)
        sp.outputs = {"ok": g.ok, "prompt_injection_suspected": g.injection_suspected, "matches": g.matches}
        if not g.ok:
            sp.status, sp.error = "error", g.error
            raise PipelineError(g.error)
        if g.injection_suspected:
            sp.status = "flagged"
            flags["prompt_injection_suspected"] = True
            flags["injection_matches"] = g.matches
            flags["needs_review_reasons"].append("possible prompt injection in the email")
            sp.summary = "instruction-like text found; treated as data"
        else:
            sp.summary = "clean"

    # ---------------------------------------------------------------- EXTRACT + VALIDATE (+ REPAIR)
    conf = {"score": 0.0, "validity": 0.0}
    student_text = None
    if student is None:
        with tr.span("EXTRACT", model="student (not loaded)") as sp:
            sp.status = "skipped"
            sp.summary = "student model not loaded: teacher-only mode"
            sp.outputs = {"registry": registry.status()}
    else:
        msgs = chat_messages(req.sender, req.subject, req.body)
        errors: list[str] = []
        out = None
        for attempt in range(2):  # 1 try + max 1 repair
            name = "EXTRACT" if attempt == 0 else "REPAIR"
            with tr.span(name, model=f"student:{registry.version}") as sp:
                out = student.generate(msgs)
                student_text = out.text
                sp.tokens_in, sp.tokens_out = out.prompt_tokens, out.n_tokens
                sp.cost_usd = student_cost_usd(out.latency_s)
                sp.retries = attempt
                sp.outputs = {"text": out.text[:4000], "mean_logprob": round(out.mean_logprob, 4),
                              "min_token_prob": round(out.min_token_prob, 4)}
                sp.summary = f"{out.n_tokens} tokens in {out.latency_s:.1f}s"
            with tr.span("VALIDATE") as sp:
                ext, err = parse_extraction(out.text)
                errors = ([err] if err else []) + (semantic_errors(ext) if ext else [])
                sp.outputs = {"valid": not errors, "errors": errors}
                if errors:
                    sp.status = "error"
                    sp.summary = errors[0][:120]
                else:
                    student_ext = ext
                    sp.summary = f"valid · intent={ext.intent} · {len(ext.items)} items"
            if not errors or tr.elapsed_s() > s.request_timeout_s * 0.5:
                break
            msgs = _repair_messages(req, out.text, errors[0])
        conf = confidence(out.mean_logprob if out else None, student_ext, errors)
        if student_ext is not None:
            with tr.span("NORMALIZE") as sp:
                before = student_ext.missing_info
                student_ext = repair_missing_info(student_ext, req.body)
                sp.outputs = {"missing_info_before": before, "missing_info_after": student_ext.missing_info}
                sp.summary = ("missing_info recomputed by rules: " + (", ".join(student_ext.missing_info) or "none"))

    # ---------------------------------------------------------------- ROUTE / ESCALATE
    want_escalation, route_reason = (True, "no student model") if student is None else \
        should_escalate(conf, s.router_threshold)
    with tr.span("ROUTE", inputs={"confidence": conf, "threshold": s.router_threshold}) as sp:
        sp.outputs = {"escalate": want_escalation, "reason": route_reason}
        sp.summary = route_reason
    if not want_escalation:
        final_ext, extraction_source, path = student_ext, "student", "student"
    else:
        allowed_live = s.teacher_live_mode == "all" or (s.teacher_live_mode == "admin_only" and req.is_admin)
        cached = teacher.cached_for_sample(req.sample_id) if req.sample_id else None
        with tr.span("ESCALATE", model=s.teacher_model) as sp:
            if cached and not (allowed_live and req.is_admin):
                ext, err = parse_extraction(cached.text)
                sp.outputs = {"cached": True, "cached_at": cached.cached_at, "text": cached.text[:4000]}
                sp.summary = f"teacher result (cached {cached.cached_at or ''})"
                sp.tokens_in, sp.tokens_out = cached.prompt_tokens, cached.output_tokens
                flags["teacher_cached"] = True
                if ext:
                    final_ext, extraction_source, path, escalated = ext, "teacher_cached", "teacher_cached", True
            elif not allowed_live:
                sp.status = "skipped"
                flags["would_escalate"] = True
                sp.summary = "would escalate: teacher disabled for public input (TEACHER_LIVE_MODE=admin_only)"
                flags["needs_review_reasons"].append("low-confidence extraction; expert model not called for public input")
            elif not teacher.configured:
                sp.status = "skipped"
                flags["would_escalate"] = True
                sp.summary = "teacher not configured"
            else:
                est = teacher.estimate_cost_usd(req.sender, req.subject, req.body)
                remaining = s.request_timeout_s - tr.elapsed_s()
                if est + tr.total_cost > s.max_cost_per_request_usd:
                    sp.status = "skipped"
                    sp.summary = f"cost cap: estimated ${est:.4f} exceeds per-request budget"
                    flags["degraded"] = True
                elif remaining < 3:
                    sp.status = "skipped"
                    sp.summary = "time budget exhausted"
                    flags["degraded"] = True
                else:
                    try:
                        t = teacher.extract(req.sender, req.subject, req.body, deadline_s=remaining)
                        ext, err = parse_extraction(t.text)
                        sp.tokens_in, sp.tokens_out, sp.cost_usd = t.prompt_tokens, t.output_tokens, t.cost_usd
                        sp.outputs = {"text": t.text[:4000], "credits": t.credits, "latency_s": round(t.latency_s, 2)}
                        if ext and not semantic_errors(ext):
                            final_ext, extraction_source, path, escalated = ext, "teacher", "teacher", True
                            sp.summary = f"teacher answered in {t.latency_s:.1f}s"
                        else:
                            sp.status, sp.error = "error", err or "teacher output failed validation"
                            flags["degraded"] = True
                    except LLMError as e:
                        sp.status, sp.error = "error", str(e)[:300]
                        sp.summary = "teacher unavailable: falling back to student result"
                        flags["degraded"] = True
        if final_ext is None:
            final_ext, extraction_source = student_ext, "student_flagged"
            path = "student_flagged" if student_ext else "none"
            flags["needs_review_reasons"].append("result not confirmed by the expert model")

    if final_ext is None:
        with tr.span("DRAFT") as sp:
            sp.status = "error"
            sp.summary = "no usable extraction (student unavailable/invalid and teacher not called)"
        quote = _persist(req, tr, customer, None, None, [], flags, path or "none", escalated, "no_quote",
                         "Could not read this email automatically. Please handle it manually.", None, conf)
        return quote

    # ---------------------------------------------------------------- RESOLVE + DRAFT
    lines: list[dict] = []
    action = None
    status = "pending_approval"
    cust_id = customer["id"] if customer else None
    with tr.span("RESOLVE", inputs={"items": len(final_ext.items), "customer_id": cust_id}) as sp:
        if final_ext.intent in ("quote_request",):
            lines, calls = resolve_and_draft(final_ext, cust_id)
            sp.outputs = {"tool_calls": calls}
            n_rev = sum(1 for l in lines if l["status"] == "NEEDS_REVIEW")
            sp.summary = f"{len(lines)} lines · {n_rev} need review"
        else:
            action = suggested_action(final_ext, req.body, cust_id)
            sp.outputs = {"suggested_action": action}
            sp.summary = f"{final_ext.intent}: no quote"
            status = "no_quote"
    with tr.span("DRAFT") as sp:
        subtotal = round(sum(l["line_total"] or 0 for l in lines), 2)
        sp.outputs = {"subtotal": subtotal, "lines": len(lines)}
        sp.summary = f"draft ${subtotal:,.2f}" if lines else (action or "")[:120]
    with tr.span("PENDING_APPROVAL") as sp:
        sp.summary = "waiting for a human" if status == "pending_approval" else "suggested action ready"
    return _persist(req, tr, customer, final_ext, student_ext, lines, flags, path, escalated, status, action,
                    extraction_source, conf)


def _persist(req, tr: Tracer, customer, final_ext, student_ext, lines, flags, path, escalated, status, action,
             extraction_source, conf) -> dict:
    s = get_settings()
    needs_review = bool(flags["needs_review_reasons"]) or any(l["status"] == "NEEDS_REVIEW" for l in lines) \
        or status == "no_quote" and final_ext is None
    subtotal = round(sum(l["line_total"] or 0 for l in lines), 2)
    reg = get_registry()
    with session_scope() as db:
        email = Email(sender=req.sender, subject=req.subject, body=req.body,
                      customer_id=customer["id"] if customer else None, source=req.source,
                      sample_id=req.sample_id, is_admin=req.is_admin,
                      injection_suspected=flags["prompt_injection_suspected"])
        db.add(email)
        db.flush()
        trace = Trace(email_id=email.id, status="completed", path=path, intent=final_ext.intent if final_ext else None,
                      latency_ms=int(tr.elapsed_s() * 1000), cost_usd=round(tr.total_cost, 6), escalated=escalated,
                      model_version=reg.version)
        db.add(trace)
        db.flush()
        for sp in tr.spans:
            db.add(Span(trace_id=trace.id, seq=sp.seq, name=sp.name, status=sp.status, started_at=sp.started_at,
                        ended_at=sp.ended_at, duration_ms=sp.duration_ms, model=sp.model,
                        inputs=_jsonable(sp.inputs), outputs=_jsonable({**(sp.outputs or {}), "summary": sp.summary}),
                        tokens_in=sp.tokens_in, tokens_out=sp.tokens_out, cost_usd=sp.cost_usd,
                        retries=sp.retries, error=sp.error))
        q = Quote(email_id=email.id, trace_id=trace.id, status=status,
                  intent=final_ext.intent if final_ext else "unknown",
                  customer_id=customer["id"] if customer else None,
                  customer_name=customer["company"] if customer else None, subtotal=subtotal, total=subtotal,
                  needs_review=needs_review, flags={**flags, "path": path, "confidence": conf},
                  suggested_action=action, extraction=final_ext.model_dump(mode="json") if final_ext else None,
                  student_extraction=student_ext.model_dump(mode="json") if student_ext else None,
                  extraction_source=extraction_source, sandbox=not req.is_admin)
        db.add(q)
        db.flush()
        for l in lines:
            db.add(QuoteLine(quote_id=q.id, line_no=l["line_no"], item_index=l["item_index"],
                             description=l["description"], quantity=l["quantity"], unit=l["unit"], sku=l["sku"],
                             name=l["name"], unit_price=l["unit_price"], list_price=l["list_price"],
                             discount_pct=l["discount_pct"], line_total=l["line_total"], stock_qty=l["stock_qty"],
                             status=l["status"], reason=l["reason"], candidates=l["candidates"]))
        db.flush()
        db.refresh(q)
        payload = quote_payload(q, customer)
    tr.emit("quote", payload)
    return payload


def _jsonable(x):
    if x is None:
        return None
    return json.loads(json.dumps(x, default=str))


def quote_payload(q: Quote, customer: Optional[dict] = None) -> dict:
    return {
        "id": q.id, "trace_id": q.trace_id, "email_id": q.email_id, "status": q.status, "intent": q.intent,
        "created_at": q.created_at.isoformat() if q.created_at else None,
        "customer": {"id": q.customer_id, "name": q.customer_name,
                     "tier": customer["tier"] if customer else None} if q.customer_id else None,
        "subtotal": q.subtotal, "total": q.total, "currency": q.currency, "needs_review": q.needs_review,
        "flags": q.flags, "suggested_action": q.suggested_action, "extraction": q.extraction,
        "student_extraction": q.student_extraction, "extraction_source": q.extraction_source, "sandbox": q.sandbox,
        "decided_by": q.decided_by, "decided_at": q.decided_at.isoformat() if q.decided_at else None,
        "lines": [{"line_no": l.line_no, "item_index": l.item_index, "description": l.description,
                   "quantity": l.quantity, "unit": l.unit, "sku": l.sku, "name": l.name, "unit_price": l.unit_price,
                   "list_price": l.list_price, "discount_pct": l.discount_pct, "line_total": l.line_total,
                   "stock_qty": l.stock_qty, "status": l.status, "reason": l.reason, "candidates": l.candidates,
                   "removed": l.removed, "added_by_user": l.added_by_user} for l in q.lines],
    }
