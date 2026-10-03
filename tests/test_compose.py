"""Composing a mandate from a sentence, on a fake model: the schema limits choices, code has the last word."""
import io
import json

import pytest

from mandate.compose import compose, schema

WORLD = {"home": {"name": "A", "line1": "1 Main St", "city": "San Jose", "state": "CA", "zip": "95131", "country": "US"},
         "catalog": {m: {"shipping": 0, "items": {"TENT-STD": {"name": "TrailHome 2-Person Tent", "price": 18500},
                                                    "TENT-PRO": {"name": "TrailHome 2P Pro", "price": 26999}}}
                     for m in ("peakgear", "trailmart")}}


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def model(draft):
    sent = []

    def transport(req, timeout=60):
        sent.append(json.loads(req.data))
        return Reply(json.dumps({"choices": [{"message": {"content": json.dumps(draft)}}]}).encode())
    return transport, sent


def test_the_schema_only_admits_catalog_skus_and_known_stores():
    s = schema(["TENT-STD"], ["peakgear"])
    assert s["properties"]["items"]["items"]["properties"]["sku"]["enum"] == ["TENT-STD"]
    assert s["properties"]["stores"]["items"]["enum"] == ["peakgear"]


def test_a_sentence_becomes_a_mandate_with_code_parsed_money():
    transport, sent = model({"items": [{"sku": "TENT-STD", "quantity": 1}], "budget": "$219.50", "stores": ["trailmart"], "best_deal": True})
    m, d = compose("one tent under 220, trailmart, best deal", WORLD, transport=transport)
    assert m.budget == 21950 and m.merchants == frozenset({"trailmart"}) and m.best_deal
    assert d["items"][0]["name"] == "TrailHome 2-Person Tent"
    assert sent[0]["response_format"]["json_schema"]["strict"] is True


def test_an_invented_sku_or_empty_request_is_refused_by_code():
    transport, _ = model({"items": [{"sku": "YACHT", "quantity": 1}], "budget": "100", "stores": ["peakgear"], "best_deal": False})
    with pytest.raises(RuntimeError):
        compose("a yacht", WORLD, transport=transport)
