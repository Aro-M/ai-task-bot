# Testing

[TESTING.md](../TESTING.md) owns the complete strategy, isolated database/queue rules and mock boundaries. [TEST_INVENTORY.md](../TEST_INVENTORY.md) lists named tests; [IMPLEMENTATION.md](../IMPLEMENTATION.md) records the current build verification. Install from locks (`uv sync --frozen`, `npm ci`).

Run `make lint test-unit test-integration test-security test-containers test-mutations test-e2e`. Real Docker-backed browser flows use `make test-e2e-live` on Linux; Chromium/Firefox/WebKit require `npx playwright install --with-deps`. No real Telegram/OpenAI key is needed. PostgreSQL/Redis destructive fixtures refuse any database except taskbot_test/Redis DB15. QA dependency pauses/container replacement are guarded to taskbot-qa; never target application volumes. External HTTP is mocked, actual decoding/queue/transactions/SSE are real.

Added contracts include Next hydration/CSP, structured error correlation, source/sort/total_pages/stats, worker readiness heartbeats, polling offset acknowledgment/lifespan cleanup, provider/configured backoff/dead-letter states, abandoned PROCESSING recovery, Telegram Retry-After, migration roundtrip and deployment dry-run/scoped command sequencing. aiogram uses aiohttp mocks; a local test-only adapter supplies aiohttp 3.14’s stream-writer argument until aioresponses supports it. No production dependency is downgraded for mocks.

Current audit adds bot message/command/voice admission bounds, single cooldown notice, per-user isolation, expiry without Redis, real PostgreSQL concurrent admission, account-erasure replay preservation and migration receipt roundtrip. The rate-limit regression failed against the old implementation before the fix.

For real free speech recognition, run `make test-local-ai`: separate Docker services, cached verified tiny model, public sample, real worker/database/SSE and mocked Telegram only. The opt-in test is skipped in ordinary CI; artifacts go to reports/local-ai.xml.
