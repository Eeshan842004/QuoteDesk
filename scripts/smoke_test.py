"""End-to-end smoke test against a running backend (local or deployed).

    python scripts/smoke_test.py --api https://<workspace>--quotedesk-web.modal.run [--frontend https://x.vercel.app]
Checks health, samples, all 8 samples through the pipeline (one via SSE), traces, eval, models, and CORS.
"""
import argparse
import json
import sys
import time

import httpx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--frontend", default=None, help="origin to test CORS with")
    a = ap.parse_args()
    fails = []

    def check(name, cond, detail=""):
        print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
        if not cond:
            fails.append(name)

    with httpx.Client(base_url=a.api, timeout=240) as c:
        t0 = time.time()
        h = c.get("/api/health").json()
        check("health", h.get("status") == "ok", f"({time.time() - t0:.1f}s, student={h['student']['state']})")
        samples = c.get("/api/samples").json()
        check("8 samples", len(samples) == 8)
        for s in samples:
            t = time.time()
            r = c.post("/api/quotes/process?stream=false", json={"sample_id": s["id"]})
            ok = r.status_code == 200
            q = r.json() if ok else {}
            check(f"sample {s['id']}", ok and q.get("id") and q.get("trace_id"),
                  f"{time.time() - t:.1f}s status={q.get('status')} path={(q.get('flags') or {}).get('path')}")
            if ok:
                tr = c.get(f"/api/traces/{q['trace_id']}").json()
                check(f"  trace {s['id']}", len(tr.get("spans", [])) >= 4)
        events = []
        with c.stream("POST", "/api/quotes/process", json={"sample_id": "clean-multi"}) as r:
            for line in r.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
        check("SSE stream", "step" in events and events[-1] == "done", f"{len(events)} events")
        check("traces list", len(c.get("/api/traces").json()) >= 1)
        ev = c.get("/api/eval/latest").json()
        check("eval report", ev.get("available") is True, f"systems={list((ev.get('systems') or {}).keys())}")
        check("models", "versions" in c.get("/api/models").json())
        if a.frontend:
            r = c.options("/api/samples", headers={"Origin": a.frontend, "Access-Control-Request-Method": "GET"})
            check("CORS", r.headers.get("access-control-allow-origin") in (a.frontend, "*"))
    print(json.dumps({"failed": fails}, indent=1))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
