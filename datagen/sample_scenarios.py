"""Step 1: sample ground-truth scenarios in pure code (no LLM). The scenario IS the label.

    python -m datagen.sample_scenarios            # writes data/generated/scenarios.jsonl (1,800)
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter

from . import world_vocab as V
from .build_world import load_world
from .config import GEN_DIR, DatagenSettings

INTENT_MIX = {"quote_request": 0.65, "product_question": 0.10, "order_status": 0.10,
              "return_request": 0.08, "other": 0.07}
REF_WEIGHTS = {"sku": 0.20, "alias": 0.30, "description": 0.22, "compatibility": 0.13,
               "previous_order": 0.10, "vague": 0.05}
N_ITEMS_WEIGHTS = {1: 0.30, 2: 0.25, 3: 0.20, 4: 0.15, 5: 0.10}
QTY_RANGE = {"valves": (1, 20), "fittings": (2, 60), "contactors": (1, 6), "capacitors": (1, 12),
             "filters": (2, 48), "motors": (1, 4), "thermostats": (1, 10), "belts": (1, 12),
             "fuses": (1, 6), "sealants": (1, 24)}
UNIT_WORDS = {"each": ["ea", "each", "pcs", "pc"], "box": ["box", "boxes", "bx"],
              "roll": ["rolls", "roll"], "tube": ["tubes", "tube"]}
UNIT_WORDS_ODD = {"each": ["units", "pieces"], "box": ["bxs", "boxes"], "roll": ["rls", "rolls"], "tube": ["tubes"]}
QTY_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 8: "eight", 10: "ten",
             12: "a dozen", 20: "twenty", 24: "two dozen"}

URGENCY_CUES = {
    "high": ["ASAP", "urgent", "this is urgent", "unit is down", "emergency call, customer has no cooling",
             "rush order", "need these today if at all possible", "no heat at the site, emergency"],
    "low": ["no rush", "whenever you get a chance", "not urgent", "planning ahead for next month",
            "no hurry on this one"],
}
NEEDED_BY = {
    "high": ["today", "by end of day", "first thing tomorrow", "by tomorrow AM", "by 2pm today"],
    "normal": ["by Friday", "by Monday", "by next Wednesday", "end of next week", "by 10/17", "before Oct 24",
               "by the 15th", "early next week", "by Thursday afternoon"],
    "low": ["sometime next month", "by mid-November", "within the next few weeks", "by end of Q4"],
}
URGENCY_MIX = {"quote_request": (0.20, 0.65, 0.15), "order_status": (0.30, 0.65, 0.05),
               "return_request": (0.05, 0.75, 0.20), "product_question": (0.05, 0.70, 0.25),
               "other": (0.0, 0.85, 0.15)}  # (high, normal, low)
NEEDED_BY_P = {"quote_request": 0.45, "order_status": 0.15, "return_request": 0.10,
               "product_question": 0.10, "other": 0.0}

OTHER_TOPICS = ["update the billing address on the account", "request a W-9 / tax form",
                "thank the team for a fast delivery", "add a new contact to the account",
                "request a copy of an invoice", "ask about a credit application",
                "ask about holiday branch hours", "ask for a new online portal login",
                "report that the delivery driver was great", "ask to be removed from the promo mailing list"]
RETURN_REASONS = ["wrong size", "arrived damaged", "ordered too many", "customer cancelled the job",
                  "wrong voltage", "no longer needed"]
QUESTION_TYPES = ["availability", "specs", "lead_time", "substitute", "compatibility"]
VAGUE_PHRASES = {
    "valves": lambda p: [f"{p['attributes']['type']} valves", f"some {p['attributes']['type']} valves"],
    "fittings": lambda p: [f"{p['attributes']['material']} {p['attributes']['type']}s", f"{p['attributes']['type']}s"],
    "contactors": lambda p: ["contactors", "some contactors"],
    "capacitors": lambda p: [f"{p['attributes']['type']} caps", "capacitors"],
    "filters": lambda p: ["air filters", "pleated filters"],
    "motors": lambda p: [f"{p['attributes']['type']}s"],
    "thermostats": lambda p: ["thermostats", "t-stats"],
    "belts": lambda p: ["v-belts", "belts"],
    "fuses": lambda p: ["fuses", "time delay fuses"],
    "sealants": lambda p: ["thread sealant", "sealant"],
}
PREV_TEMPLATES = ["same {noun} as last time", "the same {noun} we got last time", "same {noun} as our last order",
                  "{noun} like last order", "the {noun} we ordered last time"]
PREV_WHOLE = ["same as our last order", "a repeat of our last order", "same order as last time",
              "exactly what we got last time"]


def _weighted(rng, weights: dict):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def _format_sku(rng, sku: str) -> str:
    """How a customer writes a SKU; digits never change."""
    r = rng.random()
    if r < 0.70:
        return sku
    if r < 0.82:
        return sku.lower()
    if r < 0.92:
        return sku.replace("-", " ")
    return sku.replace("-", "")


def _format_model(rng, model: str) -> str:
    r = rng.random()
    if r < 0.75:
        return model
    if r < 0.90:
        return model.lower()
    return model.replace("-", " ")


_PLURAL = {"box": "boxes", "roll": "rolls", "tube": "tubes"}
_SINGULAR = {v: k for k, v in _PLURAL.items()}


def _agree(u: str, q: int) -> str:
    """'2 box' -> '2 boxes', '1 boxes' -> '1 box'."""
    if q > 1 and u in _PLURAL:
        return _PLURAL[u]
    if q == 1 and u in _SINGULAR:
        return _SINGULAR[u]
    return u


def _quantity_text(rng, q: int, unit: str, mixed_units: bool) -> str:
    use_unit = rng.random() < 0.5
    if q in QTY_WORDS and rng.random() < 0.15:
        word = QTY_WORDS[q]
        if use_unit and not word.endswith("dozen"):
            u = _agree(rng.choice(UNIT_WORDS[unit]), q)
            return f"{word} {u}"
        return word
    if use_unit:
        u = _agree(rng.choice((UNIT_WORDS_ODD if mixed_units else UNIT_WORDS)[unit]), q)
        fmt = rng.choice(["{q} {u}", "{q} {u}", "qty {q} {u}", "{q}{u}"])
        if fmt == "{q}{u}" and u not in ("ea", "pcs", "bx"):
            fmt = "{q} {u}"
        return fmt.format(q=q, u=u)
    return rng.choice(["{q}", "{q}", "{q}x", "qty {q}", "({q})", "x{q}"]).format(q=q)


class ScenarioSampler:
    def __init__(self, world: dict, seed: int):
        self.rng = random.Random(seed)
        self.catalog = world["catalog"]
        self.by_sku = {p["sku"]: p for p in self.catalog}
        self.equipment = world["equipment"]
        self.eq_by_model = {e["model"]: e for e in self.equipment}
        self.customers = world["customers"]
        self.orders_by_customer: dict[str, list] = {}
        for o in world["orders"]:
            self.orders_by_customer.setdefault(o["customer_id"], []).append(o)

    # ---------------------------------------------------------------- items
    def _qty(self, product, mixed_units, p_missing=0.12):
        if self.rng.random() < p_missing:
            return None, None
        lo, hi = QTY_RANGE[product["category"]]
        q = self.rng.randint(lo, hi)
        if product["category"] in ("filters", "fittings") and self.rng.random() < 0.5:
            q = max(lo, round(q / 6) * 6)
        return q, _quantity_text(self.rng, q, product["unit"], mixed_units)

    def _item(self, customer, ref_type, used_skus, noise, allow_whole_prev):
        rng = self.rng
        item = {"ref_type": ref_type, "category": None, "sku": None, "skus": None, "phrase": None,
                "part_number_text": None, "equipment_model_text": None, "equipment_desc": None,
                "quantity": None, "quantity_text": None, "reference": None, "missing": []}
        mixed = noise["mixed_units"]

        if ref_type in ("sku", "alias", "description"):
            p = rng.choice([x for x in self.catalog if x["sku"] not in used_skus])
            item.update(category=p["category"], sku=p["sku"])
            if ref_type == "sku":
                pn = _format_sku(rng, p["sku"])
                noun = rng.choice(V.CATEGORY_NOUNS[p["category"]])
                item["part_number_text"] = pn
                item["phrase"] = pn if rng.random() < 0.5 else f"{pn} {noun}"
            elif ref_type == "alias":
                item["phrase"] = rng.choice(p["unique_aliases"])
            else:
                item["phrase"] = p["long_description"]
            item["quantity"], item["quantity_text"] = self._qty(p, mixed)

        elif ref_type == "compatibility":
            own = customer["equipment_on_site"]
            model = rng.choice(own) if rng.random() < 0.7 else rng.choice(self.equipment)["model"]
            eq = self.eq_by_model[model]
            cat = rng.choice([c for c in eq["compatible_parts"] if eq["compatible_parts"][c] not in used_skus]
                             or list(eq["compatible_parts"]))
            sku = eq["compatible_parts"][cat]
            p = self.by_sku[sku]
            noun = rng.choice(["condenser fan motor", "fan motor", "motor"]) if (
                cat == "motors" and p["attributes"]["type"] == "condenser fan motor") else (
                rng.choice(["blower motor", "motor"]) if cat == "motors" and p["attributes"]["type"] == "blower motor"
                else rng.choice(V.CATEGORY_NOUNS[cat]))
            item.update(category=cat, phrase=noun, equipment_desc=f"{eq['brand']} {eq['type_name']}")
            if rng.random() < 0.75:
                item["equipment_model_text"] = _format_model(rng, model)
                item["sku"] = sku
            else:
                item["missing"].append("equipment_model")
            item["quantity"], item["quantity_text"] = self._qty(p, mixed)

        elif ref_type == "previous_order":
            orders = self.orders_by_customer[customer["id"]]
            last = orders[-1]
            if allow_whole_prev and rng.random() < 0.35:
                item.update(phrase=rng.choice(PREV_WHOLE), skus=[l["sku"] for l in last["lines"]],
                            reference="previous_order", category="order")
                return item
            recent_lines = [l for o in orders[-3:] for l in o["lines"] if l["sku"] not in used_skus]
            line = rng.choice(recent_lines or orders[-1]["lines"])
            p = self.by_sku[line["sku"]]
            noun = rng.choice(V.CATEGORY_NOUNS[p["category"]])
            if not noun.endswith("s") and rng.random() < 0.5:
                noun = noun + "s"
            item.update(category=p["category"], sku=p["sku"], reference="previous_order",
                        phrase=rng.choice(PREV_TEMPLATES).format(noun=noun))
            if rng.random() < 0.5:
                item["quantity"], item["quantity_text"] = self._qty(p, mixed, p_missing=0.0)

        elif ref_type == "vague":
            p = rng.choice(self.catalog)
            item.update(category=p["category"], phrase=rng.choice(VAGUE_PHRASES[p["category"]](p)))
            item["missing"].append("size_or_spec")
            item["quantity"], item["quantity_text"] = self._qty(p, mixed, p_missing=0.3)

        if item["sku"]:
            used_skus.add(item["sku"])
        return item

    # ---------------------------------------------------------------- scenario
    def _noise(self, intent):
        rng = self.rng
        return {
            "typos": rng.choices([0, 1, 2, 3], weights=[0.40, 0.35, 0.18, 0.07])[0],
            "abbreviations": rng.random() < 0.45,
            "shorthand": rng.random() < 0.30,
            "forwarded_thread": rng.random() < 0.10,
            "signature_junk": rng.random() < 0.35,
            "lowercase": rng.random() < 0.10,
            "mixed_units": rng.random() < 0.20,
            "embedded_instruction": rng.random() < 0.03,
        }

    def sample(self, sid: str, intent: str) -> dict:
        rng = self.rng
        customer = rng.choice(self.customers)
        contact = rng.choice(customer["contacts"])
        noise = self._noise(intent)
        ph, pn, pl = URGENCY_MIX[intent]
        urgency = rng.choices(["high", "normal", "low"], weights=[ph, pn, pl])[0]
        needed_by = None
        if rng.random() < NEEDED_BY_P[intent]:
            needed_by = rng.choice(NEEDED_BY[urgency])
        sc = {
            "scenario_id": sid, "customer_id": customer["id"], "company": customer["company"],
            "sender_name": contact["name"], "sender_email": contact["email"], "sender_title": contact["title"],
            "sender_phone": contact["phone"], "intent": intent, "urgency": urgency,
            "urgency_cue": rng.choice(URGENCY_CUES[urgency]) if urgency != "normal" else None,
            "needed_by": needed_by, "order_ref": None, "topic": None, "items": [], "noise": noise,
        }
        used: set = set()
        if intent == "quote_request":
            n = _weighted(rng, N_ITEMS_WEIGHTS)
            for k in range(n):
                ref = _weighted(rng, REF_WEIGHTS)
                sc["items"].append(self._item(customer, ref, used, noise, allow_whole_prev=(n == 1)))
        elif intent == "product_question":
            qtype = rng.choice(QUESTION_TYPES)
            ref = rng.choice(["sku", "alias", "alias", "description"])
            it = self._item(customer, ref, used, noise, allow_whole_prev=False)
            it["quantity"], it["quantity_text"] = None, None
            if qtype == "compatibility":
                model = rng.choice(customer["equipment_on_site"])
                it["equipment_model_text"] = _format_model(rng, model)
                it["equipment_desc"] = f"{self.eq_by_model[model]['brand']} {self.eq_by_model[model]['type_name']}"
            sc["topic"] = qtype
            sc["items"].append(it)
        elif intent == "return_request":
            orders = self.orders_by_customer[customer["id"]]
            order = rng.choice(orders[-4:])
            lines = rng.sample(order["lines"], k=min(len(order["lines"]), rng.choice([1, 1, 2])))
            for line in lines:
                p = self.by_sku[line["sku"]]
                ref = rng.choice(["sku", "alias", "alias", "description"])
                it = {"ref_type": ref, "category": p["category"], "sku": p["sku"], "skus": None, "phrase": None,
                      "part_number_text": None, "equipment_model_text": None, "equipment_desc": None,
                      "quantity": None, "quantity_text": None, "reference": None, "missing": []}
                if ref == "sku":
                    it["part_number_text"] = _format_sku(rng, p["sku"])
                    it["phrase"] = it["part_number_text"]
                elif ref == "alias":
                    it["phrase"] = rng.choice(p["unique_aliases"])
                else:
                    it["phrase"] = p["long_description"]
                if rng.random() < 0.85:
                    q = rng.randint(1, line["qty"])
                    it["quantity"], it["quantity_text"] = q, _quantity_text(rng, q, p["unit"], noise["mixed_units"])
                sc["items"].append(it)
            if rng.random() < 0.6:
                sc["order_ref"] = order["order_id"] if (rng.random() < 0.6 or not order["po_number"]) else order["po_number"]
            sc["topic"] = rng.choice(RETURN_REASONS)
        elif intent == "order_status":
            orders = self.orders_by_customer[customer["id"]]
            order = rng.choice(orders[-3:])
            if rng.random() < 0.7:
                if order["po_number"] and rng.random() < 0.4:
                    sc["order_ref"] = rng.choice([order["po_number"], order["po_number"].replace("-", " "),
                                                  "PO# " + order["po_number"][3:]])
                else:
                    oid = order["order_id"]
                    sc["order_ref"] = rng.choice([oid, oid.lower(), "order " + oid[4:], "#" + oid[4:]])
        else:
            sc["topic"] = rng.choice(OTHER_TOPICS)
        sc["difficulty"] = difficulty(sc)
        return sc


def difficulty(sc: dict) -> str:
    n = sc["noise"]
    score = max(0, len(sc["items"]) - 1) * 0.8 + n["typos"]
    score += 0.5 * n["abbreviations"] + 1.0 * n["shorthand"] + 1.0 * n["forwarded_thread"]
    score += 0.5 * n["signature_junk"] + 0.5 * n["lowercase"] + 0.5 * n["mixed_units"] + 1.0 * n["embedded_instruction"]
    for it in sc["items"]:
        score += {"compatibility": 1.0, "previous_order": 1.0, "vague": 1.0, "description": 0.5}.get(it["ref_type"], 0)
        if it["quantity"] is None and it["reference"] is None and sc["intent"] in ("quote_request", "return_request"):
            score += 1.0
    return "easy" if score < 2 else ("medium" if score < 4.5 else "hard")


def sample_all(n: int, seed: int) -> list[dict]:
    world = load_world()
    sampler = ScenarioSampler(world, seed)
    rng = random.Random(seed + 1)
    intents = []
    for intent, share in INTENT_MIX.items():
        intents += [intent] * round(n * share)
    intents = (intents + ["quote_request"] * n)[:n]
    rng.shuffle(intents)
    return [sampler.sample(f"S{i + 1:05d}", intent) for i, intent in enumerate(intents)]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ds = DatagenSettings()
    ap.add_argument("--n", type=int, default=ds.n_scenarios)
    ap.add_argument("--seed", type=int, default=ds.seed)
    args = ap.parse_args()
    scenarios = sample_all(args.n, args.seed)
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(GEN_DIR / "scenarios.jsonl", "w", encoding="utf-8") as f:
        for s in scenarios:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(len(scenarios), Counter(s["intent"] for s in scenarios), Counter(s["difficulty"] for s in scenarios))
    print(Counter(it["ref_type"] for s in scenarios for it in s["items"]))
