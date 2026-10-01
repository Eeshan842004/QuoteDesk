"""Step 3: verify each written email.

1. Code checks + label construction (datagen.labels.build_label).
2. An independent Gemini call (a different model) extracts from the email ALONE; hard fields must agree
   with the ground truth: intent, item count, each quantity, part numbers, compatible_with.
   Soft fields (urgency, needed_by, unit, reference, missing_info, description wording) are logged only.

    python -m datagen.verify            # writes verified.jsonl, dropped.jsonl, verify_report.json
Resumable: emails already verified or dropped are skipped.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from pydantic import BaseModel
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

from evallib.llm import BudgetExceeded, CreditsExhausted, LLMError, client_from_settings
from evallib.normalize import canonical_sku, norm_code, norm_text
from evallib.prompt import teacher_system_prompt, user_message
from evallib.schema import Extraction, to_target_json

from .config import CACHE_DIR, GEN_DIR, DatagenSettings, LLMSettings
from .labels import build_label
from .write_emails import COST_LOG, EMAILS_PATH, load_jsonl, load_scenarios

VERIFIED_PATH = GEN_DIR / "verified.jsonl"
DROPPED_PATH = GEN_DIR / "dropped.jsonl"
REPORT_PATH = GEN_DIR / "verify_report.json"


class VerifiedOne(BaseModel):
    id: str
    extraction: Extraction


class VerifyBatch(BaseModel):
    results: list[VerifiedOne]


def sender_of(sc: dict) -> str:
    return f"{sc['sender_name']} <{sc['sender_email']}>"


def verifier_user_message(records: list[dict]) -> str:
    parts = ["Extract each email below independently, following the rules. Reply with ONE JSON object of the form "
             '{"results": [{"id": "<id>", "extraction": <extraction object in the output format>}, ...]} '
             "with one result per email, same ids, same order."]
    for r in records:
        parts.append(f"### id={r['scenario_id']}\n{user_message(r['sender'], r['subject'], r['body'])}")
    return "\n\n".join(parts)


def align_items(truth: list[dict], pred: list[dict]) -> list[tuple[int, int, float]]:
    """Hungarian matching on description similarity. Returns (truth_idx, pred_idx, similarity 0-100)."""
    if not truth or not pred:
        return []
    sim = np.zeros((len(truth), len(pred)))
    for i, t in enumerate(truth):
        for j, p in enumerate(pred):
            s = fuzz.token_set_ratio(norm_text(t["description"]), norm_text(p["description"]))
            if t.get("part_number") and norm_code(t["part_number"]) == norm_code(p.get("part_number")):
                s = max(s, 95)
            sim[i, j] = s
    rows, cols = linear_sum_assignment(-sim)
    return [(int(r), int(c), float(sim[r, c])) for r, c in zip(rows, cols)]


def compare(truth: dict, pred: dict) -> tuple[list[str], list[str]]:
    """Returns (hard_diffs, soft_diffs)."""
    hard, soft = [], []
    if truth["intent"] != pred["intent"]:
        hard.append(f"intent {truth['intent']} != {pred['intent']}")
    if len(truth["items"]) != len(pred["items"]):
        hard.append(f"item count {len(truth['items'])} != {len(pred['items'])}")
    for ti, pi, s in align_items(truth["items"], pred["items"]):
        t, p = truth["items"][ti], pred["items"][pi]
        if s < 40:
            hard.append(f"item {ti} unmatched ({t['description']!r} vs {p['description']!r})")
            continue
        if t["quantity"] != p["quantity"]:
            hard.append(f"item {ti} quantity {t['quantity']} != {p['quantity']}")
        if norm_code(t["part_number"]) != norm_code(p["part_number"]):
            # a non-SKU "part number" (e.g. a belt size code) is a soft wording difference
            if t["part_number"] or canonical_sku(p["part_number"]):
                hard.append(f"item {ti} part_number {t['part_number']} != {p['part_number']}")
            else:
                soft.append("part_number_non_sku")
        if norm_code(t["compatible_with"]) != norm_code(p["compatible_with"]):
            hard.append(f"item {ti} compatible_with {t['compatible_with']} != {p['compatible_with']}")
        if t["unit"] != p["unit"]:
            soft.append("unit")
        if t["reference"] != p["reference"]:
            soft.append("reference")
        if norm_text(t["description"]) != norm_text(p["description"]):
            soft.append("description_wording")
    if truth["urgency"] != pred["urgency"]:
        soft.append("urgency")
    if norm_text(truth["needed_by"]) != norm_text(pred["needed_by"]):
        soft.append("needed_by")
    kinds = lambda m: sorted(x.split(":")[0].strip() for x in m)  # noqa: E731
    if kinds(truth["missing_info"]) != kinds(pred["missing_info"]):
        soft.append("missing_info")
    return hard, soft


def make_verify_client():
    s = LLMSettings()
    return client_from_settings(s, s.verify_model, cache_dir=CACHE_DIR, cost_log=COST_LOG, max_credits=s.max_credits)


def verify(scenario_ids: set | None = None, client=None, batch_size: int | None = None, tag: str = "verify") -> dict:
    scenarios = {s["scenario_id"]: s for s in load_scenarios()}
    emails = load_jsonl(EMAILS_PATH)
    done = {r["scenario_id"] for r in load_jsonl(VERIFIED_PATH)} | {r["scenario_id"] for r in load_jsonl(DROPPED_PATH)}
    todo = [e for e in emails if e["scenario_id"] not in done and (scenario_ids is None or e["scenario_id"] in scenario_ids)]
    # dedupe (a scenario may have been written twice after a partial batch)
    seen, uniq = set(), []
    for e in todo:
        if e["scenario_id"] not in seen:
            seen.add(e["scenario_id"])
            uniq.append(e)
    lock = threading.Lock()
    stats = Counter()

    def drop(rec, stage, reasons):
        with lock, open(DROPPED_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"scenario_id": rec["scenario_id"], "stage": stage, "reasons": reasons,
                                "subject": rec.get("subject"), "body": rec.get("body")}, ensure_ascii=False) + "\n")
        stats[f"dropped_{stage}"] += 1

    # stage 1: code checks
    candidates = []
    for e in uniq:
        sc = scenarios[e["scenario_id"]]
        label, errs = build_label(sc, e)
        if label is None:
            drop(e, "code", errs)
            continue
        candidates.append({"scenario_id": sc["scenario_id"], "sender": sender_of(sc), "subject": e["subject"],
                           "body": e["body"], "label": label, "scenario": sc, "writer_model": e.get("model")})

    # stage 2: independent extraction
    client = client or make_verify_client()
    batch_size = batch_size or DatagenSettings().verify_batch_size
    batches = [candidates[i:i + batch_size] for i in range(0, len(candidates), batch_size)]

    def run(batch):
        res = client.generate(teacher_system_prompt(), verifier_user_message(batch), VerifyBatch, tag=tag)
        return batch, {r["id"]: r["extraction"] for r in res.parsed["results"]}, res.credits

    with ThreadPoolExecutor(max_workers=client.max_concurrency) as ex:
        futs = [ex.submit(run, b) for b in batches]
        for f in as_completed(futs):
            try:
                batch, preds, credits = f.result()
            except (CreditsExhausted, BudgetExceeded) as e:
                print("STOPPED:", e)
                stats["stopped"] += 1
                continue
            except LLMError as e:
                print("verify batch failed:", str(e)[:200])
                stats["failed_batches"] += 1
                continue
            stats["credits_x100"] += round(credits * 100)
            for rec in batch:
                pred = preds.get(rec["scenario_id"])
                if pred is None:
                    stats["verifier_missing"] += 1
                    continue  # retried on next run
                hard, soft = compare(rec["label"], pred)
                if hard:
                    drop(rec, "verifier", hard)
                    continue
                sc = rec["scenario"]
                out = {"scenario_id": rec["scenario_id"], "customer_id": sc["customer_id"], "intent": sc["intent"],
                       "difficulty": sc["difficulty"], "sender": rec["sender"], "subject": rec["subject"],
                       "body": rec["body"], "label": rec["label"], "target": to_target_json(rec["label"]),
                       "soft_diffs": soft, "truth_skus": [it["sku"] for it in sc["items"]],
                       "truth_sku_sets": [it["skus"] for it in sc["items"]],
                       "ref_types": [it["ref_type"] for it in sc["items"]],
                       "embedded_instruction": sc["noise"]["embedded_instruction"],
                       "writer_model": rec["writer_model"], "verifier_model": client.model}
                with lock, open(VERIFIED_PATH, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                stats["kept"] += 1
    return dict(stats)


def write_report() -> dict:
    kept = load_jsonl(VERIFIED_PATH)
    dropped = load_jsonl(DROPPED_PATH)
    reasons = Counter()
    for d in dropped:
        for r in d["reasons"]:
            key = re.sub(r"'[^']*'|\"[^\"]*\"|\[.*?\]|\(.*?\)|\b[\w-]*\d[\w-]*\b", "#", r)
            key = re.sub(r"\s+", " ", key.split("!=")[0]).strip()
            reasons[f"{d['stage']}: {key}"] += 1
    total = len(kept) + len(dropped)
    soft = Counter(s for k in kept for s in set(k["soft_diffs"]))
    report = {
        "total_checked": total, "kept": len(kept), "dropped": len(dropped),
        "drop_rate": round(len(dropped) / total, 4) if total else None,
        "dropped_by_stage": dict(Counter(d["stage"] for d in dropped)),
        "drop_reasons": dict(reasons.most_common()),
        "soft_disagreement_rate": {k: round(v / len(kept), 4) for k, v in soft.most_common()} if kept else {},
        "kept_by_intent": dict(Counter(k["intent"] for k in kept)),
        "kept_by_difficulty": dict(Counter(k["difficulty"] for k in kept)),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.parse_args()
    print(verify())
    print(json.dumps(write_report(), indent=2))
