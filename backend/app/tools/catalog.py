"""Deterministic business tools: catalog search, line resolution, compatibility, order history, stock, pricing.

Prices and discounts come ONLY from get_price(). No model ever produces a price.
"""
from __future__ import annotations

import json
import re
from email.utils import parseaddr
from functools import lru_cache
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process

from evallib.normalize import canonical_sku, norm_code, norm_text

from ..config import DATA_DIR
from .schemas import Candidate, LineItemIn, OrderLine, PriceResult, ResolveResult, StockResult

CONFIDENT_SCORE = 0.9
CONFIDENT_MARGIN = 0.1

CATEGORY_WORDS = {
    "capacitors": ["cap", "caps", "capacitor", "capacitors", "mfd", "uf"],
    "contactors": ["contactor", "contactors"],
    "motors": ["motor", "motors", "blower", "hp"],
    "filters": ["filter", "filters", "merv"],
    "thermostats": ["thermostat", "thermostats", "stat", "stats", "t-stat", "tstat", "t-stats", "controller"],
    "belts": ["belt", "belts", "v-belt", "vbelt", "v-belts"],
    "fuses": ["fuse", "fuses"],
    "valves": ["valve", "valves", "bv", "gv", "cv"],
    "fittings": ["elbow", "ell", "90", "45", "tee", "coupling", "union", "reducer", "adapter", "fittings", "fitting"],
    "sealants": ["tape", "sealant", "silicone", "mastic", "dope", "putty", "caulk", "firestop", "ptfe"],
}
_NUM_TOKEN = re.compile(r"\d+(?:[./x-]\d+)*[a-z]*")
# trade shorthand -> catalog words (deterministic; applied to queries and catalog text alike)
SYNONYMS = {"bv": "ball valve", "gv": "gate valve", "cv": "check valve", "cu": "copper", "galv": "galvanized",
            "bi": "black iron", "cond": "condenser", "tstat": "thermostat", "t-stat": "thermostat",
            "stat": "thermostat", "cap": "capacitor", "mfd": "uf", "ell": "elbow", "ma": "male adapter",
            "vbelt": "v-belt"}
_DROP = {"in", "inch", "inches", "the", "a", "an", "of", "for", "some", "pcs", "ea", "each", "qty", "x"}


def search_norm(text: str) -> str:
    """Normalize for matching: lowercase, expand shorthand, singularize, drop filler words."""
    out = []
    for tok in norm_text(text).replace(",", " ").split():
        tok = tok.strip(".-")
        if not tok or tok in _DROP:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss") and not tok[-2].isdigit():
            tok = tok[:-1]
        out.extend(SYNONYMS.get(tok, tok).split())
    return " ".join(out)


def guess_category(text: str) -> Optional[str]:
    toks = set(re.findall(r"[a-z\-]+|\d+", norm_text(text)))
    best, hits = None, 0
    for cat, words in CATEGORY_WORDS.items():
        h = sum(1 for w in words if w in toks)
        if h > hits:
            best, hits = cat, h
    return best


def _num_tokens(text: str) -> set[str]:
    return set(_NUM_TOKEN.findall(norm_text(text).replace('"', "")))


class Catalog:
    def __init__(self, data_dir: Path = DATA_DIR):
        load = lambda n: json.loads((data_dir / f"{n}.json").read_text(encoding="utf-8"))  # noqa: E731
        self.products: list[dict] = load("catalog")
        self.customers: list[dict] = load("customers")
        self.orders: list[dict] = load("orders")
        self.equipment: list[dict] = load("equipment")
        self.by_sku = {p["sku"]: p for p in self.products}
        self.by_domain = {c["email_domain"].lower(): c for c in self.customers}
        self.by_id = {c["id"]: c for c in self.customers}
        self.eq_by_code = {norm_code(e["model"]): e for e in self.equipment}
        self.alias_index: dict[str, list[str]] = {}
        self._entries: list[tuple[str, str]] = []  # (sku, normalized alias/name/description)
        for p in self.products:
            for a in p["aliases"] + [p["name"], p["long_description"]]:
                key = search_norm(a)
                skus = self.alias_index.setdefault(key, [])
                if p["sku"] not in skus:
                    skus.append(p["sku"])
                self._entries.append((p["sku"], key))

    # ------------------------------------------------------------------ helpers
    def _cand(self, sku: str, score: float, reason: str) -> Candidate:
        p = self.by_sku[sku]
        return Candidate(sku=sku, name=p["name"], category=p["category"], score=round(min(max(score, 0), 1), 3),
                         reason=reason, unit=p["unit"], stock_qty=p["stock_qty"])

    def customer_for_sender(self, sender: str) -> Optional[dict]:
        addr = parseaddr(sender)[1].lower()
        domain = addr.split("@")[-1] if "@" in addr else ""
        return self.by_domain.get(domain)

    # ------------------------------------------------------------------ tools
    def search_catalog(self, query: str, limit: int = 5, category: Optional[str] = None) -> list[Candidate]:
        """Exact SKU -> exact alias/name -> fuzzy (best alias per SKU, size/number aware)."""
        sku = canonical_sku(query)
        if sku and sku in self.by_sku:
            return [self._cand(sku, 1.0, "exact SKU match")]
        q = search_norm(query)
        out: dict[str, Candidate] = {}
        exact = [s for s in self.alias_index.get(q, []) if not category or self.by_sku[s]["category"] == category]
        for s in exact:
            out[s] = self._cand(s, 0.97 if len(exact) == 1 else 0.85,
                                "exact alias match" + ("" if len(exact) == 1 else " (shared alias)"))
        qnums = _num_tokens(q)
        entries = [(s, t) for s, t in self._entries if not category or self.by_sku[s]["category"] == category]
        best: dict[str, tuple[float, str]] = {}
        for text, score, idx in process.extract(q, [t for _, t in entries], scorer=fuzz.token_set_ratio,
                                                limit=max(limit * 12, 40)):
            s, _ = entries[idx]
            val = score / 100 * 0.93
            if qnums:
                have = _num_tokens(text)
                val *= 0.55 + 0.45 * (len(qnums & have) / len(qnums))
            if val > best.get(s, (0.0, ""))[0]:
                best[s] = (val, text)
        for s, (val, text) in best.items():
            if s not in out:
                out[s] = self._cand(s, val, f"fuzzy match on '{text}'")
        return sorted(out.values(), key=lambda c: c.score, reverse=True)[:limit]

    def _confident_direct(self, description: str, category: str) -> bool:
        """True if the description alone already pins down one SKU (specific size/spec), so the equipment
        guess is not needed even when the email mentions fitting something."""
        top = self.search_catalog(description, limit=2, category=category)
        return bool(top) and top[0].score >= CONFIDENT_SCORE and (len(top) < 2 or top[0].score - top[1].score >= CONFIDENT_MARGIN)

    def get_compatible_parts(self, equipment_model: str, category: Optional[str] = None) -> list[Candidate]:
        eq = self.eq_by_code.get(norm_code(equipment_model))
        if not eq:
            return []
        out = []
        for cat, sku in eq["compatible_parts"].items():
            if category and cat != category:
                continue
            out.append(self._cand(sku, 0.98 if category else 0.9,
                                  f"listed as compatible with {eq['model']} ({eq['brand']} {eq['type_name']})"))
        return out

    def get_last_order_items(self, customer_id: Optional[str], hint: Optional[str] = None) -> list[OrderLine]:
        """Lines from the customer's most recent order that matches the hint's category, or the whole last order."""
        if not customer_id:
            return []
        orders = sorted((o for o in self.orders if o["customer_id"] == customer_id), key=lambda o: o["date"])
        if not orders:
            return []
        cat = guess_category(hint or "")
        if cat:
            for o in reversed(orders):
                lines = [l for l in o["lines"] if self.by_sku[l["sku"]]["category"] == cat]
                if lines:
                    return [OrderLine(order_id=o["order_id"], date=o["date"], sku=l["sku"],
                                      name=self.by_sku[l["sku"]]["name"], qty=l["qty"]) for l in lines]
            return []
        last = orders[-1]
        return [OrderLine(order_id=last["order_id"], date=last["date"], sku=l["sku"],
                          name=self.by_sku[l["sku"]]["name"], qty=l["qty"]) for l in last["lines"]]

    def check_stock(self, sku: str, qty: int) -> StockResult:
        p = self.by_sku[sku]
        return StockResult(sku=sku, stock_qty=p["stock_qty"], requested=qty, sufficient=p["stock_qty"] >= qty)

    def get_price(self, sku: str, customer_id: Optional[str], qty: int) -> PriceResult:
        p = self.by_sku[sku]
        c = self.by_id.get(customer_id) if customer_id else None
        tier_disc = c["tier_discount"] if c else 0.0
        vol = 0.0
        for br in (c["volume_breaks"] if c else []):
            if qty >= br["min_qty"]:
                vol = max(vol, br["extra_discount"])
        disc = round(tier_disc + vol, 4)
        unit_price = round(p["list_price"] * (1 - disc), 2)
        return PriceResult(sku=sku, customer_id=customer_id, tier=c["tier"] if c else None, qty=qty,
                           list_price=p["list_price"], tier_discount=tier_disc, volume_discount=vol,
                           discount_pct=disc, unit_price=unit_price, line_total=round(unit_price * qty, 2))

    def resolve_line_item(self, item: LineItemIn, customer_id: Optional[str],
                          missing_kinds: frozenset[str] = frozenset()) -> ResolveResult:
        """Top-3 SKU candidates with scores/reasons. CONFIDENT iff top score >= 0.9, margin >= 0.1,
        quantity present and stock sufficient; otherwise NEEDS_REVIEW with human-readable reasons."""
        reasons: list[str] = []
        expanded: list[OrderLine] = []
        cands: list[Candidate] = []
        cat = guess_category(item.description)

        if item.part_number:
            cands = self.search_catalog(item.part_number, limit=3)
            if not cands or cands[0].score < 1.0:
                reasons.append(f"part number '{item.part_number}' not found in catalog")
                cands = self.search_catalog(item.description, limit=3) or cands
        elif item.compatible_with:
            cands = self.get_compatible_parts(item.compatible_with, cat)
            if not cands:
                reasons.append(f"equipment model '{item.compatible_with}' not on file")
                cands = self.search_catalog(item.description, limit=3, category=cat)
        elif item.reference == "previous_order":
            lines = self.get_last_order_items(customer_id, item.description)
            if not customer_id:
                reasons.append("unknown customer: no order history")
            elif not lines:
                reasons.append("no matching past order found")
            elif len(lines) == 1 or not cat:
                if not cat and len(lines) > 1:
                    reasons.append(f"repeat of order {lines[0].order_id} ({len(lines)} lines) - confirm")
                expanded = lines
                for l in lines:
                    cands.append(self._cand(l.sku, 0.95 if len(lines) == 1 else 0.7,
                                            f"from order {l.order_id} on {l.date} (qty {l.qty})"))
            else:
                for l in lines:
                    cands.append(self._cand(l.sku, 0.75, f"from order {l.order_id} on {l.date} (qty {l.qty})"))
                reasons.append("several past lines match")
        elif "equipment_model" in missing_kinds and cat and not self._confident_direct(item.description, cat):
            reasons.append("equipment model not given")
            on_site = self.by_id[customer_id]["equipment_on_site"] if customer_id in self.by_id else []
            cands = [self._cand(self.eq_by_code[norm_code(m)]["compatible_parts"][cat], 0.6,
                                f"fits {m} (equipment on file for this customer)")
                     for m in on_site if cat in self.eq_by_code[norm_code(m)]["compatible_parts"]]
            cands = cands or self.search_catalog(item.description, limit=3, category=cat)
        else:
            cands = (self.search_catalog(item.description, limit=3, category=cat) if cat else []) or \
                self.search_catalog(item.description, limit=3)
        if "size_or_spec" in missing_kinds:
            reasons.append("size / spec not specified")
        # dedupe + top 3
        seen, top = set(), []
        for c in sorted(cands, key=lambda c: c.score, reverse=True):
            if c.sku not in seen:
                seen.add(c.sku)
                top.append(c)
        top = top[:3]

        if not top:
            reasons.append("no catalog match")
        else:
            best = top[0]
            margin = best.score - (top[1].score if len(top) > 1 else 0.0)
            if best.score < CONFIDENT_SCORE:
                reasons.append(f"best match score {best.score:.2f} < {CONFIDENT_SCORE}")
            if margin < CONFIDENT_MARGIN:
                reasons.append(f"ambiguous: top two candidates within {margin:.2f}")
            if item.quantity is None and expanded:
                reasons.append(f"quantity copied from order {expanded[0].order_id} - confirm")
            elif item.quantity is None:
                reasons.append("quantity missing")
            elif item.quantity is not None:
                st = self.check_stock(best.sku, item.quantity)
                if not st.sufficient:
                    reasons.append(f"insufficient stock ({st.stock_qty} on hand, {item.quantity} requested)")
        status = "CONFIDENT" if not reasons else "NEEDS_REVIEW"
        return ResolveResult(candidates=top, status=status, reasons=reasons, expanded=expanded)


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return Catalog()
