"""Smoke tests to verify the test infrastructure works."""

from app.models.user import User
from sqlalchemy import select

from tests.factories import (
    TelegramChatFactory,
    TelegramMessageFactory,
    TelegramSessionFactory,
    UserFactory,
)


async def test_engine_creates_tables(async_engine):
    """Verify SQLite in-memory engine can create all tables."""
    # If we get here, create_all succeeded
    assert async_engine is not None


async def test_db_session_works(db_session):
    """Verify DB session can perform basic operations."""
    result = await db_session.execute(select(User))
    users = result.scalars().all()
    assert users == []


async def test_test_user_fixture(db_session, test_user):
    """Verify the test_user fixture creates a user in the DB."""
    result = await db_session.execute(
        select(User).where(User.email == "test@example.com")
    )
    user = result.scalar_one()
    assert user.id == test_user.id


async def test_client_fixture(client):
    """Verify the httpx client can make requests."""
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


async def test_auth_client_fixture(auth_client):
    """Verify the authenticated client has auth headers."""
    assert "Authorization" in auth_client.headers


async def test_user_factory(db_session):
    """Verify UserFactory creates valid user objects."""
    user = UserFactory.create()
    db_session.add(user)
    await db_session.flush()
    result = await db_session.execute(select(User).where(User.id == user.id))
    assert result.scalar_one().email == user.email


async def test_chat_factory(db_session):
    """Verify TelegramChatFactory creates valid chat objects."""
    user = UserFactory.create()
    db_session.add(user)
    await db_session.flush()
    chat = TelegramChatFactory.create(user_id=user.id)
    db_session.add(chat)
    await db_session.flush()
    assert chat.title.startswith("Chat ")


async def test_message_factory(db_session):
    """Verify TelegramMessageFactory creates valid message objects."""
    user = UserFactory.create()
    db_session.add(user)
    await db_session.flush()
    chat = TelegramChatFactory.create(user_id=user.id)
    db_session.add(chat)
    await db_session.flush()
    msg = TelegramMessageFactory.create(chat_id=chat.id)
    db_session.add(msg)
    await db_session.flush()
    assert msg.text.startswith("Test message ")


async def test_session_factory(db_session):
    """Verify TelegramSessionFactory creates valid session objects."""
    user = UserFactory.create()
    db_session.add(user)
    await db_session.flush()
    session = TelegramSessionFactory.create(user_id=user.id)
    db_session.add(session)
    await db_session.flush()
    assert session.phone_number == "+1234567890"


async def test_fakeredis_fixture(fake_redis):
    """Verify fakeredis works."""
    fake_redis.set("key", "value")
    assert fake_redis.get("key") == b"value"


async def test_fakeredis_decoded_fixture(fake_redis_decoded):
    """Verify fakeredis with decode_responses works."""
    fake_redis_decoded.set("key", "value")
    assert fake_redis_decoded.get("key") == "value"
