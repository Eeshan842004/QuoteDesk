"""Human decisions on a draft quote and the correction classifier.

Each change the manager makes is classified:
- EXTRACTION: the model misread the email (wrong/missing/extra item, wrong quantity). With an admin token this
  becomes a training example: email + corrected extraction JSON.
- RESOLUTION: the tools picked the wrong SKU. Logged as tool feedback (alias suggestion). NOT training data.
- BUSINESS: a deliberate substitution / business choice. NOT training data.
Public visitors act in a sandbox: their decisions are stored but never count toward retraining (anti-poisoning).
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy import select
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import json
from pathlib import Path

from evallib.normalize import email_hash, find_ci, norm_text
from evallib.postprocess import derive_missing_info
from evallib.prompt import chat_messages
from evallib.schema import Extraction, Unit, semantic_errors, to_target_json

from ..config import DATA_DIR
from ..db import Correction, Quote, QuoteLine
from ..tools import get_catalog

Reason = Literal["misread", "wrong_part", "business"]


class LineDecision(BaseModel):
    line_no: Optional[int] = None  # None for a newly added line
    action: Literal["accept", "change_sku", "edit_quantity", "remove", "add"] = "accept"
    sku: Optional[str] = None
    quantity: Optional[int] = Field(default=None, ge=1, le=100000)
    description: Optional[str] = Field(default=None, max_length=300)
    reason: Optional[Reason] = None


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    lines: list[LineDecision] = Field(default_factory=list)
    note: Optional[str] = Field(default=None, max_length=1000)


def _classify(action: str, reason: Optional[str]) -> str:
    if reason == "business":
        return "BUSINESS"
    if action == "change_sku":
        return "EXTRACTION" if reason == "misread" else "RESOLUTION"
    return "EXTRACTION"  # edit_quantity / remove / add default to a misread unless marked business


def _reprice(line: QuoteLine, customer_id: Optional[str]) -> None:
    cat = get_catalog()
    if not line.sku:
        return
    p = cat.by_sku[line.sku]
    line.name, line.list_price, line.stock_qty = p["name"], p["list_price"], p["stock_qty"]
    if line.quantity:
        pr = cat.get_price(line.sku, customer_id, line.quantity)  # prices only ever come from the tool
        line.unit_price, line.discount_pct, line.line_total = pr.unit_price, pr.discount_pct, pr.line_total
    else:
        line.unit_price = line.discount_pct = line.line_total = None


def corrected_extraction(original: dict, changes: list[dict]) -> dict:
    """Apply EXTRACTION changes to the model's extraction to get the training target."""
    ext = copy.deepcopy(original)
    items = ext["items"]
    remove_idx = set()
    for ch in changes:
        idx = ch.get("item_index")
        if ch["action"] == "edit_quantity" and idx is not None and idx < len(items):
            items[idx]["quantity"] = ch["quantity"]
        elif ch["action"] == "remove" and idx is not None:
            remove_idx.add(idx)
        elif ch["action"] == "change_sku" and idx is not None and ch.get("part_number_fix"):
            items[idx]["part_number"] = None
        elif ch["action"] == "add":
            items.append({"description": ch["description"], "quantity": ch.get("quantity"), "unit": None,
                          "part_number": None, "compatible_with": None, "reference": None})
    removed_desc = {norm_text(items[i]["description"]) for i in remove_idx if i < len(items)}
    ext["items"] = [it for i, it in enumerate(items) if i not in remove_idx]
    have_qty = {norm_text(it["description"]) for it in ext["items"] if it["quantity"] is not None}
    ext["missing_info"] = [m for m in ext["missing_info"]
                           if not (m.startswith("quantity:") and norm_text(m.split(":", 1)[1]) in have_qty)
                           and not (":" in m and norm_text(m.split(":", 1)[1]) in removed_desc)]
    if ext["items"] and ext["intent"] not in ("quote_request", "return_request", "product_question"):
        ext["intent"] = "quote_request"
    return Extraction.model_validate(ext).model_dump(mode="json")


def apply_decision(db: Session, q: Quote, d: DecisionIn, is_admin: bool) -> dict:
    if q.status == "no_quote" and d.decision == "approve" and not d.lines:
        q.status, q.decided_at, q.decided_by = "approved", datetime.now(timezone.utc), "admin" if is_admin else "public"
        return {"status": q.status, "corrections": []}
    lines = {l.line_no: l for l in q.lines}
    cat = get_catalog()
    corrections: list[Correction] = []
    extraction_changes: list[dict] = []
    edited = False
    # Reject alone is NOT a correction: line edits are ignored on reject.
    # A quote that already has a saved "Correct result" is trained from that, not from line edits.
    has_full = db.scalars(select(Correction).where(Correction.quote_id == q.id,
                                                   Correction.field == FULL_CORRECTION)).first() is not None
    line_edits = [] if d.decision == "reject" else d.lines

    for ld in line_edits:
        if ld.action == "accept":
            continue
        kind = _classify(ld.action, ld.reason)
        if ld.action == "add":
            if not ld.sku or ld.sku not in cat.by_sku or not ld.quantity:
                raise HTTPException(422, "an added line needs a valid sku and quantity")
            desc = ld.description or cat.by_sku[ld.sku]["name"]
            new = QuoteLine(quote_id=q.id, line_no=max(lines, default=0) + 1, item_index=None, description=desc,
                            quantity=ld.quantity, sku=ld.sku, status="CONFIDENT", reason="added by reviewer",
                            candidates=[], added_by_user=True)
            _reprice(new, q.customer_id)
            q.lines.append(new)
            lines[new.line_no] = new
            before, after = None, {"sku": ld.sku, "quantity": ld.quantity, "description": desc}
            if kind == "EXTRACTION":
                extraction_changes.append({"action": "add", "description": desc, "quantity": ld.quantity})
        else:
            line = lines.get(ld.line_no)
            if line is None:
                raise HTTPException(422, f"unknown line {ld.line_no}")
            before = {"sku": line.sku, "quantity": line.quantity, "description": line.description}
            if ld.action == "change_sku":
                if not ld.sku or ld.sku not in cat.by_sku:
                    raise HTTPException(422, "change_sku needs a valid sku")
                line.sku = ld.sku
                line.status, line.reason = "CONFIDENT", "SKU chosen by reviewer"
            elif ld.action == "edit_quantity":
                if not ld.quantity:
                    raise HTTPException(422, "edit_quantity needs a quantity")
                line.quantity = ld.quantity
                if kind == "EXTRACTION":
                    extraction_changes.append({"action": "edit_quantity", "item_index": line.item_index,
                                               "quantity": ld.quantity})
            elif ld.action == "remove":
                line.removed = True
                if kind == "EXTRACTION":
                    extraction_changes.append({"action": "remove", "item_index": line.item_index})
            _reprice(line, q.customer_id)
            after = {"sku": line.sku, "quantity": line.quantity, "removed": line.removed}
        edited = True
        note = None
        if kind == "RESOLUTION":
            note = f"alias suggestion: '{(before or {}).get('description')}' -> {ld.sku}"
        corrections.append(Correction(quote_id=q.id, email_id=q.email_id, kind=kind, field=ld.action,
                                      before=before, after=after, note=note or d.note, is_admin=is_admin,
                                      counts_for_training=bool(is_admin and kind == "EXTRACTION" and not has_full)))

    training_example = None
    if is_admin and not has_full and extraction_changes and q.extraction:
        target = corrected_extraction(q.extraction, extraction_changes)
        e = q.email
        training_example = {"id": f"corr-{q.id}", "customer_id": q.customer_id, "intent": target["intent"],
                            "difficulty": "correction", "sender": e.sender, "subject": e.subject, "body": e.body,
                            "target": to_target_json(target), "source": "correction",
                            "messages": chat_messages(e.sender, e.subject, e.body, to_target_json(target))}
    for c in corrections:
        if c.counts_for_training:
            c.training_example = training_example
        db.add(c)

    active = [l for l in q.lines if not l.removed]
    q.subtotal = q.total = round(sum(l.line_total or 0 for l in active), 2)
    now = datetime.now(timezone.utc)
    q.decided_at, q.decided_by = now, ("admin" if is_admin else "public")
    if d.decision == "reject":
        q.status = "rejected"
    else:
        q.status = "sent"  # APPROVED/EDITED -> SENT (simulated)
        q.flags = {**(q.flags or {}), "decision": "edited" if edited else "approved", "sent_at": now.isoformat(),
                   "sent_note": "simulated: no email is actually sent"}
    return {"status": q.status, "decision": "edited" if edited and d.decision == "approve" else d.decision,
            "sandbox": not is_admin,
            "corrections": [{"kind": c.kind, "field": c.field, "before": c.before, "after": c.after,
                             "counts_for_training": c.counts_for_training, "note": c.note} for c in corrections]}


# ---------------------------------------------------------------------------------------------------------
# "Correct result": the admin fixes the model's extraction itself and saves it as a training example.
# ---------------------------------------------------------------------------------------------------------
FULL_CORRECTION = "full_correction"


class CorrectionItem(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    quantity: Optional[int] = Field(default=None, ge=1, le=100000)
    unit: Optional[Unit] = None
    part_number: Optional[str] = Field(default=None, max_length=60)
    compatible_with: Optional[str] = Field(default=None, max_length=60)
    reference: Optional[Literal["previous_order"]] = None
    needs_size_or_spec: bool = False
    needs_equipment_model: bool = False


class CorrectionIn(BaseModel):
    intent: Literal["quote_request", "order_status", "return_request", "product_question", "other"]
    urgency: Literal["low", "normal", "high"] = "normal"
    needed_by: Optional[str] = Field(default=None, max_length=120)
    items: list[CorrectionItem] = Field(default_factory=list, max_length=12)
    note: Optional[str] = Field(default=None, max_length=1000)


def _exam_hashes() -> set[str]:
    p = Path(DATA_DIR) / "splits" / "exam_hashes.json"
    return set(json.loads(p.read_text(encoding="utf-8"))["hashes"]) if p.exists() else set()


def build_corrected_extraction(body: str, c: CorrectionIn) -> dict:
    """Validate the admin's correction against the labeling rules and build the training target.

    - every description / part number / equipment model / deadline must appear verbatim in the email
    - missing_info is rebuilt by the labeling rules (quantity, order_number from rules; size_or_spec and
      equipment_model from the admin's per-item flags), so training labels stay consistent
    """
    problems: list[str] = []
    for i, it in enumerate(c.items, 1):
        for fld in ("description", "part_number", "compatible_with"):
            v = getattr(it, fld)
            if v and not find_ci(body, v.strip()):
                problems.append(f"item {i} {fld.replace('_', ' ')} '{v}' is not written in the email (copy it exactly)")
    if c.needed_by and not find_ci(body, c.needed_by.strip()):
        problems.append(f"deadline '{c.needed_by}' is not written in the email (copy it exactly)")
    if problems:
        raise HTTPException(422, "; ".join(problems))

    base = {
        "intent": c.intent, "urgency": c.urgency, "needed_by": c.needed_by.strip() if c.needed_by else None,
        "items": [{"description": it.description.strip(), "quantity": it.quantity, "unit": it.unit if it.quantity else None,
                   "part_number": it.part_number.strip() if it.part_number else None,
                   "compatible_with": it.compatible_with.strip() if it.compatible_with else None,
                   "reference": it.reference} for it in c.items],
        "missing_info": [],
    }
    if c.intent in ("order_status", "other"):
        base["items"] = []
    ext = Extraction.model_validate(base)
    missing = [m for m in derive_missing_info(ext, body) if not m.startswith("equipment_model")]
    for it in c.items if c.intent not in ("order_status", "other") else []:
        if it.needs_equipment_model:
            missing.append(f"equipment_model: {it.description.strip()}")
        if it.needs_size_or_spec:
            missing.append(f"size_or_spec: {it.description.strip()}")
    ext = ext.model_copy(update={"missing_info": missing})
    errs = semantic_errors(ext)
    if errs:
        raise HTTPException(422, "; ".join(errs))
    return ext.model_dump(mode="json")


def save_full_correction(db: Session, q: Quote, c: CorrectionIn) -> dict:
    """Store an admin correction of the model's extraction. One training example per quote (re-saving replaces)."""
    from ..harness.draft import resolve_and_draft

    if q.decided_at is not None:
        raise HTTPException(409, "this quote was already decided; correct it before approving or rejecting")
    e = q.email
    if email_hash(e.body) in _exam_hashes():
        raise HTTPException(422, "this email belongs to the sealed exam set and can never be used for training")
    target = build_corrected_extraction(e.body, c)
    before = q.student_extraction or q.extraction
    if before is not None and before == target and q.extraction == target:
        raise HTTPException(422, "no changes: the corrected result is identical to the model's result")

    for old in db.scalars(select(Correction).where(Correction.quote_id == q.id, Correction.counts_for_training.is_(True),
                                                   Correction.used_in_run_id.is_(None))):
        old.counts_for_training = False  # superseded by this correction
    tgt_json = to_target_json(target)
    example = {"id": f"corr-{q.id}", "customer_id": q.customer_id, "intent": target["intent"], "difficulty": "correction",
               "sender": e.sender, "subject": e.subject, "body": e.body, "target": tgt_json, "source": "correction",
               "messages": chat_messages(e.sender, e.subject, e.body, tgt_json)}
    db.add(Correction(quote_id=q.id, email_id=q.email_id, kind="EXTRACTION", field=FULL_CORRECTION,
                      before=before, after=target, note=c.note, is_admin=True, counts_for_training=True,
                      training_example=example))

    # redraft the quote from the corrected extraction so the reviewer sees the effect immediately
    ext = Extraction.model_validate(target)
    for l in list(q.lines):
        q.lines.remove(l)
    if ext.intent == "quote_request":
        lines, _ = resolve_and_draft(ext, q.customer_id)
        for l in lines:
            q.lines.append(QuoteLine(line_no=l["line_no"], item_index=l["item_index"], description=l["description"],
                                     quantity=l["quantity"], unit=l["unit"], sku=l["sku"], name=l["name"],
                                     unit_price=l["unit_price"], list_price=l["list_price"],
                                     discount_pct=l["discount_pct"], line_total=l["line_total"],
                                     stock_qty=l["stock_qty"], status=l["status"], reason=l["reason"],
                                     candidates=l["candidates"]))
        q.status, q.suggested_action = "pending_approval", None
    else:
        from ..harness.draft import suggested_action
        q.status, q.suggested_action = "no_quote", suggested_action(ext, e.body, q.customer_id)
    q.intent, q.extraction, q.extraction_source = ext.intent, target, "admin_corrected"
    q.subtotal = q.total = round(sum(l.line_total or 0 for l in q.lines), 2)
    q.needs_review = any(l.status == "NEEDS_REVIEW" for l in q.lines)
    q.flags = {**(q.flags or {}), "admin_corrected": True,
               "needs_review_reasons": [r for r in (q.flags or {}).get("needs_review_reasons", [])
                                        if "expert model" not in r and "not confirmed" not in r]}
    return target
