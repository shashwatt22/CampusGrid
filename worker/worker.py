from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import platform
import threading
import time
import urllib.error
import urllib.request
import uuid

from worker.capabilities import get_capabilities
from worker.executor import execute_bounded


def request(server, path, token, method="GET", payload=None, timeout=5):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(server.rstrip("/") + path, data=data, method=method,
                                 headers={"X-Worker-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read() or b"{}")


def run(server, name, token, max_tasks=1, poll=0.35, worker_id=None, max_task_seconds=60):
    wid = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    caps = get_capabilities(max_tasks)
    request(server, "/api/workers/register", token, "POST", {"worker_id": wid, "name": name, **caps})
    print(f"Registered {name} ({wid}) with {caps['cores']} cores, {caps['ram_mb']} MB RAM, {max_tasks} task slot(s)")
    stop = threading.Event()
    active = set()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max_tasks)
    def finish_task(task, future):
        try:
            result = future.result()
            request(server, f"/api/tasks/{task['task_id']}/result", token, "POST", {"worker_id": wid, "result": result})
            print(f"Completed task {task['task_id']} for job {task['job_id']}")
        except Exception as e:
            try:
                request(server, f"/api/tasks/{task['task_id']}/failure", token, "POST", {"worker_id": wid, "error": str(e)[:200]})
            except Exception:
                pass
            print(f"Task {task['task_id']} failed: {e}")
        finally:
            active.discard(future)
    last_heartbeat = 0.0
    try:
        while not stop.is_set():
            active.intersection_update([f for f in active if not f.done()])
            if time.monotonic() - last_heartbeat >= 3:
                try:
                    request(server, f"/api/workers/{wid}/heartbeat", token, "POST", {"active_tasks": len(active)})
                except Exception as e:
                    print(f"Heartbeat unavailable: {e}")
                last_heartbeat = time.monotonic()
            if len(active) < max_tasks:
                try:
                    task = request(server, f"/api/workers/{wid}/task", token).get("task")
                    if task:
                        future = pool.submit(execute_bounded, task, max_task_seconds)
                        active.add(future)
                        future.add_done_callback(lambda f, t=task: finish_task(t, f))
                except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                    print(f"Coordinator unavailable; retrying: {e}")
                except Exception as e:
                    print(f"Polling error: {e}")
            time.sleep(poll)
    except KeyboardInterrupt:
        print("Stopping worker after active tasks finish...")
    finally:
        pool.shutdown(wait=True, cancel_futures=False)


def main():
    ap = argparse.ArgumentParser(description="Voluntary CampusGrid compute worker")
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--name", default="CampusGrid worker")
    ap.add_argument("--token", default=os.environ.get("CAMPUSGRID_WORKER_TOKEN", "dev-worker-token"))
    ap.add_argument("--max-tasks", type=int, default=1)
    ap.add_argument("--worker-id")
    ap.add_argument("--max-task-seconds", type=int, default=60)
    args = ap.parse_args()
    if not 1 <= args.max_tasks <= 16 or not 1 <= args.max_task_seconds <= 300:
        ap.error("max-tasks must be 1..16 and max-task-seconds must be 1..300")
    run(args.server, args.name, args.token, args.max_tasks, worker_id=args.worker_id,
        max_task_seconds=args.max_task_seconds)


if __name__ == "__main__":
    main()
