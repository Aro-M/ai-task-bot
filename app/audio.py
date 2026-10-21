"""Bounded Telegram downloads, local audio checks, and Whisper requests."""

import asyncio
import json
import math
import random
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from redis.asyncio import Redis

from app.config import settings

MIME_TYPES = {
    "audio/ogg",
    "audio/opus",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "application/ogg",
}


class AudioError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_metadata(duration: object, size: object, mime: object) -> None:
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or not settings.min_audio_duration_sec
        <= duration
        <= settings.max_audio_duration_sec
    ):
        raise AudioError("invalid_duration")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 0 < size <= settings.max_audio_file_size_mb * 1024 * 1024
    ):
        raise AudioError("invalid_size")
    if not isinstance(mime, str) or mime not in MIME_TYPES:
        raise AudioError("unsupported_audio")


def telegram_file_path(value: object) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9_/-]+\.[A-Za-z0-9]+", value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise AudioError("invalid_file_path")
    return quote(value, safe="/")


async def download_audio(file_id: str, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    limit = settings.max_audio_file_size_mb * 1024 * 1024
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        for attempt in range(3):
            try:
                response = await client.get(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
                    params={"file_id": file_id},
                )
                response.raise_for_status()
                data = response.json()
                if (
                    not isinstance(data, dict)
                    or not data.get("ok")
                    or not isinstance(data.get("result"), dict)
                ):
                    raise AudioError("download_failed")
                path = telegram_file_path(data["result"].get("file_path"))
                async with client.stream(
                    "GET",
                    f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{path}",
                ) as stream:
                    stream.raise_for_status()
                    length = stream.headers.get("content-length")
                    if length is not None and (
                        not length.isdigit() or int(length) > limit
                    ):
                        raise AudioError("invalid_size")
                    received = 0
                    with destination.open("xb") as output:
                        async for chunk in stream.aiter_bytes():
                            received += len(chunk)
                            if received > limit:
                                raise AudioError("invalid_size")
                            output.write(chunk)
                    if not received:
                        raise AudioError("invalid_size")
                return
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                destination.unlink(missing_ok=True)
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code != 429
                    and exc.response.status_code < 500
                ):
                    raise
                if attempt == 2:
                    raise AudioError("download_unavailable") from None
                await asyncio.sleep(2**attempt + random.uniform(0, 0.25))


async def run_audio_tool(*arguments: str) -> tuple[bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise AudioError("corrupted_audio")
    return stdout, stderr


async def inspect_audio(path: Path) -> float:
    if (
        not path.is_file()
        or not 0 < path.stat().st_size <= settings.max_audio_file_size_mb * 1024 * 1024
    ):
        raise AudioError("invalid_size")
    stdout, _ = await run_audio_tool(
        "ffprobe",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-show_entries",
        "format=duration,format_name:stream=codec_type,codec_name",
        "-of",
        "json",
        str(path),
    )
    try:
        metadata = json.loads(stdout)
        duration = float(metadata["format"]["duration"])
        formats = set(metadata["format"]["format_name"].split(","))
        streams = metadata["streams"]
        if (
            not formats.intersection(
                {"ogg", "mp3", "mov", "mp4", "m4a", "wav", "matroska", "webm"}
            )
            or not streams
            or any(stream["codec_type"] != "audio" for stream in streams)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise AudioError("corrupted_audio") from None
    validate_metadata(duration, path.stat().st_size, "audio/ogg")
    _, stderr = await run_audio_tool(
        "ffmpeg",
        "-nostdin",
        "-v",
        "info",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        str(path),
        "-vn",
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    )
    peak = re.search(rb"max_volume:\s*(-?\d+(?:\.\d+)?|-inf) dB", stderr)
    if not peak or float(peak.group(1)) < -45:
        raise AudioError("no_clear_speech")
    return duration


async def convert_audio(path: Path) -> Path:
    target = path.with_suffix(".wav")
    await run_audio_tool(
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(target),
    )
    return target


async def provider_gate(redis: Any) -> None:
    if await redis.get("ai:circuit:open"):
        raise AudioError("provider_unavailable")
    # A single atomic script prevents an expiry race on newly created counters.
    count = await redis.eval(
        "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
        1,
        "ai:requests",
    )
    if int(count) > settings.global_ai_requests_per_minute:
        raise AudioError("provider_busy")


def whisper_retry_delay(attempt: int) -> float:
    return min(
        settings.whisper_retry_backoff_max,
        settings.whisper_retry_backoff_base * 2**attempt + random.uniform(0, 0.25),
    )


async def transcribe_audio(path: Path) -> tuple[str, str | None]:
    if not settings.openai_api_key:
        raise AudioError("provider_unavailable")
    async with Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=20,
        socket_connect_timeout=2,
        socket_timeout=3,
    ) as redis:
        async with httpx.AsyncClient(
            timeout=min(
                settings.whisper_timeout_sec, settings.transcription_job_timeout_sec
            ),
            follow_redirects=False,
        ) as client:
            for attempt in range(settings.whisper_max_retries):
                await provider_gate(redis)
                metrics_key = f"ai:metrics:{datetime.now(UTC):%Y-%m-%d}"
                await redis.hincrby(metrics_key, "attempts", 1)
                await redis.expire(metrics_key, 7 * 86400)
                started = time.monotonic()
                try:
                    form = {
                        "model": settings.whisper_model,
                        "response_format": "verbose_json",
                    }
                    if settings.whisper_language != "auto":
                        form["language"] = settings.whisper_language
                    with path.open("rb") as audio:
                        response = await client.post(
                            f"{settings.provider_base_url.rstrip('/')}/audio/transcriptions",
                            headers={
                                "Authorization": f"Bearer {settings.openai_api_key}"
                            },
                            data=form,
                            files={"file": ("voice.wav", audio, "audio/wav")},
                        )
                    response.raise_for_status()
                    result = response.json()
                    if not isinstance(result, dict) or not isinstance(
                        result.get("text"), str
                    ):
                        raise AudioError("invalid_transcript")
                    language = result.get("language")
                    if language is not None and (
                        not isinstance(language, str)
                        or language
                        not in {
                            "en",
                            "hy",
                            "english",
                            "armenian",
                            "English",
                            "Armenian",
                        }
                    ):
                        raise AudioError("unsupported_language")
                    segments = result.get("segments", [])
                    if not isinstance(segments, list):
                        raise AudioError("invalid_transcript")
                    for segment in segments:
                        if not isinstance(segment, dict):
                            raise AudioError("invalid_transcript")
                        try:
                            no_speech = float(segment.get("no_speech_prob", 0))
                            confidence = float(segment.get("avg_logprob", 0))
                        except (TypeError, ValueError):
                            raise AudioError("invalid_transcript") from None
                        if (
                            not math.isfinite(no_speech)
                            or not math.isfinite(confidence)
                            or no_speech >= 0.6
                            or confidence < -1
                        ):
                            raise AudioError("no_clear_speech")
                    await redis.delete("ai:circuit:failures")
                    await redis.hincrby(metrics_key, "accepted", 1)
                    return result["text"], language
                except (
                    httpx.TransportError,
                    httpx.HTTPStatusError,
                ) as exc:
                    await redis.hincrby(metrics_key, "http_failures", 1)
                    if (
                        isinstance(exc, httpx.HTTPStatusError)
                        and exc.response.status_code != 429
                        and exc.response.status_code < 500
                    ):
                        raise AudioError("provider_rejected") from None
                    failures = await redis.incr("ai:circuit:failures")
                    await redis.expire("ai:circuit:failures", 60)
                    if failures >= 5:
                        await redis.set("ai:circuit:open", "1", ex=30)
                    if attempt == settings.whisper_max_retries - 1:
                        raise AudioError("provider_unavailable") from None
                    await asyncio.sleep(whisper_retry_delay(attempt))
                finally:
                    await redis.hincrby(
                        metrics_key,
                        "elapsed_ms",
                        round((time.monotonic() - started) * 1000),
                    )
    raise AudioError("provider_unavailable")
