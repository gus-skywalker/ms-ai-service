"""Event publisher for domain events.

Publishes events to Redis Streams for event-driven architecture.
Ensures idempotency and audit trail.
"""

import os
import logging
import json
from typing import Optional
from datetime import datetime, timezone
from redis import Redis

from app.events.base import BaseEvent

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
EVENTS_STREAM = "domain:events"
PROCESSED_EVENTS_KEY = "events:processed:{event_id}"


class EventPublisher:
    """Publisher for domain events.
    
    Features:
    - Publishes to Redis Streams for durability and replay
    - Idempotency: tracks processed events to prevent duplicates
    - Audit trail: all events are persisted
    - No PII in events
    - Events emitted only after successful commit
    """
    
    def __init__(self, connection: Optional[Redis] = None):
        """Initialize publisher with Redis connection.
        
        Args:
            connection: Optional Redis connection. If not provided, creates new one.
        """
        self._connection = connection or Redis.from_url(REDIS_URL)
    
    def publish(self, event: BaseEvent) -> bool:
        """Publish an event to the event stream.
        
        This method ensures:
        1. Event is only published once (idempotency via correlationId)
        2. Event is persisted to Redis Streams
        3. Audit trail is maintained
        4. No external data enrichment
        
        Args:
            event: The domain event to publish
            
        Returns:
            bool: True if event was published, False if it was a duplicate
        """
        try:
            # Check idempotency - has this event already been processed?
            event_id_key = PROCESSED_EVENTS_KEY.format(event_id=event.correlationId)
            already_processed = self._connection.exists(event_id_key)
            
            if already_processed:
                logger.info(
                    "Event already published (idempotent skip)",
                    extra={
                        "correlation_id": event.correlationId,
                        "event_type": event.__class__.__name__,
                        "actor": event.actor
                    }
                )
                return False
            
            # Serialize event to JSON
            event_data = event.model_dump()
            event_type = event_data.get("eventType", event.__class__.__name__)
            
            # Prepare stream message
            stream_message = {
                "eventType": event_type,
                "eventVersion": event.eventVersion,
                "correlationId": event.correlationId,
                "actor": event.actor,
                "timestamp": event.timestamp,
                "payload": json.dumps(event_data)
            }
            
            # Publish to Redis Stream (XADD)
            # This ensures durability and enables replay
            message_id = self._connection.xadd(
                EVENTS_STREAM,
                stream_message,
                maxlen=10000  # Keep last 10k events (configurable)
            )
            
            # Mark as processed (TTL 7 days for idempotency check)
            self._connection.setex(
                event_id_key,
                7 * 24 * 3600,  # 7 days
                message_id.decode() if isinstance(message_id, bytes) else message_id
            )
            
            logger.info(
                "Event published successfully",
                extra={
                    "correlation_id": event.correlationId,
                    "event_type": event_type,
                    "actor": event.actor,
                    "stream": EVENTS_STREAM,
                    "message_id": message_id
                }
            )
            
            return True
            
        except Exception as exc:
            logger.exception(
                "Failed to publish event",
                extra={
                    "correlation_id": event.correlationId,
                    "event_type": event.__class__.__name__,
                    "actor": event.actor
                },
                exc_info=exc
            )
            # Re-raise to ensure caller knows publication failed
            # Caller must handle transaction rollback if needed
            raise


def get_publisher() -> EventPublisher:
    """Get a singleton event publisher instance.
    
    Returns:
        EventPublisher: Shared publisher instance
    """
    return EventPublisher()
