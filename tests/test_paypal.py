"""The PayPal client on a fake transport: no network, no key."""
import io
import json
import urllib.error

import pytest

from mandate.paypal import PayPal, PayPalError


class Resp(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(json.dumps(body).encode() if body is not None else b"")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake(routes):
    seen = []

    def transport(req, timeout=30):
        seen.append(req)
        status, body = routes[(req.get_method(), req.full_url.split("api-m.sandbox.paypal.com")[-1])]
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(json.dumps(body).encode()))
        return Resp(status, body)
    return transport, seen


TOKEN = {("POST", "/v1/oauth2/token"): (200, {"access_token": "t", "expires_in": 3600})}


def test_authorize_holds_the_exact_amount_and_sends_an_idempotency_key():
    order = {"id": "O1", "status": "COMPLETED", "purchase_units": [{"payments": {"authorizations": [
        {"id": "A1", "status": "CREATED", "amount": {"value": "194.99", "currency_code": "USD"}}]}}]}
    transport, seen = fake({**TOKEN, ("POST", "/v2/checkout/orders"): (201, order)})
    auth = PayPal("id", "secret", transport=transport).authorize(19499, request_id="task-1")
    body = json.loads(seen[1].data)
    assert body["intent"] == "AUTHORIZE" and body["purchase_units"][0]["amount"]["value"] == "194.99"
    assert seen[1].get_header("Paypal-request-id") == "task-1"
    assert auth["id"] == "A1" and auth["order_id"] == "O1"


def test_a_refused_card_is_an_error_not_a_silent_success():
    transport, _ = fake({**TOKEN, ("POST", "/v2/checkout/orders"): (
        422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING"}]})})
    with pytest.raises(PayPalError, match="PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING"):
        PayPal("id", "secret", transport=transport).authorize(100)


def test_capture_and_void_hit_the_authorization_and_the_token_is_reused():
    transport, seen = fake({**TOKEN,
                            ("POST", "/v2/payments/authorizations/A1/capture"): (201, {"status": "COMPLETED"}),
                            ("POST", "/v2/payments/authorizations/A2/void"): (204, None)})
    pp = PayPal("id", "secret", transport=transport)
    assert pp.capture("A1")["status"] == "COMPLETED"
    assert pp.void("A2") == {}
    assert [c[1] for c in pp.calls].count("/v1/oauth2/token") == 1


def test_the_order_round_trips_through_paypal_fields():
    from mandate.paypal import order_unit, proposal_from_order
    from mandate.policy import Line, Proposal
    home = {"name": "Alex Rivera", "line1": "1420 Alder Ave", "city": "San Jose", "state": "CA", "zip": "95131", "country": "US"}
    p = Proposal("trailmart", (Line("TENT-STD", 1, 18500), Line("TENT-ACC", 2, 2899)), tuple(sorted(home.items())), 599)
    unit = order_unit(p, names={"TENT-STD": "TrailHome 2-Person Tent"})
    assert unit["amount"]["value"] == "248.97" and unit["amount"]["breakdown"]["shipping"]["value"] == "5.99"
    back, held = proposal_from_order({"purchase_units": [unit]}, "trailmart")
    assert back == p and held == 24897
