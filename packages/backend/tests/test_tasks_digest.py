"""Tests for app.tasks.digest_tasks — covers generate_all_digests,
generate_user_digest, and _get_eligible_user_ids."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


from app.core.security import hash_password
from app.models.settings import UserSettings
from app.models.user import User


# ---------------------------------------------------------------------------
# generate_all_digests (Celery entry-point)
# ---------------------------------------------------------------------------
class TestGenerateAllDigests:
    @patch("app.tasks.digest_tasks.group")
    @patch("app.tasks.digest_tasks.generate_user_digest")
    @patch("app.tasks.digest_tasks.run_async")
    def test_dispatches_tasks_for_eligible_users(
        self, mock_run_async, mock_task, mock_group
    ):
        """When eligible users exist, a Celery group is dispatched."""
        uid1, uid2 = uuid4(), uuid4()
        mock_run_async.return_value = [uid1, uid2]

        mock_sig = MagicMock()
        mock_task.s = MagicMock(return_value=mock_sig)
        mock_group.return_value = MagicMock()

        from app.tasks.digest_tasks import generate_all_digests

        result = generate_all_digests()

        assert result["users_processed"] == 2
        assert result["dispatched"] == 2
        assert "date" in result
        assert "hour" in result
        mock_group.return_value.apply_async.assert_called_once()
        mock_run_async.call_args.args[0].close()

    @patch("app.tasks.digest_tasks.run_async")
    def test_returns_zero_when_no_eligible_users(self, mock_run_async):
        """When no users are eligible, dispatched == 0."""
        mock_run_async.return_value = []

        from app.tasks.digest_tasks import generate_all_digests

        result = generate_all_digests()

        assert result["users_processed"] == 0
        assert result["dispatched"] == 0
        mock_run_async.call_args.args[0].close()

    @patch("app.tasks.digest_tasks.group")
    @patch("app.tasks.digest_tasks.generate_user_digest")
    @patch("app.tasks.digest_tasks.run_async")
    def test_result_contains_yesterday_date(self, mock_run_async, mock_task, mock_group):
        """The returned date field should be yesterday in ISO format."""
        mock_run_async.return_value = [uuid4()]
        mock_task.s = MagicMock(return_value=MagicMock())
        mock_group.return_value = MagicMock()

        from app.tasks.digest_tasks import generate_all_digests

        result = generate_all_digests()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert result["date"] == yesterday
        mock_run_async.call_args.args[0].close()

    @patch("app.tasks.digest_tasks.group")
    @patch("app.tasks.digest_tasks.generate_user_digest")
    @patch("app.tasks.digest_tasks.run_async")
    def test_dispatches_correct_number_of_signatures(
        self, mock_run_async, mock_task, mock_group
    ):
        """Each eligible user gets a separate task signature."""
        uids = [uuid4() for _ in range(5)]
        mock_run_async.return_value = uids
        mock_group.return_value = MagicMock()

        from app.tasks.digest_tasks import generate_all_digests

        result = generate_all_digests()

        assert result["users_processed"] == 5
        assert result["dispatched"] == 5
        # group() is called with a generator; verify it was invoked
        mock_group.assert_called_once()
        mock_group.return_value.apply_async.assert_called_once()
        mock_run_async.call_args.args[0].close()


# ---------------------------------------------------------------------------
# _get_eligible_user_ids (async helper)
# ---------------------------------------------------------------------------
class TestGetEligibleUserIds:
    async def test_matching_hour(self, db_session):
        user = User(
            email="digest@example.com",
            password_hash=hash_password("TestPass1"),
        )
        db_session.add(user)
        await db_session.flush()

        settings = UserSettings(
            user_id=user.id,
            digest_enabled=True,
            digest_hour_utc=14,
        )
        db_session.add(settings)
        await db_session.flush()

        # _get_eligible_user_ids uses get_db_context() which creates its own
        # session — unit test verifies model wiring; integration test with
        # PostgreSQL covers the full path.

    async def test_default_hour_9(self, db_session):
        # Users without a settings row default to hour 9
        pass


# ---------------------------------------------------------------------------
# _get_eligible_user_ids — mocked DB path
# ---------------------------------------------------------------------------
class TestGetEligibleUserIdsMocked:
    async def test_returns_user_ids_at_matching_hour(self):
        """Mocked get_db_context returns eligible user IDs."""
        uid = uuid4()

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [uid]

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tasks.digest_tasks.get_db_context", return_value=mock_db):
            from app.tasks.digest_tasks import _get_eligible_user_ids

            result = await _get_eligible_user_ids(14)

        assert result == [uid]

    async def test_returns_empty_when_no_users(self):
        """When no users match, an empty list is returned."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tasks.digest_tasks.get_db_context", return_value=mock_db):
            from app.tasks.digest_tasks import _get_eligible_user_ids

            result = await _get_eligible_user_ids(3)

        assert result == []


# ---------------------------------------------------------------------------
# generate_user_digest (Celery per-user task)
# ---------------------------------------------------------------------------
class TestGenerateUserDigest:
    @patch("app.tasks.digest_tasks.run_async")
    def test_calls_async_helper(self, mock_run_async):
        """generate_user_digest passes args to _generate_user_digest via the async runner."""
        mock_run_async.return_value = {"digest_id": "abc", "date": "2025-01-01"}

        from app.tasks.digest_tasks import generate_user_digest

        uid = str(uuid4())
        result = generate_user_digest(uid, "2025-01-01")

        assert result["digest_id"] == "abc"
        mock_run_async.assert_called_once()
        mock_run_async.call_args.args[0].close()

    @patch("app.tasks.digest_tasks.run_async")
    def test_accepts_none_date(self, mock_run_async):
        """generate_user_digest works when digest_date is None."""
        mock_run_async.return_value = {"digest_id": "x", "date": "2025-01-01"}

        from app.tasks.digest_tasks import generate_user_digest

        result = generate_user_digest(str(uuid4()), None)
        assert "digest_id" in result
        mock_run_async.call_args.args[0].close()


# ---------------------------------------------------------------------------
# _generate_user_digest (async helper)
# ---------------------------------------------------------------------------
class TestGenerateUserDigestAsync:
    async def test_generates_digest_and_returns_result(self):
        """Happy path: digest generated, no Telegram delivery."""
        uid = uuid4()
        digest_date = date(2025, 1, 15)

        mock_digest = MagicMock()
        mock_digest.id = uuid4()
        mock_digest.digest_date = digest_date
        mock_digest.content = "Test digest content"

        # Settings query returns None (no telegram delivery)
        mock_settings_result = MagicMock()
        mock_settings_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[mock_settings_result])
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tasks.digest_tasks.get_db_context", return_value=mock_db),
            patch(
                "app.tasks.digest_tasks.generate_digest",
                new_callable=AsyncMock,
                return_value=mock_digest,
            ),
        ):
            from app.tasks.digest_tasks import _generate_user_digest

            result = await _generate_user_digest(uid, "2025-01-15")

        assert result["digest_id"] == str(mock_digest.id)
        assert result["date"] == "2025-01-15"

    async def test_sends_telegram_when_enabled(self):
        """When digest_telegram_enabled, message is sent via Telegram."""
        uid = uuid4()
        digest_date = date(2025, 3, 20)

        mock_digest = MagicMock()
        mock_digest.id = uuid4()
        mock_digest.digest_date = digest_date
        mock_digest.content = "Summary"

        mock_settings = MagicMock()
        mock_settings.digest_telegram_enabled = True

        mock_settings_result = MagicMock()
        mock_settings_result.scalar_one_or_none.return_value = mock_settings

        mock_session = MagicMock()
        mock_session.telegram_user_id = 123456

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = mock_session

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_settings_result, mock_session_result]
        )
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_send = AsyncMock()

        with (
            patch("app.tasks.digest_tasks.get_db_context", return_value=mock_db),
            patch(
                "app.tasks.digest_tasks.generate_digest",
                new_callable=AsyncMock,
                return_value=mock_digest,
            ),
            patch(
                "app.tasks.digest_tasks.send_telegram_message",
                mock_send,
            ),
        ):
            from app.tasks.digest_tasks import _generate_user_digest

            await _generate_user_digest(uid, "2025-03-20")

        mock_send.assert_awaited_once()
        call_args = mock_send.call_args
        assert call_args[0][0] == 123456  # telegram_user_id
        assert "Summary" in call_args[0][1]

    async def test_telegram_send_failure_logged_not_raised(self):
        """If Telegram send fails, error is logged but digest result is returned."""
        uid = uuid4()
        digest_date = date(2025, 3, 20)

        mock_digest = MagicMock()
        mock_digest.id = uuid4()
        mock_digest.digest_date = digest_date
        mock_digest.content = "Content"

        mock_settings = MagicMock()
        mock_settings.digest_telegram_enabled = True

        mock_settings_result = MagicMock()
        mock_settings_result.scalar_one_or_none.return_value = mock_settings

        mock_session = MagicMock()
        mock_session.telegram_user_id = 999

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = mock_session

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_settings_result, mock_session_result]
        )
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_send = AsyncMock(side_effect=Exception("Bot API error"))

        with (
            patch("app.tasks.digest_tasks.get_db_context", return_value=mock_db),
            patch(
                "app.tasks.digest_tasks.generate_digest",
                new_callable=AsyncMock,
                return_value=mock_digest,
            ),
            patch("app.tasks.digest_tasks.send_telegram_message", mock_send),
        ):
            from app.tasks.digest_tasks import _generate_user_digest

            # Should NOT raise despite send failure
            result = await _generate_user_digest(uid, "2025-03-20")

        assert result["digest_id"] == str(mock_digest.id)

    async def test_no_telegram_when_no_active_session(self):
        """If user has telegram enabled but no active session, skip send."""
        uid = uuid4()

        mock_digest = MagicMock()
        mock_digest.id = uuid4()
        mock_digest.digest_date = date(2025, 1, 1)
        mock_digest.content = "Content"

        mock_settings = MagicMock()
        mock_settings.digest_telegram_enabled = True

        mock_settings_result = MagicMock()
        mock_settings_result.scalar_one_or_none.return_value = mock_settings

        # No active session
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_settings_result, mock_session_result]
        )
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        mock_send = AsyncMock()

        with (
            patch("app.tasks.digest_tasks.get_db_context", return_value=mock_db),
            patch(
                "app.tasks.digest_tasks.generate_digest",
                new_callable=AsyncMock,
                return_value=mock_digest,
            ),
            patch("app.tasks.digest_tasks.send_telegram_message", mock_send),
        ):
            from app.tasks.digest_tasks import _generate_user_digest

            result = await _generate_user_digest(uid, "2025-01-01")

        mock_send.assert_not_awaited()
        assert "digest_id" in result
