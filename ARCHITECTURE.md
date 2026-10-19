# CampusGrid architecture

## Coordinator and workers

The coordinator is a threaded Python HTTP service. It owns the worker registry, in-memory job/task state, task leases, and result aggregation. Worker processes initiate all connections by polling; the coordinator does not open inbound connections to worker laptops. This central scheduler is simpler to operate than a decentralized peer-to-peer protocol and is the MVP's explicit architecture boundary. Worker IDs are random; names are provided by the student, not read from the machine hostname by default.

```text
Browser dashboard ──HTTP──> Coordinator <──HTTP polling── Worker A
                                  ▲       <──HTTP polling── Worker B
                                  └── owns job, task, lease, and result state
```

## Scheduling and task lifecycle

Job creation validates an allowlisted type and bounded parameters, creates uniquely identified partitions, then queues them. A worker with a free slot polls for one task. The coordinator assigns a lease and increments its active count. The worker computes locally and submits a result tied to its registered worker ID. The coordinator accepts only the active task owner, rejects a duplicate or late result, decrements the active count, and aggregates after every partition completes.

Worker heartbeats update liveness. A worker silent for 12 seconds becomes offline. Assigned tasks whose 15 second lease expires are returned to the queue. Retried task executions are deterministic for Monte Carlo because each partition has its own stored seed; prime partitions are disjoint. Aggregation counts each accepted partition once.

The scheduler is deterministic and capacity-aware only through currently free task slots and worker availability. It does not claim optimal placement, CPU benchmarking, or fairness.

## Communication and authentication

JSON HTTP endpoints are used for registration, heartbeats, polling, results, and job submission. Worker operations require a worker bearer token in `X-Worker-Token`; job submission requires a separate admin token in `X-Admin-Token`. The same worker token is shared across workers in this prototype. API parameters are checked on the server and task functions are selected from a fixed allowlist.

HTTP does not encrypt credentials. Bind to localhost by default. For a live multi-laptop demo, use only a private trusted LAN, restrict Windows Firewall to `LocalSubnet`, and avoid port forwarding. Any untrusted network requires HTTPS or a secure tunnel and stronger per-worker identity.

## Security boundaries

Workers execute only the bundled Monte Carlo and prime-analysis functions. There are no shell, Python-eval, arbitrary code upload, executable download, remote desktop, or coordinator-side filesystem APIs. Workloads have server-enforced sample/range/partition bounds. Reported core and RAM data are advisory; the prototype does not enforce hard CPU or memory isolation. A voluntary worker should be stopped by Ctrl+C and should not join a network it does not trust.

## Failure recovery and current limits

Heartbeats mark stale nodes offline; leases requeue unfinished tasks. Late results from a prior lease owner are rejected. The implementation stores current state in process memory, so coordinator restart loses in-flight and completed jobs. This is acceptable for the screening demo, not durable production operation. The dashboard is served by the coordinator and reflects API state directly.
