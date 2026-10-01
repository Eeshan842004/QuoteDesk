"""Model versions and retraining endpoints (writes require the admin token)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import ModelVersion, RetrainRun, get_db, set_state
from ..models import get_registry
from ..retrain import orchestrator as orch
from .deps import require_admin

router = APIRouter(prefix="/api", tags=["models"])


def _mv(m: ModelVersion) -> dict:
    return {"version": m.version, "hf_repo": m.hf_repo, "revision": m.revision, "status": m.status,
            "source": m.source, "created_at": m.created_at.isoformat() if m.created_at else None,
            "promoted_at": m.promoted_at.isoformat() if m.promoted_at else None, "metrics": m.metrics,
            "gate": m.gate, "notes": m.notes}


@router.get("/models")
def models(db: Session = Depends(get_db)):
    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.id.desc())).all()
    return {"live": get_registry().status(), "versions": [_mv(m) for m in rows], "retrain": orch.status(db)}


@router.post("/models/{version}/rollback", dependencies=[Depends(require_admin)])
def rollback(version: str, db: Session = Depends(get_db)):
    try:
        return orch.rollback(db, version)
    except ValueError as e:
        raise HTTPException(404, str(e))


class RegisterIn(BaseModel):
    version: str = Field(pattern=r"^v\d+$")
    hf_repo: Optional[str] = None
    revision: Optional[str] = None
    eval_report: dict[str, Any]
    notes: Optional[str] = None


@router.post("/models/register", dependencies=[Depends(require_admin)])
def register(body: RegisterIn, db: Session = Depends(get_db)):
    s = get_settings()
    try:
        return orch.register_version(db, body.version, body.hf_repo or s.hf_model_repo, body.revision or body.version,
                                     body.eval_report, notes=body.notes)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/retrain/status")
def retrain_status(db: Session = Depends(get_db)):
    out = orch.status(db)
    if out["active_run"] and out["active_run"]["mode"] == "auto":
        orch._advance_async(out["active_run"]["id"])  # lazy polling when someone looks
    return out


@router.post("/retrain/pause", dependencies=[Depends(require_admin)])
def pause(db: Session = Depends(get_db)):
    set_state(db, "retrain_paused", True)
    return {"paused": True}


@router.post("/retrain/resume", dependencies=[Depends(require_admin)])
def resume(db: Session = Depends(get_db)):
    set_state(db, "retrain_paused", False)
    return {"paused": False}


class TriggerIn(BaseModel):
    mode: Optional[str] = Field(default=None, pattern="^(manual|auto)$")


@router.post("/retrain/trigger", dependencies=[Depends(require_admin)])
def trigger(body: TriggerIn | None = None, db: Session = Depends(get_db)):
    try:
        return orch.trigger(db, body.mode if body else None)
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.get("/retrain/runs/{run_id}/bundle", dependencies=[Depends(require_admin)])
def bundle(run_id: int, db: Session = Depends(get_db)):
    r = db.get(RetrainRun, run_id)
    if not r or not r.bundle_path or not Path(r.bundle_path).exists():
        raise HTTPException(404, "bundle not available")
    return FileResponse(r.bundle_path, filename=Path(r.bundle_path).name, media_type="application/zip")
