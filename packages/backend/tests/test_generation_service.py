"""Contract tests for the single OpenAI Responses generation boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.generation_service import (
    EmptyGenerationError,
    GenerationConfigurationError,
    create_generation_response,
    generate_text,
)


def _settings(**overrides):
    values = {
        "openai_api_key": "test-key",
        "generation_model": "gpt-5.6-luna",
        "fast_generation_reasoning_effort": "none",
        "quality_generation_reasoning_effort": "low",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize(("quality", "effort"), [(False, "none"), (True, "low")])
async def test_response_call_pins_model_effort_and_store_policy(quality, effort):
    response = SimpleNamespace(output_text="answer")
    create = AsyncMock(return_value=response)
    client = MagicMock()
    client.responses.create = create
    with (
        patch("app.services.generation_service.get_settings", return_value=_settings()),
        patch("app.services.generation_service.AsyncOpenAI", return_value=client),
    ):
        returned = await create_generation_response(
            "hello",
            max_output_tokens=200,
            quality=quality,
            instructions="system",
            tools=[{"type": "web_search"}],
        )

    assert returned is response
    assert create.await_args.kwargs == {
        "model": "gpt-5.6-luna",
        "reasoning": {"effort": effort},
        "max_output_tokens": 200,
        "input": "hello",
        "store": False,
        "instructions": "system",
        "tools": [{"type": "web_search"}],
    }


@pytest.mark.asyncio
async def test_missing_openai_key_is_surfaced_before_client_creation():
    with (
        patch(
            "app.services.generation_service.get_settings",
            return_value=_settings(openai_api_key=""),
        ),
        patch("app.services.generation_service.AsyncOpenAI") as client,
        pytest.raises(GenerationConfigurationError, match="OPENAI_API_KEY"),
    ):
        await create_generation_response("hello", max_output_tokens=20)
    client.assert_not_called()


@pytest.mark.asyncio
async def test_generate_text_strips_output_and_rejects_empty_response():
    with patch(
        "app.services.generation_service.create_generation_response",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(output_text="  answer  "),
    ):
        assert await generate_text("hello", max_output_tokens=20) == "answer"

    with (
        patch(
            "app.services.generation_service.create_generation_response",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(output_text="  "),
        ),
        pytest.raises(EmptyGenerationError),
    ):
        await generate_text("hello", max_output_tokens=20)
