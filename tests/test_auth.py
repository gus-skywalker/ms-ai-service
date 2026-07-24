import asyncio
from types import SimpleNamespace

import httpx
from fastapi import HTTPException

from app.core import auth


def _settings():
    return SimpleNamespace(
        AUTH_SERVER_URL="https://auth.example",
        JWT_JWKS_PATH="/oauth2/jwks",
        AUTH_JWKS_TIMEOUT_SECONDS=0.1,
        AUTH_JWKS_CACHE_TTL_SECONDS=300,
        AUTH_JWKS_STALE_SECONDS=3600,
    )


def _reset_cache():
    auth._jwks_cache = None
    auth._jwks_cache_expires_at = 0.0
    auth._jwks_cache_stale_until = 0.0


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_fetch_jwks_uses_fresh_cache(monkeypatch):
    _reset_cache()
    calls = {"count": 0}

    class Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url):
            calls["count"] += 1
            return _Response({"keys": [{"kid": "one"}]})

    monkeypatch.setattr(auth, "get_settings", _settings)
    monkeypatch.setattr(auth.httpx, "AsyncClient", Client)

    first = asyncio.run(auth._fetch_jwks())
    second = asyncio.run(auth._fetch_jwks())

    assert first == second
    assert calls["count"] == 1


def test_fetch_jwks_returns_stale_cache_when_auth_server_fails(monkeypatch):
    _reset_cache()
    auth._jwks_cache = {"keys": [{"kid": "stale"}]}
    auth._jwks_cache_expires_at = 0.0
    auth._jwks_cache_stale_until = 9999999999.0

    class Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url):
            request = httpx.Request("GET", url)
            raise httpx.ConnectError("connection failed", request=request)

    monkeypatch.setattr(auth, "get_settings", _settings)
    monkeypatch.setattr(auth.httpx, "AsyncClient", Client)

    result = asyncio.run(auth._fetch_jwks())

    assert result == {"keys": [{"kid": "stale"}]}


def test_fetch_jwks_returns_503_when_auth_server_fails_without_cache(monkeypatch):
    _reset_cache()

    class Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url):
            request = httpx.Request("GET", url)
            raise httpx.ConnectError("connection failed", request=request)

    monkeypatch.setattr(auth, "get_settings", _settings)
    monkeypatch.setattr(auth.httpx, "AsyncClient", Client)

    try:
        asyncio.run(auth._fetch_jwks())
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail == "Authentication service temporarily unavailable"
