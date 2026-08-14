"""PostgreSQL-only contract checks for migrations and hybrid retrieval."""

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.chat import ChatType, TelegramChat
from app.models.media import MediaObject
from app.models.message import MessageContentChunk, MessageRevision, TelegramMessage
from app.models.metadata import MetadataReconciliationCheckpoint
from app.models.user import User
from app.schemas.search import SearchRequest
from app.services.search_service import semantic_search
from app.services.metadata_reconciliation import _save_metadata_batch


@pytest.mark.skipif(
    not os.environ.get("POSTGRES_CONTRACT_DATABASE_URL"),
    reason="POSTGRES_CONTRACT_DATABASE_URL is not configured",
)
async def test_hybrid_search_uses_fts_trigram_and_pgvector_after_migrations():
    engine = create_async_engine(os.environ["POSTGRES_CONTRACT_DATABASE_URL"])
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    user_id = uuid4()
    embedding = [0.0] * 1536
    embedding[0] = 1.0

    try:
        async with session_factory() as db, db.begin():
            user = User(
                id=user_id,
                email=f"postgres-contract-{user_id}@example.com",
                password_hash="not-used",
                is_active=False,
            )
            chat = TelegramChat(
                user_id=user_id,
                telegram_chat_id=9_001,
                chat_type=ChatType.PRIVATE,
                title="Postgres contract",
            )
            db.add_all([user, chat])
            await db.flush()
            message = TelegramMessage(
                chat_id=chat.id,
                telegram_message_id=9_002,
                text="Quarterly roadmap",
                has_media=True,
                media_type="document",
                media_file_name="exact-roadmap-2026.pdf",
                content_text="многоязычный текст " * 100_000,
                searchable_metadata="https://hidden.example/private-target",
                hidden_urls=["https://hidden.example/private-target"],
                embedding=embedding,
                sent_at=datetime.now(UTC),
            )
            db.add(message)
            await db.flush()
            vector_size = (
                await db.execute(
                    text(
                        "SELECT octet_length(search_vector::text) "
                        "FROM telegram_messages WHERE id = :message_id"
                    ),
                    {"message_id": message.id},
                )
            ).scalar_one()
            assert vector_size > 0
            db.add(
                MessageContentChunk(
                    message_id=message.id,
                    chunk_index=0,
                    text="The launch phrase is violet telescope.",
                    embedding=embedding,
                )
            )
            await db.flush()

            with patch(
                "app.services.search_service.generate_query_embedding",
                new_callable=AsyncMock,
            ) as exact_embedding:
                exact_response = await semantic_search(
                    db,
                    user_id,
                    SearchRequest(
                        query="violet telescope",
                        mode="exact",
                        chat_types=["private"],
                    ),
                )
                filtered_response = await semantic_search(
                    db,
                    user_id,
                    SearchRequest(
                        query="violet telescope",
                        mode="exact",
                        chat_types=["group", "supergroup"],
                    ),
                )

            exact_embedding.assert_not_awaited()
            assert [item.telegram_message_id for item in exact_response.results] == [
                9_002
            ]
            assert filtered_response.results == []

            with patch(
                "app.services.search_service.generate_query_embedding",
                new_callable=AsyncMock,
                return_value=embedding,
            ):
                for query in (
                    "exact-roadmap-2026.pdf",
                    "https://hidden.example/private-target",
                    "violet telescope",
                ):
                    response = await semantic_search(
                        db,
                        user_id,
                        SearchRequest(query=query, limit=5),
                    )
                    assert [item.telegram_message_id for item in response.results] == [
                        9_002
                    ]

                pagination_messages = []
                for offset in range(3):
                    pagination_message = TelegramMessage(
                        chat_id=chat.id,
                        telegram_message_id=9_010 + offset,
                        text="pagination-uniform-token",
                        has_media=False,
                        embedding=embedding,
                        sent_at=datetime.now(UTC) - timedelta(minutes=offset),
                    )
                    db.add(pagination_message)
                    pagination_messages.append(pagination_message)
                await db.flush()

                seen: list[int] = []
                cursor = None
                for _page_number in range(10):
                    page = await semantic_search(
                        db,
                        user_id,
                        SearchRequest(
                            query="pagination-uniform-token",
                            limit=1,
                            cursor=cursor,
                        ),
                    )
                    assert len(page.results) == 1
                    seen.append(page.results[0].telegram_message_id)
                    cursor = page.next_cursor
                    if not page.has_more:
                        break
                    assert cursor is not None
                else:
                    pytest.fail("Search pagination did not terminate")
                assert {9_010, 9_011, 9_012}.issubset(seen)
                assert len(set(seen)) == len(seen)

            checkpoint = MetadataReconciliationCheckpoint(
                user_id=user_id,
                chat_id=chat.id,
            )
            db.add(checkpoint)
            await db.flush()

            @asynccontextmanager
            async def same_session():
                yield db

            reconciled_values = {
                "chat_id": chat.id,
                "telegram_message_id": message.telegram_message_id,
                "text": "Quarterly roadmap, edited",
                "has_media": True,
                "media_type": "document",
                "media_file_name": "exact-roadmap-2026.pdf",
                "media_mime_type": "application/pdf",
                "media_file_size": 123,
                "media_duration_seconds": None,
                "sender_id": 42,
                "sender_name": "Owner",
                "is_outgoing": True,
                "sent_at": message.sent_at,
                "entities": [{"type": "MessageEntityBold"}],
                "visible_urls": [],
                "hidden_urls": ["https://hidden.example/private-target"],
                "buttons": [],
                "webpage_preview": None,
                "reply_to_message_id": None,
                "thread_id": None,
                "forward_origin": None,
                "album_id": None,
                "reactions": [],
                "edited_at": datetime.now(UTC),
                "poll": None,
                "contact": None,
                "location": None,
                "service_event": None,
                "searchable_metadata": "exact-roadmap-2026.pdf",
            }
            with (
                patch(
                    "app.services.metadata_reconciliation.get_db_context",
                    side_effect=same_session,
                ),
                patch(
                    "app.services.metadata_reconciliation.is_user_active",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
            ):
                assert (
                    await _save_metadata_batch(
                        user_id,
                        checkpoint.id,
                        [reconciled_values],
                        message.telegram_message_id,
                    )
                    == 1
                )

            revision = (
                await db.execute(
                    select(MessageRevision).where(
                        MessageRevision.message_id == message.id
                    )
                )
            ).scalar_one()
            assert revision.revision == 1
            assert revision.text == "Quarterly roadmap"
            await db.refresh(message)
            assert message.text == "Quarterly roadmap, edited"
            await db.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("POSTGRES_CONTRACT_DATABASE_URL"),
    reason="POSTGRES_CONTRACT_DATABASE_URL is not configured",
)
async def test_postgres_enforces_single_owner_and_media_integrity_constraints():
    engine = create_async_engine(os.environ["POSTGRES_CONTRACT_DATABASE_URL"])
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as db:
        transaction = await db.begin()
        try:
            await db.execute(update(User).values(is_active=False))
            owner = User(
                email=f"owner-contract-{uuid4()}@example.com",
                password_hash="not-used",
                is_active=True,
            )
            archived = User(
                email=f"archive-contract-{uuid4()}@example.com",
                password_hash="not-used",
                is_active=False,
            )
            db.add_all([owner, archived])
            await db.flush()

            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    db.add(
                        User(
                            email=f"second-active-{uuid4()}@example.com",
                            password_hash="not-used",
                            is_active=True,
                        )
                    )
                    await db.flush()

            chat = TelegramChat(
                user_id=owner.id,
                telegram_chat_id=9_100,
                chat_type=ChatType.PRIVATE,
                title="Owner constraint",
            )
            db.add(chat)
            await db.flush()
            message = TelegramMessage(
                chat_id=chat.id,
                telegram_message_id=9_101,
                has_media=True,
                media_type="document",
                sent_at=datetime.now(UTC),
            )
            db.add(message)
            await db.flush()

            with pytest.raises(DBAPIError, match="does not own message"):
                async with db.begin_nested():
                    db.add(
                        MediaObject(
                            user_id=archived.id,
                            message_id=message.id,
                            cache_key="a" * 64,
                        )
                    )
                    await db.flush()

            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    db.add(
                        MediaObject(
                            user_id=owner.id,
                            message_id=message.id,
                            cache_key="b" * 64,
                            status="invalid-status",
                            byte_offset=-1,
                        )
                    )
                    await db.flush()
        finally:
            await transaction.rollback()
            await engine.dispose()
