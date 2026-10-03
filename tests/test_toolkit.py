"""The toolkit guard on a fake PayPalAPI: pay_order is decided by the mandate, everything else passes."""
import json

from mandate.policy import Mandate, Want
from mandate.toolkit import guard

HOME = {"name": "Alex Rivera", "line1": "1420 Alder Ave", "city": "San Jose", "state": "CA", "zip": "95131", "country": "US"}
CATALOG = {"trailmart": {"shipping": 0, "items": {
    "TENT-STD": {"name": "TrailHome 2-Person Tent", "price": 18500, "line": "tent"},
    "TENT-PRO": {"name": "TrailHome 2P Pro (4-season)", "price": 26999, "line": "tent"}}}}
MANDATE = Mandate.of("218.00", {"trailmart"}, HOME, [Want("TENT-STD", 1)])


def order(name, price, line1="1420 Alder Ave"):
    return {"id": "O1", "purchase_units": [{
        "items": [{"name": name, "quantity": "1", "unit_amount": {"value": price}}],
        "amount": {"value": price, "breakdown": {"item_total": {"value": price}, "shipping": {"value": "0.00"}}},
        "shipping": {"address": {"address_line_1": line1, "admin_area_2": "San Jose", "admin_area_1": "CA",
                                 "postal_code": "95131", "country_code": "US"}}}]}


class FakeAPI:
    def __init__(self, held):
        self.held, self.calls = held, []

    def run(self, method, params):
        self.calls.append(method)
        if method == "get_order_details":
            return json.dumps({"status": "APPROVED", "raw": self.held})
        return json.dumps({"status": "COMPLETED", "method": method})


def test_the_right_order_is_captured():
    api = guard(FakeAPI(order("TrailHome 2-Person Tent", "185.00")), MANDATE, CATALOG, "trailmart")
    assert json.loads(api.run("pay_order", {"order_id": "O1"}))["status"] == "COMPLETED"
    assert api.calls == ["get_order_details", "pay_order"]


def test_an_upsold_order_is_refused_with_reasons_and_never_captured():
    log = []
    api = guard(FakeAPI(order("TrailHome 2P Pro (4-season)", "269.99")), MANDATE, CATALOG, "trailmart", log=log)
    out = json.loads(api.run("pay_order", {"order_id": "O1"}))
    assert out["status"] == "REFUSED_BY_MANDATE" and any("did not ask" in r for r in out["reasons"])
    assert "pay_order" not in api.calls and log[0]["ok"] is False


def test_a_changed_address_on_the_paypal_order_is_refused():
    api = guard(FakeAPI(order("TrailHome 2-Person Tent", "185.00", line1="77 Harbor Dock Rd")), MANDATE, CATALOG, "trailmart")
    assert json.loads(api.run("pay_order", {"order_id": "O1"}))["status"] == "REFUSED_BY_MANDATE"


def test_tools_that_move_no_money_pass_through():
    api = guard(FakeAPI(order("x", "1.00")), MANDATE, CATALOG, "trailmart")
    api.run("create_order", {"currency_code": "USD", "items": []})
    assert api.calls == ["create_order"]
