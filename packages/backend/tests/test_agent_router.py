"""Tests for the Intent Router — classifies user messages correctly."""

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

    def test_search_uses_haiku(self):
        model = get_model_for_intent(Intent.SEARCH)
        assert "haiku" in model

    def test_voice_summary_uses_haiku(self):
        model = get_model_for_intent(Intent.VOICE_SUMMARY)
        assert "haiku" in model

    def test_chat_uses_haiku(self):
        model = get_model_for_intent(Intent.CHAT)
        assert "haiku" in model

    def test_digest_uses_haiku(self):
        model = get_model_for_intent(Intent.DIGEST)
        assert "haiku" in model

    def test_action_uses_haiku(self):
        model = get_model_for_intent(Intent.ACTION)
        assert "haiku" in model

    def test_build_uses_haiku(self):
        model = get_model_for_intent(Intent.BUILD)
        assert "haiku" in model

    def test_coach_uses_haiku(self):
        model = get_model_for_intent(Intent.COACH)
        assert "haiku" in model

    def test_all_intents_have_models(self):
        for intent in Intent:
            model = get_model_for_intent(intent)
            assert model, f"No model for intent {intent}"


class TestIntentEnum:
    """Test Intent enum values."""

    def test_all_intents_exist(self):
        expected = {
            "search",
            "voice_summary",
            "digest",
            "action",
            "build",
            "coach",
            "chat",
        }
        actual = {i.value for i in Intent}
        assert actual == expected

    def test_intents_are_strings(self):
        for intent in Intent:
            assert isinstance(intent.value, str)
