"""Create ~20 realistic ADMIN corrections so a v2 retrain can be demonstrated.

Runs unseen emails from data/splits/corrections_pool.jsonl (never in train/val/exam) through the live backend
as the admin, compares the model's extraction with the ground-truth label, and saves a "Correct result" correction
(POST /api/quotes/{id}/correction) only where the model is actually wrong. Nothing is invented: emails the model
already gets right are skipped.

    python scripts/seed_demo_corrections.py --api http://localhost:8000 --token $ADMIN_TOKEN [--target 20]
"""
import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "backend"), str(ROOT)]

from evallib.metrics import score_one  # noqa: E402


def payload_from_truth(truth: dict) -> dict:
    """The correction the admin would make: the ground-truth extraction, with the missing-info flags per item."""
    flags = {}
    for m in truth["missing_info"]:
        kind, _, desc = m.partition(":")
        flags.setdefault(desc.strip(), set()).add(kind.strip())
    items = []
    for it in truth["items"]:
        k = flags.get(it["description"], set())
        items.append({**{f: it[f] for f in ("description", "quantity", "unit", "part_number", "compatible_with", "reference")},
                      "needs_size_or_spec": "size_or_spec" in k, "needs_equipment_model": "equipment_model" in k})
    return {"intent": truth["intent"], "urgency": truth["urgency"], "needed_by": truth["needed_by"], "items": items,
            "note": "demo seed: model result differed from the ground-truth label"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--token", required=True)
    ap.add_argument("--target", type=int, default=20)
    a = ap.parse_args()
    pool = [json.loads(l) for l in (ROOT / "data" / "splits" / "corrections_pool.jsonl").read_text(encoding="utf-8").splitlines()]
    made = skipped = 0
    with httpx.Client(base_url=a.api, headers={"X-Admin-Token": a.token}, timeout=240) as c:
        for rec in pool:
            if made >= a.target:
                break
            q = c.post("/api/quotes/process?stream=false",
                       json={"sender": rec["sender"], "subject": rec["subject"], "body": rec["body"]}).json()
            truth = json.loads(rec["target"])
            model_out = q.get("student_extraction") or q.get("extraction")
            if model_out and score_one(truth, json.dumps(model_out))["exact"]:
                skipped += 1
                print(f"{rec['id']}: model already correct, skipped")
                continue
            r = c.post(f"/api/quotes/{q['id']}/correction", json=payload_from_truth(truth))
            if r.status_code != 200:
                print(f"{rec['id']}: not saved ({r.status_code}: {r.json().get('detail')})")
                continue
            made = r.json()["retrain"]["corrections_pending"]
            print(f"{rec['id']}: correction saved -> {made}/{r.json()['retrain']['threshold']}")
        print(f"done: {made} pending corrections, {skipped} emails skipped because the model was already right")


if __name__ == "__main__":
    main()
