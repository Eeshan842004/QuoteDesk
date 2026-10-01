"""SQLAlchemy models: emails, quotes, quote_lines, traces, spans, corrections, model_versions, retrain_runs,
eval_runs (+ a tiny app_state key/value table for flags such as auto-retrain pause)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Email(Base):
    __tablename__ = "emails"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sender: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text)
    customer_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="pasted")  # sample | pasted | api
    sample_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    injection_suspected: Mapped[bool] = mapped_column(Boolean, default=False)


class Trace(Base):
    __tablename__ = "traces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email_id: Mapped[str] = mapped_column(ForeignKey("emails.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | completed | failed
    path: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # student | teacher | teacher_cached | ...
    intent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    model_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[Email] = relationship()
    spans: Mapped[list["Span"]] = relationship(back_populates="trace", order_by="Span.seq", cascade="all, delete-orphan")


class Span(Base):
    __tablename__ = "spans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | skipped | flagged
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    inputs: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    outputs: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trace: Mapped[Trace] = relationship(back_populates="spans")


class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email_id: Mapped[str] = mapped_column(ForeignKey("emails.id"))
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(24), default="pending_approval")
    # pending_approval | approved | edited | rejected | sent | no_quote
    intent: Mapped[str] = mapped_column(String(32))
    customer_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    flags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    suggested_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extraction: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    student_extraction: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    extraction_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sandbox: Mapped[bool] = mapped_column(Boolean, default=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # public | admin
    lines: Mapped[list["QuoteLine"]] = relationship(back_populates="quote", order_by="QuoteLine.line_no",
                                                    cascade="all, delete-orphan")
    email: Mapped[Email] = relationship()


class QuoteLine(Base):
    __tablename__ = "quote_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    list_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    line_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stock_qty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="NEEDS_REVIEW")  # CONFIDENT | NEEDS_REVIEW
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    candidates: Mapped[list[Any]] = mapped_column(JSON, default=list)
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    quote: Mapped[Quote] = relationship(back_populates="lines")


class Correction(Base):
    __tablename__ = "corrections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), index=True)
    email_id: Mapped[str] = mapped_column(ForeignKey("emails.id"))
    kind: Mapped[str] = mapped_column(String(16))  # EXTRACTION | RESOLUTION | BUSINESS
    field: Mapped[str] = mapped_column(String(64))
    before: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    counts_for_training: Mapped[bool] = mapped_column(Boolean, default=False)
    training_example: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    used_in_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("retrain_runs.id"), nullable=True)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), unique=True)
    hf_repo: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    revision: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="candidate")  # live | candidate | rejected | retired
    source: Mapped[str] = mapped_column(String(24), default="notebook")  # notebook | manual_register | auto
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    promoted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    eval_report: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    gate: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RetrainRun(Base):
    __tablename__ = "retrain_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    mode: Mapped[str] = mapped_column(String(16), default="manual")  # manual | auto
    state: Mapped[str] = mapped_column(String(24), default="COLLECTING")
    corrections_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    bundle_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    kaggle_kernel_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    gate_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    log: Mapped[list[Any]] = mapped_column(JSON, default=list)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    report_dir: Mapped[str] = mapped_column(String(300))
    summary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)


class AppState(Base):
    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
