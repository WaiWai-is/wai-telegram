"""Resumable search-vector backfill and online PostgreSQL index creation."""

import argparse
import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import text

from app.core.database import get_db_context, get_engine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OnlineIndex:
    name: str
    create_sql: str


ONLINE_INDEXES = (
    OnlineIndex(
        "ix_telegram_messages_search_vector_gin",
        "CREATE INDEX CONCURRENTLY ix_telegram_messages_search_vector_gin "
        "ON telegram_messages USING GIN (search_vector)",
    ),
    OnlineIndex(
        "ix_message_content_chunks_search_vector_gin",
        "CREATE INDEX CONCURRENTLY ix_message_content_chunks_search_vector_gin "
        "ON message_content_chunks USING GIN (search_vector)",
    ),
    OnlineIndex(
        "ix_telegram_messages_media_file_name_trgm",
        "CREATE INDEX CONCURRENTLY ix_telegram_messages_media_file_name_trgm "
        "ON telegram_messages USING GIN (media_file_name gin_trgm_ops) "
        "WHERE media_file_name IS NOT NULL",
    ),
    OnlineIndex(
        "ix_telegram_messages_searchable_metadata_trgm",
        "CREATE INDEX CONCURRENTLY ix_telegram_messages_searchable_metadata_trgm "
        "ON telegram_messages USING GIN (searchable_metadata gin_trgm_ops) "
        "WHERE searchable_metadata IS NOT NULL",
    ),
)


async def _backfill_table(table: str, *, batch_size: int) -> int:
    if table not in {"telegram_messages", "message_content_chunks"}:
        raise ValueError("Unsupported search backfill table")
    trigger_column = "searchable_metadata" if table == "telegram_messages" else "text"
    total = 0
    while True:
        async with get_db_context() as db:
            updated = (
                await db.execute(
                    text(
                        f"""
                        WITH batch AS (
                            SELECT id FROM {table}
                            WHERE search_vector IS NULL
                            ORDER BY id
                            LIMIT :batch_size
                            FOR UPDATE SKIP LOCKED
                        )
                        UPDATE {table} target
                        SET {trigger_column} = target.{trigger_column}
                        FROM batch
                        WHERE target.id = batch.id
                        RETURNING target.id
                        """
                    ),
                    {"batch_size": batch_size},
                )
            ).all()
        count = len(updated)
        total += count
        if count:
            logger.info("Backfilled %s rows in %s", total, table)
        async with get_db_context() as db:
            rows_remain = bool(
                (
                    await db.execute(
                        text(
                            f"SELECT EXISTS (SELECT 1 FROM {table} "
                            "WHERE search_vector IS NULL)"
                        )
                    )
                ).scalar_one()
            )
        if not rows_remain:
            return total
        if not count:
            # A concurrent writer owns the remaining SKIP LOCKED rows. Do not
            # incorrectly declare the backfill complete.
            await asyncio.sleep(0.25)


async def backfill_search_vectors(*, batch_size: int = 5_000) -> dict[str, int]:
    return {
        "telegram_messages": await _backfill_table(
            "telegram_messages", batch_size=batch_size
        ),
        "message_content_chunks": await _backfill_table(
            "message_content_chunks", batch_size=batch_size
        ),
    }


async def create_online_search_indexes() -> None:
    engine = get_engine()
    async with engine.connect() as raw_connection:
        connection = await raw_connection.execution_options(
            isolation_level="AUTOCOMMIT"
        )
        for index in ONLINE_INDEXES:
            state = (
                await connection.execute(
                    text(
                        "SELECT i.indisvalid "
                        "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                        "WHERE c.relname = :name "
                        "AND c.relnamespace = current_schema()::regnamespace"
                    ),
                    {"name": index.name},
                )
            ).scalar_one_or_none()
            if state is False:
                await connection.execute(
                    text(f'DROP INDEX CONCURRENTLY "{index.name}"')
                )
            if state is not True:
                await connection.execute(text(index.create_sql))
            valid = (
                await connection.execute(
                    text(
                        "SELECT i.indisvalid "
                        "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                        "WHERE c.relname = :name "
                        "AND c.relnamespace = current_schema()::regnamespace"
                    ),
                    {"name": index.name},
                )
            ).scalar_one_or_none()
            if valid is not True:
                raise RuntimeError(f"Online index is not valid: {index.name}")
            logger.info("Online search index is valid: %s", index.name)


async def _run(args: argparse.Namespace) -> None:
    if not args.indexes_only:
        counts = await backfill_search_vectors(batch_size=args.batch_size)
        logger.info("Search vector backfill complete: %s", counts)
    if not args.backfill_only:
        await create_online_search_indexes()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=5_000)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--backfill-only", action="store_true")
    mode.add_argument("--indexes-only", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
