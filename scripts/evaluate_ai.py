"""Deterministic extraction evaluation; makes no provider requests."""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.services import DomainError, clean_transcript, extract_fields


def evaluate() -> dict[str, int | float]:
    cases = json.loads(
        (
            Path(__file__).resolve().parents[1] / "tests/fixtures/ai_evaluation.json"
        ).read_text()
    )
    passed = false_positive = false_negative = 0
    for case in cases:
        try:
            actual = extract_fields(
                clean_transcript(case["input"]),
                now=datetime(2026, 10, 21, 12, tzinfo=UTC),
            )
        except DomainError:
            passed += bool(case.get("reject"))
            false_negative += not bool(case.get("reject"))
            continue
        if case.get("reject"):
            false_positive += 1
            continue
        due = actual.get("due_date")
        actual = {
            "title": actual["title"],
            "description": actual.get("description"),
            "due_date": due.isoformat() if due else None,
            "priority": actual.get("priority"),
        }
        passed += all(actual[key] == case.get(key) for key in actual)
    report = {
        "cases": len(cases),
        "passed": passed,
        "accuracy": passed / len(cases),
        "false_positives": false_positive,
        "false_negatives": false_negative,
    }
    if passed != len(cases):
        raise AssertionError(report)
    return report


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
