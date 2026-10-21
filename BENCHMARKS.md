# Benchmark results · 21 October 2026

Measured locally using Docker Desktop on Apple Silicon, PostgreSQL 16, Redis 7 and Python 3.12. No paid/live Telegram/OpenAI calls. Latest build run under shared local host load; no confidence interval, production capacity or speech accuracy guarantee.

| Measurement | Result | Scope |
|---|---|---|
| Concurrent task creations | 100/100 committed; 0 errors | Actual API, JWT, Redis limiter, PostgreSQL, outbox |
| Average / p95 API latency | 494.58 / 501.68 ms | HTTPX in-process ASGI transport; no reverse-proxy/network RTT |
| Task creation throughput | 190.54 creations/s | Entire 100-request burst, not sustained quota bypass |
| Owner event latency | 58.78 ms | TCP SSE + real Redis/outbox, from explicit dispatch |
| Queue throughput | 35.47 jobs/s | Real Celery Redis queue, 20 synthetic 50ms jobs, two prefork children |
| Synthetic transcription average service | 51.90 ms | Fixture sleep + Redis instrumentation; no audio recognition |
| Synthetic queue-to-finish p95 | 530.48 ms | Enqueue through completion for the same 20 jobs |
| Synthetic outcomes | 16 success / 4 injected failures; 80% / 20% | Deliberately constructed outcomes, **not Whisper success/failure accuracy** |
| Worker concurrency | 2 simultaneous executions observed | Atomic Redis high-water measurement and two blocked voice slots |
| Tenant task-list query average / p95 | 0.55 / 0.68 ms | 20 warm PostgreSQL queries over 100 tasks, each returning 20 owned rows |
| Prior audit: actual paused PostgreSQL failure response | 7.05 s, HTTP 503; recovery 200 | Disposable QA deployment only |
| Prior audit: actual paused Redis failure response | 4.12 s, HTTP 503; recovery 200 | Disposable QA deployment only |
| Live Whisper latency/success/WER/cost | Not measured | Requires authorized provider credentials and consented labeled audio |

Reproduce API/query/queue/SSE measurements with `make test-integration`; JSON and event timings are printed in `reports/audit-integration.log`. The integration fixture uses ten DB pool connections plus ten overflow; production API/bot defaults are five plus ten. The API test asserts all 100 responses are 201 and all tasks exist. The queue test asserts all 20 results, the exact injected 16/4 outcomes, and observed concurrency of two. It also holds both voice slots while an independent notifications process delivers a text-task event. These are integrity assertions; timing is reported, not compared against arbitrary shared-runner thresholds.

SSE timing starts at explicit outbox dispatch; production's one-second scheduler adds up to a tick plus queue/service load. The protocol used by this application is SSE, not WebSocket. Query measurements include ORM/driver round trips on a tiny warm table; they are not large-dataset EXPLAIN/production I/O results. Calibrate realistic tenant sizes and sustained load on a stable staging runner before enforcing performance budgets.

For network HTTP measurement, set `TASKBOT_BENCH_URL` and `TASKBOT_BENCH_TOKEN` for a disposable development API, then run `make benchmark`. Use its exact configured frontend origin. It creates 100 tasks, settles every request, reports average/p95/throughput/errors, and deletes the returned task IDs through the normal API. API limits remain enabled: cleanup honors Retry-After up to 60 seconds per wait, three attempts per item, within a 180-second cleanup budget (an in-flight request can add its 30-second timeout). Cleanup failures are counted and cause a nonzero exit. Inspect reported leftovers before discarding the deployment. Mocked tests exercise transport/malformed responses and both successful and exhausted 429 cleanup; no real minute-long unit-test sleep is used.

`docker compose exec -T api python -m scripts.metrics` supplies retained job status/failure counts, retries and latency/cost estimates, pending/dead-letter effects, Redis queue depths, responding worker queues and daily provider counters. The current CLI also reports daily API request/error rates and retained task totals. Daily counters expire after seven days and are not a billing ledger; stored estimates do not reconcile potentially billed provider retries.

Deterministic task-field evaluation passes 8/8 checked-in examples. It is separate from Whisper speech recognition and does not establish general Armenian/English accuracy. The service voice E2E decodes real audio while mocking HTTP provider edges; live speech WER and Telegram acknowledgment latency remain staging work.

Optional free speech check: `make test-local-ai` passed with an actual local tiny model on an 11-second public English sample. The complete worker/task/SSE pipeline measured **7.36 seconds** (13.74 seconds for the pytest run), excluding model/image download and service startup. Docker Desktop amd64 emulation was used on Apple Silicon; this is one functional measurement, not a comparative speech benchmark or Armenian WER. Provider estimate was **$0** and no OpenAI HTTP call occurred. See `reports/local-ai-real-test.log` / `reports/local-ai.xml`.
