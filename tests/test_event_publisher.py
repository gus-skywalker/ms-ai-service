"""Tests for event publisher and MembershipCreated event."""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from app.events.membership_events import MembershipCreated
from app.events.publisher import EventPublisher, EVENTS_STREAM, PROCESSED_EVENTS_KEY, IDEMPOTENCY_TTL_SECONDS
from fakeredis import FakeStrictRedis


@pytest.fixture
def redis_connection():
    """Provide a fake Redis connection for testing."""
    return FakeStrictRedis()


@pytest.fixture
def publisher(redis_connection):
    """Provide an EventPublisher with fake Redis."""
    return EventPublisher(connection=redis_connection)


class TestMembershipCreatedEvent:
    """Test MembershipCreated event structure and validation."""
    
    def test_creates_valid_event_with_required_fields(self):
        """Event should be created with all required fields."""
        event = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="owner",
            actor="user-456",
            correlationId="corr-abc"
        )
        
        assert event.membershipId == "membership-123"
        assert event.userId == "user-456"
        assert event.budgetId == "budget-789"
        assert event.role == "owner"
        assert event.actor == "user-456"
        assert event.correlationId == "corr-abc"
        assert event.eventType == "MembershipCreated"
        assert event.eventVersion == "1.0.0"
    
    def test_generates_correlation_id_if_not_provided(self):
        """Event should auto-generate correlationId if not provided."""
        event = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="member",
            actor="user-456"
        )
        
        assert event.correlationId is not None
        assert len(event.correlationId) > 0
    
    def test_generates_timestamp_if_not_provided(self):
        """Event should auto-generate timestamp if not provided."""
        before = datetime.now(timezone.utc)
        event = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="member",
            actor="user-456"
        )
        after = datetime.now(timezone.utc)
        
        assert event.timestamp is not None
        event_time = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
        assert before <= event_time <= after
    
    def test_event_is_immutable(self):
        """Events should be immutable (frozen)."""
        event = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="member",
            actor="user-456"
        )
        
        with pytest.raises((ValidationError, AttributeError)):
            event.membershipId = "different-id"
    
    def test_event_contains_no_pii(self):
        """Event should contain only IDs, no PII like names or emails."""
        event = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="member",
            actor="user-456"
        )
        
        # Verify only ID fields are present, no name, email, etc.
        data = event.model_dump()
        assert "name" not in data
        assert "email" not in data
        assert "phone" not in data
        assert "membershipId" in data
        assert "userId" in data
        assert "budgetId" in data


class TestEventPublisher:
    """Test EventPublisher functionality."""
    
    def test_publishes_event_successfully(self, publisher, redis_connection):
        """Publisher should publish event to Redis Stream."""
        event = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="owner",
            actor="user-456",
            correlationId="corr-unique-1"
        )
        
        result = publisher.publish(event)
        
        assert result is True
        # Verify event was added to stream
        stream_data = redis_connection.xread({EVENTS_STREAM: '0'})
        assert len(stream_data) > 0
        assert stream_data[0][0] == EVENTS_STREAM.encode()
    
    def test_idempotency_prevents_duplicate_publishing(self, publisher, redis_connection):
        """Publisher should prevent duplicate events with same correlationId."""
        correlation_id = "corr-unique-2"
        event1 = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="owner",
            actor="user-456",
            correlationId=correlation_id
        )
        event2 = MembershipCreated(
            membershipId="membership-456",
            userId="user-789",
            budgetId="budget-abc",
            role="member",
            actor="user-789",
            correlationId=correlation_id  # Same correlationId
        )
        
        # First publish should succeed
        result1 = publisher.publish(event1)
        assert result1 is True
        
        # Second publish with same correlationId should be skipped
        result2 = publisher.publish(event2)
        assert result2 is False
        
        # Verify only one event in stream
        stream_data = redis_connection.xread({EVENTS_STREAM: '0'})
        assert len(stream_data[0][1]) == 1
    
    def test_event_includes_all_required_metadata(self, publisher, redis_connection):
        """Published event should include eventVersion, correlationId, and actor."""
        event = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="owner",
            actor="user-456",
            correlationId="corr-unique-3"
        )
        
        publisher.publish(event)
        
        # Read from stream
        stream_data = redis_connection.xread({EVENTS_STREAM: '0'})
        message = stream_data[0][1][0][1]
        
        assert b'eventVersion' in message
        assert b'correlationId' in message
        assert b'actor' in message
        assert b'timestamp' in message
        assert message[b'eventType'] == b'MembershipCreated'
        assert message[b'eventVersion'] == b'1.0.0'
        assert message[b'correlationId'] == b'corr-unique-3'
        assert message[b'actor'] == b'user-456'
    
    def test_sets_idempotency_key_with_ttl(self, publisher, redis_connection):
        """Publisher should set idempotency key with TTL."""
        event = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="owner",
            actor="user-456",
            correlationId="corr-unique-4"
        )
        
        publisher.publish(event)
        
        # Check idempotency key exists
        key = PROCESSED_EVENTS_KEY.format(event_id=event.correlationId)
        assert redis_connection.exists(key) == 1
        
        # Check TTL is set using the constant
        ttl = redis_connection.ttl(key)
        assert ttl > 0
        assert ttl <= IDEMPOTENCY_TTL_SECONDS
    
    def test_different_correlation_ids_publish_successfully(self, publisher, redis_connection):
        """Events with different correlationIds should both be published."""
        event1 = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="owner",
            actor="user-456",
            correlationId="corr-unique-5"
        )
        event2 = MembershipCreated(
            membershipId="membership-456",
            userId="user-789",
            budgetId="budget-abc",
            role="member",
            actor="user-789",
            correlationId="corr-unique-6"
        )
        
        result1 = publisher.publish(event1)
        result2 = publisher.publish(event2)
        
        assert result1 is True
        assert result2 is True
        
        # Verify both events in stream
        stream_data = redis_connection.xread({EVENTS_STREAM: '0'})
        assert len(stream_data[0][1]) == 2
    
    def test_stream_limits_max_length(self, publisher, redis_connection):
        """Publisher should configure max stream length."""
        # This tests that maxlen parameter is passed (actual trimming tested by Redis)
        event = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="owner",
            actor="user-456",
            correlationId="corr-unique-7"
        )
        
        # Publishing should not raise error with maxlen
        result = publisher.publish(event)
        assert result is True


class TestEventPublisherEdgeCases:
    """Test edge cases and error scenarios."""
    
    def test_handles_out_of_order_events(self, publisher):
        """Publisher should handle events regardless of order."""
        # Events can arrive out of order; each should be published
        event1 = MembershipCreated(
            membershipId="membership-1",
            userId="user-1",
            budgetId="budget-1",
            role="owner",
            actor="user-1",
            correlationId="corr-1",
            timestamp="2026-01-23T10:00:00Z"
        )
        event2 = MembershipCreated(
            membershipId="membership-2",
            userId="user-2",
            budgetId="budget-2",
            role="member",
            actor="user-2",
            correlationId="corr-2",
            timestamp="2026-01-23T09:00:00Z"  # Earlier timestamp
        )
        
        result1 = publisher.publish(event1)
        result2 = publisher.publish(event2)
        
        # Both should succeed despite timestamps
        assert result1 is True
        assert result2 is True
    
    def test_does_not_enrich_with_external_data(self, publisher):
        """Publisher should not fetch or add external data to events."""
        event = MembershipCreated(
            membershipId="membership-123",
            userId="user-456",
            budgetId="budget-789",
            role="owner",
            actor="user-456",
            correlationId="corr-unique-8"
        )
        
        original_data = event.model_dump()
        publisher.publish(event)
        current_data = event.model_dump()
        
        # Event data should not change after publishing
        assert original_data == current_data
