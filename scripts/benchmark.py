"""Measure an isolated API and clean up through its normal rate-limited API."""

import asyncio
import json
import math
import os
import statistics
import time
from typing import Any

import httpx


async def benchmark(client: httpx.AsyncClient, count: int = 100) -> dict[str, Any]:
    latencies: list[float] = []
    created: list[str] = []
    errors: list[int | str] = []
    cleanup_failures = 0
    started = time.perf_counter()

    async def create(index: int) -> None:
        request_started = time.perf_counter()
        try:
            response = await client.post(
                "/api/tasks", json={"title": f"Benchmark {index}"}
            )
            if response.status_code == 201:
                created.append(response.json()["id"])
            else:
                errors.append(response.status_code)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            errors.append("transport_or_response")
        finally:
            latencies.append((time.perf_counter() - request_started) * 1000)

    try:
        # All requests settle before cleanup, including transport failures.
        outcomes = await asyncio.gather(
            *(create(index) for index in range(count)), return_exceptions=True
        )
        errors.extend(
            "unexpected_response"
            for outcome in outcomes
            if isinstance(outcome, BaseException)
        )
        elapsed = time.perf_counter() - started
    finally:
        deadline = time.monotonic() + 180
        for task_id in created:
            removed = False
            for _ in range(3):
                if time.monotonic() >= deadline:
                    break
                try:
                    response = await client.delete(f"/api/tasks/{task_id}")
                    if response.status_code in {204, 404}:
                        removed = True
                        break
                    delay = float(response.headers.get("Retry-After", "1"))
                    if (
                        response.status_code != 429
                        or not math.isfinite(delay)
                        or not 0 <= delay <= 60
                        or time.monotonic() + delay >= deadline
                    ):
                        break
                    await asyncio.sleep(delay)
                except (httpx.HTTPError, ValueError):
                    break
            cleanup_failures += not removed
    ordered = sorted(latencies)
    return {
        "scenario": f"{count} concurrent task creations",
        "created": len(created),
        "errors": errors,
        "average_ms": round(statistics.mean(ordered), 2),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 2),
        "creations_per_second": round(len(created) / elapsed, 2),
        "cleanup_failures": cleanup_failures,
    }


async def main() -> None:
    base = os.environ.get("TASKBOT_BENCH_URL")
    token = os.environ.get("TASKBOT_BENCH_TOKEN")
    if not base or not token:
        raise SystemExit(
            "Set TASKBOT_BENCH_URL and TASKBOT_BENCH_TOKEN for a disposable API; never target production."
        )
    async with httpx.AsyncClient(
        base_url=base, cookies={"session": token}, headers={"Origin": base}, timeout=30
    ) as client:
        result = await benchmark(client)
    print(json.dumps(result, indent=2))
    if result["errors"] or result["cleanup_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
