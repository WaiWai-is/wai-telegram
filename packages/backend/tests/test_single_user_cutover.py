from argparse import Namespace
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.api_key import ApiKey
from app.models.chat import ChatType, TelegramChat
from app.models.digital_agent import DigitalAgent
from app.models.message import TelegramMessage
from app.models.session import TelegramSession
from app.models.settings import UserSettings
from app.models.sync_job import SyncJob, SyncStatus
from app.services.single_user_cutover import (
    ArchivedSessionCredential,
    CutoverResult,
    OwnerEvidence,
    OwnerEvidenceError,
    apply_single_user_cutover,
    collect_owner_evidence,
)
from tests.factories import ApiKeyFactory, UserFactory


async def _seed_cutover(db_session):
    now = datetime.now(UTC)
    owner = UserFactory.create(email="owner@example.com", is_active=False)
    archived = UserFactory.create(email="archive@example.com", is_active=False)
    db_session.add_all([owner, archived])
    await db_session.flush()

    db_session.add_all(
        [
            TelegramSession(
                user_id=owner.id,
                phone_number="+10000000001",
                session_string="owner-secret",
                telegram_user_id=111,
                is_active=True,
            ),
            TelegramSession(
                user_id=archived.id,
                phone_number="+10000000002",
                session_string="archive-secret",
                telegram_user_id=222,
                is_active=False,
            ),
            ApiKeyFactory.create(
                user_id=owner.id,
                raw_key="wai_owner_evidence_abcdefghijklmnopqrstuvwxyz",
                last_used_at=now - timedelta(minutes=2),
            ),
            ApiKeyFactory.create(
                user_id=archived.id,
                raw_key="wai_archive_key_abcdefghijklmnopqrstuvwxyz",
                last_used_at=now - timedelta(days=2),
            ),
            UserSettings(
                user_id=archived.id,
                realtime_sync_enabled=True,
                digest_enabled=True,
                digest_telegram_enabled=True,
            ),
            SyncJob(user_id=archived.id, status=SyncStatus.PENDING),
            DigitalAgent(
                user_id=archived.id,
                telegram_chat_id=222,
                name="Archive agent",
                description="archive",
                system_prompt="archive",
                tools="search_messages",
                schedule_type="cron",
                cron_expression="0 9 * * *",
                status="active",
            ),
        ]
    )
    await db_session.flush()

    owner_chat = TelegramChat(
        user_id=owner.id,
        telegram_chat_id=1001,
        chat_type=ChatType.PRIVATE,
        title="Owner",
    )
    archive_chat = TelegramChat(
        user_id=archived.id,
        telegram_chat_id=1002,
        chat_type=ChatType.PRIVATE,
        title="Archive",
    )
    db_session.add_all([owner_chat, archive_chat])
    await db_session.flush()
    db_session.add_all(
        [
            TelegramMessage(
                chat_id=owner_chat.id,
                telegram_message_id=index,
                text=f"owner {index}",
                has_media=False,
                is_outgoing=False,
                sent_at=now,
            )
            for index in range(1, 4)
        ]
        + [
            TelegramMessage(
                chat_id=archive_chat.id,
                telegram_message_id=1,
                text="archive",
                has_media=False,
                is_outgoing=False,
                sent_at=now,
            )
        ]
    )
    await db_session.flush()
    return owner, archived, now


class TestOwnerEvidence:
    async def test_three_signals_must_agree(self, db_session):
        owner, _archived, now = await _seed_cutover(db_session)

        evidence = await collect_owner_evidence(
            db_session,
            expected_owner_user_id=owner.id,
            now=now,
        )

        assert evidence.owner_user_id == owner.id
        assert evidence.owner_message_count == 3
        assert evidence.total_users == 2

    async def test_expected_owner_mismatch_stops_without_changes(self, db_session):
        _owner, _archived, now = await _seed_cutover(db_session)

        with pytest.raises(OwnerEvidenceError, match="ambiguous"):
            await collect_owner_evidence(
                db_session,
                expected_owner_user_id=uuid4(),
                now=now,
            )


class TestCutoverTransaction:
    async def test_deactivates_access_and_preserves_archive_data(self, db_session):
        owner, archived, now = await _seed_cutover(db_session)
        evidence = await collect_owner_evidence(
            db_session,
            expected_owner_user_id=owner.id,
            now=now,
        )
        messages_before = (
            await db_session.execute(select(func.count()).select_from(TelegramMessage))
        ).scalar_one()

        result = await apply_single_user_cutover(db_session, evidence, now=now)

        await db_session.refresh(owner)
        await db_session.refresh(archived)
        assert owner.is_active is True
        assert archived.is_active is False
        assert archived.deactivated_at.replace(tzinfo=UTC) == now

        archived_key = (
            await db_session.execute(
                select(ApiKey).where(ApiKey.user_id == archived.id)
            )
        ).scalar_one()
        archived_session = (
            await db_session.execute(
                select(TelegramSession).where(TelegramSession.user_id == archived.id)
            )
        ).scalar_one()
        archived_settings = (
            await db_session.execute(
                select(UserSettings).where(UserSettings.user_id == archived.id)
            )
        ).scalar_one()
        archived_job = (
            await db_session.execute(
                select(SyncJob).where(SyncJob.user_id == archived.id)
            )
        ).scalar_one()
        archived_agent = (
            await db_session.execute(
                select(DigitalAgent).where(DigitalAgent.user_id == archived.id)
            )
        ).scalar_one()
        messages_after = (
            await db_session.execute(select(func.count()).select_from(TelegramMessage))
        ).scalar_one()

        assert archived_key.is_active is False
        assert archived_session.is_active is False
        assert archived_session.session_string == ""
        assert archived_settings.realtime_sync_enabled is False
        assert archived_settings.digest_enabled is False
        assert archived_settings.digest_telegram_enabled is False
        assert archived_job.status == SyncStatus.CANCELLED
        assert archived_agent.status == "paused"
        assert messages_after == messages_before == 4
        assert result.archived_message_count == 1
        assert result.users_deactivated == 1


class TestCutoverCLI:
    async def test_dry_run_has_no_external_or_database_mutations(self, capsys):
        from app.cli.single_user_cutover import _run

        owner_id = uuid4()
        evidence = OwnerEvidence(
            owner_user_id=owner_id,
            active_session_users=(owner_id,),
            recent_api_key_users=(owner_id,),
            top_message_volume_users=(owner_id,),
            owner_chat_count=2,
            owner_message_count=3,
            total_users=2,
        )
        db = SimpleNamespace()

        @asynccontextmanager
        async def session_factory():
            yield db

        with (
            patch(
                "app.cli.single_user_cutover.get_settings",
                return_value=SimpleNamespace(
                    owner_user_id=owner_id,
                    redis_url="redis://test",
                ),
            ),
            patch(
                "app.cli.single_user_cutover.get_session_factory",
                return_value=session_factory,
            ),
            patch(
                "app.cli.single_user_cutover.collect_owner_evidence",
                new=AsyncMock(return_value=evidence),
            ),
            patch(
                "app.cli.single_user_cutover.collect_archived_session_credentials",
                new=AsyncMock(return_value=()),
            ),
            patch(
                "app.cli.single_user_cutover.revoke_archived_telegram_sessions",
                new=AsyncMock(),
            ) as revoke,
            patch(
                "app.cli.single_user_cutover.apply_single_user_cutover",
                new=AsyncMock(),
            ) as apply,
        ):
            await _run(
                Namespace(
                    apply=False,
                    confirm_owner=None,
                    recent_key_minutes=60,
                )
            )

        assert '"mode": "dry-run"' in capsys.readouterr().out
        revoke.assert_not_awaited()
        apply.assert_not_awaited()

    async def test_apply_revokes_before_commit_then_validates_and_purges(self):
        from app.cli.single_user_cutover import _run

        owner_id = uuid4()
        archived_id = uuid4()
        evidence = OwnerEvidence(
            owner_user_id=owner_id,
            active_session_users=(owner_id,),
            recent_api_key_users=(owner_id,),
            top_message_volume_users=(owner_id,),
            owner_chat_count=2,
            owner_message_count=3,
            total_users=2,
        )
        result = CutoverResult(
            owner_user_id=owner_id,
            users_deactivated=1,
            api_keys_disabled=1,
            telegram_sessions_wiped=1,
            settings_disabled=1,
            sync_jobs_cancelled=0,
            agents_paused=0,
            archived_chat_count=1,
            archived_message_count=1,
            cancelled_job_ids=(),
            deactivated_user_ids=(archived_id,),
        )
        credentials = (ArchivedSessionCredential(uuid4(), "encrypted"),)
        db = SimpleNamespace(commit=AsyncMock())

        @asynccontextmanager
        async def session_factory():
            yield db

        sequence = MagicMock()
        revoke = AsyncMock(return_value=1)
        apply = AsyncMock(return_value=result)
        sequence.attach_mock(revoke, "revoke")
        sequence.attach_mock(apply, "apply")
        with (
            patch(
                "app.cli.single_user_cutover.get_settings",
                return_value=SimpleNamespace(
                    owner_user_id=owner_id,
                    redis_url="redis://test",
                ),
            ),
            patch(
                "app.cli.single_user_cutover.get_session_factory",
                return_value=session_factory,
            ),
            patch(
                "app.cli.single_user_cutover.collect_owner_evidence",
                new=AsyncMock(return_value=evidence),
            ),
            patch(
                "app.cli.single_user_cutover.collect_archived_session_credentials",
                new=AsyncMock(return_value=credentials),
            ),
            patch(
                "app.cli.single_user_cutover.revoke_archived_telegram_sessions",
                new=revoke,
            ),
            patch(
                "app.cli.single_user_cutover.apply_single_user_cutover",
                new=apply,
            ),
            patch(
                "app.cli.single_user_cutover.validate_active_owner",
                new=AsyncMock(),
            ) as validate,
            patch(
                "app.cli.single_user_cutover._purge_runtime_state_with_retries",
                new=AsyncMock(return_value=4),
            ) as purge,
        ):
            await _run(
                Namespace(
                    apply=True,
                    confirm_owner=owner_id,
                    recent_key_minutes=60,
                )
            )

        assert [call[0] for call in sequence.mock_calls] == ["revoke", "apply"]
        db.commit.assert_awaited_once()
        validate.assert_awaited_once_with(db, owner_id)
        purge.assert_awaited_once_with("redis://test", result)

    async def test_redis_purge_retries_after_transient_failures(self):
        from app.cli.single_user_cutover import _purge_runtime_state_with_retries

        purge = AsyncMock(side_effect=[RuntimeError("one"), RuntimeError("two"), 7])
        with (
            patch(
                "app.cli.single_user_cutover.purge_deactivated_runtime_state",
                new=purge,
            ),
            patch(
                "app.cli.single_user_cutover.asyncio.sleep", new=AsyncMock()
            ) as sleep,
        ):
            assert (
                await _purge_runtime_state_with_retries("redis://test", object()) == 7
            )

        assert sleep.await_args_list[0].args == (1,)
        assert sleep.await_args_list[1].args == (5,)
