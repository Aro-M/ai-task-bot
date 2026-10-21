"""Failure injection restricted to the disposable taskbot-qa Compose project."""

import json
import os
import secrets
import subprocess
import time
from pathlib import Path

import httpx
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "taskbot-qa",
    "--env-file",
    "tests/fixtures/qa.env",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.qa.yml",
]
BASE = "http://localhost:18080"


def command(*args: str) -> str:
    return subprocess.run(
        args, cwd=ROOT, check=True, capture_output=True, text=True, timeout=40
    ).stdout


def inspect(name: str) -> dict:
    result = json.loads(command("docker", "inspect", name))[0]
    if result["Config"]["Labels"].get("com.docker.compose.project") != "taskbot-qa":
        raise RuntimeError("Refusing to change infrastructure outside taskbot-qa")
    return result


def healthy(client: httpx.Client) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if client.get("/api/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise AssertionError("QA API did not recover")


def main() -> None:
    api = inspect("taskbot-qa-api-1")
    environment = dict(item.split("=", 1) for item in api["Config"]["Env"])
    if not (
        environment.get("ENVIRONMENT") == "test"
        and make_url(environment["DATABASE_URL"]).database == "taskbot_test"
        and environment.get("REDIS_URL", "").endswith("/15")
        and not environment.get("OPENAI_API_KEY")
    ):
        raise RuntimeError(
            "Failure injection requires isolated test DB/Redis and no AI key"
        )
    origin = environment["FRONTEND_ORIGIN"]
    # Compose replacement must preserve the effective origin, including container-browser QA.
    os.environ["TASKBOT_QA_ORIGIN"] = origin
    results = []
    with httpx.Client(base_url=BASE, timeout=12, headers={"Origin": origin}) as client:
        healthy(client)
        fixture = httpx.post("http://localhost:18081/seed", timeout=10).json()
        update_id = secrets.randbelow(900_000_000) + 100_000_000

        def webhook(number: int, title: str) -> httpx.Response:
            return client.post(
                "/telegram/webhook",
                headers={
                    "X-Telegram-Bot-Api-Secret-Token": environment["WEBHOOK_SECRET"],
                },
                json={
                    "update_id": number,
                    "message": {
                        "from": {"id": fixture["telegramId"], "first_name": "QA Owner"},
                        "chat": {"id": fixture["telegramId"], "type": "private"},
                        "text": title,
                    },
                },
            )

        for service in ("postgres", "redis"):
            name = f"taskbot-qa-{service}-1"
            inspect(name)
            command("docker", "pause", name)
            started = time.monotonic()
            try:
                status = client.get("/api/health").status_code
                elapsed = round(time.monotonic() - started, 2)
                assert status == 503 and elapsed < 11
                results.append(
                    {
                        "scenario": f"{service} paused",
                        "status": status,
                        "seconds": elapsed,
                    }
                )
                expected = 503 if service == "postgres" else 200
                response = webhook(update_id, f"Accepted after {service} outage")
                assert response.status_code == expected
                results.append(
                    {
                        "scenario": f"webhook with {service} paused",
                        "status": response.status_code,
                    }
                )
            finally:
                command("docker", "unpause", name)
            healthy(client)
            if service == "postgres":
                assert (
                    webhook(update_id, "Accepted after postgres outage").status_code
                    == 200
                )
                assert (
                    webhook(update_id, "Accepted after postgres outage").status_code
                    == 200
                )
            update_id += 1
            results.append({"scenario": f"{service} recovered", "status": 200})

        assert (
            client.post("/api/auth/login", json={"code": fixture["code"]}).status_code
            == 200
        )
        tasks = client.get("/api/tasks").json()
        assert tasks["total"] == 2
        assert {task["title"] for task in tasks["items"]} == {
            "Accepted after postgres outage",
            "Accepted after redis outage",
        }
        results.append(
            {
                "scenario": "accepted writes retained, failed update retried without duplicate",
                "tasks": 2,
            }
        )
        assert client.delete("/api/auth/me").status_code == 204

        frontend_id = inspect("taskbot-qa-frontend-1")["Id"]
        old_ip = api["NetworkSettings"]["Networks"]["taskbot-qa_default"]["IPAddress"]
        reservation = f"taskbot-qa-ip-reservation-{secrets.token_hex(4)}"
        reservation_created = False
        try:
            command(*COMPOSE, "stop", "api")
            command(*COMPOSE, "rm", "-f", "api")
            command(
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                reservation,
                "--network",
                "taskbot-qa_default",
                "--ip",
                old_ip,
                "redis:7-alpine",
                "sleep",
                "90",
            )
            reservation_created = True
            command(*COMPOSE, "up", "-d", "--no-deps", "--no-build", "api")
            healthy(client)
            new_ip = inspect("taskbot-qa-api-1")["NetworkSettings"]["Networks"][
                "taskbot-qa_default"
            ]["IPAddress"]
            assert new_ip != old_ip
            replaced_env = dict(
                item.split("=", 1)
                for item in inspect("taskbot-qa-api-1")["Config"]["Env"]
            )
            assert replaced_env["FRONTEND_ORIGIN"] == origin
            assert inspect("taskbot-qa-frontend-1")["Id"] == frontend_id
            results.append(
                {
                    "scenario": "API replaced with different IP; frontend unchanged",
                    "status": 200,
                }
            )
        finally:
            if reservation_created:
                subprocess.run(
                    ["docker", "rm", "-f", reservation], capture_output=True, timeout=10
                )
            command(*COMPOSE, "up", "-d", "--no-deps", "--no-build", "api")
    report = {"checks": len(results), "results": results}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/qa-resilience.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
