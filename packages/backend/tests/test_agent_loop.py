"""Tests for the Agent Loop — the core execution engine.

Covers:
- AgentContext and AgentResult dataclasses
- run_agent() main entry point with different intents
- Tool calling loop (mock Claude returning tool_use, then text)
- execute_tool dispatch to individual tool handlers
- Edge cases (empty message, very long message, max turns exceeded)
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.agent.loop import (
    MAX_TURNS,
    TOOLS,
    AgentContext,
    AgentMessage,
    AgentResult,
    execute_tool,
    run_agent,
)
from app.services.agent.router import Intent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(**overrides) -> AgentContext:
    """Create an AgentContext with sensible defaults."""
    defaults = dict(
        user_id=uuid4(),
        chat_id=12345,
        user_name="TestUser",
        user_language="en",
        timezone="UTC",
    )
    defaults.update(overrides)
    return AgentContext(**defaults)


def _text_block(text: str):
    """Simulate a Claude TextBlock."""
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(tool_name: str, tool_input: dict, block_id: str = "tu_1"):
    """Simulate a Claude ToolUseBlock."""
    return SimpleNamespace(
        type="tool_use", name=tool_name, input=tool_input, id=block_id
    )


def _claude_response(
    content_blocks, stop_reason="end_turn", input_tokens=10, output_tokens=20
):
    """Build a fake Claude messages.create() response."""
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=content_blocks, stop_reason=stop_reason, usage=usage)


# ===========================================================================
# Dataclass tests
# ===========================================================================


class TestAgentMessage:
    def test_fields(self):
        msg = AgentMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"


class TestAgentContext:
    def test_defaults(self):
        ctx = _make_context()
        assert ctx.user_language == "en"
        assert ctx.timezone == "UTC"
        assert ctx.connected_services == []
        assert ctx.identity_memories == []
        assert ctx.working_context == []
        assert ctx.recalled_memories == []
        assert ctx.conversation_history == []
        assert ctx.has_voice is False
        assert ctx.voice_transcript is None

    def test_custom_fields(self):
        ctx = _make_context(
            user_language="ru",
            timezone="Europe/Moscow",
            connected_services=["gmail"],
            identity_memories=["Likes coffee"],
            has_voice=True,
            voice_transcript="test transcript",
        )
        assert ctx.user_language == "ru"
        assert ctx.timezone == "Europe/Moscow"
        assert ctx.connected_services == ["gmail"]
        assert ctx.identity_memories == ["Likes coffee"]
        assert ctx.has_voice is True
        assert ctx.voice_transcript == "test transcript"


class TestAgentResult:
    def test_defaults(self):
        result = AgentResult(
            response="hello",
            intent=Intent.CHAT,
            model_used="claude-haiku-4-5-20251001",
        )
        assert result.response == "hello"
        assert result.intent == Intent.CHAT
        assert result.model_used == "claude-haiku-4-5-20251001"
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.tool_calls == 0

    def test_with_tokens(self):
        result = AgentResult(
            response="ok",
            intent=Intent.SEARCH,
            model_used="model-x",
            input_tokens=100,
            output_tokens=200,
            tool_calls=3,
        )
        assert result.input_tokens == 100
        assert result.output_tokens == 200
        assert result.tool_calls == 3


# ===========================================================================
# TOOLS constant
# ===========================================================================


class TestToolDefinitions:
    def test_all_tools_present(self):
        names = {t["name"] for t in TOOLS}
        expected = {
            "search_messages",
            "get_digest",
            "track_commitment",
            "extract_entities",
            "list_commitments",
            "search_web",
        }
        assert names == expected

    def test_tools_have_input_schema(self):
        for tool in TOOLS:
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"


# ===========================================================================
# execute_tool dispatch
# ===========================================================================


class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        ctx = _make_context()
        result = await execute_tool("nonexistent_tool", {}, ctx)
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    @patch("app.services.agent.loop._tool_search_messages", new_callable=AsyncMock)
    async def test_dispatches_search_messages(self, mock_search):
        mock_search.return_value = "found 3 messages"
        ctx = _make_context()
        result = await execute_tool("search_messages", {"query": "test"}, ctx)
        assert result == "found 3 messages"
        mock_search.assert_awaited_once_with({"query": "test"}, ctx)

    @pytest.mark.asyncio
    @patch("app.services.agent.loop._tool_get_digest", new_callable=AsyncMock)
    async def test_dispatches_get_digest(self, mock_digest):
        mock_digest.return_value = "digest content"
        ctx = _make_context()
        result = await execute_tool("get_digest", {"date": "2025-01-01"}, ctx)
        assert result == "digest content"
        mock_digest.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.agent.loop._tool_track_commitment", new_callable=AsyncMock)
    async def test_dispatches_track_commitment(self, mock_track):
        mock_track.return_value = "Tracked"
        ctx = _make_context()
        result = await execute_tool(
            "track_commitment",
            {"who": "Alex", "what": "send report", "direction": "they_promised"},
            ctx,
        )
        assert result == "Tracked"
        mock_track.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.agent.loop._tool_extract_entities")
    async def test_dispatches_extract_entities(self, mock_extract):
        mock_extract.return_value = "People: Alex"
        ctx = _make_context()
        result = await execute_tool("extract_entities", {"text": "Alex said hi"}, ctx)
        assert result == "People: Alex"
        mock_extract.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.agent.loop._tool_list_commitments")
    async def test_dispatches_list_commitments(self, mock_list):
        mock_list.return_value = "No commitments"
        ctx = _make_context()
        result = await execute_tool("list_commitments", {"direction": "all"}, ctx)
        assert result == "No commitments"
        mock_list.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.search_web", new_callable=AsyncMock, create=True)
    async def test_dispatches_search_web(self, mock_web):
        # search_web is imported inside execute_tool, so we patch it at the source
        with patch(
            "app.services.agent.web_search.search_web", new_callable=AsyncMock
        ) as mock_ws:
            mock_ws.return_value = "web results"
            ctx = _make_context()
            result = await execute_tool("search_web", {"query": "python"}, ctx)
            assert result == "web results"
            mock_ws.assert_awaited_once_with("python")


# ===========================================================================
# run_agent — main entry point
# ===========================================================================


class TestRunAgentSimpleChat:
    """Test run_agent when Claude responds with plain text (no tool use)."""

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_simple_chat_response(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        mock_classify.return_value = Intent.CHAT
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        # Mock the client instance and its messages.create
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response([_text_block("Hello! How can I help?")])
        )

        ctx = _make_context()
        result = await run_agent(ctx, "Hello")

        assert result.response == "Hello! How can I help?"
        assert result.intent == Intent.CHAT
        assert result.model_used == "claude-haiku-4-5-20251001"
        assert result.input_tokens == 10
        assert result.output_tokens == 20
        assert result.tool_calls == 0

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_search_intent(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        mock_classify.return_value = Intent.SEARCH
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response(
                [_text_block("Found 3 messages about pricing.")]
            )
        )

        ctx = _make_context()
        result = await run_agent(ctx, "Find pricing discussions")

        assert result.intent == Intent.SEARCH
        assert "pricing" in result.response

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_build_intent(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        mock_classify.return_value = Intent.BUILD
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response(
                [_text_block("Building your landing page...")]
            )
        )

        ctx = _make_context()
        result = await run_agent(ctx, "Build a landing page for my cafe")

        assert result.intent == Intent.BUILD
        assert "landing page" in result.response


class TestRunAgentWithToolCalling:
    """Test run_agent when Claude uses tool_use before giving a text response."""

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.execute_tool", new_callable=AsyncMock)
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_single_tool_call(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls, mock_exec_tool
    ):
        mock_classify.return_value = Intent.SEARCH
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."
        mock_exec_tool.return_value = "Found: Alex discussed pricing at $500"

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # First call: tool_use. Second call: text response.
        tool_block = _tool_use_block("search_messages", {"query": "pricing"})
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _claude_response(
                    [tool_block],
                    stop_reason="tool_use",
                    input_tokens=15,
                    output_tokens=25,
                ),
                _claude_response(
                    [_text_block("Alex discussed pricing at $500.")],
                    input_tokens=30,
                    output_tokens=40,
                ),
            ]
        )

        ctx = _make_context()
        result = await run_agent(ctx, "What did Alex say about pricing?")

        assert result.response == "Alex discussed pricing at $500."
        assert result.tool_calls == 1
        assert result.input_tokens == 45  # 15 + 30
        assert result.output_tokens == 65  # 25 + 40
        mock_exec_tool.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.execute_tool", new_callable=AsyncMock)
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_multiple_tool_calls_in_one_turn(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls, mock_exec_tool
    ):
        """Claude returns two tool_use blocks in a single response."""
        mock_classify.return_value = Intent.SEARCH
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."
        mock_exec_tool.side_effect = ["Result A", "Result B"]

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        tool_block_1 = _tool_use_block(
            "search_messages", {"query": "budget"}, block_id="tu_1"
        )
        tool_block_2 = _tool_use_block(
            "search_messages", {"query": "pricing"}, block_id="tu_2"
        )

        mock_client.messages.create = AsyncMock(
            side_effect=[
                _claude_response([tool_block_1, tool_block_2], stop_reason="tool_use"),
                _claude_response([_text_block("Here's what I found.")]),
            ]
        )

        ctx = _make_context()
        result = await run_agent(ctx, "Search for budget and pricing")

        assert result.tool_calls == 2
        assert result.response == "Here's what I found."

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.execute_tool", new_callable=AsyncMock)
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_sequential_tool_calls(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls, mock_exec_tool
    ):
        """Claude calls a tool, gets result, calls another tool, then responds."""
        mock_classify.return_value = Intent.SEARCH
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."
        mock_exec_tool.side_effect = ["search result", "digest result"]

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_client.messages.create = AsyncMock(
            side_effect=[
                _claude_response(
                    [_tool_use_block("search_messages", {"query": "meeting"}, "tu_1")],
                    stop_reason="tool_use",
                    input_tokens=10,
                    output_tokens=10,
                ),
                _claude_response(
                    [_tool_use_block("get_digest", {"date": "2025-01-01"}, "tu_2")],
                    stop_reason="tool_use",
                    input_tokens=20,
                    output_tokens=20,
                ),
                _claude_response(
                    [_text_block("Summary: you had a meeting and here's the digest.")],
                    input_tokens=30,
                    output_tokens=30,
                ),
            ]
        )

        ctx = _make_context()
        result = await run_agent(ctx, "What happened in my meeting yesterday?")

        assert result.tool_calls == 2
        assert result.input_tokens == 60
        assert result.output_tokens == 60
        assert "meeting" in result.response

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.execute_tool", new_callable=AsyncMock)
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_tool_execution_error_is_sent_back(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls, mock_exec_tool
    ):
        """When a tool raises an exception, the error message is returned to Claude."""
        mock_classify.return_value = Intent.SEARCH
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."
        mock_exec_tool.side_effect = RuntimeError("DB connection failed")

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        tool_block = _tool_use_block("search_messages", {"query": "test"})
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _claude_response([tool_block], stop_reason="tool_use"),
                _claude_response([_text_block("Sorry, I couldn't search right now.")]),
            ]
        )

        ctx = _make_context()
        result = await run_agent(ctx, "Search something")

        # The agent should still return a response despite tool failure
        assert result.response == "Sorry, I couldn't search right now."
        assert result.tool_calls == 1


class TestRunAgentEdgeCases:
    """Test edge cases for run_agent."""

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_empty_message(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        mock_classify.return_value = Intent.CHAT
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response(
                [_text_block("I'm here if you need anything.")]
            )
        )

        ctx = _make_context()
        result = await run_agent(ctx, "")

        assert result.response == "I'm here if you need anything."

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_very_long_message(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        mock_classify.return_value = Intent.CHAT
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response([_text_block("Got it.")])
        )

        ctx = _make_context()
        long_msg = "a" * 50000
        result = await run_agent(ctx, long_msg)

        assert result.response == "Got it."
        # Verify the full message was passed through
        call_kwargs = mock_client.messages.create.call_args
        user_msg = call_kwargs.kwargs["messages"][-1]
        assert len(user_msg["content"]) == 50000

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_no_text_blocks_returns_default(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        """When Claude returns content with no text blocks, return a default."""
        mock_classify.return_value = Intent.CHAT
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        # Content block without .text attribute
        empty_block = SimpleNamespace(type="something_else")
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response([empty_block])
        )

        ctx = _make_context()
        result = await run_agent(ctx, "test")

        assert result.response == "I processed your request."

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.execute_tool", new_callable=AsyncMock)
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_max_turns_exceeded(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls, mock_exec_tool
    ):
        """When the agent loops MAX_TURNS times with tool_use, it gives up."""
        mock_classify.return_value = Intent.SEARCH
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."
        mock_exec_tool.return_value = "some result"

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # Every response is a tool_use — never stops
        tool_response = _claude_response(
            [_tool_use_block("search_messages", {"query": "loop"})],
            stop_reason="tool_use",
            input_tokens=5,
            output_tokens=5,
        )
        mock_client.messages.create = AsyncMock(return_value=tool_response)

        ctx = _make_context()
        result = await run_agent(ctx, "infinite loop")

        assert "turn limit" in result.response
        assert result.tool_calls == MAX_TURNS
        assert result.input_tokens == 5 * MAX_TURNS
        assert result.output_tokens == 5 * MAX_TURNS


class TestRunAgentVoiceMessages:
    """Test voice message handling in run_agent."""

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_voice_transcript_with_text(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        """Voice transcript + user text creates combined user content."""
        mock_classify.return_value = Intent.VOICE_SUMMARY
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response(
                [_text_block("Voice summary: meeting notes.")]
            )
        )

        ctx = _make_context(
            has_voice=True, voice_transcript="Discussion about Q2 budget"
        )
        result = await run_agent(ctx, "summarize this")

        assert result.intent == Intent.VOICE_SUMMARY
        # Check that messages sent to Claude include the transcript
        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_msg = call_kwargs["messages"][-1]["content"]
        assert "Voice message transcript" in user_msg
        assert "Q2 budget" in user_msg
        assert "summarize this" in user_msg

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_voice_transcript_without_text(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        """Voice transcript with empty text shows only transcript."""
        mock_classify.return_value = Intent.VOICE_SUMMARY
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response([_text_block("Transcript summary.")])
        )

        ctx = _make_context(has_voice=True, voice_transcript="Hello from voice")
        await run_agent(ctx, "")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_msg = call_kwargs["messages"][-1]["content"]
        assert "Voice message transcript" in user_msg
        assert "Hello from voice" in user_msg
        # Should NOT contain "User's text:" when message is empty
        assert "User's text:" not in user_msg


class TestRunAgentConversationHistory:
    """Test that conversation history is passed through correctly."""

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_history_included_in_messages(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        mock_classify.return_value = Intent.CHAT
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response([_text_block("Sure!")])
        )

        history = [
            AgentMessage(role="user", content="Hi"),
            AgentMessage(role="assistant", content="Hello!"),
        ]
        ctx = _make_context(conversation_history=history)
        await run_agent(ctx, "Tell me more")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        messages = call_kwargs["messages"]
        # 2 history messages + 1 current
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hi"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hello!"
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "Tell me more"

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_history_truncated_to_20(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        """Only the last 20 messages from history should be included."""
        mock_classify.return_value = Intent.CHAT
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response([_text_block("Ok.")])
        )

        # 30 history messages
        history = [
            AgentMessage(role="user" if i % 2 == 0 else "assistant", content=f"msg-{i}")
            for i in range(30)
        ]
        ctx = _make_context(conversation_history=history)
        await run_agent(ctx, "latest")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        messages = call_kwargs["messages"]
        # 20 history (truncated) + 1 current = 21
        assert len(messages) == 21
        # First message should be msg-10 (30 - 20 = 10)
        assert messages[0]["content"] == "msg-10"


class TestRunAgentMetrics:
    """Test that metrics are incremented correctly."""

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_metrics_incremented(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        mock_classify.return_value = Intent.DIGEST
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response(
                [_text_block("Digest ready.")], input_tokens=50, output_tokens=100
            )
        )

        # increment is imported dynamically inside run_agent via
        # `from app.services.agent.metrics import increment`
        # so we patch it at the source module
        calls = []

        def fake_increment(metric, value=1):
            calls.append((metric, value))

        with patch("app.services.agent.metrics.increment", fake_increment):
            ctx = _make_context()
            result = await run_agent(ctx, "/digest")

        assert result.input_tokens == 50
        assert result.output_tokens == 100

        # Verify key metrics were recorded
        metric_names = [c[0] for c in calls]
        assert "agent_requests_total" in metric_names
        assert "agent_intent_digest" in metric_names
        assert "agent_tokens_input" in metric_names
        assert "agent_tokens_output" in metric_names

        # Verify token values passed to metrics
        token_input_call = next(c for c in calls if c[0] == "agent_tokens_input")
        assert token_input_call[1] == 50
        token_output_call = next(c for c in calls if c[0] == "agent_tokens_output")
        assert token_output_call[1] == 100


class TestRunAgentSoulPromptArgs:
    """Test that the soul prompt is assembled with correct context."""

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_soul_prompt_receives_context(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        mock_classify.return_value = Intent.CHAT
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "Assembled prompt"

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response([_text_block("ok")])
        )

        ctx = _make_context(
            user_name="Mik",
            user_language="ru",
            timezone="Europe/Moscow",
            connected_services=["gmail"],
            identity_memories=["Likes espresso"],
            working_context=["Q2 budget review"],
            recalled_memories=["Alex said $500"],
        )
        await run_agent(ctx, "test")

        mock_soul.assert_called_once_with(
            user_name="Mik",
            user_language="ru",
            timezone="Europe/Moscow",
            connected_services=["gmail"],
            identity_memories=["Likes espresso"],
            working_context=["Q2 budget review"],
            recalled_memories=["Alex said $500"],
        )

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_system_prompt_passed_to_claude(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        mock_classify.return_value = Intent.CHAT
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "Custom soul prompt"

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response([_text_block("ok")])
        )

        ctx = _make_context()
        await run_agent(ctx, "test")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "Custom soul prompt"
        assert call_kwargs["tools"] == TOOLS
        assert call_kwargs["max_tokens"] == 4096


class TestRunAgentMultiTextBlocks:
    """Test response assembly when Claude returns multiple text blocks."""

    @pytest.mark.asyncio
    @patch("app.services.agent.loop.anthropic.AsyncAnthropic")
    @patch("app.services.agent.loop.classify_intent", new_callable=AsyncMock)
    @patch("app.services.agent.loop.get_model_for_intent")
    @patch("app.services.agent.loop.build_soul_prompt")
    async def test_multiple_text_blocks_joined(
        self, mock_soul, mock_model, mock_classify, mock_anthropic_cls
    ):
        mock_classify.return_value = Intent.CHAT
        mock_model.return_value = "claude-haiku-4-5-20251001"
        mock_soul.return_value = "You are Wai."

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_claude_response(
                [
                    _text_block("First part."),
                    _text_block("Second part."),
                ]
            )
        )

        ctx = _make_context()
        result = await run_agent(ctx, "test")

        assert result.response == "First part.\nSecond part."
