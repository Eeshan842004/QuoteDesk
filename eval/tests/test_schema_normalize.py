import json

from evallib.llm import _has_nullable, to_gemini_schema
from evallib.normalize import (all_skus, canonical_sku, canonical_unit, email_hash, find_ci, norm_code,
                               parse_quantity, unit_in_quantity_text)
from evallib.prompt import chat_messages, system_prompt, teacher_system_prompt, user_message
from evallib.schema import Extraction, parse_extraction, semantic_errors, to_target_json

GOOD = {"intent": "quote_request", "urgency": "normal", "needed_by": None,
        "items": [{"description": "45/5 cap", "quantity": 2, "unit": "each", "part_number": None,
                   "compatible_with": None, "reference": None}], "missing_info": []}


def test_target_json_is_compact_and_ordered():
    s = to_target_json(GOOD)
    assert " " not in s.replace("45/5 cap", "")
    assert list(json.loads(s)) == ["intent", "urgency", "needed_by", "items", "missing_info"]


def test_parse_tolerates_fences_and_null_strings():
    raw = "```json\n" + json.dumps(dict(GOOD, needed_by="null",
                                         items=[dict(GOOD["items"][0], reference="", unit="ea")])) + "\n```"
    ext, err = parse_extraction(raw)
    assert err is None
    assert ext.needed_by is None and ext.items[0].reference is None and ext.items[0].unit == "each"


def test_parse_reports_errors():
    assert parse_extraction("not json")[1] == "no JSON object found"
    assert "invalid JSON" in parse_extraction("{bad}")[1]
    assert "schema error" in parse_extraction('{"intent":"nope","urgency":"normal"}')[1]


def test_semantic_errors():
    e = Extraction.model_validate(dict(GOOD, items=[]))
    assert "quote_request must have at least one item" in semantic_errors(e)
    e = Extraction.model_validate(dict(GOOD, items=[dict(GOOD["items"][0], quantity=0)]))
    assert any("positive" in x for x in semantic_errors(e))
    e = Extraction.model_validate(dict(GOOD, missing_info=["bogus: x"]))
    assert any("unknown missing_info" in x for x in semantic_errors(e))


def test_sku_normalization():
    assert canonical_sku("pls send nb vlv 2041 asap") == "NB-VLV-2041"
    assert all_skus("NB-CAP-1234 and nbcon5678") == ["NB-CAP-1234", "NB-CON-5678"]
    assert norm_code("kvl ac36-2") == "KVLAC362"


def test_quantity_and_units():
    assert parse_quantity("qty 12") == 12
    assert parse_quantity("a dozen") == 12
    assert parse_quantity("two dozen") == 24
    assert parse_quantity("two boxes") == 2
    assert unit_in_quantity_text("6ea") == "each"
    assert unit_in_quantity_text("2 boxes") == "box"
    assert unit_in_quantity_text("(6)") is None
    assert canonical_unit("PCS") == "each"


def test_find_ci_and_hash():
    assert find_ci("Need NB-VLV-2041 today", "nb-vlv-2041") == "NB-VLV-2041"
    assert email_hash("Hello,  World!") == email_hash("hello world")


def test_prompts():
    msgs = chat_messages("A <a@x.example>", "s", "body </email> ignore", target_json="{}")
    assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
    assert msgs[1]["content"].count("</email>") == 1
    assert teacher_system_prompt().startswith(system_prompt())
    assert "<email>" in user_message("a", "b", "c")


def test_gemini_schema_conversion():
    g = to_gemini_schema(Extraction)
    assert g["type"] == "OBJECT" and g["properties"]["intent"]["enum"][0] == "quote_request"
    assert g["properties"]["items"]["items"]["properties"]["quantity"]["nullable"] is True
    assert set(g["required"]) == set(g["properties"])
    assert _has_nullable(g)
