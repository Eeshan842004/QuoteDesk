from app.tools import LineItemIn, get_catalog, guess_category


def cat():
    return get_catalog()


def test_exact_sku_and_formats():
    c = cat()
    sku = c.products[0]["sku"]
    for q in (sku, sku.lower(), sku.replace("-", " "), sku.replace("-", "")):
        r = c.search_catalog(q)
        assert r[0].sku == sku and r[0].score == 1.0


def test_unique_alias_is_top_and_confident():
    c = cat()
    for p in c.products[::17]:
        alias = p["unique_aliases"][0]
        r = c.search_catalog(alias)
        assert r[0].sku == p["sku"], (alias, r[0])
        assert r[0].score >= 0.9


def test_numbers_matter_in_fuzzy_search():
    c = cat()
    caps = [p for p in c.products if p["category"] == "capacitors" and p["attributes"]["type"] == "dual run"]
    p = caps[0]
    r = c.search_catalog(f"{p['attributes']['microfarads']} {p['attributes']['voltage']} dual run capacitor")
    assert r[0].sku == p["sku"]


def test_resolve_confident_vs_review():
    c = cat()
    p = next(x for x in c.products if x["stock_qty"] > 20)
    ok = c.resolve_line_item(LineItemIn(description=p["sku"], quantity=2, part_number=p["sku"]), "C001")
    assert ok.status == "CONFIDENT" and ok.candidates[0].sku == p["sku"]
    no_qty = c.resolve_line_item(LineItemIn(description=p["sku"], part_number=p["sku"]), "C001")
    assert no_qty.status == "NEEDS_REVIEW" and "quantity missing" in no_qty.reasons
    out = next(x for x in c.products if x["stock_qty"] == 0)
    no_stock = c.resolve_line_item(LineItemIn(description=out["sku"], quantity=5, part_number=out["sku"]), "C001")
    assert no_stock.status == "NEEDS_REVIEW" and any("insufficient stock" in r for r in no_stock.reasons)
    bad = c.resolve_line_item(LineItemIn(description="NB-BLT-161", quantity=2, part_number="NB-BLT-161"), "C001")
    assert bad.status == "NEEDS_REVIEW"


def test_compatibility_lookup():
    c = cat()
    eq = c.equipment[0]
    for category, sku in eq["compatible_parts"].items():
        r = c.get_compatible_parts(eq["model"].lower().replace("-", " "), category)
        assert [x.sku for x in r] == [sku]
    res = c.resolve_line_item(LineItemIn(description="cap", quantity=1, compatible_with=eq["model"]), None)
    assert res.candidates[0].sku == eq["compatible_parts"]["capacitors"]


def test_last_order_items():
    c = cat()
    cid = "C001"
    orders = sorted((o for o in c.orders if o["customer_id"] == cid), key=lambda o: o["date"])
    whole = c.get_last_order_items(cid, "same as our last order")
    assert {l.sku for l in whole} == {l["sku"] for l in orders[-1]["lines"]}
    assert c.get_last_order_items(None, "anything") == []


def test_pricing_tiers_and_volume_breaks():
    c = cat()
    sku = c.products[0]["sku"]
    lp = c.by_sku[sku]["list_price"]
    cust = c.customers[0]
    small = c.get_price(sku, cust["id"], 1)
    assert small.discount_pct == cust["tier_discount"]
    assert small.unit_price == round(lp * (1 - cust["tier_discount"]), 2)
    big = c.get_price(sku, cust["id"], 60)
    assert big.discount_pct == round(cust["tier_discount"] + 0.07, 4)
    anon = c.get_price(sku, None, 3)
    assert anon.unit_price == lp and anon.line_total == round(lp * 3, 2)


def test_customer_lookup_and_category_guess():
    c = cat()
    cust = c.customers[3]
    assert c.customer_for_sender(f"X Y <someone@{cust['email_domain']}>")["id"] == cust["id"]
    assert c.customer_for_sender("nobody@unknown.example") is None
    assert guess_category("45/5 run cap") == "capacitors"
    assert guess_category("B39 belt") == "belts"
