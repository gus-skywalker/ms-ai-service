"""Example usage of MembershipCreated event publisher.

This demonstrates the correct usage pattern for emitting events after
successful database commits in the budget-api service.
"""

from app.events.membership_events import MembershipCreated
from app.events.publisher import get_publisher


def create_membership_example():
    """Example: Creating a membership and publishing the event.
    
    This demonstrates the CORRECT pattern:
    1. Perform database operations
    2. Commit transaction
    3. ONLY AFTER successful commit, publish event
    4. Handle publication errors appropriately
    """
    
    # Step 1: Simulate database operations
    # In real code, this would be:
    # - Insert membership record
    # - Assign permissions
    # - Update related entities
    membership_id = "membership-abc-123"
    user_id = "user-def-456"
    budget_id = "budget-ghi-789"
    role = "owner"
    actor = user_id  # The user who created the membership
    correlation_id = "request-trace-xyz"  # From incoming request
    
    # Step 2: Database commit happens here
    # db.session.commit()
    # or transaction.commit()
    
    # Step 3: ONLY after successful commit, create and publish event
    try:
        event = MembershipCreated(
            membershipId=membership_id,
            userId=user_id,
            budgetId=budget_id,
            role=role,
            actor=actor,
            correlationId=correlation_id
        )
        
        publisher = get_publisher()
        success = publisher.publish(event)
        
        if success:
            print(f"✓ Event published: {event.eventType}")
        else:
            # Event was already published (idempotent)
            print(f"⚠ Event already published: {correlation_id}")
            
    except Exception as e:
        # If event publication fails, log it but don't rollback the transaction
        # The membership is already committed
        print(f"✗ Failed to publish event: {e}")
        # In production, this should trigger alerting
        # The event can be republished via reconciliation process


def create_membership_with_transaction_example():
    """Example: Using the publisher in a transaction context.
    
    IMPORTANT: Events MUST be published AFTER commit succeeds.
    """
    
    # Simulated transaction context
    # transaction = begin_transaction()
    
    try:
        # Database operations
        membership_id = "membership-xyz-789"
        user_id = "user-abc-123"
        budget_id = "budget-def-456"
        role = "member"
        
        # ... insert membership ...
        # ... update related records ...
        
        # COMMIT FIRST
        # transaction.commit()
        
        # THEN publish event (after commit succeeds)
        event = MembershipCreated(
            membershipId=membership_id,
            userId=user_id,
            budgetId=budget_id,
            role=role,
            actor=user_id
        )
        
        publisher = get_publisher()
        publisher.publish(event)
        
    except Exception as e:
        # If commit fails, no event is published (correct)
        # transaction.rollback()
        print(f"✗ Transaction failed, no event published: {e}")
        raise


def incorrect_pattern_example():
    """WRONG: Publishing event before commit.
    
    DO NOT DO THIS - it can lead to:
    - Events for uncommitted data
    - Inconsistent state if transaction rolls back
    - Out-of-order processing issues
    """
    
    # ❌ WRONG PATTERN ❌
    # transaction = begin_transaction()
    
    # event = MembershipCreated(...)
    # publisher.publish(event)  # ❌ WRONG - before commit
    
    # db.insert_membership(...)
    # transaction.commit()  # What if this fails? Event already published!
    
    pass  # Don't implement this pattern


def event_payload_guidelines():
    """Guidelines for event payloads.
    
    ✓ DO:
    - Include only IDs (membershipId, userId, budgetId)
    - Include correlationId for tracing
    - Include actor for audit trail
    - Include eventVersion for schema evolution
    - Keep events immutable
    
    ✗ DON'T:
    - Include PII (names, emails, phone numbers)
    - Include sensitive data (passwords, tokens)
    - Enrich with external data
    - Couple to consumer expectations
    - Assume synchronous processing
    """
    
    # ✓ GOOD: Only IDs
    event = MembershipCreated(
        membershipId="membership-123",
        userId="user-456",
        budgetId="budget-789",
        role="owner",
        actor="user-456",
        correlationId="trace-abc"
    )
    
    # ❌ BAD: Would include PII (if we added these fields)
    # event.userName = "John Doe"  # ❌ PII
    # event.userEmail = "john@example.com"  # ❌ PII
    # event.budgetName = "Family Budget"  # ❌ Business data
    
    return event


def idempotency_example():
    """Example: Handling idempotent event publishing.
    
    Events with the same correlationId will only be published once.
    This prevents duplicate events from retries or reprocessing.
    """
    
    correlation_id = "request-abc-123"
    
    # First publish - succeeds
    event1 = MembershipCreated(
        membershipId="membership-1",
        userId="user-1",
        budgetId="budget-1",
        role="owner",
        actor="user-1",
        correlationId=correlation_id
    )
    
    publisher = get_publisher()
    result1 = publisher.publish(event1)
    print(f"First publish: {result1}")  # True
    
    # Second publish with same correlationId - skipped
    event2 = MembershipCreated(
        membershipId="membership-2",  # Different data
        userId="user-2",
        budgetId="budget-2",
        role="member",
        actor="user-2",
        correlationId=correlation_id  # Same correlationId
    )
    
    result2 = publisher.publish(event2)
    print(f"Second publish (duplicate): {result2}")  # False (idempotent)
    
    # This ensures:
    # - Retry safety
    # - No duplicate processing
    # - Consistent audit trail


if __name__ == "__main__":
    # Run examples
    print("=== Correct usage pattern ===")
    create_membership_example()
    
    print("\n=== Event payload guidelines ===")
    event = event_payload_guidelines()
    print(f"Event type: {event.eventType}")
    print(f"Event version: {event.eventVersion}")
    print(f"Has PII: No")
    
    print("\n=== Idempotency example ===")
    idempotency_example()
