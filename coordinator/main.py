from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from coordinator.core import Grid, MAX_PARTITIONS, MAX_PI_SAMPLES, MAX_PRIME_LIMIT

GRID = Grid()
WORKER_TOKEN = os.environ.get("CAMPUSGRID_WORKER_TOKEN", "dev-worker-token")
ADMIN_TOKEN = os.environ.get("CAMPUSGRID_ADMIN_TOKEN", "dev-admin-token")
UI_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"


class Handler(BaseHTTPRequestHandler):
    server_version = "CampusGrid/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.log_date_time_string(), fmt % args))

    def _send(self, status: int, obj, content_type="application/json"):
        data = obj if isinstance(obj, bytes) else (obj.encode() if isinstance(obj, str) else json.dumps(obj).encode())
        self.send_response(status)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Worker-Token, X-Admin-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, b"")

    def _json(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 1_000_000:
                raise ValueError("request too large")
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError) as e:
            raise ValueError("invalid JSON request") from e

    def _worker_auth(self):
        if self.headers.get("X-Worker-Token") != WORKER_TOKEN:
            self._send(401, {"error": "invalid worker credential"})
            return False
        return True

    def _admin_auth(self):
        if self.headers.get("X-Admin-Token") != ADMIN_TOKEN:
            self._send(401, {"error": "invalid admin credential"})
            return False
        return True

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, UI_PATH.read_text(encoding="utf-8"), "text/html")
        elif path == "/api/health":
            self._send(200, {"status": "ok", "service": "campusgrid-coordinator"})
        elif path == "/api/state":
            self._send(200, GRID.snapshot())
        elif path.startswith("/api/jobs/"):
            jid = path.rsplit("/", 1)[-1]
            view = GRID.job_view(jid)
            self._send(200 if view else 404, view or {"error": "job not found"})
        elif path.startswith("/api/workers/") and path.endswith("/task"):
            if not self._worker_auth(): return
            wid = path.split("/")[3]
            if wid not in GRID.workers:
                self._send(404, {"error": "worker not registered"}); return
            task = GRID.claim_task(wid)
            self._send(200, {"task": task})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self._json()
        except ValueError as e:
            self._send(400, {"error": str(e)}); return
        if path == "/api/workers/register":
            if not self._worker_auth(): return
            required = ("worker_id", "name", "cores", "ram_mb", "max_tasks")
            if any(k not in data for k in required):
                self._send(400, {"error": "missing worker fields"}); return
            if not isinstance(data["name"], str) or not data["name"].strip() or len(data["name"]) > 80:
                self._send(422, {"error": "worker name must contain 1..80 characters"}); return
            try:
                if not (1 <= int(data["cores"]) <= 256 and 256 <= int(data["ram_mb"]) <= 2_000_000 and 1 <= int(data["max_tasks"]) <= 32):
                    raise ValueError()
            except (ValueError, TypeError):
                self._send(422, {"error": "capabilities outside safe bounds"}); return
            if not str(data["worker_id"]).replace("-", "").replace("_", "").isalnum() or len(str(data["worker_id"])) > 64:
                self._send(422, {"error": "invalid worker_id"}); return
            self._send(201, GRID.register(data))
        elif path.startswith("/api/workers/") and path.endswith("/heartbeat"):
            if not self._worker_auth(): return
            wid = path.split("/")[3]
            if not GRID.heartbeat(wid, data.get("active_tasks")):
                self._send(404, {"error": "worker not registered"}); return
            self._send(200, {"ok": True})
        elif path.startswith("/api/tasks/") and path.endswith("/result"):
            if not self._worker_auth(): return
            tid = path.split("/")[3]
            wid = data.get("worker_id", "")
            accepted, reason = GRID.complete_task(wid, tid, data.get("result", {}))
            status = 200 if accepted else (409 if reason in ("duplicate_result", "stale_or_unowned_task") else 422 if reason == "invalid_result" else 404)
            self._send(status,
                       {"accepted": accepted, "reason": reason})
        elif path.startswith("/api/tasks/") and path.endswith("/failure"):
            if not self._worker_auth(): return
            tid = path.split("/")[3]
            accepted = GRID.fail_task(data.get("worker_id", ""), tid, data.get("error", "task failed"))
            self._send(200 if accepted else 409, {"accepted": accepted})
        elif path == "/api/jobs":
            if not self._admin_auth(): return
            kind = data.get("type")
            params = data.get("params", {})
            try:
                parts = int(params.get("partitions", 0))
                if not 1 <= parts <= MAX_PARTITIONS:
                    raise ValueError("partitions must be 1..256")
                if kind == "monte_carlo_pi":
                    samples = int(params.get("samples", 0))
                    seed = int(params.get("seed", 20261019))
                    if not parts <= samples <= MAX_PI_SAMPLES:
                        raise ValueError("samples must be between partitions and 20,000,000")
                    if not 0 <= seed <= (2**64 - 1):
                        raise ValueError("seed must be an unsigned 64-bit integer")
                    clean = {"samples": samples, "partitions": parts, "seed": seed}
                elif kind == "prime_analysis":
                    limit = int(params.get("limit", 0))
                    if not parts <= limit <= MAX_PRIME_LIMIT:
                        raise ValueError("limit must be between partitions and 100,000,000")
                    clean = {"limit": limit, "partitions": parts}
                else:
                    raise ValueError("type must be monte_carlo_pi or prime_analysis")
            except (TypeError, ValueError) as e:
                self._send(422, {"error": str(e)}); return
            job = GRID.create_job(kind, clean)
            self._send(201, job)
        else:
            self._send(404, {"error": "not found"})


def serve(host=None, port=None):
    host = host or os.environ.get("CAMPUSGRID_HOST", "127.0.0.1")
    port = port or int(os.environ.get("CAMPUSGRID_PORT", "8000"))
    print(f"CampusGrid coordinator listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
