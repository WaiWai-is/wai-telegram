from app.cli.search_indexes import ONLINE_INDEXES
from app.models.message import MessageContentChunk, TelegramMessage


def test_online_search_index_names_match_declared_model_indexes() -> None:
    declared_names = {
        index.name
        for table in (TelegramMessage.__table__, MessageContentChunk.__table__)
        for index in table.indexes
    }
    online_names = {index.name for index in ONLINE_INDEXES}

    assert online_names <= declared_names
