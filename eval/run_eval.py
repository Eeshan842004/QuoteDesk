"""QuoteDesk evaluation CLI. Every number in the UI/README comes from files written here.

    python eval/run_eval.py teacher   --run 2026-09-30 [--splits exam exam_hard val] [--workers 8]
    python eval/run_eval.py student   --run 2026-09-30 --adapter user/quotedesk-student@v1   (or --local path)
    python eval/run_eval.py base      --run 2026-09-30 [--limit 60]            (CPU, slow; notebook does it on GPU)
    python eval/run_eval.py import-notebook --run 2026-09-30 --from path/to/kaggle/outputs
    python eval/run_eval.py calibrate --run 2026-09-30        (needs student + teacher predictions on val)
    python eval/run_eval.py harness   --run 2026-09-30 [--threshold 0.83]   (student + router + teacher)
    python eval/run_eval.py summarize --run 2026-09-30        (-> summary.json + docs/EVAL_REPORT.md)

Reports: eval/reports/<run>/{teacher,tuned,tuned_cpu,base,harness}.json + *_predictions.jsonl, calibration.json/png,
summary.json. Costs: teacher = measured tokens x Google's published paid price (label in pricing.json);
student = CPU seconds x Modal container price (estimate).
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "backend"), str(ROOT)]

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evallib.metrics import aggregate, score_one  # noqa: E402
from evallib.postprocess import repair_missing_info  # noqa: E402
from evallib.prompt import chat_messages, fewshot_messages, teacher_system_prompt, user_message  # noqa: E402
from evallib.runner import evaluate, load_split, pricing, student_cost_usd, teacher_cost_usd, write_report  # noqa: E402
from evallib.schema import Extraction, parse_extraction, semantic_errors  # noqa: E402

SPLITS = ROOT / "data" / "splits"
REPORTS = ROOT / "eval" / "reports"
SYSTEM_LABELS = {"base": "Base Gemma 3 270M (3-shot)", "tuned": "Fine-tuned Gemma 3 270M (GPU, notebook)",
                 "tuned_cpu": "Fine-tuned Gemma 3 270M (CPU)",
                 "tuned_cpu_norm": "Fine-tuned Gemma 3 270M (CPU) + rule fixes", "teacher": "Gemini 3.8 Flash (teacher)",
                 "harness": "Full harness (student + router + teacher)"}


def run_dir(name: str) -> Path:
    d = REPORTS / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def splits_for(names, limit=None):
    out = {}
    for n in names:
        rows = load_split(SPLITS / f"{n}.jsonl")
        out[n] = rows[:limit] if limit else rows
    return out


def read_preds(d: Path, system: str) -> dict:
    """{(split, id): prediction} from <system>_predictions.jsonl."""
    p = d / f"{system}_predictions.jsonl"
    if not p.exists():
        return {}
    return {(r["split"], r["id"]): r for r in map(json.loads, p.read_text(encoding="utf-8").splitlines())}


# ------------------------------------------------------------------ SKU resolution (end-to-end, after tools)

def sku_resolution(records: list[dict], preds: dict, split: str) -> dict:
    """Share of truth items with a known SKU whose resolved top candidate (tools on the predicted extraction)
    is that SKU. Items the system missed count as wrong."""
    from app.harness.draft import missing_kinds_for
    from app.tools import LineItemIn, get_catalog
    from evallib.metrics import align

    cat = get_catalog()
    total = correct = 0
    for rec in records:
        truth = json.loads(rec["target"])
        tskus = rec.get("truth_skus") or []
        pred = (preds.get((split, rec["id"])) or {}).get("pred")
        known = [(i, s) for i, s in enumerate(tskus) if s]
        total += len(known)
        if not pred or not known:
            continue
        pext = Extraction.model_validate(pred)
        pairs = {t: p for t, p, s in align(truth["items"], pred["items"]) if s >= 80}
        cust = rec.get("customer_id")
        for ti, sku in known:
            pi = pairs.get(ti)
            if pi is None:
                continue
            it = pext.items[pi]
            res = cat.resolve_line_item(LineItemIn(**it.model_dump()), cust, missing_kinds_for(pext, it.description))
            if res.candidates and res.candidates[0].sku == sku:
                correct += 1
    return {"sku_resolution_accuracy": round(correct / total, 4) if total else None, "sku_items": total}


def add_sku_metrics(d: Path, system: str, splits: dict):
    rep_path = d / f"{system}.json"
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    preds = read_preds(d, system)
    for split, rows in splits.items():
        if split in rep["splits"]:
            rep["splits"][split].update(sku_resolution(rows, preds, split))
    rep_path.write_text(json.dumps(rep, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ systems

def cmd_teacher(a):
    from datagen.config import LLMSettings
    from evallib.llm import LLMError, client_from_settings

    s = LLMSettings()
    d = run_dir(a.run)
    client = client_from_settings(s, s.teacher_model, cache_dir=ROOT / "data" / "generated" / "cache",
                                  cost_log=d / "teacher_calls.jsonl", max_attempts=4)
    splits = splits_for(a.splits, a.limit)

    def gen(rec):
        try:
            r = client.generate(teacher_system_prompt(), user_message(rec["sender"], rec["subject"], rec["body"]),
                                Extraction, tag=f"eval_teacher", use_cache=True)
        except LLMError as e:
            return {"text": None, "latency_s": None, "error": str(e)[:200]}
        return {"text": json.dumps(r.parsed), "latency_s": r.latency_s,
                "cost_usd": teacher_cost_usd(r.prompt_tokens, r.billable_output_tokens),
                "prompt_tokens": r.prompt_tokens, "output_tokens": r.billable_output_tokens, "credits": r.credits,
                "cached": r.cached}

    results = {n: evaluate(rows, gen, max_workers=a.workers, label=f"teacher/{n}") for n, rows in splits.items()}
    write_report(d, "teacher", s.teacher_model, results, extra={
        "provider": s.provider, "label": SYSTEM_LABELS["teacher"],
        "latency_note": "wall-clock per email through the KIE proxy (streaming, includes queueing)",
        "cost_note": pricing()["teacher"]["label"]})
    add_sku_metrics(d, "teacher", splits)
    _print(d / "teacher.json")


def _student(a):
    from app.models.student import StudentModel
    q = getattr(a, "quantize", None)
    if a.local:
        return StudentModel(a.base_model, adapter=a.local, quantize=q)
    if a.adapter:
        repo, _, rev = a.adapter.partition("@")
        import os
        return StudentModel(a.base_model, adapter=repo, revision=rev or None, hf_token=os.getenv("HF_TOKEN"), quantize=q)
    return StudentModel(a.base_model, quantize=q)


def cmd_student(a):
    d = run_dir(a.run)
    m = _student(a)
    splits = splits_for(a.splits, a.limit)

    def gen(rec):
        out = m.generate(chat_messages(rec["sender"], rec["subject"], rec["body"])[:2])
        ext, err = parse_extraction(out.text)
        errs = ([err] if err else []) + (semantic_errors(ext) if ext else [])
        from app.harness.router import confidence
        conf = confidence(out.mean_logprob, ext, errs)
        return {"text": out.text, "latency_s": out.latency_s, "cost_usd": student_cost_usd(out.latency_s),
                "mean_logprob": out.mean_logprob, "confidence": conf["score"], "valid": not errs}

    results = {n: evaluate(rows, gen, label=f"student/{n}") for n, rows in splits.items()}
    name = ("tuned_cpu" if (a.adapter or a.local) else "base_zeroshot_cpu") + ("_int8" if a.quantize else "")
    write_report(d, name, f"{a.base_model}+{a.adapter or a.local or 'none'}", results, extra={
        "label": SYSTEM_LABELS.get(name, name), "hardware": "local CPU", "threads": _threads(),
        "latency_note": "single-email greedy decoding on CPU (what the deployed backend does)",
        "cost_note": pricing()["student_cpu"]["label"]})
    add_sku_metrics(d, name, splits)
    _print(d / f"{name}.json")


def cmd_base(a):
    from app.models.student import StudentModel
    d = run_dir(a.run)
    m = StudentModel(a.base_model)
    shots = [{"sender": r["sender"], "subject": r["subject"], "body": r["body"], "target": r["target"]}
             for r in load_split(SPLITS / "fewshot.jsonl")]
    splits = splits_for(a.splits, a.limit)

    def gen(rec):
        out = m.generate(fewshot_messages(shots, rec["sender"], rec["subject"], rec["body"]))
        return {"text": out.text, "latency_s": out.latency_s, "cost_usd": student_cost_usd(out.latency_s)}

    results = {n: evaluate(rows, gen, label=f"base/{n}") for n, rows in splits.items()}
    write_report(d, "base", f"{a.base_model} (3-shot)", results, extra={
        "label": SYSTEM_LABELS["base"], "hardware": "local CPU", "fewshot_ids": [s.get("id") for s in shots]})
    add_sku_metrics(d, "base", splits)
    _print(d / "base.json")


def cmd_import_notebook(a):
    d = run_dir(a.run)
    src = Path(getattr(a, "from"))
    found = {}
    for name, target in (("eval.json", "tuned"), ("tuned.json", "tuned"), ("base_eval.json", "base"), ("base.json", "base")):
        p = next(iter(src.rglob(name)), None)
        if p and target not in found:
            shutil.copy2(p, d / f"{target}.json")
            pp = p.with_name(f"{'tuned' if target == 'tuned' else 'base'}_predictions.jsonl")
            if pp.exists():
                shutil.copy2(pp, d / f"{target}_predictions.jsonl")
            found[target] = str(p)
    for extra in ("run_config.json", "loss_curve.png"):
        p = next(iter(src.rglob(extra)), None)
        if p:
            shutil.copy2(p, d / extra)
    splits = splits_for(["exam", "exam_hard"])
    for target in found:
        if (d / f"{target}_predictions.jsonl").exists():
            add_sku_metrics(d, target, splits)
    print("imported:", found)


def normalized_text(text, body):
    """Student output after the harness NORMALIZE step (missing_info recomputed by rules)."""
    ext, err = parse_extraction(text) if text else (None, "empty")
    return repair_missing_info(ext, body).model_dump_json() if ext else text


def cmd_normalize(a):
    """tuned_cpu predictions -> tuned_cpu_norm: same student outputs after the NORMALIZE step."""
    d = run_dir(a.run)
    stu = read_preds(d, "tuned_cpu")
    splits = splits_for(["exam", "exam_hard", "val"])
    results = {}
    for n, rows in splits.items():
        def gen(rec, n=n):
            sp = stu[(n, rec["id"])]
            return {"text": normalized_text(sp.get("text"), rec["body"]), "latency_s": sp.get("latency_s"),
                    "cost_usd": sp.get("cost_usd"), "confidence": sp.get("confidence"), "valid": sp.get("valid", True)}
        results[n] = evaluate(rows, gen, label=f"norm/{n}", progress_every=0)
    write_report(d, "tuned_cpu_norm", "student + NORMALIZE rules", results, extra={
        "label": SYSTEM_LABELS["tuned_cpu_norm"], "hardware": "local CPU",
        "latency_note": "same CPU decoding; NORMALIZE adds < 1 ms", "cost_note": pricing()["student_cpu"]["label"]})
    add_sku_metrics(d, "tuned_cpu_norm", splits)
    _print(d / "tuned_cpu_norm.json")


def cmd_calibrate(a):
    """Sweep the router threshold on val using recorded student (tuned_cpu) + teacher predictions."""
    d = run_dir(a.run)
    stu, tea = read_preds(d, "tuned_cpu"), read_preds(d, "teacher")
    rows = load_split(SPLITS / "val.jsonl")
    rows = [r for r in rows if ("val", r["id"]) in stu and ("val", r["id"]) in tea]
    if not rows:
        sys.exit("need tuned_cpu and teacher predictions on val (run `student` and `teacher` with --splits val)")
    sweep = []
    for i in range(0, 101):
        t = i / 100
        scores, costs, esc = [], [], []
        for r in rows:
            sp, tp = stu[("val", r["id"])], tea[("val", r["id"])]
            escalate = (sp.get("confidence") or 0.0) < t or not sp.get("valid", True)
            chosen = tp if escalate else sp
            text = chosen.get("text") if escalate else normalized_text(chosen.get("text"), r["body"])
            scores.append(score_one(json.loads(r["target"]), text))
            costs.append((sp.get("cost_usd") or 0) + ((tp.get("cost_usd") or 0) if escalate else 0))
            esc.append(escalate)
        m = aggregate(scores, escalated=esc, costs_usd=costs)
        sweep.append({"threshold": t, "item_f1": m["item_f1"], "exact_match_rate": m["exact_match_rate"],
                      "intent_accuracy": m["intent_accuracy"], "escalation_rate": m["escalation_rate"],
                      "cost_per_1k_usd": m["cost_per_1k_usd"]})
    best_f1 = max(s["item_f1"] for s in sweep)
    tol = a.tolerance
    chosen = min((s for s in sweep if s["item_f1"] >= best_f1 - tol), key=lambda s: (s["escalation_rate"], s["threshold"]))
    calib = {"split": "val", "n": len(rows), "rule": f"lowest escalation rate whose val item F1 is within {tol} of the best",
             "best_item_f1": best_f1, "chosen": chosen, "sweep": sweep, "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (d / "calibration.json").write_text(json.dumps(calib, indent=2), encoding="utf-8")
    _plot_calibration(calib, d / "calibration.png")
    print(f"chosen threshold {chosen['threshold']:.2f}: item F1 {chosen['item_f1']}, escalation {chosen['escalation_rate']}, "
          f"cost/1k ${chosen['cost_per_1k_usd']}")
    print(f"set ROUTER_CONFIDENCE_THRESHOLD={chosen['threshold']:.2f}")


def _plot_calibration(calib, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    xs = [s["threshold"] for s in calib["sweep"]]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(xs, [s["item_f1"] for s in calib["sweep"]], label="item F1")
    ax.plot(xs, [s["escalation_rate"] for s in calib["sweep"]], label="% escalated")
    ax2 = ax.twinx()
    ax2.plot(xs, [s["cost_per_1k_usd"] for s in calib["sweep"]], "--", color="gray", label="cost / 1k emails ($)")
    ax.axvline(calib["chosen"]["threshold"], color="black", lw=0.8, ls=":")
    ax.set_xlabel("router confidence threshold")
    ax.set_title("Router calibration on val")
    ax.legend(loc="center left")
    ax2.legend(loc="center right")
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def cmd_harness(a):
    """Full harness offline: student (recorded tuned_cpu predictions) + router + teacher (recorded teacher
    predictions for the same email, same prompt/model; no extra calls)."""
    d = run_dir(a.run)
    thr = a.threshold
    if thr is None:
        c = d / "calibration.json"
        if not c.exists():
            sys.exit("no threshold: run `calibrate` first or pass --threshold")
        thr = json.loads(c.read_text())["chosen"]["threshold"]
    stu, tea = read_preds(d, "tuned_cpu"), read_preds(d, "teacher")
    splits = splits_for(a.splits)
    results = {}
    for n, rows in splits.items():
        def gen(rec, n=n):
            sp, tp = stu.get((n, rec["id"])), tea.get((n, rec["id"]))
            if sp is None:
                raise RuntimeError("missing student prediction")
            escalate = (sp.get("confidence") or 0.0) < thr or not sp.get("valid", True)
            if escalate and tp is not None and tp.get("text"):
                return {"text": tp["text"], "latency_s": (sp.get("latency_s") or 0) + (tp.get("latency_s") or 0),
                        "cost_usd": (sp.get("cost_usd") or 0) + (tp.get("cost_usd") or 0), "escalated": True,
                        "path": "teacher"}
            return {"text": normalized_text(sp["text"], rec["body"]), "latency_s": sp.get("latency_s"),
                    "cost_usd": sp.get("cost_usd"), "escalated": escalate,
                    "path": "student" if not escalate else "student_flagged"}
        results[n] = evaluate(rows, gen, label=f"harness/{n}", progress_every=0)
    write_report(d, "harness", f"student+router(t={thr})+teacher", results, extra={
        "label": SYSTEM_LABELS["harness"], "threshold": thr,
        "note": "teacher outputs reused from teacher_predictions.jsonl (same prompt and model) to avoid duplicate calls"})
    add_sku_metrics(d, "harness", splits)
    _print(d / "harness.json")


def cmd_summarize(a):
    d = run_dir(a.run)
    systems = {}
    for key in ("base", "tuned", "tuned_cpu", "tuned_cpu_norm", "teacher", "harness"):
        p = d / f"{key}.json"
        if p.exists():
            rep = json.loads(p.read_text(encoding="utf-8"))
            systems[key] = {"label": rep.get("label") or SYSTEM_LABELS.get(key, key), "model": rep.get("model"),
                            "splits": rep.get("splits", {}), "hardware": rep.get("hardware"),
                            "latency_note": rep.get("latency_note"), "cost_note": rep.get("cost_note"),
                            "created": rep.get("created")}
    calib = json.loads((d / "calibration.json").read_text()) if (d / "calibration.json").exists() else None
    split_report = SPLITS / "split_report.json"
    verify_report = ROOT / "data" / "generated" / "verify_report.json"
    summary = {"run": a.run, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "systems": systems,
               "router_threshold": (calib or {}).get("chosen", {}).get("threshold"),
               "pricing": pricing(),
               "data": {"splits": json.loads(split_report.read_text()) if split_report.exists() else None,
                        "verification": json.loads(verify_report.read_text()) if verify_report.exists() else None},
               "how_measured": [
                   "Exam (150) and exam_hard (30) are sealed: hashed and checked against every training file.",
                   "Item F1 matches items by description similarity (token-set >= 80) AND equal quantity.",
                   "SKU resolution runs the deterministic tools on each system's extraction and checks the top SKU.",
                   "Teacher cost = measured tokens x Google's published paid price for gemini-3.8-flash; calls go through the KIE proxy.",
                   "Student cost is an estimate: CPU inference seconds x Modal CPU container price.",
                   "Latency: teacher = wall-clock via KIE (includes queueing); student = single-email CPU decoding."]}
    (d / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_markdown(summary, d)
    print(f"wrote {d / 'summary.json'} and docs/EVAL_REPORT.md ({', '.join(systems) or 'no systems yet'})")


def _fmt(v, pct=False, money=False):
    if v is None:
        return "–"
    if money:
        return f"${v:,.3f}"
    return f"{100 * v:.1f}%" if pct else (f"{v:.2f}" if isinstance(v, float) else str(v))


def _write_markdown(summary, d: Path):
    lines = ["# Evaluation report", "",
             f"Generated from `eval/reports/{summary['run']}/summary.json` on {summary['created']}. "
             "Every number below is copied from that file.", ""]
    for split in ("exam", "exam_hard"):
        lines += [f"## {split} split", "",
                  "| System | Intent acc | JSON valid | Item F1 | Qty acc | Missing-info F1 | Exact match | SKU resolution | p50 s | p95 s | Escalated | Cost / 1k |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for key, s in summary["systems"].items():
            m = s["splits"].get(split)
            if not m:
                continue
            lines.append(f"| {s['label']} | {_fmt(m.get('intent_accuracy'), True)} | {_fmt(m.get('json_validity_rate'), True)} | "
                         f"{_fmt(m.get('item_f1'), True)} | {_fmt(m.get('quantity_accuracy'), True)} | "
                         f"{_fmt(m.get('missing_info_f1'), True)} | {_fmt(m.get('exact_match_rate'), True)} | "
                         f"{_fmt(m.get('sku_resolution_accuracy'), True)} | {_fmt(m.get('latency_p50_s'))} | "
                         f"{_fmt(m.get('latency_p95_s'))} | {_fmt(m.get('escalation_rate'), True)} | "
                         f"{_fmt(m.get('cost_per_1k_usd'), money=True)} |")
        lines.append("")
    if summary.get("router_threshold") is not None:
        lines += [f"Router threshold (chosen on val): **{summary['router_threshold']:.2f}**. See `calibration.png`.", ""]
    lines += ["## How we measured", ""] + [f"- {x}" for x in summary["how_measured"]] + [""]
    (ROOT / "docs" / "EVAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def _threads():
    try:
        import torch
        return torch.get_num_threads()
    except Exception:
        return None


def _print(path: Path):
    rep = json.loads(path.read_text(encoding="utf-8"))
    for split, m in rep["splits"].items():
        print(f"{rep['system']:>10} {split:>10}: intent={m.get('intent_accuracy')} json={m.get('json_validity_rate')} "
              f"item_f1={m.get('item_f1')} exact={m.get('exact_match_rate')} sku={m.get('sku_resolution_accuracy')} "
              f"p50={m.get('latency_p50_s')} cost/1k={m.get('cost_per_1k_usd')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    today = time.strftime("%Y-%m-%d")

    def common(p, splits=("exam", "exam_hard")):
        p.add_argument("--run", default=today)
        p.add_argument("--splits", nargs="+", default=list(splits))
        p.add_argument("--limit", type=int, default=None)

    p = sub.add_parser("teacher"); common(p, ("exam", "exam_hard", "val")); p.add_argument("--workers", type=int, default=8)
    p.set_defaults(fn=cmd_teacher)
    for name, fn in (("student", cmd_student), ("base", cmd_base)):
        p = sub.add_parser(name); common(p, ("exam", "exam_hard", "val") if name == "student" else ("exam", "exam_hard"))
        p.add_argument("--base-model", default="unsloth/gemma-3-270m-it")
        p.add_argument("--adapter", default=None, help="hf_repo@revision")
        p.add_argument("--local", default=None, help="local adapter directory")
        p.add_argument("--quantize", default=None, choices=["int8"], help="dynamic int8 on CPU (compare accuracy!)")
        p.set_defaults(fn=fn)
    p = sub.add_parser("import-notebook"); p.add_argument("--run", default=today); p.add_argument("--from", required=True)
    p.set_defaults(fn=cmd_import_notebook)
    p = sub.add_parser("normalize"); p.add_argument("--run", default=today); p.set_defaults(fn=cmd_normalize)
    p = sub.add_parser("calibrate"); p.add_argument("--run", default=today); p.add_argument("--tolerance", type=float, default=0.01)
    p.set_defaults(fn=cmd_calibrate)
    p = sub.add_parser("harness"); common(p); p.add_argument("--threshold", type=float, default=None)
    p.set_defaults(fn=cmd_harness)
    p = sub.add_parser("summarize"); p.add_argument("--run", default=today); p.set_defaults(fn=cmd_summarize)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
