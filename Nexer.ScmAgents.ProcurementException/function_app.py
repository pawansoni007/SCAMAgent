"""
Azure Functions application entry point.
"""
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import azure.functions as func
import azure.durable_functions as df
from azure.data.tables import TableServiceClient

from functions.request_handler import validate_request, RequestValidationError
from functions.recommendation_validator import RecommendationValidator
from services.agent_registry import AgentRegistry
from services.prompt_registry import PromptRegistry
from services.tenant_config_service import TenantConfigService
from services.chat_history_service import ChatHistoryService

PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT",
    "https://scm-azure-foundry-dev.services.ai.azure.com/api/projects/scm-agent-dev",
)
MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4o")
APPROVAL_TIMEOUT_HOURS = 24
DEFAULT_TENANT = "nexer-demo"
DEFAULT_USER_ID = "buyer@nexer-demo.com"

app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

agent_registry = AgentRegistry()
prompt_registry = PromptRegistry()
tenant_config_service = TenantConfigService()
validator = RecommendationValidator()
chat_history_service = ChatHistoryService()

from services.conversation_title_service import (
    ConversationTitleService,
)

conversation_title_service = (
    ConversationTitleService()
)

_orchestrators: dict = {}
_chat_agents: dict = {}

# conversation_id -> AgentSession. The session's history provider keeps the
# structured message list (including tool calls/results), which the flat
# text transcript persisted in Cosmos cannot represent. Memory-only: on a
# cold start or eviction the chat route falls back to seeding a fresh
# session from the persisted transcript.
from collections import OrderedDict

_chat_sessions: "OrderedDict[str, object]" = OrderedDict()
_CHAT_SESSION_CACHE_MAX = 200


def _get_cached_chat_session(conversation_id: str):
    session = _chat_sessions.get(conversation_id)
    if session is not None:
        _chat_sessions.move_to_end(conversation_id)
    return session


def _store_chat_session(conversation_id: str, session) -> None:
    _chat_sessions[conversation_id] = session
    _chat_sessions.move_to_end(conversation_id)
    while len(_chat_sessions) > _CHAT_SESSION_CACHE_MAX:
        _chat_sessions.popitem(last=False)


def _drop_chat_session(conversation_id: str) -> None:
    _chat_sessions.pop(conversation_id, None)


_SESSION_STATE_MAX_MESSAGES = 40


def _trimmed_session_state(session) -> dict:
    """
    Serialize a session for persistence, keeping only a bounded tail of
    messages. The cut advances to the next user message so a function_call
    is never separated from its function_result, and the Cosmos document
    stays well under the 2 MB item limit.
    """
    state = session.to_dict()
    messages = (state.get("state") or {}).get("messages") or []
    if len(messages) > _SESSION_STATE_MAX_MESSAGES:
        start = len(messages) - _SESSION_STATE_MAX_MESSAGES
        while start < len(messages) and messages[start].get("role") != "user":
            start += 1
        state["state"]["messages"] = messages[start:]
    return state

# ---------------------------------------------------------------------------
# Table Storage helpers
# ---------------------------------------------------------------------------

_TABLE_CONN = os.environ.get("AzureWebJobsStorage", "UseDevelopmentStorage=true")

def _get_table(name: str):
    svc = TableServiceClient.from_connection_string(_TABLE_CONN)
    client = svc.get_table_client(name)
    try:
        client.create_table()
    except Exception:
        pass
    return client


def _save_exception(event, response, instance_id: str):
    try:
        table = _get_table("exceptions")
        table.upsert_entity({
            "PartitionKey": event.tenant_id,
            "RowKey": response.request_id,
            "data": json.dumps({
                "id": response.request_id,
                "tenant_id": event.tenant_id,
                "item_id": event.item_id,
                "plant": event.plant,
                "event_type": event.event_type,
                "severity": getattr(event, "severity", "medium") or "medium",
                "status": "pending",
                "instance_id": instance_id,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            })
        })
    except Exception as exc:
        logging.warning("Failed to save exception: %s", exc)


def _resolve_exception(request_id: str, tenant_id: str, decision: str, comment: str, rank):
    try:
        exc_table = _get_table("exceptions")
        hist_table = _get_table("exceptionhistory")

        # Find entity — try provided tenant_id first, then scan
        entity = None
        try:
            entity = exc_table.get_entity(partition_key=tenant_id, row_key=request_id)
        except Exception:
            for e in exc_table.list_entities():
                if e["RowKey"] == request_id:
                    entity = e
                    break

        if entity is None:
            logging.warning("Exception %s not found in table", request_id)
            return

        data = json.loads(entity["data"])
        data["status"] = decision
        data["final_status"] = decision
        data["resolved_at"] = datetime.utcnow().isoformat()
        data["updated_at"] = datetime.utcnow().isoformat()
        data["selected_rank"] = rank
        data["audit_trail"] = [{
            "id": uuid.uuid4().hex,
            "action": decision,
            "performed_by": "buyer",
            "performed_at": datetime.utcnow().isoformat(),
            "notes": comment or "",
            "selected_rank": rank,
        }]

        hist_table.upsert_entity({
            "PartitionKey": data["tenant_id"],
            "RowKey": request_id,
            "data": json.dumps(data)
        })

        exc_table.delete_entity(
            partition_key=entity["PartitionKey"],
            row_key=request_id
        )
    except Exception as exc:
        logging.warning("Failed to resolve exception: %s", exc)


# ---------------------------------------------------------------------------
# Lazy getters
# ---------------------------------------------------------------------------

def _get_orchestrator(tenant_id: str):
    from orchestrator.orchestrator_agent import OrchestratorAgent
    if tenant_id not in _orchestrators:
        _orchestrators[tenant_id] = OrchestratorAgent(
            project_endpoint=PROJECT_ENDPOINT,
            model=MODEL,
            agent_registry=agent_registry,
            prompt_registry=prompt_registry,
            tenant_config=tenant_config_service.get_or_default(tenant_id),
        )
    return _orchestrators[tenant_id]


def _get_chat_agent(tenant_id: str):
    from agents.procurement_exception_agent.buyer_chat_agent import BuyerChatAgent
    if tenant_id not in _chat_agents:
        logging.info(
            "Creating buyer chat agent "
            "(tenant_id=%s, foundry_project_endpoint=%s, foundry_model=%s)",
            tenant_id,
            PROJECT_ENDPOINT,
            MODEL,
        )
        _chat_agents[tenant_id] = BuyerChatAgent(
            project_endpoint=PROJECT_ENDPOINT,
            model=MODEL,
            prompt_registry=prompt_registry,
            tenant_config=tenant_config_service.get_or_default(tenant_id),
        )
    else:
        logging.info(
            "Reusing buyer chat agent "
            "(tenant_id=%s, foundry_project_endpoint=%s, foundry_model=%s)",
            tenant_id,
            PROJECT_ENDPOINT,
            MODEL,
        )
    return _chat_agents[tenant_id]


def _json(data, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data), status_code=status_code, mimetype="application/json"
    )


def _error(detail: str, status_code: int) -> func.HttpResponse:
    return _json({"detail": detail}, status_code)


# ---------------------------------------------------------------------------
# Read-only HTTP triggers
# ---------------------------------------------------------------------------

@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json({"status": "ok", "host": "azure-functions"})


@app.route(route="agents", methods=["GET"])
def list_agents(req: func.HttpRequest) -> func.HttpResponse:
    return _json([e.model_dump() for e in agent_registry.list_agents()])


@app.route(route="tenants", methods=["GET"])
def list_tenants(req: func.HttpRequest) -> func.HttpResponse:
    return _json([
        {
            "tenant_id": tid,
            "rules": cfg.rules.model_dump(),
            "approval_policy": cfg.approval_policy.model_dump(),
        }
        for tid, cfg in tenant_config_service._configs.items()
    ])


@app.route(route="reference-data", methods=["GET"])
def reference_data(req: func.HttpRequest) -> func.HttpResponse:
    from functions.reference_data_builder import build_reference_data

    tenant_ids = list(tenant_config_service._configs.keys())
    logging.info(
        "Reference data request received (tenant_count=%s, tenants=%s)",
        len(tenant_ids),
        tenant_ids,
    )
    try:
        payload = build_reference_data(tenant_ids)
        logging.info(
            "Reference data request completed "
            "(items=%s, supplier_groups=%s, po_groups=%s, has_event_sample=%s)",
            len(payload.get("items") or []),
            len(payload.get("suppliers_by_item") or {}),
            len(payload.get("purchase_orders_by_item") or {}),
            bool(payload.get("event_sample")),
        )
        return _json(payload)
    except Exception as exc:
        logging.exception(
            "Reference data request failed (exception_type=%s)",
            type(exc).__name__,
        )
        return _error(f"Reference data error: {exc}", 500)


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------

@app.route(route="procurement/analyze", methods=["POST"])
@app.durable_client_input(client_name="client")
async def analyze(req: func.HttpRequest, client) -> func.HttpResponse:
    try:
        payload = req.get_json()
    except ValueError:
        return _error("Request body must be valid JSON.", 400)

    try:
        request = validate_request(payload, tenant_config_service, agent_registry)
    except RequestValidationError as exc:
        return _error(str(exc), 400)

    tenant_config = tenant_config_service.get_or_default(request.event.tenant_id)
    orchestrator = _get_orchestrator(request.event.tenant_id)

    try:
        response = await orchestrator.route(request)
    except ValueError as exc:
        return _error(str(exc), 422)

    validation = validator.validate(response, tenant_config)

    instance_id = await client.start_new(
        "approval_lifecycle",
        instance_id=response.request_id,
        client_input={
            "event": request.event.model_dump(),
            "response": response.model_dump(),
        },
    )
    logging.info("Approval lifecycle started: %s", instance_id)

    # ← Save to Exception Inbox
    _save_exception(request.event, response, instance_id)

    return _json({
        "response": response.model_dump(),
        "validation": validation.model_dump(),
        "approval_instance_id": instance_id,
    })


# ---------------------------------------------------------------------------
# Approval list & history
# ---------------------------------------------------------------------------

@app.route(route="approval/list", methods=["GET"])
def list_exceptions(req: func.HttpRequest) -> func.HttpResponse:
    try:
        table = _get_table("exceptions")
        entities = list(table.list_entities())
        result = [json.loads(e["data"]) for e in entities]
        return _json(result)
    except Exception as exc:
        logging.warning("approval/list error: %s", exc)
        return _json([])


@app.route(route="approval/history", methods=["GET"])
def exception_history(req: func.HttpRequest) -> func.HttpResponse:
    try:
        table = _get_table("exceptionhistory")
        entities = list(table.list_entities())
        result = [json.loads(e["data"]) for e in entities]
        return _json(result)
    except Exception as exc:
        logging.warning("approval/history error: %s", exc)
        return _json([])


# ---------------------------------------------------------------------------
# Approval decision
# ---------------------------------------------------------------------------

@app.route(route="approval/decision", methods=["POST"])
@app.durable_client_input(client_name="client")
async def approval_decision(req: func.HttpRequest, client) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _error("Request body must be valid JSON.", 400)

    request_id = body.get("request_id")
    decision = body.get("decision")
    if not request_id or decision not in ("approved", "rejected", "escalated"):
        return _error("request_id and decision (approved|rejected|escalated) are required.", 400)

    record = {
        "request_id": request_id,
        "rank": body.get("rank"),
        "decision": decision,
        "comment": body.get("comment", ""),
    }

    try:
        await client.raise_event(request_id, "HumanDecision", record)
    except Exception as exc:
        return _error(
            f"No waiting approval orchestration found for request '{request_id}': {exc}", 404
        )

    # ← Move to history
    _resolve_exception(
        request_id=request_id,
        tenant_id=body.get("tenant_id", DEFAULT_TENANT),
        decision=decision,
        comment=body.get("comment", ""),
        rank=body.get("rank"),
    )

    next_step = (
        "createPurchaseOrderDraft is being invoked by the Durable approval orchestration."
        if decision == "approved"
        else "No ERP action will be taken."
    )
    return _json({"status": "recorded", "decision": record, "next_step": next_step})


@app.route(route="approval/status/{request_id}", methods=["GET"])
@app.durable_client_input(client_name="client")
async def approval_status(req: func.HttpRequest, client) -> func.HttpResponse:
    request_id = req.route_params["request_id"]
    status = await client.get_status(request_id, show_history=False, show_input=False)
    if status is None or status.runtime_status is None:
        return _error(f"No approval orchestration found for request '{request_id}'.", 404)
    return _json({
        "request_id": request_id,
        "runtime_status": str(status.runtime_status),
        "output": status.output,
        "created_time": str(status.created_time),
        "last_updated_time": str(status.last_updated_time),
    })


# ---------------------------------------------------------------------------
# Durable orchestration
# ---------------------------------------------------------------------------

@app.orchestration_trigger(context_name="context")
def approval_lifecycle(context: df.DurableOrchestrationContext):
    data = context.get_input()
    if isinstance(data, str):
        data = json.loads(data)

    timeout_task = context.create_timer(
        context.current_utc_datetime + timedelta(hours=APPROVAL_TIMEOUT_HOURS)
    )
    approval_task = context.wait_for_external_event("HumanDecision")

    winner = yield context.task_any([approval_task, timeout_task])
    if winner == timeout_task:
        return {
            "outcome": "expired",
            "detail": f"No human decision within {APPROVAL_TIMEOUT_HOURS}h. No ERP action taken.",
        }
    timeout_task.cancel()

    decision = approval_task.result
    if isinstance(decision, str):
        decision = json.loads(decision)
    if decision.get("decision") != "approved":
        return {
            "outcome": decision.get("decision"),
            "detail": "No ERP action taken.",
            "decision": decision,
        }

    recommendations = data["response"]["recommendations"]
    rec = next((r for r in recommendations if r.get("rank") == decision.get("rank")), None)
    if rec is None:
        return {
            "outcome": "error",
            "detail": f"Approved rank {decision.get('rank')} not found in recommendations.",
        }

    draft = yield context.call_activity("create_po_draft", {
        "event": data["event"],
        "recommendation": rec,
        "decision": decision,
    })
    return {"outcome": "approved", "decision": decision, "draft": draft}


@app.activity_trigger(input_name="payload")
def create_po_draft(payload: dict) -> dict:
    from agents.procurement_exception_agent.tools import createPurchaseOrderDraft
    from agents.procurement_exception_agent.services.inventory import get_inventory

    event = payload["event"]
    rec = payload["recommendation"]

    inventory = get_inventory(event["item_id"])
    qty = inventory.stock_gap if inventory and inventory.stock_gap > 0 else 100

    result = createPurchaseOrderDraft(
        item_id=event["item_id"],
        supplier_id=rec.get("supplier_id") or "UNSPECIFIED",
        qty=qty,
        plant=event.get("plant") or "UNSPECIFIED",
        justification=(
            f"Human-approved rank {rec['rank']} recommendation "
            f"({payload['decision'].get('comment') or rec['reason']})"
        ),
    )
    return json.loads(result)


# ---------------------------------------------------------------------------
# Buyer chat
# ---------------------------------------------------------------------------

@app.route(route="chat", methods=["POST"])
async def chat(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _error("Request body must be valid JSON.", 400)

    text = (body.get("message") or "").strip()
    if not text:
        return _error("Message must not be empty.", 400)

    tenant_id = body.get("tenant_id") or DEFAULT_TENANT
    user_id = DEFAULT_USER_ID
    # TODO:
    # Replace with Entra ID user when authentication is enabled.

    conversation_id = body.get("conversation_id")

    logging.info(
        "Chat request received "
        "(tenant_id=%s, conversation_id=%s, is_new_conversation=%s, "
        "debug_enabled=%s, foundry_project_endpoint=%s, foundry_model=%s)",
        tenant_id,
        conversation_id or "new",
        conversation_id is None,
        bool(body.get("debug")),
        PROJECT_ENDPOINT,
        MODEL,
    )

    agent = _get_chat_agent(tenant_id)
    debug_enabled = bool(body.get("debug"))

    generated_title = None

    is_new_conversation = (
        conversation_id is None
    )

    if is_new_conversation:

        generated_title = (
            await conversation_title_service
            .generate_title(
                text
            )
        )

    conversation = (
        chat_history_service.create_or_get_conversation(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            first_message=text,
            title=generated_title,
        )
    )

    #
    # New conversation already contains the first user message.
    # Existing conversation needs the new user message appended.
    #
    existing_conversation = None

    if conversation_id:
        existing_conversation = (
            chat_history_service.get_conversation(
                conversation_id,
                user_id,
            )
        )

    if not is_new_conversation:
        chat_history_service.append_user_message(
            conversation.id,
            user_id,
            text,
        )

        conversation = chat_history_service.get_conversation(
            conversation.id,
            user_id,
        )

        if conversation is None:
            return _error(
                "Conversation not found.",
                404,
            )

    pending_action_confirmed = (
        chat_history_service.latest_message_confirms_pending_action(
            conversation,
        )
    )
    if pending_action_confirmed:
        logging.info(
            "Buyer reply confirmed pending chat action "
            "(tenant_id=%s, conversation_id=%s)",
            tenant_id,
            conversation.id,
        )

    # Session resolution: warm in-memory cache first, then the state
    # persisted in Cosmos (survives instance recycling on Consumption/Flex
    # plans), then a fresh session seeded from the flat transcript.
    session = _get_cached_chat_session(conversation.id)
    session_source = "memory" if session is not None else None

    if session is None and conversation.agent_session_state:
        try:
            session = agent.restore_session(
                conversation.agent_session_state,
            )
            session_source = "cosmos"
        except Exception:
            logging.warning(
                "Failed to restore persisted agent session; falling back "
                "to transcript seeding (conversation_id=%s)",
                conversation.id,
                exc_info=True,
            )

    if session is not None:
        # The session already holds the structured history, including prior
        # tool calls and results — send only the newest buyer message.
        prompt = text
        pending_action = (
            chat_history_service.pending_action_for_latest_message(
                conversation,
            )
        )
        if pending_action:
            prompt = (
                f"{text}\n\n"
                f"{chat_history_service.pending_action_instruction(pending_action)}"
            )
    else:
        # New conversation, or no usable prior state: seed a fresh session
        # with the persisted transcript (flat text fallback).
        session = agent.create_session()
        session_source = "transcript"
        prompt = chat_history_service.build_agent_prompt(
            conversation,
        )

    trace_token = None
    debug_calls = []
    try:
        if debug_enabled:
            from services.debug_trace import begin_debug_trace

            trace_token = begin_debug_trace()
        logging.info(
            "Calling buyer chat agent "
            "(tenant_id=%s, conversation_id=%s, prompt_chars=%s, "
            "session_source=%s, "
            "foundry_project_endpoint=%s, foundry_model=%s)",
            tenant_id,
            conversation.id,
            len(prompt or ""),
            session_source,
            PROJECT_ENDPOINT,
            MODEL,
        )
        reply = await agent.chat(
            prompt,
            session,
        )
        _store_chat_session(conversation.id, session)
        try:
            chat_history_service.save_agent_session_state(
                conversation.id,
                user_id,
                _trimmed_session_state(session),
            )
        except Exception:
            # Persistence is best-effort: a failed save only means the next
            # cold start falls back to transcript seeding.
            logging.warning(
                "Failed to persist agent session state "
                "(conversation_id=%s)",
                conversation.id,
                exc_info=True,
            )
        logging.info(
            "Buyer chat agent completed "
            "(tenant_id=%s, conversation_id=%s, reply_chars=%s)",
            tenant_id,
            conversation.id,
            len(reply or ""),
        )
    except Exception as exc:
        # A failed run can leave the in-memory session mid tool-call; drop it
        # so the next turn reseeds from the persisted transcript instead.
        _drop_chat_session(conversation.id)
        logging.exception(
            "Buyer chat agent failed "
            "(tenant_id=%s, conversation_id=%s, foundry_project_endpoint=%s, "
            "foundry_model=%s, exception_type=%s)",
            tenant_id,
            conversation.id if conversation else "unknown",
            PROJECT_ENDPOINT,
            MODEL,
            type(exc).__name__,
        )
        if trace_token is not None:
            from services.debug_trace import end_debug_trace

            debug_calls = end_debug_trace(trace_token)
            trace_token = None
        return _error(f"Agent error: {exc}", 502)
    finally:
        if trace_token is not None and not debug_calls:
            from services.debug_trace import end_debug_trace

            debug_calls = end_debug_trace(trace_token)
            trace_token = None

    chat_history_service.append_assistant_message(
        conversation.id,
        user_id,
        reply,
    )
    chat_history_service.refresh_pending_action_after_assistant_reply(
        conversation.id,
        user_id,
    )

    response_body = {
        "conversation_id": conversation.id,
        "reply": reply,
        "agent_id": "scm-buyer-chat-agent",
        "tenant_id": tenant_id,
    }
    if debug_enabled:
        response_body["debug"] = {
            "calls": debug_calls,
            "tools_called": [call for call in debug_calls if call.get("kind") == "tool"],
            "method_calls": [call for call in debug_calls if call.get("kind") != "tool"],
            "prompt_package": agent.prompt_metadata,
        }

    return _json(response_body)



#get conversation endpoint for buyers to retrieve a specific conversation by id

@app.route(
    route="chat/conversations/{conversation_id}",
    methods=["GET"],
)
def get_conversation(
    req: func.HttpRequest,
) -> func.HttpResponse:

    user_id = DEFAULT_USER_ID

    conversation_id = req.route_params.get(
        "conversation_id"
    )

    conversation = (
        chat_history_service.get_conversation(
            conversation_id,
            user_id,
        )
    )

    if not conversation:
        return _error(
            "Conversation not found.",
            404,
        )

    return _json(
        conversation.model_dump()
    )


#Rename conversation endpoint for buyers to rename a specific conversation by id

@app.route(
    route="conversations/{conversation_id}/title",
    methods=["PATCH"],
)
async def rename_conversation(
    req: func.HttpRequest,
) -> func.HttpResponse:

    conversation_id = req.route_params[
        "conversation_id"
    ]

    try:
        body = req.get_json()
    except ValueError:
        return _error(
            "Request body must be valid JSON.",
            400,
        )

    title = (
        body.get("title")
        or ""
    ).strip()

    if not title:
        return _error(
            "Title is required.",
            400,
        )

    user_id = DEFAULT_USER_ID

    success = (
        chat_history_service
        .rename_conversation(
            conversation_id,
            user_id,
            title,
        )
    )

    if not success:
        return _error(
            "Conversation not found.",
            404,
        )

    return _json(
        {
            "status": "ok",
            "conversation_id":
                conversation_id,
            "title": title,
        }
    )


#archive conversation endpoint for buyers to archive a specific conversation by id
@app.route(
    route="conversations/{conversation_id}/archive",
    methods=["POST"],
)
async def archive_conversation(
    req: func.HttpRequest,
) -> func.HttpResponse:

    conversation_id = req.route_params[
        "conversation_id"
    ]

    user_id = DEFAULT_USER_ID

    success = (
        chat_history_service
        .archive_conversation(
            conversation_id,
            user_id,
        )
    )

    if not success:
        return _error(
            "Conversation not found.",
            404,
        )

    return _json(
        {
            "status": "ok",
            "conversation_id":
                conversation_id,
        }
    )


@app.route(
    route="conversations/{conversation_id}/unarchive",
    methods=["POST"],
)
async def unarchive_conversation(
    req: func.HttpRequest,
) -> func.HttpResponse:

    conversation_id = req.route_params[
        "conversation_id"
    ]

    user_id = DEFAULT_USER_ID

    success = (
        chat_history_service
        .unarchive_conversation(
            conversation_id,
            user_id,
        )
    )

    if not success:
        return _error(
            "Conversation not found.",
            404,
        )

    return _json(
        {
            "status": "ok",
            "conversation_id":
                conversation_id,
        }
    )


#delete conversation endpoint for buyers to delete a specific conversation by id
@app.route(
    route="conversations/{conversation_id}",
    methods=["DELETE"],
)
async def delete_conversation(
    req: func.HttpRequest,
) -> func.HttpResponse:

    conversation_id = req.route_params[
        "conversation_id"
    ]

    user_id = DEFAULT_USER_ID

    success = (
        chat_history_service
        .delete_conversation(
            conversation_id,
            user_id,
        )
    )

    if not success:
        return _error(
            "Conversation not found.",
            404,
        )

    _drop_chat_session(conversation_id)

    return _json(
        {
            "status": "ok",
            "conversation_id":
                conversation_id,
        }
    )


#get archived conversations
@app.route(
    route="chat/conversations",
    methods=["GET"],
)
def list_conversations(
    req: func.HttpRequest,
) -> func.HttpResponse:

    include_archived = (
        req.params.get(
            "include_archived",
            "false",
        ).lower()
        == "true"
    )

    conversations = (
        chat_history_service.list_conversations(
            user_id=DEFAULT_USER_ID,
            include_archived=include_archived,
        )
    )

    return _json(
        [
            c.model_dump()
            for c in conversations
        ]
    )

# ---------------------------------------------------------------------------
# Policy Search (Azure AI Search) — delegates to policy_service.py
# ---------------------------------------------------------------------------

@app.route(route="policy/search", methods=["GET", "POST"])
def policy_search(req: func.HttpRequest) -> func.HttpResponse:
    from agents.procurement_exception_agent.services.policy.policy_service import (
        get_policies_for_exception,
    )

    try:
        if req.method == "GET":
            query = req.params.get("q", "")
            tenant_id = req.params.get("tenant_id", DEFAULT_TENANT)
        else:
            body = req.get_json()
            query = body.get("query", "")
            tenant_id = body.get("tenant_id", DEFAULT_TENANT)

        # get_policies_for_exception builds its own query text from an
        # exception_context dict; for a raw free-text search route, pass
        # the query straight through as exception_type so it's used as-is.
        policies = get_policies_for_exception(
            exception_context={"exception_type": query} if query else {},
            tenant_id=tenant_id,
        )

        return _json({"query": query, "results": policies, "count": len(policies)})

    except Exception as exc:
        logging.error("Policy search error: %s", exc)
        return _error(f"Search failed: {exc}", 500)