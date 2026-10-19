"""Launch a coordinator and two separate worker OS processes, run a real job."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST, PORT = "127.0.0.1", "8177"
BASE = f"http://{HOST}:{PORT}"
TOKEN, ADMIN = "integration-worker-secret", "integration-admin-secret"
ENV = {**os.environ, "PYTHONPATH": str(ROOT), "CAMPUSGRID_HOST": HOST,
       "CAMPUSGRID_PORT": PORT, "CAMPUSGRID_WORKER_TOKEN": TOKEN, "CAMPUSGRID_ADMIN_TOKEN": ADMIN}


def api(path, method="GET", data=None, admin=False):
    headers = {"Content-Type": "application/json"}
    headers["X-Admin-Token" if admin else "X-Worker-Token"] = ADMIN if admin else TOKEN
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())


def main():
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, "-m", "coordinator.main"], cwd=ROOT, env=ENV,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT))
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                api("/api/health"); break
            except Exception:
                time.sleep(.15)
        else:
            raise RuntimeError("coordinator failed to start")
        with urllib.request.urlopen(BASE + "/", timeout=3) as r:
            assert b"CampusGrid" in r.read(), "dashboard HTML not served"
        try:
            req = urllib.request.Request(BASE + "/api/workers/register", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", "X-Worker-Token": "wrong"})
            urllib.request.urlopen(req, timeout=3)
            raise AssertionError("invalid worker token was accepted")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        try:
            req = urllib.request.Request(BASE + "/api/jobs", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", "X-Admin-Token": "wrong"})
            urllib.request.urlopen(req, timeout=3)
            raise AssertionError("invalid admin token was accepted")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        for idx in range(2):
            procs.append(subprocess.Popen([sys.executable, "-m", "worker.worker", "--server", BASE,
                                          "--name", f"Integration Worker {idx+1}", "--worker-id", f"integration-{idx+1}",
                                          "--token", TOKEN], cwd=ROOT, env=ENV,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT))
        deadline = time.time() + 8
        while time.time() < deadline:
            if api("/api/state")["stats"]["online_workers"] == 2: break
            time.sleep(.15)
        else:
            raise RuntimeError("both workers did not register")
        job = api("/api/jobs", "POST", {"type": "monte_carlo_pi", "params": {"samples": 500_000, "partitions": 12, "seed": 42}}, admin=True)
        deadline = time.time() + 25
        while time.time() < deadline:
            view = api(f"/api/jobs/{job['job_id']}")
            if view["status"] == "completed": break
            time.sleep(.2)
        else:
            raise RuntimeError(f"job timed out: {view['tasks_completed']}/{view['tasks_total']} tasks")
        participants = view["workers_involved"]
        assert len(participants) >= 2, f"expected both workers to participate, saw {participants}"
        assert view["result"]["samples"] == 500_000
        print("INTEGRATION PASS")
        print(json.dumps({"job_id": job["job_id"], "status": view["status"], "result": view["result"],
                          "tasks": f"{view['tasks_completed']}/{view['tasks_total']}",
                          "workers_involved": participants, "elapsed_seconds": view["elapsed_seconds"]}, indent=2))
    finally:
        for p in reversed(procs):
            p.terminate()
        for p in reversed(procs):
            try: p.wait(timeout=3)
            except subprocess.TimeoutExpired: p.kill()


if __name__ == "__main__":
    main()
