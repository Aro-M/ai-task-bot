"""Whitelist log context so provider payloads and secrets never enter logs."""

import json
import logging
import traceback
from datetime import UTC, datetime
from pathlib import Path


def exception_context(exc: BaseException) -> list[dict[str, str | int]]:
    return [
        {
            "file": Path(frame.filename).name,
            "line": frame.lineno or 0,
            "function": frame.name,
        }
        for frame in traceback.extract_tb(exc.__traceback__)[-8:]
    ]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Only our fixed event names and explicitly approved identifiers are serialized.
        fields = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": (
                record.getMessage() if record.name.startswith("app.") else record.name
            ),
        }
        for key in (
            "request_id",
            "user_id",
            "task_id",
            "job_id",
            "outbox_id",
            "status",
            "error_code",
            "latency_ms",
            "kind",
            "retry_count",
            "stack",
        ):
            if hasattr(record, key):
                fields[key] = getattr(record, key)
        return json.dumps(fields, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("httpx", "httpcore", "telegram", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
