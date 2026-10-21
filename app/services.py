"""Task mutations and their events share the caller's database transaction."""

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outbox, Priority, Task, TaskSource, TaskStatus, utcnow
from app.schemas import TaskCreate, TaskPatch, normalize_text

__all__ = [
    "DomainError",
    "Forbidden",
    "NotFound",
    "clean_transcript",
    "create_task",
    "delete_task",
    "extract_fields",
    "normalize_text",
    "owned_task",
    "update_task",
]


class DomainError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class NotFound(DomainError):
    def __init__(self, message: str = "Task not found"):
        super().__init__(message, 404)


class Forbidden(DomainError):
    def __init__(self, message: str = "Access denied"):
        super().__init__(message, 403)


async def owned_task(session: AsyncSession, user_id: str, task_id: str) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise NotFound()
    if task.user_id != user_id:
        raise Forbidden()
    return task


async def record_event(session: AsyncSession, task: Task, event: str) -> None:
    session.add(
        Outbox(
            user_id=task.user_id,
            kind="event",
            payload={"event": event, "task_id": task.id, "user_id": task.user_id},
        )
    )
    await session.flush()


async def create_task(
    session: AsyncSession,
    user_id: str,
    data: TaskCreate,
    source: TaskSource | str = TaskSource.DASHBOARD,
    source_key: str | None = None,
) -> Task:
    task = Task(
        user_id=user_id,
        source=TaskSource(source),
        source_key=source_key,
        **data.model_dump(),
    )
    session.add(task)
    await session.flush()
    await record_event(session, task, "task.created")
    logging.getLogger(__name__).info(
        "task.created",
        extra={"user_id": user_id, "task_id": task.id, "status": task.status},
    )
    return task


async def update_task(session: AsyncSession, task: Task, data: TaskPatch) -> Task:
    changes = data.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] != task.status:
        task.completed_at = (
            utcnow() if changes["status"] == TaskStatus.COMPLETED else None
        )
    for field, value in changes.items():
        setattr(task, field, value)
    task.updated_at = utcnow()
    await session.flush()
    await record_event(session, task, "task.updated")
    return task


async def delete_task(session: AsyncSession, task: Task) -> None:
    await record_event(session, task, "task.deleted")
    await session.delete(task)
    await session.flush()


def clean_transcript(text: str) -> str:
    text = normalize_text(text)
    if sum(c.isalpha() for c in text) < 3:
        raise DomainError("No meaningful speech detected; please send the task as text")
    if text.casefold().strip(".!?։ []()") in {
        "thank you",
        "thanks for watching",
        "thank you for watching",
        "subscribe",
        "շնորհակալություն",
        "inaudible",
        "unintelligible",
        "no speech",
        "music",
        "silence",
    }:
        raise DomainError("No actionable speech detected; please send the task as text")
    if len(text) > 5000:
        raise DomainError(
            "Transcript exceeds 5000 characters; please send a shorter task"
        )
    return text


def _dictated_fields(text: str) -> dict[str, str]:
    dictated: dict[str, str] = {}
    heading = re.match(
        r"^(?:(?:create (?:a )?task|ստեղծիր (?:մի )?առաջադրանք)[.,:;։՝]?\s+)?"
        r"(?:task )?(?:title|վերնագիր(?:ը|ն)?)\b\s*[:։՝․,.-]?\s*(?:(?:is|է)\s+)?",
        text,
        re.IGNORECASE,
    )
    if heading:
        # shortcut: labels are reserved in explicit Title/Վերնագիր mode; use plain text for literal labels.
        markers = list(
            re.finditer(
                r"\b(description|նկարագրություն(?:ը|ն)?|due date|do date|deadline|"
                r"(?:վերջնաժամկետ|ժամկետ|ամսաթիվ)(?:ը)?|"
                r"(?<!high )(?<!medium )(?<!low )priority|"
                r"(?<!բարձր )(?<!միջին )(?<!ցածր )առաջնահերթություն(?:ը|ն)?)\b"
                r"\s*[:։՝․,.-]?\s*(?:(?:is|է)\s+)?",
                text[heading.end() :],
                re.IGNORECASE,
            )
        )
        content = text[heading.end() :]
        field, start = "title", 0
        for marker in markers:
            value = content[start : marker.start()].strip(" .,:;-։՝․ ")
            if not value or field in dictated:
                raise DomainError("Please dictate each field once, with a value")
            dictated[field] = value
            field = marker.group(1).casefold()
            if field.startswith("նկարագրություն"):
                field = "description"
            elif field in {"deadline", "do date"} or field.startswith(
                ("վերջնաժամկետ", "ժամկետ", "ամսաթիվ")
            ):
                field = "due date"
            elif field.startswith("առաջնահերթություն"):
                field = "priority"
            start = marker.end()
        value = content[start:].strip(" .,:;-։՝․ ")
        if not value or field in dictated:
            raise DomainError("Please dictate each field once, with a value")
        dictated[field] = value
        if len(dictated["title"]) > 300:
            raise DomainError("Please keep the dictated title under 301 characters")
    return dictated


def extract_fields(text: str, now: datetime | None = None) -> dict[str, Any]:
    """Split explicitly dictated fields; preserve unstructured input as before."""
    text = normalize_text(text)
    if len(text) > 5000:
        raise DomainError("Task text exceeds 5000 characters")
    dictated = _dictated_fields(text)

    result: dict[str, Any] = {"title": dictated.get("title", text)}
    if "description" in dictated:
        result["description"] = dictated["description"]
    if not dictated and len(text) > 300:
        heading = text[:300]
        result["title"] = heading.rsplit(" ", 1)[0] if " " in heading else heading
        result["description"] = text
    lower = (dictated.get("due date", "") if dictated else text).casefold()
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Extraction clock must include a timezone")
    now = now.astimezone(UTC)
    date = None
    if dictated:
        named_date = re.match(
            r"(?:[a-z]+ \d{1,2}(?:st|nd|rd|th)?|\d{1,2}(?:st|nd|rd|th)? [a-z]+),? \d{4}\b",
            lower,
        )
        if named_date:
            words = re.sub(r"(?<=\d)(st|nd|rd|th)\b|,", "", named_date[0])
            for format in ("%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
                try:
                    parsed = datetime.strptime(words, format)
                except ValueError:
                    continue
                lower = parsed.strftime("%Y-%m-%d") + lower[named_date.end() :]
                break
    iso = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", lower)
    if iso:
        try:
            date = datetime.strptime(iso.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            pass
    elif re.search(r"\btomorrow\b|(?<!\w)վաղը(?!\w)", lower):
        date = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif re.search(r"\btoday\b|(?<!\w)այսօր(?!\w)", lower):
        date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if date is not None:
        hours = "one two three four five six seven eight nine ten eleven twelve".split()
        clock_text = re.sub(r"\b([ap])\.?\s*m\b\.?", r"\1m", lower)
        clock_text = re.sub(r"(?<=\d)\.(?=\d{2}\s*[ap]m\b)", ":", clock_text)
        clock_text = re.sub(
            r"\b(1[0-2]|[1-9])([0-5]\d)(?=\s*[ap]m\b)", r"\1:\2", clock_text
        )
        if dictated:
            armenian_numbers = (
                "զրո մեկ երկու երեք չորս հինգ վեց յոթ ութ ինը տաս տասնմեկ "
                "տասներկու տասներեք տասնչորս տասնհինգ տասնվեց տասնյոթ տասնութ "
                "տասնինը քսան քսանմեկ քսաներկու քսաներեք"
            ).split()
            for number, word in list(enumerate(armenian_numbers)) + [
                (30, "երեսուն"),
                (40, "քառասուն"),
                (45, "քառասունհինգ"),
                (50, "հիսուն"),
            ]:
                clock_text = re.sub(rf"\b{word}ն?\b", str(number), clock_text)
            clock_text = re.sub(
                r"\b(\d{1,2})\s+անց\s+(\d{1,2})\b",
                lambda m: f"{m[1]}:{int(m[2]):02d}",
                clock_text,
            )
            clock_text = re.sub(
                r"\bժամը\s+(1[3-9]|2[0-3]|0)(?![\d:])\b", r"ժամը \1:00", clock_text
            )
            for word, replacement in (
                ("այսօր", "today"),
                ("վաղը", "tomorrow"),
                ("ժամը", "at"),
            ):
                clock_text = re.sub(rf"\b{word}\b", replacement, clock_text)
        for hour, word in enumerate(hours, 1):
            clock_text = re.sub(rf"\b{word}\b", str(hour), clock_text)
        clock_text = re.sub(
            r"(?<=\d)\s+(fifteen|thirty|forty[ -]5)\b",
            lambda match: ":" + {"fifteen": "15", "thirty": "30"}.get(match[1], "45"),
            clock_text,
        )
        clock_pattern = r"(1[0-2]|[1-9])(?::([0-5]\d))?\s*(am|pm)\b"
        military_pattern = r"([01]?\d|2[0-3]):([0-5]\d)"
        if dictated and not re.fullmatch(
            rf"(?:today|tomorrow|\d{{4}}-\d{{2}}-\d{{2}})"
            rf"(?:\s+(?:at\s+)?(?:{clock_pattern}|{military_pattern}))?(?:\s+utc)?",
            clock_text,
        ):
            raise DomainError(
                "Please use an explicit due date and AM/PM or 24-hour time in UTC"
            )
        clock = re.search(rf"(?<![\d:]){clock_pattern}", clock_text)
        military = re.search(rf"(?<!\d){military_pattern}(?!\d)", clock_text)
        if clock:
            hour = int(clock.group(1)) % 12 + (12 if clock.group(3) == "pm" else 0)
            date = date.replace(hour=hour, minute=int(clock.group(2) or 0))
        elif military:
            date = date.replace(
                hour=int(military.group(1)), minute=int(military.group(2))
            )
        result["due_date"] = date
    if dictated and "due date" in dictated and date is None:
        raise DomainError(
            "Say due date today, tomorrow, YYYY-MM-DD, or a month/day with the year; add AM/PM for a time"
        )
    if dictated and "priority" in dictated:
        priority_match = re.fullmatch(
            r"(high|medium|low|բարձր|միջին|ցածր)(?: priority| առաջնահերթություն)?",
            dictated["priority"],
            re.IGNORECASE,
        )
        if priority_match is None:
            raise DomainError("Say priority high, medium, or low")
        value = priority_match[1].casefold()
        result["priority"] = Priority(
            {"բարձր": "HIGH", "միջին": "MEDIUM", "ցածր": "LOW"}.get(
                value, value.upper()
            )
        )
        return result
    lower = "" if dictated else text.casefold()
    for priority, pattern in (
        (Priority.HIGH, r"\bhigh priority\b|բարձր առաջնահերթություն"),
        (Priority.MEDIUM, r"\bmedium priority\b|միջին առաջնահերթություն"),
        (Priority.LOW, r"\blow priority\b|ցածր առաջնահերթություն"),
    ):
        if re.search(pattern, lower):
            result["priority"] = priority
            break
    return result
