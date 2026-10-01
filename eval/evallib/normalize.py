"""Normalizers shared by datagen, eval metrics, and backend tools."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Optional

# Northbeam SKUs: NB-VLV-2041, written by customers as "nb vlv 2041", "NBVLV2041", "NB-VLV 2041", ...
SKU_RE = re.compile(r"\bNB[\s\-_./]?([A-Z]{3})[\s\-_./]?(\d{4})\b", re.I)

UNIT_SYNONYMS = {
    "each": ["each", "ea", "ea.", "pc", "pcs", "pc.", "piece", "pieces", "unit", "units"],
    "box": ["box", "boxes", "bx", "bxs"],
    "case": ["case", "cases", "cs", "cse"],
    "roll": ["roll", "rolls", "rl", "rls"],
    "pack": ["pack", "packs", "pk", "pkg", "pkgs"],
    "ft": ["ft", "ft.", "feet", "foot"],
    "tube": ["tube", "tubes", "tb", "cartridge", "cartridges"],
    "pair": ["pair", "pairs", "pr", "prs"],
}
_UNIT_LOOKUP = {syn: canon for canon, syns in UNIT_SYNONYMS.items() for syn in syns}

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "twenty-four": 24, "thirty": 30, "forty": 40, "fifty": 50, "a dozen": 12, "dozen": 12,
    "two dozen": 24, "half a dozen": 6, "half dozen": 6,
}


def norm_code(s: Optional[str]) -> str:
    """Uppercase alphanumerics only. 'nb vlv-2041' -> 'NBVLV2041'; 'kvl ac36 2' -> 'KVLAC362'."""
    if not s:
        return ""
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def canonical_sku(text: Optional[str]) -> Optional[str]:
    """First Northbeam SKU in text, canonicalized to NB-XXX-0000."""
    m = SKU_RE.search(text or "")
    return f"NB-{m.group(1).upper()}-{m.group(2)}" if m else None


def all_skus(text: Optional[str]) -> list[str]:
    return [f"NB-{m.group(1).upper()}-{m.group(2)}" for m in SKU_RE.finditer(text or "")]


def canonical_unit(word: Optional[str]) -> Optional[str]:
    if not word:
        return None
    return _UNIT_LOOKUP.get(word.strip().lower())


def parse_quantity(text: Optional[str]) -> Optional[int]:
    """Integer quantity from a phrase: '12', '12x', 'x12', 'qty 12', '(12)', '12 ea', 'a dozen', 'two boxes'."""
    if not text:
        return None
    t = text.strip().lower()
    m = re.search(r"\d+", t)
    if m:
        return int(m.group(0))
    for phrase in sorted(NUMBER_WORDS, key=len, reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", t):
            return NUMBER_WORDS[phrase]
    return None


def unit_in_quantity_text(text: Optional[str]) -> Optional[str]:
    """Canonical unit if the quantity phrase contains a unit word ('6 ea' -> each, '2 boxes' -> box)."""
    if not text:
        return None
    t = text.lower()
    for tok in re.findall(r"[a-z]+\.?", t):
        u = canonical_unit(tok) or canonical_unit(tok.rstrip("."))
        if u:
            return u
    m = re.search(r"\d+\s*([a-z]+)", t)  # glued: '6ea', '2bx'
    return canonical_unit(m.group(1)) if m else None


def norm_text(s: Optional[str]) -> str:
    """Lowercase, strip accents and punctuation (keeps / . - inside sizes), collapse whitespace."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9/.\-\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def find_ci(haystack: str, needle: Optional[str]) -> Optional[str]:
    """Case-insensitive substring search; returns the substring *as written in haystack*."""
    if not needle:
        return None
    i = haystack.lower().find(needle.lower())
    return haystack[i : i + len(needle)] if i >= 0 else None


def email_hash(body: str) -> str:
    """Stable hash of an email body for leakage checks (insensitive to case/spacing/punctuation)."""
    return hashlib.sha256(norm_text(body).encode()).hexdigest()
