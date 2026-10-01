"""20-scenario pilot: write + verify + 2 single-email teacher calls, then project total credit use.

    python -m datagen.pilot
Writes data/generated/pilot_report.json. The pilot's emails stay in the dataset (no waste).
"""
from __future__ import annotations

import json
import time
from collections import Counter

from evallib.llm import client_from_settings
from evallib.prompt import teacher_system_prompt, user_message
from evallib.schema import Extraction

from .config import CACHE_DIR, GEN_DIR, DatagenSettings, LLMSettings
from .verify import VERIFIED_PATH, make_verify_client, sender_of, verify, write_report
from .write_emails import COST_LOG, EMAILS_PATH, load_jsonl, load_scenarios, make_writer_client, write

PILOT_MIX = {"quote_request": 12, "product_question": 2, "order_status": 2, "return_request": 2, "other": 2}
EVAL_TEACHER_CALLS = {"P2b teacher baseline (exam 150 + exam_hard 30)": 180,
                      "P4 router calibration on val": 150,
                      "P4 harness eval escalations (upper bound)": 180,
                      "sample-email cache (8) + smoke tests": 20}
SAFETY = 1.25  # retries, schema failures, variance


def pick_pilot(scenarios: list[dict]) -> list[dict]:
    need = dict(PILOT_MIX)
    out = []
    for s in scenarios:
        if need.get(s["intent"], 0) > 0:
            out.append(s)
            need[s["intent"]] -= 1
    return out


def credits_for(tag: str, since: str) -> tuple[float, int]:
    total, n = 0.0, 0
    for r in load_jsonl(COST_LOG):
        if r.get("tag") == tag and r["ts"] >= since and not r.get("cached"):
            total += r.get("credits") or 0.0
            n += 1
    return total, n


def main():
    ds = DatagenSettings()
    t0 = time.strftime("%Y-%m-%dT%H:%M:%S")
    scenarios = load_scenarios()
    pilot = pick_pilot(scenarios)
    ids = {s["scenario_id"] for s in pilot}
    writer = make_writer_client()
    bal_before = writer.balance()
    print(f"KIE balance before: {bal_before}")

    print("writing", len(pilot), "emails ...")
    wstats = write(pilot, client=writer, tag="pilot_write")
    print("write:", wstats)
    print("verifying ...")
    vclient = make_verify_client()
    vstats = verify(ids, client=vclient, tag="pilot_verify")
    print("verify:", vstats)

    # two single-email teacher calls (the unit cost of every later eval run)
    s = LLMSettings()
    teacher = client_from_settings(s, s.teacher_model, cache_dir=CACHE_DIR, cost_log=COST_LOG)
    kept = [k for k in load_jsonl(VERIFIED_PATH) if k["scenario_id"] in ids][:2]
    for k in kept:
        teacher.generate(teacher_system_prompt(), user_message(k["sender"], k["subject"], k["body"]), Extraction,
                         tag="pilot_teacher", use_cache=False)

    bal_after = writer.balance()
    w_cr, w_n = credits_for("pilot_write", t0)
    v_cr, v_n = credits_for("pilot_verify", t0)
    t_cr, t_n = credits_for("pilot_teacher", t0)
    n_written = len([e for e in load_jsonl(EMAILS_PATH) if e["scenario_id"] in ids])
    per_email_write = w_cr / max(n_written, 1)
    per_email_verify = v_cr / max(n_written, 1)
    per_teacher_call = t_cr / max(t_n, 1)
    remaining_scenarios = ds.n_scenarios - len(pilot)
    datagen_proj = remaining_scenarios * (per_email_write + per_email_verify)
    eval_proj = sum(EVAL_TEACHER_CALLS.values()) * per_teacher_call
    total_proj = (datagen_proj + eval_proj) * SAFETY
    kept_n = len([k for k in load_jsonl(VERIFIED_PATH) if k["scenario_id"] in ids])

    report = {
        "timestamp": t0, "pilot_size": len(pilot), "pilot_mix": dict(Counter(s["intent"] for s in pilot)),
        "written": n_written, "kept_after_verify": kept_n,
        "pilot_drop_rate": round(1 - kept_n / max(n_written, 1), 3),
        "kie_balance_before": bal_before, "kie_balance_after": bal_after,
        "balance_delta": round(bal_before - bal_after, 3) if bal_before is not None and bal_after is not None else None,
        "logged_credits": {"write": round(w_cr, 3), "verify": round(v_cr, 3), "teacher": round(t_cr, 3)},
        "calls": {"write": w_n, "verify": v_n, "teacher": t_n},
        "per_email_credits": {"write": round(per_email_write, 4), "verify": round(per_email_verify, 4)},
        "per_teacher_call_credits": round(per_teacher_call, 4),
        "projection": {
            "datagen_remaining_scenarios": remaining_scenarios,
            "datagen_credits": round(datagen_proj, 2),
            "eval_teacher_calls": EVAL_TEACHER_CALLS,
            "eval_credits": round(eval_proj, 2),
            "safety_factor": SAFETY,
            "total_credits_with_safety": round(total_proj, 2),
            "fits_in_balance": (bal_after is not None and total_proj <= bal_after),
        },
        "verify_report": write_report(),
    }
    (GEN_DIR / "pilot_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    print("\n================ 5 SAMPLE EMAILS ================")
    samples = [k for k in load_jsonl(VERIFIED_PATH) if k["scenario_id"] in ids][:5]
    for k in samples:
        print(f"\n--- {k['scenario_id']} | {k['intent']} | {k['difficulty']}\nFrom: {k['sender']}\nSubject: {k['subject']}\n")
        print(k["body"])
        print("\nLABEL:", k["target"])


if __name__ == "__main__":
    main()
