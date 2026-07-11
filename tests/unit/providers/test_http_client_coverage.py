"""Coverage tests for AsyncHTTPClient — targeting uncovered lines."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from lan_streamer.providers.http_client import AsyncHTTPClient


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.run_until_complete(
        asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True)
    )
    loop.close()


@pytest.fixture
def client() -> AsyncHTTPClient:
    return AsyncHTTPClient(
        requests_per_second=100.0, max_retries=2, backoff_factor=0.01
    )


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    return event_loop.run_until_complete(coro)


class TestRetryAfterHeader:
    """Line 112: 429 with valid Retry-After digit header."""

    def test_429_with_retry_after_digit(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_429 = AsyncMock(spec=aiohttp.ClientResponse)
            mock_429.status = 429
            mock_429.headers = {"Retry-After": "1"}
            mock_429.close = MagicMock()

            mock_200 = AsyncMock(spec=aiohttp.ClientResponse)
            mock_200.status = 200
            mock_200.json = AsyncMock(return_value={"ok": True})

            session = MagicMock()
            session.request = AsyncMock(side_effect=[mock_429, mock_200])

            with patch.object(client, "_get_session", AsyncMock(return_value=session)):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await client.get("http://example.invalid")
                    assert result == {"ok": True}

        _run(run(), event_loop)


class TestClientErrorRetry:
    """Lines 128-147: exception handling with retry then raise."""

    def test_client_error_raises_after_retries(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            session = MagicMock()
            session.request = AsyncMock(
                side_effect=aiohttp.ClientError("connection failed")
            )

            with patch.object(client, "_get_session", AsyncMock(return_value=session)):
                with pytest.raises(aiohttp.ClientError):
                    await client.get("http://example.invalid")

        _run(run(), event_loop)

    def test_timeout_error_raises_after_retries(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            session = MagicMock()
            session.request = AsyncMock(side_effect=asyncio.TimeoutError("timeout"))

            with patch.object(client, "_get_session", AsyncMock(return_value=session)):
                with pytest.raises(asyncio.TimeoutError):
                    await client.get("http://example.invalid")

        _run(run(), event_loop)

    def test_client_error_retries_then_succeeds(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_200 = AsyncMock(spec=aiohttp.ClientResponse)
            mock_200.status = 200
            mock_200.json = AsyncMock(return_value={"recovered": True})

            session = MagicMock()
            session.request = AsyncMock(
                side_effect=[aiohttp.ClientError("transient"), mock_200]
            )

            with patch.object(client, "_get_session", AsyncMock(return_value=session)):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await client.get("http://example.invalid")
                    assert result == {"recovered": True}

        _run(run(), event_loop)


class TestGetJson:
    """Lines 175-179: get_json returns raw parsed JSON (list or dict)."""

    def test_get_json_returns_list(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_response = AsyncMock(spec=aiohttp.ClientResponse)
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=[{"a": 1}, {"b": 2}])

            with patch.object(
                client, "_request", AsyncMock(return_value=mock_response)
            ):
                result = await client.get_json("http://example.invalid/data")
                assert result == [{"a": 1}, {"b": 2}]

        _run(run(), event_loop)

    def test_get_json_returns_dict(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_response = AsyncMock(spec=aiohttp.ClientResponse)
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"key": "val"})

            with patch.object(
                client, "_request", AsyncMock(return_value=mock_response)
            ):
                result = await client.get_json("http://example.invalid/data")
                assert result == {"key": "val"}

        _run(run(), event_loop)


class TestDelete:
    """Lines 213-215: delete method."""

    def test_delete_returns_json(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_response = AsyncMock(spec=aiohttp.ClientResponse)
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"deleted": True})

            with patch.object(
                client, "_request", AsyncMock(return_value=mock_response)
            ) as mock_request:
                result = await client.delete("http://example.invalid/resource")
                assert result == {"deleted": True}
                mock_request.assert_called_once_with(
                    "DELETE",
                    "http://example.invalid/resource",
                    headers=None,
                    timeout=None,
                )

        _run(run(), event_loop)

    def test_delete_with_headers(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_response = AsyncMock(spec=aiohttp.ClientResponse)
            mock_response.status = 204
            mock_response.json = AsyncMock(return_value={})

            with patch.object(
                client, "_request", AsyncMock(return_value=mock_response)
            ) as mock_request:
                result = await client.delete(
                    "http://example.invalid/resource",
                    headers={"X-Custom": "value"},
                    timeout=5.0,
                )
                assert result == {}
                mock_request.assert_called_once_with(
                    "DELETE",
                    "http://example.invalid/resource",
                    headers={"X-Custom": "value"},
                    timeout=5.0,
                )

        _run(run(), event_loop)


class TestCloseSession:
    """Line 64: close when session is open."""

    def test_close_when_already_closed(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            client._session = None
            await client.close()

        _run(run(), event_loop)

    def test_close_when_open(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_session.close = AsyncMock()
            client._session = mock_session
            await client.close()
            mock_session.close.assert_called_once()

        _run(run(), event_loop)


class TestGetSessionCreation:
    """Lines 52-61: _get_session creates a new session."""

    def test_creates_session_when_none(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            client._session = None
            session = await client._get_session()
            assert session is not None
            await client.close()

        _run(run(), event_loop)


class TestRetryAfterNonDigit:
    """Line 114: 429 with non-digit Retry-After header."""

    def test_non_digit_retry_after_uses_backoff(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_429 = AsyncMock(spec=aiohttp.ClientResponse)
            mock_429.status = 429
            mock_429.headers = {"Retry-After": "abc"}
            mock_429.close = MagicMock()

            mock_200 = AsyncMock(spec=aiohttp.ClientResponse)
            mock_200.status = 200
            mock_200.json = AsyncMock(return_value={"ok": True})

            session = MagicMock()
            session.request = AsyncMock(side_effect=[mock_429, mock_200])

            with patch.object(client, "_get_session", AsyncMock(return_value=session)):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await client.get("http://example.invalid")
                    assert result == {"ok": True}

        _run(run(), event_loop)


class TestGetBytes:
    """Lines 188-190: get_bytes method."""

    def test_get_bytes_returns_raw(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_response = AsyncMock(spec=aiohttp.ClientResponse)
            mock_response.status = 200
            mock_response.read = AsyncMock(return_value=b"\x89PNG\r\n")

            with patch.object(
                client, "_request", AsyncMock(return_value=mock_response)
            ):
                result = await client.get_bytes("http://example.invalid/image.png")
                assert result == b"\x89PNG\r\n"

        _run(run(), event_loop)


class TestPost:
    """Lines 200-204: post method."""

    def test_post_returns_json(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_response = AsyncMock(spec=aiohttp.ClientResponse)
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"created": True})

            with patch.object(
                client, "_request", AsyncMock(return_value=mock_response)
            ) as mock_request:
                result = await client.post(
                    "http://example.invalid/api",
                    json_data={"key": "value"},
                )
                assert result == {"created": True}
                mock_request.assert_called_once_with(
                    "POST",
                    "http://example.invalid/api",
                    json_data={"key": "value"},
                    headers=None,
                    timeout=None,
                )

        _run(run(), event_loop)


class TestRuntimeErrorAfterRetries:
    """Line 149: RuntimeError raised when all retries exhausted via 429."""

    def test_runtime_error_after_all_retries_429(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        async def run() -> None:
            c = AsyncHTTPClient(
                requests_per_second=100.0, max_retries=2, backoff_factor=0.01
            )
            mock_429 = AsyncMock(spec=aiohttp.ClientResponse)
            mock_429.status = 429
            mock_429.headers = {}
            mock_429.close = MagicMock()

            mock_session = MagicMock()
            mock_session.request = AsyncMock(return_value=mock_429)

            with patch.object(c, "_get_session", AsyncMock(return_value=mock_session)):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(RuntimeError, match="failed after 2 retries"):
                        await c.get("http://example.invalid")

        _run(run(), event_loop)
