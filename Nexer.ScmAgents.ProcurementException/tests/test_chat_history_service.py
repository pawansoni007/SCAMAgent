import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from models.chat_models import ChatMessage, Conversation
from services.chat_history_service import ChatHistoryService, InMemoryChatRepository


class ChatHistoryServicePendingActionTests(unittest.TestCase):
    def setUp(self):
        self.service = ChatHistoryService(repository=InMemoryChatRepository())

    def test_pending_action_is_stored_after_assistant_asks_to_continue(self):
        conversation = self.service.create_conversation(
            user_id="buyer@example.com",
            tenant_id="nexer-demo",
            first_message="Show overdue purchase orders.",
        )
        self.service.append_assistant_message(
            conversation.id,
            conversation.user_id,
            "There are additional pages available. Would you like the next page?",
        )

        updated = self.service.refresh_pending_action_after_assistant_reply(
            conversation.id,
            conversation.user_id,
        )

        self.assertIsNotNone(updated.pending_action)
        self.assertEqual(
            updated.pending_action.source_user_message,
            "Show overdue purchase orders.",
        )
        self.assertIn(
            "additional pages",
            updated.pending_action.assistant_message,
        )

    def test_confirmation_reply_executes_pending_action_in_prompt(self):
        conversation = Conversation(
            id="conv-1",
            user_id="buyer@example.com",
            tenant_id="nexer-demo",
            title="Draft PO",
            messages=[
                ChatMessage(
                    role="user",
                    content="Create a draft PO for ITEM001 from SUP001.",
                ),
                ChatMessage(
                    role="assistant",
                    content=(
                        "I can create the draft PO for ITEM001 from SUP001. "
                        "Please confirm before I proceed."
                    ),
                ),
                ChatMessage(role="user", content="go ahead"),
            ],
        )
        conversation.pending_action = self.service._infer_pending_action(
            conversation,
        )

        prompt = self.service.build_agent_prompt(conversation)

        self.assertIn("confirms or continues the pending assistant action", prompt)
        self.assertIn("Execute that pending action now", prompt)
        self.assertIn("Create a draft PO for ITEM001", prompt)

    def test_confirmation_words_are_supported_for_pending_actions(self):
        for reply in ("yes", "okay", "continue", "next", "go ahead", "proceed"):
            with self.subTest(reply=reply):
                conversation = Conversation(
                    id=f"conv-{reply}",
                    user_id="buyer@example.com",
                    tenant_id="nexer-demo",
                    title="Continuation",
                    messages=[
                        ChatMessage(role="user", content="Show overdue POs."),
                        ChatMessage(
                            role="assistant",
                            content=(
                                "Page 1 is shown. Additional pages are available. "
                                "Would you like to proceed with the next page?"
                            ),
                        ),
                        ChatMessage(role="user", content=reply),
                    ],
                )
                conversation.pending_action = self.service._infer_pending_action(
                    conversation,
                )

                self.assertTrue(
                    self.service.latest_message_confirms_pending_action(
                        conversation,
                    )
                )

    def test_pending_action_is_cleared_after_non_pending_assistant_reply(self):
        conversation = self.service.create_conversation(
            user_id="buyer@example.com",
            tenant_id="nexer-demo",
            first_message="Show overdue purchase orders.",
        )
        self.service.append_assistant_message(
            conversation.id,
            conversation.user_id,
            "There are additional pages available. Would you like the next page?",
        )
        self.service.refresh_pending_action_after_assistant_reply(
            conversation.id,
            conversation.user_id,
        )
        self.service.append_user_message(
            conversation.id,
            conversation.user_id,
            "next",
        )
        self.service.append_assistant_message(
            conversation.id,
            conversation.user_id,
            "Here is the next page of purchase orders.",
        )

        updated = self.service.refresh_pending_action_after_assistant_reply(
            conversation.id,
            conversation.user_id,
        )

        self.assertIsNone(updated.pending_action)

    def test_agent_session_state_round_trips(self):
        conversation = self.service.create_conversation(
            user_id="buyer@example.com",
            tenant_id="nexer-demo",
            first_message="Show overdue purchase orders.",
        )
        self.assertIsNone(conversation.agent_session_state)

        state = {
            "type": "session",
            "session_id": "abc-123",
            "service_session_id": None,
            "state": {
                "messages": [
                    {"type": "message", "role": "user", "contents": []},
                ]
            },
        }
        saved = self.service.save_agent_session_state(
            conversation.id,
            conversation.user_id,
            state,
        )
        self.assertIsNotNone(saved)

        reloaded = self.service.get_conversation(
            conversation.id,
            conversation.user_id,
        )
        self.assertEqual(reloaded.agent_session_state, state)

    def test_save_agent_session_state_missing_conversation_returns_none(self):
        self.assertIsNone(
            self.service.save_agent_session_state(
                "no-such-conversation",
                "buyer@example.com",
                {"type": "session"},
            )
        )


if __name__ == "__main__":
    unittest.main()
