import unittest

from coordinator.core import Grid, monte_carlo_pi, prime_count


class AlgorithmTests(unittest.TestCase):
    def test_monte_carlo_is_reproducible_and_bounded(self):
        a = monte_carlo_pi(20_000, 123)
        self.assertEqual(a, monte_carlo_pi(20_000, 123))
        self.assertEqual(a["samples"], 20_000)
        self.assertTrue(3.0 < 4 * a["inside"] / a["samples"] < 3.3)

    def test_prime_count_inclusive(self):
        self.assertEqual(prime_count(1, 10)["count"], 4)
        self.assertEqual(prime_count(11, 20)["count"], 4)
        self.assertEqual(prime_count(20, 10)["count"], 0)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.grid = Grid()
        self.grid.register({"worker_id": "w1", "name": "Worker 1", "cores": 4, "ram_mb": 8192, "max_tasks": 1})
        self.grid.register({"worker_id": "w2", "name": "Worker 2", "cores": 4, "ram_mb": 8192, "max_tasks": 1})

    def test_respects_capacity_and_assigns_multiple_workers(self):
        self.grid.create_job("monte_carlo_pi", {"samples": 32, "partitions": 8, "seed": 1})
        assigned = []
        for wid in ("w1", "w2"):
            assigned.append(self.grid.claim_task(wid))
            self.assertIsNone(self.grid.claim_task(wid))
        self.assertTrue(all(assigned))
        self.assertNotEqual(assigned[0]["task_id"], assigned[1]["task_id"])

    def test_offline_worker_gets_no_task(self):
        self.grid.create_job("monte_carlo_pi", {"samples": 8, "partitions": 1, "seed": 1})
        self.grid.workers["w1"]["last_heartbeat"] -= 100
        self.assertIsNone(self.grid.claim_task("w1"))

    def test_aggregation_and_duplicate_result_protection(self):
        job = self.grid.create_job("prime_analysis", {"limit": 20, "partitions": 2})
        for wid in ("w1", "w2"):
            task = self.grid.claim_task(wid)
            params = task["params"]
            result = prime_count(params["start"], params["end"])
            ok, _ = self.grid.complete_task(wid, task["task_id"], result)
            self.assertTrue(ok)
            if wid == "w1":
                self.assertEqual(self.grid.complete_task(wid, task["task_id"], result), (False, "duplicate_result"))
        view = self.grid.job_view(job["job_id"])
        self.assertEqual(view["status"], "completed")
        self.assertEqual(view["result"]["prime_count"], 8)

    def test_expired_lease_is_reassigned_to_another_worker(self):
        self.grid.create_job("monte_carlo_pi", {"samples": 16, "partitions": 1, "seed": 4})
        first = self.grid.claim_task("w1")
        self.grid.tasks[first["task_id"]]["lease_until"] = 0
        second = self.grid.claim_task("w2")
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(self.grid.tasks[first["task_id"]]["worker_id"], "w2")
        self.assertEqual(self.grid.tasks[first["task_id"]]["attempts"], 2)


if __name__ == "__main__":
    unittest.main()
