"""A mandate from a sentence: the person says what they want, a model fills a strict schema, the person confirms.

    compose("one TrailHome tent, under $220, to my home, best deal", world)

The schema only admits SKUs that exist in the allowed stores' catalogs and store names that exist, so the
model can choose but cannot invent. Amounts are parsed by code from the model's dollar strings. The result is
shown to the person before any agent runs: the model drafts the mandate, it never approves a payment.
"""
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request

from .policy import Mandate, Want, cents

MODEL = os.environ.get("MANDATE_COMPOSE_MODEL", "gemini-3.5-flash-lite")
URL = os.environ.get("MANDATE_LLM_URL", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")

SYSTEM = ("You turn a shopper's request into a spending mandate for a shopping agent. Choose SKUs only from the "
          "catalog given, the quantity the person asked for (1 if unstated), the budget in US dollars as stated "
          "(if none is stated, use the cheapest allowed price of the items plus 15%, rounded up to whole dollars), "
          "the stores the person allows (all listed stores if unstated), and best_deal true when they ask for the "
          "cheapest / best deal / best price. Never add items the person did not ask for.")


def schema(skus, stores):
    return {"type": "object", "additionalProperties": False,
            "required": ["items", "budget", "stores", "best_deal"],
            "properties": {
                "items": {"type": "array", "minItems": 1, "maxItems": 5, "items": {
                    "type": "object", "additionalProperties": False, "required": ["sku", "quantity"],
                    "properties": {"sku": {"type": "string", "enum": skus},
                                   "quantity": {"type": "integer", "minimum": 1, "maximum": 10}}}},
                "budget": {"type": "string", "description": "US dollars, e.g. 219.00"},
                "stores": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": stores}},
                "best_deal": {"type": "boolean"}}}


def _key():
    v = os.environ.get("GEMINI_API_KEY", "").strip()
    if v:
        return v
    path = pathlib.Path.home() / ".config" / "gemini.key"
    return path.read_text().strip() if path.exists() else ""


def compose(text, world, allowed=("peakgear", "trailmart"), transport=None):
    """Returns (mandate, draft dict for the page). Raises RuntimeError when no model is available."""
    catalog = world["catalog"]
    names = {s: it["name"] for m in allowed for s, it in catalog[m]["items"].items()}
    menu = "\n".join(f"{s}: {n} (from ${min(catalog[m]['items'][s]['price'] for m in allowed) / 100:.2f})"
                     for s, n in sorted(names.items()))
    body = {"model": MODEL, "temperature": 0, "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Allowed stores: {', '.join(allowed)}\nCatalog:\n{menu}\n\nRequest: {text}"}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "mandate", "strict": True, "schema": schema(sorted(names), list(allowed))}}}
    key = _key()
    if not key and transport is None:
        raise RuntimeError("no model key for composing mandates")
    draft = None
    for attempt in range(4):
        req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with (transport or urllib.request.urlopen)(req, timeout=60) as r:   # noqa: S310 - fixed https endpoint
                draft = json.loads(json.load(r)["choices"][0]["message"]["content"])
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < 3:
                time.sleep(2 * (attempt + 1))         # free tier overload passes in seconds
                continue
            raise
    # code, not the model, has the last word on what is valid
    items = [i for i in draft.get("items", []) if i.get("sku") in names and int(i.get("quantity", 0)) >= 1]
    stores = [s for s in draft.get("stores", []) if s in allowed] or list(allowed)
    budget = cents(re.sub(r"[^0-9.]", "", str(draft.get("budget", "0"))) or "0")
    if not items or budget <= 0:
        raise RuntimeError("the request did not name anything in the catalog")
    mandate = Mandate.of(budget, stores, world["home"], [Want(i["sku"], int(i["quantity"])) for i in items],
                         best_deal=bool(draft.get("best_deal")))
    return mandate, {"items": [{"sku": i["sku"], "name": names[i["sku"]], "quantity": int(i["quantity"])} for i in items],
                     "budget": f"{budget / 100:.2f}", "stores": stores, "best_deal": bool(draft.get("best_deal"))}
