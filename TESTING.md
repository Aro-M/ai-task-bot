# Testing strategy

Install from locks with `make install`; developer prerequisites are in [README](README.md#9-ծրագրավորողի-տեղադրում-և-ավտոմատ-ստուգումներ). Use Python 3.12, Node 22, ffmpeg/ffprobe and Docker. Install browser engines once: `cd frontend && npx playwright install chromium firefox webkit`; Linux additionally needs `--with-deps`.

| Command | Scope and boundary |
|---|---|
| `make lint` | Ruff, Black, mypy, ESLint, Prettier and TypeScript |
| `make test-unit` | Python unit/security/audio/parser/deployment tests, backend coverage ≥80%; React/API/timezone tests, frontend coverage thresholds and exact Next inline-script CSP test |
| `uv run python -m scripts.evaluate_ai` | 17 deterministic English/Armenian fallback extraction fixtures; no model request |
| `make test-integration` | Ephemeral PostgreSQL/Redis, real migrations, Celery, API ownership, outbox, concurrency and Telegram-to-task service journeys; external providers mocked |
| `make test-local-ai` | Two opt-in actual local speech inference journeys, real worker/DB/SSE, Telegram HTTP mocked; no paid API |
| `make test-e2e` | Eight desktop/mobile Chromium journeys with intercepted API/EventSource |
| `make test-e2e-live` | Isolated real Nginx/API/DB/Redis stack, failure injection, then Chromium/Firefox/WebKit CRUD/realtime/axe/layout journeys |
| `make test-mutations` | Eight targeted security/integrity mutations must each trigger a normal test assertion failure |
| `make test-security` | pip-audit, high-severity Bandit and npm audit |
| `make test-containers` | Hadolint on five Dockerfiles; Trivy HIGH/CRITICAL lock-file vulnerability scan |
| `make ci` | Combined local checks, frontend production export and Docker builds |

## Isolation

Unit tests always replace the AI key with a fixed test-only value and disable live task parsing. Individual AI parser tests opt into mocked Responses requests. They do not inherit a usable key from the developer's `.env`. HTTP boundary mocks fail on unexpected requests. Real codec tests use ffmpeg against generated or fixture audio.

Integration runs only through `docker-compose.test.yml`: no `.env`, host ports or application volumes. Destructive fixtures require `RUN_INTEGRATION=1`, the exact `taskbot_test` PostgreSQL database and Redis DB 15. PostgreSQL uses tmpfs. Cleanup only that environment with `docker compose -p taskbot-test -f docker-compose.test.yml down -v`.

`make test-local-ai` uses `taskbot-local-ai-test`, a separate verified model cache, two real English recordings and disposable services. The public sample and synthetic field dictation exercise real CPU inference; no Armenian WER is measured. The normal integration run skips these two opt-in cases, then they are run separately. Apple Silicon emulates the digest-pinned amd64 whisper.cpp image.

Live browser QA uses `taskbot-qa`, loopback ports 18080/18081, disposable fixture credentials, temporary databases, no AI key and the deterministic parser. `tests/operations.py` refuses infrastructure outside that project. It pauses PostgreSQL/Redis, checks bounded 503s and retained/retried writes, then replaces API at a different IP while frontend remains running. The QA-only network has an explicit subnet so Docker can reserve the old IP. The normal application is not paused or reset. `make test-e2e-live` removes the QA stack even after a test failure.

## What is exercised

- Authorization/IDOR, signed and expired JWTs, one-time login code expiry/single-use, Origin/CSRF and private SSE payloads.
- Task CRUD, status transitions/reopening, search/source filters, sorting/pagination/stats, UTC storage and Yerevan deadline inputs/displays.
- Durable update identities, duplicate queue delivery, owner-before-job locks, concurrent admissions, outbox retry/backoff, job TTL/shared retry budget, stale recovery and account erasure.
- Actual malformed/silent/unsupported audio, secure path/download bounds, cancellation/temp cleanup, provider timeout/429/5xx/refusal/invalid speech metadata, both speech response contracts and controlled fallback.
- Strict structured task parsing, non-task input, missing/invalid provider fields, explicit timezone/relative-date request context, no tool execution and deterministic extraction.
- Desktop/mobile accessible dialogs, keyboard focus, preserved edits after failure, live arrival/reconnect, list/board layout and axe WCAG 2 A/AA + 2.1 AA checks.

## Evidence and limits

[VERIFICATION.md](VERIFICATION.md) owns current measured outcomes; [TEST_INVENTORY.md](TEST_INVENTORY.md) provides selectors; [BENCHMARKS.md](BENCHMARKS.md) preserves scoped performance measurements. Do not add counts from repeated runs as independent cases.

Backend JUnit/coverage evidence goes to `reports/` and `coverage.xml`; frontend produces coverage and Playwright reports/traces. These generated/private files are ignored and CI uploads its own artifacts. CI additionally scans Git history with Gitleaks and builds deployable images. The workflow is in `.github/workflows/ci.yml`; inspect the run for the exact pushed commit before claiming hosted CI passed.

Mocked speech or Responses tests cannot establish live comprehension, provider model availability, Armenian recognition quality, production cost or all possible failure modes. README's ten longer test messages are manual acceptance examples, not a measured model benchmark. A labeled Armenian/English corpus, production HTTPS/webhook smoke, exact-image OS vulnerability scan, backup restore rehearsal and sustained deployment capacity remain separate release checks. Automated axe/layout checks do not replace manual screen-reader or visual review.

## macOS Firefox launch fallback

If native Firefox cannot start because macOS denies its sandbox extension, that launch failure is not an application assertion failure. Keep the failed trace, then run the same three-engine suite in the version-matched Linux Playwright image. The commands below use only disposable `taskbot-qa` resources and do not install Linux packages into the host's node_modules:

```sh
# Run from the repository root in a POSIX shell.
(
  set -e
  trap 'docker compose -p taskbot-qa --env-file tests/fixtures/qa.env -f docker-compose.yml -f docker-compose.qa.yml down -v' EXIT
  TASKBOT_QA_ORIGIN=http://frontend:8080 docker compose -p taskbot-qa --env-file tests/fixtures/qa.env -f docker-compose.yml -f docker-compose.qa.yml up --build -d --wait frontend qa-control
  uv run python -m tests.operations
  docker run --rm --network taskbot-qa_default --shm-size=1g \
    --mount type=bind,src="$PWD/frontend",dst=/work \
    --mount type=volume,dst=/work/node_modules --workdir /work \
    -e CI=true -e TASKBOT_QA_URL=http://frontend:8080 \
    -e TASKBOT_QA_CONTROL_URL=http://qa-control:8002 \
    mcr.microsoft.com/playwright:v1.58.2-noble \
    sh -c 'npm ci --no-audit --no-fund && npm run test:e2e:live'
)
```

The image tag must match the locked Playwright version. If the QA-only subnet `172.30.254.0/24` conflicts with another Docker network, change only the disposable QA subnet after checking local network allocations; never reconfigure the application's database network to run these tests. CI uses native Linux browsers instead.
