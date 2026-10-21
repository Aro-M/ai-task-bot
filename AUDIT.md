# AI Task Bot — current production review

21 October 2026. Scope: current private working tree, application at localhost:8080, disposable taskbot-test/taskbot-qa services, checked-in CI/CD and existing local evidence. No commit, source upload, provider charge, registry publication, remote deployment, webhook registration or credential change was performed.

## 1. Executive Summary

Production audit: **82/100, suitable for private staging with release gates**. The five critical flows are implemented and covered locally: Telegram text → durable task → SSE/dashboard; voice → immediate acknowledgment → Redis/Celery → validated audio → mocked Whisper → task/event/confirmation; dashboard status writes; bounded retry/dead-letter/fallback; and Compose startup. Real Telegram text/voice delivery has since been checked with the local inference mode; paid OpenAI speech quality and protected hosted deployment remain unverified. The score is engineering judgment, not certification.

Strengths: tenant authorization, atomic outbox persistence, unique update/task identities, consistent owner-before-job locks, independent transcription/notification consumers, bounded audio processing, safe error/log output, strict Next.js client types and real browser/service testing. The main new code finding was missing general bot ingress admission. It is fixed with database-backed per-user admission, preserving text ingestion during Redis failure. No Critical vulnerability or reproducible duplicate-task/data-loss defect was established in the inspected scope.

Current evidence totals are in [VERIFICATION.md](VERIFICATION.md); named cases in [TEST_INVENTORY.md](TEST_INVENTORY.md). Local tests are not a hosted CI run or real-speech acceptance test.

English voice-field follow-up: the reproduced whole-transcript-as-title limitation is fixed in the shared extractor. Explicit field labels populate title/description/deadline/priority, reject unsupported metadata before creation, and appear in voice confirmations. Free inference now uses pinned base. Latest proof is 233 unit cases, 20 service cases and two separate opt-in actual-model cases, including all-field dictation. This does not establish general speech accuracy; existing human recordings were not reprocessed. See the final follow-up in VERIFICATION.md for boundaries and timings.

Bilingual follow-up extends that parser to Armenian and mixed field labels/values, with Armenian voice success confirmations and automatic language detection. Current totals: 254 unit cases, 20 service cases, two separate actual-model English regression cases and 17/17 extraction fixtures. Armenian transcription is mocked in the structural tests; actual Armenian ASR quality remains unmeasured. The latest VERIFICATION.md section records this boundary.

| Critical flow | Local result | Boundary |
|---|---|---|
| Telegram text → PostgreSQL → event → dashboard | Passed service/browser coverage | Telegram notifications mocked |
| Voice → acknowledgment → queue → worker → task/event/confirmation | Passed service E2E, actual audio decoding and queue | Whisper/Telegram HTTP mocked; browser SSE tested separately |
| Dashboard status change → database → UI | Passed | All six directed transitions allowed; unknown/null status rejected |
| Worker transient failure/retry/exhaustion | Passed | Provider HTTP retries, durable infrastructure budget, terminal fallback and duplicate protection |
| Compose startup | Passed | Local Docker with private configuration; no production HTTPS/provider validation |

## 2. Issue Report

Severity describes potential impact; evidence gaps are labeled as such and are not presented as reproduced exploits.

| ID | Severity | Area | Issue and impact | Root cause | Recommended fix | Status |
|---|---|---|---|---|---|---|
| ISSUE-001 | Medium | Bot / DB / Security | Text and commands had no shared message-rate bound; an authenticated Telegram user could grow tasks, notifications and login-code churn without the voice/API quotas applying | Admission covered voice/HTTP, not all private bot updates | Serialize owner admission and count indexed replay receipts; cap 60 per sliding minute, single cooldown notice | **Fixed** |
| ISSUE-002 | High | AI / Deployment | Live critical-path evidence is absent; actual Telegram/Whisper behavior, speech quality, quotas and network permissions could block a public launch | Local fixtures deliberately mock provider HTTP; production credentials/TLS are external | Private staging text/voice run with consented labeled audio, real failure/retry and cost checks, HTTPS webhook smoke | **Proposed — release gate** |
| ISSUE-003 | Medium | Worker / Telegram | A confirmation can repeat after a crash between Telegram acceptance and outbox commit; task rows remain unique | Telegram sendMessage has no transactional idempotency handshake with PostgreSQL | Keep durable at-least-once delivery and unique task/notification rows; explicitly accept rare duplicate notices instead of dropping accepted work | **Needs Discussion — guarantee acceptance** |
| ISSUE-004 | Medium | Worker / Audio | SIGKILL bypasses finally; orphan temporary audio may remain in a worker container's tmpfs until replacement, potentially consuming its 128MiB bound after repeated hard kills | OS process termination cannot execute cleanup; no per-container stale-file janitor | Replace the worker container after hard-kill incidents; if repeated in staging, add a tightly scoped stale-file janitor with cutoff beyond the maximum job/tool lifetime and kill-injection tests | **Proposed — operational limitation** |
| ISSUE-005 | Medium | CI/CD / DB | Hosted environment approvals, actual deployment and backup restoration have not been exercised | These require operator-owned GitHub environments, dedicated runners, registry permissions and a separate restore target | Configure required reviewers/private packages; run exact-SHA staging release and restore rehearsal before production | **Proposed — release gate** |
| ISSUE-006 | Low | Containers / CI | Locked application dependencies do not make rebuilt base OS layers byte-identical; exact-image OS CVEs remain unmeasured | Base tags/distro package updates are floating; current Trivy gate scans dependency locks | Scan exact published image digests; pin reviewed base digests with a deliberate security-update process when reproducible releases are required | **Proposed** |
| ISSUE-007 | Low | DB / Operations | Replay receipt storage grows over time; full history intentionally survives account erasure without owner links | Deleting replay identities arbitrarily could permit old update/task reprocessing | Monitor table/index growth; choose a verified Telegram replay watermark/retention policy before partitioning or purging | **Proposed** |

Other review conclusions: no production create_all; migrations 0001–0004 are explicit. Tenant-created/status and status-created job indexes exist. The unique source_key constraint supplies the idempotency index; PostgreSQL scans a tenant-created B-tree backward for descending order, so no redundant DESC index is needed. No N+1 task-list query was found. Redis and PostgreSQL have no published host ports. Python/Nginx runtime processes use non-root users; database images retain their standard initialization behavior. API query inputs are parameterized and literal search metacharacters escaped. No generative/tool-executing LLM exists, so malformed LLM JSON and model-command execution are not applicable.

## 3. Implemented Fixes

### ISSUE-001 — database-backed bot admission

Files: `app/config.py`, `app/bot.py`, `app/models.py`, `migrations/versions/0004_bot_rate_limit.py`, `tests/unit/test_pipeline.py`, `tests/integration/test_system.py`, and linked configuration/testing/security documentation.

Before: distinct text and command updates could always create their effects; only voice and HTTP had explicit admission controls. A regression test against the old implementation failed because an excess text created another task and an excess voice created a job (`reports/audit-rate-limit-red.log`).

After: private, validated updates share a 60-message sliding-minute budget per user. Admission holds an owner NO KEY UPDATE lock and counts indexed ProcessedUpdate receipts, including the current update. The first excess update records one plain cooldown notice; later excess updates are acknowledged without new task/job/notice effects. Different users have separate budgets; retries retain the same receipt and cannot renew the window. This adds no Redis dependency to text ingestion and no new rate-limit service/table.

The nullable owner foreign key uses ON DELETE SET NULL: account erasure removes receipt ownership while retaining replay identities. New timestamps/index support the bounded count. Historical migrated rows have no owner association and do not consume quota. Downgrade preserves update IDs while dropping only the new admission metadata. A private local pre-migration database backup was created before the main additive upgrade; a restore rehearsal was not performed.

Tests: two focused unit cases; one real PostgreSQL concurrency/erasure case; existing migration roundtrip strengthened to retain a replay receipt through downgrade/upgrade. Existing bot, worker, auth and task flows continue passing. No frontend/provider/queue protocol rewrite was necessary.

## 4. Tests Added or Improved

| Test | Type | Assertion contract | Command |
|---|---|---|---|
| test_bot_rate_limit_bounds_all_messages_and_warns_once | Unit/security | Shared text/command/voice cap, one warning, no excess tasks/jobs/voice acknowledgment, user isolation and duplicate rejection | `uv run pytest tests/unit/test_pipeline.py::test_bot_rate_limit_bounds_all_messages_and_warns_once` |
| test_bot_rate_limit_expires_without_redis | Unit/security | Sliding-window expiry permits text again without a Redis client | `uv run pytest tests/unit/test_pipeline.py::test_bot_rate_limit_expires_without_redis` |
| test_bot_admission_is_atomic_and_account_erasure_keeps_replay_guard | Integration/security | Twelve concurrent updates with cap three produce exactly three tasks and one warning; erasure clears owner links and replay remains rejected | `make test-integration` |
| test_outbox_migration_roundtrip_preserves_existing_data | Integration/migration, strengthened | Existing task/event and receipt survive downgrade to 0001 and upgrade to head; discarded admission history cannot resurrect an update | `make test-integration` |

Current ordinary case count: **245 = 199 Python unit + 20 service integration/E2E + 14 React/API + 8 desktop/mobile browser + 3 real-stack browser + 1 Node CSP**. Eight mutation checks and eight operational checks are supplemental. Parameterized examples and browser repetitions count separately. Python app combined line/branch coverage is **91.56%** (92.93% lines, 85.91% branches); frontend lines/branches **95.41% / 90.19%**. These percentages measure instrumented app/components, not provider behavior or every possible failure.

[TEST_INVENTORY.md](TEST_INVENTORY.md) lists the full named suite and commands. Coverage includes ownership/IDOR, JWT expiry/signatures, missing credentials, SQL/XSS/injection payload handling, input sizes/statuses, actual invalid/silent audio, temporary cleanup, provider timeout/429/5xx/network/empty output, circuit opening, retries/dead letters, shared budgets/TTL, outbox replay, polling offset safety, event isolation/reconnect, accessible CRUD and dependency failures. No real speech accuracy or manual accessibility certification is inferred.

## 5. Reliability Configuration

Values below distinguish code/new-install defaults from the preserved operator settings observed in the local running containers. Policy constants remain centralized rather than duplicated as unused environment variables.

| Setting | Final value and meaning |
|---|---|
| Whole job timeout | TRANSCRIPTION_JOB_TIMEOUT_SEC=60 seconds default/effective; asyncio deadline includes I/O/tools/validation |
| Celery soft/hard limit | Job timeout +20/+30 = 80/90 seconds; worker/dispatcher stop grace 90/110 seconds assumes default job timeout |
| Job TTL | JOB_TTL=86400 seconds from original creation, including manual/recovery retries |
| Durable infrastructure retries | MAX_JOB_RETRIES=3 shared retries after initial attempt, also consumed by reconciliation/manual retry |
| Infrastructure backoff | Celery base 2 seconds, max 60, full jitter enabled |
| Whisper requests | WHISPER_MAX_RETRIES=3 **total attempts**, configurable 1–5; whole deadline/circuit may stop earlier |
| Whisper timeout | WHISPER_TIMEOUT_SEC=45 default/effective, bounded by whole-job timeout |
| Whisper backoff | Base 2 seconds, doubles by attempt, 0–0.25 seconds jitter, capped 30 seconds |
| Telegram download | Three transient attempts; 15-second HTTP timeout; 1/2-second exponential waits plus 0–0.25-second jitter |
| Audio tools | Each subprocess has a 15-second timeout; kill/wait on cancellation |
| Telegram client | Send timeout 3 seconds; polling connect session timeout 5, long poll request timeout 30 with server poll 25; client limit 20 |
| Outbox effects | 12 attempts or 24-hour age; persisted exponential jitter 1–60 seconds, Telegram Retry-After honored up to original lifetime |
| Dead-letter retention | 604800 seconds / seven days for terminal jobs/effects; successful tasks are retained |
| Recovery/visibility | Broker visibility and stale-claim window max(300, job timeout ×3) seconds; locked live work skipped |
| Circuit | Five transient provider failures within 60-second counter window opens for 30 seconds; next request resumes after key expiry |
| Transcription concurrency | Four prefork children effective; notifications one independent child; prefetch one, late ack, requeue on lost worker |
| PostgreSQL pool | API/bot each five base + ten overflow; wait 3 seconds, connect 3, command 5; worker NullPool intentionally avoids pools crossing asyncio.run event loops |
| Redis pools | API shared cap 100; publisher/provider clients cap 20 each; Celery broker pool 10 / transport cap 20; heartbeat cap 2 with 1-second timeouts |
| API/login | Authenticated user 120 requests/60 seconds; login five/IP/60 seconds; Redis unavailable → controlled 503 |
| Bot messages | 60 private messages/commands per user/sliding 60 seconds; database-backed and serialized |
| Voice quotas | Concurrent two/user, hourly ten/user, daily default/example 50/user; **existing local operator daily limit 20 is preserved**; active global cap 1000 |
| Provider requests | Code default 60/minute; example and existing runtime 30/minute; each HTTP attempt counts |
| Audio limits | Minimum 1 second; maximum 120 seconds/20MiB default; supported metadata plus actual format/audio-only/silence/decode inspection |
| Worker readiness | Role heartbeats expire after 60 seconds; readiness requires DB, Redis and both roles; configuration validated at import |

Increasing job timeout or audio size/duration requires revisiting Celery grace periods, tmpfs capacity and provider upload limits. Do not treat accepted environment ranges as a production capacity guarantee. Provider/download HTTP 429 responses retry within local backoff/deadline; Whisper Retry-After is not independently honored. The provider circuit and global limiter still bound attempts.

## 6. Benchmark Results

Latest local run: Docker Desktop/Apple Silicon under shared host load; PostgreSQL16/Redis7, actual database/queue/events, mocked provider edges. No stable-runner comparison or production capacity claim.

| Measurement | Result | Scope |
|---|---|---|
| API creations | 100/100, zero errors; 190.54 creations/second | Concurrent burst, in-process HTTP transport plus real DB/Redis/outbox |
| API average / p95 | 494.58 / 501.68 milliseconds | Excludes Nginx/network round trip |
| SSE delivery | 58.78 milliseconds | Real TCP SSE from explicit outbox dispatch; scheduler tick/load adds delay in production |
| Queue throughput | 35.47 jobs/second | 20 synthetic 50ms jobs, actual Redis/Celery, two prefork children |
| Synthetic service / p95 enqueue-to-finish | 51.90 / 530.48 milliseconds | No speech recognition |
| Synthetic outcomes | 16 success, four injected failures | Constructed 80%/20%, not real Whisper reliability |
| Query average / p95 | 0.55 / 0.68 milliseconds | Twenty warm tenant-list queries over a 100-task fixture |
| Runtime worker concurrency | Four transcription / one notification | Configured/observed worker pools, not provider throughput certification |
| Whisper accuracy/success/WER/actual cost | Not measured | Requires authorized real speech corpus and provider |

Reproduce with `make test-integration`; latest records are in `reports/audit-integration.log`. Network benchmark instructions and cleanup limitations are in [BENCHMARKS.md](BENCHMARKS.md). Latency is reported rather than compared against an arbitrary shared-VM threshold.

## 7. Remaining Risks

Before public launch, close ISSUE-002/005/006 with private provider/HTTPS checks, protected hosted CI/CD, exact-image scanning and a backup restoration exercise. This work does not have those external permissions/evidence and did not change remote resources.

Accept/document ISSUE-003's network delivery guarantee. Monitor hard kills/tmpfs and receipt growth (ISSUE-004/007). Current tests prove normal failure/cancellation cleanup and recovery from abandoned claims; they do not prove cleanup after SIGKILL or a real broker disk disaster. PostgreSQL/Redis paused-container tests validate controlled outage behavior, not backup durability after power loss. Runtime worker readiness does not authenticate a live Telegram/OpenAI account.

Other bounded tradeoffs: a stolen session JWT remains valid until its 15-minute expiry unless the account is removed; logout clears the browser cookie. SSE is ephemeral and recovers by refetch, without durable per-browser event history. Deterministic extraction uses UTC and only explicit fields; ambiguous language remains task text. English/Armenian transcription is accepted; unsupported languages fall back to text. Automated axe/layout checks complement manual accessibility review. An in-flight failed polling update can delay the batch until retry; offset safety intentionally favors retained updates over acknowledging failed writes.

## 8. Final Verification Checklist

PASS means local current-source evidence within the stated mock boundary. Pending/N/A is deliberately not a pass.

| Requested item | Status and evidence |
|---|---|
| Text task creation | PASS: bot/PostgreSQL/outbox/SSE and browser remote task coverage |
| Voice task creation | PASS with mocked provider HTTP: actual decode, worker/DB/queue/events/confirmation |
| Immediate voice acknowledgment | PASS: precedes job insert/commit, no download/provider work in handler; metadata/admission checks occur first |
| Whisper only in worker | PASS: call path inspected and service E2E |
| Whisper timeout | PASS: configurable 45s, bounded by 60s whole job |
| Backoff/jitter/transient retries | PASS: HTTP and Celery failure tests; configured attempt limits |
| No duplicate task on retry | PASS: source-key uniqueness, row locks, update identity and concurrent redelivery |
| Dead-letter handling | PASS: provider/download exhaustion and shared infrastructure recovery budget; inspected/retained terminal metadata |
| Job TTL | PASS: 24h original lifetime checked in processing/reconciliation/manual retry |
| Temporary cleanup | PASS on success/failure/cancellation; SIGKILL limitation ISSUE-004 |
| Empty transcript | PASS: no meaningless task, fallback notification |
| Dashboard real time / reconnect | PASS: real SSE delivery/isolation plus browser/reconnect tests |
| Ownership | PASS: derived tenant, API/worker/account erasure tests |
| Invalid transitions | PASS: unknown/null statuses 422; all six directed transitions explicitly valid; same-status update idempotent |
| Hardcoded secrets / .env | PASS: source scan and tracked-file review; .env ignored/untracked, fixtures explicitly disposable |
| Sensitive logs | PASS in inspected app paths: whitelist excludes bodies/secrets and exception text; upstream logging remains operator scope |
| Health / readiness | PASS locally: dependency checks and worker role TTLs; no live provider credential claim |
| Unit tests | PASS: 192 Python +14 React/API +1 CSP |
| Integration tests | PASS: 20 with real PostgreSQL/Redis/Celery/SSE |
| E2E tests | PASS: service journeys plus eight desktop/mobile and three real-stack browser cases |
| Security tests/scans | PASS locally: auth/input/privacy regressions, mutations, dependency audits, Bandit, Hadolint, Trivy lock scan and Gitleaks |
| AI failure tests | PASS with mocks: timeout/429/5xx/network/invalid output/audio, no task on failure, fallback/dead-letter |
| Docker Compose | PASS locally: rebuilt images, additive migration and health/readiness smoke |
| CI pipeline | **PENDING hosted run**: local lint/type/test/security/build/browser commands pass; configured workflow reviewed, not triggered |
| Optional LLM JSON/tool execution | N/A: no generative LLM or tool-executing model in this system |

Operational commands and raw artifact references are maintained in [VERIFICATION.md](VERIFICATION.md) and [TESTING.md](TESTING.md). The normal application and its credentials/volumes remain preserved; disposable QA/test resources are removed after checks.

### Live follow-up: ISSUE-008 (Medium, AI validation) — Fixed

Actual Telegram use exposed acceptance of `[ Inaudible ]` as a task. `app/services.py` now treats standalone inaudible/unintelligible/no-speech markers as unusable output; comparison tolerates outer brackets, punctuation, whitespace and case without altering valid user text. The worker regression failed before the fix, then passed. Four rejection variants, two meaningful-text preservation cases and a worker/no-task/fallback case were added. Images were rebuilt; existing user data was not edited. See the live follow-up in VERIFICATION.md. Baseline external-evidence gaps above now apply to paid OpenAI/public HTTPS/hosted release, while real Telegram delivery/local processing has local evidence. Dashboard UI access was unavailable in this follow-up because browser control is disabled in Work settings.
