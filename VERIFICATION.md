# Current local verification · 21 October 2026

| Check | Result |
|---|---|
| Python unit/security/audio/AI/deployment tests | 254 passed |
| PostgreSQL/Redis/Celery/SSE integration and service E2E | 20 passed |
| React component/API tests | 14 passed |
| Desktop/mobile Playwright journeys | 8 passed |
| Real-stack Linux Chromium/Firefox/WebKit journeys | 3 passed against final rebuilt images |
| Exact Next inline-script CSP test | 1 passed |
| Python unit combined line/branch coverage | 92.04%, required 80%; lines 93.30%, branches 87.28% |
| Frontend line / branch coverage | 95.41% / 90.19% |
| Ruff, Black, mypy, ESLint, Prettier, TypeScript | Passed |
| Python/npm dependency audits | No known vulnerabilities reported |
| High-severity Bandit | Passed |
| Hadolint | All five Dockerfiles passed |
| Trivy dependency lock scan | No HIGH/CRITICAL findings; base-image OS packages not scanned |
| Current-source Gitleaks, including authored untracked files | Passed, no leaks found in current files (offline) |
| PostgreSQL migration upgrade/downgrade/schema drift | Passed with existing fixture data |
| Production Next export + Python/service image builds | Passed |
| Compose startup and readiness | API, bot, worker, dispatcher, frontend, PostgreSQL and Redis healthy; scheduler running |
| Final HTTP/Nginx smoke | Dashboard/basic health/live/ready 200; unauthenticated tasks 401 |
| Actual Next hydration CSP | Three exact inline hashes present; script-src has no unsafe-inline |
| Runtime worker isolation | transcription + legacy celery; notifications + legacy effects; concurrency defaults 4/1 |
| Maintenance script | Dry-run succeeded, no data changes |
| Deterministic AI extraction fixture | 17/17 English/Armenian/mixed examples, including descriptions; no provider requests |
| Targeted mutation checks | 8/8 detected |
| Disposable dependency/replacement checks | 8 passed |
| Automated accessibility/layout | No axe violations on tested pages; 320–1440 px bounds checked |

**300 passing ordinary automated cases**, plus eight mutation checks, eight operational checks and the gates above. Counts include parameterization and repeated browser engines/devices; they are not independent product flows. [TEST_INVENTORY.md](TEST_INVENTORY.md) lists cases. [IMPLEMENTATION.md](IMPLEMENTATION.md) maps requirements/choices; [BENCHMARKS.md](BENCHMARKS.md) records measurements. [AUDIT.md](AUDIT.md) contains the current eight-section review. Historical [REVIEW.md](REVIEW.md) is explicitly a pre-migration snapshot.

Evidence is retained locally in ignored `reports/unit.xml`, `reports/integration.xml`, `reports/audit-unit.log`, `reports/audit-integration.log`, `reports/audit-unit.log`, `reports/audit-browser.log`, `reports/audit-live-browser.log`, `reports/audit-runtime-smoke.json`, coverage and browser output folders. Tests used actual DB/Redis/Celery/audio decoding/SSE and Docker Nginx, while Telegram/OpenAI HTTP edges were mocked. Browser QA never intercepts the actual API or SSE; only its outbound Telegram notifications are stubbed.

Not verified: paid OpenAI speech quality/latency/cost and general Armenian accuracy, public HTTPS webhook, hosted protected GitHub Actions, registry push/remote deployment, exact-image OS scanning, backup restore, sustained production load or manual screen-reader review. No secrets changed, source uploaded or paid call made. The deploy workflow/script is locally tested tooling, not evidence of a completed deployment. Temporary test/QA resources are removed separately; main credentials and data volumes are preserved.

Current audit: [AUDIT.md](AUDIT.md). Added database-backed bot admission with migration 0004, two unit cases, one concurrent PostgreSQL/erasure case and stronger migration roundtrip assertions. A private, ignored pre-migration backup was created before upgrading the main local stack; restore was not rehearsed. Main daily voice quota remains its operator-selected 20, while new-install defaults/examples use 50.

## Free local speech verification

Added optional development-only whisper.cpp Compose mode, Armenian install/run instructions, a standalone SVG architecture diagram and generated/cache/recording/backup ignore rules. **One additional opt-in real-speech E2E passed**: actual 11-second public sample → real Redis/Celery → local tiny inference → PostgreSQL task → authenticated SSE → confirmation, with duplicate processing checked and estimated provider cost zero. Telegram is mocked; no OpenAI request/key/account is used. Measured pipeline 7.36 seconds, test run 13.74 seconds; no general accuracy/performance claim. Raw results: `reports/local-ai.xml`, `reports/local-ai-real-test.log`, `reports/local-ai-service.log`. The ordinary 245-case suite remains separate; this optional case is skipped there.

Post-addition checks: 95 pipeline unit cases passed; 20 ordinary service cases passed with the opt-in case skipped; lint/types/format and offline current-source Gitleaks passed. The SVG was rendered/visually inspected and README links/ignore exceptions checked. Main application rebuilt and all eight services were running/healthy with readiness 200 after transient shared-VM health delays. No .env or main volumes changed.

## Live Telegram follow-up and workspace cleanup

The configured real bot was tested through Telegram Desktop and the running polling service. One explicit TEST text message received its actual Telegram confirmation, created exactly one TELEGRAM_TEXT task and produced the observed real Redis task.created event. Actual voice messages were downloaded from Telegram, processed by the private local model and linked to one task each; a no_clear_speech failure produced a visible fallback and no task. No pending outbox effects or leftover temporary audio directories were found at inspection. No OpenAI call/charge occurred.

The live review caught an unusable `[ Inaudible ]` transcript being accepted. A regression first failed against the old worker; the shared transcript guard now rejects standalone inaudible/unintelligible/no-speech markers, including bracket/case/space variants, while preserving meaningful text containing those words. Seven regression cases were added (199 unit tests now pass); 20 service cases also pass, with the opt-in CPU speech case skipped there. The corrected image is deployed locally. Existing user tasks were retained.

Only untracked, ignored and regenerable artifacts were removed: Python/tool caches, host Next export/build output, duplicate browser exports and downloaded inspection files. Approximately 108 MiB freed; deletion manifest is `reports/cleanup-manifest.json`. Source, tests, dependency installs/locks, .env, Docker data/model volumes, the private migration backup and current evidence remain intact. Frontend typecheck still passes after cache removal. Browser UI access is disabled in Work settings, so this follow-up verifies actual Telegram/Desktop, database/Redis and runtime health rather than claiming a new dashboard browser observation.

## English voice field completion follow-up

The reported inability to fill separate fields was reproduced: the old extractor stored the whole dictation as a title. Explicit Title/Description/Deadline (or Due date)/Priority now fills the four creation fields. Invalid/repeated fields fail without a partial task; description words do not silently override explicit metadata. Spoken clock forms and English dates with a year are covered. Plain messages keep their previous behavior. Voice confirmation includes metadata and a bounded description preview; parser failures explain how to retry. README and /help show the spoken format. UTC semantics and PENDING creation status are explicit.

The free overlay now uses checksum-pinned multilingual base instead of tiny, retaining the 2-CPU/1-GiB cap and existing job deadlines. Synthetic samples still exposed word errors, so this is not a general accuracy claim. No private recording or transcript was added to fixtures. The new WAV is locally synthesized English speech, documented in `docs/ai-design.md`.

Latest checks: **233 unit cases passed**, 91.92% combined line/branch coverage; **20 integration/service E2E passed**, two opt-in model cases skipped there; **both real local-model cases passed separately**. Public-speech pipeline took 15.65 seconds; field-dictation pipeline took 14.57 seconds. The latter asserted every stored field, unique task/event, owner SSE and metadata confirmation. Telegram HTTP is mocked in those two cases; inference, decoding, queue, DB and SSE are real. The extraction evaluator checks descriptions as well and passes 13/13 cases; its regression detects a dropped description. Ruff, Black, mypy and whitespace checks passed. No frontend code changed; earlier browser/frontend checks were not repeated for this parser fix.

The main local stack was rebuilt successfully. The live worker's four-field extraction, local base endpoint/model and zero provider estimate were verified; API/bot/worker/dispatcher/frontend/database/cache/local-model-service are healthy and readiness returns 200. Main .env, task/database volumes and credentials were preserved. Disposable test DB/Redis containers and volumes were removed; local model caches remain for reuse. No new human voice recording through Telegram was validated after this fix, and accent/noise/long-audio quality remains unmeasured. Evidence: `reports/voice-fields-unit.log`, `reports/integration.xml`, `reports/local-ai.xml`, `reports/voice-fields-local-e2e.log`, `reports/voice-fields-rollout.log`, and the RED reproducer logs.

## Armenian and English dictation follow-up

The same parser now accepts Armenian labels and definite forms, Armenian punctuation, mixed English/Armenian labels and priority values, and explicit Armenian 24-hour time words. Duplicate aliases across languages and invalid/ambiguous metadata still fail before creation. Description text does not imply unrelated metadata. Recognized Armenian voice receives Armenian success/metadata labels; /help and README include both spoken formats. The dashboard interface and API schema are unchanged. Language detection stays automatic and free local base inference remains selected; credentials/data are preserved.

Latest results: **254 unit tests passed** (92.04% combined coverage), **20 service integration/E2E passed**, and **both actual-model English regression cases passed separately**. The evaluator passes 17/17 cases, including Armenian and mixed-language fixtures; Ruff, Black, mypy and whitespace checks passed. Armenian ingestion/worker tests mock the transcription edge and assert stored fields/confirmation. No paid call or private recording upload occurred. Evidence: `reports/armenian-fields-red.log`, `reports/armenian-confirmation-red.log`, `reports/armenian-fields-unit.log`, `reports/armenian-fields-integration.log`, `reports/armenian-fields-local-e2e.log` and `reports/armenian-fields-rollout.log`. Frontend tests were not repeated for these backend-only changes.

## Follow-up: real Armenian speech check

On 2026-10-21, a user-provided Armenian Telegram voice recording was checked locally against the multilingual base, small, medium and turbo Whisper models, an Armenian-fine-tuned small model, and an independent Transformers/MPS run. None recovered the expected structured fields. The job was not retried or converted into a task during this diagnosis, and the audio and transcript are not stored in the repository. Deterministic parsing of Armenian text passes its fixtures; real Armenian speech recognition remains unresolved. No paid provider call was made.
