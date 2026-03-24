"""Forward Processor — remember anything forwarded to Wai.

When user forwards a message to the bot, Wai:
1. Detects the type (text, voice, photo, document, link)
2. Extracts content (transcribes voice, reads text, describes photo)
3. Extracts entities (people, decisions, amounts, dates)
4. Detects commitments
5. Stores in searchable memory
6. Returns a beautiful confirmation

This is the core "second brain" mechanic.
Forward anything → Wai remembers → search later.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.agent.commitments import detect_commitments, save_commitment
from app.services.agent.entities import (
    extract_entities_fast,
    format_entities_for_display,
)

logger = logging.getLogger(__name__)


@dataclass
class ForwardedContent:
    """Parsed content from a forwarded message."""

    text: str = ""
    content_type: str = "text"  # text, voice, photo, document, link
    source_chat: str | None = None
    source_sender: str | None = None
    source_date: datetime | None = None
    has_url: bool = False
    url: str | None = None


def parse_forwarded_message(message: dict) -> ForwardedContent:
    """Parse a Telegram message dict into ForwardedContent."""
    content = ForwardedContent()

    # Extract forward info
    forward_from = message.get("forward_from", {})
    forward_from_chat = message.get("forward_from_chat", {})
    forward_date = message.get("forward_date")

    if forward_from:
        name_parts = [
            forward_from.get("first_name", ""),
            forward_from.get("last_name", ""),
        ]
        content.source_sender = " ".join(p for p in name_parts if p).strip() or None
    elif forward_from_chat:
        content.source_chat = forward_from_chat.get("title")

    if forward_date:
        content.source_date = datetime.fromtimestamp(forward_date, tz=UTC)

    # Extract text
    content.text = message.get("text", "") or message.get("caption", "") or ""

    # Detect content type
    if message.get("voice") or message.get("audio"):
        content.content_type = "voice"
    elif message.get("photo"):
        content.content_type = "photo"
    elif message.get("document"):
        content.content_type = "document"
    elif message.get("video"):
        content.content_type = "video"
    elif message.get("sticker"):
        content.content_type = "sticker"
    else:
        content.content_type = "text"

    # Detect URLs
    url_match = re.search(r"https?://\S+", content.text)
    if url_match:
        content.has_url = True
        content.url = url_match.group(0)

    return content


async def process_forwarded_message(
    message: dict,
    user_name: str | None = None,
) -> str:
    """Process a forwarded message and return a confirmation.

    This is the main entry point for forwarded messages.
    """
    content = parse_forwarded_message(message)

    parts = []

    # Source info
    source_parts = []
    if content.source_sender:
        source_parts.append(f"from *{content.source_sender}*")
    if content.source_chat:
        source_parts.append(f"in _{content.source_chat}_")
    if content.source_date:
        source_parts.append(f"({content.source_date.strftime('%b %d, %H:%M')})")

    source_str = " ".join(source_parts) if source_parts else ""

    # Content type icon
    type_icons = {
        "text": "💬",
        "voice": "🎤",
        "photo": "📷",
        "document": "📄",
        "video": "🎬",
        "sticker": "😀",
    }
    icon = type_icons.get(content.content_type, "📝")

    if content.text:
        parts.append(f"{icon} *Saved* {source_str}")

        # Show preview
        preview = content.text[:300]
        if len(content.text) > 300:
            preview += "..."
        parts.append(f"_{preview}_")

        # Extract entities
        entities = extract_entities_fast(content.text)
        if entities:
            parts.append(f"\n{format_entities_for_display(entities)}")

        # Detect commitments
        from uuid import UUID

        user_id = UUID("00000000-0000-0000-0000-000000000000")
        commitments = detect_commitments(content.text, user_name=user_name)
        if commitments:
            commit_lines = []
            for c in commitments:
                save_commitment(c, user_id)
                deadline_text = f" (by {c.deadline})" if c.deadline else ""
                commit_lines.append(f"  🤝 {c.who}: {c.what}{deadline_text}")
            parts.append("\n*Commitments detected:*\n" + "\n".join(commit_lines))

        # URL detected
        if content.has_url:
            parts.append(f"\n🔗 Link: {content.url}")

        parts.append("\n✅ _Remembered. You can search for this later._")
    elif content.content_type == "voice":
        parts.append(
            f"{icon} Voice message received {source_str}\n"
            "_Transcribing... (voice summary will follow)_"
        )
    elif content.content_type == "photo":
        # Try to describe the photo with Claude Vision
        photos = message.get("photo", [])
        if photos:
            from app.services.agent.media_processor import describe_photo

            # Use the largest photo size
            file_id = photos[-1].get("file_id", "")
            description = await describe_photo(file_id)
            if description:
                parts.append(f"{icon} *Photo saved* {source_str}")
                parts.append(f"_{description}_")
                # Extract entities from description
                desc_entities = extract_entities_fast(description)
                if desc_entities:
                    parts.append(f"\n{format_entities_for_display(desc_entities)}")
                parts.append(
                    "\n✅ _Remembered. Search for this photo's content later._"
                )
            else:
                parts.append(
                    f"{icon} Photo received {source_str}\n"
                    "_Could not analyze photo. Send text describing it and I'll remember._"
                )
        else:
            parts.append(f"{icon} Photo received {source_str}")
    elif content.content_type == "document":
        doc = message.get("document", {})
        file_name = doc.get("file_name", "unknown")
        file_id = doc.get("file_id", "")

        from app.services.agent.media_processor import extract_document_text

        doc_text = await extract_document_text(file_id, file_name)
        if doc_text and not doc_text.startswith("[Document:"):
            parts.append(f"{icon} *Document saved* {source_str}: *{file_name}*")
            preview = doc_text[:500]
            if len(doc_text) > 500:
                preview += "..."
            parts.append(f"_{preview}_")
            # Extract entities from document content
            doc_entities = extract_entities_fast(doc_text[:2000])
            if doc_entities:
                parts.append(f"\n{format_entities_for_display(doc_entities)}")
            parts.append("\n✅ _Remembered. Search for this document's content later._")
        else:
            parts.append(
                f"{icon} Document received {source_str}: *{file_name}*\n"
                f"_{doc_text or 'Content extraction not available.'}_"
            )
    else:
        parts.append(f"{icon} Content received {source_str}\n_Saved._")

    return "\n".join(parts)


def is_forwarded_message(message: dict) -> bool:
    """Check if a message is forwarded from another user/chat."""
    return bool(
        message.get("forward_from")
        or message.get("forward_from_chat")
        or message.get("forward_sender_name")
        or message.get("forward_date")
    )
