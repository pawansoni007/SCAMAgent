"""
Chat conversation repository.

Handles conversation persistence in Cosmos DB.
"""

from datetime import datetime

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from integrations.cosmos.cosmos_client import get_chat_container
from models.chat_models import (
    ChatMessage,
    Conversation,
    ConversationSummary,
)


class ChatRepository:

    def __init__(self):
        self._container = get_chat_container()

    def create_conversation(
        self,
        conversation: Conversation,
    ) -> Conversation:
        document = self._to_document(conversation)

        self._container.create_item(document)

        return conversation

    def get_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Conversation | None:

        try:
            document = self._container.read_item(
                item=conversation_id,
                partition_key=user_id,
            )

            return self._from_document(document)

        except CosmosResourceNotFoundError:
            return None

    def save_conversation(
        self,
        conversation: Conversation,
    ) -> Conversation:

        conversation.updated_at = (
            datetime.utcnow().isoformat() + "Z"
        )

        document = self._to_document(conversation)

        self._container.upsert_item(document)

        return conversation

    def list_conversations(
        self,
        user_id: str,
        include_archived: bool = False,
    ) -> list[ConversationSummary]:

        query = """
        SELECT
            c.id,
            c.title,
            c.updatedAt,
            c.archived
        FROM c
        WHERE c.userId = @userId
          AND c.deleted = false
        """

        if not include_archived:
            query += " AND c.archived = false"

        query += " ORDER BY c.updatedAt DESC"

        items = list(
            self._container.query_items(
                query=query,
                parameters=[
                    {
                        "name": "@userId",
                        "value": user_id,
                    }
                ],
                partition_key=user_id,
            )
        )

        return [
            ConversationSummary(
                id=item["id"],
                title=item["title"],
                updated_at=item["updatedAt"],
                archived=item.get("archived", False),
            )
            for item in items
        ]

    def rename_conversation(
        self,
        conversation_id: str,
        user_id: str,
        title: str,
    ) -> bool:

        conversation = self.get_conversation(
            conversation_id,
            user_id,
        )

        if not conversation:
            return False

        conversation.title = title

        self.save_conversation(conversation)

        return True

    def archive_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:

        conversation = self.get_conversation(
            conversation_id,
            user_id,
        )

        if not conversation:
            return False

        conversation.archived = True

        self.save_conversation(conversation)

        return True
    
    def unarchive_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:

        conversation = self.get_conversation(
            conversation_id,
            user_id,
        )

        if not conversation:
            return False

        conversation.archived = False

        self.save_conversation(
            conversation
        )

        return True

    def delete_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:

        conversation = self.get_conversation(
            conversation_id,
            user_id,
        )

        if not conversation:
            return False

        conversation.deleted = True

        self.save_conversation(conversation)

        return True

    def _to_document(
        self,
        conversation: Conversation,
    ) -> dict:

        return {
            "id": conversation.id,
            "userId": conversation.user_id,
            "tenantId": conversation.tenant_id,
            "title": conversation.title,
            "archived": conversation.archived,
            "deleted": conversation.deleted,
            "createdAt": conversation.created_at,
            "updatedAt": conversation.updated_at,
            "messages": [
                message.model_dump()
                for message in conversation.messages
            ],
            "pendingAction": (
                conversation.pending_action.model_dump()
                if conversation.pending_action
                else None
            ),
            "agentSessionState": conversation.agent_session_state,
        }

    def _from_document(
        self,
        document: dict,
    ) -> Conversation:

        return Conversation(
            id=document["id"],
            user_id=document["userId"],
            tenant_id=document["tenantId"],
            title=document["title"],
            archived=document.get("archived", False),
            deleted=document.get("deleted", False),
            created_at=document["createdAt"],
            updated_at=document["updatedAt"],
            messages=[
                ChatMessage(**message)
                for message in document.get(
                    "messages",
                    [],
                )
            ],
            pending_action=document.get("pendingAction"),
            agent_session_state=document.get("agentSessionState"),
        )