"""Mandate over HTTP: one page, three endpoints. Standard library only.

    PYTHONPATH=src python3 -m mandate.web            # http://127.0.0.1:8795

GET  /api/scenarios   the products and attacks a visitor can try
GET  /api/bench       the benchmark summary (docs/bench.json)
POST /api/run         {"task": "tent-fee"}: both sides of one task, with live PayPal sandbox ids

Model replies replay from the recorded benchmark runs (MANDATE_MODE=replay by default here), so a visitor
sees exactly the runs the numbers are made of and nothing spends model quota; PayPal calls are live.
"""
import http.server
import json
import os
import pathlib
import sys
import threading

from . import stores
from .paypal import PayPal, PayPalError
from .compose import compose
from .policy import fingerprint
from .trace import mandate_for, run_task

ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGE = pathlib.Path(__file__).with_name("page.html")
WORLD = stores.load_world()
NAMES = {line: next(it["name"] for s, it in WORLD["catalog"]["peakgear"]["items"].items()
                    if s == f"{line.upper()}-STD")
         for line in sorted({t["line"] for t in WORLD["tasks"]})}
LOCK = threading.Lock()          # one run at a time: the free sandbox and the demo stay calm


def scenarios():
    return {"products": [{"line": line, "name": name} for line, name in NAMES.items()],
            "attacks": [{"id": "none", "label": "No attack (honest page)"}] +
                       [{"id": k, "label": v} for k, v in WORLD["attacks"].items()],
            "ready": sorted(t["id"] for t in WORLD["tasks"]),
            "default": default_mandate()}


def default_mandate(task_id="tent-fee"):
    task = next(t for t in WORLD["tasks"] if t["id"] == task_id)
    m = mandate_for(task, WORLD["home"])
    names = {s: it["name"] for shop in WORLD["catalog"].values() for s, it in shop["items"].items()}
    return {"fingerprint": fingerprint(m), "budget": f"{m.budget / 100:.2f}", "stores": sorted(m.merchants),
            "ship_to": dict(m.ship_to), "best_deal": m.best_deal,
            "wants": [{"sku": w.sku, "name": names.get(w.sku, w.sku), "quantity": w.quantity} for w in m.wants]}


def bench():
    """Every recorded benchmark: docs/bench.json (the main model) first, then docs/bench-<model>.json."""
    runs = []
    for path in sorted((ROOT / "docs").glob("bench*.json"), key=lambda p: (p.name != "bench.json", p.name)):
        if path.name == "bench-tent.json":
            continue
        data = json.loads(path.read_text())
        runs.append({"model": data.get("model"), "summary": data.get("summary"), "stopped": data.get("stopped"),
                     "tasks": len(data.get("rows", []))})
    first = runs[0] if runs else {"summary": None}
    return dict(first, runs=runs)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "mandate/0.1"

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/scenarios":
            self._send(200, scenarios())
        elif path == "/api/bench":
            self._send(200, bench())
        elif path == "/healthz":
            self._send(200, {"ok": True, "tasks": len(WORLD["tasks"])})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path == "/api/compose":
            return self._compose()
        if self.path != "/api/run":
            self._send(404, {"error": "not found"})
            return
        try:
            length = min(int(self.headers.get("content-length") or 0), 2048)
            task_id = str(json.loads(self.rfile.read(length) or b"{}").get("task", ""))
        except ValueError:
            self._send(400, {"error": "send JSON: {\"task\": \"tent-fee\"}"})
            return
        if task_id not in {t["id"] for t in WORLD["tasks"]}:
            self._send(400, {"error": "unknown scenario"})
            return
        mode = os.environ.get("MANDATE_MODE", "replay")
        try:
            pp = PayPal.from_env()
        except PayPalError:
            pp = None                                   # still shows the decisions, without PayPal ids
        with LOCK:
            try:
                self._send(200, run_task(task_id, WORLD, pp=pp, mode=mode))
            except RuntimeError as error:
                self._send(409, {"error": "This scenario has not been recorded yet. " + str(error)[:120]})
            except PayPalError as error:
                self._send(502, {"error": f"PayPal sandbox did not answer: {error}"})

    def _compose(self):
        try:
            length = min(int(self.headers.get("content-length") or 0), 2048)
            text = str(json.loads(self.rfile.read(length) or b"{}").get("text", "")).strip()[:300]
        except ValueError:
            self._send(400, {"error": "send JSON: {\"text\": ...}"})
            return
        if not text:
            self._send(400, {"error": "Say what the agent should buy."})
            return
        try:
            mandate, draft = compose(text, WORLD)
        except RuntimeError as error:
            self._send(503 if "no model key" in str(error) else 422, {"error": str(error)})
            return
        except Exception as error:   # noqa: BLE001 - model or network failure is shown, not raised
            self._send(502, {"error": f"the model did not answer: {type(error).__name__}"})
            return
        a = dict(mandate.ship_to)
        self._send(200, dict(draft, fingerprint=fingerprint(mandate), ship_to=a))

    def log_message(self, fmt, *args):
        sys.stdout.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8795"))
    server = http.server.ThreadingHTTPServer((host, port), Handler)
    print(f"http://{host}:{port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
