"""Thin wrapper over the official Kaggle API (v1.2 automatic retraining).

`import kaggle` authenticates at import time, so it is imported lazily and only on the auto-retrain path.
Auth: KAGGLE_API_TOKEN (preferred) or legacy KAGGLE_USERNAME + KAGGLE_KEY.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from ..config import REPO_ROOT, get_settings


class KaggleUnavailable(RuntimeError):
    pass


def _api():
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except Exception as e:  # pragma: no cover - depends on environment
        raise KaggleUnavailable(f"kaggle package not usable: {e}")
    api = KaggleApi()
    try:
        api.authenticate()
    except BaseException as e:  # the CLI may call sys.exit on missing credentials
        raise KaggleUnavailable(f"Kaggle authentication failed: {e}")
    return api


def push_dataset_version(bundle_dir: Path, notes: str) -> str:
    s = get_settings()
    if not s.kaggle_dataset_slug:
        raise KaggleUnavailable("KAGGLE_DATASET_SLUG not set")
    meta = json.loads((bundle_dir / "dataset-metadata.json").read_text())
    meta["id"] = s.kaggle_dataset_slug
    (bundle_dir / "dataset-metadata.json").write_text(json.dumps(meta, indent=2))
    res = _api().dataset_create_version(str(bundle_dir), version_notes=notes, quiet=True, dir_mode="zip")
    return str(getattr(res, "url", "") or res)


def kernel_status(kernel_slug: str) -> str:
    """Returns one of: queued, running, complete, error, cancelled, unknown."""
    res = _api().kernels_status(kernel_slug)
    status = getattr(res, "status", None) or (res.get("status") if isinstance(res, dict) else None)
    return str(status).lower().split(".")[-1] if status else "unknown"


def push_kernel(version_tag: str, work_dir: Path) -> str:
    """Push the training notebook with VERSION_TAG / HF_MODEL_REPO injected; returns the kernel slug."""
    s = get_settings()
    if not s.kaggle_kernel_slug:
        raise KaggleUnavailable("KAGGLE_KERNEL_SLUG not set")
    status = kernel_status(s.kaggle_kernel_slug) if _kernel_exists(s.kaggle_kernel_slug) else "unknown"
    if status in ("queued", "running"):
        raise RuntimeError(f"kernel {s.kaggle_kernel_slug} is already {status}; not pushing")
    kdir = work_dir / "kernel"
    if kdir.exists():
        shutil.rmtree(kdir)
    kdir.mkdir(parents=True)
    nb = json.loads((REPO_ROOT / "training" / "finetune_gemma_lora.ipynb").read_text(encoding="utf-8"))
    for cell in nb["cells"]:
        src = cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"])
        if "VERSION_TAG =" in src and "HF_MODEL_REPO =" in src:
            lines = []
            for line in src.splitlines():
                if line.startswith("VERSION_TAG ="):
                    line = f'VERSION_TAG = "{version_tag}"'
                elif line.startswith("HF_MODEL_REPO =") and s.hf_model_repo:
                    line = f'HF_MODEL_REPO = "{s.hf_model_repo}"'
                lines.append(line)
            cell["source"] = "\n".join(lines)
    (kdir / "finetune_gemma_lora.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
    meta = json.loads((REPO_ROOT / "training" / "kernel-metadata.json").read_text())
    meta["id"] = s.kaggle_kernel_slug
    meta["dataset_sources"] = [s.kaggle_dataset_slug]
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    _api().kernels_push(str(kdir), acc="NvidiaTeslaT4")
    return s.kaggle_kernel_slug


def _kernel_exists(slug: str) -> bool:
    try:
        kernel_status(slug)
        return True
    except Exception:
        return False


def download_outputs(kernel_slug: str, dest: Path) -> Optional[dict]:
    dest.mkdir(parents=True, exist_ok=True)
    _api().kernels_output(kernel_slug, str(dest), force=True, quiet=True)
    p = next(iter(dest.rglob("eval.json")), None)
    return json.loads(p.read_text()) if p else None
