"""Visitor-pasted emails must not be listed publicly."""
from conftest import ADMIN, ext, item

CUST = "Andre Brennan <andre.brennan@pinecrest-mech.example>"


def test_pasted_emails_are_not_in_the_public_trace_list(client, student):
    student([(ext(items=[item("belts", 2)]), -0.01)])
    pasted = client.post("/api/quotes/process?stream=false", json={"sender": CUST, "subject": "private", "body": "need 2 belts privacy-check"}).json()
    sample = client.post("/api/quotes/process?stream=false", json={"sample_id": "clean-multi"}).json()
    public = {t["id"] for t in client.get("/api/traces?limit=200").json()}
    assert sample["trace_id"] in public and pasted["trace_id"] not in public
    admin = {t["id"] for t in client.get("/api/traces?limit=200", headers=ADMIN).json()}
    assert pasted["trace_id"] in admin
    # the owner can still open their own trace by its link
    assert client.get(f"/api/traces/{pasted['trace_id']}").status_code == 200


def test_rate_limit_uses_the_proxy_appended_address(client):
    from starlette.requests import Request
    from app.api.deps import client_ip
    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.9")], "client": ("10.0.0.1", 1)}
    assert client_ip(Request(scope)) == "203.0.113.9"
