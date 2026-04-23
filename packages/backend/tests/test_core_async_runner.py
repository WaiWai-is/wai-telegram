from app.core.async_runner import run_async, stop_async_runner


async def _loop_identifier() -> int:
    import asyncio

    return id(asyncio.get_running_loop())


class TestAsyncRunner:
    def teardown_method(self):
        stop_async_runner()

    def test_run_async_executes_coroutine(self):
        async def compute() -> int:
            return 42

        assert run_async(compute()) == 42

    def test_run_async_reuses_same_event_loop(self):
        first = run_async(_loop_identifier())
        second = run_async(_loop_identifier())

        assert first == second
