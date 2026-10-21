# Current implementation contract

Python 3.12/FastAPI, aiogram 3, SQLAlchemy 2/Alembic/PostgreSQL 16, Celery/Redis 7, Next.js 16/React 19/strict TypeScript. Shared Python code stays in `app/`; separately owned runtime entry points/Dockerfiles live under `services/` and `frontend/`. See [architecture](docs/architecture.md) for transactions, locks, delivery guarantees and migrations.

## Boundaries and ownership

- `app/config.py`, `db.py`, `models.py`, `schemas.py`, `services.py`: validated settings, persistence, schemas and task invariants. Service helpers flush; the caller commits. Production migrations own schema creation.
- `app/api.py`, `auth.py`: authenticated tenant context, Origin/CSRF, rate limits, safe errors and SSE. Clients cannot supply an owner identity. Foreign-owner access returns 403; missing task returns 404.
- `app/bot.py`: aiogram transport, polling/webhook ingestion, metadata validation, update identity, user profile updates and durable enqueue. Polling offset advances after successful database commit; use one polling replica.
- `app/worker.py`, `audio.py`, `events.py`: committed job claim, bounded processing/retries, secure temporary audio, outbox and per-owner events. Never transcribe in the bot handler.
- `frontend/src/api.ts`, `types.ts`, `App.tsx`, `TaskDialog.tsx`, `app/`: cookie API client, shared types, accessible dashboard and Next entry points. Static production export uses generated inline hydration script hashes in Nginx CSP.

## Data and API

UUID ownership uses cascading foreign keys; timestamps are UTC. Task states PENDING/IN_PROGRESS/COMPLETED allow all six directed changes and idempotent same-status updates. Sources are DASHBOARD/TELEGRAM_TEXT/TELEGRAM_VOICE; priority LOW/MEDIUM/HIGH. Job states are QUEUED/PROCESSING/COMPLETED/FAILED/RETRYING/DEAD_LETTER/CANCELLED plus retained legacy TIMED_OUT. A unique `Task.source_key=voice:<job UUID>` enforces voice idempotency. No separate raw transcript is retained.

Bot `/login` supplies an eight-digit, five-minute, single-use code hashed at rest. Login issues a 15-minute HttpOnly JWT cookie, Secure in production and SameSite Strict. Mutating requests require the configured trusted Origin. Missing/invalid credentials return 401; Redis limiter failure returns controlled 503.

API includes task CRUD, source/status/search filters, validated stable sorts, `{items,page,page_size,total,total_pages}`, owner statistics at `/api/tasks/stats`, paginated jobs and bounded manual retry. Health/live/ready are distinct; readiness checks DB, Redis and expiring heartbeats for both worker roles. Errors use `{error:{code,message,details,request_id},detail}` with the legacy `detail` retained for existing clients. `/api/events` provides authenticated SSE, including ready/task/transcription events. ID-only events trigger refetch on connect/reconnect; see [README](README.md) for route details.

## Durable work

Celery JSON payloads carry `job_id` only; the worker loads authoritative user/file/time metadata from PostgreSQL. `transcription` and `notifications` queues have independent consumers (4/1 concurrency by default); legacy celery/effects queues are drained during upgrades. The one-second scheduler dispatches bounded outbox/reconciliation/retention work. No unused maintenance queue is provisioned.

The worker commits PROCESSING before long I/O, then locks owner before job. Audio is streamed from the fixed Telegram host, size bounded, decoded/validated with ffmpeg/ffprobe argument arrays and deleted in a finally-managed temporary directory. Whisper retries transient errors with configured timeout/backoff/jitter; the entire job has a 60-second default deadline. Exhausted provider/download errors become DEAD_LETTER; invalid audio/output becomes FAILED. Infrastructure retries share three durable retries and the original 24-hour lifetime. Stale claims recover safely; terminal jobs expire after seven days. Telegram final-notification rows are unique, but ambiguous network delivery remains at least once.

Outbox effects commit with task/job changes, retry with persisted deadlines (including Telegram Retry-After) and terminalize after 12 attempts or 24 hours. Terminal effects drop sensitive payloads and purge after seven days; successful notification payloads are cleared. Exact configuration names/defaults are owned by [`.env.example`](.env.example) and `app/config.py`, avoiding a second stale settings list.

## Verification and operations

[TESTING.md](TESTING.md) defines guarded disposable services and mock boundaries; [VERIFICATION.md](VERIFICATION.md) records current results; [TEST_INVENTORY.md](TEST_INVENTORY.md) lists cases. [Deployment](docs/deployment.md) describes private, approved immutable-image release and rollback prerequisites. No live provider, registry publication or remote deployment is implied by local tests.

Bot admission: `BOT_MESSAGES_PER_MINUTE=60` is a centralized fixed policy in `app/config.py`. The indexed `ProcessedUpdate(user_id,created_at)` ledger counts all private updates in a sliding minute under an owner lock; duplicates do not renew the window. The first excess update creates one cooldown notice. Owner association is nullable and SET NULL on erasure, retaining replay identities.

Optional free development speech reuses the existing provider HTTP contract via docker-compose.local-ai.yml. The overlay substitutes a local-only key/URL, model tiny, zero per-minute provider estimate and one transcription child. Production host restrictions stay intact. `make test-local-ai` exercises actual local inference in isolated test services; ordinary CI skips that additional case.
