"""Voice Summary — the #1 wow moment.

Forward a voice message → get instant:
1. Full transcript
2. AI summary (key points)
3. Action items extracted
4. Entities (people, decisions, amounts)
5. Commitments detected

This is the feature that makes people say "how did I live without this?"
"""

import logging

import anthropic

from app.core.config import get_settings
from app.services.agent.commitments import (
    CommitmentDirection,
    detect_commitments,
)
from app.services.agent.entities import EntityType, extract_entities_fast

logger = logging.getLogger(__name__)

VOICE_SUMMARY_PROMPT = """Analyze this voice message transcript and provide a structured summary.

Transcript:
{transcript}

Respond in the SAME LANGUAGE as the transcript. Format:

📝 *Summary*
[2-3 sentence summary of what was discussed]

🔑 *Key Points*
• [key point 1]
• [key point 2]
• [key point 3]

📋 *Action Items*
• [action item with owner if mentioned]

Keep it concise — this is a Telegram message. If the transcript is short (under 30 words), just provide the summary without the other sections."""


async def summarize_voice(transcript: str, user_name: str | None = None) -> str:
    """Generate a rich summary of a voice message transcript.

    Returns formatted Telegram message with summary, key points,
    action items, entities, and detected commitments.
    """
    if not transcript or not transcript.strip():
        return "❌ Could not transcribe voice message (empty audio or unclear speech)."

    parts = []

    # 1. If short transcript, just return it
    if len(transcript.split()) < 15:
        parts.append(f"🎤 *Transcript:*\n{transcript}")
        return "\n".join(parts)

    # 2. Full transcript (collapsible for long ones)
    if len(transcript) > 500:
        parts.append(f"🎤 *Transcript* (first 500 chars):\n_{transcript[:500]}..._")
    else:
        parts.append(f"🎤 *Transcript:*\n_{transcript}_")

    # 3. AI Summary via Claude Haiku (cheap + fast)
    settings = get_settings()
    if settings.anthropic_api_key:
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[
                    {
                        "role": "user",
                        "content": VOICE_SUMMARY_PROMPT.format(
                            transcript=transcript[:2000]
                        ),
                    }
                ],
            )
            summary = response.content[0].text.strip()
            parts.append(f"\n{summary}")
        except Exception as e:
            logger.warning(f"Voice summary LLM failed: {e}")

    # 4. Entities (fast, no LLM)
    entities = extract_entities_fast(transcript)
    if entities:
        entity_parts = []
        persons = [e for e in entities if e.type == EntityType.PERSON]
        amounts = [e for e in entities if e.type == EntityType.AMOUNT]
        decisions = [e for e in entities if e.type == EntityType.DECISION]

        if persons:
            names = ", ".join(e.name for e in persons[:5])
            entity_parts.append(f"👤 People: {names}")
        if amounts:
            amts = ", ".join(e.name for e in amounts[:3])
            entity_parts.append(f"💰 Amounts: {amts}")
        if decisions:
            for d in decisions[:2]:
                entity_parts.append(f"✅ Decision: {d.name}")

        if entity_parts:
            parts.append("\n" + "\n".join(entity_parts))

    # 5. Commitments
    commitments = detect_commitments(transcript, user_name=user_name)
    if commitments:
        commit_parts = []
        for c in commitments:
            deadline_text = f" (by {c.deadline})" if c.deadline else ""
            if c.direction == CommitmentDirection.I_PROMISED:
                commit_parts.append(f"📤 You promised: {c.what}{deadline_text}")
            else:
                commit_parts.append(f"📥 {c.who} promised: {c.what}{deadline_text}")
        if commit_parts:
            parts.append("\n🤝 *Commitments:*\n" + "\n".join(commit_parts))

    return "\n".join(parts)


def estimate_voice_duration_text(duration_seconds: int | None) -> str:
    """Format duration for display."""
    if not duration_seconds:
        return ""
    if duration_seconds < 60:
        return f"{duration_seconds}s"
    minutes = duration_seconds // 60
    seconds = duration_seconds % 60
    return f"{minutes}m{seconds}s" if seconds else f"{minutes}m"
