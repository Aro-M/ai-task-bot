FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
# Install current distro security patches; application dependencies use lock files.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 FORWARDED_ALLOW_IPS="*"
USER app
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM base AS test
USER root
RUN uv sync --frozen
COPY tests ./tests
USER app
CMD ["pytest", "tests/integration", "tests/e2e", "-s", "-o", "cache_dir=/tmp/pytest-cache", "--junitxml=/tmp/reports/integration.xml"]

FROM base AS runtime
