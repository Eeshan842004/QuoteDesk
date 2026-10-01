"""No real brand names in the fictional world or in generated emails (docs/DECISIONS.md D3)."""
import json
import re
from pathlib import Path

from datagen import world_vocab as V

ROOT = Path(__file__).resolve().parents[1]
WORLD_FILES = ["catalog.json", "equipment.json", "customers.json", "orders.json"]
EMAIL_FILES = ["generated/verified.jsonl", "splits/train.jsonl", "splits/val.jsonl", "splits/exam.jsonl",
               "splits/exam_hard.jsonl"]


def _hits(text: str, brands: list[str], case_sensitive: bool) -> list[str]:
    flags = 0 if case_sensitive else re.I
    return [b for b in brands if re.search(rf"(?<![A-Za-z]){re.escape(b)}(?![A-Za-z])", text, flags)]


def test_world_files_have_no_real_brands():
    for name in WORLD_FILES:
        p = ROOT / "data" / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        assert not _hits(text, V.REAL_BRANDS_STRICT, False), name
        assert not _hits(text, V.REAL_BRANDS_AMBIGUOUS, True), name


def test_generated_emails_have_no_real_brands():
    for name in EMAIL_FILES:
        p = ROOT / "data" / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            text = json.dumps(rec, ensure_ascii=False)
            assert not _hits(text, V.REAL_BRANDS_STRICT, False), (name, rec.get("scenario_id") or rec.get("id"))
