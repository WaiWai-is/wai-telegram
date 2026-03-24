"""Tests for the Soul Prompt assembly."""

from app.services.agent.soul import build_soul_prompt


class TestSoulPromptAssembly:
    """Test that soul prompt includes all required layers."""

    def test_includes_identity(self):
        prompt = build_soul_prompt()
        assert "[Identity]" in prompt
        assert "Wai" in prompt

    def test_includes_rules(self):
        prompt = build_soul_prompt()
        assert "[Rules]" in prompt
        assert "no_message" in prompt

    def test_includes_context(self):
        prompt = build_soul_prompt()
        assert "[Context]" in prompt
        assert "UTC" in prompt

    def test_includes_available_actions(self):
        prompt = build_soul_prompt()
        assert "[Available actions]" in prompt
        assert "search_messages" in prompt

    def test_includes_user_name(self):
        prompt = build_soul_prompt(user_name="Mik")
        assert "Mik" in prompt

    def test_language_default(self):
        prompt = build_soul_prompt()
        assert "en" in prompt

    def test_language_russian(self):
        prompt = build_soul_prompt(user_language="ru")
        assert "ru" in prompt

    def test_connected_services(self):
        prompt = build_soul_prompt(connected_services=["gmail", "calendar"])
        assert "gmail" in prompt
        assert "calendar" in prompt

    def test_no_services(self):
        prompt = build_soul_prompt(connected_services=[])
        assert "none yet" in prompt

    def test_identity_memories_injected(self):
        prompt = build_soul_prompt(
            identity_memories=["Likes coffee", "Works at startup"]
        )
        assert "[About the user]" in prompt
        assert "Likes coffee" in prompt
        assert "Works at startup" in prompt

    def test_working_context_injected(self):
        prompt = build_soul_prompt(working_context=["Working on Q2 budget"])
        assert "[Current context]" in prompt
        assert "Q2 budget" in prompt

    def test_recalled_memories_injected(self):
        prompt = build_soul_prompt(recalled_memories=["Alex mentioned pricing at $500"])
        assert "[Recalled memories]" in prompt
        assert "Alex mentioned pricing" in prompt

    def test_no_memories_no_sections(self):
        prompt = build_soul_prompt()
        assert "[About the user]" not in prompt
        assert "[Current context]" not in prompt
        assert "[Recalled memories]" not in prompt

    def test_prompt_is_compact(self):
        """Soul prompt should be under 5KB as per spec."""
        prompt = build_soul_prompt(
            user_name="Test User",
            identity_memories=["mem1", "mem2", "mem3"],
            working_context=["ctx1", "ctx2"],
            recalled_memories=["rec1", "rec2", "rec3"],
        )
        assert len(prompt) < 5000, f"Soul prompt too large: {len(prompt)} bytes"

    def test_prompt_has_three_superpowers(self):
        prompt = build_soul_prompt()
        assert "MEMORY" in prompt
        assert "BUILD" in prompt
        assert "CHIEF OF STAFF" in prompt
