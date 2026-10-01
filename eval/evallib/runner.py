"""Shared evaluation loop: run a system over a split, score it, and write a report JSON.

A "system" is any function generate(record) -> dict with keys:
    text (str | None), latency_s (float), escalated (bool, optional), cost_usd (float, optional),
    plus any extra fields (tokens, credits, path) that are kept in the predictions file.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from .metrics import aggregate, score_one

_PRICING = json.loads((Path(__file__).resolve().parent / "pricing.json").read_text(encoding="utf-8"))


def pricing() -> dict:
    return _PRICING


def teacher_cost_usd(prompt_tokens: int, billable_output_tokens: int) -> float:
    p = _PRICING["teacher"]
    return prompt_tokens / 1e6 * p["input_per_1m_usd"] + billable_output_tokens / 1e6 * p["output_per_1m_usd"]


def student_cost_usd(latency_s: float) -> float:
    return latency_s * _PRICING["student_cpu"]["usd_per_second"]


def load_split(path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def evaluate(records: list[dict], generate: Callable[[dict], dict], max_workers: int = 1,
             progress_every: int = 25, label: str = "") -> dict:
    """Run generate over records (optionally in threads) and score. Returns {"metrics", "predictions"}."""
    outputs: list[Optional[dict]] = [None] * len(records)

    def run(i):
        try:
            outputs[i] = generate(records[i])
        except Exception as e:  # a system failure counts as an invalid output
            outputs[i] = {"text": None, "latency_s": None, "error": f"{type(e).__name__}: {str(e)[:200]}"}
        done = sum(o is not None for o in outputs)
        if progress_every and done % progress_every == 0:
            print(f"  [{label}] {done}/{len(records)}", flush=True)

    t0 = time.time()
    if max_workers > 1:
        with ThreadPoolExecutor(max_workers) as ex:
            list(ex.map(run, range(len(records))))
    else:
        for i in range(len(records)):
            run(i)
    preds, scores = [], []
    for rec, out in zip(records, outputs):
        truth = json.loads(rec["target"])
        sc = score_one(truth, out.get("text"))
        scores.append(sc)
        preds.append({"id": rec["id"], "intent": rec["intent"], "difficulty": rec.get("difficulty"),
                      "category": rec.get("category"), "text": out.get("text"), "pred": sc["pred"],
                      "score": {k: v for k, v in sc.items() if k != "pred"},
                      **{k: v for k, v in out.items() if k != "text"}})
    metrics = aggregate(scores, [o.get("latency_s") for o in outputs],
                        [bool(o.get("escalated")) for o in outputs] if any("escalated" in o for o in outputs) else (),
                        [o.get("cost_usd") for o in outputs])
    metrics["wall_time_s"] = round(time.time() - t0, 1)
    metrics["errors"] = sum(1 for o in outputs if o.get("error"))
    return {"metrics": metrics, "predictions": preds}


def write_report(out_dir, system: str, model: str, results: dict, extra: Optional[dict] = None) -> Path:
    """results: {split_name: evaluate(...) output}. Writes <system>.json (+ <system>_predictions.jsonl)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"system": system, "model": model, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "splits": {k: v["metrics"] for k, v in results.items()}, "pricing": _PRICING}
    if extra:
        report.update(extra)
    path = out_dir / f"{system}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    with open(out_dir / f"{system}_predictions.jsonl", "w", encoding="utf-8") as f:
        for split, v in results.items():
            for p in v["predictions"]:
                f.write(json.dumps({"split": split, **p}, ensure_ascii=False) + "\n")
    return path
