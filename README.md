# Taskroom · AI Task Bot

Տեքստից կամ ձայնային հաղորդագրությունից առաջադրանք ստեղծող Telegram բոտ և կենդանի թարմացվող վեբ վահանակ։

Private technical assessment implementation. Do not publish this repository, its images, or the assessment publicly.

Taskroom captures private Telegram text and voice notes as tasks and delivers changes to a responsive Next.js 16 + TypeScript dashboard through authenticated server-sent events (SSE). Structured task fields can be parsed from English and Armenian text. Armenian speech recognition remains unreliable with the free local models tested. Tasks can be created, edited, searched, filtered, completed, reopened, and deleted. List and board views use the same paginated data.

## Ինչ տեղադրել և ինչ գործարկել

**Առաջարկվող տարբերակ․ Docker Desktop + Docker Compose v2.24 կամ ավելի նոր։** Mac-ում և Windows-ում տեղադրիր [Docker Desktop](https://www.docker.com/products/docker-desktop/), Linux-ում՝ Docker Engine + Compose plugin։ Միացրու Docker-ը։ Այս տարբերակում Python, Node, PostgreSQL կամ Redis առանձին տեղադրել պետք չէ։ Հրամանները գործարկիր նախագծի պանակից։ `make`-ի համար Windows-ում օգտագործիր WSL2, Mac/Linux-ում այն սովորաբար արդեն կա։

```sh
cd /path/to/ai-task-bot
docker --version
docker compose version
```

### 1. Անվճար իրական ձայնային փորձարկում՝ առանց հաշիվների

```sh
make test-local-ai
```

Այս հրամանը՝

1. ներբեռնում է ֆիքսված `whisper.cpp` image-ը, մոտ **141 MiB** `base` բազմալեզու մոդել և հանրային 11-վայրկյանանոց ձայնային նմուշ,
2. ստուգում է մոդելի և նմուշի SHA-256 ամբողջականությունը,
3. ստեղծում է մեկուսացված PostgreSQL/Redis և տեղային ձայնաճանաչման ծառայություն,
4. ձայնը անցկացնում է իրական Celery worker → տեղային մոդել → task → SSE → հաստատում շղթայով,
5. ստուգում է ճանաչված բառերը, եզակի առաջադրանքը և զրոյական provider վճարը, հետո հեռացնում է թեստային կոնտեյներները։

**OpenAI բանալի, վճարային հաշիվ կամ իրական Telegram token պետք չեն։** Միայն Telegram-ի ցանցային կողմն է նմանակվում․ ձայնաճանաչումն իրական է։ Հիմնական հավելվածի `.env`-ը, բազան և տվյալները չեն օգտագործվում։ Առաջին գործարկումն ինտերնետ է պահանջում image/model ներբեռնելու համար։ Մոդելը պահվում է թեստի առանձին Docker volume-ում՝ հաջորդ անգամ կրկին չներբեռնելու համար։ Image-ը ֆիքսված է digest-ով և amd64 է․ Apple Silicon-ում Docker-ը գործարկում է էմուլյացիայով, հետևաբար այն կարող է ավելի դանդաղ լինել։

Թեստը օգտագործում է նաև նախագծի սինթետիկ անգլերեն թելադրանքը և ստուգում բոլոր չորս դաշտերը։ Սա սահմանափակ գործնական ստուգում է, **ոչ ընդհանուր խոսքի կամ հայերենի ճշտության երաշխիք**։ `base` մոդելի արագությունն ու ճշտությունը կախված են համակարգչից և ձայնից։ Արդյունքները՝ `reports/local-ai.xml`, ծառայության log-ը՝ `reports/local-ai-service.log`։ Անձնական ձայնագրություններ չեն ներբեռնվում կամ վերբեռնվում արտաքին AI ծառայություն։

### 2. Ամբողջ հավելվածը՝ անվճար տեղային ձայնաճանաչմամբ

Նոր տեղադրման համար պատճենիր կարգավորումների նմուշը։ **Եթե `.env` արդեն ունես, այն մի վերագրիր։**

```sh
cp .env.example .env
```

`.env`-ում լրացրու՝

| Փոփոխական | Ինչ գրել |
|---|---|
| `ENVIRONMENT` | `development` |
| `POSTGRES_PASSWORD` | Քո տեղային բազայի գաղտնաբառը |
| `DATABASE_URL` | `postgresql+asyncpg://taskbot:ՔՈ_ՆՈՒՅՆ_ԳԱՂՏՆԱԲԱՌԸ@postgres:5432/taskbot` |
| `JWT_SECRET`, `WEBHOOK_SECRET` | Երկու տարբեր երկար պատահական արժեք |
| `TELEGRAM_BOT_TOKEN` | Telegram-ի **@BotFather**-ից ստացած token |
| `TELEGRAM_MODE` | `polling` |
| `OPENAI_API_KEY` | Թող դատարկ մնա․ անվճար տարբերակին պետք չէ |
| `FRONTEND_ORIGIN` | `http://localhost:8080` |

Պատահական գաղտնի արժեք ստեղծելու համար կարող ես երկու անգամ առանձին գործարկել `openssl rand -hex 32`։ Գաղտնաբառում URL-ի հատուկ նշաններ օգտագործելիս դրանք պետք է percent-encode անել `DATABASE_URL`-ում։

```sh
make up-local-ai
docker compose -f docker-compose.yml -f docker-compose.local-ai.yml ps
```

Եթե `make` չունես, հավելվածի գործարկման նույն հրամանն է՝

```sh
docker compose -f docker-compose.yml -f docker-compose.local-ai.yml up --build -d --wait
```

Բացիր [http://localhost:8080](http://localhost:8080)։ Բոտին ուղարկիր `/start`, հետո տեքստ կամ ձայնային հաղորդագրություն։ Վահանակ մուտք գործելու համար բոտին անձնական չաթում ուղարկիր `/login` և մուտքագրիր ստացած 8-նիշ կոդը։ Կոդը գործում է 5 րոպե, վեբ session-ը՝ 15 րոպե։

**Ձայնով բոլոր դաշտերը լրացնելու համար** սկսիր `Title` կամ `Վերնագիր` բառից, դաշտերի միջև փոքր դադար տուր և ասա, օրինակ՝

> Title call Anna. Description discuss the report. Deadline tomorrow at six PM UTC. Priority high.

Կամ հայերեն՝

> Վերնագիր Զանգել Աննային։ Նկարագրություն Քննարկել զեկույցը։ Վերջնաժամկետ վաղը ժամը տասնչորս։ Առաջնահերթություն բարձր։

Հայերեն, անգլերեն և խառը դաշտերը մշակվում են նույն բոտով․ լեզուն ձեռքով փոխել պետք չէ (`WHISPER_LANGUAGE=auto`)։ Հայերեն ճանաչված ձայնի հաստատման մեջ դաշտանուններն ու առաջնահերթությունը հայերեն են։ Սա վահանակի լեզվի ընտրիչ չի ավելացնում։

| Հայերեն դաշտ | English field |
|---|---|
| Վերնագիր | Title |
| Նկարագրություն | Description |
| Վերջնաժամկետ / Ժամկետ / Ամսաթիվ | Deadline / Due date |
| Առաջնահերթություն՝ բարձր / միջին / ցածր | Priority: high / medium / low |

Սա առանձին լրացնում է վերնագիրը, նկարագրությունը, վերջնաժամկետը և առաջնահերթությունը։ Նկարագրությունը, վերջնաժամկետն ու առաջնահերթությունը կամավոր են, հերթականությունը կարող է փոխվել։ Ամսաթիվը՝ `այսօր`/`today`, `վաղը`/`tomorrow`, `2026-12-31` կամ `December 31st, 2026`․ ժամը՝ `ժամը 18:30`, `ժամը տասնութն անց երեսուն`, `six thirty PM` կամ `6:30 PM`։ Հայերեն ամսանուններ և առանց օրվա հատվածի «ժամը վեց» ձևը դեռ չեն մեկնաբանվում։ **Բոտի ժամերը UTC են**․ Երևանի 18:00-ի համար ասա `ժամը տասնչորս` կամ `two PM UTC`։ Նոր թասկը սկսում է `To do` վիճակից։ Հաստատման պատասխանում կտեսնես պահված դաշտերը․ ձայնաճանաչման սխալ բառերը կարող ես ուղղել վահանակում։

Այս հստակ ձևաչափում դաշտանունները բաժանարարներ են․ նկարագրության մեջ դրանք բառացի օգտագործելիս օգտագործիր սովորական տեքստ և խմբագրիր վահանակում։ Չճանաչված կամ կրկնված դաշտի դեպքում թերի թասկ չի ստեղծվում․ բոտը խնդրում է կրկնել կամ ուղարկել տեքստ։ Առանց `Title`/`Վերնագիր` սկզբի սովորական հաղորդագրությունները պահպանում են նախկին վարքագիծը։ Տեղային մոդելի հայերենի ընդհանուր ձայնաճանաչման ճշտությունը չափված չէ․ հայերեն կառուցվածքային թեստերում ճանաչված տեքստը նմանակվում է։

API փաստաթղթերը՝ [http://localhost:8080/api/docs](http://localhost:8080/api/docs)։ Պատրաստության ստուգումը՝ [http://localhost:8080/api/health/ready](http://localhost:8080/api/health/ready)։

`up-local-ai`-ը միացնում է առանձին Compose overlay․ այն worker-ին ուղղում է տեղային մոդելին, սահմանում է մեկ ձայնային worker և provider-ի գնահատված արժեքը՝ 0։ `.env` ֆայլը չի փոխվում։ Նույնիսկ եթե այնտեղ OpenAI բանալի ունես, այս տարբերակը այն փոխարինում է միայն կոնտեյների միջավայրում տեղային անգործուն նշումով։ Ձայնը չի գնում OpenAI։ Telegram-ն աշխատելու համար շարունակում է ինտերնետ պահանջել։

Դադարեցնելու համար՝

```sh
make down-local-ai
```

Տվյալներն ու մոդելը պահպանվում են։ **Սովորական դադարեցման համար մի ավելացրու `-v`․ դա կարող է ջնջել տվյալների volume-ները։** Տեղային AI տարբերակը նախատեսված է development/testing-ի համար․ production կարգավորումները շարունակում են պահանջել պաշտոնական OpenAI ծառայությունը։

### 3. Վճարովի OpenAI տարբերակը՝ ցանկության դեպքում

`.env`-ում ավելացրու քո `OPENAI_API_KEY`-ը, նախ դադարեցրու տեղային տարբերակը, հետո գործարկիր միայն հիմնական Compose-ը՝

```sh
make down-local-ai
docker compose up --build -d --wait
```

Այս տարբերակում ձայնային առաջադրանքները կանչում են վճարովի OpenAI Whisper API։ Սովորական տեքստային առաջադրանքները OpenAI չեն կանչում։

### 4. Արագ ավտոմատ թեստեր՝ առանց AI ներբեռնելու

```sh
make test-integration
```

Սա Docker-ով աշխատեցնում է API/բազա/հերթ/իրադարձությունների թեստերը՝ Telegram/OpenAI պատասխանների նմանակմամբ։ Իրական ձայնաճանաչման համար օգտագործիր առաջին բաժնի `make test-local-ai` հրամանը։

Developer գործիքները պետք են միայն կոդը կոնտեյներներից դուրս աշխատեցնելու համար՝ **Python 3.12, uv, Node.js 22, ffmpeg/ffprobe**։ Mac-ում Homebrew-ի առկայությամբ՝

```sh
brew install uv node@22 ffmpeg
export PATH="$(brew --prefix node@22)/bin:$PATH"
make install
make lint
make test-unit
```

Browser թեստերի համար մեկ անգամ տեղադրիր շարժիչները, հետո գործարկիր՝

```sh
cd frontend
npx playwright install chromium firefox webkit
npm run test:e2e
cd ..
```

Linux-ում browser dependencies-ի համար կիրառիր `npx playwright install --with-deps chromium firefox webkit`։ Իրական մեկուսացված վեբ հոսքերի համար՝ `make test-e2e-live`։ Ավելի մանրամասն՝ [TESTING.md](TESTING.md)։

### Telegram և production կարգավորում

Տեղային `polling`-ը public URL/tunnel չի պահանջում։ Մեկ token-ի համար պահիր մեկ polling instance։ Եթե բոտն արդեն webhook ունի, օգտագործիր առանձին development bot կամ Telegram-ում գիտակցաբար հեռացրու webhook-ը․ հավելվածը այն ինքնուրույն չի փոխում։

Production-ում ընտրիր `TELEGRAM_MODE=webhook`, `ENVIRONMENT=production`, ուժեղ գաղտնիքներ և ճիշտ HTTPS `FRONTEND_ORIGIN`։ HTTPS `/telegram/webhook` հասցեն գրանցիր `secret_token=WEBHOOK_SECRET`-ով․ դա արտաքին կարգավորման գործողություն է, ավտոմատ չի կատարվում։ Token-ը մի գրիր URL-ի կամ shell history-ի մեջ։ Օպերատորի հրամանը՝ `uv run python -m scripts.register_webhook https://YOUR_HOST/telegram/webhook`։ Պահուստների, TLS-ի և տեղակայման մասին՝ [docs/deployment.md](docs/deployment.md)։

## Architecture and invariants

![Համակարգի աշխատանքի սխեմա](docs/architecture.svg)

Խմբագրվող Mermaid տարբերակը՝

```mermaid
flowchart LR
  Telegram -->|polling locally / secret webhook in production| Bot
  Bot -->|text task / voice job + outbox transaction| PostgreSQL
  Dashboard -->|cookie-auth CRUD| API
  API --> PostgreSQL
  Beat -->|notifications queue| Dispatcher
  PostgreSQL -->|outbox| Dispatcher
  Dispatcher -->|job ID via Redis queue| Worker
  Worker -->|bounded download| Telegram
  Worker -->|validated canonical audio| Speech[Local Whisper free / OpenAI API paid]
  Worker -->|task + notification + event transaction| PostgreSQL
  Dispatcher -->|owner channel| Redis
  Dispatcher -->|confirmation| Telegram
  Redis -->|SSE via API| Dashboard
```

The monorepo has separately deployable API, bot, transcription worker, outbox dispatcher, scheduler and frontend services, plus PostgreSQL 16 and Redis 7. The scheduler is a singleton; API/bot/worker replicas can scale independently. The worker consumes `transcription`; the dispatcher consumes `notifications` (legacy `celery`/`effects` queues are drained during upgrades), so occupied transcription slots cannot delay text events or notifications. Dispatch ticks expire after five seconds when consumed; Redis has a 256 MiB no-eviction cap so an offline consumer cannot exhaust host memory. PostgreSQL stores ownership and durable truth. Celery uses JSON-only messages, late acknowledgements, limited prefetch, retry backoff, worker-loss redelivery, and queued-job reconciliation. Redis is the broker, rate limiter, circuit-breaker store and owner-scoped event bus. SQLAlchemy pools API/bot connections; worker connections use NullPool because each Celery invocation creates its own event loop. PostgreSQL connection/query deadlines bound dependency failures, and Nginx refreshes Docker DNS when service containers are replaced.

- A Telegram update primary key and a unique task source key prevent duplicate tasks. A failed database transaction leaves the Telegram update retryable.
- Task/job changes and intended side effects commit together in a database outbox. Redis outages retain accepted work. Dispatch retries failed effects without letting one bad notification block every other user.
- Worker row locks prevent simultaneous processing of one job; owner locks use a consistent order with admission, retry and account deletion. Task creation, final job state, notification and event are one transaction. A short claim transaction commits `PROCESSING` and its event before audio work; a worker crash leaves a stale claim that reconciliation returns to `RETRYING`.
- Redis Pub/Sub is ephemeral. SSE subscribes before its `ready` event, and the dashboard refetches on ready/reconnect to recover missed changes. Events carry IDs rather than private titles. There is no periodic task polling.
- Every CRUD/job endpoint derives the owner from a validated JWT and checks database ownership. Account deletion cascades through tasks, jobs, codes and outbox effects.

## Audio and AI behavior

Metadata limits default to 1–120 seconds and 20 MB; 2 active, 10 hourly and 50 daily transcriptions per user, plus a global 1,000 active-job admission bound. Admissions serialize in PostgreSQL. Real contents are inspected with ffprobe, decoded with ffmpeg, checked for excessive silence/quietness, and converted to mono 16 kHz WAV. Subprocesses use argument arrays, restricted protocols and timeouts. Downloads stream from the fixed Telegram host with a hard size cap and retry transient errors; partial downloads are removed before retry. Audio files live in a private temporary directory on a bounded, memory-backed worker `/tmp` and are deleted on success, failure and cancellation. A hard-killed process can leave temporary data in that memory mount until the worker container stops; container replacement discards it.

The worker calls the selected speech service. Default mode uses OpenAI Whisper; the optional development overlay uses a private local whisper.cpp server and zero provider cost. The configurable model defaults to `whisper-1`, language to `auto` (`en` and `hy` can be selected). Calls have per-request and whole-job deadlines, transient timeout/429/5xx retries with exponential jitter, global request limits and a short circuit breaker. Empty, unsupported-language, low-confidence and common silence-hallucination responses cannot create tasks. Failures generate an actionable Telegram text fallback; retryable failed jobs can be retried through the owner-only API within the shared budget/lifetime. Exhausted provider/download requests are `DEAD_LETTER` with a safe reason and text fallback.

There is no generative task-structuring LLM or tool execution. User input remains data. Starting with Title or Վերնագիր opts into explicit English/Armenian field labels (Title/Վերնագիր, Description/Նկարագրություն, Deadline/Due date/Վերջնաժամկետ, Priority/Առաջնահերթություն); labels and values can be mixed across languages. Those labels are reserved separators in that mode; missing/duplicate values and unsupported explicit dates/priorities are rejected rather than silently dropped. Structured dates accept today/tomorrow, այսօր/վաղը, ISO or English month/day plus an explicit year; unambiguous AM/PM or 24-hour times use UTC. Speech formatting such as 630pm, 6.30pm and six thirty PM is normalized. Unstructured messages preserve the original wording and prior English/Armenian date/priority inference. Text up to 5,000 characters keeps a title of at most 300 characters; long unstructured input is retained in full in the description. Dashboard dates use the browser timezone and store UTC. New tasks start PENDING; status changes use the dashboard. One message creates one task. Evaluation includes field separation, preservation, invalid metadata and prompt-injection text; it does not establish speech accuracy.

Estimated usage cost is tracked per job using actual validated duration and the configurable per-minute price. It is an estimate, not a provider billing reconciliation; failed/retried provider calls may incur additional cost. Job status and latency are owner-visible at `/api/jobs`. Structured logs carry fixed event names, IDs, status, errors and latency without raw audio, transcript, credentials or request bodies. See [TESTING.md](TESTING.md) and [BENCHMARKS.md](BENCHMARKS.md).

## API

| Route | Behavior |
|---|---|
| `POST /api/auth/login` | Consume `{code}` and set HttpOnly SameSite-strict cookie |
| `GET /api/auth/me` | Current owner identity |
| `POST /api/auth/logout` | Clear browser session |
| `DELETE /api/auth/me` | Delete account and all associated private data |
| `GET /api/tasks` | `page`, `page_size` (1–100), `status`, `source`, `search`, `sort`; response includes `total_pages` |
| `POST /api/tasks` | Create `{title, description?, due_date?, priority?}` |
| `GET/PATCH/DELETE /api/tasks/{uuid}` | Owner-only task operations |
| `GET /api/tasks/stats` | Owner totals by status |
| `GET /api/jobs` | Owner job pages, `page` and `page_size` (default 20, maximum 100) |
| `POST /api/jobs/{uuid}/retry` | Retry a failed/timed-out job within quotas |
| `GET /api/events` | Authenticated SSE; task created/updated/deleted and transcription started/completed/failed |
| `GET /api/health` | Compatibility dependency probe: PostgreSQL + Redis |
| `GET /api/health/live` | Process liveness, independent of dependencies |
| `GET /api/health/ready` | DB + Redis + validated settings + both worker-role heartbeats |

Title limit 300, description limit 5,000 characters. Status values: `PENDING`, `IN_PROGRESS`, `COMPLETED`; reopening is allowed. Sources: `DASHBOARD`, `TELEGRAM_TEXT`, `TELEGRAM_VOICE`. Mutating requests require `Origin` matching `FRONTEND_ORIGIN`, including scripts. Invalid credentials return 401, foreign ownership 403, missing IDs 404, invalid payloads 422, exceeded limits 429 and unavailable dependencies 503. Errors use `{error: {code, message, details: {}, request_id}}`; legacy `detail` remains during the client transition. The request ID matches `X-Request-ID`. Generic errors omit database details. `source=telegram_voice` (uppercase also accepted) and `sort=created_at_desc|created_at_asc|updated_at_desc|due_date_asc` are validated.

## Configuration

All variables are listed in `.env.example`; environment files are ignored by Git. `JWT_SECRET` and `WEBHOOK_SECRET` should be generated independently with `secrets.token_urlsafe(48)`. `DATABASE_URL` is asyncpg-format; percent-encode special characters in passwords. Redis must use private infrastructure and appropriate network/TLS controls when managed externally. `TRANSCRIPTION_JOB_TIMEOUT_SEC` bounds processing; `WHISPER_COST_PER_MINUTE` controls estimated cost. Provider base URL overrides are accepted only outside production for fixtures and the explicit free local overlay. No automated tests require or use a real OpenAI key when choosing the paid mode.

## Privacy and retention

Audio is deleted locally immediately after processing. In default mode OpenAI receives only audio and transcription settings; local mode processes it on your machine and makes no OpenAI request. Telegram, and OpenAI when the paid mode is selected, retain data according to their own applicable policies; local deletion does not erase provider-held copies. No raw transcript is retained separately from task title/description. Tasks and minimal Telegram profile data remain until deleted by the user. Expired/exhausted jobs enter failed-job storage and are purged after seven days by the dispatcher; other job metadata remains until account deletion. Jobs expire after 24 hours and share a three-retry budget across infrastructure retries, crash recovery and manual retries. Successful notification payloads are purged immediately; failed effects retry with persisted exponential jitter, at most 12 attempts or 24 hours, then retain content-free dead-letter metadata for seven days. Login codes expire after five minutes and are invalidated on reissue; expired rows can be deleted by the maintenance script. Delivered outbox metadata older than 30 days can also be purged; keep transcription admission records for at least a day to preserve quota accounting. Schedule `docker compose exec -T api python -m scripts.cleanup --apply` daily; omit `--apply` for a dry run. The maintenance scripts are included in the Python runtime image.

## Deployment and operations

Compose runs Alembic migrations in a one-shot service before starting consumers; migration failure prevents rollout. PostgreSQL/Redis have private persistent volumes. Never run `docker compose down -v` on a real deployment unless deleting all data is intended. Backup PostgreSQL before migrations. API/bot/frontend/worker health checks and structured job logs aid diagnostics. `docker compose logs --tail=100 api worker scheduler` shows failures without task contents.

CI runs locked installs, formatting, lint, types, unit coverage gates, isolated database/queue/E2E tests, browser journeys, secret/dependency/static scans and image builds. CD is a manually triggered, protected `release` environment workflow that checks successful CI for the exact main commit and pushes immutable SHA image tags to a **private** GHCR package. Configure reviewers and package visibility before enabling it. No repository, registry publication, external webhook change or remote deployment was performed during implementation. The separate `deploy.yml` workflow supports manually approved staging/production deployment on dedicated self-hosted runners: pull immutable images, stop consumers, migrate, restart and run readiness smoke. [docs/deployment.md](docs/deployment.md) describes operator setup, backup requirements and recovery. To roll back an operator-managed deployment, select the previous image SHA and restore a compatible database backup if a schema rollback is required; automatic rollback and PR previews are bonus features, not implemented.

## Limits and deliberate omissions

Live Telegram/OpenAI credentials and public HTTPS registration require operator configuration; automated success does not certify real Armenian speech accuracy. One recent Armenian Telegram voice check failed with the free local models tested; synthetic English audio tests prove decoding and pipeline behavior, not Armenian speech recognition quality. The noise/quietness heuristics can reject usable quiet speech or accept noise if a provider confidently hallucinates; user review remains necessary. Acknowledgement normally precedes queue processing immediately, but Telegram/network outages cannot guarantee the 1–2 second target.

The worker holds its job transaction during bounded provider work to ensure one task per job. `PROCESSING` is owner-visible after the short claim transaction commits; final task/notification/event changes remain atomic. A crash after Telegram accepts a notification but before outbox acknowledgement can duplicate that notification; it cannot duplicate its task. Pub/Sub events may also be delivered more than once. Logout clears the current browser cookie; a copied JWT remains usable for at most 15 minutes unless the account is deleted. No reminders, tags, paid provider failover, live transcription accuracy benchmark, preview deployments or automated production rollback was added. Mutation checks cover eight selected invariants; failure injection is restricted to disposable QA infrastructure. These are documented limits rather than hidden switches.

Operational metrics: `docker compose exec -T api python -m scripts.metrics` reports aggregate job counts/failure rates, retries, latency, estimated cost, pending/dead-letter effects, Redis queue depth, provider counters and responding worker queues. The snapshot includes API request/error counters with seven-day Redis TTL and retained task counts. No public metrics endpoint or user content is exposed. See [AUDIT.md](AUDIT.md) for reviewed reliability defaults and [TEST_INVENTORY.md](TEST_INVENTORY.md) for named checks.

## Local development outside containers

Keep PostgreSQL/Redis running privately, and override their URLs with your development endpoints (do not point tests at application data). Set `FRONTEND_ORIGIN=http://localhost:3000` and `TELEGRAM_MODE=polling`. Install `uv sync --frozen` and `cd frontend && npm ci`. In separate terminals run the API (`uv run uvicorn app.api:app --reload`), bot (`uv run uvicorn app.bot:app --port 8001`), transcription worker (`uv run celery -A app.worker.celery_app worker -Q transcription -n transcription@%h --concurrency=4`), effect worker (`uv run celery -A app.worker.celery_app worker -Q notifications -n notifications@%h --concurrency=1`), singleton beat (`uv run celery -A app.worker.celery_app beat`), and `cd frontend && npm run dev`. Apply `uv run alembic upgrade head` before starting them. The Next dev server forwards `/api` to localhost:8000; only loopback development origins are allowlisted.

## Source map and design choices

| Location | Owns |
|---|---|
| `app/api.py`, `app/auth.py`, `app/services.py`, `app/schemas.py` | API, identity, task transactions and validated boundaries |
| `app/bot.py` | aiogram 3 polling lifecycle and authenticated webhook ingestion |
| `app/worker.py`, `app/audio.py`, `app/events.py` | Celery lifecycle, safe audio/provider calls, durable effects and SSE payloads |
| `app/models.py`, `migrations/` | Shared relational schema, indexes and reversible migrations |
| `services/api`, `services/bot`, `services/worker` | Separate service Dockerfiles built from the common locked Python image |
| `frontend/src/app`, `frontend/src`, `frontend/scripts` | Next App Router entry, existing accessible UI/data client, build-time CSP hashes |
| `tests/`, `frontend/e2e*`, `.github/workflows/` | Isolated tests, browser journeys and release automation |

The supplied large folder tree is interpreted as clear ownership, not a requirement to duplicate shared models/repositories/lock files. The existing small shared Python package avoids divergent schemas and six layers for one implementation; services remain independently deployable. SSE is the selected allowed real-time transport, so `/ws/tasks` is replaced by `/api/events`. A private static Next export served by Nginx needs no extra Node runtime service; all task data is fetched using authenticated FastAPI calls. CSP includes hashes of exact exported hydration scripts, with no broad inline-script permission. `source_key` is the existing unique idempotency key; queue messages carry only `job_id` and resolve private metadata in PostgreSQL. Separate transcript storage is deliberately omitted to avoid a second copy of private content. `TIMED_OUT` remains for backward compatibility alongside the required job states.

Further details: [architecture](docs/architecture.md), [security](docs/security.md), [AI design](docs/ai-design.md), [testing](docs/testing.md), [deployment](docs/deployment.md), and the current [implementation checklist](IMPLEMENTATION.md). Future work should prioritize consented real-speech evaluation, backup-restore rehearsal and deployment capacity calibration before optional model structuring or reminders.

### Bot admission and current audit

All private Telegram messages and commands share a **60 messages per sliding minute per user** cap. PostgreSQL serializes admission using the existing update-replay ledger, so text ingestion remains durable while Redis is down. The first over-limit update creates one clear cooldown notice; further over-limit updates are acknowledged without creating tasks, voice jobs or repeated notices. Update identity remains retained after account erasure, but its owner association is removed. Migration 0004 adds the nullable owner/timestamp/index; downgrade drops only admission history, preserving replay IDs. Historical receipts have no owner and do not count against users.

[Current audit](AUDIT.md) follows the requested eight-section review format and separates local verification from outstanding live-provider and hosted-release gates.
