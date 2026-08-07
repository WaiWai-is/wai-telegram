from types import SimpleNamespace

from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

from app.services.telegram_metadata import extract_message_metadata


def test_extracts_visible_hidden_and_button_urls_for_search():
    text = "Документы example.com и договор"
    visible_start = text.index("example.com")
    hidden_start = text.index("договор")
    message = SimpleNamespace(
        message=text,
        entities=[
            MessageEntityUrl(offset=visible_start, length=len("example.com")),
            MessageEntityTextUrl(
                offset=hidden_start,
                length=len("договор"),
                url="https://secret.example/contract?id=42",
            ),
        ],
        buttons=[
            [
                SimpleNamespace(
                    text="Открыть",
                    url="https://button.example/file",
                    data=None,
                )
            ]
        ],
        media=None,
        reply_to=None,
        fwd_from=None,
        grouped_id=777,
        reactions=None,
        edit_date=None,
        action=None,
    )

    result = extract_message_metadata(message, file_name="offer.pdf")

    assert result["visible_urls"] == ["example.com"]
    assert result["hidden_urls"] == [
        "https://secret.example/contract?id=42",
        "https://button.example/file",
    ]
    assert result["buttons"] == [
        {"row": 0, "column": 0, "text": "Открыть", "url": "https://button.example/file"}
    ]
    assert result["album_id"] == 777
    assert "offer.pdf" in result["searchable_metadata"]
    assert "secret.example" in result["searchable_metadata"]


def test_extracts_reply_forward_reactions_and_web_preview():
    message = SimpleNamespace(
        message="Ответ",
        entities=None,
        buttons=None,
        media=SimpleNamespace(
            webpage=SimpleNamespace(
                url="https://waiwai.is/page",
                display_url="waiwai.is/page",
                site_name="WAI",
                title="Page title",
                description="Page description",
            )
        ),
        reply_to=SimpleNamespace(reply_to_msg_id=10, reply_to_top_id=8),
        fwd_from=SimpleNamespace(
            from_name="Original author",
            date=None,
            channel_post=12,
            post_author="Editor",
            from_id=SimpleNamespace(user_id=99),
            saved_from_peer=None,
            saved_from_msg_id=None,
        ),
        grouped_id=None,
        reactions=SimpleNamespace(
            results=[
                SimpleNamespace(
                    reaction=SimpleNamespace(emoticon="👍"),
                    count=3,
                    chosen_order=0,
                )
            ]
        ),
        edit_date=None,
        action=None,
    )

    result = extract_message_metadata(message)

    assert result["reply_to_message_id"] == 10
    assert result["thread_id"] == 8
    assert result["forward_origin"]["from_name"] == "Original author"
    assert result["forward_origin"]["from_peer"] == {"user_id": 99}
    assert result["reactions"] == [{"reaction": "👍", "count": 3, "chosen_order": 0}]
    assert result["webpage_preview"]["url"] == "https://waiwai.is/page"
