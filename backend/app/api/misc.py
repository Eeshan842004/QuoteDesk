"""Read-only endpoints: health, samples, traces, eval results."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import REPORTS_DIR, get_settings
from ..db import Email, Quote, Trace, get_db
from .deps import admin_flag
from ..models import get_registry
from ..models.teacher import get_teacher
from ..samples import list_samples

router = APIRouter(prefix="/api", tags=["read"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    s = get_settings()
    try:
        db.execute(text("select 1"))
        db_ok = True
    except Exception:
        db_ok = False
    teacher = get_teacher()
    return {
        "status": "ok" if db_ok else "degraded", "db": db_ok,
        "student": {"enabled": s.student_enabled, **get_registry().status()},
        "teacher": {"configured": teacher.configured, "model": s.teacher_model, "provider": s.provider,
                    "live_mode": s.teacher_live_mode, "cached_samples": len(teacher.sample_cache)},
        "router_threshold": s.router_threshold, "admin_configured": bool(s.admin_token),
        "notice": "Demo with synthetic data and a fictional company.",
    }


@router.get("/samples")
def samples():
    teacher = get_teacher()
    return [{**s, "teacher_cached": s["id"] in teacher.sample_cache} for s in list_samples()]


@router.get("/traces")
def traces(limit: int = Query(50, le=200), offset: int = 0, intent: Optional[str] = None,
           path: Optional[str] = None, db: Session = Depends(get_db), is_admin: bool = Depends(admin_flag)):
    """Public list shows only the demo samples: emails pasted by visitors stay private (reachable only through
    their own unguessable trace link). Admins see everything."""
    q = select(Trace).order_by(Trace.created_at.desc())
    if not is_admin:
        q = q.join(Email, Email.id == Trace.email_id).where(Email.source == "sample")
    if intent:
        q = q.where(Trace.intent == intent)
    if path:
        q = q.where(Trace.path == path)
    rows = db.scalars(q.limit(limit).offset(offset)).all()
    quote_by_trace = {qq.trace_id: qq for qq in db.scalars(select(Quote).where(Quote.trace_id.in_([t.id for t in rows])))}
    out = []
    for t in rows:
        qq = quote_by_trace.get(t.id)
        out.append({"id": t.id, "created_at": t.created_at.isoformat(), "intent": t.intent, "path": t.path,
                    "latency_ms": t.latency_ms, "cost_usd": t.cost_usd, "escalated": t.escalated,
                    "status": qq.status if qq else t.status, "quote_id": qq.id if qq else None,
                    "needs_review": qq.needs_review if qq else None, "model_version": t.model_version,
                    "subject": t.email.subject, "sender": t.email.sender, "source": t.email.source,
                    "injection_suspected": t.email.injection_suspected})
    return out


@router.get("/traces/{trace_id}")
def trace_detail(trace_id: str, db: Session = Depends(get_db)):
    t = db.get(Trace, trace_id)
    if not t:
        raise HTTPException(404, "trace not found")
    qq = db.scalars(select(Quote).where(Quote.trace_id == t.id)).first()
    return {"id": t.id, "created_at": t.created_at.isoformat(), "intent": t.intent, "path": t.path,
            "latency_ms": t.latency_ms, "cost_usd": t.cost_usd, "escalated": t.escalated, "status": t.status,
            "model_version": t.model_version, "quote_id": qq.id if qq else None,
            "email": {"sender": t.email.sender, "subject": t.email.subject, "body": t.email.body,
                      "source": t.email.source},
            "spans": [{"seq": s.seq, "name": s.name, "status": s.status,
                       "started_at": s.started_at.isoformat() if s.started_at else None,
                       "duration_ms": s.duration_ms, "model": s.model, "inputs": s.inputs, "outputs": s.outputs,
                       "tokens_in": s.tokens_in, "tokens_out": s.tokens_out, "cost_usd": s.cost_usd,
                       "retries": s.retries, "error": s.error} for s in t.spans]}


def latest_report_dir():
    if not REPORTS_DIR.exists():
        return None
    dirs = sorted((p for p in REPORTS_DIR.iterdir() if p.is_dir() and (p / "summary.json").exists()), reverse=True)
    return dirs[0] if dirs else None


@router.get("/eval/latest")
def eval_latest():
    d = latest_report_dir()
    if d is None:
        return {"available": False, "message": "No evaluation report yet. Run eval/run_eval.py."}
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    calib = d / "calibration.json"
    return {"available": True, "report_dir": d.name, **summary,
            "calibration": json.loads(calib.read_text(encoding="utf-8")) if calib.exists() else None}
