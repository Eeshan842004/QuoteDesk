"""Paths and settings for datagen/eval scripts. Values come from environment variables (.env is loaded)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
GEN_DIR = DATA_DIR / "generated"
SPLITS_DIR = DATA_DIR / "splits"
CACHE_DIR = GEN_DIR / "cache"
BUNDLE_DIR = DATA_DIR / "kaggle_bundle"
EVAL_DIR = ROOT / "eval"

load_dotenv(ROOT / ".env")

# make `import evallib` work when running `python -m datagen.xxx`
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v not in (None, "") else default


@dataclass
class LLMSettings:
    provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "kie"))
    kie_api_key: str | None = field(default_factory=lambda: _env("KIE_API_KEY"))
    kie_base_url: str = field(default_factory=lambda: _env("KIE_BASE_URL", "https://api.kie.ai"))
    gemini_api_key: str | None = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    teacher_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3-8-flash"))
    datagen_model: str = field(default_factory=lambda: _env("GEMINI_DATAGEN_MODEL", "gemini-3-8-flash"))
    verify_model: str = field(default_factory=lambda: _env("GEMINI_VERIFY_MODEL", "gemini-3-7-flash"))
    thinking_level: str = field(default_factory=lambda: _env("GEMINI_THINKING_LEVEL", "low"))
    max_concurrency: int = field(default_factory=lambda: int(_env("LLM_MAX_CONCURRENCY", "4")))
    min_interval_s: float = field(default_factory=lambda: float(_env("LLM_MIN_INTERVAL_S", "0.6")))
    max_credits: float | None = field(
        default_factory=lambda: float(_env("DATAGEN_MAX_CREDITS")) if _env("DATAGEN_MAX_CREDITS") else None)


@dataclass
class DatagenSettings:
    batch_size: int = field(default_factory=lambda: int(_env("DATAGEN_BATCH_SIZE", "5")))
    seed: int = field(default_factory=lambda: int(_env("DATAGEN_SEED", "42")))
    n_scenarios: int = 1800
    verify_batch_size: int = 10
