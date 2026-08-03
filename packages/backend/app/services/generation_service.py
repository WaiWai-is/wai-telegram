from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings


class GenerationConfigurationError(RuntimeError):
    """The configured generation provider cannot be called."""


class EmptyGenerationError(RuntimeError):
    """The generation provider returned no user-visible text."""


async def create_generation_response(
    input_data: Any,
    *,
    max_output_tokens: int,
    quality: bool = False,
    instructions: str | None = None,
    tools: list[dict[str, Any]] | None = None,
):
    """Call the single reviewed runtime generation model through Responses API."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise GenerationConfigurationError("OPENAI_API_KEY is required")

    effort = (
        settings.quality_generation_reasoning_effort
        if quality
        else settings.fast_generation_reasoning_effort
    )
    kwargs: dict[str, Any] = {
        "model": settings.generation_model,
        "reasoning": {"effort": effort},
        "max_output_tokens": max_output_tokens,
        "input": input_data,
        "store": False,
    }
    if instructions is not None:
        kwargs["instructions"] = instructions
    if tools:
        kwargs["tools"] = tools

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    return await client.responses.create(**kwargs)


async def generate_text(
    input_data: Any,
    *,
    max_output_tokens: int,
    quality: bool = False,
    instructions: str | None = None,
) -> str:
    response = await create_generation_response(
        input_data,
        max_output_tokens=max_output_tokens,
        quality=quality,
        instructions=instructions,
    )
    text = response.output_text.strip()
    if not text:
        raise EmptyGenerationError("OpenAI returned no text")
    return text
