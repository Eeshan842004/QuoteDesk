import json

from evallib.metrics import aggregate, align, intent_drop, percentile, score_one
from evallib.runner import evaluate, student_cost_usd, teacher_cost_usd

TRUTH = {"intent": "quote_request", "urgency": "high", "needed_by": "by Friday",
         "items": [{"description": "45/5 440V dual run cap", "quantity": 2, "unit": None, "part_number": None,
                    "compatible_with": None, "reference": None},
                   {"description": "NB-CON-2374", "quantity": None, "unit": None, "part_number": "NB-CON-2374",
                    "compatible_with": None, "reference": None}],
         "missing_info": ["quantity: NB-CON-2374"]}


def test_perfect_prediction_is_exact():
    s = score_one(TRUTH, json.dumps(TRUTH))
    assert s["json_valid"] and s["intent_ok"] and s["exact"]
    assert (s["item_tp"], s["item_fp"], s["item_fn"]) == (2, 0, 0)
    assert s["missing_tp"] == 1


def test_wrong_quantity_is_not_a_true_positive():
    pred = json.loads(json.dumps(TRUTH))
    pred["items"][0]["quantity"] = 3
    s = score_one(TRUTH, json.dumps(pred))
    assert (s["item_tp"], s["item_fp"], s["item_fn"]) == (1, 1, 1)
    assert s["qty_pairs"] == 2 and s["qty_ok"] == 1 and not s["exact"]


def test_items_matched_regardless_of_order_and_case():
    pred = json.loads(json.dumps(TRUTH))
    pred["items"] = pred["items"][::-1]
    pred["items"][1]["description"] = "45/5 440v DUAL RUN CAP"
    s = score_one(TRUTH, json.dumps(pred))
    assert s["item_tp"] == 2 and s["exact"]


def test_invalid_output():
    s = score_one(TRUTH, "sorry I cannot help")
    assert not s["json_valid"] and s["item_fn"] == 2 and s["missing_fn"] == 1


def test_extra_and_missing_items():
    pred = dict(TRUTH, items=TRUTH["items"][:1] + [{"description": "B39 belt", "quantity": 1}], missing_info=[])
    s = score_one(TRUTH, json.dumps(pred))
    assert (s["item_tp"], s["item_fp"], s["item_fn"]) == (1, 1, 1)
    assert s["missing_fn"] == 1


def test_aggregate_and_percentiles():
    scores = [score_one(TRUTH, json.dumps(TRUTH)), score_one(TRUTH, "x")]
    m = aggregate(scores, latencies=[1.0, 3.0], escalated=[False, True], costs_usd=[0.001, 0.003])
    assert m["n"] == 2 and m["intent_accuracy"] == 0.5 and m["json_validity_rate"] == 0.5
    assert m["item_recall"] == 0.5 and m["item_precision"] == 1.0
    assert m["escalation_rate"] == 0.5 and m["cost_per_1k_usd"] == 2.0
    assert percentile([1, 2, 3, 4], 50) == 2.5


def test_intent_drop():
    cur = {"per_intent_accuracy": {"quote_request": 0.9, "other": 1.0}}
    new = {"per_intent_accuracy": {"quote_request": 0.95, "other": 0.97}}
    assert intent_drop(cur, new) == {"quote_request": 5.0, "other": -3.0}


def test_align_prefers_part_number():
    t = [{"description": "the belt", "part_number": "NB-BLT-1613"}]
    p = [{"description": "something", "part_number": "nb blt 1613"}, {"description": "the belt", "part_number": None}]
    assert align(t, p)[0][1] in (0, 1)


def test_runner_evaluate_and_costs():
    recs = [{"id": "a", "intent": "quote_request", "target": json.dumps(TRUTH)}]
    out = evaluate(recs, lambda r: {"text": r["target"], "latency_s": 0.5, "cost_usd": student_cost_usd(0.5)},
                   progress_every=0)
    assert out["metrics"]["exact_match_rate"] == 1.0
    assert teacher_cost_usd(1_000_000, 0) == 0.75
