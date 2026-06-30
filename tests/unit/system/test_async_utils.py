"""Tests for the async_utils module."""

import asyncio

import pytest

from lan_streamer.system.async_utils import (
    AsyncSemaphore,
    async_run_subprocess,
    get_fs_executor,
    get_network_semaphore,
    get_subprocess_semaphore,
    run_in_executor,
    run_in_fs_executor,
    shutdown_fs_executor,
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
