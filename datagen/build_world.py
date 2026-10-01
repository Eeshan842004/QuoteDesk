"""Build the fictional world: catalog, equipment, customers, orders. Pure code, seeded, byte-deterministic.

    python -m datagen.build_world            # writes data/{catalog,equipment,customers,orders}.json
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

from . import world_vocab as V
from .config import DATA_DIR

PER_CATEGORY = 20


def _price(x: float) -> float:
    """Round to a retail-looking price (.49 / .99 endings)."""
    x = max(x, 0.5)
    whole = int(x)
    return round(whole + (0.49 if x - whole < 0.5 else 0.99), 2)


def _stock(rng: random.Random, typical: int) -> int:
    r = rng.random()
    if r < 0.10:
        return 0
    if r < 0.25:
        return rng.randint(1, 5)
    return rng.randint(typical // 3, typical)


# ---------------------------------------------------------------- category generators
# each returns a list of dicts with: name, attributes, aliases, long_description, unit, price, stock_typical

def _valves(rng):
    combos = [(s, t, m, c) for s in V.SIZES for t in V.VALVE_TYPES for m in V.VALVE_MATERIALS for c in V.VALVE_CONNECTIONS
              if not (m == "PVC" and c in ("sweat", "press", "PEX")) and not (m == "stainless" and c == "sweat")]
    rng.shuffle(combos)
    out = []
    for size, vtype, mat, conn in combos[:PER_CATEGORY]:
        s = size.rstrip('"')
        mult = {"brass": 1.0, "bronze": 1.3, "stainless": 2.2, "PVC": 0.45}[mat] * {"ball": 1.0, "gate": 1.1, "check": 1.15}[vtype]
        base = [9, 12, 18, 29, 38, 56][V.SIZES.index(size)]
        out.append(dict(
            name=f"{size} {mat} {vtype} valve, {conn}",
            attributes={"type": vtype, "size": size, "material": mat, "connection": conn},
            aliases=[f"{s} {mat} {vtype} valve {conn}", f"{s} {mat} {V.VALVE_ABBR[vtype]} {conn}",
                     f"{s}\" {vtype} valve", f"{s} {vtype} valve", f"{mat} {vtype} valves"],
            long_description=f"{V.SIZE_WORDS[size]} {mat} {vtype} valve with {conn} ends",
            unit="each", price=base * mult, stock_typical=120))
    return out


def _fittings(rng):
    combos = [(s, t, m) for s in V.SIZES[:5] for t in V.FITTING_TYPES for m in V.FITTING_MATERIALS]
    rng.shuffle(combos)
    out = []
    for size, ftype, mat in combos[:PER_CATEGORY]:
        s = size.rstrip('"')
        boxed = mat in ("copper", "PVC sch40") and size in ('1/2"', '3/4"')
        base = [1.2, 1.8, 2.9, 4.6, 6.1][V.SIZES.index(size)]
        mult = {"copper": 1.0, "PVC sch40": 0.35, "black iron": 1.6, "galvanized": 1.7, "CPVC": 0.5}[mat]
        mult *= {"90 elbow": 1, "45 elbow": 1, "tee": 1.4, "coupling": 0.7, "union": 3.2, "reducer": 1.1,
                 "cap": 0.6, "male adapter": 1.2}[ftype]
        short = V.FITTING_SHORT[ftype]
        out.append(dict(
            name=f"{size} {mat} {ftype}" + (" (box of 10)" if boxed else ""),
            attributes={"type": ftype, "size": size, "material": mat, "pack_qty": 10 if boxed else 1},
            aliases=[f"{s} {V.FITTING_MAT_SHORT[mat]} {short}", f"{s}\" {mat} {ftype}",
                     f"{s} {ftype}s", f"{mat} {ftype}s"],
            long_description=f"{V.SIZE_WORDS[size]} {mat} {ftype} fittings",
            unit="box" if boxed else "each", price=base * mult * (9 if boxed else 1), stock_typical=300))
    return out


def _contactors(rng):
    combos = [(p, a, c) for p in V.CONTACTOR_POLES for a in V.CONTACTOR_AMPS for c in V.CONTACTOR_COILS]
    rng.shuffle(combos)
    out = []
    for poles, amps, coil in combos[:PER_CATEGORY]:
        out.append(dict(
            name=f"{poles}-pole {amps}A contactor, {coil} coil",
            attributes={"poles": poles, "amps": amps, "coil_voltage": coil},
            aliases=[f"{amps}A {poles}P contactor {coil} coil", f"{poles} pole {amps} amp contactor {coil}",
                     f"{coil} contactor {poles}p {amps}a", f"{amps} amp contactor", f"{poles} pole contactor"],
            long_description=f"{poles}-pole {amps} amp definite purpose contactor with a {coil} coil",
            unit="each", price=14 + poles * 6 + amps * 0.3 + {"24V": 0, "120V": 3, "208/240V": 5}[coil],
            stock_typical=80))
    return out


def _capacitors(rng):
    combos = [("dual run", u, v) for u in V.CAP_DUAL for v in V.CAP_VOLTS]
    combos += [("single run", u, v) for u in V.CAP_RUN for v in V.CAP_VOLTS]
    combos += [("start", u, "250V") for u in V.CAP_START]
    rng.shuffle(combos)
    # guarantee enough dual and single run caps for equipment compatibility
    dual = [c for c in combos if c[0] == "dual run"][:9]
    single = [c for c in combos if c[0] == "single run"][:7]
    start = [c for c in combos if c[0] == "start"][:4]
    out = []
    for ctype, uf, volt in dual + single + start:
        uf_plus = uf.replace("/", "+")
        if ctype == "dual run":
            base = 18 + float(uf.split("/")[0]) * 0.25
        elif ctype == "single run":
            base = 9 + float(uf) * 0.3
        else:
            base = 16.0
        out.append(dict(
            name=f"{uf} uF {volt} {ctype} capacitor",
            attributes={"type": ctype, "microfarads": uf, "voltage": volt},
            aliases=[f"{uf} {volt} {ctype} cap", f"{uf_plus} mfd {volt} {ctype} capacitor",
                     f"{uf} uf {volt} cap", f"{uf} cap", f"{ctype} capacitor"],
            long_description=f"{ctype} capacitor, {uf} microfarad, rated {volt}",
            unit="each", price=base + (3 if volt == "440V" else 0), stock_typical=150))
    return out


def _filters(rng):
    combos = [(s, m) for s in V.FILTER_SIZES for m in V.FILTER_MERV]
    rng.shuffle(combos)
    out = []
    for size, merv in combos[:PER_CATEGORY]:
        depth = size.split("x")[2]
        base = {"1": 7.0, "2": 12.0, "4": 26.0}[depth] * {8: 1.0, 11: 1.35, 13: 1.7}[merv]
        w, h, d = size.split("x")
        out.append(dict(
            name=f"Pleated air filter {size} MERV {merv}",
            attributes={"size": size, "merv": merv},
            aliases=[f"{size} merv {merv}", f"{w} by {h} by {d} merv {merv} pleated", f"{size} MERV{merv} filters",
                     f"{size} filters", f"{w}x{h} filters"],
            long_description=f"pleated air filters, {w} by {h} by {d} inch, MERV {merv}",
            unit="each", price=base, stock_typical=400))
    return out


def _motors(rng):
    out = []
    for mtype, n in V.MOTOR_TYPES.items():
        combos = [(hp, rpm, v) for hp in V.MOTOR_HP for rpm in V.MOTOR_RPM for v in V.MOTOR_VOLTS]
        rng.shuffle(combos)
        short = {"condenser fan motor": "cond fan motor", "blower motor": "blower motor",
                 "exhaust fan motor": "exhaust motor"}[mtype]
        for hp, rpm, volt in combos[:n]:
            hp_val = float(Fraction(hp))
            out.append(dict(
                name=f"{hp} HP {rpm} RPM {volt} {mtype}",
                attributes={"type": mtype, "hp": hp, "rpm": rpm, "voltage": volt},
                aliases=[f"{hp} hp {rpm} rpm {short} {volt}", f"{hp}hp {rpm} {mtype} {volt}",
                         f"{short} {hp} hp {rpm} rpm {volt}", f"{hp} hp {mtype}", f"{mtype}"],
                long_description=f"{mtype}, {hp} horsepower, {rpm} RPM, {volt}",
                unit="each", price=75 + hp_val * 180, stock_typical=25))
    return out


def _thermostats(rng):
    out = []
    items = [(grp, t) for grp, ts in V.THERMOSTAT_TYPES.items() for t in ts]
    # 11 models x 2 colors = 22; keep every non-conventional variant so each equipment type has a match
    combos = [(grp, t, c) for grp, t in items for c in ("white", "black")]
    rng.shuffle(combos)
    others = [c for c in combos if c[0] != "conventional"]
    conventional = [c for c in combos if c[0] == "conventional"]
    for grp, t, color in (others + conventional)[:PER_CATEGORY]:
        base = {"conventional": 45, "heat pump": 70, "line voltage": 45, "walk-in controller": 118}[grp]
        if "Wi-Fi" in t:
            base += 90
        out.append(dict(
            name=f"{t} thermostat, {color}",
            attributes={"group": grp, "model": t, "color": color},
            aliases=[f"{t} tstat {color}", f"{color} {t} thermostat", f"{t} t-stat", f"{grp} thermostat"],
            long_description=f"{color} {t} thermostat",
            unit="each", price=base, stock_typical=60))
    return out


def _belts(rng):
    combos = [(sec, ln) for sec, lens in V.BELT_SECTIONS.items() for ln in lens]
    rng.shuffle(combos)
    out = []
    for sec, ln in combos[:PER_CATEGORY]:
        code = f"{sec}{ln}"
        price = {"A": 8 + ln * 0.12, "B": 12 + ln * 0.18, "4L": 6 + ln * 0.012, "5L": 9 + ln * 0.016}[sec]
        out.append(dict(
            name=f"V-belt {code}",
            attributes={"section": sec, "length": ln, "code": code},
            aliases=[f"{code} belt", f"{code} v-belt", f"{code} vbelt", f"{sec} section belt"],
            long_description=f"{sec}-section V-belt, size {code}",
            unit="each", price=price, stock_typical=90))
    return out


def _fuses(rng):
    combos = [(c, a, v, s) for c in V.FUSE_CLASSES for a in V.FUSE_AMPS for v in V.FUSE_VOLTS for s in V.FUSE_SPEED]
    rng.shuffle(combos)
    out = []
    for cls, amps, volt, speed in combos[:PER_CATEGORY]:
        base = {"RK5": 38, "CC": 52, "J": 71, "K5": 30}[cls] + amps * 0.5 + (12 if volt == "600V" else 0)
        out.append(dict(
            name=f"Class {cls} {amps}A {volt} {speed} fuse (box of 10)",
            attributes={"class": cls, "amps": amps, "voltage": volt, "speed": speed, "pack_qty": 10},
            aliases=[f"{amps}A {cls} {volt} {speed} fuse", f"class {cls} {amps} amp {volt} {speed}",
                     f"{amps}a {cls} {speed} fuses {volt}", f"{amps} amp fuses", f"class {cls} fuses"],
            long_description=f"class {cls} {speed} fuses, {amps} amp, {volt}",
            unit="box", price=base, stock_typical=70))
    return out


def _sealants(rng):
    out = []
    for stype, size, unit, base in V.SEALANTS:
        short = V.SEALANT_SHORT[stype]
        out.append(dict(
            name=f"{stype}, {size}",
            attributes={"type": stype, "size": size},
            aliases=[f"{size} {short}", f"{short} {size}", f"{stype} {size}", f"{short}"],
            long_description=f"{stype} in a {size} size",
            unit=unit, price=base, stock_typical=250))
    return out


GENERATORS = {"valves": _valves, "fittings": _fittings, "contactors": _contactors, "capacitors": _capacitors,
              "filters": _filters, "motors": _motors, "thermostats": _thermostats, "belts": _belts,
              "fuses": _fuses, "sealants": _sealants}


# ---------------------------------------------------------------- builders

def build_catalog(rng: random.Random) -> list[dict]:
    catalog = []
    for cat in V.CATEGORIES:
        items = GENERATORS[cat](rng)
        assert len(items) == PER_CATEGORY, (cat, len(items))
        numbers = rng.sample(range(1000, 10000), PER_CATEGORY)
        for num, it in zip(sorted(numbers), items):
            catalog.append({
                "sku": f"NB-{V.CATEGORY_CODE[cat]}-{num}",
                "name": it["name"],
                "category": cat,
                "attributes": it["attributes"],
                "aliases": list(dict.fromkeys(it["aliases"])),
                "long_description": it["long_description"],
                "unit": it["unit"],
                "list_price": _price(it["price"]),
                "stock_qty": _stock(rng, it["stock_typical"]),
                "compatible_equipment": [],
            })
    # mark aliases that identify exactly one SKU (safe for "alias" scenarios)
    counts = defaultdict(int)
    for p in catalog:
        for a in p["aliases"]:
            counts[a.lower()] += 1
    for p in catalog:
        p["unique_aliases"] = [a for a in p["aliases"] if counts[a.lower()] == 1]
    return catalog


def _compatible_candidates(catalog, etype, category):
    pool = [p for p in catalog if p["category"] == category]
    if category == "motors":
        pool = [p for p in pool if p["attributes"]["type"] == V.MOTOR_FOR[etype]]
    elif category == "thermostats":
        pool = [p for p in pool if p["attributes"]["group"] == V.THERMOSTAT_FOR[etype]]
    elif category == "capacitors":
        pool = [p for p in pool if p["attributes"]["type"] == V.CAPACITOR_FOR[etype]]
    elif category == "valves":
        pool = [p for p in pool if p["attributes"]["size"] in ('3/4"', '1"') and p["attributes"]["material"] != "PVC"] or pool
    elif category == "contactors":
        pool = [p for p in pool if p["attributes"]["coil_voltage"] == "24V"] or pool
    return pool


def build_equipment(rng: random.Random, catalog: list[dict]) -> list[dict]:
    equipment, used = [], set()
    brand_cycle = 0
    for etype, n in V.EQUIPMENT_TYPE_COUNTS.items():
        plain, caps, categories = V.EQUIPMENT_TYPES[etype]
        for _ in range(n):
            brand, code = V.EQUIPMENT_BRANDS[brand_cycle % len(V.EQUIPMENT_BRANDS)]
            brand_cycle += 1
            while True:
                model = f"{code}-{etype}{rng.choice(caps)}-{rng.choice(V.EQUIPMENT_REVS)}"
                if model not in used:
                    used.add(model)
                    break
            cap = int(model.split("-")[1][len(etype):])
            compat = {}
            for cat in categories:
                pool = _compatible_candidates(catalog, etype, cat)
                compat[cat] = rng.choice(pool)["sku"]
            equipment.append({"model": model, "brand": brand, "type": etype, "type_name": plain,
                              "capacity": cap, "compatible_parts": compat})
    by_sku = {p["sku"]: p for p in catalog}
    for eq in equipment:
        for sku in eq["compatible_parts"].values():
            by_sku[sku]["compatible_equipment"].append(eq["model"])
    for p in catalog:
        p["compatible_equipment"].sort()
    return equipment


def build_customers(rng: random.Random, equipment: list[dict]) -> list[dict]:
    customers = []
    tiers = ["A"] * 5 + ["B"] * 8 + ["C"] * 7
    rng.shuffle(tiers)
    firsts, lasts = V.FIRST_NAMES[:], V.LAST_NAMES[:]
    rng.shuffle(firsts)
    rng.shuffle(lasts)
    for i, ((company, slug), tier) in enumerate(zip(V.CUSTOMER_COMPANIES, tiers)):
        domain = f"{slug}.example"
        contacts = []
        for j in range(rng.choice([1, 1, 2])):
            first, last = firsts[(i * 2 + j) % len(firsts)], lasts[(i * 3 + j) % len(lasts)]
            local = rng.choice([f"{first}.{last}", f"{first[0]}{last}", f"{first}"]).lower()
            contacts.append({"name": f"{first} {last}", "email": f"{local}@{domain}",
                             "title": rng.choice(V.TITLES), "phone": f"555-01{rng.randint(0, 99):02d}"})
        customers.append({
            "id": f"C{i + 1:03d}", "company": company, "email_domain": domain, "contacts": contacts,
            "tier": tier, "tier_discount": V.TIER_DISCOUNT[tier], "volume_breaks": V.VOLUME_BREAKS,
            "equipment_on_site": sorted(e["model"] for e in rng.sample(equipment, rng.randint(2, 4))),
        })
    return customers


def build_orders(rng: random.Random, customers: list[dict], catalog: list[dict], equipment: list[dict]) -> list[dict]:
    orders, next_id = [], 51200
    eq_by_model = {e["model"]: e for e in equipment}
    consumables = [p for p in catalog if p["category"] in ("filters", "fittings", "sealants", "valves", "fuses")]
    start = date(2026, 1, 5)
    for c in customers:
        n = rng.randint(3, 10)
        days = sorted(rng.sample(range(0, 262), n))
        favored = [sku for m in c["equipment_on_site"] for sku in eq_by_model[m]["compatible_parts"].values()]
        for k, d in enumerate(days):
            lines = {}
            for _ in range(rng.randint(1, 5)):
                p = rng.choice(favored) if favored and rng.random() < 0.5 else rng.choice(consumables)["sku"]
                lines[p] = lines.get(p, 0) + rng.choice([1, 2, 2, 4, 5, 6, 10, 12, 24])
            status = "delivered"
            if k == n - 1:
                status = rng.choice(["processing", "shipped", "backordered", "delivered"])
            elif k == n - 2:
                status = rng.choice(["shipped", "delivered", "delivered"])
            next_id += rng.randint(3, 40)
            orders.append({
                "order_id": f"NBO-{next_id}", "customer_id": c["id"],
                "po_number": f"PO-{rng.randint(1000, 9999)}" if rng.random() < 0.6 else None,
                "date": (start + timedelta(days=d)).isoformat(), "status": status,
                "lines": [{"sku": s, "qty": q} for s, q in lines.items()],
            })
    orders.sort(key=lambda o: (o["customer_id"], o["date"]))
    return orders


def build_world(seed: int = 7) -> dict:
    rng = random.Random(seed)
    catalog = build_catalog(rng)
    equipment = build_equipment(rng, catalog)
    customers = build_customers(rng, equipment)
    orders = build_orders(rng, customers, catalog, equipment)
    return {"catalog": catalog, "equipment": equipment, "customers": customers, "orders": orders}


def write_world(world: dict, out_dir: Path = DATA_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, obj in world.items():
        (out_dir / f"{name}.json").write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_world(data_dir: Path = DATA_DIR) -> dict:
    return {n: json.loads((data_dir / f"{n}.json").read_text(encoding="utf-8"))
            for n in ("catalog", "equipment", "customers", "orders")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    w = build_world(args.seed)
    write_world(w)
    print({k: len(v) for k, v in w.items()})
