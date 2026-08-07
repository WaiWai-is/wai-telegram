from unittest.mock import AsyncMock, patch

from app.services.agent.typing import send_typing_action


async def test_typing_uses_central_bot_client():
    client = AsyncMock()
    with patch(
        "app.services.agent.typing.get_bot_api_client",
        return_value=client,
    ):
        await send_typing_action(12345)

    client.call.assert_awaited_once_with(
        "sendChatAction",
        json={"chat_id": 12345, "action": "typing"},
        timeout=5,
    )


async def test_typing_failure_is_non_fatal():
    client = AsyncMock()
    client.call.side_effect = RuntimeError("local bot api unavailable")
    with patch(
        "app.services.agent.typing.get_bot_api_client",
        return_value=client,
    ):
        await send_typing_action(12345)
