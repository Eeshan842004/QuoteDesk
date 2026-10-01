"""Turn (scenario, written email) into the final training label, with hard code checks.

The structured fields (intent, urgency, quantity, unit, reference, missing_info) come from the scenario.
Only text spans (description, part number, equipment model, needed_by) come from the email, and each must be
a verbatim substring of the body. Any failed check drops the email.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from evallib.normalize import all_skus, find_ci, norm_code, norm_text, parse_quantity, unit_in_quantity_text
from evallib.schema import Extraction, semantic_errors

from . import world_vocab as V

EQUIP_RE = re.compile(r"\b(" + "|".join(code for _, code in V.EQUIPMENT_BRANDS) +
                      r")[\s\-]?[A-Z]{2,3}\d{1,3}[\s\-]?[0-9A-C]\b", re.I)
ORDER_RE = re.compile(r"\bNBO[\s\-]?\d{4,}\b|\bPO[\s#\-]*\d{3,}\b|#\s?\d{5}\b|\border\s+(?:no\.?\s*)?\d{5}\b", re.I)
_BRAND_RES = [re.compile(rf"(?<![A-Za-z]){re.escape(b)}(?![A-Za-z])", re.I) for b in V.REAL_BRANDS_STRICT]
MIN_BODY, MAX_BODY = 20, 5000


def real_brand_hits(text: str) -> list[str]:
    return [b for b, rx in zip(V.REAL_BRANDS_STRICT, _BRAND_RES) if rx.search(text)]


def build_label(sc: dict, written: dict) -> tuple[dict | None, list[str]]:
    """Returns (label, errors). label is None if any hard check fails."""
    errors: list[str] = []
    body = written.get("body") or ""
    if not (MIN_BODY <= len(body) <= MAX_BODY):
        errors.append(f"body length {len(body)} out of range")
    spans = {int(it["index"]): it["description"] for it in written.get("items", []) if it.get("description")}

    items = []
    for i, it in enumerate(sc["items"]):
        desc = spans.get(i)
        if not desc:
            errors.append(f"item {i}: writer returned no description span")
            continue
        actual = find_ci(body, desc.strip())
        if not actual:
            errors.append(f"item {i}: description span not in body")
            continue
        sim = fuzz.partial_ratio(norm_text(actual), norm_text(it["phrase"]))
        if sim < 50:
            errors.append(f"item {i}: description span '{actual}' too far from phrase '{it['phrase']}' ({sim:.0f})")
        pn = None
        if it["part_number_text"]:
            pn = find_ci(body, it["part_number_text"])
            if not pn:
                errors.append(f"item {i}: part number {it['part_number_text']!r} missing")
        model = None
        if it["equipment_model_text"]:
            model = find_ci(body, it["equipment_model_text"])
            if not model:
                errors.append(f"item {i}: equipment model {it['equipment_model_text']!r} missing")
        if it["quantity_text"]:
            if not find_ci(body, it["quantity_text"]):
                errors.append(f"item {i}: quantity text {it['quantity_text']!r} missing")
            assert parse_quantity(it["quantity_text"]) == it["quantity"], it
        items.append({
            "description": actual.strip(),
            "quantity": it["quantity"],
            "unit": unit_in_quantity_text(it["quantity_text"]) if it["quantity_text"] else None,
            "part_number": pn,
            "compatible_with": model,
            "reference": it["reference"],
        })

    needed_by = None
    if sc["needed_by"]:
        needed_by = find_ci(body, sc["needed_by"])
        if not needed_by:
            errors.append(f"needed_by phrase {sc['needed_by']!r} missing")

    if sc["order_ref"]:
        if not find_ci(body, sc["order_ref"]):
            errors.append(f"order ref {sc['order_ref']!r} missing")
    elif sc["intent"] == "order_status" and ORDER_RE.search(body):
        errors.append("order number present although scenario has none")

    # no stray SKUs or equipment models beyond the scenario's
    expected_skus = {norm_code(it["part_number_text"]) for it in sc["items"] if it["part_number_text"]}
    stray = [s for s in all_skus(body) if norm_code(s) not in expected_skus]
    if stray:
        errors.append(f"stray SKUs in body: {stray}")
    expected_models = {norm_code(it["equipment_model_text"]) for it in sc["items"] if it["equipment_model_text"]}
    stray_eq = [m.group(0) for m in EQUIP_RE.finditer(body) if norm_code(m.group(0)) not in expected_models]
    if stray_eq:
        errors.append(f"stray equipment models in body: {stray_eq}")
    brands = real_brand_hits(body + " " + (written.get("subject") or ""))
    if brands:
        errors.append(f"real brand names: {brands}")
    if errors:
        return None, errors

    missing = []
    for it, lab in zip(sc["items"], items):
        if sc["intent"] in ("quote_request", "return_request") and lab["quantity"] is None and lab["reference"] is None:
            missing.append(f"quantity: {lab['description']}")
        if "equipment_model" in it["missing"]:
            missing.append(f"equipment_model: {lab['description']}")
        if "size_or_spec" in it["missing"]:
            missing.append(f"size_or_spec: {lab['description']}")
    if sc["intent"] == "order_status" and not sc["order_ref"]:
        missing.append("order_number")

    label = {"intent": sc["intent"], "urgency": sc["urgency"], "needed_by": needed_by,
             "items": items if sc["intent"] not in ("order_status", "other") else [],
             "missing_info": missing}
    ext = Extraction.model_validate(label)
    sem = semantic_errors(ext)
    if sem:
        return None, [f"semantic: {e}" for e in sem]
    return ext.model_dump(mode="json"), []
