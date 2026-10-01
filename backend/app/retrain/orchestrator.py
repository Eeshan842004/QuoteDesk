"""Retraining orchestrator.

States: IDLE -> COLLECTING -> QUEUED -> UPLOADING_DATA -> TRAINING -> EVALUATING -> PROMOTED | REJECTED | FAILED
Manual mode (v1.1, default): QUEUED -> AWAITING_MANUAL (bundle zip + instructions) -> register -> gate.
Auto mode (v1.2, AUTO_RETRAIN_ENABLED=true + Kaggle creds): dataset version + kernel push, polled by tick().

tick() is safe to call often: from GET /api/retrain/status, from a Modal cron, or from a local loop.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from evallib.normalize import email_hash

from ..config import REPORTS_DIR, get_settings
from ..db import Correction, ModelVersion, RetrainRun, get_state, session_scope, set_state
from ..models import get_registry
from .gate import evaluate_gate, exam_metrics

log = logging.getLogger("quotedesk.retrain")
ACTIVE = ("QUEUED", "UPLOADING_DATA", "TRAINING", "EVALUATING", "AWAITING_MANUAL")
TERMINAL = ("PROMOTED", "REJECTED", "FAILED")


def _log(run: RetrainRun, msg: str) -> None:
    run.log = list(run.log or []) + [{"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "msg": msg}]


def pending_corrections(db: Session) -> list[Correction]:
    return list(db.scalars(select(Correction).where(Correction.counts_for_training.is_(True),
                                                    Correction.kind == "EXTRACTION",
                                                    Correction.used_in_run_id.is_(None))))


def pending_examples(db: Session) -> list[dict]:
    """Distinct training examples waiting for the next run (one per email, latest correction wins)."""
    by_hash: dict[str, dict] = {}
    for c in sorted(pending_corrections(db), key=lambda c: c.id):
        ex = c.training_example
        if ex:
            by_hash[email_hash(ex["body"])] = ex
    return list(by_hash.values())


def active_run(db: Session) -> Optional[RetrainRun]:
    return db.scalars(select(RetrainRun).where(RetrainRun.state.in_(ACTIVE)).order_by(RetrainRun.id.desc())).first()


def live_version(db: Session) -> Optional[ModelVersion]:
    return db.scalars(select(ModelVersion).where(ModelVersion.status == "live")).first()


def next_version_tag(db: Session) -> str:
    nums = []
    for v in db.scalars(select(ModelVersion.version)):
        if v.startswith("v") and v[1:].isdigit():
            nums.append(int(v[1:]))
    for v in db.scalars(select(RetrainRun.candidate_version)):
        if v and v.startswith("v") and v[1:].isdigit():
            nums.append(int(v[1:]))
    return f"v{max(nums, default=1) + 1}"


def status(db: Session) -> dict:
    s = get_settings()
    pend = pending_examples(db)
    runs = db.scalars(select(RetrainRun).order_by(RetrainRun.id.desc()).limit(20)).all()
    act = active_run(db)
    return {
        "state": act.state if act else ("COLLECTING" if pend else "IDLE"),
        "auto_enabled": s.auto_retrain_enabled, "paused": bool(get_state(db, "retrain_paused", False)),
        "corrections_pending": len(pend), "threshold": s.retrain_threshold,
        "active_run": run_dict(act) if act else None, "runs": [run_dict(r) for r in runs],
    }


def run_dict(r: RetrainRun) -> dict:
    return {"id": r.id, "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None, "mode": r.mode, "state": r.state,
            "corrections_count": r.corrections_count, "candidate_version": r.candidate_version,
            "gate_result": r.gate_result, "reason": r.reason, "log": r.log or [],
            "bundle_available": bool(r.bundle_path and Path(r.bundle_path).exists())}


def start_run(db: Session, mode: str) -> RetrainRun:
    s = get_settings()
    if active_run(db):
        raise RuntimeError("a retrain run is already in progress")
    corrections = pending_corrections(db)
    examples = pending_examples(db)
    if not examples:
        raise RuntimeError("no admin EXTRACTION corrections to train on")
    version = next_version_tag(db)
    run = RetrainRun(mode=mode, state="QUEUED", corrections_count=len(examples), candidate_version=version, log=[])
    db.add(run)
    db.flush()
    _log(run, f"queued {mode} run {version} with {len(examples)} training examples from {len(corrections)} corrections")
    work = s.work_dir / f"run_{run.id}"
    try:
        from datagen.make_bundle import LeakageError, build_bundle  # repo layout is mirrored in the image
        zip_path = build_bundle(out_dir=work / "bundle", corrections=examples, version_tag=version,
                                dataset_slug=s.kaggle_dataset_slug, zip_path=work / f"quotedesk-data-{version}.zip")
    except Exception as e:
        run.state, run.reason = "FAILED", f"bundle build failed: {e}"
        _log(run, run.reason)
        return run
    run.bundle_path = str(zip_path)
    for c in corrections:
        c.used_in_run_id = run.id
    _log(run, f"bundle ready: {zip_path.name} (exam overlap check passed)")
    if mode == "manual":
        run.state = "AWAITING_MANUAL"
        _log(run, (f"MANUAL: download the bundle, upload it as a new version of your Kaggle dataset, run "
                   f"training/finetune_gemma_lora.ipynb with VERSION_TAG=\"{version}\", then POST "
                   f"/api/models/register with the pushed tag and eval.json."))
        return run
    run.state = "UPLOADING_DATA"
    _log(run, "uploading dataset version to Kaggle")
    return run


def trigger(db: Session, mode: Optional[str] = None) -> dict:
    s = get_settings()
    mode = mode or ("auto" if s.auto_retrain_enabled and s.kaggle_kernel_slug else "manual")
    run = start_run(db, mode)
    db.flush()
    if mode == "auto":
        _advance_async(run.id)
    return run_dict(run)


def maybe_auto_trigger(db: Session) -> dict:
    """Called after every admin decision."""
    s = get_settings()
    n = len(pending_examples(db))
    info = {"corrections_pending": n, "threshold": s.retrain_threshold, "triggered": False}
    if get_state(db, "retrain_paused", False) or active_run(db):
        return info
    if n >= s.retrain_threshold:
        try:
            info["run"] = trigger(db, "auto" if s.kaggle_kernel_slug else "manual")
            info["triggered"] = True
        except RuntimeError as e:
            info["error"] = str(e)
    return info


# ---------------------------------------------------------------- auto mode (Kaggle)
_tick_lock = threading.Lock()


def _advance_async(run_id: int) -> None:
    threading.Thread(target=tick, daemon=True, name=f"retrain-{run_id}").start()


def tick() -> Optional[dict]:
    """Advance the active auto run by one step. Returns the run state or None."""
    if not _tick_lock.acquire(blocking=False):
        return None
    try:
        from . import kaggle_client as kc
        s = get_settings()
        with session_scope() as db:
            run = active_run(db)
            if not run or run.mode != "auto":
                return None
            work = s.work_dir / f"run_{run.id}"
            try:
                if run.state == "UPLOADING_DATA":
                    kc.push_dataset_version(work / "bundle", notes=f"QuoteDesk {run.candidate_version} + corrections")
                    _log(run, "dataset version pushed; pushing training kernel (GPU T4)")
                    kc.push_kernel(run.candidate_version, work)
                    run.state = "TRAINING"
                    _log(run, "kernel pushed; training")
                elif run.state == "TRAINING":
                    st = kc.kernel_status(s.kaggle_kernel_slug)
                    if st in ("complete",):
                        run.state = "EVALUATING"
                        _log(run, "kernel complete; downloading outputs")
                    elif st in ("error", "cancelled", "cancelacknowledged"):
                        run.state, run.reason = "FAILED", f"Kaggle kernel ended with status {st}"
                        _log(run, run.reason)
                if run.state == "EVALUATING":
                    report = kc.download_outputs(s.kaggle_kernel_slug, work / "outputs")
                    if not report:
                        run.state, run.reason = "FAILED", "no eval.json in kernel outputs"
                        _log(run, run.reason)
                    else:
                        res = register_version(db, run.candidate_version, s.hf_model_repo, run.candidate_version,
                                               report, source="auto", run=run)
                        _log(run, f"gate: {'PROMOTED' if res['promoted'] else 'REJECTED'}")
            except kc.KaggleUnavailable as e:
                run.state, run.reason = "FAILED", f"{e}. Use the manual path (bundle + /api/models/register)."
                _log(run, run.reason)
            except Exception as e:
                log.exception("retrain tick failed")
                _log(run, f"tick error (will retry): {type(e).__name__}: {str(e)[:200]}")
            return run_dict(run)
    finally:
        _tick_lock.release()


# ---------------------------------------------------------------- register / promote / rollback

def register_version(db: Session, version: str, hf_repo: Optional[str], revision: Optional[str], eval_report: dict,
                     source: str = "manual_register", run: Optional[RetrainRun] = None, notes: str | None = None) -> dict:
    s = get_settings()
    if run is None:
        run = db.scalars(select(RetrainRun).where(RetrainRun.candidate_version == version)
                         .order_by(RetrainRun.id.desc())).first()
    cand = exam_metrics(eval_report)
    if cand is None:
        raise ValueError("eval report has no 'exam' split metrics")
    live = live_version(db)
    current = (live.metrics or {}) if live else None
    gate = evaluate_gate(current, cand, s.promotion_margin)
    mv = db.scalars(select(ModelVersion).where(ModelVersion.version == version)).first()
    if mv is None:
        mv = ModelVersion(version=version)
        db.add(mv)
    mv.hf_repo, mv.revision, mv.source = hf_repo, revision, source
    mv.metrics, mv.eval_report, mv.gate, mv.notes = cand, eval_report, gate, notes
    promoted = gate["passed"]
    if promoted:
        if live and live.version != version:
            live.status = "retired"
        mv.status, mv.promoted_at = "live", datetime.now(timezone.utc)
        set_state(db, "live_version", {"version": version, "repo": hf_repo, "revision": revision})
        _hot_swap(hf_repo, revision)
    else:
        mv.status = "rejected"
    if run is not None:
        run.state = "PROMOTED" if promoted else "REJECTED"
        run.gate_result = gate
        run.reason = None if promoted else "; ".join(gate["reasons"])
    _save_report(version, eval_report)
    return {"version": version, "promoted": promoted, "gate": gate}


def rollback(db: Session, version: str) -> dict:
    mv = db.scalars(select(ModelVersion).where(ModelVersion.version == version)).first()
    if mv is None:
        raise ValueError(f"unknown version {version}")
    live = live_version(db)
    if live and live.id != mv.id:
        live.status = "retired"
    mv.status, mv.promoted_at = "live", datetime.now(timezone.utc)
    set_state(db, "live_version", {"version": mv.version, "repo": mv.hf_repo, "revision": mv.revision})
    _hot_swap(mv.hf_repo, mv.revision)
    return {"version": version, "status": "live"}


def _hot_swap(repo: Optional[str], revision: Optional[str]) -> None:
    if not (repo and revision):
        return
    threading.Thread(target=get_registry().load, args=(repo, revision), daemon=True, name="hot-swap").start()


def _save_report(version: str, report: dict) -> None:
    try:
        d = REPORTS_DIR / "models"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{version}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError:
        pass


def seed_initial_version(db: Session) -> None:
    """On startup: make sure the env-configured adapter is recorded as the live version."""
    s = get_settings()
    if not (s.hf_model_repo and s.student_adapter_revision):
        return
    live = live_version(db)
    state = get_state(db, "live_version")
    if live is None and db.scalar(select(func.count()).select_from(ModelVersion)) == 0:
        metrics = None
        tuned = _latest_report("tuned.json")
        if tuned:
            metrics = exam_metrics(tuned)
        db.add(ModelVersion(version=s.student_adapter_revision, hf_repo=s.hf_model_repo,
                            revision=s.student_adapter_revision, status="live", source="notebook",
                            promoted_at=datetime.now(timezone.utc), metrics=metrics, eval_report=tuned,
                            gate={"passed": True, "checks": [{"name": "baseline", "ok": True,
                                                              "detail": "initial version from the notebook"}],
                                  "reasons": []}))
        set_state(db, "live_version", {"version": s.student_adapter_revision, "repo": s.hf_model_repo,
                                       "revision": s.student_adapter_revision})
    elif state is None and live is not None:
        set_state(db, "live_version", {"version": live.version, "repo": live.hf_repo, "revision": live.revision})


def _latest_report(name: str) -> Optional[dict]:
    if not REPORTS_DIR.exists():
        return None
    for d in sorted((p for p in REPORTS_DIR.iterdir() if p.is_dir() and p.name[:2] == "20"), reverse=True):
        if (d / name).exists():
            return json.loads((d / name).read_text(encoding="utf-8"))
    return None
