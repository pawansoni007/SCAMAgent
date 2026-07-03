"""
Chat History Service.

Business layer for conversation management.
"""

import logging
import uuid
from datetime import datetime

from models.chat_models import (
    ChatMessage,
    Conversation,
    ConversationSummary,
    PendingAction,
)

from integrations.cosmos.chat_repository import ChatRepository

logger = logging.getLogger(__name__)

CONFIRMATION_REPLIES = {
    "yes",
    "y",
    "yeah",
    "yep",
    "ok",
    "okay",
    "continue",
    "next",
    "next page",
    "more",
    "show more",
    "go ahead",
    "proceed",
    "please proceed",
}

ACTION_REQUEST_MARKERS = (
    "would you like",
    "do you want",
    "shall i",
    "should i",
    "can i proceed",
    "please confirm",
    "confirm",
    "go ahead",
    "proceed",
    "next page",
    "additional pages",
    "show more",
    "continue",
    "create the draft",
    "create a draft",
)


class ChatHistoryService:

    def __init__(
        self,
        repository: ChatRepository | None = None,
    ):
        if repository:
            self._repository = repository
            return

        try:
            self._repository = ChatRepository()
        except Exception as exc:
            logger.warning(
                "Cosmos chat repository unavailable; using in-memory chat history. Error: %s",
                exc,
            )
            self._repository = InMemoryChatRepository()

    def create_conversation(
        self,
        user_id: str,
        tenant_id: str,
        first_message: str,
        title: str | None = None,
    ) -> Conversation:

        conversation = Conversation(
            id=uuid.uuid4().hex,
            user_id=user_id,
            tenant_id=tenant_id,
            title=(
                title
                or self._generate_title(
                    first_message
                )
            ),
            messages=[
                ChatMessage(
                    role="user",
                    content=first_message,
                )
            ],
        )

        return self._repository.create_conversation(
            conversation
        )

    def get_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Conversation | None:

        return self._repository.get_conversation(
            conversation_id,
            user_id,
        )
    
    def append_message(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> Conversation | None:

        conversation = self.get_conversation(
            conversation_id,
            user_id,
        )

        if not conversation:
            return None

        conversation.messages.append(
            ChatMessage(
                role=role,
                content=content,
            )
        )

        return self._repository.save_conversation(
            conversation
        )
    
    def list_conversations(
        self,
        user_id: str,
        include_archived: bool = False,
    ):
        return self._repository.list_conversations(
            user_id,
            include_archived,
        )
    
    def rename_conversation(
        self,
        conversation_id: str,
        user_id: str,
        title: str,
    ) -> bool:

        return self._repository.rename_conversation(
            conversation_id,
            user_id,
            title,
        )
        

    def archive_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:

        return self._repository.archive_conversation(
            conversation_id,
            user_id,
        )
    
    def unarchive_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:

        return (
            self._repository.unarchive_conversation(
                conversation_id,
                user_id,
            )
        )

    
    def delete_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:

        return self._repository.delete_conversation(
            conversation_id,
            user_id,
        )
    
    def build_history_prompt(
        self,
        conversation: Conversation,
    ) -> str:

        lines = []

        for msg in conversation.messages:

            role = (
                "User"
                if msg.role == "user"
                else "Assistant"
            )

            lines.append(
                f"{role}: {msg.content}"
            )

        return "\n\n".join(lines)


    def create_or_get_conversation(
        self,
        conversation_id: str | None,
        user_id: str,
        tenant_id: str,
        first_message: str,
        title: str | None = None,
    ) -> Conversation:

        if conversation_id:

            conversation = self.get_conversation(
                conversation_id,
                user_id,
            )

            if conversation:
                return conversation

        return self.create_conversation(
            user_id=user_id,
            tenant_id=tenant_id,
            first_message=first_message,
            title=title,
        )

    @staticmethod
    def _generate_title(
        text: str,
    ) -> str:
        """
        Temporary title generation.

        Later we can replace this with AI-generated titles.
        """

        text = text.strip()

        if len(text) <= 60:
            return text

        return text[:57] + "..."
    
    def build_continuation_prompt(
        self,
        conversation: Conversation,
    ) -> str:
        """
        Build a prompt from the persisted conversation history.

        The latest user message is already present in the
        conversation.messages collection.
        """

        return self.build_history_prompt(
            conversation
        )

    def build_agent_prompt(
        self,
        conversation: Conversation,
    ) -> str:
        """
        Build the LLM prompt, resolving short confirmations against pending state.

        The chat UI persists natural user text such as "yes" or "next". This
        method adds an internal system instruction when that text confirms a
        previously requested action, so the agent executes the prior tool/action
        instead of asking for clarification.
        """

        prompt = self.build_continuation_prompt(
            conversation
        )
        pending_action = self.pending_action_for_latest_message(
            conversation
        )
        if not pending_action:
            return prompt

        return (
            f"{prompt}\n\n"
            f"{self.pending_action_instruction(pending_action)}"
        )

    @staticmethod
    def pending_action_instruction(
        pending_action: PendingAction,
    ) -> str:
        """
        Internal system instruction that resolves a short confirmation
        ("yes", "next") against the pending assistant action.
        """

        return (
            "System: The latest buyer message confirms or continues the pending "
            "assistant action below. Execute that pending action now using the "
            "appropriate available tool(s) and the same context/filters from "
            "the prior request. Do not ask for clarification unless required "
            "arguments are genuinely missing. After executing, respond with the "
            "result for the buyer.\n"
            f"Pending action source request: {pending_action.source_user_message!r}\n"
            f"Pending assistant request: {pending_action.assistant_message!r}"
        )

    def pending_action_for_latest_message(
        self,
        conversation: Conversation,
    ) -> PendingAction | None:
        if not self.latest_message_confirms_pending_action(conversation):
            return None

        return conversation.pending_action or self._infer_pending_action(
            conversation,
        )

    def latest_message_confirms_pending_action(
        self,
        conversation: Conversation,
    ) -> bool:
        latest = self._latest_message(conversation)
        if latest is None or latest.role != "user":
            return False

        if latest.content.strip().lower() not in CONFIRMATION_REPLIES:
            return False

        return bool(
            conversation.pending_action
            or self._infer_pending_action(conversation)
        )

    def refresh_pending_action_after_assistant_reply(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Conversation | None:
        conversation = self.get_conversation(
            conversation_id,
            user_id,
        )
        if not conversation:
            return None

        conversation.pending_action = self._pending_action_from_latest_assistant(
            conversation,
        )

        return self._repository.save_conversation(
            conversation
        )
    
    def append_user_message(
        self,
        conversation_id: str,
        user_id: str,
        content: str,
    ):
        return self.append_message(
            conversation_id,
            user_id,
            "user",
            content,
        )


    def append_assistant_message(
        self,
        conversation_id: str,
        user_id: str,
        content: str,
    ):
        return self.append_message(
            conversation_id,
            user_id,
            "assistant",
            content,
        )

    @staticmethod
    def _latest_message(
        conversation: Conversation,
    ) -> ChatMessage | None:
        if not conversation.messages:
            return None
        return conversation.messages[-1]

    def _infer_pending_action(
        self,
        conversation: Conversation,
    ) -> PendingAction | None:
        previous_assistant = self._last_message_before_latest_user(
            conversation,
            role="assistant",
        )
        if not previous_assistant:
            return None

        if not self._assistant_requested_action(previous_assistant.content):
            return None

        previous_user = self._last_message_before_latest_user(
            conversation,
            role="user",
        )

        return PendingAction(
            source_user_message=previous_user.content if previous_user else "",
            assistant_message=previous_assistant.content,
        )

    def _pending_action_from_latest_assistant(
        self,
        conversation: Conversation,
    ) -> PendingAction | None:
        latest = self._latest_message(conversation)
        if latest is None or latest.role != "assistant":
            return None

        if not self._assistant_requested_action(latest.content):
            return None

        previous_user = self._last_message_before_index(
            conversation,
            role="user",
            before_index=len(conversation.messages) - 1,
        )

        return PendingAction(
            source_user_message=previous_user.content if previous_user else "",
            assistant_message=latest.content,
        )

    @staticmethod
    def _assistant_requested_action(
        text: str,
    ) -> bool:
        normalized = text.lower()
        if any(
            marker in normalized
            for marker in (
                "would you like",
                "do you want",
                "shall i",
                "should i",
                "can i proceed",
                "please confirm",
                "confirm before",
                "before i proceed",
            )
        ):
            return True

        if "?" not in text:
            return False

        return any(marker in normalized for marker in ACTION_REQUEST_MARKERS)

    def _last_message_before_latest_user(
        self,
        conversation: Conversation,
        *,
        role: str,
    ) -> ChatMessage | None:
        return self._last_message_before_index(
            conversation,
            role=role,
            before_index=len(conversation.messages) - 1,
        )

    @staticmethod
    def _last_message_before_index(
        conversation: Conversation,
        *,
        role: str,
        before_index: int,
    ) -> ChatMessage | None:
        for message in reversed(conversation.messages[:before_index]):
            if message.role == role:
                return message
        return None


class InMemoryChatRepository:
    """Local-development fallback when Cosmos DB settings are not configured."""

    def __init__(self):
        self._conversations: dict[tuple[str, str], Conversation] = {}

    def create_conversation(
        self,
        conversation: Conversation,
    ) -> Conversation:
        self._conversations[(conversation.user_id, conversation.id)] = conversation
        return conversation

    def get_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Conversation | None:
        return self._conversations.get((user_id, conversation_id))

    def save_conversation(
        self,
        conversation: Conversation,
    ) -> Conversation:
        conversation.updated_at = datetime.utcnow().isoformat() + "Z"
        self._conversations[(conversation.user_id, conversation.id)] = conversation
        return conversation

    def list_conversations(
        self,
        user_id: str,
        include_archived: bool = False,
    ) -> list[ConversationSummary]:
        conversations = [
            conversation
            for (stored_user_id, _), conversation in self._conversations.items()
            if stored_user_id == user_id
            and not conversation.deleted
            and (include_archived or not conversation.archived)
        ]
        conversations.sort(key=lambda conversation: conversation.updated_at, reverse=True)
        return [
            ConversationSummary(
                id=conversation.id,
                title=conversation.title,
                updated_at=conversation.updated_at,
                archived=conversation.archived,
            )
            for conversation in conversations
        ]

    def rename_conversation(
        self,
        conversation_id: str,
        user_id: str,
        title: str,
    ) -> bool:
        conversation = self.get_conversation(conversation_id, user_id)
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
        conversation = self.get_conversation(conversation_id, user_id)
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
        conversation = self.get_conversation(conversation_id, user_id)
        if not conversation:
            return False
        conversation.archived = False
        self.save_conversation(conversation)
        return True

    def delete_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:
        conversation = self.get_conversation(conversation_id, user_id)
        if not conversation:
            return False
        conversation.deleted = True
        self.save_conversation(conversation)
        return True