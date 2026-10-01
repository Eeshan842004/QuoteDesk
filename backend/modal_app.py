"""Modal deployment (Starter plan, CPU only, scale to zero).

    modal secret create quotedesk-secrets --from-dotenv .env.modal     # or create it in the dashboard
    modal run backend/modal_app.py::prefetch                           # one-off: cache weights in the Volume
    modal deploy backend/modal_app.py                                  # -> https://<workspace>--quotedesk-web.modal.run

Cost guards: max 1 container, no keep-warm (min_containers=0), scaledown_window=300 s, 2 cores + 4 GiB
(~$0.126 per warm hour at Modal's published CPU/memory prices). See PLAN.md section 2 for the monthly estimate.
"""
from __future__ import annotations

import os
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "quotedesk"
AUTO_RETRAIN = os.getenv("AUTO_RETRAIN_ENABLED", "false") == "true"  # read at deploy time

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("torch==2.14.0", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install_from_requirements(str(ROOT / "backend" / "requirements.txt"))
    .env({"HF_HOME": "/cache/hf", "QD_DATA_DIR": "/app/data", "QD_EVAL_DIR": "/app/eval",
          "QD_WORK_DIR": "/cache/work", "PYTHONPATH": "/app/backend:/app:/app/eval",
          "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "2", "LOAD_STUDENT_ON_STARTUP": "false"})
    .add_local_dir(ROOT / "backend" / "app", "/app/backend/app", ignore=["**/__pycache__/**", "*.db"])
    .add_local_dir(ROOT / "eval" / "evallib", "/app/eval/evallib", ignore=["**/__pycache__/**"])
    .add_local_dir(ROOT / "eval" / "reports", "/app/eval/reports", ignore=["**/*_predictions.jsonl", "**/*_calls.jsonl"])
    .add_local_dir(ROOT / "datagen", "/app/datagen", ignore=["**/__pycache__/**", "tests/**"])
    .add_local_dir(ROOT / "training", "/app/training")
    .add_local_dir(ROOT / "data", "/app/data", ignore=["generated/**", "kaggle_bundle/**", "*.zip", "corrections/**"])
)

app = modal.App(APP_NAME, image=image)
hf_cache = modal.Volume.from_name("quotedesk-hf-cache", create_if_missing=True)
secrets = [modal.Secret.from_name("quotedesk-secrets")]


@app.cls(cpu=2.0, memory=4096, min_containers=0, max_containers=1, scaledown_window=300, timeout=600,
         volumes={"/cache": hf_cache}, secrets=secrets, enable_memory_snapshot=True)
@modal.concurrent(max_inputs=8)
class Web:
    @modal.enter(snap=True)
    def load_model(self):
        """Runs once, before the memory snapshot: import the app and load the student into RAM (no DB here)."""
        import torch
        torch.set_num_threads(2)
        from app.config import get_settings
        from app.models import get_registry
        s = get_settings()
        if s.student_enabled:
            get_registry().load(s.hf_model_repo, s.student_adapter_revision, local_path=s.student_local_adapter)

    @modal.enter(snap=False)
    def after_restore(self):
        from app.main import create_app
        self.web_app = create_app(load_student=False)  # lifespan syncs the DB's live version (hot-swap if newer)

    @modal.asgi_app()
    def web(self):
        return self.web_app


@app.function(volumes={"/cache": hf_cache}, secrets=secrets, timeout=1800, cpu=1.0, memory=2048)
def prefetch():
    """Download base weights + adapter into the Volume so cold starts don't hit the Hub."""
    from huggingface_hub import snapshot_download
    base = os.getenv("STUDENT_BASE_MODEL", "unsloth/gemma-3-270m-it")
    token = os.getenv("HF_TOKEN")
    print("base:", snapshot_download(base, token=token))
    repo, rev = os.getenv("HF_MODEL_REPO"), os.getenv("STUDENT_ADAPTER_REVISION")
    if repo and rev:
        print("adapter:", snapshot_download(repo, revision=rev, token=token))
    hf_cache.commit()


if AUTO_RETRAIN:  # v1.2: only deployed when enabled, so no idle cron cost otherwise
    @app.function(schedule=modal.Period(minutes=15), volumes={"/cache": hf_cache}, secrets=secrets, timeout=900,
                  cpu=0.5, memory=1024)
    def retrain_tick():
        from app.db import init_db
        from app.retrain.orchestrator import tick
        init_db()
        print(tick())
        hf_cache.commit()
