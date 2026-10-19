from coordinator.core import monte_carlo_pi, prime_count
import multiprocessing


def execute(task):
    kind, params = task["kind"], task["params"]
    if kind == "monte_carlo_pi":
        return monte_carlo_pi(int(params["samples"]), int(params["seed"]))
    if kind == "prime_analysis":
        return prime_count(int(params["start"]), int(params["end"]))
    raise ValueError("task type is not allowlisted")


def _child_compute(task, result_queue):
    try:
        result_queue.put((True, execute(task)))
    except BaseException as exc:
        result_queue.put((False, str(exc)))


def execute_bounded(task, timeout_seconds):
    """Run allowlisted work in a child process that can be terminated on timeout."""
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(target=_child_compute, args=(task, result_queue), daemon=True)
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join()
        raise TimeoutError(f"task exceeded {timeout_seconds}s execution limit")
    if process.exitcode != 0:
        raise RuntimeError(f"task process exited with code {process.exitcode}")
    try:
        ok, value = result_queue.get(timeout=1)
    except Exception as exc:
        raise RuntimeError("task process returned no result") from exc
    finally:
        result_queue.close()
    if not ok:
        raise RuntimeError(value)
    return value
