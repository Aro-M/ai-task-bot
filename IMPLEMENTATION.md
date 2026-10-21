# AI Task Bot implementation · 21 October 2026

The existing system now uses the requested aiogram 3 bot and Next.js dashboard, with asynchronous Whisper work, durable failure handling and deployment tooling. Local build/runtime and tests are verified below. External release gates remain explicit.

| Requirement | Implementation | Evidence |
|---|---|---|
| Telegram text, commands and ownership | aiogram 3; profile updates; `/start`, `/help`, `/tasks`, `/login`; input/admission limits and update deduplication | Unit, PostgreSQL concurrent redelivery and service E2E |
| Local polling / production webhook | Commit-before-offset polling; bounded Telegram client; shared-secret webhook; no automatic webhook changes | Polling failure/retry/cancellation tests and webhook service E2E |
| Voice off request path | PostgreSQL job plus outbox → Redis/Celery → bounded download/actual decode → Whisper → task + events/confirmation | Real Redis, Celery, PostgreSQL, decoded audio; HTTP providers mocked |
| Retry, TTL and recovery | Visible PROCESSING claim, RETRYING, DEAD_LETTER, stale claim recovery, shared infrastructure budget, provider jitter, Retry-After | Unit failures, locking/redelivery/concurrency integration, migration roundtrip |
| Data safety | Unique voice task key, tenant context, owner-before-job locks, global admission serialization, finally cleanup | Ownership/privacy, concurrency, cleanup and mutation checks |
| API | Task CRUD, filters/search/source/sort/stats, pagination, job retry, correlated safe errors and live/ready health | Unit/API, real DB/Redis and runtime smoke |
| Dashboard | Next.js 16 + strict TypeScript; list/board, CRUD, status/search/filter, creation/due time, accessible dialog, loading/empty/error states | React/API tests, desktop/mobile and three-engine real-stack browser tests |
| Real time | Tenant Redis Pub/Sub + authenticated SSE + reconnect refetch; task and transcription events | Real HTTP SSE/isolation and browser remote-event journeys |
| Security | Single-use bot code → HttpOnly JWT cookie; Origin/CSRF; validation/limits; content-free logs; generated hydration CSP | Auth/privacy/XSS tests, axe, dependency/secret/static scans |
| Containers | Dedicated API/bot/worker/frontend Dockerfiles, common locked Python base, PostgreSQL16/Redis7 volumes, health/restart and isolated consumers | Compose build/start, role queues and readiness smoke |
| CI/CD | Locked CI checks/scanners/build/browser flows; private SHA image publication; protected manual staging/production deploy with migration/readiness | Local commands and deployment unit tests; hosted execution pending |
| Documentation | Architecture, security, AI decisions, testing, configuration and deployment/recovery | README links and current contract/inventory |

## Evidence

See [VERIFICATION.md](VERIFICATION.md) for exact counts, coverage and gates, [TEST_INVENTORY.md](TEST_INVENTORY.md) for cases, and [BENCHMARKS.md](BENCHMARKS.md) for measured throughput/latency with scope. Raw logs are local ignored artifacts under `reports/`. [REVIEW.md](REVIEW.md) preserves the historical audit before this migration.

## Deliberate implementation choices

- Shared models/services remain in `app/` rather than duplicating schemas, locks and dependency manifests across the suggested large service tree. Separate runtime Dockerfiles/entry points provide the needed boundaries.
- Next uses production static export behind Nginx. This dashboard needs client rendering/API/SSE; adding a Node production server would add no required behavior. Vite is retained only for Vitest.
- SSE at `/api/events` satisfies the permitted SSE/WebSocket choice; there is no redundant `/ws/tasks` endpoint.
- Queue messages carry one identifier instead of copied user/file/job metadata. PostgreSQL remains authoritative and broker payloads carry less sensitive data. The existing unique `source_key` implements the requested idempotency key.
- Raw transcript is not duplicated in jobs; the normalized task retains user content. Deterministic explicit-field extraction replaces an optional generative LLM. Ambiguous dates/times are preserved as text.
- Maintenance shares bounded dispatcher tasks; transcription remains isolated. Legacy queue names and TIMED_OUT state are retained for safe upgrades. Database enums use checked string constraints.
- New local `.env.example` selects polling. The code fallback remains webhook to preserve existing installations. Polling never silently deletes an operator webhook; follow README switching instructions.
- `WHISPER_MAX_RETRIES` is the bounded total attempt count (default 3); infrastructure recovery separately permits three retries across the original job lifetime. A whole-job deadline can stop provider attempts early. Operational TTL/retry/retention constants are centralized instead of exposing every fixed policy as an environment toggle.
- Exactly one task/final-notification row is enforced. Exactly-once delivery over Telegram cannot be guaranteed across a crash after network acceptance; notifications use durable at-least-once delivery.
- Error responses retain legacy `detail` alongside the new structured envelope for existing clients.

## Remaining release gates

No source was uploaded, credentials changed, paid call made, image pushed or remote deployment performed. Private Telegram text/voice, actual Whisper speech accuracy/latency/cost, HTTPS webhook setup, protected hosted CI/CD, exact-image OS scanning, backup restore and sustained production load still require staging/operator evidence. Dependency lock scans do not certify base-image OS packages. Automated accessibility checks do not replace a screen-reader/manual audit. See [deployment](docs/deployment.md) for release prerequisites.

The subsequent [current audit](AUDIT.md) added database-backed 60/minute bot admission, migration 0004 and focused concurrency/privacy/expiry regressions.

Free development speech is now available through `make up-local-ai`, with `make test-local-ai` verifying actual CPU model inference without a paid API. See the Armenian README quickstart and [architecture diagram](docs/architecture.svg). Default production OpenAI behavior is preserved.
