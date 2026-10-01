"""Quotes: process an email (SSE stream of pipeline steps), read a quote, submit the human decision."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..config import get_settings
from ..db import Quote, get_db
from ..harness import PipelineError, ProcessRequest, quote_payload, run_pipeline
from ..retrain.corrections import CorrectionIn, DecisionIn, apply_decision, save_full_correction
from ..retrain.orchestrator import maybe_auto_trigger
from ..samples import get_sample
from ..tools import get_catalog
from .deps import admin_flag, limiter, require_admin

log = logging.getLogger("quotedesk.api")
router = APIRouter(prefix="/api/quotes", tags=["quotes"])


class ProcessIn(BaseModel):
    sender: Optional[str] = Field(default=None, max_length=320)
    subject: str = Field(default="", max_length=500)
    body: Optional[str] = None
    sample_id: Optional[str] = None


def _to_request(body: ProcessIn, is_admin: bool) -> ProcessRequest:
    if body.sample_id:
        smp = get_sample(body.sample_id)
        if not smp:
            raise HTTPException(404, "unknown sample")
        return ProcessRequest(sender=smp["sender"], subject=smp["subject"], body=smp["body"], is_admin=is_admin,
                              sample_id=smp["id"], source="sample")
    if not body.body or not body.body.strip():
        raise HTTPException(422, "body is required")
    if len(body.body) > get_settings().max_email_chars:
        raise HTTPException(413, f"email too long (max {get_settings().max_email_chars} characters)")
    return ProcessRequest(sender=body.sender or "Unknown Sender <unknown@unknown.example>", subject=body.subject,
                          body=body.body, is_admin=is_admin, source="pasted")


@router.post("/process")
@limiter.limit(lambda: get_settings().rate_limit)
async def process(request: Request, body: ProcessIn, stream: bool = Query(True),
                  is_admin: bool = Depends(admin_flag)):
    req = _to_request(body, is_admin)
    if not stream:
        try:
            return await asyncio.to_thread(run_pipeline, req)
        except PipelineError as e:
            raise HTTPException(422, str(e))

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: str, data: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    async def worker():
        try:
            result = await asyncio.to_thread(run_pipeline, req, emit)
            emit("done", {"quote_id": result["id"], "trace_id": result["trace_id"]})
        except PipelineError as e:
            emit("error", {"message": str(e)})
        except Exception:
            log.exception("pipeline failed")
            emit("error", {"message": "internal error while processing the email"})
        finally:
            emit("__end__", {})

    task = asyncio.create_task(worker())

    async def events():
        try:
            while True:
                event, data = await queue.get()
                if event == "__end__":
                    break
                yield {"event": event, "data": json.dumps(data, default=str)}
        finally:
            if not task.done():
                await task

    return EventSourceResponse(events(), ping=10)


@router.get("/{quote_id}")
def get_quote(quote_id: str, db: Session = Depends(get_db)):
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "quote not found")
    cust = get_catalog().by_id.get(q.customer_id) if q.customer_id else None
    out = quote_payload(q, cust)
    out["email"] = {"sender": q.email.sender, "subject": q.email.subject, "body": q.email.body,
                    "source": q.email.source, "sample_id": q.email.sample_id}
    return out


@router.post("/{quote_id}/correction", dependencies=[Depends(require_admin)])
def correct(quote_id: str, body: CorrectionIn, db: Session = Depends(get_db)):
    """Admin only: fix what the model read (intent, items, quantities...) and save it as a training example."""
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "quote not found")
    save_full_correction(db, q, body)
    db.flush()
    cust = get_catalog().by_id.get(q.customer_id) if q.customer_id else None
    return {"saved": True, "retrain": maybe_auto_trigger(db), "quote": quote_payload(q, cust)}


@router.post("/{quote_id}/decision")
@limiter.limit(lambda: get_settings().rate_limit)
def decide(request: Request, quote_id: str, decision: DecisionIn, db: Session = Depends(get_db),
           is_admin: bool = Depends(admin_flag)):
    q = db.get(Quote, quote_id)
    if not q:
        raise HTTPException(404, "quote not found")
    if q.decided_at is not None:
        raise HTTPException(409, "this quote was already decided")
    result = apply_decision(db, q, decision, is_admin=is_admin)
    db.flush()
    if is_admin:
        result["retrain"] = maybe_auto_trigger(db)
    cust = get_catalog().by_id.get(q.customer_id) if q.customer_id else None
    result["quote"] = quote_payload(q, cust)
    return result


__all__ = ["router", "Literal"]
