"""Promotion safety gate. A candidate is promoted only if, on the sealed exam split:
  1. item F1      >= current item F1 + PROMOTION_MARGIN
  2. JSON validity >= current JSON validity
  3. no intent class accuracy drops by more than 2 points
Otherwise it is REJECTED with the reasons stored.
"""
from __future__ import annotations

from typing import Optional

MAX_INTENT_DROP_POINTS = 2.0


def exam_metrics(report: dict) -> Optional[dict]:
    """Pull the exam-split metrics out of an eval report (notebook eval.json or run_eval output)."""
    if not report:
        return None
    splits = report.get("splits") or {}
    return splits.get("exam") or report.get("exam")


def evaluate_gate(current: Optional[dict], candidate: dict, margin: float) -> dict:
    checks, reasons = [], []
    if current is None:
        return {"passed": True, "checks": [{"name": "baseline", "ok": True,
                                            "detail": "no live model yet: first version is promoted"}], "reasons": []}

    def add(name, ok, detail):
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            reasons.append(detail)

    cf, nf = current.get("item_f1") or 0.0, candidate.get("item_f1") or 0.0
    add("item_f1", nf >= cf + margin, f"exam item F1 {nf:.4f} vs required {cf + margin:.4f} (current {cf:.4f} + margin {margin})")
    cv, nv = current.get("json_validity_rate") or 0.0, candidate.get("json_validity_rate") or 0.0
    add("json_validity", nv >= cv, f"JSON validity {nv:.4f} vs current {cv:.4f}")
    cur_int, new_int = current.get("per_intent_accuracy") or {}, candidate.get("per_intent_accuracy") or {}
    worst = None
    for intent, acc in cur_int.items():
        drop = 100 * (acc - new_int.get(intent, 0.0))
        if worst is None or drop > worst[1]:
            worst = (intent, drop)
        if drop > MAX_INTENT_DROP_POINTS:
            add(f"intent:{intent}", False, f"intent '{intent}' accuracy dropped {drop:.1f} points (max {MAX_INTENT_DROP_POINTS})")
    if worst is None or worst[1] <= MAX_INTENT_DROP_POINTS:
        checks.append({"name": "intent_classes", "ok": True,
                       "detail": f"largest intent drop {max(worst[1], 0.0) if worst else 0:.1f} points (max {MAX_INTENT_DROP_POINTS})"})
    return {"passed": not reasons, "checks": checks, "reasons": reasons}
