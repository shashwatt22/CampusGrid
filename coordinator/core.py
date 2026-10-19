"""Thread-safe in-memory coordinator and approved computation functions."""
from __future__ import annotations

import math
import random
import threading
import time
import uuid
from collections import Counter

MAX_PARTITIONS = 256
MAX_PI_SAMPLES = 20_000_000
MAX_PRIME_LIMIT = 100_000_000
HEARTBEAT_TIMEOUT = 12.0
TASK_LEASE_SECONDS = 15.0


def monte_carlo_pi(samples: int, seed: int) -> dict:
    rng = random.Random(seed)
    inside = sum(1 for _ in range(samples) if (x := rng.random()) * x + (y := rng.random()) * y <= 1.0)
    return {"inside": inside, "samples": samples}


def prime_count(start: int, end: int) -> dict:
    """Count primes in inclusive [start, end], using a local sieve."""
    if end < 2 or end < start:
        return {"count": 0, "start": start, "end": end}
    low = max(2, start)
    size = end - low + 1
    sieve = bytearray(b"\x01") * size
    for p in range(2, math.isqrt(end) + 1):
        first = max(p * p, ((low + p - 1) // p) * p)
        if first <= end:
            sieve[first - low::p] = b"\x00" * (((end - first) // p) + 1)
    return {"count": sum(sieve), "start": start, "end": end}


class Grid:
    def __init__(self):
        self.lock = threading.RLock()
        self.workers: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}

    def register(self, data: dict) -> dict:
        wid = data["worker_id"]
        with self.lock:
            old = self.workers.get(wid, {})
            worker = {
                "worker_id": wid, "name": data["name"], "cores": int(data["cores"]),
                "ram_mb": int(data["ram_mb"]), "max_tasks": int(data["max_tasks"]),
                "status": "online", "last_heartbeat": time.time(),
                "active_tasks": old.get("active_tasks", 0), "completed_tasks": old.get("completed_tasks", 0),
            }
            self.workers[wid] = worker
            return dict(worker)

    def heartbeat(self, wid: str, active_tasks: int | None = None):
        with self.lock:
            w = self.workers.get(wid)
            if not w:
                return False
            w["last_heartbeat"] = time.time()
            w["status"] = "online"
            if active_tasks is not None:
                w["active_tasks"] = max(0, int(active_tasks))
            return True

    def create_job(self, kind: str, params: dict) -> dict:
        now = time.time()
        jid = uuid.uuid4().hex[:12]
        partitions = int(params["partitions"])
        job = {"job_id": jid, "type": kind, "params": dict(params), "status": "queued",
               "created_at": now, "started_at": None, "completed_at": None,
               "task_ids": [], "result": None, "error": None}
        with self.lock:
            for i in range(partitions):
                tid = uuid.uuid4().hex[:12]
                if kind == "monte_carlo_pi":
                    base, rem = divmod(params["samples"], partitions)
                    task_params = {"samples": base + (i < rem), "seed": params["seed"] + i}
                else:
                    width = (params["limit"] + partitions - 1) // partitions
                    start, end = i * width + 1, min((i + 1) * width, params["limit"])
                    task_params = {"start": start, "end": end}
                task = {"task_id": tid, "job_id": jid, "kind": kind, "params": task_params,
                        "status": "queued", "worker_id": None, "lease_until": None,
                        "attempts": 0, "result": None, "created_at": now, "completed_at": None}
                self.tasks[tid] = task
                job["task_ids"].append(tid)
            self.jobs[jid] = job
        return self.job_view(jid)

    def _refresh_workers(self):
        now = time.time()
        for w in self.workers.values():
            if now - w["last_heartbeat"] > HEARTBEAT_TIMEOUT:
                w["status"] = "offline"
        for t in self.tasks.values():
            if t["status"] == "assigned" and t["lease_until"] < now:
                old = self.workers.get(t["worker_id"])
                if old:
                    old["active_tasks"] = max(0, old["active_tasks"] - 1)
                t.update(status="queued", worker_id=None, lease_until=None)

    def claim_task(self, wid: str) -> dict | None:
        with self.lock:
            self._refresh_workers()
            w = self.workers.get(wid)
            if not w or w["status"] != "online" or w["active_tasks"] >= w["max_tasks"]:
                return None
            queued = [t for t in self.tasks.values() if t["status"] == "queued"]
            if not queued:
                return None
            task = min(queued, key=lambda t: (t["attempts"], t["created_at"], t["task_id"]))
            task.update(status="assigned", worker_id=wid, lease_until=time.time() + TASK_LEASE_SECONDS,
                        attempts=task["attempts"] + 1)
            w["active_tasks"] += 1
            job = self.jobs[task["job_id"]]
            if job["status"] == "queued":
                job.update(status="running", started_at=time.time())
            return {k: task[k] for k in ("task_id", "job_id", "kind", "params")}

    def complete_task(self, wid: str, tid: str, result: dict) -> tuple[bool, str]:
        with self.lock:
            task = self.tasks.get(tid)
            if not task:
                return False, "unknown_task"
            if task["status"] == "completed":
                return False, "duplicate_result"
            if task["status"] != "assigned" or task["worker_id"] != wid:
                return False, "stale_or_unowned_task"
            if not isinstance(result, dict):
                return False, "invalid_result"
            if task["kind"] == "monte_carlo_pi":
                expected = task["params"]["samples"]
                try:
                    inside, samples = int(result["inside"]), int(result["samples"])
                except (KeyError, TypeError, ValueError):
                    return False, "invalid_result"
                if samples != expected or not 0 <= inside <= samples:
                    return False, "invalid_result"
                result = {"inside": inside, "samples": samples}
            else:
                p = task["params"]
                try:
                    count = int(result["count"])
                    start, end = int(result["start"]), int(result["end"])
                except (KeyError, TypeError, ValueError):
                    return False, "invalid_result"
                if (start, end) != (p["start"], p["end"]) or not 0 <= count <= max(0, end - start + 1):
                    return False, "invalid_result"
                result = {"count": count, "start": start, "end": end}
            task.update(status="completed", result=result, completed_at=time.time(), lease_until=None)
            w = self.workers.get(wid)
            if w:
                w["active_tasks"] = max(0, w["active_tasks"] - 1)
                w["completed_tasks"] += 1
            self._aggregate(task["job_id"])
            return True, "accepted"

    def fail_task(self, wid: str, tid: str, error: str):
        with self.lock:
            task = self.tasks.get(tid)
            if not task or task["status"] != "assigned" or task["worker_id"] != wid:
                return False
            w = self.workers.get(wid)
            if w:
                w["active_tasks"] = max(0, w["active_tasks"] - 1)
            task["last_error"] = str(error)[:300]
            task.update(status="queued", worker_id=None, lease_until=None)
            return True

    def _aggregate(self, jid: str):
        job = self.jobs[jid]
        ts = [self.tasks[t] for t in job["task_ids"]]
        if not all(t["status"] == "completed" for t in ts):
            return
        if job["type"] == "monte_carlo_pi":
            inside = sum(t["result"]["inside"] for t in ts)
            samples = sum(t["result"]["samples"] for t in ts)
            result = {"estimate": 4 * inside / samples, "inside": inside, "samples": samples}
        else:
            result = {"prime_count": sum(t["result"]["count"] for t in ts),
                      "range": [1, job["params"]["limit"]]}
        job.update(status="completed", result=result, completed_at=time.time())

    def snapshot(self) -> dict:
        with self.lock:
            self._refresh_workers()
            workers = [dict(w) for w in self.workers.values()]
            jobs = [self.job_view(jid, locked=True) for jid in self.jobs]
            return {"workers": workers, "jobs": jobs, "stats": {
                "online_workers": sum(w["status"] == "online" for w in workers),
                "cpu_cores": sum(w["cores"] for w in workers if w["status"] == "online"),
                "available_slots": sum(max(0, w["max_tasks"] - w["active_tasks"]) for w in workers if w["status"] == "online"),
                "running_jobs": sum(j["status"] == "running" for j in jobs),
                "completed_jobs": sum(j["status"] == "completed" for j in jobs),
                "failed_jobs": sum(j["status"] == "failed" for j in jobs)}}

    def job_view(self, jid: str, locked: bool = False) -> dict:
        if not locked:
            with self.lock:
                return self.job_view(jid, locked=True)
        j = self.jobs.get(jid)
        if not j:
            return {}
        tasks = [self.tasks[t] for t in j["task_ids"]]
        workers = Counter(t["worker_id"] for t in tasks if t["worker_id"])
        return {"job_id": j["job_id"], "type": j["type"], "params": j["params"], "status": j["status"],
                "created_at": j["created_at"], "started_at": j["started_at"], "completed_at": j["completed_at"],
                "elapsed_seconds": round((j["completed_at"] or time.time()) - (j["started_at"] or j["created_at"]), 3),
                "result": j["result"], "error": j["error"], "tasks_completed": sum(t["status"] == "completed" for t in tasks),
                "tasks_total": len(tasks), "workers_involved": dict(workers),
                "tasks": [{"task_id": t["task_id"], "status": t["status"], "worker_id": t["worker_id"],
                           "attempts": t["attempts"], "result": t["result"]} for t in tasks]}
