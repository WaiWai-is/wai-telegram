from uuid import uuid4

from app.tasks import sync_tasks


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def eval(self, script: str, num_keys: int, key: str, token: str, *args) -> int:
        if "del" in script:
            if self.data.get(key) == token:
                del self.data[key]
                return 1
            return 0
        if "expire" in script:
            return 1 if self.data.get(key) == token else 0
        return 0


def test_distributed_lock_release_does_not_delete_foreign_owner(monkeypatch) -> None:
    fake_redis = FakeRedis()
    monkeypatch.setattr(sync_tasks, "redis_client", fake_redis)

    user_id = uuid4()
    lock = sync_tasks.DistributedLock(user_id)
    assert lock.acquire() is True
    assert fake_redis.data[lock.lock_key] == lock.token

    # Simulate lock expiry + reacquire by another worker.
    fake_redis.data[lock.lock_key] = "other-owner-token"
    lock.release()

    assert fake_redis.data[lock.lock_key] == "other-owner-token"
