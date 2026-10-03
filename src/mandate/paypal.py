"""PayPal Orders v2 and Payments v2 in the sandbox: hold, then capture or void. Standard library only.

    pp = PayPal.from_env()
    auth = pp.authorize(total_cents, card=TEST_CARD, reference="task-1")   # money is held, not taken
    pp.capture(auth["id"])  or  pp.void(auth["id"])

Keys come from PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET or ~/.config/paypal-sandbox.{id,secret}.
Every call sends a PayPal-Request-Id, so a retried request can never charge twice.
"""
import base64
import json
import os
import pathlib
import time
import urllib.error
import urllib.request
import uuid

from .policy import dollars

BASE = os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
# PayPal's published sandbox test card; it moves no real money and only works against the sandbox.
TEST_CARD = {"number": "4111111111111111", "expiry": "2030-12", "name": "Test Buyer",
             "billing_address": {"address_line_1": "1 Main St", "admin_area_2": "San Jose",
                                 "admin_area_1": "CA", "postal_code": "95131", "country_code": "US"}}


class PayPalError(RuntimeError):
    def __init__(self, status, body):
        self.status, self.body = status, body
        issues = [d.get("issue") for d in (body or {}).get("details", [])] if isinstance(body, dict) else []
        name = body.get("name") if isinstance(body, dict) else None
        super().__init__(f"PayPal {status} {name or ''} {' '.join(i for i in issues if i)}".strip())


def _key(env, name):
    value = os.environ.get(env, "").strip()
    if value:
        return value
    try:
        return (pathlib.Path.home() / ".config" / name).read_text().strip()
    except OSError:
        raise PayPalError(0, {"name": f"no key: set {env} or write ~/.config/{name}"}) from None


class PayPal:
    def __init__(self, client_id, secret, base=BASE, transport=None):
        self.client_id, self.secret, self.base = client_id, secret, base.rstrip("/")
        self.transport = transport or urllib.request.urlopen
        self._token, self._expires = None, 0.0
        self.calls = []                                    # (method, path, status) for the trace

    @classmethod
    def from_env(cls, **kw):
        return cls(_key("PAYPAL_CLIENT_ID", "paypal-sandbox.id"), _key("PAYPAL_CLIENT_SECRET", "paypal-sandbox.secret"), **kw)

    def _send(self, method, path, body=None, headers=None, form=None):
        data = None
        if form is not None:
            data = form.encode()
        elif body is not None:
            data = json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with self.transport(req, timeout=30) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        self.calls.append((method, path.split("?")[0], status))
        payload = json.loads(raw) if raw and raw.strip() else {}
        if status >= 400:
            raise PayPalError(status, payload)
        return payload

    def token(self):
        if self._token and time.time() < self._expires - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
        got = self._send("POST", "/v1/oauth2/token", form="grant_type=client_credentials",
                         headers={"Authorization": "Basic " + basic,
                                  "Content-Type": "application/x-www-form-urlencoded"})
        self._token, self._expires = got["access_token"], time.time() + float(got.get("expires_in", 0))
        return self._token

    def _api(self, method, path, body=None, request_id=None):
        headers = {"Authorization": "Bearer " + self.token(), "Content-Type": "application/json"}
        if method == "POST":
            headers["PayPal-Request-Id"] = request_id or str(uuid.uuid4())
        return self._send(method, path, body if body is not None else ({} if method == "POST" else None), headers)

    def authorize(self, total_cents, card=None, reference="mandate", currency="USD", description=None, request_id=None,
                  proposal=None, names=None):
        """Create an order with intent AUTHORIZE and a card source: the money is held, nothing is taken.
        With a proposal, PayPal stores the line items, shipping amount and ship-to address on the order,
        so the mandate can read the order back from PayPal instead of trusting the agent.
        Returns the authorization (id, status, amount, order_id)."""
        unit = {"reference_id": reference, "amount": {"currency_code": currency, "value": dollars(total_cents)}}
        if description:
            unit["description"] = description[:127]
        if proposal is not None:
            unit.update(order_unit(proposal, currency, names or {}))
        order = self._api("POST", "/v2/checkout/orders", {
            "intent": "AUTHORIZE", "purchase_units": [unit],
            "payment_source": {"card": card or TEST_CARD}}, request_id)
        auths = (order.get("purchase_units") or [{}])[0].get("payments", {}).get("authorizations") or []
        if order.get("status") != "COMPLETED" or not auths:
            raise PayPalError(200, {"name": "NOT_AUTHORIZED", "details": [{"issue": order.get("status")}]})
        auth = dict(auths[0])
        auth["order_id"] = order["id"]
        return auth

    def capture(self, authorization_id, request_id=None):
        return self._api("POST", f"/v2/payments/authorizations/{authorization_id}/capture", {}, request_id)

    def void(self, authorization_id, request_id=None):
        return self._api("POST", f"/v2/payments/authorizations/{authorization_id}/void", None, request_id)

    def order(self, order_id):
        return self._api("GET", f"/v2/checkout/orders/{order_id}")

    def authorization(self, authorization_id):
        return self._api("GET", f"/v2/payments/authorizations/{authorization_id}")


def order_unit(proposal, currency="USD", names=None):
    """Line items, amount breakdown and shipping address of a purchase unit, from a proposal."""
    money = lambda c: {"currency_code": currency, "value": dollars(c)}   # noqa: E731
    items = [{"name": (names or {}).get(l.sku, l.sku)[:127], "sku": l.sku, "quantity": str(l.quantity),
              "unit_amount": money(l.unit_price)} for l in proposal.lines]
    item_total = sum(l.quantity * l.unit_price for l in proposal.lines)
    a = dict(proposal.ship_to)
    return {"items": items,
            "amount": dict(money(item_total + proposal.shipping),
                           breakdown={"item_total": money(item_total), "shipping": money(proposal.shipping)}),
            "shipping": {"name": {"full_name": a.get("name", "")[:300]},
                         "address": {"address_line_1": a.get("line1", ""), "admin_area_2": a.get("city", ""),
                                     "admin_area_1": a.get("state", ""), "postal_code": a.get("zip", ""),
                                     "country_code": (a.get("country") or "US")[:2].upper()}}}


def proposal_from_order(order, merchant):
    """What PayPal says was ordered: the source of truth the mandate checks."""
    from .policy import Line, Proposal, cents
    pu = (order.get("purchase_units") or [{}])[0]
    lines = tuple(Line(i.get("sku") or i.get("name", ""), int(i.get("quantity", "0")),
                       cents(i.get("unit_amount", {}).get("value", "0"))) for i in pu.get("items", []))
    ship = pu.get("amount", {}).get("breakdown", {}).get("shipping", {}).get("value", "0")
    addr = pu.get("shipping", {}).get("address", {})
    ship_to = {"name": pu.get("shipping", {}).get("name", {}).get("full_name", ""),
               "line1": addr.get("address_line_1", ""), "city": addr.get("admin_area_2", ""),
               "state": addr.get("admin_area_1", ""), "zip": addr.get("postal_code", ""),
               "country": addr.get("country_code", "")}
    held = cents(pu.get("amount", {}).get("value", "0"))
    return Proposal(merchant, lines, tuple(sorted(ship_to.items())), cents(ship)), held
