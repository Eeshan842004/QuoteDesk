"""Holds the live student model and hot-swaps it when a new version is promoted or rolled back."""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from ..config import get_settings
from .student import StudentModel

log = logging.getLogger("quotedesk.registry")


class ModelRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self.model: Optional[StudentModel] = None
        self.version: Optional[str] = None
        self.repo: Optional[str] = None
        self.state = "disabled"  # disabled | loading | ready | error
        self.error: Optional[str] = None
        self.load_seconds: Optional[float] = None

    def status(self) -> dict:
        return {"state": self.state, "version": self.version, "repo": self.repo, "error": self.error,
                "load_seconds": self.load_seconds}

    def load(self, repo: Optional[str], revision: Optional[str], local_path: Optional[str] = None) -> bool:
        """Load base + adapter; on success atomically swap. Returns True if the new model is live."""
        s = get_settings()
        if not (local_path or (repo and revision)):
            self.state = "disabled"
            return False
        prev_state = self.state
        self.state = "loading" if self.model is None else prev_state
        t0 = time.perf_counter()
        try:
            m = StudentModel(s.student_base_model, adapter=local_path or repo,
                             revision=None if local_path else revision, hf_token=s.hf_token,
                             max_new_tokens=s.student_max_new_tokens, quantize=s.student_quantize)
        except Exception as e:  # keep the old model if a swap fails
            log.exception("student load failed")
            self.error = f"{type(e).__name__}: {str(e)[:300]}"
            self.state = "ready" if self.model is not None else "error"
            return False
        with self._lock:
            self.model, self.version, self.repo = m, (revision or "local"), (local_path or repo)
            self.state, self.error = "ready", None
            self.load_seconds = round(time.perf_counter() - t0, 1)
        log.info("student %s@%s ready in %.1fs", self.repo, self.version, self.load_seconds)
        return True

    def get(self) -> Optional[StudentModel]:
        return self.model if self.state == "ready" else None


_registry = ModelRegistry()


def get_registry() -> ModelRegistry:
    return _registry
