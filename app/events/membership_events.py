"""Membership domain events."""

from typing import Literal
from pydantic import Field
from app.events.base import BaseEvent


class MembershipCreated(BaseEvent):
    """Event emitted when a membership is created.
    
    Contains only IDs - no PII.
    Emitted after successful database commit.
    """
    
    eventType: Literal["MembershipCreated"] = "MembershipCreated"
    eventVersion: Literal["1.0.0"] = "1.0.0"
    
    # Domain IDs only - no PII
    membershipId: str = Field(description="Unique identifier of the membership")
    userId: str = Field(description="ID of the user who is a member")
    budgetId: str = Field(description="ID of the budget the user is a member of")
    role: str = Field(description="Role assigned to the member (e.g., 'owner', 'member')")
