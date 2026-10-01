"""Deterministic repair of the student's `missing_info` field (the harness NORMALIZE step).

The 270M student extracts items and quantities well but is unreliable at the *derived* field missing_info
(it lists "quantity" for items that have one and never emits order_number; see docs/DECISIONS.md D16).
Three kinds are rule-derivable from the extraction / email, so the harness recomputes them in code and
discards the student's own missing_info entries:
- "quantity: <description>":       quote/return item with quantity null and no previous_order reference
- "order_number":                  order_status email that contains no order or PO number
- "equipment_model: <description>": item with no compatible_with whose own line says it should fit something
                                   ("fits my unit", "for our furnace") but names no equipment model
"size_or_spec" needs judgement and is not derived (recall gap documented in docs/EVAL_REPORT.md).
"""
from __future__ import annotations

import re

from .schema import Extraction

ORDER_REF_RE = re.compile(r"\bNBO[\s\-]?\d{4,}\b|\border\s*(?:no\.?|number|#)?\s*#?\s*\d{5}\b|#\s?\d{5}\b", re.I)
PO_RE = re.compile(r"\bPO[\s#\-]*\d{3,}\b", re.I)
EQUIP_MODEL_RE = re.compile(r"\b(KVL|QMK|TVD|OSR|BSV|VTR|HSK|MRW)[\s\-]?[A-Z]{2,3}\d{1,3}[\s\-]?[0-9A-C]\b", re.I)
FIT_RE = re.compile(r"\b(fit|fits|fitting|compatible|goes? (in|on|with)|works? (in|on|with)|for (my|our|the|a|an))\b", re.I)


def has_order_reference(body: str) -> bool:
    return bool(ORDER_REF_RE.search(body or "") or PO_RE.search(body or ""))


def _line_of(body: str, needle: str) -> str | None:
    i = body.lower().find(needle.lower())
    if i < 0:
        return None
    start = body.rfind("\n", 0, i) + 1
    end = body.find("\n", i)
    return body[start: len(body) if end < 0 else end]


def derive_missing_info(ext: Extraction, body: str) -> list[str]:
    out: list[str] = []
    if ext.intent in ("quote_request", "return_request"):
        out += [f"quantity: {it.description}" for it in ext.items if it.quantity is None and it.reference is None]
    if ext.intent in ("quote_request", "return_request", "product_question"):
        for it in ext.items:
            if it.compatible_with:
                continue
            line = _line_of(body, it.description)
            if line and FIT_RE.search(line) and not EQUIP_MODEL_RE.search(line):
                out.append(f"equipment_model: {it.description}")
    if ext.intent == "order_status" and not has_order_reference(body):
        out.append("order_number")
    return out


def repair_missing_info(ext: Extraction, body: str) -> Extraction:
    """Return a copy of `ext` whose missing_info is derived from the extraction and the email."""
    return ext.model_copy(update={"missing_info": derive_missing_info(ext, body)})
