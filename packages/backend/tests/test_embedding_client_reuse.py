"""The OpenAI client is built once, not per embedding call."""

import pytest


@pytest.fixture(autouse=True)
async def _reset_client(monkeypatch):
    from app.services import embedding_service

    monkeypatch.setattr(
        embedding_service.settings, "openai_api_key", "sk-test", raising=False
    )
    embedding_service._client = None
    yield
    embedding_service._client = None


async def test_the_same_client_is_returned_twice():
    from app.services.embedding_service import get_openai_client

    first = await get_openai_client()
    second = await get_openai_client()
    assert first is second


async def test_concurrent_callers_do_not_build_two_clients():
    import asyncio

    from app.services.embedding_service import get_openai_client

    clients = await asyncio.gather(*(get_openai_client() for _ in range(8)))
    assert len({id(c) for c in clients}) == 1


async def test_closing_lets_the_next_call_rebuild():
    from app.services.embedding_service import close_openai_client, get_openai_client

    first = await get_openai_client()
    await close_openai_client()
    second = await get_openai_client()
    assert first is not second
