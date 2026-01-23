"""Base event classes and types for event-driven architecture."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from uuid import uuid4


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
        default_factory=lambda: str(uuid4()),
        description="Correlation ID for request tracing"
    )
    actor: str = Field(description="Actor who triggered the event (user ID or system ID)")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp when event occurred"
    )
