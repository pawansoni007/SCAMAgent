from agent_framework import Agent
from agent_framework_foundry import FoundryChatClient

from services.azure_credential import get_azure_credential


class TitleGenerationAgent:

    def __init__(
        self,
        project_endpoint: str,
        model: str = "gpt-4o",
    ):
        self._agent = Agent(
            client=FoundryChatClient(
                project_endpoint=project_endpoint,
                model=model,
                credential=get_azure_credential(),
            ),
            name="conversation-title-agent",
            description="Generates short conversation titles.",
            instructions="""
You generate conversation titles.

Rules:
- Maximum 6 words.
- Professional business language.
- No quotation marks.
- No punctuation at the end.
- Return title only.
- Never explain your answer.
""",
        )

    async def generate_title(
        self,
        first_message: str,
    ) -> str:

        session = self._agent.create_session()

        response = await self._agent.run(
            f"Generate a title for: {first_message}",
            session=session,
        )

        return response.text.strip()