# tonpo-py/transport.py
"""
Low-level HTTP transport.
Handles all requests, auth headers, and HTTP-status → exception mapping.
Not used directly — use TonpoClient instead.
"""
import logging
from typing import Any, Dict, Optional

import httpx

from .models import TonpoConfig
from .exceptions import (
    AuthenticationError,
    TonpoError,
    TonpoConnectionError,
    TonpoResponseError,
    NotStartedError,
)

logger = logging.getLogger(__name__)


class HttpTransport:
    """
    Thin async HTTP wrapper around httpx.
    Handles auth-header injection and HTTP-status → exception mapping.
    """

    def __init__(self, config: TonpoConfig):
        self._config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._api_key: Optional[str] = None

    async def start(self):
        self._client = httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=self._config.request_timeout,
            limits=httpx.Limits(max_keepalive_connections=10),
        )

    async def stop(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def set_api_key(self, api_key: str):
        self._api_key = api_key

    def _headers(self) -> Dict[str, str]:
        if self._api_key:
            return {self._config.api_key_header: self._api_key}
        return {}

    def _ensure_started(self):
        if not self._client:
            raise NotStartedError(
                "Client not started — call start() or use 'async with'"
            )

    async def get(self, path: str) -> Any:
        self._ensure_started()
        try:
            r = await self._client.get(path, headers=self._headers())
            return self._handle(r)
        except httpx.RequestError as e:
            raise TonpoConnectionError(f"GET {path} failed: {e}") from e

    async def post(self, path: str, json: Optional[Dict] = None) -> Any:
        self._ensure_started()
        try:
            r = await self._client.post(
                path, json=json or {}, headers=self._headers()
            )
            return self._handle(r)
        except httpx.RequestError as e:
            raise TonpoConnectionError(f"POST {path} failed: {e}") from e

    async def delete(self, path: str) -> Any:
        self._ensure_started()
        try:
            r = await self._client.delete(path, headers=self._headers())
            return self._handle(r)
        except httpx.RequestError as e:
            raise TonpoConnectionError(f"DELETE {path} failed: {e}") from e
            
    async def patch(self, path: str, json: Optional[Dict] = None) -> Any:
        """Send a PATCH request."""
        self._ensure_started()
        try:
            r = await self._client.patch(
                path, json=json or {}, headers=self._headers()
            )
            return self._handle(r)
        except httpx.RequestError as e:
            raise TonpoConnectionError(f"PATCH {path} failed: {e}") from e
            
    def _handle(self, response: httpx.Response) -> Any:
        """Map HTTP status codes to SDK exceptions."""
        code = response.status_code

        # Success
        if code in (200, 201):
            try:
                return response.json()
            except Exception:
                return {}

        # 204 No Content — success with empty body
        if code == 204:
            return {}

        # Auth failure
        if code == 401:
            raise AuthenticationError("Invalid or missing API key")

        if code == 403:
            raise AuthenticationError("Permission denied — check API key scope")

        if code == 404:
            from .exceptions import AccountNotFoundError
            raise AccountNotFoundError(
                f"Resource not found (404): {response.url.path}"
            )

        # Strip HTML error pages (nginx/proxy) before surfacing to user
        raw = response.text
        if "<html>" in raw.lower():
            detail = f"HTTP {code} — tonpo/proxy error (see raw for details)"
        else:
            detail = raw[:300]

        raise TonpoResponseError(
            detail,
            status_code=code,
            raw=raw,
        )
