import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from app import ai
from app.schemas import TaskCreate
from app.services import DomainError

API_URL = "https://api.openai.com/v1/responses"


def response_for(fields):
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(fields)}],
            }
        ],
    }


def enable_mock_provider(monkeypatch):
    monkeypatch.setattr(ai.settings, "openai_api_key", "fixture-key")
    monkeypatch.setattr(ai.settings, "task_parser_enabled", True)
    monkeypatch.setattr(ai, "provider_gate", AsyncMock())


@pytest.mark.asyncio
@respx.mock
async def test_parse_task_uses_structured_output_and_validates_fields(monkeypatch):
    enable_mock_provider(monkeypatch)
    route = respx.post(API_URL).mock(
        return_value=httpx.Response(
            200,
            json=response_for(
                {
                    "is_task": True,
                    "title": "Call Anna",
                    "description": "Discuss the report",
                    "due_date": "2026-10-22T14:00:00Z",
                    "priority": "HIGH",
                }
            ),
        )
    )

    task = await ai.parse_task(
        "Please call Anna tomorrow at 14:00 to discuss the report"
    )

    assert task == TaskCreate(
        title="Call Anna",
        description="Discuss the report",
        due_date=datetime(2026, 10, 22, 14, tzinfo=UTC),
        priority="HIGH",
    )
    request = route.calls[0].request
    body = json.loads(request.content)
    assert body["model"] == "gpt-6-luna"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["store"] is False
    assert "Please call Anna" in body["input"][1]["content"]
    prompt = body["input"][0]["content"]
    assert "Asia/Yerevan" in prompt
    assert "Current Yerevan time:" in prompt
    assert request.headers["authorization"] == "Bearer fixture-key"
    ai.provider_gate.assert_awaited_once()


@pytest.mark.asyncio
@respx.mock
async def test_parse_task_does_not_turn_conversation_into_task(monkeypatch):
    enable_mock_provider(monkeypatch)
    respx.post(API_URL).mock(
        return_value=httpx.Response(
            200,
            json=response_for(
                {
                    "is_task": False,
                    "title": None,
                    "description": None,
                    "due_date": None,
                    "priority": None,
                }
            ),
        )
    )

    assert await ai.parse_task("How are you today?") is None


@pytest.mark.asyncio
@respx.mock
async def test_parse_task_rejects_malformed_model_output(monkeypatch):
    enable_mock_provider(monkeypatch)
    respx.post(API_URL).mock(
        return_value=httpx.Response(
            200,
            json=response_for(
                {
                    "is_task": True,
                    "title": "Call Anna",
                    "description": None,
                    "due_date": "tomorrow afternoon",
                    "priority": "URGENT",
                }
            ),
        )
    )

    with pytest.raises(DomainError):
        await ai.parse_task("Call Anna")


@pytest.mark.asyncio
@respx.mock
async def test_parse_task_fails_closed_when_provider_is_unavailable(monkeypatch):
    enable_mock_provider(monkeypatch)
    respx.post(API_URL).mock(return_value=httpx.Response(503))

    with pytest.raises(DomainError):
        await ai.parse_task("Call Anna")


@pytest.mark.asyncio
@respx.mock
async def test_parse_task_preserves_armenian_fields(monkeypatch):
    enable_mock_provider(monkeypatch)
    respx.post(API_URL).mock(
        return_value=httpx.Response(
            200,
            json=response_for(
                {
                    "is_task": True,
                    "title": "Զանգել Աննային",
                    "description": "Քննարկել զեկույցը",
                    "due_date": "2026-10-22T14:00:00Z",
                    "priority": "HIGH",
                }
            ),
        )
    )

    task = await ai.parse_task(
        "Վաղը զանգել Աննային՝ զեկույցը քննարկելու համար, ժամը 14:00-ին, բարձր առաջնահերթությամբ։"
    )

    assert task == TaskCreate(
        title="Զանգել Աննային",
        description="Քննարկել զեկույցը",
        due_date=datetime(2026, 10, 22, 14, tzinfo=UTC),
        priority="HIGH",
    )


@pytest.mark.asyncio
async def test_parse_task_without_key_does_not_fall_back_to_creating_wrong_task(
    monkeypatch,
):
    monkeypatch.setattr(ai.settings, "openai_api_key", "")
    monkeypatch.setattr(ai.settings, "task_parser_enabled", True)

    with pytest.raises(ai.TaskParserError, match="OPENAI_API_KEY"):
        await ai.parse_task("How are you?")


@pytest.mark.asyncio
async def test_local_no_api_mode_keeps_deterministic_task_entry(monkeypatch):
    monkeypatch.setattr(ai.settings, "openai_api_key", "local-only")
    monkeypatch.setattr(ai.settings, "task_parser_enabled", False)

    assert await ai.parse_task("Call Anna") == TaskCreate(title="Call Anna")
