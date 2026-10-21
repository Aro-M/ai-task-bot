# Named BuildKit context supplied by Compose from the common Python build.
# hadolint ignore=DL3006
FROM python-base AS runtime
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
