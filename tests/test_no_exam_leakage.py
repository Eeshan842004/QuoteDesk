"""The sealed exam must never appear in anything we train on (exact hash or near-duplicate > 90)."""
import json
from pathlib import Path

import numpy as np
import pytest
from rapidfuzz import fuzz, process

from evallib.normalize import email_hash, norm_text

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ROOT / "data" / "splits"
TRAINABLE = [SPLITS / "train.jsonl", SPLITS / "val.jsonl", SPLITS / "fewshot.jsonl",
             ROOT / "data" / "kaggle_bundle" / "train.jsonl", ROOT / "data" / "kaggle_bundle" / "corrections.jsonl",
             ROOT / "data" / "corrections" / "corrections.jsonl",
             SPLITS / "corrections_pool.jsonl"]


def _rows(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


@pytest.fixture(scope="module")
def exam():
    if not (SPLITS / "exam_hashes.json").exists():
        pytest.skip("splits not built yet")
    hashes = set(json.loads((SPLITS / "exam_hashes.json").read_text(encoding="utf-8"))["hashes"])
    bodies = [r["body"] for r in _rows(SPLITS / "exam.jsonl") + _rows(SPLITS / "exam_hard.jsonl")]
    return hashes, bodies


def test_hashes_cover_exam(exam):
    hashes, bodies = exam
    assert {email_hash(b) for b in bodies} <= hashes


def test_no_exact_exam_email_in_trainable_files(exam):
    hashes, _ = exam
    for p in TRAINABLE:
        leaked = [r.get("id") for r in _rows(p) if email_hash(r["body"]) in hashes]
        assert not leaked, f"{p.name} contains exam emails: {leaked[:5]}"


def test_no_near_duplicate_exam_email_in_training(exam):
    _, exam_bodies = exam
    ex = [norm_text(b) for b in exam_bodies]
    for p in TRAINABLE:
        rows = _rows(p)
        if not rows:
            continue
        sim = process.cdist([norm_text(r["body"]) for r in rows], ex, scorer=fuzz.ratio, workers=-1, dtype=np.uint8)
        assert sim.max() <= 90, f"{p.name} has a near-duplicate of an exam email (ratio {sim.max()})"
