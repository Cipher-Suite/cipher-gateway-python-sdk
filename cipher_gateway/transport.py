# cipher_gateway/transport.py
"""
Low-level HTTP transport.
Handles all requests, auth headers, and error mapping.
Not used directly — use CipherGatewayClient instead.
"""
import logging
from typing import Any, Dict, Optional

import httpx

from .models import GatewayConfig
from .exceptions import (
    AuthenticationError,
    CipherGatewayError,
    GatewayResponseError,
    NotStartedError,
)

logger = logging.getLogger(__name__)


class HttpTransport:
    """
    Thin async HTTP wrapper around httpx.
    Handles auth header injection and error mapping.
    """

    def __init__(self, config: GatewayConfig):
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
                "Client not started — call start() or use async with"
            )

    async def get(self, path: str) -> Any:
        self._ensure_started()
        try:
            r = await self._client.get(path, headers=self._headers())
            return self._handle(r)
        except httpx.RequestError as e:
            raise CipherGatewayError(f"Request failed: {e}") from e

    async def post(self, path: str, json: Optional[Dict] = None) -> Any:
        self._ensure_started()
        try:
            r = await self._client.post(
                path, json=json or {}, headers=self._headers()
            )
            return self._handle(r)
        except httpx.RequestError as e:
            raise CipherGatewayError(f"Request failed: {e}") from e

    async def delete(self, path: str) -> Any:
        self._ensure_started()
        try:
            r = await self._client.delete(path, headers=self._headers())
            return self._handle(r)
        except httpx.RequestError as e:
            raise CipherGatewayError(f"Request failed: {e}") from e

    def _handle(self, response: httpx.Response) -> Any:
        """Map HTTP status codes to SDK exceptions"""
        if response.status_code == 200 or response.status_code == 201:
            try:
                return response.json()
            except Exception:
                return {}

        if response.status_code == 401:
            raise AuthenticationError("Invalid or missing API key")

        if response.status_code == 404:
            raise GatewayResponseError(
                "Resource not found",
                status_code=404,
                raw=response.text,
            )

        # Strip HTML error pages (nginx, etc.) before surfacing to user
        raw = response.text
        if '<html>' in raw.lower():
            detail = f"HTTP {response.status_code} — gateway/proxy error"
        else:
            detail = raw[:200]

        raise GatewayResponseError(
            detail,
            status_code=response.status_code,
            raw=raw,
        )
