"""Build the Kaggle dataset bundle (splits + evallib + metadata) and zip it.

    python -m datagen.make_bundle                    # -> data/kaggle_bundle/ and data/quotedesk-data.zip
The same function is used by the v1.1 retrain flow with extra corrections (never exam data).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from evallib.normalize import email_hash

from .config import BUNDLE_DIR, DATA_DIR, EVAL_DIR, ROOT, SPLITS_DIR

SPLIT_FILES = ["train.jsonl", "val.jsonl", "exam.jsonl", "exam_hard.jsonl", "fewshot.jsonl"]
EVALLIB_FILES = ["__init__.py", "schema.py", "prompt.py", "normalize.py", "metrics.py", "runner.py",
                 "system_prompt.txt", "teacher_rules.txt", "pricing.json"]


class LeakageError(RuntimeError):
    pass


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return None


def assert_no_exam_overlap(rows: list[dict], exam_hashes: set[str]):
    bad = [r.get("id") for r in rows if email_hash(r["body"]) in exam_hashes]
    if bad:
        raise LeakageError(f"{len(bad)} training rows match exam emails: {bad[:5]}")


def build_bundle(out_dir: Path = BUNDLE_DIR, corrections: list[dict] | None = None, version_tag: str = "v1",
                 dataset_slug: str | None = None, zip_path: Path | None = None) -> Path:
    exam_hashes = set(json.loads((SPLITS_DIR / "exam_hashes.json").read_text(encoding="utf-8"))["hashes"])
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "evallib").mkdir(parents=True)
    for f in SPLIT_FILES:
        shutil.copy2(SPLITS_DIR / f, out_dir / f)
    train_rows = [json.loads(l) for l in (out_dir / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    val_rows = [json.loads(l) for l in (out_dir / "val.jsonl").read_text(encoding="utf-8").splitlines()]
    assert_no_exam_overlap(train_rows + val_rows, exam_hashes)
    if corrections:
        assert_no_exam_overlap(corrections, exam_hashes)
        with open(out_dir / "corrections.jsonl", "w", encoding="utf-8") as fh:
            for r in corrections:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for f in EVALLIB_FILES:
        src = EVAL_DIR / "evallib" / f
        if src.exists():
            shutil.copy2(src, out_dir / "evallib" / f)
    for f in ("catalog.json", "customers.json", "orders.json", "equipment.json"):
        shutil.copy2(DATA_DIR / f, out_dir / f)

    slug = dataset_slug or os.getenv("KAGGLE_DATASET_SLUG") or "your-kaggle-user/quotedesk-data"
    (out_dir / "dataset-metadata.json").write_text(json.dumps({
        "title": "QuoteDesk extraction data", "id": slug,
        "licenses": [{"name": "CC0-1.0"}],
        "description": "Synthetic, fictional training data for the QuoteDesk email-extraction student model."},
        indent=2), encoding="utf-8")
    files = sorted(p for p in out_dir.rglob("*") if p.is_file())
    manifest = {
        "version_tag": version_tag, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "git_sha": _git_sha(),
        "counts": {f: sum(1 for _ in open(out_dir / f, encoding="utf-8")) for f in SPLIT_FILES},
        "corrections": len(corrections or []),
        "sha256": {str(p.relative_to(out_dir)).replace("\\", "/"): _sha(p) for p in files},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    zip_path = zip_path or DATA_DIR / "quotedesk-data.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out_dir.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(out_dir))
    return zip_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v1")
    a = ap.parse_args()
    z = build_bundle(version_tag=a.tag)
    print("bundle:", BUNDLE_DIR, "zip:", z, f"({z.stat().st_size / 1e6:.2f} MB)")
