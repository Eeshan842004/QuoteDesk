"""Step 4+5: near-duplicate removal, stratified split, chat-format export, exam hashes.

    python -m datagen.split_export [--val 150 --exam 150]
Inputs:  data/generated/verified.jsonl, data/splits/exam_hard.jsonl (run datagen.exam_hard first)
Outputs: data/splits/{train,val,exam,fewshot,corrections_pool}.jsonl, exam_hashes.json, split_report.json
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict

import numpy as np
from rapidfuzz import fuzz, process

from evallib.normalize import email_hash, norm_text
from evallib.prompt import chat_messages

from .config import GEN_DIR, SPLITS_DIR
from .write_emails import load_jsonl

DUP_THRESHOLD = 90


def dedupe(records: list[dict], against: list[str]) -> tuple[list[dict], int]:
    """Drop records whose body is > DUP_THRESHOLD similar to an earlier kept record or to any `against` body."""
    bodies = [norm_text(r["body"]) for r in records]
    sim = process.cdist(bodies, bodies, scorer=fuzz.ratio, workers=-1, dtype=np.uint8)
    ext = process.cdist(bodies, [norm_text(b) for b in against], scorer=fuzz.ratio, workers=-1,
                        dtype=np.uint8) if against else None
    keep, kept_idx = [], []
    for i, r in enumerate(records):
        if ext is not None and ext[i].max() > DUP_THRESHOLD:
            continue
        if kept_idx and sim[i, kept_idx].max() > DUP_THRESHOLD:
            continue
        keep.append(r)
        kept_idx.append(i)
    return keep, len(records) - len(keep)


def stratified_split(records: list[dict], n_val: int, n_exam: int, seed: int = 13):
    rng = random.Random(seed)
    strata = defaultdict(list)
    for r in records:
        strata[(r["intent"], r["difficulty"])].append(r)
    total = len(records)

    def allocate(n):
        raw = {k: n * len(v) / total for k, v in strata.items()}
        alloc = {k: int(x) for k, x in raw.items()}
        for k in sorted(raw, key=lambda k: raw[k] - alloc[k], reverse=True)[: n - sum(alloc.values())]:
            alloc[k] += 1
        return alloc

    val_alloc, exam_alloc = allocate(n_val), allocate(n_exam)
    train, val, exam = [], [], []
    for k in sorted(strata):
        group = sorted(strata[k], key=lambda r: r["id"])
        rng.shuffle(group)
        e, v = exam_alloc[k], val_alloc[k]
        exam += group[:e]
        val += group[e:e + v]
        train += group[e + v:]
    return train, val, exam


def to_record(v: dict) -> dict:
    return {"id": v["scenario_id"], "customer_id": v["customer_id"], "intent": v["intent"],
            "difficulty": v["difficulty"], "sender": v["sender"], "subject": v["subject"], "body": v["body"],
            "target": v["target"], "truth_skus": v["truth_skus"], "truth_sku_sets": v.get("truth_sku_sets"),
            "ref_types": v.get("ref_types"), "embedded_instruction": v.get("embedded_instruction", False),
            "source": "generated", "messages": chat_messages(v["sender"], v["subject"], v["body"], v["target"])}


def pick_fewshot(train: list[dict]) -> list[dict]:
    """3 diverse worked examples for the base-model baseline: multi-item quote, compat/prev-order, non-quote."""
    def first(pred):
        return next(r for r in sorted(train, key=lambda r: r["id"]) if pred(r))
    a = first(lambda r: r["intent"] == "quote_request" and len(json.loads(r["target"])["items"]) >= 3
              and len(r["body"]) < 700)
    b = first(lambda r: r["intent"] == "quote_request" and r["id"] != a["id"] and r["ref_types"]
              and any(t in ("compatibility", "previous_order") for t in r["ref_types"]) and len(r["body"]) < 600)
    c = first(lambda r: r["intent"] in ("order_status", "product_question") and len(r["body"]) < 500)
    return [a, b, c]


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(n_val: int, n_exam: int, n_pool: int = 40):
    verified = load_jsonl(GEN_DIR / "verified.jsonl")
    exam_hard = load_jsonl(SPLITS_DIR / "exam_hard.jsonl")
    assert exam_hard, "run `python -m datagen.exam_hard` first"
    records = sorted((to_record(v) for v in {v["scenario_id"]: v for v in verified}.values()), key=lambda r: r["id"])
    deduped, n_dups = dedupe(records, [r["body"] for r in exam_hard])
    train, val, exam = stratified_split(deduped, n_val, n_exam)
    # reserve a small pool of unseen emails for scripts/seed_demo_corrections.py (never in train/val/exam)
    rng = random.Random(29)
    pool_ids = {r["id"] for r in rng.sample([r for r in train if r["intent"] == "quote_request"], k=min(n_pool, len(train) // 10))}
    pool = [r for r in train if r["id"] in pool_ids]
    train = [r for r in train if r["id"] not in pool_ids]
    fewshot = pick_fewshot(train)

    SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train", train), ("val", val), ("exam", exam), ("fewshot", fewshot),
                       ("corrections_pool", pool)):
        write_jsonl(SPLITS_DIR / f"{name}.jsonl", rows)
    hashes = sorted({email_hash(r["body"]) for r in exam + exam_hard})
    (SPLITS_DIR / "exam_hashes.json").write_text(json.dumps(
        {"note": "sha256 of normalized exam + exam_hard bodies; never train on these",
         "count": len(hashes), "hashes": hashes}, indent=1), encoding="utf-8")

    def breakdown(rows):
        return {"n": len(rows), "by_intent": dict(Counter(r["intent"] for r in rows)),
                "by_difficulty": dict(Counter(r["difficulty"] for r in rows)),
                "approx_tokens_p50_p99": [int(np.percentile([len(json.dumps(r["messages"])) / 3.6 for r in rows], p))
                                          for p in (50, 99)] if rows else None}
    report = {"verified_in": len(records), "near_duplicates_removed": n_dups, "dup_threshold": DUP_THRESHOLD,
              "train": breakdown(train), "val": breakdown(val), "exam": breakdown(exam),
              "exam_hard": breakdown(exam_hard), "corrections_pool": breakdown(pool),
              "fewshot_ids": [r["id"] for r in fewshot]}
    (SPLITS_DIR / "split_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--val", type=int, default=150)
    ap.add_argument("--exam", type=int, default=150)
    a = ap.parse_args()
    main(a.val, a.exam)
