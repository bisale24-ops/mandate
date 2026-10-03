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
from .trace import run_task

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
            "ready": sorted(t["id"] for t in WORLD["tasks"])}


def bench():
    path = ROOT / "docs" / "bench.json"
    if not path.exists():
        return {"summary": None}
    data = json.loads(path.read_text())
    return {"model": data.get("model"), "summary": data.get("summary"), "stopped": data.get("stopped"),
            "tasks": len(data.get("rows", []))}


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
