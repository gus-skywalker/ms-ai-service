from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for the AI microservice."""

    AUTH_SERVER_URL: str = "http://localhost:9000"
    JWT_JWKS_PATH: str = "/oauth2/jwks"
    JWT_ALGORITHM: str = "RS256"
    JWT_AUDIENCE: Optional[str] = None
    AUTH_JWKS_TIMEOUT_SECONDS: float = 3.0
    AUTH_JWKS_CACHE_TTL_SECONDS: int = 300
    AUTH_JWKS_STALE_SECONDS: int = 3600
    AI_SERVICE_TOKEN: Optional[str] = "testtoken"
    AI_MODEL_DIR: str = "./models"

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
