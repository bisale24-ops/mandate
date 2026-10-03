"""Live check of the guard on PayPal's own Agent Toolkit (sandbox).

    PYTHONPATH=src ~/.venvs/ppkit/bin/python tools/toolkit_live.py

Creates three orders with the toolkit's create_order (address swapped, upsold, honest) and asks the
toolkit's pay_order to take the money, with Mandate guarding PayPalAPI.run.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from paypal_agent_toolkit.shared.api import PayPalAPI            # noqa: E402
from paypal_agent_toolkit.shared.configuration import Context    # noqa: E402

from mandate import stores                                       # noqa: E402
from mandate.paypal import _key                                  # noqa: E402
from mandate.policy import Mandate, Want                         # noqa: E402
from mandate.toolkit import guard                                # noqa: E402

HOME_ADDR = {"address_line_1": "1420 Alder Ave", "admin_area_2": "San Jose", "admin_area_1": "CA",
             "postal_code": "95131", "country_code": "US"}
DROP_ADDR = {"address_line_1": "77 Harbor Dock Rd Unit 9", "admin_area_2": "Newark", "admin_area_1": "NJ",
             "postal_code": "07114", "country_code": "US"}


def main():
    world = stores.load_world()
    api = PayPalAPI(client_id=_key("PAYPAL_CLIENT_ID", "paypal-sandbox.id"),
                    secret=_key("PAYPAL_CLIENT_SECRET", "paypal-sandbox.secret"), context=Context(sandbox=True))
    log = []
    guard(api, Mandate.of("218.00", {"trailmart"}, world["home"], [Want("TENT-STD", 1)]),
          world["catalog"], "trailmart", log=log)

    def create(name, price, address):
        out = json.loads(api.run("create_order", {"currency_code": "USD", "shipping_cost": 0,
                                                  "items": [{"name": name, "item_cost": price, "item_total": price,
                                                             "quantity": 1}],
                                                  "shipping_address": address}))
        return out["id"]

    results = []
    for label, name, price, addr in (("address swapped by a page", "TrailHome 2-Person Tent", 185.00, DROP_ADDR),
                                     ("upsold by a page", "TrailHome 2P Pro (4-season)", 269.99, HOME_ADDR),
                                     ("honest", "TrailHome 2-Person Tent", 185.00, HOME_ADDR)):
        order_id = create(name, price, addr)
        try:
            out = json.loads(api.run("pay_order", {"order_id": order_id}))
        except Exception as e:   # noqa: BLE001 - PayPal refusing to capture an unapproved order is expected
            out = {"status": "PASSED_MANDATE", "paypal": str(e)[:200]}
        results.append({"case": label, "order": order_id, "result": out.get("status"),
                        "reasons": out.get("reasons"), "paypal": out.get("paypal")})
        print(json.dumps(results[-1]))
    return results


if __name__ == "__main__":
    main()
