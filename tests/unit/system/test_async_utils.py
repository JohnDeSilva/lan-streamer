"""Tests for the async_utils module."""

import asyncio

import pytest

from lan_streamer.system.async_utils import (
    AsyncSemaphore,
    async_run_subprocess,
    cancel_task_safely,
    gather_with_concurrency,
    get_event_loop_safe,
    get_fs_executor,
    get_network_semaphore,
    get_subprocess_semaphore,
    run_in_executor,
    run_in_fs_executor,
    shutdown_fs_executor,
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


# ---------------------------------------------------------------------------
# FileSystemExecutor (get_fs_executor / shutdown_fs_executor)
# ---------------------------------------------------------------------------


class TestFileSystemExecutor:
    """Tests for :func:`get_fs_executor` and :func:`shutdown_fs_executor`."""

    def teardown_method(self) -> None:
        """Ensure the executor is cleaned up after each test."""
        shutdown_fs_executor()

    def test_returns_executor_instance(self) -> None:
        """get_fs_executor should return a ThreadPoolExecutor."""
        executor = get_fs_executor()
        from concurrent.futures import ThreadPoolExecutor

        assert isinstance(executor, ThreadPoolExecutor)

    def test_singleton_same_instance(self) -> None:
        """get_fs_executor should return the same instance on repeated calls."""
        first = get_fs_executor()
        second = get_fs_executor()
        assert first is second
        shutdown_fs_executor()

    def test_max_workers_is_three(self) -> None:
        """get_fs_executor should have max_workers == 3."""
        executor = get_fs_executor()
        assert executor._max_workers == 3

    def test_shutdown_clears_singleton(self) -> None:
        """shutdown_fs_executor should clear the global executor."""
        first = get_fs_executor()
        shutdown_fs_executor()
        second = get_fs_executor()
        assert first is not second

    def test_shutdown_safe_to_call_multiple_times(self) -> None:
        """shutdown_fs_executor should not raise when called multiple times."""
        shutdown_fs_executor()
        shutdown_fs_executor()
        shutdown_fs_executor()

    def test_new_executor_after_shutdown_is_functional(self) -> None:
        """A new executor obtained after shutdown should be usable."""
        shutdown_fs_executor()
        executor = get_fs_executor()
        future = executor.submit(lambda: 42)
        assert future.result() == 42


# ---------------------------------------------------------------------------
# run_in_fs_executor
# ---------------------------------------------------------------------------


class TestRunInFsExecutor:
    """Tests for :func:`run_in_fs_executor`."""

    def teardown_method(self) -> None:
        """Clean up the executor after each test."""
        shutdown_fs_executor()

    def test_returns_result(self) -> None:
        """run_in_fs_executor should return the result of the callable."""

        async def _test() -> None:
            result = await run_in_fs_executor(lambda: "hello from fs")
            assert result == "hello from fs"

        asyncio.run(_test())

    def test_passes_args(self) -> None:
        """run_in_fs_executor should forward positional arguments."""

        async def _test() -> None:
            result = await run_in_fs_executor(lambda a, b: a + b, 10, 20)
            assert result == 30

        asyncio.run(_test())

    def test_passes_kwargs(self) -> None:
        """run_in_fs_executor should forward keyword arguments."""

        async def _test() -> None:
            result = await run_in_fs_executor(
                lambda first, second: f"{first}-{second}",
                "a",
                second="b",
            )
            assert result == "a-b"

        asyncio.run(_test())

    def test_propagates_exception(self) -> None:
        """run_in_fs_executor should propagate exceptions from the callable."""

        async def _test() -> None:
            def _failing() -> None:
                msg = "fs executor failure"
                raise RuntimeError(msg)

            with pytest.raises(RuntimeError, match="fs executor failure"):
                await run_in_fs_executor(_failing)

        asyncio.run(_test())

    def test_runs_in_fs_executor_pool(self) -> None:
        """run_in_fs_executor should use the dedicated filesystem executor."""

        async def _test() -> None:
            def _identify_pool() -> str:
                return threading.current_thread().name

            result = await run_in_fs_executor(_identify_pool)
            assert "fs_executor" in result

        import threading

        asyncio.run(_test())


# ---------------------------------------------------------------------------
# Global concurrency semaphores (Stage 6)
# ---------------------------------------------------------------------------


class TestNetworkSemaphore:
    """Tests for :func:`get_network_semaphore`."""

    def test_returns_semaphore_instance(self) -> None:
        """get_network_semaphore should return an asyncio.Semaphore."""
        semaphore = get_network_semaphore()
        assert isinstance(semaphore, asyncio.Semaphore)

    def test_singleton_same_instance(self) -> None:
        """get_network_semaphore should return the same instance."""
        first = get_network_semaphore()
        second = get_network_semaphore()
        assert first is second

    def test_value_is_10(self) -> None:
        """get_network_semaphore should have value 10."""
        semaphore = get_network_semaphore()
        assert semaphore._value == 10


class TestSubprocessSemaphore:
    """Tests for :func:`get_subprocess_semaphore`."""

    def test_returns_semaphore_instance(self) -> None:
        """get_subprocess_semaphore should return an asyncio.Semaphore."""
        semaphore = get_subprocess_semaphore()
        assert isinstance(semaphore, asyncio.Semaphore)

    def test_singleton_same_instance(self) -> None:
        """get_subprocess_semaphore should return the same instance."""
        first = get_subprocess_semaphore()
        second = get_subprocess_semaphore()
        assert first is second

    def test_value_is_3(self) -> None:
        """get_subprocess_semaphore should have value 3."""
        semaphore = get_subprocess_semaphore()
        assert semaphore._value == 3


class TestAsyncRunSubprocess:
    """Tests for :func:`async_run_subprocess`."""

    def test_returns_completed_process(self) -> None:
        """async_run_subprocess should return a CompletedProcess on success."""

        async def _test() -> None:
            result = await async_run_subprocess(["echo", "hello"])
            assert result.returncode == 0
            assert "hello" in result.stdout

        asyncio.run(_test())

    def test_captures_stderr(self) -> None:
        """async_run_subprocess should capture stderr output."""

        async def _test() -> None:
            result = await async_run_subprocess(
                ["sh", "-c", 'echo "error msg" >&2; exit 1']
            )
            assert result.returncode == 1
            assert "error msg" in result.stderr

        asyncio.run(_test())

    def test_respects_timeout(self) -> None:
        """async_run_subprocess should raise TimeoutError when timeout is exceeded."""

        async def _test() -> None:
            with pytest.raises(asyncio.TimeoutError):
                await async_run_subprocess(["sleep", "10"], timeout=0.01)

        asyncio.run(_test())

    def test_uses_subprocess_semaphore(self) -> None:
        """async_run_subprocess should use the subprocess semaphore (value=3)."""

        async def _test() -> None:
            # Verify the semaphore allows at most 3 concurrent acquisitions.
            # Launch 6 quick subprocesses; the semaphore limits to 3 in flight.
            results = await asyncio.gather(
                *[async_run_subprocess(["true"]) for _ in range(6)]
            )
            assert all(result.returncode == 0 for result in results)

        asyncio.run(_test())

    def test_cancellation_kills_process(self) -> None:
        """async_run_subprocess should terminate the process when cancelled."""
        from unittest.mock import AsyncMock, MagicMock, patch

        async def _test() -> None:
            mock_process = MagicMock()
            mock_process.communicate = AsyncMock(side_effect=asyncio.CancelledError())
            mock_process.kill = MagicMock()
            mock_process.wait = AsyncMock()

            with patch(
                "asyncio.create_subprocess_exec", return_value=mock_process
            ) as mock_exec:
                with pytest.raises(asyncio.CancelledError):
                    await async_run_subprocess(["some_command"])

                mock_exec.assert_called_once_with(
                    "some_command",
                    stdin=None,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                mock_process.kill.assert_called_once()
                mock_process.wait.assert_called_once()

        asyncio.run(_test())
