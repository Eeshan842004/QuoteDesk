from app.retrain.corrections import corrected_extraction
from app.retrain.gate import evaluate_gate
from app.tools import get_catalog

from conftest import ADMIN, ext, item

CUST = "Andre Brennan <andre.brennan@pinecrest-mech.example>"


def _quote(client, student, qty=4):
    skus = [p["sku"] for p in get_catalog().products if p["stock_qty"] >= 30][:2]
    student([(ext(items=[item(skus[0], qty, part_number=skus[0]), item(skus[1], 2, part_number=skus[1])]), -0.01)])
    return client.post("/api/quotes/process?stream=false",
                       json={"sender": CUST, "subject": "q", "body": f"{qty} {skus[0]} and 2 {skus[1]}"}).json(), skus


def test_public_decision_is_sandboxed(client, student):
    q, _ = _quote(client, student)
    r = client.post(f"/api/quotes/{q['id']}/decision",
                    json={"decision": "approve", "lines": [{"line_no": 1, "action": "edit_quantity", "quantity": 9}]})
    body = r.json()
    assert r.status_code == 200 and body["sandbox"] is True
    assert body["corrections"][0]["kind"] == "EXTRACTION" and body["corrections"][0]["counts_for_training"] is False
    assert body["quote"]["status"] == "sent"
    assert client.post(f"/api/quotes/{q['id']}/decision", json={"decision": "approve"}).status_code == 409


def test_admin_corrections_classified_and_counted(client, student):
    q, skus = _quote(client, student)
    other = next(p["sku"] for p in get_catalog().products if p["sku"] not in skus and p["stock_qty"] > 5)
    r = client.post(f"/api/quotes/{q['id']}/decision", headers=ADMIN, json={"decision": "approve", "lines": [
        {"line_no": 1, "action": "edit_quantity", "quantity": 6},
        {"line_no": 2, "action": "change_sku", "sku": other},
        {"action": "add", "sku": other, "quantity": 1, "description": "extra item", "reason": "business"}]}).json()
    kinds = [c["kind"] for c in r["corrections"]]
    assert kinds == ["EXTRACTION", "RESOLUTION", "BUSINESS"]
    assert [c["counts_for_training"] for c in r["corrections"]] == [True, False, False]
    line1 = r["quote"]["lines"][0]
    assert line1["quantity"] == 6 and line1["unit_price"] == get_catalog().get_price(skus[0], "C001", 6).unit_price
    st = client.get("/api/retrain/status").json()
    assert st["corrections_pending"] >= 1


def test_corrected_extraction_updates_missing_info():
    original = ext(items=[item("caps"), item("belts", 2)], missing=["quantity: caps"])
    out = corrected_extraction(original, [{"action": "edit_quantity", "item_index": 0, "quantity": 3},
                                          {"action": "remove", "item_index": 1},
                                          {"action": "add", "description": "B39 belt", "quantity": 1}])
    assert [i["description"] for i in out["items"]] == ["caps", "B39 belt"]
    assert out["items"][0]["quantity"] == 3 and out["missing_info"] == []


def test_gate_rules():
    cur = {"item_f1": 0.80, "json_validity_rate": 0.97, "per_intent_accuracy": {"quote_request": 0.95, "other": 1.0}}
    better = {"item_f1": 0.84, "json_validity_rate": 0.98, "per_intent_accuracy": {"quote_request": 0.96, "other": 0.99}}
    assert evaluate_gate(cur, better, 0.0)["passed"]
    assert not evaluate_gate(cur, better, 0.05)["passed"]  # margin not met
    worse_json = dict(better, json_validity_rate=0.95)
    assert "JSON validity" in evaluate_gate(cur, worse_json, 0.0)["reasons"][0]
    intent_drop = dict(better, per_intent_accuracy={"quote_request": 0.96, "other": 0.95})
    g = evaluate_gate(cur, intent_drop, 0.0)
    assert not g["passed"] and "other" in g["reasons"][0]
    assert evaluate_gate(None, better, 0.0)["passed"]


def _report(f1, validity=0.97):
    return {"system": "tuned", "splits": {"exam": {"item_f1": f1, "json_validity_rate": validity,
                                                   "per_intent_accuracy": {"quote_request": 0.95}}}}


def test_register_promote_reject_rollback(client):
    assert client.post("/api/models/register", json={"version": "v1", "eval_report": _report(0.8)}).status_code == 401
    r1 = client.post("/api/models/register", headers=ADMIN, json={"version": "v1", "eval_report": _report(0.8)}).json()
    assert r1["promoted"]
    r2 = client.post("/api/models/register", headers=ADMIN, json={"version": "v2", "eval_report": _report(0.75)}).json()
    assert not r2["promoted"] and "item F1" in r2["gate"]["reasons"][0]
    r3 = client.post("/api/models/register", headers=ADMIN, json={"version": "v3", "eval_report": _report(0.85)}).json()
    assert r3["promoted"]
    versions = {m["version"]: m["status"] for m in client.get("/api/models").json()["versions"]}
    assert versions == {"v1": "retired", "v2": "rejected", "v3": "live"}
    assert client.post("/api/models/v1/rollback", headers=ADMIN).json()["status"] == "live"
    versions = {m["version"]: m["status"] for m in client.get("/api/models").json()["versions"]}
    assert versions["v1"] == "live" and versions["v3"] == "retired"


def test_pause_resume_requires_admin(client):
    assert client.post("/api/retrain/pause").status_code == 401
    assert client.post("/api/retrain/pause", headers=ADMIN).json() == {"paused": True}
    assert client.get("/api/retrain/status").json()["paused"] is True
    assert client.post("/api/retrain/resume", headers=ADMIN).json() == {"paused": False}


def test_mcp_tools_listed_and_callable(client):
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    init = client.post("/mcp/", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})
    assert init.status_code == 200, init.text
    tools = client.post("/mcp/", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()
    names = {t["name"] for t in tools["result"]["tools"]}
    assert names == {"search_catalog", "resolve_line_item", "get_compatible_parts", "check_stock", "get_price"}
    sku = get_catalog().products[0]["sku"]
    call = client.post("/mcp/", headers=headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                                       "params": {"name": "check_stock", "arguments": {"sku": sku, "qty": 1}}}).json()
    assert sku in str(call["result"])
