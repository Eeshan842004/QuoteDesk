"""The student's extraction schema: the single contract shared by datagen, the notebook, the backend, and eval.

Labeling rules (the ground truth follows these exactly; the teacher/verifier prompt restates them):
- intent: one of 5. A mixed-intent email is quote_request if any item is requested for a quote.
- urgency: "high" only for an explicit urgency cue (ASAP, urgent, emergency, unit down, rush) or a
  same/next-day deadline; "low" for explicit no-rush cues; otherwise "normal".
- needed_by: the deadline phrase exactly as written in the email, or null.
- items[].description: the exact words the customer used to name the part (without the quantity).
- items[].quantity: integer (number words converted, "a dozen" -> 12) or null if not stated.
- items[].unit: canonical unit (each|box|case|roll|pack|ft|tube|pair) only if a unit word is written
  next to the quantity; otherwise null.
- items[].part_number: a Northbeam SKU (NB-XXX-0000, however typed) exactly as written, or null. Size codes
  (A64, 4L500, 16x25x1) belong to the description. Never invented.
- items[].compatible_with: the equipment model exactly as written, or null.
- items[].reference: "previous_order" when the customer asks for the same thing as a past order, else null.
- missing_info (item order, then email-level):
    "quantity: <description>"         quote/return item with no quantity (not for previous_order items)
    "equipment_model: <description>"  part requested to fit equipment whose model is not given
    "size_or_spec: <description>"     part named too vaguely to pick one (e.g. "some ball valves")
    "order_number"                    order_status email with no order or PO reference
- product_question items always have quantity null. order_status and other have items [].
- The model never outputs prices.
"""
from __future__ import annotations

import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

INTENTS = ("quote_request", "order_status", "return_request", "product_question", "other")
URGENCIES = ("low", "normal", "high")
UNITS = ("each", "box", "case", "roll", "pack", "ft", "tube", "pair")

Intent = Literal["quote_request", "order_status", "return_request", "product_question", "other"]
Urgency = Literal["low", "normal", "high"]
Unit = Literal["each", "box", "case", "roll", "pack", "ft", "tube", "pair"]

MISSING_KINDS = ("quantity", "equipment_model", "size_or_spec", "order_number")
_NULLISH = {"", "null", "none", "n/a", "na", "nil"}
_UNIT_ALIASES = {"ea": "each", "pcs": "each", "pc": "each", "piece": "each", "pieces": "each", "unit": "each",
                 "units": "each", "boxes": "box", "bx": "box", "cases": "case", "cs": "case", "rolls": "roll",
                 "packs": "pack", "pk": "pack", "feet": "ft", "foot": "ft", "tubes": "tube", "pairs": "pair"}


def _nullish(v):
    """LLMs sometimes emit the string "null" / "" for a nullable field; treat those as JSON null."""
    if isinstance(v, str) and v.strip().lower() in _NULLISH:
        return None
    return v


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    quantity: Optional[int] = None
    unit: Optional[Unit] = None
    part_number: Optional[str] = None
    compatible_with: Optional[str] = None
    reference: Optional[Literal["previous_order"]] = None

    @field_validator("quantity", "part_number", "compatible_with", "reference", mode="before")
    @classmethod
    def _null_strings(cls, v):
        return _nullish(v)

    @field_validator("unit", mode="before")
    @classmethod
    def _canonical_unit(cls, v):
        v = _nullish(v)
        if isinstance(v, str):
            v = v.strip().lower().rstrip(".")
            v = _UNIT_ALIASES.get(v, v)
        return v


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    urgency: Urgency
    needed_by: Optional[str] = None
    items: list[LineItem] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)

    @field_validator("needed_by", mode="before")
    @classmethod
    def _null_strings(cls, v):
        return _nullish(v)

    @field_validator("items", "missing_info", mode="before")
    @classmethod
    def _null_list(cls, v):
        return [] if v is None else v


def to_target_json(extraction: Extraction | dict) -> str:
    """Compact, key-ordered JSON: the exact assistant string the student is trained to emit."""
    if isinstance(extraction, dict):
        extraction = Extraction.model_validate(extraction)
    return json.dumps(extraction.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def parse_extraction(text: str) -> tuple[Optional[Extraction], Optional[str]]:
    """Parse model output into an Extraction. Returns (extraction, None) or (None, error message)."""
    if text is None:
        return None, "empty output"
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None, "no JSON object found"
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e.msg} at pos {e.pos}"
    try:
        return Extraction.model_validate(data), None
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return None, f"schema error at {loc}: {first['msg']}"


def semantic_errors(e: Extraction) -> list[str]:
    """Checks beyond the schema (harness VALIDATE step and datagen label asserts)."""
    errs = []
    for i, it in enumerate(e.items):
        if it.quantity is not None and it.quantity <= 0:
            errs.append(f"items[{i}].quantity must be positive")
        if it.unit is not None and it.quantity is None:
            errs.append(f"items[{i}].unit given without quantity")
    if e.intent == "quote_request" and not e.items:
        errs.append("quote_request must have at least one item")
    if e.intent in ("order_status", "other") and e.items:
        errs.append(f"{e.intent} must have no items")
    if e.intent == "product_question" and any(it.quantity is not None for it in e.items):
        errs.append("product_question items must have quantity null")
    for m in e.missing_info:
        kind = m.split(":", 1)[0].strip()
        if kind not in MISSING_KINDS:
            errs.append(f"unknown missing_info kind: {kind!r}")
    return errs
