# CampusGrid demo guide

## One laptop: multi-process demonstration

Open three PowerShell terminals in the project directory. Set the same `CAMPUSGRID_WORKER_TOKEN` in the coordinator and both workers. Set a separate `CAMPUSGRID_ADMIN_TOKEN` in the coordinator.

1. Start coordinator: `python -m coordinator.main`.
2. Start workers in separate terminals:

```powershell
python -m worker.worker --server http://127.0.0.1:8000 --name Laptop-A --worker-id laptop-a
python -m worker.worker --server http://127.0.0.1:8000 --name Laptop-B --worker-id laptop-b
```

3. Open `http://127.0.0.1:8000`, enter the admin token, and submit Monte Carlo π with 1,000,000 samples and 8 partitions.
4. Show both nodes online, task counts progressing, and the final estimate plus worker IDs.

Label this accurately as a **multi-process local demonstration**. The two workers are processes on one physical laptop.

## Multiple laptops

1. On the coordinator laptop set `CAMPUSGRID_HOST=0.0.0.0`, the worker token and admin token, then run the coordinator.
2. Use `ipconfig` to identify the coordinator's private IPv4 address.
3. Restrict inbound TCP port 8000 to `LocalSubnet` using the rule in README.md.
4. Teammates on the same trusted LAN run `python -m worker.worker --server http://<COORDINATOR-IP>:8000 --name <TEAMMATE-NAME> --token <SHARED-WORKER-TOKEN>`.
5. Verify worker rows appear before submitting a multi-partition job.

Call this a **multi-machine demonstration** only when the dashboard shows workers registered from separate laptops and the demo was actually run across those laptops. This repository's automated integration test does not verify LAN or Windows Firewall behavior.

## 20–30 second capture

- 0–5 s: show the live worker network and online node count.
- 5–10 s: select Monte Carlo π and submit 1,000,000 samples / 8 partitions.
- 10–20 s: show both worker IDs receiving real partition assignments and progress moving.
- 20–30 s: show the computed estimate, total sample count, completion state, and participating worker IDs.

Do not replace the live dashboard with fabricated workers or predetermined results. Small test runs may complete quickly; increase samples within the server cap if the screen needs longer visible progress.
