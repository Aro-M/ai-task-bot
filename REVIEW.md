> **Historical audit before the Next.js/aiogram build migration.** Findings and their original evidence are preserved below. Versions, queue/state descriptions, counts and score refer to that earlier snapshot; they are not a current release certification. See [IMPLEMENTATION.md](IMPLEMENTATION.md) and [VERIFICATION.md](VERIFICATION.md) for the current system and evidence.

# AI Task Bot — production review · 21 October 2026

## 1. Executive Summary

Production audit: **82/100, suitable for private staging with caveats**. Local security, persistence, queue recovery and browser journeys were exercised and focused defects fixed. A public launch still requires live Telegram/OpenAI validation and the protected hosted release/deployment procedure. The score expresses engineering confidence, not a certification or proof of every possible failure.

The strongest invariants are database-owned tasks, tenant authorization, unique Telegram/task identities, a transactional outbox, bounded audio processing, and independent transcription/effect workers. No source was uploaded for external review, no paid provider calls were made, and no registry, webhook or remote deployment was changed. Local application data and credentials were preserved.

## 2. Issue Report

No Critical vulnerability was established in the inspected surface. IDs identify review findings, including evidence gaps; “Proposed” does not mean an unverified vulnerability was reproduced.

| ID | Severity | Area | Issue / impact | Root cause | Recommended fix | Status |
|---|---|---|---|---|---|---|
| AI-R01 | High | Security | Public example production secrets accepted; validation could echo sensitive input | Sentinel values passed length checks; default validation error formatting | Reject example sentinels and hide validation inputs | Fixed |
| AI-R02 | High | Worker/Redis | Busy voice slots delayed text confirmations and dashboard events | Dispatcher shared the transcription queue | Dedicated effects queue/process and expiring scheduler ticks | Fixed |
| AI-R03 | High | Worker/Redis | Stale/infrastructure-failed jobs could requeue indefinitely | Recovery had no durable shared retry budget, lifetime or terminal handling | Three shared retries, 24h lifetime, failed-job storage and seven-day purge | Fixed |
| AI-R04 | High | API/DB | Paused PostgreSQL left requests hanging | Driver query/connect and pool waits were not bounded | 3s connect/pool waits, 5s commands, safe 503 | Fixed |
| AI-R05 | Medium | API/deployment | Replacing API caused continuing Nginx 502s | Upstream Docker IP resolved only at startup | Runtime Docker DNS resolution with 5s cache | Fixed |
| AI-R06 | Medium | Worker/DB | Account deletion and stale recovery could deadlock | Recovery locked job before owner | Shared owner-before-job locking, skip locked busy work | Fixed |
| AI-R07 | Medium | Bot/AI | Transient Telegram download failures immediately lost voice attempts | Download had no bounded transient retry | Three attempts, jitter and partial-file cleanup | Fixed |
| AI-R08 | Medium | Bot/AI | Useful transcripts over 300 characters were rejected | Full transcript was used as bounded title | Preserve up to 5,000 normalized characters; use original prefix as title and full description | Fixed |
| AI-R09 | Medium | Frontend | Muted text/control contrast failed automated WCAG AA rules | Existing palette/control colors were too faint | Adjust existing tokens and verify login/dialog/list/board | Fixed |
| AI-R10 | Medium | Security/tests | JWT test survived disabling signature checks | Only malformed-token tampering was asserted | Add valid-format attacker-signed token and targeted mutation checks | Fixed |
| AI-R11 | Medium | Performance/tests | Benchmark silently left tasks after rate-limited deletes | 100 creates plus 100 deletes exceeded 120/min quota; delete responses ignored | Settle all requests, honor bounded Retry-After, report cleanup errors and exit nonzero | Fixed |
| AI-R12 | Medium | Worker/observability | Failed effects retried every tick; pools/backlog/metrics lacked explicit bounds | Retry deadlines and operational aggregation were absent | Persist deadlines/dead-letter codes; cap pools, global voice admission and Redis memory; private aggregate metrics CLI | Fixed |
| AI-R13 | Low | Operations/CI | Runtime lacked maintenance scripts; failed integration runs lost reports; audio storage unbounded on disk | Packaging and test target gaps | Package scripts, preserve test exit while collecting reports, bounded RAM worker temp storage | Fixed |
| AI-R16 | Low | QA tooling | Container-browser login failed after API replacement | Fault tool let Compose fall back to its default origin | Preserve the inspected effective origin and assert replacement configuration | Fixed |
| AI-R14 | High | AI/release | Real recognition, provider behavior and billing remain unverified | No authorized live calls or consented labeled speech corpus | Private staging run with Armenian/English recordings, measured WER and provider cost | Proposed |
| AI-R15 | High | CI/CD | Hosted CI and deployed release/restore procedures remain unverified | No remote run/deployment environment was authorized | Run protected CI, configure release reviewers/private registry, rehearse migration/restore and smoke checks in staging | Proposed |

## 3. Implemented Fixes

| Finding | Files changed | Before → after | Regression evidence |
|---|---|---|---|
| R01 | `app/config.py`, `tests/unit/test_core.py` | Example secrets and echoed inputs → rejected placeholders and redacted errors | Production safety and error privacy tests |
| R02 | `app/worker.py`, `docker-compose.yml`, `tests/queue_tasks.py`, integration tests | Shared voice/effect slots → two voice processes and independent effect dispatcher | Real Celery saturation test, two voice slots occupied while event arrives |
| R03 | `app/worker.py`, `app/api.py`, `app/config.py`, pipeline/API/integration tests | Unlimited recovery → persisted shared retry budget, expiry, terminal failure and retention | Retry-to-success/dead-letter, both expiry paths, manual retry refusal, retention preserving tasks |
| R04 | `app/db.py`, `app/api.py` | Unbounded dependency wait → driver/pool deadlines and safe response | Real paused PostgreSQL/Redis operational checks |
| R05 | `frontend/nginx.conf`, `tests/operations.py` | Stale upstream → five-second Docker DNS refresh | Replace API at a different IP; frontend stays running |
| R06 | `app/worker.py`, integration tests | Inverted locks → shared `locked_job()` order | Concurrent account deletion/recovery and processing/retry tests |
| R07 | `app/audio.py`, pipeline tests | Single download attempt → bounded transient retries, permanent refusal, safe cleanup | Metadata 503, interrupted stream, exhaustion, 404 and existing-file preservation |
| R08 | `app/services.py`, core/pipeline tests | Long useful input rejected → original bounded title plus full normalized description | Long Armenian text and voice preservation |
| R09 | `frontend/src/styles.css`, real browser suite | Faint secondary UI → passing tested axe contrast checks | Chromium, Firefox, WebKit and viewport bounds |
| R10 | `tests/unit/test_auth.py`, `scripts/check_mutations.py` | Weak malformed-token test → adversarial signed token fails | Eight selected mutations detected by assertions |
| R11 | `scripts/benchmark.py`, `tests/unit/test_scripts.py` | Ignored cleanup failures → bounded Retry-After handling, error accounting, nonzero exit | Mixed transport failures, settled requests, successful/repeatedly throttled cleanup |
| R12 | `app/models.py`, `migrations/versions/0002_outbox_backoff.py`, worker/audio/events/API/DB, `scripts/metrics.py`, Compose | Tick retries/unbounded defaults → durable effect deadlines, terminal code, explicit caps and aggregate counters | Backoff/retention/privacy tests, cross-user PostgreSQL admission race, nonempty migration downgrade/upgrade |
| R13/R16 | `Dockerfile`, `Makefile`, Compose, `tests/operations.py` | Missing runtime cleanup/report loss → packaged maintenance and failure-safe collection; RAM temp cap | Runtime dry-run, successful/failed report-target simulation, origin-preserving API replacement assertion and Compose checks |

Migration 0002 adds nullable effect error metadata and a required availability timestamp with a database default; existing rows are backfilled and older inserts remain compatible during an upgrade. The PostgreSQL roundtrip test retains task/outbox data. Stop new consumers before downgrading this migration. This test does not replace a real backup/restore rehearsal.

Dead-letter job storage reuses `TranscriptionJob(status=FAILED, error_code=dead_letter/expired)`; no second queue/database is introduced. Failed effects retain their original kind/quota identity, a safe error code and empty payload. Dispatcher purge removes these terminal records after seven days while preserving tasks. Recovery runs only when PostgreSQL is reachable; broker expiry alone is not relied on to remove stale work.

## 4. Tests Added

The complete named inventory, purpose/type and runnable selectors are in [TEST_INVENTORY.md](TEST_INVENTORY.md). Parameterized Python cases are listed individually; browser cases identify their engine/device repetitions. [TESTING.md](TESTING.md) explains fixtures and mock boundaries.

| Layer | Final local result | Command |
|---|---|---|
| Python unit/security/audio/AI/scripts | 178 passed; combined statement/branch app coverage 92.67% | `make test-unit` |
| PostgreSQL/Redis/Celery/SSE/service E2E | 19 passed | `make test-integration` |
| React/API client | 13 passed; 95.41% line / 90% branch coverage | `make test-unit` |
| Desktop/mobile mock-edge browser | 8 passed | `make test-e2e` |
| Real-stack Chromium/Firefox/WebKit | 3 passed on pinned Linux Playwright image | `make test-e2e-live` on Linux |
| Targeted mutations | 8/8 detected in temporary copies | `make test-mutations` |
| Operational faults | 8 checks on disposable QA stack | `uv run python -m tests.operations` after QA setup |
| Extraction fixtures | 8/8; deterministic extraction only | `uv run python -m scripts.evaluate_ai` |

Total: **221 ordinary automated test cases**, plus mutation, operational and runtime checks. Ruff, Black, mypy, ESLint, Prettier and TypeScript pass. Dependency audits report no known vulnerabilities. Full Bandit has three low-severity non-security random-jitter findings and one medium intentional `0.0.0.0` container binding; no high findings. Gitleaks scans the current authored source, including untracked files, in a local offline container with redacted output.

Raw evidence is in ignored `reports/`: `review-unit-final.log`, `review-integration-final.log`, `review-browser-final.log`, `review-linux-browser-final.log`, `review-mutations-final.json`, `qa-resilience.json`, `review-security-final.log`, `review-bandit.json`, `review-secrets-final.log`, JUnit and Linux browser traces/screenshots. Earlier before-fix regression/fault reports remain there for comparison.

## 5. Reliability Configuration

Values below are code defaults; deployment environment may lower quotas or change supported audio/job limits. Limits are validated centrally in `Settings`; fixed retry/retention policies are constants.

| Control | Final value / behavior |
|---|---|
| Job retry budget | 3 retries after initial execution, shared by infrastructure failures, crash reconciliation and manual retry; retry count committed after processing rollback |
| Celery retry backoff | Base 2s, exponential, cap 60s, full jitter; task max retries 3 |
| Stale queued reconciliation | Older than max(300s, 3×job timeout); at most 100 candidates per dispatch tick; owner/job locks prevent overlap |
| Job lifetime | 24h from original creation, including manual retries; checked before provider work and by reconciliation |
| Terminal retention | Dead-letter/expired job and failed-effect metadata 7d, automatically purged by dispatcher; ordinary delivered outbox metadata 30d via scheduled maintenance |
| Effect retries | 12 attempts, persisted availability deadline; uniform jitter from 1s to min(60s, 2^attempt); at most 24h lifetime; content removed on terminal failure |
| Job timeout | 60s asyncio budget, Celery soft 80s/hard 90s; configurable base 1–600s |
| Worker shutdown | Voice grace 90s; dispatcher grace 110s; late ack, reject on worker loss, prefetch 1 |
| Broker visibility | max(300s, 3×job timeout); durable PostgreSQL reconciliation covers lost messages |
| Dispatcher schedule | Every 1s on effects queue; tick expires after 5s; 10 effects per invocation |
| Audio/provider retries | 3 attempts each; 1s then 2s exponential delays plus 0–0.25s jitter; permanent 4xx except 429 refused |
| External/tool deadlines | Telegram download HTTP 15s, provider HTTP min(30s, job timeout), each ffprobe/ffmpeg subprocess 15s; Telegram notifications connect 2s/read/write 3s |
| Circuit breaker | Shared Redis failure counter, expires 60s after failure; ≥5 transient HTTP failures opens circuit 30s; valid response clears failure counter; cooldown admits new probes |
| Admission | 2 active/user, 10/hour, 30/day by code default (example env 20/day); global 1,000 active voice jobs with PostgreSQL advisory serialization |
| Rate limits | API 120 requests/user/min; OTP login 5/IP/min; AI 60 provider attempts/min globally; Redis failure fails closed |
| Request/data limits | Nginx 64KiB request body; title 300, normalized extracted text 5,000 characters; audio default 1–120s and 20MiB; list pages at most 100 |
| Concurrency | Voice worker 2 prefork children; effects worker 1; singleton scheduler; worker row/source-key locks prevent duplicate tasks |
| DB pools | Each API/bot process 5 persistent + 10 overflow, pool wait 3s; asyncpg connect 3s/command 5s; worker NullPool (one loop per invocation); migration NullPool |
| Redis pools/memory | API max 100 connections, event/audio clients max 20 each, broker connection pool 10/transport max 20, metrics max 2; application connect 2s/socket 3s; broker 3s; Redis 256MiB, noeviction |
| Temporary storage | Worker `/tmp` RAM mount 128MiB; private directories removed on normal completion, error and cancellation |
| Tokens/streams | OTP 5min single use, JWT 15min HttpOnly/SameSite strict; SSE ends at session lifetime and reconnects/refetches |
| Health/metrics | API DB+Redis health; bot liveness; per-worker targeted Celery ping in Compose; private `python -m scripts.metrics` includes responding queues, depths, job outcomes, retries, latency, provider attempts/HTTP failures and cost estimates |
| Correlation/privacy | API-generated request IDs in header/logs; queue processing correlated by stable job/outbox IDs; structured application logs whitelist fields and omit audio/transcripts/provider bodies |

Global voice admission and broker memory are bounded. Aggregate task/outbox database growth still depends on user count, rate limits and regular maintenance; there is no global task-storage quota. Redis noeviction returns errors at its cap; accepted writes remain in PostgreSQL/outbox until expiry/recovery. Monitor disk capacity and pending/dead-letter counts. A disabled dispatcher delays expiry/purge until it returns.

Provider counters use UTC-day Redis hashes with seven-day TTL. Estimates cover recorded job cost, not a billing ledger or potentially billed failed attempts. `provider_today_utc.elapsed_ms` includes retry waiting; job latency and benchmark HTTP/service latency have separate scopes. The CLI is operator-only and exposes no task text or public endpoint. API request IDs are not full distributed tracing/span propagation.

## 6. Benchmark Results

See [BENCHMARKS.md](BENCHMARKS.md) for measured local conditions, results, reproduction and exclusions. API, SSE, PostgreSQL queries and actual Celery prefork execution were measured. Synthetic provider outcomes are deliberately labeled; no live Whisper accuracy or production capacity claim is made.

## 7. Remaining Risks

- **R14/R15 remain release gates:** no live Telegram/OpenAI, hosted GitHub Actions, registry publication, TLS deployment or actual backup restore. Use private staging and consented recordings; configure release environment reviewers before enabling CD.
- CD builds/pushes immutable images after exact-commit CI, but staging/production migration, smoke and rollback execution is operator-managed. README documents the procedure; no automatic deployment/rollback is claimed.
- Circuit cooldown can admit multiple concurrent probes; a strict single half-open lease is not implemented. Existing rate/admission bounds constrain exposure. Provider billing may include retries not represented in successful-job estimates.
- Relative dates are UTC heuristics; negation/conflicting dates/arbitrary language are not generally understood. Users must review extracted fields. The eight-case fixture is regression evidence, not language accuracy.
- No generative structuring LLM or model-triggered tools exist; malformed LLM JSON/tool-administration tests are N/A. Untrusted text remains task data and cannot execute instructions.
- At-least-once Telegram delivery may duplicate a notification after an ambiguous crash; unique task source keys prevent task duplication. Hard SIGKILL can leave RAM audio until container removal; no kill test with sensitive recordings was performed.
- Processing remains externally queued until its locked transaction commits. A copied JWT may remain usable until 15min expiry after logout; account deletion invalidates ownership through DB.
- Automated axe/keyboard/layout checks passed; no manual screen-reader audit, committed visual comparison baseline or real-user INP/Core Web Vitals measurement. Native local Firefox could not initialize; all three engines were verified in the pinned Linux container.
- Concurrent builds/browser runs on the shared local Docker VM temporarily caused health-probe timeouts; all application services recovered after disposable QA teardown. Calibrate CPU/memory and health budgets on the intended staging host.
- Full application logs are filtered, but external provider/database/platform logs have their own retention/redaction controls; review those in staging. Dependency audits are point-in-time checks, not vulnerability-free guarantees.

## 8. Final Verification Checklist

| Requirement | Result / evidence |
|---|---|
| Text task creation | PASS: bot/service/browser journeys |
| Voice task creation | PASS with mocked provider edges and real audio decoding/queue/DB; live speech pending |
| Whisper failure fallback | PASS: timeout/429/5xx/empty/unsupported/malformed/low-confidence fixtures |
| Redis failure/recovery | PASS: unit/integration plus actual isolated service pause |
| PostgreSQL failure/recovery | PASS: actual isolated pause, bounded failure and recovery |
| Duplicate updates/jobs | PASS: concurrent redelivery and unique source keys |
| Job timeout/TTL | PASS: timeout tests, expiry before provider and reconciliation expiry |
| Retry backoff | PASS: bounded provider attempts, persistent effect deadline and configured Celery jitter |
| Repeated failures dead-lettered | PASS: real PostgreSQL exhaustion and content-free effect terminal storage |
| Temporary audio deletion | PASS on tested normal/error/cancellation paths; hard-kill limit above |
| Dashboard real-time updates | PASS: real SSE ownership plus independent effects worker saturation |
| Ownership isolation | PASS: API/service/browser IDOR tests |
| Secret handling/log privacy | PASS for inspected authored source/application logger; live platform controls pending |
| Unit/integration/E2E/security tests | PASS locally; named inventory and raw reports linked above |
| Compose/build/migration | PASS locally, including nonempty migration roundtrip and runtime smoke |
| CI pipeline | NOT RUN hosted; local constituent checks pass and workflow reviewed |
| Public production readiness | CONDITIONAL: private staging/provider/deployment gates remain |
