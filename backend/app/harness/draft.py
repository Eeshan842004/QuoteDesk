"""RESOLVE + DRAFT: turn an extraction into quote lines using ONLY the deterministic tools for SKUs, stock
and prices; produce a suggested action for non-quote intents."""
from __future__ import annotations

import re
from typing import Optional

from evallib.normalize import norm_text
from evallib.schema import Extraction

from ..tools import LineItemIn, get_catalog

ORDER_REF_RE = re.compile(r"\bNBO[\s\-]?(\d{4,})\b|\border\s*#?\s*(\d{5})\b|#\s?(\d{5})\b", re.I)
PO_RE = re.compile(r"\bPO[\s#\-]*(\d{3,})\b", re.I)


def missing_kinds_for(ext: Extraction, description: str) -> frozenset[str]:
    d = norm_text(description)
    kinds = set()
    for m in ext.missing_info:
        kind, _, desc = m.partition(":")
        if desc and norm_text(desc) == d:
            kinds.add(kind.strip())
    return frozenset(kinds)


def price_line(sku: str, customer_id: Optional[str], qty: Optional[int]) -> dict:
    cat = get_catalog()
    p = cat.by_sku[sku]
    out = {"sku": sku, "name": p["name"], "list_price": p["list_price"], "stock_qty": p["stock_qty"],
           "unit_price": None, "discount_pct": None, "line_total": None}
    if qty:
        pr = cat.get_price(sku, customer_id, qty)
        out.update(unit_price=pr.unit_price, discount_pct=pr.discount_pct, line_total=pr.line_total)
    return out


def resolve_and_draft(ext: Extraction, customer_id: Optional[str]) -> tuple[list[dict], list[dict]]:
    """Returns (lines, tool_calls). Each line carries candidates, status and reasons."""
    cat = get_catalog()
    lines, calls = [], []
    for idx, item in enumerate(ext.items):
        li = LineItemIn(**item.model_dump())
        kinds = missing_kinds_for(ext, item.description)
        res = cat.resolve_line_item(li, customer_id, kinds)
        calls.append({"tool": "resolve_line_item", "input": {**li.model_dump(), "customer_id": customer_id},
                      "output": res.model_dump()})
        if len(res.expanded) > 1:  # "same as our last order" -> one line per past line, flagged for review
            for ol in res.expanded:
                pl = price_line(ol.sku, customer_id, ol.qty)
                lines.append({"item_index": idx, "description": f"{item.description} ({ol.name})",
                              "quantity": ol.qty, "unit": None, **pl, "status": "NEEDS_REVIEW",
                              "reason": "; ".join(res.reasons), "candidates": [c.model_dump() for c in res.candidates]})
            continue
        qty = item.quantity if item.quantity is not None else (res.expanded[0].qty if res.expanded else None)
        top = res.candidates[0] if res.candidates else None
        pl = price_line(top.sku, customer_id, qty) if top else {
            "sku": None, "name": None, "list_price": None, "stock_qty": None, "unit_price": None,
            "discount_pct": None, "line_total": None}
        if top and qty:
            calls.append({"tool": "get_price", "input": {"sku": top.sku, "customer_id": customer_id,
                                                         "qty": qty}, "output": pl})
        lines.append({"item_index": idx, "description": item.description, "quantity": qty,
                      "unit": item.unit, **pl, "status": res.status, "reason": "; ".join(res.reasons) or None,
                      "candidates": [c.model_dump() for c in res.candidates]})
    for n, l in enumerate(lines, 1):
        l["line_no"] = n
    return lines, calls


def suggested_action(ext: Extraction, body: str, customer_id: Optional[str]) -> str:
    cat = get_catalog()
    if ext.intent == "order_status":
        m = ORDER_REF_RE.search(body)
        order = None
        if m:
            num = next(g for g in m.groups() if g)
            order = next((o for o in cat.orders if o["order_id"].endswith(num)), None)
        if not order:
            pm = PO_RE.search(body)
            if pm:
                order = next((o for o in cat.orders if o["po_number"] and o["po_number"].endswith(pm.group(1))), None)
        if order and (customer_id is None or order["customer_id"] == customer_id):
            return (f"Reply with status: order {order['order_id']} (placed {order['date']}) is "
                    f"{order['status'].upper()}. No quote needed.")
        if customer_id:
            recent = sorted((o for o in cat.orders if o["customer_id"] == customer_id), key=lambda o: o["date"])[-2:]
            listed = ", ".join(f"{o['order_id']} ({o['status']})" for o in recent)
            return f"Ask which order they mean (no order/PO number found). Recent orders: {listed}."
        return "Ask the customer for the order or PO number. No quote needed."
    if ext.intent == "return_request":
        names = ", ".join(it.description for it in ext.items) or "the items"
        return f"Open a return (RMA) for: {names}. Confirm quantities and reason. No quote needed."
    if ext.intent == "product_question":
        parts = []
        for it in ext.items:
            res = cat.resolve_line_item(LineItemIn(**it.model_dump()), customer_id)
            if res.candidates:
                c = res.candidates[0]
                parts.append(f"{c.name} ({c.sku}): {c.stock_qty} in stock")
        return "Answer the product question. " + ("; ".join(parts) if parts else "No catalog match found.")
    return "Route to the account team (not a parts request). No quote needed."
