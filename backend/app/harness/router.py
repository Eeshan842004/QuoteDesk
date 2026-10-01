"""Router: confidence of a student extraction and the escalate decision.

confidence = exp(mean token log-prob) x validity x completeness
- validity: 0 if the output fails schema or semantic validation, else 1
- completeness: quote/return items without a quantity should be listed in missing_info
The threshold comes from the calibration sweep on val (eval/run_eval.py calibrate), never guessed.
"""
from __future__ import annotations

import math
from typing import Optional

from evallib.normalize import norm_text
from evallib.schema import Extraction


def confidence(mean_logprob: Optional[float], ext: Optional[Extraction], errors: list[str]) -> dict:
    if ext is None or errors or mean_logprob is None:
        return {"score": 0.0, "token_prob": math.exp(mean_logprob) if mean_logprob is not None else None,
                "validity": 0.0, "completeness": None}
    token_prob = math.exp(mean_logprob)
    need = [it for it in ext.items if it.quantity is None and it.reference is None] \
        if ext.intent in ("quote_request", "return_request") else []
    listed = {norm_text(m.split(":", 1)[1]) for m in ext.missing_info if m.startswith("quantity:")}
    covered = sum(1 for it in need if norm_text(it.description) in listed)
    completeness = 1.0 if not need else 0.5 + 0.5 * covered / len(need)
    return {"score": round(token_prob * completeness, 4), "token_prob": round(token_prob, 4), "validity": 1.0,
            "completeness": round(completeness, 3)}


def should_escalate(conf: dict, threshold: Optional[float]) -> tuple[bool, str]:
    if conf["validity"] == 0.0:
        return True, "student output invalid after repair"
    if threshold is None:
        return False, "threshold not calibrated yet: escalating only invalid outputs"
    if conf["score"] < threshold:
        return True, f"confidence {conf['score']:.3f} < threshold {threshold:.3f}"
    return False, f"confidence {conf['score']:.3f} >= threshold {threshold:.3f}"
