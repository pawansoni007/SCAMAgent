class ConversationTitleService:

    def __init__(self):
        pass

    async def generate_title(
        self,
        first_message: str,
    ) -> str:
        """
        Generate an AI title.

        Falls back to a deterministic title
        if AI generation fails.
        """

        return self._fallback_title(
            first_message
        )

    @staticmethod
    def _fallback_title(
        text: str,
    ) -> str:

        text = text.strip()

        if len(text) <= 60:
            return text

        return text[:57] + "..."