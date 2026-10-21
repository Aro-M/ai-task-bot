.PHONY: test-local-ai up-local-ai down-local-ai install test-unit test-integration test-e2e test-e2e-live test-mutations test-security test-containers benchmark lint ci up down
install:
	uv sync --frozen
	cd frontend && npm ci
test-unit:
	uv run pytest tests/unit --cov=app --cov-report=term-missing --cov-report=xml --junitxml=reports/unit.xml
	cd frontend && npm run test:coverage && npm run test:csp
test-integration:
	@test_status=0; \
	docker compose -p taskbot-test -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from tests || test_status=$$?; \
	mkdir -p reports; \
	docker compose -p taskbot-test -f docker-compose.test.yml cp tests:/tmp/reports/. reports/ || true; \
	exit $$test_status
test-e2e:
	cd frontend && npm run test:e2e
test-e2e-live:
	@set -e; trap 'docker compose -p taskbot-qa --env-file tests/fixtures/qa.env -f docker-compose.yml -f docker-compose.qa.yml down -v' EXIT; \
	docker compose -p taskbot-qa --env-file tests/fixtures/qa.env -f docker-compose.yml -f docker-compose.qa.yml up --build -d --wait frontend qa-control; \
	uv run python -m tests.operations; \
	(cd frontend && npm run test:e2e:live)
test-mutations:
	uv run python -m scripts.check_mutations
test-security:
	uv run pip-audit
	uv run bandit -q -r app -lll
	cd frontend && npm audit --audit-level=high
test-containers:
	docker run --rm --entrypoint /bin/hadolint -v "$(CURDIR):/repo:ro" hadolint/hadolint:v2.12.0-alpine /repo/Dockerfile /repo/frontend/Dockerfile /repo/services/api/Dockerfile /repo/services/bot/Dockerfile /repo/services/worker/Dockerfile
	docker run --rm -v "$(CURDIR):/project:ro" -v taskbot-trivy-cache:/root/.cache/trivy aquasec/trivy:0.69.3 fs --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --skip-dirs /project/.venv,/project/frontend/node_modules,/project/frontend/.next,/project/reports --no-progress /project
benchmark:
	uv run python scripts/benchmark.py
lint:
	uv run ruff check app tests scripts
	uv run black --check app tests scripts migrations
	uv run mypy app
	cd frontend && npm run lint && npm run typecheck && npm run format:check
ci: lint test-unit test-integration test-security test-containers test-e2e test-e2e-live test-mutations
	cd frontend && npm run build
	docker build --target runtime -t taskbot-api:local .
	docker build -t taskbot-frontend:local frontend
up:
	docker compose up --build -d
down:
	docker compose down

# Slow opt-in test: downloads a checksum-verified model once; no API charge.
test-local-ai:
	@test_status=0; \
	docker compose -p taskbot-local-ai-test -f docker-compose.test.yml -f docker-compose.local-ai-test.yml up -d --wait local-whisper postgres redis && \
	docker compose -p taskbot-local-ai-test -f docker-compose.test.yml -f docker-compose.local-ai-test.yml run --build --no-deps --name taskbot-local-ai-test-runner tests || test_status=$$?; \
	mkdir -p reports; \
	docker compose -p taskbot-local-ai-test -f docker-compose.test.yml -f docker-compose.local-ai-test.yml logs --no-color local-model local-whisper > reports/local-ai-service.log; \
	docker cp taskbot-local-ai-test-runner:/tmp/reports/. reports/ || true; \
	docker rm taskbot-local-ai-test-runner >/dev/null 2>&1 || true; \
	docker compose -p taskbot-local-ai-test -f docker-compose.test.yml -f docker-compose.local-ai-test.yml down; \
	exit $$test_status

up-local-ai:
	docker compose -f docker-compose.yml -f docker-compose.local-ai.yml up --build -d --wait

down-local-ai:
	docker compose -f docker-compose.yml -f docker-compose.local-ai.yml down
