"""Gemini client used by datagen, eval (teacher baseline), and the backend (escalation).

Providers:
- "kie":    KIE.ai reseller, Gemini REST over SSE (`streamGenerateContent`). Structured output via
            `generationConfig.responseSchema` (OpenAPI subset). `responseJsonSchema` is ignored by KIE and
            non-streaming calls hang, so neither is used (see docs/DECISIONS.md D4).
- "google": official google-genai SDK with a (free) AI Studio key.

Features: thread-safe concurrency + pacing, retries with exponential backoff, content-hash cache,
JSONL cost log (tokens + KIE credits), and a hard credit cap.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Type

from pydantic import BaseModel, ValidationError


class LLMError(Exception):
    """Non-retryable LLM failure."""


class RetryableLLMError(LLMError):
    pass


class CreditsExhausted(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


@dataclass
class LLMResult:
    text: str
    parsed: Optional[dict]
    model: str
    provider: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    credits: float = 0.0
    latency_s: float = 0.0
    ttft_s: Optional[float] = None
    cached: bool = False
    attempts: int = 1

    @property
    def billable_output_tokens(self) -> int:
        """Google bills thinking tokens as output tokens."""
        return self.output_tokens + self.thought_tokens


# ------------------------------------------------------------------ schema conversion

def to_gemini_schema(model_cls: Type[BaseModel]) -> dict:
    """Pydantic model -> Gemini OpenAPI-subset schema (uppercase types, nullable, enum, propertyOrdering).

    Every property is marked required (nullable where optional) so the model always emits full objects.
    """
    js = model_cls.model_json_schema()
    defs = js.get("$defs", {})

    def conv(node: dict) -> dict:
        if "$ref" in node:
            return conv(defs[node["$ref"].split("/")[-1]])
        desc = node.get("description")
        if "anyOf" in node:
            options = [n for n in node["anyOf"] if n.get("type") != "null"]
            nullable = len(options) < len(node["anyOf"])
            out = conv(options[0]) if len(options) == 1 else {"anyOf": [conv(o) for o in options]}
            if nullable:
                out["nullable"] = True
        elif "enum" in node or "const" in node:
            values = node.get("enum") or [node["const"]]
            out = {"type": "STRING", "enum": [str(v) for v in values]}
        else:
            t = node.get("type")
            if t == "object":
                props = {k: conv(v) for k, v in node.get("properties", {}).items()}
                out = {"type": "OBJECT", "properties": props, "required": list(props), "propertyOrdering": list(props)}
            elif t == "array":
                out = {"type": "ARRAY", "items": conv(node.get("items", {"type": "string"}))}
            elif t in ("string", "integer", "number", "boolean"):
                out = {"type": t.upper()}
            else:
                out = {"type": "STRING"}
        if desc:
            out["description"] = desc
        return out

    return conv(js)


def _has_nullable(node: Any) -> bool:
    if isinstance(node, dict):
        return bool(node.get("nullable")) or any(_has_nullable(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_nullable(v) for v in node)
    return False


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def _extract_json_text(text: str) -> str:
    t = _FENCE.sub("", text.strip())
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    return t[start:] if start > 0 else t


# ------------------------------------------------------------------ client

@dataclass
class LLMClient:
    provider: str
    model: str
    kie_api_key: Optional[str] = None
    kie_base_url: str = "https://api.kie.ai"
    gemini_api_key: Optional[str] = None
    thinking_level: Optional[str] = "low"
    max_concurrency: int = 4
    min_interval_s: float = 0.6
    cache_dir: Optional[Path] = None
    cost_log: Optional[Path] = None
    max_credits: Optional[float] = None
    timeout_s: float = 180.0
    max_attempts: int = 5
    credits_spent: float = 0.0
    _sem: threading.Semaphore = field(init=False, repr=False)
    _pace_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _log_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _last_start: float = field(default=0.0, init=False, repr=False)
    _local: threading.local = field(default_factory=threading.local, init=False, repr=False)

    def __post_init__(self):
        self._sem = threading.Semaphore(self.max_concurrency)
        if self.provider == "kie" and not self.kie_api_key:
            raise LLMError("KIE_API_KEY is not set")
        if self.provider == "google" and not self.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        if self.provider not in ("kie", "google"):
            raise LLMError(f"unknown provider {self.provider!r}")
        if self.cache_dir:
            Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    # ---- public API
    def generate(self, system: str, user: str, schema: Optional[Type[BaseModel]] = None, *, tag: str = "",
                 use_cache: bool = True, temperature: Optional[float] = None,
                 max_output_tokens: Optional[int] = None, deadline_s: Optional[float] = None) -> LLMResult:
        """deadline_s: hard wall-clock limit for this call (KIE provider); raises LLMError when exceeded."""
        self._local.deadline = (time.time() + deadline_s) if deadline_s else None
        key = self._cache_key(system, user, schema, temperature)
        if use_cache and self.cache_dir:
            hit = self._cache_get(key, schema)
            if hit:
                self._log(tag, hit, ok=True)
                return hit
        if self.max_credits is not None and self.credits_spent >= self.max_credits:
            raise BudgetExceeded(f"credit cap reached: spent {self.credits_spent:.2f} >= {self.max_credits}")

        last_err: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with self._sem:
                    self._pace()
                    res = (self._call_kie if self.provider == "kie" else self._call_google)(
                        system, user, schema, temperature, max_output_tokens)
                res.attempts = attempt
                self.credits_spent += res.credits
                if schema is not None:
                    try:
                        res.parsed = schema.model_validate_json(_extract_json_text(res.text)).model_dump(mode="json")
                    except (ValidationError, ValueError) as e:
                        self._log(tag, res, ok=False, error=f"schema: {str(e)[:200]}")
                        raise RetryableLLMError(f"response failed schema validation: {str(e)[:300]}")
                self._log(tag, res, ok=True)
                if use_cache and self.cache_dir:
                    self._cache_put(key, res)
                return res
            except (CreditsExhausted, BudgetExceeded):
                raise
            except RetryableLLMError as e:
                last_err = e
                if not str(e).startswith("response failed schema validation"):
                    self._log(tag, None, ok=False, error=f"attempt {attempt}: {str(e)[:250]}")
                if attempt == self.max_attempts:
                    break
                dl = getattr(self._local, "deadline", None)
                if dl is not None and time.time() >= dl:
                    break
                sleep = min(60.0, 2 ** attempt) + random.uniform(0, 1.5)
                if dl is not None:
                    sleep = min(sleep, max(0.0, dl - time.time()))
                if "429" in str(e):
                    sleep = max(sleep, 10.0)
                time.sleep(sleep)
        self._log(tag, None, ok=False, error=str(last_err)[:300])
        raise LLMError(f"gave up after {self.max_attempts} attempts: {last_err}")

    def balance(self) -> Optional[float]:
        """Remaining KIE credits (None for other providers or on error)."""
        if self.provider != "kie":
            return None
        import httpx
        try:
            r = httpx.get(f"{self.kie_base_url}/api/v1/chat/credit",
                          headers={"Authorization": f"Bearer {self.kie_api_key}"}, timeout=30)
            data = r.json()
            return float(data["data"]) if data.get("code") == 200 else None
        except Exception:
            return None

    # ---- providers
    def _client(self):
        import httpx
        c = getattr(self._local, "client", None)
        if c is None:
            c = httpx.Client(timeout=httpx.Timeout(connect=20, read=self.timeout_s, write=30, pool=60))
            self._local.client = c
        return c

    def _call_kie(self, system, user, schema, temperature, max_output_tokens) -> LLMResult:
        import httpx
        gen: dict[str, Any] = {}
        if schema is not None:
            gen["responseMimeType"] = "application/json"
            gschema = to_gemini_schema(schema)
            # KIE ignores `nullable` (the model is forced to emit "" instead of null) and anyOf+NULL breaks, so
            # schemas with nullable fields use plain JSON mode; the prompt carries the format and pydantic validates.
            if not _has_nullable(gschema):
                gen["responseSchema"] = gschema
        if self.thinking_level:
            gen["thinkingConfig"] = {"thinkingLevel": self.thinking_level, "includeThoughts": False}
        if temperature is not None:
            gen["temperature"] = temperature
        if max_output_tokens:
            gen["maxOutputTokens"] = max_output_tokens
        body = {"stream": True, "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{self.kie_base_url}/gemini/v1/models/{self.model}:streamGenerateContent"
        headers = {"Authorization": f"Bearer {self.kie_api_key}", "Content-Type": "application/json",
                   "Accept": "text/event-stream"}
        t0 = time.time()
        deadline = getattr(self._local, "deadline", None)
        req_timeout = None
        if deadline is not None:
            remaining = deadline - t0
            if remaining <= 0:
                raise LLMError("deadline exceeded before the call")
            req_timeout = httpx.Timeout(connect=min(10.0, remaining), read=remaining, write=10.0, pool=10.0)
        text_parts: list[str] = []
        usage: dict = {}
        credits = 0.0
        ttft = None
        finish = None
        try:
            kwargs = {"timeout": req_timeout} if req_timeout is not None else {}
            with self._client().stream("POST", url, json=body, headers=headers, **kwargs) as r:
                if r.status_code != 200:
                    raw = r.read().decode(errors="replace")[:500]
                    self._raise_for_status(r.status_code, raw)
                ctype = r.headers.get("content-type", "")
                if "event-stream" not in ctype:
                    raw = r.read().decode(errors="replace")
                    self._raise_for_body(raw)
                for line in r.iter_lines():
                    if deadline is not None and time.time() > deadline:
                        raise LLMError("deadline exceeded while streaming")
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if "error" in chunk:
                        self._raise_for_body(json.dumps(chunk))
                    if isinstance(chunk.get("code"), int) and chunk["code"] != 200 and "candidates" not in chunk:
                        self._raise_for_body(json.dumps(chunk))
                    for cand in chunk.get("candidates", []) or []:
                        finish = cand.get("finishReason") or finish
                        for part in (cand.get("content") or {}).get("parts", []) or []:
                            if part.get("thought"):
                                continue
                            if "text" in part:
                                if ttft is None:
                                    ttft = time.time() - t0
                                text_parts.append(part["text"])
                    if "usageMetadata" in chunk:
                        usage = chunk["usageMetadata"]
                    if "credits_consumed" in chunk:
                        try:
                            credits = float(chunk["credits_consumed"])
                        except (TypeError, ValueError):
                            pass
        except httpx.TimeoutException as e:
            raise RetryableLLMError(f"timeout: {e}")
        except httpx.TransportError as e:
            raise RetryableLLMError(f"network: {e}")
        text = "".join(text_parts)
        if finish == "MAX_TOKENS":
            raise RetryableLLMError("truncated output (MAX_TOKENS)")
        if not text.strip():
            raise RetryableLLMError(f"empty response (finish={finish})")
        return LLMResult(text=text, parsed=None, model=self.model, provider="kie",
                         prompt_tokens=int(usage.get("promptTokenCount", 0) or 0),
                         output_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
                         thought_tokens=int(usage.get("thoughtsTokenCount", 0) or 0),
                         credits=credits, latency_s=time.time() - t0, ttft_s=ttft)

    def _call_google(self, system, user, schema, temperature, max_output_tokens) -> LLMResult:
        from google import genai
        from google.genai import errors, types
        client = getattr(self._local, "gclient", None)
        if client is None:
            client = genai.Client(api_key=self.gemini_api_key)
            self._local.gclient = client
        cfg: dict[str, Any] = {"system_instruction": system or None}
        if schema is not None:
            cfg["response_mime_type"] = "application/json"
            cfg["response_schema"] = schema
        if self.thinking_level:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_level=self.thinking_level)
        if temperature is not None:
            cfg["temperature"] = temperature
        if max_output_tokens:
            cfg["max_output_tokens"] = max_output_tokens
        t0 = time.time()
        try:
            resp = client.models.generate_content(model=self.model, contents=user,
                                                  config=types.GenerateContentConfig(**cfg))
        except errors.APIError as e:
            code = getattr(e, "code", 0) or 0
            if code in (429, 500, 502, 503, 504):
                raise RetryableLLMError(f"{code}: {e}")
            raise LLMError(f"{code}: {e}")
        um = resp.usage_metadata
        return LLMResult(text=resp.text or "", parsed=None, model=self.model, provider="google",
                         prompt_tokens=(um.prompt_token_count or 0) if um else 0,
                         output_tokens=(um.candidates_token_count or 0) if um else 0,
                         thought_tokens=(um.thoughts_token_count or 0) if um else 0,
                         credits=0.0, latency_s=time.time() - t0, ttft_s=None)

    # ---- helpers
    @staticmethod
    def _raise_for_status(status: int, raw: str):
        if status == 402:
            raise CreditsExhausted(f"402 insufficient credits: {raw}")
        if status == 429 or status >= 500:
            raise RetryableLLMError(f"{status}: {raw}")
        raise LLMError(f"HTTP {status}: {raw}")

    def _raise_for_body(self, raw: str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise RetryableLLMError(f"unexpected non-stream body: {raw[:300]}")
        code = data.get("code") or (data.get("error") or {}).get("code")
        msg = data.get("msg") or (data.get("error") or {}).get("message") or raw[:300]
        if code == 402:
            raise CreditsExhausted(f"402 insufficient credits: {msg}")
        if code in (429, 455, 500, 502, 503, 505) or code is None:
            raise RetryableLLMError(f"{code}: {msg}")
        raise LLMError(f"{code}: {msg}")

    def _pace(self):
        with self._pace_lock:
            wait = self._last_start + self.min_interval_s - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last_start = time.time()

    def _cache_key(self, system, user, schema, temperature) -> str:
        schema_repr = json.dumps(to_gemini_schema(schema), sort_keys=True) if schema else ""
        raw = json.dumps([self.provider, self.model, system, user, schema_repr, self.thinking_level, temperature])
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_get(self, key, schema) -> Optional[LLMResult]:
        p = Path(self.cache_dir) / f"{key}.json"
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            res = LLMResult(**d)
            if schema is not None:
                res.parsed = schema.model_validate_json(_extract_json_text(res.text)).model_dump(mode="json")
            res.cached = True
            return res
        except Exception:
            return None

    def _cache_put(self, key, res: LLMResult):
        p = Path(self.cache_dir) / f"{key}.json"
        d = asdict(res)
        d["parsed"] = None
        d["cached"] = False
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    def _log(self, tag: str, res: Optional[LLMResult], ok: bool, error: str | None = None):
        if not self.cost_log:
            return
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": tag, "provider": self.provider, "model": self.model,
               "ok": ok, "error": error}
        if res is not None:
            rec.update(prompt_tokens=res.prompt_tokens, output_tokens=res.output_tokens,
                       thought_tokens=res.thought_tokens, credits=0.0 if res.cached else res.credits,
                       latency_s=round(res.latency_s, 2), ttft_s=round(res.ttft_s, 2) if res.ttft_s else None,
                       cached=res.cached, attempts=res.attempts)
        with self._log_lock:
            Path(self.cost_log).parent.mkdir(parents=True, exist_ok=True)
            with open(self.cost_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")


def client_from_settings(settings, model: str, *, cache_dir=None, cost_log=None, max_credits=None,
                         provider: str | None = None, **kw) -> LLMClient:
    """Build a client from a settings object (datagen.config.LLMSettings or backend settings)."""
    return LLMClient(provider=provider or settings.provider, model=model,
                     kie_api_key=getattr(settings, "kie_api_key", None),
                     kie_base_url=getattr(settings, "kie_base_url", "https://api.kie.ai"),
                     gemini_api_key=getattr(settings, "gemini_api_key", None),
                     thinking_level=getattr(settings, "thinking_level", "low"),
                     max_concurrency=getattr(settings, "max_concurrency", 4),
                     min_interval_s=getattr(settings, "min_interval_s", 0.6),
                     cache_dir=cache_dir, cost_log=cost_log, max_credits=max_credits, **kw)
