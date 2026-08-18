"""Lossless, JSON-safe Telegram message metadata extraction."""

from datetime import date, datetime
from typing import Any

from telethon.helpers import add_surrogate, del_surrogate


def _text_slice(text: str, offset: int, length: int) -> str:
    surrogate_text = add_surrogate(text)
    return del_surrogate(surrogate_text[offset : offset + length])


def _peer_value(peer: object | None) -> dict[str, int] | None:
    if peer is None:
        return None
    for attribute in ("user_id", "chat_id", "channel_id"):
        value = getattr(peer, attribute, None)
        if isinstance(value, int):
            return {attribute: value}
    return None


def _json_scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return None


def _plain_text(value: object) -> str | None:
    """Unwrap Telegram's TextWithEntities, which replaced plain strings for poll text.

    Passing the object straight into a JSON column raises "Object of type
    TextWithEntities is not JSON serializable" and aborts the whole batch.
    """
    if value is None or isinstance(value, str):
        return value
    inner = getattr(value, "text", None)
    return inner if isinstance(inner, str) else None


def _entities(
    message: object, text: str
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    rows: list[dict[str, Any]] = []
    visible_urls: list[str] = []
    hidden_urls: list[str] = []
    for entity in getattr(message, "entities", None) or ():
        offset = getattr(entity, "offset", None)
        length = getattr(entity, "length", None)
        if not isinstance(offset, int) or not isinstance(length, int):
            continue
        entity_type = type(entity).__name__
        row: dict[str, Any] = {
            "type": entity_type,
            "offset": offset,
            "length": length,
            "text": _text_slice(text, offset, length),
        }
        for attribute in ("url", "user_id", "language", "document_id"):
            value = _json_scalar(getattr(entity, attribute, None))
            if value is not None:
                row[attribute] = value
        rows.append(row)
        if entity_type == "MessageEntityUrl" and row["text"]:
            visible_urls.append(row["text"])
        url = row.get("url")
        if isinstance(url, str) and url:
            hidden_urls.append(url)
    return rows, visible_urls, hidden_urls


def _buttons(message: object) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    urls: list[str] = []
    for row_index, button_row in enumerate(getattr(message, "buttons", None) or ()):
        for column_index, button in enumerate(button_row or ()):
            item: dict[str, Any] = {
                "row": row_index,
                "column": column_index,
                "text": str(getattr(button, "text", "") or ""),
            }
            url = getattr(button, "url", None)
            if isinstance(url, str) and url:
                item["url"] = url
                urls.append(url)
            item["type"] = type(button).__name__
            if item["type"] == "SimpleNamespace":
                item.pop("type")
            rows.append(item)
    return rows, urls


def _webpage_preview(message: object) -> dict[str, Any] | None:
    webpage = getattr(getattr(message, "media", None), "webpage", None)
    if webpage is None:
        return None
    result: dict[str, Any] = {}
    for attribute in (
        "id",
        "url",
        "display_url",
        "site_name",
        "title",
        "description",
        "type",
        "author",
        "duration",
    ):
        value = _json_scalar(getattr(webpage, attribute, None))
        if value is not None:
            result[attribute] = value
    result["has_photo"] = getattr(webpage, "photo", None) is not None
    result["has_document"] = getattr(webpage, "document", None) is not None
    return result


def _forward_origin(message: object) -> dict[str, Any] | None:
    forward = getattr(message, "fwd_from", None)
    if forward is None:
        return None
    result: dict[str, Any] = {}
    for attribute in (
        "from_name",
        "date",
        "channel_post",
        "post_author",
        "saved_from_msg_id",
        "psa_type",
    ):
        value = _json_scalar(getattr(forward, attribute, None))
        if value is not None:
            result[attribute] = value
    for attribute in ("from_id", "saved_from_peer"):
        value = _peer_value(getattr(forward, attribute, None))
        if value is not None:
            result["from_peer" if attribute == "from_id" else attribute] = value
    return result


def _reaction_value(reaction: object) -> str | int:
    emoticon = getattr(reaction, "emoticon", None)
    if isinstance(emoticon, str):
        return emoticon
    document_id = getattr(reaction, "document_id", None)
    if isinstance(document_id, int):
        return document_id
    return type(reaction).__name__


def _reactions(message: object) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in getattr(getattr(message, "reactions", None), "results", None) or ():
        result.append(
            {
                "reaction": _reaction_value(getattr(row, "reaction", None)),
                "count": int(getattr(row, "count", 0) or 0),
                "chosen_order": getattr(row, "chosen_order", None),
            }
        )
    return result


def _poll(message: object) -> dict[str, Any] | None:
    media = getattr(message, "media", None)
    poll = getattr(media, "poll", None)
    if poll is None:
        return None
    result = {
        "id": getattr(poll, "id", None),
        "question": _plain_text(getattr(poll, "question", None)),
        "closed": bool(getattr(poll, "closed", False)),
        "public_voters": bool(getattr(poll, "public_voters", False)),
        "multiple_choice": bool(getattr(poll, "multiple_choice", False)),
        "quiz": bool(getattr(poll, "quiz", False)),
        "answers": [
            {
                "text": _plain_text(getattr(answer, "text", None)),
            }
            for answer in getattr(poll, "answers", None) or ()
        ],
    }
    results = getattr(media, "results", None)
    if results is not None:
        result["total_voters"] = getattr(results, "total_voters", None)
    return result


def _contact(message: object) -> dict[str, Any] | None:
    media = getattr(message, "media", None)
    if type(media).__name__ != "MessageMediaContact":
        return None
    return {
        key: getattr(media, key, None)
        for key in ("phone_number", "first_name", "last_name", "vcard", "user_id")
    }


def _location(message: object) -> dict[str, Any] | None:
    media = getattr(message, "media", None)
    geo = getattr(media, "geo", None)
    if geo is None:
        return None
    result: dict[str, Any] = {
        "latitude": getattr(geo, "lat", None),
        "longitude": getattr(geo, "long", None),
    }
    for key in ("title", "address", "provider", "venue_id", "venue_type"):
        value = getattr(media, key, None)
        if value is not None:
            result[key] = value
    return result


def _service_event(message: object) -> dict[str, Any] | None:
    action = getattr(message, "action", None)
    if action is None:
        return None
    result: dict[str, Any] = {"type": type(action).__name__}
    for attribute in (
        "title",
        "user_id",
        "users",
        "photo",
        "ttl",
        "period",
        "amount",
        "currency",
        "message",
        "call_id",
    ):
        value = getattr(action, attribute, None)
        if isinstance(value, list):
            result[attribute] = [item for item in value if isinstance(item, int)]
        else:
            scalar = _json_scalar(value)
            if scalar is not None:
                result[attribute] = scalar
    return result


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def extract_message_metadata(
    message: object,
    *,
    file_name: str | None = None,
) -> dict[str, Any]:
    """Return all searchable/lifecycle metadata without downloading media bytes."""
    text = str(getattr(message, "message", None) or getattr(message, "text", "") or "")
    entities, visible_urls, hidden_urls = _entities(message, text)
    buttons, button_urls = _buttons(message)
    hidden_urls.extend(button_urls)
    webpage = _webpage_preview(message)
    if webpage:
        for key in ("url", "display_url"):
            value = webpage.get(key)
            if isinstance(value, str):
                hidden_urls.append(value)
    visible_urls = _deduplicate(visible_urls)
    hidden_urls = _deduplicate(hidden_urls)
    searchable_values = [file_name or "", *visible_urls, *hidden_urls]
    searchable_values.extend(str(button.get("text") or "") for button in buttons)
    if webpage:
        searchable_values.extend(
            str(webpage.get(key) or "") for key in ("site_name", "title", "description")
        )
    reply = getattr(message, "reply_to", None)
    return {
        "entities": entities or None,
        "visible_urls": visible_urls or None,
        "hidden_urls": hidden_urls or None,
        "buttons": buttons or None,
        "webpage_preview": webpage,
        "reply_to_message_id": getattr(reply, "reply_to_msg_id", None),
        "thread_id": getattr(reply, "reply_to_top_id", None),
        "forward_origin": _forward_origin(message),
        "album_id": getattr(message, "grouped_id", None),
        "reactions": _reactions(message) or None,
        "edited_at": getattr(message, "edit_date", None),
        "poll": _poll(message),
        "contact": _contact(message),
        "location": _location(message),
        "service_event": _service_event(message),
        "searchable_metadata": "\n".join(_deduplicate(searchable_values)) or None,
    }
