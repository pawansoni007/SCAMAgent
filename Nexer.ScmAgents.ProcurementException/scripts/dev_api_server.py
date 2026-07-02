"""
Dev API Server — local stand-in for the Enterprise Gateway + Azure Functions layer.

Exposes the SCM agent pipeline over HTTP for the React UI:

  GET  /api/health                   liveness probe
  GET  /api/agents                   Agent Registry contents
  GET  /api/tenants                  registered tenants with rules summary
  GET  /api/reference-data           items / suppliers / event types for the UI form
  POST /api/procurement/analyze      run the full pipeline, return Top3Response + validation
  POST /api/approval/decision        record a human approval decision (mock)
  POST /api/chat                     buyer chat (multi-turn, session-based)

Run:
    cd Nexer.ScmAgents.ProcurementException
    .venv\\Scripts\\python.exe scripts\\dev_api_server.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import uuid

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent_framework import AgentSession

from functions.request_handler import validate_request, RequestValidationError
from functions.recommendation_validator import RecommendationValidator
from services.agent_registry import AgentRegistry
from services.prompt_registry import PromptRegistry
from services.tenant_config_service import TenantConfigService
from orchestrator.orchestrator_agent import OrchestratorAgent
from agents.procurement_exception_agent.buyer_chat_agent import BuyerChatAgent
from functions.reference_data_builder import build_reference_data

PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT",
    "https://scm-azure-foundry-dev.services.ai.azure.com/api/projects/scm-agent-dev",
)
MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4o")

app = FastAPI(title="SCM AI Agents Dev API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Runtime assets (step 5 of the blueprint architecture)
agent_registry = AgentRegistry()
prompt_registry = PromptRegistry()
tenant_config_service = TenantConfigService()
validator = RecommendationValidator()

# Orchestrator cache per tenant (instructions are tenant-specific)
_orchestrators: dict[str, OrchestratorAgent] = {}

# Buyer chat agents per tenant + active conversation sessions
_chat_agents: dict[str, BuyerChatAgent] = {}
_chat_sessions: dict[str, tuple[str, AgentSession]] = {}  # session_id -> (tenant_id, session)

DEFAULT_TENANT = "nexer-demo"

# In-memory record of human approval decisions
_decisions: list[dict] = []


def _get_orchestrator(tenant_id: str) -> OrchestratorAgent:
    if tenant_id not in _orchestrators:
        _orchestrators[tenant_id] = OrchestratorAgent(
            project_endpoint=PROJECT_ENDPOINT,
            model=MODEL,
            agent_registry=agent_registry,
            prompt_registry=prompt_registry,
            tenant_config=tenant_config_service.get_or_default(tenant_id),
        )
    return _orchestrators[tenant_id]


def _get_chat_agent(tenant_id: str) -> BuyerChatAgent:
    if tenant_id not in _chat_agents:
        _chat_agents[tenant_id] = BuyerChatAgent(
            project_endpoint=PROJECT_ENDPOINT,
            model=MODEL,
            prompt_registry=prompt_registry,
            tenant_config=tenant_config_service.get_or_default(tenant_id),
        )
    return _chat_agents[tenant_id]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/agents")
def list_agents():
    return [e.model_dump() for e in agent_registry.list_agents()]


@app.get("/api/tenants")
def list_tenants():
    return [
        {
            "tenant_id": tid,
            "rules": cfg.rules.model_dump(),
            "approval_policy": cfg.approval_policy.model_dump(),
        }
        for tid, cfg in tenant_config_service._configs.items()
    ]


@app.get("/api/reference-data")
def reference_data():
    return build_reference_data(list(tenant_config_service._configs.keys()))


@app.post("/api/procurement/analyze")
async def analyze(payload: dict):
    """Run the full pipeline: validate -> orchestrate -> rules engine -> validate output."""
    try:
        request = validate_request(payload, tenant_config_service, agent_registry)
    except RequestValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    tenant_config = tenant_config_service.get_or_default(request.event.tenant_id)
    orchestrator = _get_orchestrator(request.event.tenant_id)

    try:
        response = await orchestrator.route(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    validation = validator.validate(response, tenant_config)

    return {
        "response": response.model_dump(),
        "validation": validation.model_dump(),
    }


class ChatMessage(BaseModel):
    message: str
    session_id: str | None = None
    tenant_id: str = DEFAULT_TENANT


@app.post("/api/chat")
async def chat(payload: ChatMessage):
    """Buyer chat: multi-turn conversation with the Buyer Chat Agent.

    Omit session_id to start a new conversation; pass it back on subsequent
    messages to keep the conversation history (Agent Framework AgentSession).
    """
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message must not be empty.")

    agent = _get_chat_agent(payload.tenant_id)

    session_id = payload.session_id
    if session_id and session_id in _chat_sessions:
        tenant_id, session = _chat_sessions[session_id]
        if tenant_id != payload.tenant_id:
            raise HTTPException(
                status_code=400,
                detail="Session belongs to a different tenant. Start a new conversation.",
            )
    else:
        session_id = uuid.uuid4().hex
        session = agent.create_session()
        _chat_sessions[session_id] = (payload.tenant_id, session)

    try:
        reply = await agent.chat(text, session)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent error: {exc}")

    return {
        "session_id": session_id,
        "reply": reply,
        "agent_id": "scm-buyer-chat-agent",
        "tenant_id": payload.tenant_id,
    }


class ApprovalDecision(BaseModel):
    request_id: str
    rank: int
    decision: str  # approved | rejected | escalated
    comment: str = ""


@app.post("/api/approval/decision")
def record_decision(decision: ApprovalDecision):
    """Record the human decision. In production this triggers the Durable Functions
    approval lifecycle and, if approved, createPurchaseOrderDraft via the Business API Layer."""
    record = decision.model_dump()
    _decisions.append(record)
    next_step = (
        "createPurchaseOrderDraft will be invoked via the Business API Layer."
        if decision.decision == "approved"
        else "No ERP action will be taken."
    )
    return {"status": "recorded", "decision": record, "next_step": next_step}


if __name__ == "__main__":
    print("Dev API listening on http://127.0.0.1:7071/")
    uvicorn.run(app, host="127.0.0.1", port=7071)
