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
    AUTOCAT_MIN_LABELS: int = 21
    AUTOCAT_MIN_CATEGORIES: int = 2
    AUTOCAT_MIN_EXAMPLES_PER_CATEGORY: int = 3
    AUTOCAT_MAX_CATEGORY_CONCENTRATION: float = 0.85
    AUTOCAT_MIN_LABEL_TRUST: float = 0.90
    AUTOCAT_MIN_AVERAGE_TRUST: float = 0.90
    AUTOCAT_MIN_DESCRIPTION_COVERAGE: float = 0.60
    AUTOCAT_MIN_MACRO_F1: float = 0.35
    AUTOCAT_MIN_ACCURACY: float = 0.40
    AUTOCAT_MIN_BASELINE_LIFT: float = 0.0
    AUTOCAT_MAX_MACRO_F1_REGRESSION: float = 0.05
    AUTOCAT_SAFE_CONFIDENCE: float = 0.60
    AUTOCAT_TRAINING_COOLDOWN_SECONDS: int = 900

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
