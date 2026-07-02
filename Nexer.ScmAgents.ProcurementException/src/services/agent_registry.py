"""
Agent registry.

Keeps metadata about available agents, versions, owners, tenant access, and
operational status. This implementation is in-memory and seeded at startup.
"""

from enum import Enum
from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class AgentRegistryEntry(BaseModel):
    agent_id: str = Field(..., description="Unique agent identifier")
    agent_name: str = Field(..., description="Display name")
    agent_version: str = Field(..., description="Active agent version (MAJOR.MINOR.PATCH)")
    prompt_package_version: str = Field(..., description="Prompt package version in use")
    tool_contract_version: str = Field(..., description="Tool/API contract version in use")
    owner: str = Field(..., description="Owning team")
    status: AgentStatus = Field(default=AgentStatus.DRAFT, description="Operational status")
    allowed_tenants: list[str] = Field(
        default_factory=list,
        description="Tenants allowed to use this agent. Empty list = all tenants.",
    )
    description: str = Field(default="", description="What this agent does")


class AgentRegistry:
    """In-memory Agent Registry. Replace storage with Cosmos DB / Azure SQL in production."""

    def __init__(self) -> None:
        self._entries: dict[str, AgentRegistryEntry] = {}
        self._seed()

    def _seed(self) -> None:
        self.register(AgentRegistryEntry(
            agent_id="scm-orchestrator-agent",
            agent_name="SCM Orchestration Agent",
            agent_version="1.0.0",
            prompt_package_version="1.0.0",
            tool_contract_version="1.0.0",
            owner="AI Engineering Team",
            status=AgentStatus.ACTIVE,
            description="Routes SCM exception events to the appropriate specialist agent.",
        ))
        self.register(AgentRegistryEntry(
            agent_id="scm-procurement-exception-agent",
            agent_name="Procurement Exception Agent",
            agent_version="1.0.0",
            prompt_package_version="1.0.0",
            tool_contract_version="1.0.0",
            owner="AI Engineering Team / SCM Business Team",
            status=AgentStatus.ACTIVE,
            description="Analyzes procurement exceptions and produces Top 3 recommendations.",
        ))

    def register(self, entry: AgentRegistryEntry) -> None:
        self._entries[entry.agent_id] = entry

    def get(self, agent_id: str) -> AgentRegistryEntry | None:
        return self._entries.get(agent_id)

    def list_agents(self) -> list[AgentRegistryEntry]:
        return list(self._entries.values())

    def is_available(self, agent_id: str, tenant_id: str) -> bool:
        """Check that an agent is active and the tenant is allowed to use it."""
        entry = self._entries.get(agent_id)
        if entry is None or entry.status != AgentStatus.ACTIVE:
            return False
        return not entry.allowed_tenants or tenant_id in entry.allowed_tenants
