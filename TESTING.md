# Testing strategy

Install with `make install`. Every CI install uses `uv.lock` or `frontend/package-lock.json`.

| Command | Scope |
|---|---|
| `make test-local-ai` | Opt-in real local CPU speech recognition through Redis/Celery/PostgreSQL/SSE; Telegram mocked, no paid API |
| `make test-unit` | Python unit/security/AI tests, branch coverage ≥80%; React component/API and exact Next hydration CSP tests |
| `make test-integration` | Dedicated ephemeral PostgreSQL and Redis; real migrations, API ownership, outbox, concurrent ingestion/worker locks, queue and SSE journeys |
| `make test-e2e` | Chromium desktop and mobile browser journeys |
| `make test-e2e-live` | Real isolated Docker stack, dependency pauses/API replacement, then Chromium/Firefox/WebKit journeys and axe checks |
| `make test-mutations` | Eight targeted mutations in temporary source copies; every mutation must trigger a test failure |
| `make test-containers` | Hadolint on all five Dockerfiles; Trivy HIGH/CRITICAL dependency lock scan |
| `make test-security` | pip-audit, high-severity Bandit and npm audit |
| `make benchmark` | 100 concurrent task creations against an explicitly selected isolated API |
| `make lint` | Ruff, Black, mypy, ESLint, Prettier, TypeScript |
| `make ci` | Local combined checks; see workflow for secret scan and Docker/browser builds |

`make test-integration` starts only `docker-compose.test.yml`, never `.env` or production infrastructure. Fixtures refuse destructive resets unless `RUN_INTEGRATION=1`, the PostgreSQL database is exactly `taskbot_test`, and Redis DB is 15. PostgreSQL storage uses tmpfs and no test ports are exposed. Reset test containers with `docker compose -p taskbot-test -f docker-compose.test.yml down -v`.

Unit tests use SQLite with real foreign-key enforcement and mock Redis/external HTTP; they verify normalization, UTC, schemas, due-date/priority extraction, transcript refusals, prompt-injection preservation, status transitions/reopening, JWT signature/expiry, OTP expiry/collisions/single-use, CSRF, owner authorization, error privacy, quota admission, outbox retries and JSON payloads. Audio tests include actual ffmpeg corruption/silence/format checks. Provider tests use respx (HTTPX/Whisper) and aioresponses (aiogram/aiohttp) to return timeout, 429, outage, malformed/empty text, unsupported language and low-confidence segments without calling OpenAI. No arbitrary model output can execute an administrative operation.

Integration uses a real Celery worker thread and separate prefork processes connected through Redis and real PostgreSQL transactions. Only Telegram/OpenAI network edges are mocked. The voice E2E travels through acknowledgement, durable enqueue, Celery, Telegram download, actual audio conversion, mocked Whisper, task persistence, owner SSE, confirmation, CRUD, deletion and foreign-owner refusal. Redelivered updates/queue messages must create one task. A live HTTP SSE stream checks delivery and isolation. Failure cases prove retained outbox effects and controlled 503s.

Browser tests run the Next.js dashboard with intercepted API calls and a synthetic EventSource so interaction/accessibility behavior is deterministic. They cover login, creation, editing, status changes, deletion cancellation/confirmation, remote task arrivals, reconnect recovery, filters, preserved drafts after service failure, keyboard focus and 375-pixel layout/dialog bounds. These complement the real-service E2E; neither suite alone claims a live Telegram-to-browser provider test.

The separate live suite (`frontend/e2e-live`) uses actual Nginx, API authentication, PostgreSQL, Redis SSE and Telegram webhook ingestion, without intercepting API or EventSource. It runs against `taskbot-qa` on loopback ports 18080/18081; all credentials are disposable fixtures, PostgreSQL/Redis use temporary memory storage, and the fixture control server refuses non-test database settings. Only outbound Telegram notifications are stubbed. That server lives in `tests/` and is absent from production runtime images. No transcription/provider requests occur in browser QA; the service E2E covers that pipeline with mocked provider edges.

Install browser engines once using the locked Playwright package: `cd frontend && npx playwright install chromium firefox webkit` (use `--with-deps` on Linux). `make test-e2e-live` starts the disposable stack, runs `tests.operations`, exercises all three browser engines, and removes the QA containers afterward. Failure injection checks paused PostgreSQL/Redis, bounded 503s, retained writes, safe redelivery, and replacement of API with a deliberately different IP while frontend remains running. It refuses other Compose projects and any environment containing a live AI key. It never pauses or resets the normal local application.

Live accessibility scans cover login, task dialog, list and board with WCAG 2 A/AA and 2.1 AA axe rules. Browser checks also assert layout bounds at 320, 375, 768 and 1440 pixels. There is no committed visual baseline, so screenshot comparison remains inconclusive; layout bounds and interaction assertions are the enforceable checks. Automated axe checks are not a full accessibility certification or a manual screen-reader test. Native Firefox failed to launch in the local macOS sandbox; all three engines were subsequently verified in the pinned Linux Playwright image. CI installs native Linux engines.

The mutation script checks ownership, OTP expiry, JWT signature, update identity, empty speech rejection, CSRF, event privacy and completion timestamps. It mutates only temporary copies, requires a normal pytest test failure rather than collection/setup errors, and fails if a target changed or a mutation survives. This is a selected regression check, not a whole-codebase mutation score.

Backend XML coverage and JUnit reports live in `coverage.xml` and `reports/`. Frontend coverage comes from `npm run test:coverage`; Playwright saves HTML reports and failure traces. CI uploads these artifacts. Both backend and frontend have enforceable thresholds. Extraction evaluation fixtures live in `tests/fixtures/ai_evaluation.json`; run `uv run python -m scripts.evaluate_ai`. Tests do not fetch live private user recordings. No real-speech WER is reported without a consented, labeled speech corpus.

See [BENCHMARKS.md](BENCHMARKS.md) for measured conditions and limits. CI performance thresholds should be calibrated on a stable runner before enforcing latency comparisons; this implementation checks success/count integrity and reports latency instead of inventing a portable p95 target.

The queue lifecycle suite also checks a shared three-retry budget (in addition to bounded attempts inside each provider request), 24-hour expiry before audio work and during reconciliation, dead-letter job/effect seven-day retention, persisted effect backoff, global cross-user admission serialization, migration roundtrip preservation, and content-free aggregate/provider counters. `scripts/benchmark.py` cleanup respects the live API limiter and reports leftovers; its transport/malformed-response/429 paths are mocked without a real 60-second sleep. Named cases with types, purposes and runnable selectors are in [TEST_INVENTORY.md](TEST_INVENTORY.md).

The current build adds committed PROCESSING visibility, RETRYING/DEAD_LETTER and abandoned-claim recovery, aiogram polling offset/cleanup, Telegram Retry-After, per-role expiring readiness heartbeats, profile timestamp/state migration, source/sort/stats/pagination and structured error correlation. Deployment tests verify dry-run purity, validated command order and smoke failure handling without remote changes. Node tests hash exact Next inline scripts; the production browser suite proves hydration under the generated CSP. The test-only aioresponses adapter accommodates aiohttp 3.14 stream-writer metadata. Vite remains a Vitest dependency only; the application runtime/build is Next.js.

Bot admission tests use a small patched cap to verify task/command/voice boundaries, one cooldown notice, tenant isolation, replay identity and sliding-window expiry without Redis. The real PostgreSQL test sends twelve concurrent updates against a cap of three, then erases the account and replays an update; only three tasks may be created, owner links must be cleared and replay must remain rejected. The migration roundtrip preserves update IDs while deliberately dropping admission association on downgrade.

## Real speech without API charges

`make test-local-ai` downloads a digest-pinned whisper.cpp image and SHA-256-verified tiny model/public sample once. It starts only `taskbot-local-ai-test`, runs `test_local_speech_voice_queue_task_sse_and_confirmation`, copies `reports/local-ai.xml`, and tears down its containers. Model cache volume is retained for reuse; test DB uses tmpfs. No .env or real provider/Telegram credential is read. The test passes through the local HTTP ASR endpoint (not a canned transcript), asserts expected recognized words, unique task creation/redelivery safety, zero provider estimate, owner SSE and final confirmation. respx fails on an unexpected external host. The ordinary integration run reports this one opt-in test skipped; `RUN_LOCAL_AI=1` alone is not sufficient—use the isolated Compose target.

The first run may take minutes to download the image/model; later runs reuse the verified cache. Apple Silicon uses Docker amd64 emulation for this pinned image. The successful local pipeline measurement was 7.36 seconds for 11-second English speech; startup and model download are excluded, and Armenian accuracy is not established. Unit/fault/browser suites keep their existing mocked provider boundary.
