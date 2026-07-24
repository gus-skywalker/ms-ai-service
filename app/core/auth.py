from __future__ import annotations
from typing import Optional
import httpx
import logging
import time
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from app.core.config import get_settings
import os

_http_bearer = HTTPBearer(auto_error=True)
_jwks_cache: Optional[dict] = None
_jwks_cache_expires_at: float = 0.0
_jwks_cache_stale_until: float = 0.0
_logger = logging.getLogger(__name__)

def verify_service_token(token: str) -> bool:
    if token is None:
        return False
    expected = os.getenv("AI_SERVICE_TOKEN") or get_settings().AI_SERVICE_TOKEN
    if expected is None or expected.strip() == "":
        return False
    return token.strip() == expected.strip()

async def _fetch_jwks(force_refresh: bool = False) -> dict:
    global _jwks_cache, _jwks_cache_expires_at, _jwks_cache_stale_until
    settings = get_settings()
    now = time.monotonic()
    if not force_refresh and _jwks_cache is not None and now < _jwks_cache_expires_at:
        return _jwks_cache

    jwks_url = settings.AUTH_SERVER_URL.rstrip("/") + settings.JWT_JWKS_PATH
    try:
        async with httpx.AsyncClient(timeout=settings.AUTH_JWKS_TIMEOUT_SECONDS) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_cache_expires_at = now + settings.AUTH_JWKS_CACHE_TTL_SECONDS
            _jwks_cache_stale_until = now + settings.AUTH_JWKS_STALE_SECONDS
            return _jwks_cache
    except (httpx.HTTPError, ValueError) as exc:
        if _jwks_cache is not None and now < _jwks_cache_stale_until:
            _logger.warning("Using stale JWKS cache after auth server fetch failed: %s", exc)
            return _jwks_cache
        _logger.warning("Unable to fetch JWKS from auth server: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc

async def _decode_token_with_jwks(token: str) -> dict:
    settings = get_settings()
    jwks = await _fetch_jwks()
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing 'kid' in token header",
        )
    key = None
    for jwk in jwks.get("keys", []):
        if jwk.get("kid") == kid:
            key = jwk
            break
    if key is None:
        jwks = await _fetch_jwks(force_refresh=True)
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == kid:
                key = jwk
                break
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find matching JWK",
        )
    try:
        options = {"verify_aud": bool(settings.JWT_AUDIENCE)}
        decoded = jwt.decode(
            token,
            key,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            options=options,
        )
        return decoded
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        ) from exc

async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_http_bearer),
) -> str:
    """Extract the userId from a validated JWT.
    Priority of claims: "userId" -> "user_id" -> "sub".
    """
    token = credentials.credentials
    payload = await _decode_token_with_jwks(token)
    user_id = (
        payload.get("userId")
        or payload.get("user_id")
        or payload.get("sub")
    )
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain a user identifier",
        )
    return str(user_id)
