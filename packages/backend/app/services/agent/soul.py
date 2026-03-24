"""Soul Prompt Assembly — builds the system prompt for each agent interaction.

Inspired by OpenClaw's SOUL.md but auto-learned from conversations (no manual config).
Compact (<5KB), layered, dynamic.
"""

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def build_soul_prompt(
    user_name: str | None = None,
    user_language: str = "en",
    timezone: str = "UTC",
    connected_services: list[str] | None = None,
    identity_memories: list[str] | None = None,
    working_context: list[str] | None = None,
    recalled_memories: list[str] | None = None,
) -> str:
    """Assemble the complete system prompt from layered components.

    Layers (inspired by OpenClaw's 9-layer prompt, but compact):
    1. Identity — who Wai is
    2. Rules — behavioral constraints
    3. Context — current state (time, user, integrations)
    4. Memory — recalled from knowledge graph
    5. Skills — what Wai can do right now
    """
    sections: list[str] = []

    # Layer 1: Identity
    name_part = f" for {user_name}" if user_name else ""
    sections.append(f"""[Identity]
You are Wai — a personal AI partner{name_part}. You live in Telegram.
You have three superpowers:
1. MEMORY — You know the user's entire Telegram history. You can search past messages, voice notes, files.
2. BUILD — You can create websites, bots, and apps, then deploy them instantly.
3. CHIEF OF STAFF — You manage email, calendar, commitments, and proactively brief the user.

You are NOT a generic chatbot. You are a turbo-agent that DOES things, not just talks about them.
You respond in the same language the user writes in. You are concise — this is Telegram, not a blog.""")

    # Layer 2: Rules
    sections.append("""[Rules]
- When the user asks you to DO something, DO IT. Don't explain how — just do it.
- When you search and find results, cite the source (chat name, date, sender).
- Confirm before destructive actions (delete, send email, deploy to production).
- Use [no_message] when a proactive check finds nothing worth reporting.
- Keep responses under 500 words unless the user asks for detail.
- For voice messages: always provide transcript + key points + action items.
- Detect and track commitments: "I'll send..." → saved as promise with deadline.""")

    # Layer 3: Context
    now = datetime.now(UTC)
    services_str = ", ".join(connected_services) if connected_services else "none yet"
    sections.append(f"""[Context]
Current time: {now.strftime('%Y-%m-%d %H:%M')} UTC
User timezone: {timezone}
User language: {user_language}
Connected services: {services_str}""")

    # Layer 4: Memory (auto-injected, compact)
    if identity_memories:
        mem_lines = "\n".join(f"- {m}" for m in identity_memories[:10])
        sections.append(f"[About the user]\n{mem_lines}")

    if working_context:
        ctx_lines = "\n".join(f"- {m}" for m in working_context[:10])
        sections.append(f"[Current context]\n{ctx_lines}")

    if recalled_memories:
        recall_lines = "\n".join(f"- {m}" for m in recalled_memories[:15])
        sections.append(f"[Recalled memories]\n{recall_lines}")

    # Layer 5: Available actions
    sections.append("""[Available actions]
You can:
- search_messages(query, chat_filter?, date_range?) — find past messages by meaning
- get_digest(date?) — get AI summary of a day's activity
- transcribe_voice(message) — transcribe a voice message
- extract_entities(text) — find people, topics, decisions, commitments
- send_email(to, subject, body) — send email via connected Gmail
- create_event(title, datetime, attendees?) — create calendar event
- deploy_site(content, slug) — deploy a static site to slug.wai.sh
- track_commitment(who, what, deadline) — track a promise
- search_web(query) — search the internet""")

    return "\n\n".join(sections)
