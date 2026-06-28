"""
Async HTTP client wrapper around ``aiohttp`` with rate limiting and retry.

Provides :class:`AsyncHTTPClient`, a singleton-style wrapper that manages an
``aiohttp.ClientSession`` with token-bucket rate limiting and exponential
backoff retry on 429 / network errors.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


class AsyncHTTPClient:
    """Async HTTP client with rate limiting and retry support.

    Wraps an ``aiohttp.ClientSession`` with configurable rate limits and
    automatic retry with exponential backoff.

    Usage::

        client = AsyncHTTPClient()
        response_data = await client.get("https://api.example.com/data")
        response_data = await client.post("https://api.example.com/data", json={"key": "value"})
        raw_bytes = await client.get_bytes("https://example.com/image.jpg")
    """

    def __init__(
        self,
        requests_per_second: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        timeout: float = 10.0,
    ) -> None:
        self._requests_per_second = requests_per_second
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._timeout = timeout

        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limit_lock = asyncio.Lock()
        self._last_request_time: float = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout_config = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(
                timeout=timeout_config,
                headers={
                    "User-Agent": "LanStreamer/1.0",
                    "Accept": "application/json",
                },
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _throttle(self) -> None:
        """Token-bucket throttle: ensure minimum spacing between requests."""
        async with self._rate_limit_lock:
            now = asyncio.get_running_loop().time()
            min_interval = 1.0 / self._requests_per_second
            elapsed = now - self._last_request_time
            delay = max(0.0, min_interval - elapsed)
            self._last_request_time = now + delay
        if delay > 0:
            await asyncio.sleep(delay)

    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> aiohttp.ClientResponse:
        """Make an HTTP request with rate limiting, concurrency limit, and retry."""
        from lan_streamer.system.async_utils import get_network_semaphore

        session = await self._get_session()
        effective_timeout = timeout if timeout is not None else self._timeout

        last_exception: Optional[Exception] = None

        for attempt in range(self._max_retries):
            async with get_network_semaphore():
                await self._throttle()

                try:
                    response = await session.request(
                        method=method.upper(),
                        url=url,
                        params=params,
                        json=json_data,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=effective_timeout),
                    )

                    if response.status == 429:
                        retry_after_str = response.headers.get("Retry-After")
                        if retry_after_str and retry_after_str.isdigit():
                            sleep_time = float(retry_after_str)
                        else:
                            sleep_time = self._backoff_factor * (
                                2**attempt
                            ) + random.uniform(0, 1)
                        logger.warning(
                            "HTTP 429 rate limit at %s. Retrying in %.2f seconds...",
                            url,
                            sleep_time,
                        )
                        response.close()
                        await asyncio.sleep(sleep_time)
                        continue

                    return response

                except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                    last_exception = error
                    if attempt == self._max_retries - 1:
                        logger.error(
                            "Request to %s failed after %d retries: %s",
                            url,
                            self._max_retries,
                            error,
                        )
                        raise
                    sleep_time = self._backoff_factor * (2**attempt) + random.uniform(
                        0, 1
                    )
                    logger.warning(
                        "Request to %s failed (%s). Retrying in %.2f seconds...",
                        url,
                        error,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)

        raise RuntimeError(
            f"Request to '{url}' failed after {self._max_retries} retries: {last_exception}"
        )

    async def get(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """GET request returning parsed JSON as a dict."""
        response = await self._request(
            "GET", url, params=params, headers=headers, timeout=timeout
        )
        response.raise_for_status()
        return dict(await response.json())

    async def get_json(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """GET request returning raw parsed JSON (list or dict)."""
        response = await self._request(
            "GET", url, params=params, headers=headers, timeout=timeout
        )
        response.raise_for_status()
        return await response.json()

    async def get_bytes(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> bytes:
        """GET request returning raw bytes."""
        response = await self._request("GET", url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return await response.read()

    async def post(
        self,
        url: str,
        json_data: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """POST request returning parsed JSON."""
        response = await self._request(
            "POST", url, json_data=json_data, headers=headers, timeout=timeout
        )
        response.raise_for_status()
        return dict(await response.json())

    async def delete(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """DELETE request returning parsed JSON."""
        response = await self._request("DELETE", url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return dict(await response.json())
