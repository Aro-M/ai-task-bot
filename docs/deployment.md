# Deployment, updates and recovery

For a first local installation, follow [README](../README.md): create a Telegram bot, fill `.env`, run `docker compose up --build -d --wait`, then use `/login`. Docker Desktop/Engine with Compose 2.24.4+ is required. Local polling needs no public domain or inbound port. Keep `.env` and persistent database volumes private.

## Public server from source

These are operator instructions, not an automatically completed deployment. Use a dedicated Linux server, a domain whose DNS points to it, Docker/Compose and a TLS reverse proxy. Keep PostgreSQL/Redis private; Compose publishes only frontend on loopback `127.0.0.1:8080`. Never expose the development speech server.

1. Clone the private repository on the server. Copy `.env.example` to `.env` only for a new install, replace all placeholders, then `chmod 600 .env`.
2. Use fresh independent production secrets: `JWT_SECRET` and `WEBHOOK_SECRET` must each have at least 32 characters. Set the real Telegram token and OpenAI key. Configure API billing and model access independently.
3. Set `ENVIRONMENT=production`, `TELEGRAM_MODE=webhook`, `FRONTEND_ORIGIN=https://YOUR_DOMAIN`. Leave the database/Redis Docker hostnames from the template; use the same database password in POSTGRES_PASSWORD and DATABASE_URL. Production requires official `https://api.openai.com/v1` and does not accept the free overlay.
4. Run `docker compose up --build -d --wait`, followed by `docker compose ps` and `curl --fail http://localhost:8080/api/health/ready`.
5. Configure a TLS reverse proxy for YOUR_DOMAIN to `127.0.0.1:8080`, including long-lived SSE without response buffering. For example, an installed [Caddy](https://caddyserver.com/docs/install) server can use this Caddyfile (replace the domain):

```caddyfile
tasks.example.com {
    reverse_proxy 127.0.0.1:8080 {
        flush_interval -1
    }
}
```

Caddy needs working DNS and inbound 80/443 for automatic certificate setup. Follow its service installation instructions and validate/reload that configuration. If using Nginx instead, install a valid TLS certificate and disable buffering/short timeouts for `/api/events`. Apply HSTS only after validating HTTPS. Restrict firewall/SSH appropriately for your deployment.

6. Confirm `https://YOUR_DOMAIN/api/health/ready` returns 200, then explicitly register the Telegram webhook:

```sh
docker compose exec -T api python -m scripts.register_webhook https://YOUR_DOMAIN/telegram/webhook
```

The helper reads secrets internally and does not print a token-bearing URL. It preserves pending updates. Do not run a polling replica using this token at the same time. To switch back, follow README's explicit webhook deletion step before enabling polling.

7. Send `/start`, `/login`, a text task and a voice task to the real bot. Verify all stored fields, deadline timezone and private dashboard updates. Check two distinct Telegram accounts cannot access each other's tasks. Confirm real model availability/cost. These are required acceptance checks, not implied by healthy containers.

Use one polling replica if choosing polling; webhook deployments also need reviewed scaling and ingress controls. The common locked Python base is shared by independently configured API/bot/transcription/dispatcher/scheduler roles. The one-shot migration must exit successfully. Runtime workers consume separate queues at default concurrency 4/1. Basic health checks DB/Redis; `/api/health/ready` additionally checks settings and the expiring heartbeats of both worker roles. A running scheduler alone does not certify the whole system.

## Updating an existing installation

Record the current commit or image SHA, back up PostgreSQL, and preserve `.env`. For a clean source checkout, `git pull --ff-only` obtains the reviewed update. If Git reports local changes, review them rather than forcing a reset. Rebuild/recreate with `docker compose up --build -d --wait`, then check readiness and task CRUD/SSE. An `.env` edit requires recreated containers; a simple process restart keeps the old container environment.

Plan a maintenance window for migrations and stop writes/consumers when a schema change requires it. The approved image deployment helper explicitly starts DB/Redis, stops consumers, migrates and then restarts services. Never downgrade while new consumers are running. Changing POSTGRES_PASSWORD in `.env` does not change an already initialized PostgreSQL volume's password.

`docker compose down` preserves named volumes. **Never run `down -v` on a real deployment** unless intentional permanent data loss is the goal. Test targets use separate projects and disposable databases.

## Backup and restore

Take a private custom-format backup before releases. From the application directory, create a restricted backup directory and dump without printing data:

```sh
mkdir -p backups
chmod 700 backups
docker compose exec -T postgres pg_dump -U taskbot -d taskbot -Fc > backups/taskbot-before-release.dump
chmod 600 backups/taskbot-before-release.dump
```

Choose a new filename each time instead of overwriting the last known good copy. `.dump` files are Git-ignored, but still need encrypted, access-controlled storage outside the server. Verify the dump can be read with `pg_restore --list` and rehearse a full restore into a **separate staging PostgreSQL database**. A successful dump command or table listing alone is not proof of restore correctness. Check restored row counts, ownership, migration version and application read/write behavior before relying on the backup.

For an application-only rollback on a compatible schema, restart the previous immutable image SHA and repeat readiness/CRUD/SSE checks. For incompatible schemas, stop consumers/writes and use a reviewed release-compatible Alembic downgrade or restore the corresponding verified backup. Migration 0003 maps extended job states to legacy values on downgrade; 0004 drops admission ownership/history while preserving update replay IDs. These operations can lose detail. Automatic rollback is omitted because image rollback does not reverse changed data.

## GitHub CI and approved image deployments

`.github/workflows/ci.yml` runs locked installs, lint/types/unit/coverage, deterministic evaluations, mutations, PostgreSQL/Redis/Celery journeys, dependency/static/secret scans, Dockerfile/lock-file checks, deployable builds and desktop/mobile/three-engine browser journeys. It uploads artifacts even when a step fails. A push to main starts CI; inspect the result for the exact commit.

Publishing and deployment are separate manual workflows. Before using them configure:

- Private repository and private GHCR packages.
- `release`, `staging`, `production` GitHub Environments with the required reviewers/access rules. An environment name alone does not create an approval gate.
- Dedicated trusted self-hosted Linux runners labeled `taskbot-staging` and `taskbot-production`, one target per host, with Docker/Compose, gh, Python 3.12/uv and registry read access.
- A reviewed absolute `DEPLOY_DIRECTORY`, production `.env` and independent backups on each target. Never run untrusted pull requests on privileged deployment runners.

`cd.yml` manually publishes SHA-tagged images only after a successful exact-commit main CI and release environment approval. `deploy.yml` separately validates a full SHA with successful main-push CI, checks out that release, logs into private GHCR and invokes `scripts.deploy`. The release overlay selects images by prefix/SHA. The script waits for health/readiness and records `.release-sha`; failure does not claim success.

A dry-run plan (still requires the target directory and its `.env`) is:

```sh
uv run python -m scripts.deploy --environment staging --tag FULL_40_CHARACTER_SHA --directory /srv/taskbot-staging --image-prefix ghcr.io/aro-m/ai-task-bot
```

Only `--apply` executes it; the hosted approved workflow supplies that flag. Do not add it until the deployment prerequisites and backup are ready.

## Release evidence still needed

Current local/CI evidence is recorded in [VERIFICATION.md](../VERIFICATION.md). Public readiness additionally needs the deployed HTTPS/webhook smoke, measured Armenian/English real speech acceptance and billing, an up-to-date OS scan of the exact deployable images, an actual backup restore rehearsal and sustained capacity monitoring. Tests of command order cannot certify a remote server, its reviewers, its TLS settings or its backups.
