import json
from uuid import uuid4

from app.tasks.sync_tasks import DistributedLock


class FakeRedis:
    """Minimal fake Redis for testing DistributedLock."""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        if ex:
            self.ttls[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def setex(self, key: str, ttl: int, value: str) -> bool:
        self.data[key] = str(value)
        self.ttls[key] = ttl
        return True

    def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                count += 1
        return count

    def eval(self, script: str, num_keys: int, key: str, *args) -> int:
        # Simple Lua script emulation for lock operations
        if "del" in script.lower():
            # Release: compare and delete
            if self.data.get(key) == args[0]:
                del self.data[key]
                return 1
            return 0
        if "expire" in script.lower():
            # Refresh: compare and extend TTL
            if self.data.get(key) == args[0]:
                self.ttls[key] = int(args[1]) if len(args) > 1 else 180
                return 1
            return 0
        return 0


class TestDistributedLock:
    def test_acquire_success(self, monkeypatch):
        fake_redis = FakeRedis()
        monkeypatch.setattr("app.tasks.sync_tasks.redis_client", fake_redis)

        user_id = uuid4()
        lock = DistributedLock(user_id, owner=f"chat:{uuid4()}")
        assert lock.acquire() is True
        assert fake_redis.data[lock.lock_key] == lock.payload

        lock.release()

    def test_acquire_conflict(self, monkeypatch):
        fake_redis = FakeRedis()
        monkeypatch.setattr("app.tasks.sync_tasks.redis_client", fake_redis)

        user_id = uuid4()
        lock1 = DistributedLock(user_id, owner="owner1")
        lock2 = DistributedLock(user_id, owner="owner2")

        assert lock1.acquire() is True
        assert lock2.acquire() is False

        lock1.release()

    def test_release_does_not_delete_foreign_owner(self, monkeypatch):
        fake_redis = FakeRedis()
        monkeypatch.setattr("app.tasks.sync_tasks.redis_client", fake_redis)

        user_id = uuid4()
        lock = DistributedLock(user_id, owner=f"chat:{uuid4()}")
        assert lock.acquire() is True

        # Simulate lock expiry and reacquire by another worker
        other_payload = json.dumps(
            {"owner": "other", "token": "other-token"},
            separators=(",", ":"),
            sort_keys=True,
        )
        fake_redis.data[lock.lock_key] = other_payload
        lock.release()

        # Other owner's lock should still be present
        assert fake_redis.data[lock.lock_key] == other_payload

    def test_refresh_extends_ttl(self, monkeypatch):
        fake_redis = FakeRedis()
        monkeypatch.setattr("app.tasks.sync_tasks.redis_client", fake_redis)

        user_id = uuid4()
        lock = DistributedLock(user_id, owner="test")
        assert lock.acquire() is True
        assert lock.refresh() is True

        lock.release()

    def test_refresh_fails_if_not_owner(self, monkeypatch):
        fake_redis = FakeRedis()
        monkeypatch.setattr("app.tasks.sync_tasks.redis_client", fake_redis)

        user_id = uuid4()
        lock = DistributedLock(user_id, owner="test")
        assert lock.acquire() is True

        # Replace payload to simulate lost ownership
        fake_redis.data[lock.lock_key] = "foreign_payload"
        assert lock.refresh() is False

        lock.release()


class TestHeartbeatKeys:
    def test_single_heartbeat_key_format(self):
        from app.tasks.sync_tasks import _single_heartbeat_key

        job_id = uuid4()
        key = _single_heartbeat_key(job_id)
        assert key == f"sync:{job_id}:heartbeat"

    def test_bulk_heartbeat_key_format(self):
        from app.tasks.sync_tasks import _bulk_heartbeat_key

        job_id = uuid4()
        key = _bulk_heartbeat_key(job_id)
        assert key == f"bulk:{job_id}:heartbeat"


class TestCleanupProgress:
    def test_cleanup_single_progress(self, monkeypatch):
        fake_redis = FakeRedis()
        monkeypatch.setattr("app.tasks.sync_tasks.redis_client", fake_redis)

        from app.tasks.sync_tasks import _cleanup_single_progress

        job_id = uuid4()
        fake_redis.data[f"sync:{job_id}:total"] = "100"
        fake_redis.data[f"sync:{job_id}:seen"] = "50"
        fake_redis.data[f"sync:{job_id}:heartbeat"] = "1"

        _cleanup_single_progress(job_id)

        assert f"sync:{job_id}:total" not in fake_redis.data
        assert f"sync:{job_id}:seen" not in fake_redis.data
        assert f"sync:{job_id}:heartbeat" not in fake_redis.data

    def test_cleanup_bulk_progress(self, monkeypatch):
        fake_redis = FakeRedis()
        monkeypatch.setattr("app.tasks.sync_tasks.redis_client", fake_redis)

        from app.tasks.sync_tasks import _cleanup_bulk_progress

        job_id = uuid4()
        fake_redis.data[f"bulk:{job_id}:total"] = "10"
        fake_redis.data[f"bulk:{job_id}:completed"] = "5"
        fake_redis.data[f"bulk:{job_id}:current_chat"] = "Chat"
        fake_redis.data[f"bulk:{job_id}:heartbeat"] = "1"

        _cleanup_bulk_progress(job_id)

        assert f"bulk:{job_id}:total" not in fake_redis.data
        assert f"bulk:{job_id}:completed" not in fake_redis.data
