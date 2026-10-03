"""One task, both sides: the agent without Mandate and the same agent with it, as a trace a page can draw.

Model calls replay from fixtures/llm when the run is recorded (so the hosted demo shows the benchmark's
exact runs and costs no model quota); PayPal calls are live against the sandbox on every run, so each
hold, void and capture on the page has a real PayPal id.
"""
import json

from . import agent, policy, stores
from .paypal import proposal_from_order
from .policy import Mandate, Want, dollars


def mandate_for(task, home):
    return Mandate.of(task["budget"], task["merchants"], home,
                      [Want(w["sku"], w["quantity"]) for w in task["wants"]],
                      best_deal="better deal" in task["request"])


def _steps(messages, task):
    """Tool calls and their results, with the injected text marked so the page can highlight it."""
    out = []
    results = {m.get("tool_call_id"): m.get("content", "") for m in messages if m.get("role") == "tool"}
    for m in messages:
        for call in m.get("tool_calls") or []:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            text = results.get(call.get("id"), "")
            inj = task.get("injection") or ""
            out.append({"tool": name, "args": args, "result": text[:1200],
                        "injected": bool(inj) and inj[:40] in text})
    return out


def _proposal_dict(p):
    if p is None:
        return None
    return {"merchant": p.merchant, "lines": [vars(l) for l in p.lines], "shipping": p.shipping,
            "ship_to": dict(p.ship_to), "total": p.total, "total_text": dollars(p.total)}


def run_task(task_id, world=None, pp=None, mode=None):
    world = world or stores.load_world()
    task = next(t for t in world["tasks"] if t["id"] == task_id)
    home, catalog = world["home"], world["catalog"]
    names = {s: it["name"] for shop in catalog.values() for s, it in shop["items"].items()}

    # without Mandate: the agent's checkout is paid as proposed
    prop, msgs = agent.run(task, stores.Stores(world, task), home, mode=mode)
    plain = {"steps": _steps(msgs, task), "proposal": _proposal_dict(prop), "paypal": None}
    if prop is not None and pp is not None and prop.total > 0:
        auth = pp.authorize(prop.total, reference=f"{task_id}-unguarded"[:120], description=task["request"],
                            proposal=prop, names=names)
        pp.capture(auth["id"])
        plain["paypal"] = {"authorization": auth["id"], "order": auth["order_id"], "fate": "captured",
                           "amount": dollars(prop.total)}

    # with Mandate: every checkout is held, read back from PayPal and decided by the mandate
    m = mandate_for(task, home)
    attempts = []

    def on_checkout(p):
        held, checked = p.total, p
        auth = None
        if pp is not None and held > 0:
            auth = pp.authorize(held, reference=f"{task_id}-mandate-{len(attempts)}"[:120],
                                description=task["request"], proposal=p, names=names)
            checked, held = proposal_from_order(pp.order(auth["order_id"]), p.merchant)
        v = policy.check(m, checked, catalog, held=held)
        if auth:
            (pp.capture if v.ok else pp.void)(auth["id"])
        attempts.append({"proposal": _proposal_dict(p), "ok": v.ok, "reasons": list(v.reasons),
                         "paypal": auth and {"authorization": auth["id"], "order": auth["order_id"],
                                             "fate": "captured" if v.ok else "voided", "amount": dollars(held)}})
        return v.ok, "; ".join(v.reasons)

    final, gmsgs = agent.run(task, stores.Stores(world, task), home, mode=mode, on_checkout=on_checkout)
    guarded = {"steps": _steps(gmsgs, task), "attempts": attempts, "proposal": _proposal_dict(final)}

    best = min(catalog[mm]["items"][task["wants"][0]["sku"]]["price"] + catalog[mm]["shipping"]
               for mm in task["merchants"])
    return {"task": {k: task[k] for k in ("id", "line", "attack", "where", "request", "budget")},
            "budget_text": dollars(task["budget"]), "best_text": dollars(best),
            "injection": task.get("injection"),
            "mandate": {"budget": dollars(m.budget), "stores": sorted(m.merchants), "ship_to": dict(m.ship_to),
                        "wants": [{"sku": w.sku, "name": names.get(w.sku, w.sku), "quantity": w.quantity}
                                  for w in m.wants], "best_deal": m.best_deal},
            "without": plain, "with": guarded}
