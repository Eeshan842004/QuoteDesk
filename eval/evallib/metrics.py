"""Evaluation metrics shared by the notebook, the backend, and eval/run_eval.py.

Per email we compare the ground-truth label with a model's raw text output:
- json_valid: output parses into the schema (and passes semantic checks)
- intent / urgency correctness
- items: Hungarian match on description similarity (token_set_ratio >= DESC_MATCH on normalized text).
  A predicted item is a true positive when it is matched AND its quantity is equal (spec: "match items by
  description similarity and quantity").
- quantity accuracy: share of description-matched pairs with equal quantity
- missing_info: match by kind (quantity / equipment_model / size_or_spec / order_number) + description similarity
- exact match: every field equal (text fields compared normalized)
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Optional

from rapidfuzz import fuzz

from .normalize import norm_code, norm_text
from .schema import INTENTS, parse_extraction, semantic_errors

DESC_MATCH = 80


def _sim(a: Optional[str], b: Optional[str]) -> float:
    return fuzz.token_set_ratio(norm_text(a), norm_text(b))


def align(truth_items: list[dict], pred_items: list[dict]) -> list[tuple[int, int, float]]:
    """Maximum-similarity one-to-one matching (Hungarian). Returns (truth_idx, pred_idx, sim) pairs."""
    if not truth_items or not pred_items:
        return []
    try:
        from scipy.optimize import linear_sum_assignment
        import numpy as np
        m = np.array([[_item_sim(t, p) for p in pred_items] for t in truth_items])
        rows, cols = linear_sum_assignment(-m)
        return [(int(r), int(c), float(m[r, c])) for r, c in zip(rows, cols)]
    except ImportError:  # greedy fallback
        pairs = sorted(((_item_sim(t, p), i, j) for i, t in enumerate(truth_items) for j, p in enumerate(pred_items)),
                       reverse=True)
        used_t, used_p, out = set(), set(), []
        for s, i, j in pairs:
            if i not in used_t and j not in used_p:
                used_t.add(i)
                used_p.add(j)
                out.append((i, j, s))
        return out


def _item_sim(t: dict, p: dict) -> float:
    s = _sim(t["description"], p["description"])
    if t.get("part_number") and norm_code(t["part_number"]) == norm_code(p.get("part_number")):
        s = max(s, 95.0)
    return s


def _missing_pairs(items: list[str]) -> list[tuple[str, str]]:
    out = []
    for m in items:
        kind, _, desc = m.partition(":")
        out.append((kind.strip(), desc.strip()))
    return out


def _match_missing(truth: list[str], pred: list[str]) -> int:
    t, p = _missing_pairs(truth), _missing_pairs(pred)
    used, tp = set(), 0
    for kind, desc in t:
        for j, (pk, pd) in enumerate(p):
            if j in used or pk != kind:
                continue
            if not desc or not pd or _sim(desc, pd) >= DESC_MATCH:
                used.add(j)
                tp += 1
                break
    return tp


def score_one(truth: dict, pred_text: Optional[str]) -> dict:
    """Score one prediction against the truth label (dict in the Extraction schema)."""
    ext, err = parse_extraction(pred_text) if pred_text is not None else (None, "no output")
    n_true = len(truth["items"])
    r = {"json_valid": False, "parse_error": err, "intent_true": truth["intent"], "intent_pred": None,
         "intent_ok": False, "urgency_ok": False, "needed_by_ok": False,
         "item_tp": 0, "item_fp": 0, "item_fn": n_true, "qty_pairs": 0, "qty_ok": 0,
         "pn_pairs": 0, "pn_ok": 0, "compat_pairs": 0, "compat_ok": 0,
         "missing_tp": 0, "missing_fp": 0, "missing_fn": len(truth["missing_info"]), "exact": False,
         "pred": None}
    if ext is None:
        return r
    pred = ext.model_dump(mode="json")
    r["pred"] = pred
    r["json_valid"] = not semantic_errors(ext)
    r["intent_pred"] = pred["intent"]
    r["intent_ok"] = pred["intent"] == truth["intent"]
    r["urgency_ok"] = pred["urgency"] == truth["urgency"]
    r["needed_by_ok"] = norm_text(pred["needed_by"]) == norm_text(truth["needed_by"])

    pairs = [(i, j, s) for i, j, s in align(truth["items"], pred["items"]) if s >= DESC_MATCH]
    tp = 0
    fields_equal = len(pairs) == n_true == len(pred["items"])
    for i, j, _ in pairs:
        t, p = truth["items"][i], pred["items"][j]
        r["qty_pairs"] += 1
        if t["quantity"] == p["quantity"]:
            r["qty_ok"] += 1
            tp += 1
        if t.get("part_number") or p.get("part_number"):
            r["pn_pairs"] += 1
            r["pn_ok"] += norm_code(t.get("part_number")) == norm_code(p.get("part_number"))
        if t.get("compatible_with") or p.get("compatible_with"):
            r["compat_pairs"] += 1
            r["compat_ok"] += norm_code(t.get("compatible_with")) == norm_code(p.get("compatible_with"))
        same = (t["quantity"] == p["quantity"] and t.get("unit") == p.get("unit")
                and norm_code(t.get("part_number")) == norm_code(p.get("part_number"))
                and norm_code(t.get("compatible_with")) == norm_code(p.get("compatible_with"))
                and t.get("reference") == p.get("reference")
                and norm_text(t["description"]) == norm_text(p["description"]))
        fields_equal = fields_equal and same
    r["item_tp"], r["item_fp"], r["item_fn"] = tp, len(pred["items"]) - tp, n_true - tp

    mtp = _match_missing(truth["missing_info"], pred["missing_info"])
    r["missing_tp"], r["missing_fp"], r["missing_fn"] = mtp, len(pred["missing_info"]) - mtp, len(truth["missing_info"]) - mtp
    r["exact"] = bool(r["json_valid"] and r["intent_ok"] and r["urgency_ok"] and r["needed_by_ok"] and fields_equal
                      and mtp == len(truth["missing_info"]) == len(pred["missing_info"]))
    return r


def _f1(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    rec = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * rec / (p + rec) if p + rec else 0.0
    return p, rec, f


def percentile(values: list[float], q: float) -> Optional[float]:
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] if lo == hi else v[lo] + (v[hi] - v[lo]) * (k - lo)


def aggregate(scores: list[dict], latencies: Iterable[Optional[float]] = (), escalated: Iterable[bool] = (),
              costs_usd: Iterable[Optional[float]] = ()) -> dict:
    n = len(scores)
    s = lambda k: sum(x[k] for x in scores)  # noqa: E731
    ip, ir, if1 = _f1(s("item_tp"), s("item_fp"), s("item_fn"))
    mp, mr, mf1 = _f1(s("missing_tp"), s("missing_fp"), s("missing_fn"))
    per_intent = defaultdict(lambda: [0, 0])
    for x in scores:
        per_intent[x["intent_true"]][0] += x["intent_ok"]
        per_intent[x["intent_true"]][1] += 1
    lat = [l for l in latencies if l is not None]
    esc = list(escalated)
    costs = [c for c in costs_usd if c is not None]
    out = {
        "n": n,
        "intent_accuracy": s("intent_ok") / n if n else None,
        "json_validity_rate": s("json_valid") / n if n else None,
        "item_precision": ip, "item_recall": ir, "item_f1": if1,
        "quantity_accuracy": s("qty_ok") / s("qty_pairs") if s("qty_pairs") else None,
        "part_number_accuracy": s("pn_ok") / s("pn_pairs") if s("pn_pairs") else None,
        "compatible_with_accuracy": s("compat_ok") / s("compat_pairs") if s("compat_pairs") else None,
        "missing_info_precision": mp, "missing_info_recall": mr, "missing_info_f1": mf1,
        "urgency_accuracy": s("urgency_ok") / n if n else None,
        "exact_match_rate": s("exact") / n if n else None,
        "per_intent_accuracy": {k: v[0] / v[1] for k, v in sorted(per_intent.items())},
        "per_intent_n": {k: v[1] for k, v in sorted(per_intent.items())},
        "latency_p50_s": percentile(lat, 50), "latency_p95_s": percentile(lat, 95),
        "escalation_rate": (sum(esc) / len(esc)) if esc else None,
        "cost_per_1k_usd": (1000 * sum(costs) / len(costs)) if costs else None,
    }
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def intent_drop(current: dict, candidate: dict) -> dict:
    """Per-intent accuracy change (points) from current to candidate; used by the promotion gate."""
    cur, new = current.get("per_intent_accuracy", {}), candidate.get("per_intent_accuracy", {})
    return {k: round(100 * (new.get(k, 0.0) - cur[k]), 2) for k in cur if k in INTENTS}
