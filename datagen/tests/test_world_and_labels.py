import json
from collections import Counter

import pytest

from datagen.build_world import build_world
from datagen.labels import build_label
from datagen.sample_scenarios import INTENT_MIX, ScenarioSampler, sample_all
from evallib.schema import Extraction


@pytest.fixture(scope="module")
def world():
    return build_world(7)


def test_world_is_deterministic(world):
    again = build_world(7)
    assert json.dumps(world, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_world_shape(world):
    cat = world["catalog"]
    assert len(cat) == 200 and len({p["sku"] for p in cat}) == 200
    assert Counter(p["category"] for p in cat) == Counter({c: 20 for c in Counter(p["category"] for p in cat)})
    assert all(p["unique_aliases"] for p in cat)
    assert len(world["equipment"]) == 40 and len(world["customers"]) == 20
    by_sku = {p["sku"]: p for p in cat}
    for eq in world["equipment"]:
        for c, sku in eq["compatible_parts"].items():
            assert by_sku[sku]["category"] == c and eq["model"] in by_sku[sku]["compatible_equipment"]
    for c in world["customers"]:
        assert c["email_domain"].endswith(".example")
        assert 3 <= sum(o["customer_id"] == c["id"] for o in world["orders"]) <= 10


def test_scenario_distribution():
    scs = sample_all(600, 42)
    counts = Counter(s["intent"] for s in scs)
    for intent, share in INTENT_MIX.items():
        assert abs(counts[intent] / 600 - share) < 0.03
    assert sample_all(50, 42) == sample_all(50, 42)


def _fake_written(sc):
    """Write an email that satisfies every constraint, to test label construction."""
    parts, spans = [], []
    for i, it in enumerate(sc["items"]):
        chunk = f"{it['quantity_text'] + ' ' if it['quantity_text'] else ''}{it['phrase']}"
        if it["part_number_text"] and it["part_number_text"] not in it["phrase"]:
            chunk += f" ({it['part_number_text']})"
        if it["equipment_model_text"]:
            chunk += f" for our unit {it['equipment_model_text']}"
        parts.append(chunk)
        spans.append({"index": i, "description": it["phrase"]})
    body = "Hi team,\nplease quote: " + "; ".join(parts) + "."
    if sc["needed_by"]:
        body += f" Need it {sc['needed_by']}."
    if sc["order_ref"]:
        body += f" Ref {sc['order_ref']}."
    body += "\nThanks, " + sc["sender_name"]
    return {"subject": "parts", "body": body, "items": spans}


def test_labels_from_consistent_emails(world):
    sampler = ScenarioSampler(world, 3)
    ok = 0
    for i, intent in enumerate(["quote_request"] * 30 + ["return_request"] * 5 + ["order_status"] * 5 +
                                ["product_question"] * 5 + ["other"] * 5):
        sc = sampler.sample(f"T{i}", intent)
        label, errs = build_label(sc, _fake_written(sc))
        assert label is not None, errs
        Extraction.model_validate(label)
        if intent in ("order_status", "other"):
            assert label["items"] == []
        for it, lab in zip(sc["items"], label["items"]):
            assert lab["quantity"] == it["quantity"]
            if it["quantity"] is None and it["reference"] is None and intent in ("quote_request", "return_request"):
                assert f"quantity: {lab['description']}" in label["missing_info"]
        ok += 1
    assert ok == 50


def test_label_rejects_missing_verbatim(world):
    sampler = ScenarioSampler(world, 5)
    for i in range(200):
        sc = sampler.sample(f"X{i}", "quote_request")
        if any(it["part_number_text"] for it in sc["items"]):
            break
    w = _fake_written(sc)
    pn = next(it["part_number_text"] for it in sc["items"] if it["part_number_text"])
    w["body"] = w["body"].replace(pn, "")
    w["items"] = [{"index": s["index"], "description": s["description"].replace(pn, "").strip() or "x"}
                  for s in w["items"]]
    label, errs = build_label(sc, w)
    assert label is None and errs
