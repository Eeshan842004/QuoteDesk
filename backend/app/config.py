"""Backend settings from environment variables (.env at the repo root is loaded in development)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
load_dotenv(REPO_ROOT / ".env")


def _first_existing(*candidates: Path) -> Path:
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


# In the repo: ../data and ../eval. In the container image both are copied under /app.
DATA_DIR = _first_existing(Path(os.getenv("QD_DATA_DIR", "/nonexistent")), REPO_ROOT / "data", BACKEND_DIR / "data")
EVAL_DIR = _first_existing(Path(os.getenv("QD_EVAL_DIR", "/nonexistent")), REPO_ROOT / "eval", BACKEND_DIR / "eval")
REPORTS_DIR = EVAL_DIR / "reports"
SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def _float(name: str, default: float | None) -> float | None:
    v = _env(name)
    return float(v) if v is not None else default


@dataclass
class Settings:
    # LLM / teacher
    provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "kie"))
    kie_api_key: str | None = field(default_factory=lambda: _env("KIE_API_KEY"))
    kie_base_url: str = field(default_factory=lambda: _env("KIE_BASE_URL", "https://api.kie.ai"))
    gemini_api_key: str | None = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    teacher_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3-8-flash"))
    thinking_level: str = field(default_factory=lambda: _env("GEMINI_THINKING_LEVEL", "low"))
    max_concurrency: int = 4
    min_interval_s: float = 0.0
    teacher_live_mode: str = field(default_factory=lambda: _env("TEACHER_LIVE_MODE", "admin_only"))

    # student
    hf_token: str | None = field(default_factory=lambda: _env("HF_TOKEN"))
    hf_model_repo: str | None = field(default_factory=lambda: _env("HF_MODEL_REPO"))
    student_base_model: str = field(default_factory=lambda: _env("STUDENT_BASE_MODEL", "unsloth/gemma-3-270m-it"))
    student_adapter_revision: str | None = field(default_factory=lambda: _env("STUDENT_ADAPTER_REVISION"))
    student_local_adapter: str | None = field(default_factory=lambda: _env("STUDENT_LOCAL_ADAPTER"))
    student_max_new_tokens: int = field(default_factory=lambda: int(_env("STUDENT_MAX_NEW_TOKENS", "384")))
    student_quantize: str | None = field(default_factory=lambda: _env("STUDENT_QUANTIZE"))  # None | "int8"
    load_student_on_startup: bool = field(default_factory=lambda: _env("LOAD_STUDENT_ON_STARTUP", "true") == "true")

    # harness
    router_threshold: float | None = field(default_factory=lambda: _float("ROUTER_CONFIDENCE_THRESHOLD", None))
    request_timeout_s: float = field(default_factory=lambda: float(_env("REQUEST_TIMEOUT_S", "30")))
    max_cost_per_request_usd: float = field(default_factory=lambda: float(_env("MAX_COST_PER_REQUEST_USD", "0.01")))
    max_email_chars: int = field(default_factory=lambda: int(_env("MAX_EMAIL_CHARS", "6000")))
    rate_limit: str = field(default_factory=lambda: _env("RATE_LIMIT", "10/minute"))

    # app
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'quotedesk.db'}"))
    admin_token: str | None = field(default_factory=lambda: _env("ADMIN_TOKEN"))
    allowed_origins: list[str] = field(default_factory=lambda: [o.strip() for o in _env(
        "ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()])

    # retraining
    retrain_threshold: int = field(default_factory=lambda: int(_env("RETRAIN_THRESHOLD", "20")))
    promotion_margin: float = field(default_factory=lambda: float(_env("PROMOTION_MARGIN", "0.0")))
    auto_retrain_enabled: bool = field(default_factory=lambda: _env("AUTO_RETRAIN_ENABLED", "false") == "true")
    kaggle_dataset_slug: str | None = field(default_factory=lambda: _env("KAGGLE_DATASET_SLUG"))
    kaggle_kernel_slug: str | None = field(default_factory=lambda: _env("KAGGLE_KERNEL_SLUG"))
    work_dir: Path = field(default_factory=lambda: Path(_env("QD_WORK_DIR", str(BACKEND_DIR / "work"))))

    @property
    def student_enabled(self) -> bool:
        return bool(self.student_local_adapter or (self.hf_model_repo and self.student_adapter_revision))

    @property
    def teacher_configured(self) -> bool:
        return bool(self.kie_api_key if self.provider == "kie" else self.gemini_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
