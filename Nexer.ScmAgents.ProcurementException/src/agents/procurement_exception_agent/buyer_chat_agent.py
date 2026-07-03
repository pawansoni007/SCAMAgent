"""
Buyer chat agent.

Conversational variant of the procurement agent. It uses the same tool contract
as the event workflow, but returns chat responses and keeps session history.
Draft PO creation still requires explicit buyer confirmation.
"""

from azure.core.credentials import TokenCredential
from agent_framework import Agent, AgentSession
from agent_framework_foundry import FoundryChatClient

from services.azure_credential import get_azure_credential
from services.prompt_registry import PromptRegistry
from services.tenant_config_service import TenantConfig
from agents.procurement_exception_agent.tools import BUYER_CHAT_TOOLS

AGENT_ID = "scm-buyer-chat-agent"
AGENT_VERSION = "1.0.0"


class BuyerChatAgent:
    """
    Conversational procurement assistant for the Buyer persona.

    Exposes:
      - create_session() : new AgentSession (in-memory conversation history)
      - chat()           : run one user message within a session, return reply text
    """

    def __init__(
        self,
        project_endpoint: str,
        model: str = "gpt-4o",
        credential: TokenCredential | None = None,
        tenant_config: TenantConfig | None = None,
        prompt_registry: PromptRegistry | None = None,
    ) -> None:
        registry = prompt_registry or PromptRegistry()
        package = registry.load_package(AGENT_ID)
        self.prompt_package_version = package.package_version
        self.prompt_metadata = {
            "agent_id": package.agent_id,
            "package_version": package.package_version,
            "model": package.model,
            "status": package.status,
            "environment": package.environment,
            "prompt_types": list(package.prompts.keys()),
        }

        variables = tenant_config.prompt_variables() if tenant_config else {}
        instructions = package.build_instructions(variables)
        if tenant_config:
            instructions += f"\n\nCURRENT TENANT: {tenant_config.tenant_id}"

        self._agent = Agent(
            client=FoundryChatClient(
                project_endpoint=project_endpoint,
                model=model,
                credential=credential or get_azure_credential(),
            ),
            name=AGENT_ID,
            description=(
                "Conversational Procurement Agent for Buyers. Answers questions "
                "about overdue and open purchase orders, suppliers, lead times, "
                "prices, inventory coverage and policies, and prepares draft POs "
                "after explicit buyer confirmation."
            ),
            instructions=instructions,
            tools=BUYER_CHAT_TOOLS,
            # Deterministic sampling: tool selection must not vary between
            # identical requests, and prompt changes must be evaluable
            # against a stable baseline (scripts/tool_selection_eval.py).
            default_options={"temperature": 0.0, "top_p": 1.0},
        )

    def create_session(self) -> AgentSession:
        """Start a new conversation (in-memory history provider)."""
        return self._agent.create_session()

    async def chat(self, message: str, session: AgentSession) -> str:
        """Send one buyer message within the given session and return the reply."""
        response = await self._agent.run(message, session=session)
        return response.text.strip()

    async def chat_with_prompt(
        self,
        prompt: str,
    ) -> str:
        """
        Run a prompt without relying on
        in-memory session history.
        """

        session = self.create_session()

        response = await self._agent.run(
            prompt,
            session=session,
        )

        return response.text.strip()