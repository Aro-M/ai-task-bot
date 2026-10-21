# Named BuildKit context supplied by Compose from the common Python build.
# hadolint ignore=DL3006
FROM python-base AS runtime
CMD ["uvicorn", "app.bot:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
