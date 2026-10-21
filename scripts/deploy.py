"""Plan an operator-managed release; --apply is required to change the target host."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def deployment_plan(
    environment: str, tag: str, directory: Path, prefix: str
) -> list[list[str]]:
    if environment not in {"staging", "production"} or not re.fullmatch(
        r"[0-9a-f]{40}", tag
    ):
        raise ValueError("Choose staging/production and a full lowercase commit SHA")
    if not directory.is_absolute() or not (directory / ".env").is_file():
        raise ValueError(
            "Deployment directory must be absolute and contain operator-managed .env"
        )
    if not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+", prefix):
        raise ValueError("Use the private GHCR repository prefix")
    base = [
        "docker",
        "compose",
        "--project-directory",
        str(directory),
        "--env-file",
        str(directory / ".env"),
        "-p",
        f"taskbot-{environment}",
        "-f",
        str(ROOT / "docker-compose.yml"),
        "-f",
        str(ROOT / "docker-compose.release.yml"),
    ]
    return [
        base + args
        for args in [
            [
                "pull",
                "migrate",
                "api",
                "bot",
                "worker",
                "dispatcher",
                "scheduler",
                "frontend",
            ],
            ["up", "-d", "--wait", "postgres", "redis"],
            ["stop", "api", "bot", "worker", "dispatcher", "scheduler"],
            ["run", "--rm", "--no-deps", "migrate"],
            ["up", "-d", "--no-build", "--wait", "--wait-timeout", "180"],
        ]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", choices=["staging", "production"], required=True
    )
    parser.add_argument("--tag", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--image-prefix", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan = deployment_plan(
        args.environment, args.tag, args.directory, args.image_prefix
    )
    if not args.apply:
        print(json.dumps({"apply": False, "commands": plan}, indent=2))
        return
    process_env = {
        **os.environ,
        "TASKBOT_IMAGE_TAG": args.tag,
        "TASKBOT_IMAGE_PREFIX": args.image_prefix,
    }
    for command in plan:
        subprocess.run(command, env=process_env, check=True, timeout=600)
    # The dedicated staging/production runner shares the target host's loopback network.
    with urlopen("http://127.0.0.1:8080/api/health/ready", timeout=10) as response:
        if response.status != 200 or json.load(response).get("status") != "ready":
            raise RuntimeError(
                "Release readiness smoke failed; follow the documented recovery procedure"
            )
    (args.directory / ".release-sha").write_text(args.tag + "\n")
    print("Release readiness smoke passed.")


if __name__ == "__main__":
    main()
