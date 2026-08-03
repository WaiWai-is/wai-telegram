"""Tests for the Intent Router — classifies user messages correctly."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.router import Intent, classify_intent, get_model_for_intent


class TestPatternBasedClassification:
    """Test quick pattern matching (no LLM call)."""

    @pytest.mark.asyncio
    async def test_search_command_en(self):
        assert await classify_intent("/search budget") == Intent.SEARCH

    @pytest.mark.asyncio
    async def test_search_command_ru(self):
        assert await classify_intent("/найди бюджет") == Intent.SEARCH

    @pytest.mark.asyncio
    async def test_find_command(self):
        assert await classify_intent("/find pricing discussion") == Intent.SEARCH

    @pytest.mark.asyncio
    async def test_digest_command(self):
        assert await classify_intent("/digest") == Intent.DIGEST

    @pytest.mark.asyncio
    async def test_digest_command_ru(self):
        assert await classify_intent("/дайджест") == Intent.DIGEST

    @pytest.mark.asyncio
    async def test_build_command(self):
        assert await classify_intent("/build landing page") == Intent.BUILD

    @pytest.mark.asyncio
    async def test_deploy_command(self):
        assert await classify_intent("/deploy my site") == Intent.BUILD

    @pytest.mark.asyncio
    async def test_coach_command(self):
        assert await classify_intent("/coach") == Intent.COACH

    @pytest.mark.asyncio
    async def test_teach_command(self):
        assert await classify_intent("/teach me prompting") == Intent.COACH

    @pytest.mark.asyncio
    async def test_send_command(self):
        assert await classify_intent("/send email to Alex") == Intent.ACTION

    @pytest.mark.asyncio
    async def test_email_command(self):
        assert await classify_intent("/email subject body") == Intent.ACTION

    @pytest.mark.asyncio
    async def test_voice_message_always_voice_summary(self):
        assert await classify_intent("any text", has_voice=True) == Intent.VOICE_SUMMARY

    @pytest.mark.asyncio
    async def test_voice_message_empty_text(self):
        assert await classify_intent("", has_voice=True) == Intent.VOICE_SUMMARY


class TestNaturalLanguageClassification:
    """Test natural language pattern matching (no LLM call)."""

    @pytest.mark.asyncio
    async def test_what_did_alex_say(self):
        assert (
            await classify_intent("What did Alex say about pricing?") == Intent.SEARCH
        )

    @pytest.mark.asyncio
    async def test_search_for(self):
        assert await classify_intent("Search for budget discussions") == Intent.SEARCH

    @pytest.mark.asyncio
    async def test_russian_search(self):
        assert await classify_intent("Что обсуждали с Алексом?") == Intent.SEARCH

    @pytest.mark.asyncio
    async def test_find_keyword(self):
        assert await classify_intent("Find the link about PostgreSQL") == Intent.SEARCH

    @pytest.mark.asyncio
    async def test_build_a_site(self):
        assert await classify_intent("Build a landing page for my cafe") == Intent.BUILD

    @pytest.mark.asyncio
    async def test_create_keyword(self):
        assert await classify_intent("Create a Telegram bot for orders") == Intent.BUILD

    @pytest.mark.asyncio
    async def test_deploy_keyword(self):
        assert await classify_intent("Deploy this to production") == Intent.BUILD

    @pytest.mark.asyncio
    async def test_send_email(self):
        assert (
            await classify_intent("Send email to Alex about the meeting")
            == Intent.ACTION
        )

    @pytest.mark.asyncio
    async def test_schedule_event(self):
        assert (
            await classify_intent("Schedule a meeting for tomorrow at 3pm")
            == Intent.ACTION
        )

    @pytest.mark.asyncio
    async def test_russian_build(self):
        assert await classify_intent("Создай сайт для кафе") == Intent.BUILD

    @pytest.mark.asyncio
    async def test_russian_action(self):
        assert await classify_intent("Отправь письмо Алексу") == Intent.ACTION

    @pytest.mark.asyncio
    async def test_digest_natural(self):
        assert await classify_intent("What happened yesterday?") == Intent.DIGEST

    @pytest.mark.asyncio
    async def test_commitments_natural(self):
        assert await classify_intent("What did I promise this week?") == Intent.SEARCH


class TestModelRouting:
    """Test model selection for each intent."""

    def test_all_intents_use_luna(self):
        for intent in Intent:
            assert get_model_for_intent(intent) == "gpt-5.6-luna"

    @pytest.mark.asyncio
    async def test_ambiguous_message_uses_shared_generation_service(self):
        with patch(
            "app.services.agent.router.generate_text",
            new_callable=AsyncMock,
            return_value="chat",
        ) as generate:
            assert await classify_intent("Hello there") == Intent.CHAT
        assert generate.await_args.kwargs["max_output_tokens"] == 20

    @pytest.mark.asyncio
    async def test_invalid_model_classification_is_surfaced(self):
        with (
            patch(
                "app.services.agent.router.generate_text",
                new_callable=AsyncMock,
                return_value="unknown",
            ),
            pytest.raises(ValueError, match="Invalid intent"),
        ):
            await classify_intent("Hello there")


class TestIntentEnum:
    """Test Intent enum values."""

    def test_all_intents_exist(self):
        expected = {
            "search",
            "voice_summary",
            "digest",
            "action",
            "build",
            "edit",
            "coach",
            "chat",
        }
        actual = {i.value for i in Intent}
        assert actual == expected

    def test_intents_are_strings(self):
        for intent in Intent:
            assert isinstance(intent.value, str)
