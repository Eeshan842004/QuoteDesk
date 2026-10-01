from evallib.postprocess import derive_missing_info, has_order_reference, repair_missing_info
from evallib.schema import Extraction


def ext(intent="quote_request", items=(), missing=()):
    return Extraction.model_validate({"intent": intent, "urgency": "normal", "needed_by": None,
                                      "items": list(items), "missing_info": list(missing)})


def item(desc, qty=None, ref=None, compat=None):
    return {"description": desc, "quantity": qty, "unit": None, "part_number": None,
            "compatible_with": compat, "reference": ref}


def test_quantity_entries_are_derived_not_trusted():
    e = ext(items=[item("45/5 cap", 6), item("contactor")], missing=["quantity: 45/5 cap", "size_or_spec: contactor"])
    out = repair_missing_info(e, "6 45/5 cap and a contactor")
    assert out.missing_info == ["quantity: contactor"]  # model's wrong entries are discarded


def test_previous_order_items_never_need_a_quantity():
    e = ext(items=[item("same fuses as last time", ref="previous_order")])
    assert derive_missing_info(e, "same fuses as last time") == []


def test_order_number_only_when_no_reference_in_email():
    e = ext("order_status")
    assert derive_missing_info(e, "where is our order from last week?") == ["order_number"]
    assert derive_missing_info(e, "status of NBO-51296 please") == []
    assert derive_missing_info(e, "status of PO-3960 please") == []
    assert has_order_reference("order #51296")


def test_equipment_model_when_line_says_fits_but_names_no_model():
    body = "need 2 filters whatever fits my unit\n3 contactors for KVL-AC24-2"
    e = ext(items=[item("filters", 2), item("contactors", 3)])
    assert derive_missing_info(e, body) == ["equipment_model: filters"]
    e2 = ext(items=[item("contactors", 3, compat="KVL-AC24-2")])
    assert derive_missing_info(e2, body) == []


def test_non_quote_intents_get_no_item_entries():
    e = ext("other")
    assert derive_missing_info(e, "please update our billing address") == []
