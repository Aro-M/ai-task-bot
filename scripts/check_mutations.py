"""Check that selected security/integrity regressions break tests in temporary copies."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    (
        "owner authorization",
        "app/services.py",
        "if task.user_id != user_id:",
        "if False:",
        "tests/unit/test_core.py::test_ownership_denies_foreign_task_and_distinguishes_absent",
    ),
    (
        "OTP expiry",
        "app/auth.py",
        "LoginCode.expires_at > datetime.now(UTC)",
        "LoginCode.expires_at < datetime.now(UTC)",
        "tests/unit/test_auth.py::test_expired_code_rejected",
    ),
    (
        "JWT signature",
        "app/auth.py",
        'options={"require": ["sub", "iat", "exp"]}',
        'options={"require": ["sub", "iat", "exp"], "verify_signature": False}',
        "tests/unit/test_auth.py::test_signed_session_roundtrip_and_tampering",
    ),
    (
        "Telegram deduplication",
        "app/bot.py",
        'update_id = update["update_id"]',
        "update_id = 1",
        "tests/unit/test_pipeline.py::test_distinct_telegram_updates_are_not_dropped",
    ),
    (
        "empty speech rejection",
        "app/services.py",
        "if sum(c.isalpha() for c in text) < 3:",
        "if False:",
        "tests/unit/test_core.py::test_unusable_transcripts_do_not_become_tasks",
    ),
    (
        "CSRF origin",
        "app/api.py",
        'and request.headers.get("origin") != settings.frontend_origin',
        "and False",
        "tests/unit/test_api.py::test_origin_and_unauthenticated_guards",
    ),
    (
        "event privacy",
        "app/events.py",
        '("event", "task_id", "user_id", "job_id")',
        '("event", "task_id", "user_id", "job_id", "text")',
        "tests/unit/test_pipeline.py::test_job_payload_and_events_never_publish_text",
    ),
    (
        "completion timestamp",
        "app/services.py",
        'utcnow() if changes["status"] == TaskStatus.COMPLETED else None',
        "None",
        "tests/unit/test_core.py::test_status_lifecycle_and_reopening_clear_completion",
    ),
]


def main() -> None:
    results = []
    with tempfile.TemporaryDirectory(prefix="taskbot-mutation-") as temporary:
        workspace = Path(temporary)
        for folder in ("app", "tests", "scripts"):
            shutil.copytree(
                ROOT / folder,
                workspace / folder,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        shutil.copy2(ROOT / "pyproject.toml", workspace / "pyproject.toml")
        for name, filename, before, after, test in CASES:
            source = (ROOT / filename).read_text()
            if source.count(before) != 1:
                raise RuntimeError(f"Mutation target drifted: {name}")
            target = workspace / filename
            target.write_text(source.replace(before, after, 1))
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    test,
                    "-q",
                    "--tb=short",
                    "--junitxml=mutation.xml",
                ],
                cwd=workspace,
                env={
                    **os.environ,
                    "PYTHONPATH": str(workspace),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                capture_output=True,
                text=True,
                timeout=30,
            )
            target.write_text(source)
            # Collection/import/infrastructure failures do not prove an assertion caught the regression.
            report_file = workspace / "mutation.xml"
            suite = (
                ET.parse(report_file).getroot().find("testsuite")
                if report_file.exists()
                else None
            )
            killed = (
                result.returncode == 1
                and suite is not None
                and int(suite.get("failures", "0")) > 0
                and int(suite.get("errors", "0")) == 0
            )
            report_file.unlink(missing_ok=True)
            results.append({"mutation": name, "detected": killed})
            if not killed:
                print(result.stdout[-3000:], file=sys.stderr)
                print(result.stderr[-1000:], file=sys.stderr)
    report = {
        "checked": len(results),
        "detected": sum(item["detected"] for item in results),
        "results": results,
    }
    print(json.dumps(report, indent=2))
    if not all(item["detected"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
