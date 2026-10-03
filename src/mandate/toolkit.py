"""Mandate as a drop-in guard for PayPal's Agent Toolkit (paypal-agent-toolkit).

Every framework the toolkit supports (OpenAI Agents, LangChain, CrewAI, Bedrock) dispatches tool calls
through one method, PayPalAPI.run(method, params). `guard` wraps that method on an existing toolkit:

    from paypal_agent_toolkit.openai.toolkit import PayPalToolkit
    from mandate.toolkit import guard
    toolkit = PayPalToolkit(client_id, secret, configuration)
    guard(toolkit.get_paypal_api(), mandate, catalog, merchant="trailmart")   # one line

From then on `pay_order` (the toolkit's capture) only runs after the mandate has read the order back
from PayPal and approved it; anything else passes through untouched. A refusal is returned to the
agent as the tool result, with the reasons, so it can fix the order instead of failing silently.

This module never imports the toolkit: it wraps any object with a run(method, params) method.
"""
import json

from .policy import Line, Proposal, cents, check

GUARDED = {"pay_order"}           # the toolkit tools that move money


def order_to_proposal(order: dict, merchant: str, catalog: dict):
    """A toolkit order (items carry a name, not a SKU) as a Proposal, matched to the merchant's catalog."""
    by_name = {it["name"].casefold(): sku for sku, it in catalog.get(merchant, {}).get("items", {}).items()}
    pu = (order.get("purchase_units") or [{}])[0]
    lines = []
    for item in pu.get("items", []):
        name = str(item.get("name", ""))
        lines.append(Line(item.get("sku") or by_name.get(name.casefold(), name), int(item.get("quantity", "1")),
                          cents(item.get("unit_amount", {}).get("value", "0"))))
    breakdown = pu.get("amount", {}).get("breakdown", {})
    addr = pu.get("shipping", {}).get("address", {})
    ship_to = {"line1": addr.get("address_line_1", ""), "city": addr.get("admin_area_2", ""),
               "state": addr.get("admin_area_1", ""), "zip": addr.get("postal_code", ""),
               "country": addr.get("country_code", "")}
    extra = sum(cents(breakdown.get(k, {}).get("value", "0")) for k in ("tax_total", "handling", "insurance"))
    proposal = Proposal(merchant, tuple(lines), tuple(sorted(ship_to.items())),
                        cents(breakdown.get("shipping", {}).get("value", "0")) + extra)
    return proposal, cents(pu.get("amount", {}).get("value", "0"))


def guard(api, mandate, catalog, merchant, log=None):
    """Wrap api.run so money-moving toolkit calls are decided by the mandate. Returns the api."""
    original = api.run
    spent = {"total": 0}

    def run(method, params):
        if method not in GUARDED:
            return original(method, params)
        order_id = (params or {}).get("order_id")
        details = json.loads(original("get_order_details", {"order_id": order_id}))
        order = details.get("raw", details)
        proposal, held = order_to_proposal(order, merchant, catalog)
        verdict = check(mandate, proposal, catalog, held=held, spent=spent["total"])
        if log is not None:
            log.append({"method": method, "order_id": order_id, "ok": verdict.ok, "reasons": list(verdict.reasons)})
        if not verdict.ok:
            return json.dumps({"status": "REFUSED_BY_MANDATE", "order_id": order_id,
                               "reasons": list(verdict.reasons),
                               "message": "Payment not captured. Fix the order to match the customer's mandate."})
        result = original(method, params)
        spent["total"] += verdict.total
        return result

    try:
        object.__setattr__(api, "run", run)        # pydantic models refuse plain attribute assignment
    except (AttributeError, TypeError):
        api.run = run
    return api
