"""Admin "Correct result" flow: save a correction -> counter -> training bundle."""
import json
import zipfile
from pathlib import Path

import pytest

from app.config import get_settings
from app.tools import get_catalog

from conftest import ADMIN, ext, item

CUST = "Andre Brennan <andre.brennan@pinecrest-mech.example>"
ROOT = Path(__file__).resolve().parents[2]


def _process(client, student, body, model_ext):
    student([(model_ext, -0.01)])
    return client.post("/api/quotes/process?stream=false", json={"sender": CUST, "subject": "q", "body": body}).json()


def _status(client):
    return client.get("/api/retrain/status").json()


def _fix(items, intent="quote_request", **kw):
    return {"intent": intent, "urgency": "normal", "items": items, **kw}


def test_requires_admin(client, student):
    q = _process(client, student, "need 2 45/5 capacitors correction-auth", ext(items=[item("45/5 capacitors", 2)]))
    r = client.post(f"/api/quotes/{q['id']}/correction", json=_fix([{"description": "45/5 capacitors", "quantity": 2}]))
    assert r.status_code == 401


def test_vague_item_correction_becomes_one_training_example(client, student):
    """The model picked a specific SKU for '45/5 capacitors' without enough information: the admin says the
    description is under-specified, and the saved correction teaches the model to flag it."""
    body = "hi pls quote 2 45/5 capacitors for the roof unit correction-vague"
    q = _process(client, student, body, ext(items=[item("45/5 capacitors", 2)]))
    assert q["lines"][0]["sku"]  # the tools guessed a SKU
    before = _status(client)["corrections_pending"]

    r = client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN, json=_fix(
        [{"description": "45/5 capacitors", "quantity": 2, "needs_size_or_spec": True}], note="needs voltage")).json()
    assert r["saved"] and r["retrain"]["corrections_pending"] == before + 1
    quote = r["quote"]
    assert quote["extraction_source"] == "admin_corrected" and quote["flags"]["admin_corrected"] is True
    assert quote["extraction"]["missing_info"] == ["size_or_spec: 45/5 capacitors"]
    # the model original output is kept, and the admin flags (not the rule guess) decide the target
    assert "size_or_spec: 45/5 capacitors" not in quote["student_extraction"]["missing_info"]

    # training example is exactly the corrected target, with the shared system prompt
    from sqlalchemy import select
    from app.db import Correction, session_scope
    with session_scope() as db:
        c = db.scalars(select(Correction).where(Correction.quote_id == q["id"], Correction.counts_for_training.is_(True))).one()
        ex = c.training_example
    assert json.loads(ex["target"])["missing_info"] == ["size_or_spec: 45/5 capacitors"]
    assert ex["messages"][-1]["role"] == "assistant" and ex["body"] == body

    # saving the same quote again replaces it: still counts once
    r2 = client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN, json=_fix(
        [{"description": "45/5 capacitors", "quantity": 3, "needs_size_or_spec": True}])).json()
    assert r2["retrain"]["corrections_pending"] == before + 1


def test_quantity_and_order_number_missing_info_come_from_rules(client, student):
    body = "need 45/5 capacitors and the 60A contactor please correction-rules"
    q = _process(client, student, body, ext(items=[item("45/5 capacitors", 5), item("60A contactor", 5)]))
    r = client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN, json=_fix(
        [{"description": "45/5 capacitors"}, {"description": "60A contactor", "quantity": 4}])).json()
    assert r["quote"]["extraction"]["missing_info"] == ["quantity: 45/5 capacitors"]
    o = _process(client, student, "where is our order from last week? correction-order", ext("order_status"))
    r = client.post(f"/api/quotes/{o['id']}/correction", headers=ADMIN, json=_fix([], intent="order_status", urgency="high")).json()
    assert r["quote"]["extraction"]["missing_info"] == ["order_number"] and r["quote"]["status"] == "no_quote"


def test_text_must_be_copied_from_the_email(client, student):
    q = _process(client, student, "need 2 belts correction-verbatim", ext(items=[item("belts", 2)]))
    r = client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN, json=_fix([{"description": "V-belt B39", "quantity": 2}]))
    assert r.status_code == 422 and "not written in the email" in r.json()["detail"]
    r = client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN,
                    json=_fix([{"description": "belts", "quantity": 2}], needed_by="by friday"))
    assert r.status_code == 422 and "deadline" in r.json()["detail"]


def test_identical_to_model_output_is_not_a_correction(client, student):
    q = _process(client, student, "need 2 belts correction-noop", ext(items=[item("belts", 2, unit=None)]))
    first = q["extraction"]
    r = client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN, json=_fix([{"description": "belts", "quantity": first["items"][0]["quantity"]}]))
    assert r.status_code == 422 and "no changes" in r.json()["detail"]


def test_reject_alone_is_never_a_correction(client, student):
    q = _process(client, student, "need 2 belts correction-reject", ext(items=[item("belts", 2)]))
    before = _status(client)["corrections_pending"]
    r = client.post(f"/api/quotes/{q['id']}/decision", headers=ADMIN, json={
        "decision": "reject", "lines": [{"line_no": 1, "action": "edit_quantity", "quantity": 9, "reason": "misread"}]}).json()
    assert r["status"] == "rejected" and r["corrections"] == []
    assert _status(client)["corrections_pending"] == before


def test_public_decisions_and_corrections_never_count(client, student):
    q = _process(client, student, "need 2 belts correction-public", ext(items=[item("belts", 2)]))
    before = _status(client)["corrections_pending"]
    client.post(f"/api/quotes/{q['id']}/decision", json={"decision": "approve", "lines": [
        {"line_no": 1, "action": "edit_quantity", "quantity": 9, "reason": "misread"}]})
    assert _status(client)["corrections_pending"] == before


def test_line_edits_after_a_full_correction_do_not_double_count(client, student):
    q = _process(client, student, "need 2 belts and 3 fuses correction-double", ext(items=[item("belts", 2), item("fuses", 3)]))
    before = _status(client)["corrections_pending"]
    client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN, json=_fix([{"description": "belts", "quantity": 2}, {"description": "fuses", "quantity": 4}]))
    client.post(f"/api/quotes/{q['id']}/decision", headers=ADMIN, json={"decision": "approve", "lines": [
        {"line_no": 1, "action": "edit_quantity", "quantity": 7, "reason": "misread"}]})
    assert _status(client)["corrections_pending"] == before + 1


def test_same_email_corrected_twice_counts_once(client, student):
    body = "need 2 belts correction-same-email"
    a = _process(client, student, body, ext(items=[item("belts", 2)]))
    b = _process(client, student, body, ext(items=[item("belts", 2)]))
    before = _status(client)["corrections_pending"]
    for q in (a, b):
        client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN, json=_fix([{"description": "belts", "quantity": 5}]))
    assert _status(client)["corrections_pending"] == before + 1


def test_decided_quote_cannot_be_corrected(client, student):
    q = _process(client, student, "need 2 belts correction-decided", ext(items=[item("belts", 2)]))
    client.post(f"/api/quotes/{q['id']}/decision", json={"decision": "approve", "lines": []})
    r = client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN, json=_fix([{"description": "belts", "quantity": 5}]))
    assert r.status_code == 409


def test_exam_emails_are_refused(client, student):
    exam = ROOT / "data" / "splits" / "exam.jsonl"
    if not exam.exists():
        pytest.skip("splits not built")
    rec = json.loads(exam.read_text(encoding="utf-8").splitlines()[0])
    student([(ext(items=[item("x", 1)]), -0.01)])
    q = client.post("/api/quotes/process?stream=false", json={"sender": rec["sender"], "subject": rec["subject"], "body": rec["body"]}).json()
    r = client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN, json=_fix([{"description": "x", "quantity": 2}]))
    assert r.status_code == 422 and "sealed exam" in r.json()["detail"]


def test_threshold_prepares_a_training_bundle_with_the_corrections(client, student, monkeypatch):
    """At RETRAIN_THRESHOLD real corrections the existing workflow builds the next version's training bundle."""
    s = get_settings()
    start = _status(client)["corrections_pending"]
    monkeypatch.setattr(s, "retrain_threshold", start + 3)
    last = None
    for i in range(3):
        q = _process(client, student, f"need {i + 2} belts and fuses correction-trigger-{i}", ext(items=[item("belts", 2)]))
        assert not _status(client)["active_run"]
        last = client.post(f"/api/quotes/{q['id']}/correction", headers=ADMIN,
                           json=_fix([{"description": "belts", "quantity": 7 + i}, {"description": "fuses", "quantity": 1}])).json()
    assert last["retrain"]["triggered"] is True
    run = _status(client)["active_run"]
    assert run["state"] == "AWAITING_MANUAL" and run["corrections_count"] == start + 3
    assert _status(client)["corrections_pending"] == 0  # consumed by the run

    z = Path(get_settings().work_dir) / f"run_{run['id']}" / f"quotedesk-data-{run['candidate_version']}.zip"
    with zipfile.ZipFile(z) as zf:
        corr = [json.loads(l) for l in zf.read("corrections.jsonl").decode().splitlines()]
        assert {"train.jsonl", "exam.jsonl", "manifest.json"} <= set(zf.namelist())
    assert len(corr) == start + 3 and all(c["source"] == "correction" for c in corr)
