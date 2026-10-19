# Test report

Executed in the available Python 3.12 environment on 2026-10-19.

## Automated checks

- Unit suite: `python -m unittest discover -s tests -v`
- Process integration: `python scripts/integration_demo.py`
- Syntax check: `python -m compileall -q coordinator worker tests scripts`

## Results

- Unit tests: **6 passed, 0 failed**.
- Syntax check: **passed**.
- Integration: **passed** using one coordinator process and two independent worker processes.
- API checks: dashboard HTML served; invalid worker and admin credentials each received HTTP 401.
- Workload: Monte Carlo π, 500,000 samples split into 12 tasks; all 12 completed.
- Workers: both `integration-1` and `integration-2` participated (5 and 7 tasks in this run).
- Aggregated result: estimate `3.137736`, inside count `392,217`, sample count `500,000`.
- Observed coordinator job duration: `2.339` seconds for this run. It is a single local measurement; no single-process comparison or speedup claim was measured.

## Manual checks and limits

- Dashboard/API checks performed in this environment are localhost checks only.
- Separate physical laptops and Windows Firewall/LAN connectivity require the supplied manual setup and were not available to verify here.
- No speedup claim is made. Benchmark results are machine-dependent and not measured as a screening metric.
