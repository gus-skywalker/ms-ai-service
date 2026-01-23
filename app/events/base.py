"""Base event classes and types for event-driven architecture."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from uuid import uuid4


def _generate_correlation_id() -> str:
    """Generate a unique correlation ID for event tracing."""
    return str(uuid4())


def _generate_timestamp() -> str:
    """Generate an ISO 8601 timestamp in UTC."""
    return datetime.now(timezone.utc).isoformat()


class BaseEvent(BaseModel):
    """Base class for all domain events.
    
    Events must contain only IDs (no PII) and include:
    - eventVersion: schema version for evolution
    - correlationId: for request tracing
    - actor: who triggered the action (user/system ID)
    - timestamp: when the event occurred
    """
    
    model_config = ConfigDict(frozen=True)  # Events are immutable
    
    eventVersion: str = Field(description="Event schema version")
    correlationId: str = Field(
        default_factory=_generate_correlation_id,
        description="Correlation ID for request tracing"
    )
    actor: str = Field(description="Actor who triggered the event (user ID or system ID)")
    timestamp: str = Field(
        default_factory=_generate_timestamp,
        description="ISO 8601 timestamp when event occurred"
    )
