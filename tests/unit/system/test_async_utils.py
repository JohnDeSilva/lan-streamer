"""Tests for the async_utils module."""

import asyncio

import pytest

from lan_streamer.system.async_utils import (
    AsyncSemaphore,
    cancel_task_safely,
    gather_with_concurrency,
    get_event_loop_safe,
    run_in_executor,
    to_async,
)


# ---------------------------------------------------------------------------
# run_in_executor
# ---------------------------------------------------------------------------


def _sync_identity(value: str) -> str:
    """A simple synchronous function for testing run_in_executor."""
    return value


def _sync_sum(a: int, b: int) -> int:
    """A synchronous function that accepts multiple arguments."""
    return a + b


def _sync_with_kwargs(first: str, second: str, separator: str = ", ") -> str:
    """A synchronous function that accepts keyword arguments."""
    return f"{first}{separator}{second}"


class TestRunInExecutor:
    """Tests for :func:`run_in_executor`."""

    def test_returns_result(self) -> None:
        """run_in_executor should return the result of the callable."""

        async def _test() -> None:
            result = await run_in_executor(_sync_identity, "hello")
            assert result == "hello"

        asyncio.run(_test())

    def test_passes_positional_args(self) -> None:
        """run_in_executor should forward positional arguments."""

        async def _test() -> None:
            result = await run_in_executor(_sync_sum, 3, 4)
            assert result == 7

        asyncio.run(_test())

    def test_passes_keyword_args(self) -> None:
        """run_in_executor should forward keyword arguments."""

        async def _test() -> None:
            result = await run_in_executor(
                _sync_with_kwargs, "foo", "bar", separator="|"
            )
            assert result == "foo|bar"

        asyncio.run(_test())

    def test_raises_callable_exception(self) -> None:
        """run_in_executor should propagate exceptions from the callable."""

        def _failing() -> None:
            msg = "intentional failure"
            raise ValueError(msg)

        async def _test() -> None:
            with pytest.raises(ValueError, match="intentional failure"):
                await run_in_executor(_failing)

        asyncio.run(_test())


# ---------------------------------------------------------------------------
# to_async
# ---------------------------------------------------------------------------


def _multiply(x: int, y: int) -> int:
    """A simple synchronous function for testing the to_async decorator."""
    return x * y


class TestToAsync:
    """Tests for :func:`to_async`."""

    def test_wraps_callable(self) -> None:
        """to_async should wrap a sync callable into an async function."""

        async def _test() -> None:
            wrapped = to_async(_multiply)
            result = await wrapped(6, 7)
            assert result == 42

        asyncio.run(_test())

    def test_preserves_function_name(self) -> None:
        """to_async should preserve the original function's __name__."""
        wrapped = to_async(_multiply)
        assert wrapped.__name__ == "_multiply"
        assert wrapped.__wrapped__ is _multiply  # type: ignore[attr-defined]

    def test_propagates_exceptions(self) -> None:
        """to_async should propagate exceptions from the wrapped callable."""

        def _failing() -> None:
            msg = "wrapped failure"
            raise RuntimeError(msg)

        async def _test() -> None:
            wrapped = to_async(_failing)
            with pytest.raises(RuntimeError, match="wrapped failure"):
                await wrapped()

        asyncio.run(_test())


# ---------------------------------------------------------------------------
# AsyncSemaphore
# ---------------------------------------------------------------------------


class TestAsyncSemaphore:
    """Tests for :class:`AsyncSemaphore`."""

    def test_acquire_and_release(self) -> None:
        """AsyncSemaphore should allow acquire/release via async with."""

        async def _test() -> None:
            semaphore = AsyncSemaphore(2)
            async with semaphore:
                pass  # Should not block or raise

        asyncio.run(_test())

    def test_limits_concurrency(self) -> None:
        """AsyncSemaphore should block when the capacity is exhausted."""

        async def _test() -> None:
            semaphore = AsyncSemaphore(1)

            acquired_events: list[bool] = []

            async def _acquire_and_record() -> None:
                async with semaphore:
                    acquired_events.append(True)
                    await asyncio.sleep(0.05)

            # Two concurrent acquisitions on a semaphore of size 1 should both
            # succeed (one after the other), proving the semaphore only lets one
            # through at a time.
            await asyncio.gather(_acquire_and_record(), _acquire_and_record())
            assert len(acquired_events) == 2

        asyncio.run(_test())

    def test_rejects_invalid_value(self) -> None:
        """AsyncSemaphore should reject values less than 1."""
        with pytest.raises(ValueError, match="Semaphore value must be >= 1"):
            AsyncSemaphore(0)

        with pytest.raises(ValueError, match="Semaphore value must be >= 1"):
            AsyncSemaphore(-1)


# ---------------------------------------------------------------------------
# gather_with_concurrency
# ---------------------------------------------------------------------------


class TestGatherWithConcurrency:
    """Tests for :func:`gather_with_concurrency`."""

    def test_returns_all_results(self) -> None:
        """gather_with_concurrency should return results in input order."""

        async def _double(value: int) -> int:
            return value * 2

        async def _test() -> None:
            results = await gather_with_concurrency(
                5, _double(1), _double(2), _double(3)
            )
            assert results == [2, 4, 6]

        asyncio.run(_test())

    def test_preserves_order(self) -> None:
        """gather_with_concurrency should preserve input order despite delays."""

        async def _delayed_identity(index: int, delay: float) -> int:
            await asyncio.sleep(delay)
            return index

        async def _test() -> None:
            results = await gather_with_concurrency(
                3,
                _delayed_identity(0, 0.1),
                _delayed_identity(1, 0.01),
                _delayed_identity(2, 0.05),
            )
            assert results == [0, 1, 2]

        asyncio.run(_test())

    def test_respects_limit(self) -> None:
        """gather_with_concurrency should not exceed the concurrency limit."""

        async def _test() -> None:
            semaphore_count: int = 0
            max_concurrent: int = 0

            async def _track_concurrency() -> None:
                nonlocal semaphore_count, max_concurrent
                semaphore_count += 1
                max_concurrent = max(max_concurrent, semaphore_count)
                await asyncio.sleep(0.05)
                semaphore_count -= 1

            await gather_with_concurrency(2, *(_track_concurrency() for _ in range(4)))
            assert max_concurrent <= 2

        asyncio.run(_test())

    def test_rejects_invalid_n(self) -> None:
        """gather_with_concurrency should reject n < 1."""

        async def _test() -> None:
            with pytest.raises(ValueError, match="Concurrency limit must be >= 1"):
                await gather_with_concurrency(0)

            with pytest.raises(ValueError, match="Concurrency limit must be >= 1"):
                await gather_with_concurrency(-1)

        asyncio.run(_test())

    def test_propagates_exceptions(self) -> None:
        """gather_with_concurrency should propagate exceptions from coroutines."""

        async def _will_fail() -> None:
            msg = "gather failure"
            raise RuntimeError(msg)

        async def _test() -> None:
            with pytest.raises(RuntimeError, match="gather failure"):
                await gather_with_concurrency(2, _will_fail())

        asyncio.run(_test())


# ---------------------------------------------------------------------------
# cancel_task_safely
# ---------------------------------------------------------------------------


class TestCancelTaskSafely:
    """Tests for :func:`cancel_task_safely`."""

    def test_cancels_running_task(self) -> None:
        """cancel_task_safely should cancel a running task."""

        async def _never_finish() -> None:
            while True:
                await asyncio.sleep(1)

        async def _test() -> None:
            task = asyncio.create_task(_never_finish())
            await asyncio.sleep(0.01)  # let the task start

            cancel_task_safely(task)

            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(_test())

    def test_handles_none(self) -> None:
        """cancel_task_safely should do nothing when task is None."""
        cancel_task_safely(None)  # Should not raise

    def test_handles_done_task(self) -> None:
        """cancel_task_safely should do nothing when task is already done."""

        async def _quick() -> int:
            return 42

        async def _test() -> None:
            task = asyncio.create_task(_quick())
            result = await task
            assert result == 42

            # Should not raise or log errors
            cancel_task_safely(task)

        asyncio.run(_test())

    def test_handles_cancelled_task(self) -> None:
        """cancel_task_safely should do nothing when task is already cancelled."""

        async def _slow() -> None:
            await asyncio.sleep(10)

        async def _test() -> None:
            task = asyncio.create_task(_slow())
            await asyncio.sleep(0.01)
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

            # Should not raise or log errors for already-cancelled task
            cancel_task_safely(task)

        asyncio.run(_test())


# ---------------------------------------------------------------------------
# get_event_loop_safe
# ---------------------------------------------------------------------------


class TestGetEventLoopSafe:
    """Tests for :func:`get_event_loop_safe`."""

    def test_returns_loop_outside_async(self) -> None:
        """get_event_loop_safe should return an event loop when none is running."""
        loop = get_event_loop_safe()
        assert isinstance(loop, asyncio.AbstractEventLoop)
        assert not loop.is_closed()
        loop.close()

    def test_returns_running_loop(self) -> None:
        """get_event_loop_safe should return the currently running loop."""

        async def _test() -> None:
            running_loop = asyncio.get_running_loop()
            safe_loop = get_event_loop_safe()
            assert safe_loop is running_loop

        asyncio.run(_test())
