"""Synchronous test facade over httpx ASGITransport and real app lifespan."""

from __future__ import annotations

import asyncio
from types import TracebackType

import httpx
from fastapi import FastAPI


class SyncASGIClient:
    __test__ = False

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    def __enter__(self) -> "SyncASGIClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        return asyncio.run(self._request(method, url, **kwargs))

    def stream(self, method: str, url: str, **kwargs: object) -> _LoadedResponse:
        return _LoadedResponse(self.request(method, url, **kwargs))

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: object,
    ) -> httpx.Response:
        async with self._app.router.lifespan_context(self._app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(
                    app=self._app,
                    raise_app_exceptions=False,
                ),
                base_url="http://testserver",
            ) as client:
                return await client.request(method, url, **kwargs)


class _LoadedResponse:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    def __enter__(self) -> httpx.Response:
        return self._response

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._response.close()
