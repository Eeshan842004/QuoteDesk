"""The 8 curated demo emails (+ cached teacher outputs in teacher_cache.json, labelled 'cached' in the UI)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def list_samples() -> list[dict]:
    return json.loads((_DIR / "samples.json").read_text(encoding="utf-8"))


def get_sample(sample_id: str) -> Optional[dict]:
    return next((s for s in list_samples() if s["id"] == sample_id), None)
