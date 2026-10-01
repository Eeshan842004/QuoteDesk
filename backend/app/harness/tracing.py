"""Span tracing. Every pipeline step is a span (name, timing, inputs, outputs, model, tokens, cost, retries,
errors) that is streamed to the client as it starts/ends and persisted with the trace."""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

Emit = Callable[[str, dict], None]


@dataclass
class SpanRecord:
    seq: int
    name: str
    status: str = "ok"  # ok | error | skipped | flagged
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    model: Optional[str] = None
    inputs: Optional[dict] = None
    outputs: Optional[dict] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: float = 0.0
    retries: int = 0
    error: Optional[str] = None
    summary: Optional[str] = None  # one-line human description for the timeline

    def public(self) -> dict:
        return {"seq": self.seq, "step": self.name, "status": self.status, "duration_ms": self.duration_ms,
                "model": self.model, "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "cost_usd": round(self.cost_usd, 6), "retries": self.retries, "error": self.error,
                "summary": self.summary}


class Tracer:
    def __init__(self, emit: Optional[Emit] = None):
        self.spans: list[SpanRecord] = []
        self._emit = emit or (lambda event, data: None)
        self.t0 = time.perf_counter()

    def emit(self, event: str, data: dict) -> None:
        try:
            self._emit(event, data)
        except Exception:
            pass

    @contextmanager
    def span(self, name: str, model: Optional[str] = None, inputs: Optional[dict] = None):
        rec = SpanRecord(seq=len(self.spans) + 1, name=name, model=model, inputs=inputs)
        self.spans.append(rec)
        self.emit("step", {"seq": rec.seq, "step": name, "status": "running", "model": model})
        t = time.perf_counter()
        try:
            yield rec
        except Exception as e:
            rec.status = "error"
            rec.error = f"{type(e).__name__}: {str(e)[:300]}"
            raise
        finally:
            rec.ended_at = datetime.now(timezone.utc)
            rec.duration_ms = int((time.perf_counter() - t) * 1000)
            self.emit("step", rec.public())

    def elapsed_s(self) -> float:
        return time.perf_counter() - self.t0

    @property
    def total_cost(self) -> float:
        return sum(s.cost_usd for s in self.spans)
