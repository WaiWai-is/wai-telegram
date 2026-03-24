"""Tests for Conversation History — session memory."""

from uuid import uuid4

from app.services.agent.conversation import (
    MAX_HISTORY,
    _conversations,
    add_message,
    clear_history,
    get_conversation_summary,
    get_history,
    get_history_for_agent,
)


class TestConversationHistory:
    def setup_method(self):
        _conversations.clear()

    def test_add_and_get(self):
        uid = uuid4()
        add_message(uid, "user", "hello")
        add_message(uid, "assistant", "hi there")
        history = get_history(uid)
        assert len(history) == 2
        assert history[0].role == "user"
        assert history[0].content == "hello"
        assert history[1].role == "assistant"

    def test_max_history_trim(self):
        uid = uuid4()
        for i in range(30):
            add_message(uid, "user", f"message {i}")
        assert len(get_history(uid)) == MAX_HISTORY

    def test_oldest_trimmed(self):
        uid = uuid4()
        for i in range(25):
            add_message(uid, "user", f"msg-{i}")
        history = get_history(uid)
        assert "msg-0" not in [m.content for m in history]
        assert f"msg-{24}" in [m.content for m in history]

    def test_clear_history(self):
        uid = uuid4()
        add_message(uid, "user", "hello")
        clear_history(uid)
        assert len(get_history(uid)) == 0

    def test_users_isolated(self):
        uid1 = uuid4()
        uid2 = uuid4()
        add_message(uid1, "user", "from user 1")
        add_message(uid2, "user", "from user 2")
        assert len(get_history(uid1)) == 1
        assert len(get_history(uid2)) == 1
        assert get_history(uid1)[0].content == "from user 1"

    def test_get_history_for_agent(self):
        uid = uuid4()
        add_message(uid, "user", "what can you do?")
        add_message(uid, "assistant", "I can search, build, and manage.")
        agent_history = get_history_for_agent(uid)
        assert len(agent_history) == 2
        assert agent_history[0] == {"role": "user", "content": "what can you do?"}
        assert agent_history[1]["role"] == "assistant"

    def test_limit_parameter(self):
        uid = uuid4()
        for i in range(10):
            add_message(uid, "user", f"msg-{i}")
        history = get_history(uid, limit=3)
        assert len(history) == 3

    def test_conversation_summary_empty(self):
        uid = uuid4()
        summary = get_conversation_summary(uid)
        assert "No previous" in summary

    def test_conversation_summary_with_history(self):
        uid = uuid4()
        add_message(uid, "user", "hello")
        add_message(uid, "assistant", "hi")
        summary = get_conversation_summary(uid)
        assert "2 messages" in summary

    def test_timestamp_set(self):
        uid = uuid4()
        add_message(uid, "user", "test")
        msg = get_history(uid)[0]
        assert msg.timestamp is not None
