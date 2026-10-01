"""Teacher (Gemini 3.8 Flash via KIE, or Google direct): used for escalations, with a cache for the 8 demo samples."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from evallib.llm import LLMClient, LLMError, client_from_settings
from evallib.prompt import teacher_system_prompt, user_message
from evallib.runner import teacher_cost_usd
from evallib.schema import Extraction

from ..config import SAMPLES_DIR, get_settings


@dataclass
class TeacherOutput:
    text: str
    prompt_tokens: int
    output_tokens: int
    cost_usd: float
    credits: float
    latency_s: float
    cached: bool
    model: str
    cached_at: Optional[str] = None


class TeacherService:
    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[LLMClient] = None
        self.sample_cache: dict = {}
        p = SAMPLES_DIR / "teacher_cache.json"
        if p.exists():
            self.sample_cache = json.loads(p.read_text(encoding="utf-8"))

    @property
    def configured(self) -> bool:
        return self.settings.teacher_configured

    def client(self) -> LLMClient:
        if self._client is None:
            s = self.settings
            self._client = client_from_settings(s, s.teacher_model, max_attempts=1, timeout_s=s.request_timeout_s)
        return self._client

    def cached_for_sample(self, sample_id: Optional[str]) -> Optional[TeacherOutput]:
        c = self.sample_cache.get(sample_id or "")
        if not c:
            return None
        return TeacherOutput(text=c["text"], prompt_tokens=c.get("prompt_tokens", 0),
                             output_tokens=c.get("output_tokens", 0), cost_usd=0.0, credits=0.0,
                             latency_s=0.0, cached=True, model=c.get("model", self.settings.teacher_model),
                             cached_at=c.get("cached_at"))

    def estimate_cost_usd(self, sender: str, subject: str, body: str) -> float:
        prompt_tokens = (len(teacher_system_prompt()) + len(user_message(sender, subject, body))) / 3.5
        return teacher_cost_usd(int(prompt_tokens), 600)

    def extract(self, sender: str, subject: str, body: str, deadline_s: float) -> TeacherOutput:
        res = self.client().generate(teacher_system_prompt(), user_message(sender, subject, body), Extraction,
                                     tag="harness_escalation", use_cache=False, deadline_s=deadline_s)
        return TeacherOutput(text=json.dumps(res.parsed) if res.parsed else res.text,
                             prompt_tokens=res.prompt_tokens, output_tokens=res.billable_output_tokens,
                             cost_usd=teacher_cost_usd(res.prompt_tokens, res.billable_output_tokens),
                             credits=res.credits, latency_s=res.latency_s, cached=False, model=res.model)


@lru_cache(maxsize=1)
def get_teacher() -> TeacherService:
    return TeacherService()


__all__ = ["TeacherService", "TeacherOutput", "get_teacher", "LLMError"]
