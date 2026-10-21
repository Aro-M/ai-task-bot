# Named BuildKit context supplied by Compose from the common Python build.
# hadolint ignore=DL3006
FROM python-base AS runtime
CMD ["celery", "-A", "app.worker.celery_app", "worker", "--queues=transcription", "--concurrency=4", "--loglevel=INFO"]
