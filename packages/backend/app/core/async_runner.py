import asyncio
import os
import threading
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_ready = threading.Event()
_pid: int | None = None
_lock = threading.Lock()


def _thread_main() -> None:
    global _loop

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _loop = loop
    _ready.set()

    try:
        loop.run_forever()
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        _loop = None


def start_async_runner() -> None:
    global _thread, _pid

    with _lock:
        pid = os.getpid()
        if _thread is not None and _thread.is_alive() and _pid == pid:
            return

        _ready.clear()
        _thread = threading.Thread(
            target=_thread_main,
            name="wai-telegram-async-runner",
            daemon=True,
        )
        _thread.start()
        _pid = pid

    if not _ready.wait(timeout=5):
        raise RuntimeError("Timed out starting async runner")


def run_async(awaitable: Awaitable[T]) -> T:
    start_async_runner()
    if _loop is None:
        raise RuntimeError("Async runner loop is unavailable")

    future = asyncio.run_coroutine_threadsafe(awaitable, _loop)
    return future.result()


def stop_async_runner() -> None:
    global _thread, _pid

    with _lock:
        loop = _loop
        thread = _thread
        _thread = None
        _pid = None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)

    if thread is not None:
        thread.join(timeout=5)
