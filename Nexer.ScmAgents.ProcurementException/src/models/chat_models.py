"""
Chat History domain models.

Enterprise conversation persistence for Buyer Chat Agent.

These models are persisted to Cosmos DB and are used to:
- Store conversation history
- Display conversation lists
- Rebuild AgentSession context
"""

from datetime import datetime
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Single message within a conversation."""

    role: str = Field(
        ...,
        description="user | assistant | system",
    )

    content: str = Field(
        ...,
        description="Message text",
    )

    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="UTC timestamp",
    )


class PendingAction(BaseModel):
    """Action the assistant asked the buyer to confirm or continue."""

    kind: str = Field(
        default="agent_action",
        description="Generic pending agent action type",
    )

    source_user_message: str = Field(
        default="",
        description="Buyer request that led to the pending action",
    )

    assistant_message: str = Field(
        default="",
        description="Assistant message that requested confirmation",
    )

    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
    )


class Conversation(BaseModel):
    """
    Persisted conversation document.

    Stored as a single Cosmos document.
    """

    id: str = Field(
        ...,
        description="Conversation ID",
    )

    user_id: str = Field(
        ...,
        description="Authenticated user identifier",
    )

    tenant_id: str = Field(
        ...,
        description="Tenant identifier",
    )

    title: str = Field(
        ...,
        description="Conversation title",
    )

    archived: bool = Field(
        default=False,
    )

    deleted: bool = Field(
        default=False,
    )

    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
    )

    updated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
    )

    messages: list[ChatMessage] = Field(
        default_factory=list,
    )

    pending_action: PendingAction | None = Field(
        default=None,
        description="Pending action awaiting buyer confirmation or continuation",
    )

    agent_session_state: dict | None = Field(
        default=None,
        description=(
            "Serialized AgentSession (AgentSession.to_dict) so chat "
            "continuity, including tool calls/results, survives instance "
            "recycling on Consumption/Flex plans"
        ),
    )


class ConversationSummary(BaseModel):
    """
    Lightweight model used for conversation sidebar listing.
    """

    id: str

    title: str

    updated_at: str

    archived: bool = False