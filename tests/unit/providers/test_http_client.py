"""
Tests for AsyncHTTPClient — the async HTTP wrapper with rate limiting and retry.

All async tests use ``event_loop.run_until_complete()`` since the project
does not use ``pytest-asyncio``.
"""

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
    return AsyncHTTPClient(requests_per_second=100.0)


def _run(coro: Any, event_loop: asyncio.AbstractEventLoop) -> Any:
    return event_loop.run_until_complete(coro)


class TestConstruction:
    def test_default_parameters(self) -> None:
        c = AsyncHTTPClient()
        assert c._requests_per_second == 10.0
        assert c._max_retries == 3
        assert c._backoff_factor == 1.0
        assert c._timeout == 10.0

    def test_custom_parameters(self) -> None:
        c = AsyncHTTPClient(
            requests_per_second=5.0, max_retries=5, backoff_factor=2.0, timeout=30.0
        )
        assert c._requests_per_second == 5.0
        assert c._max_retries == 5
        assert c._backoff_factor == 2.0
        assert c._timeout == 30.0


class TestSession:
    def test_get_session_creates_session(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            session = await client._get_session()
            assert isinstance(session, aiohttp.ClientSession)
            await client.close()

        _run(run(), event_loop)

    def test_get_session_reuses_session(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            s1 = await client._get_session()
            s2 = await client._get_session()
            assert s1 is s2
            await client.close()

        _run(run(), event_loop)

    def test_close_closes_session(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            await client._get_session()
            await client.close()
            assert client._session is None or client._session.closed

        _run(run(), event_loop)


class TestThrottle:
    def test_throttle_does_not_delay_first_request(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            start = asyncio.get_running_loop().time()
            await client._throttle()
            elapsed = asyncio.get_running_loop().time() - start
            assert elapsed < 0.05

        _run(run(), event_loop)

    def test_throttle_enforces_minimum_spacing(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            client._requests_per_second = 20.0
            await client._throttle()
            start = asyncio.get_running_loop().time()
            await client._throttle()
            elapsed = asyncio.get_running_loop().time() - start
            assert elapsed >= 0.04

        _run(run(), event_loop)


class TestGet:
    def test_get_returns_json(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_response = AsyncMock(spec=aiohttp.ClientResponse)
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"key": "value"})

            with patch.object(
                client, "_request", AsyncMock(return_value=mock_response)
            ):
                result = await client.get("http://example.com")
                assert result == {"key": "value"}

        _run(run(), event_loop)

    def test_get_passes_params(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_response = AsyncMock(spec=aiohttp.ClientResponse)
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={})

            with patch.object(
                client, "_request", AsyncMock(return_value=mock_response)
            ) as mock_request:
                await client.get("http://example.com", params={"q": "test"})
                mock_request.assert_called_once_with(
                    "GET",
                    "http://example.com",
                    params={"q": "test"},
                    headers=None,
                    timeout=None,
                )

        _run(run(), event_loop)


class TestGetBytes:
    def test_get_bytes_returns_raw_data(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_response = AsyncMock(spec=aiohttp.ClientResponse)
            mock_response.status = 200
            mock_response.read = AsyncMock(return_value=b"raw data")

            with patch.object(
                client, "_request", AsyncMock(return_value=mock_response)
            ):
                result = await client.get_bytes("http://example.com")
                assert result == b"raw data"

        _run(run(), event_loop)


class TestPost:
    def test_post_sends_json(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_response = AsyncMock(spec=aiohttp.ClientResponse)
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"result": "ok"})

            with patch.object(
                client, "_request", AsyncMock(return_value=mock_response)
            ) as mock_request:
                await client.post("http://example.com", json_data={"a": 1})
                mock_request.assert_called_once_with(
                    "POST",
                    "http://example.com",
                    json_data={"a": 1},
                    headers=None,
                    timeout=None,
                )

        _run(run(), event_loop)


class TestRequest:
    def test_retry_on_429(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_429 = AsyncMock(spec=aiohttp.ClientResponse)
            mock_429.status = 429
            mock_429.headers = {}

            mock_200 = AsyncMock(spec=aiohttp.ClientResponse)
            mock_200.status = 200
            mock_200.json = AsyncMock(return_value={"ok": True})

            session = MagicMock()
            session.request = AsyncMock(side_effect=[mock_429, mock_200])

            with patch.object(client, "_get_session", AsyncMock(return_value=session)):
                result = await client.get("http://example.com")
                assert result == {"ok": True}

        _run(run(), event_loop)

    def test_raises_after_max_retries(
        self, event_loop: asyncio.AbstractEventLoop, client: AsyncHTTPClient
    ) -> None:
        async def run() -> None:
            mock_429 = AsyncMock(spec=aiohttp.ClientResponse)
            mock_429.status = 429
            mock_429.headers = {}
            mock_429.close = MagicMock()

            session = MagicMock()
            session.request = AsyncMock(return_value=mock_429)

            with patch.object(client, "_get_session", AsyncMock(return_value=session)):
                with pytest.raises(RuntimeError, match="failed after 3 retries"):
                    await client.get("http://example.com")

        _run(run(), event_loop)
