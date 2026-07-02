"""
policy_service.py
─────────────────────────────────────────────────────────────────────
Internal service used by the Procurement Exception Agent to fetch
relevant policies from Azure AI Search BEFORE generating any
recommendation. This is NOT the HTTP endpoint — that lives in
function_app.py under route="policy/search".

Search strategy: HYBRID (keyword + vector), merged via Azure AI
Search's built-in Reciprocal Rank Fusion (RRF).

Why hybrid and not keyword-only:
Procurement events carry ERP codes and enum values (e.g. item_id
"M0001", event_type "overdue_purchase_order") that rarely appear
verbatim in policy text written in business language ("Spending
Limit", "Emergency Procurement"). Pure keyword search against those
fields returns zero matches even when a policy is clearly relevant.
Vector search closes that gap by matching on meaning rather than
exact tokens; keyword search is kept alongside it to still catch
exact-term matches (policy IDs, citation numbers) when they do
appear. RRF blends both result sets.

Production notes:
- SearchClient and the embedding client are each created once per
  process via functools.lru_cache (lazy, safe under concurrency).
- Settings are read from environment variables only, with a
  local.settings.json fallback restricted to local dev.
- A search or embedding failure does NOT crash the agent run. It
  logs a warning and returns an empty list, so the agent proceeds
  with the "no policies retrieved" fallback prompt instead of a
  hard 500.
- tenant_id is escaped before being placed in the OData filter.

SCHEMA NOTE (2026-06): this was rewritten to match the new chunk-level
"procurement-policies" index from the indexer-based RAG migration
(see scripts/setup_search_pipeline.py). One search document = one
chunk of one policy now, not one whole policy. Field changes:
  id -> policy_id, clause_text -> chunk, content_vector -> vector,
  summary/citation/effective_date removed (not in the new schema).
  tenant_id added back as a real index field (was missing during the
  migration -- chunks now carry it via blob metadata, same pattern as
  policy_id/category/title). Requires the matching patch in
  setup_search_pipeline.py (tenant_id field + projection mapping) and
  policies_docs/_manifest.json values (set by convert_policies_to_docs.py,
  default tenant_id="default" unless your JSON specifies one).
"""

import os
import json
import logging
from functools import lru_cache
from typing import Optional

from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

logger = logging.getLogger(__name__)

# Tunables — kept as named constants instead of magic numbers buried in code.
DEFAULT_INDEX_NAME = "procurement-policies"
MAX_POLICIES_RETURNED = 5
VECTOR_FIELD_NAME = "vector"  # was "content_vector" -- that field doesn't exist in the new schema
VECTOR_K_NEAREST = 10  # candidates pulled by the vector leg before RRF merge/top

# Matches the new chunk-level index schema (chunk_id, parent_id, title, chunk,
# category, vector) plus policy_id, which requires the small setup_search_pipeline.py
# patch discussed in chat (adds a policy_id field + projection mapping so chunks
# carry their source policy's ID through for citations like [POL-001]).
SEARCH_FIELDS = [
    "chunk_id", "parent_id", "policy_id", "category", "title", "chunk",
]

# Maps SCM event types -> natural-language search terms that match how
# policies are actually written, instead of raw ERP/enum codes which never
# appear verbatim in policy text.
EVENT_TYPE_SEARCH_TERMS = {
    "overdue_purchase_order": "purchase order approval delay procurement timeline",
    "supplier_delay": "supplier delay alternative sourcing lead time",
    "blocked_purchase_order": "purchase order approval threshold spending authority",
    "lead_time_deviation": "lead time supplier performance contract review",
    "supplier_risk_alert": "vendor risk approved vendor list compliance",
    "procurement_exception": "procurement exception approval policy",
}


def _is_local_dev() -> bool:
    # Azure Functions sets this in the cloud; it's absent locally.
    return os.environ.get("AZURE_FUNCTIONS_ENVIRONMENT", "Development") != "Production"


def _get_setting(key: str, required: bool = True, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(key)

    if value is None and _is_local_dev():
        # Local-dev-only fallback: walk up looking for local.settings.json.
        # This branch never runs in Azure (local.settings.json isn't deployed
        # and AZURE_FUNCTIONS_ENVIRONMENT == "Production" in the cloud).
        search_dir = os.path.dirname(__file__)
        for _ in range(8):
            candidate = os.path.join(search_dir, "local.settings.json")
            if os.path.exists(candidate):
                with open(candidate) as f:
                    value = json.load(f).get("Values", {}).get(key)
                break
            parent = os.path.dirname(search_dir)
            if parent == search_dir:
                break
            search_dir = parent

    if value is None:
        if required:
            raise RuntimeError(
                f"Missing required setting '{key}'. "
                "Add it to local.settings.json > Values for local dev, "
                "or to Azure App Settings for cloud."
            )
        return default
    return value


@lru_cache(maxsize=1)
def _get_search_client() -> SearchClient:
    """
    One SearchClient per process. lru_cache makes this both lazy
    (built on first call) and safe under concurrent invocations —
    no manual global/None check needed.

    Keyless auth: uses DefaultAzureCredential (Managed Identity in
    Azure, your az login session locally) -- consistent with the rest
    of the project. No API key is stored or required anywhere.
    """
    client = SearchClient(
        endpoint=_get_setting("AZURE_SEARCH_ENDPOINT"),
        index_name=_get_setting("AZURE_SEARCH_INDEX", required=False, default=DEFAULT_INDEX_NAME),
        credential=DefaultAzureCredential(),
    )
    logger.info("PolicyService: SearchClient ready (keyless).")
    return client


@lru_cache(maxsize=1)
def _get_embedding_client():
    """
    One Azure OpenAI client per process, authenticated via Managed Identity
    (DefaultAzureCredential) — consistent with the rest of the codebase.
    Returns (client, deployment_name).
    """
    from openai import AzureOpenAI

    endpoint = _get_setting("AZURE_OPENAI_EMBEDDING_ENDPOINT")
    deployment = _get_setting(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", required=False, default="text-embedding-3-small"
    )
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version="2024-06-01",
    )
    logger.info("PolicyService: embedding client ready (deployment=%s).", deployment)
    return client, deployment


def _escape_odata_literal(value: str) -> str:
    """OData string literals escape a single quote by doubling it."""
    return value.replace("'", "''")


def _build_query_text(exception_context: dict) -> str:
    """
    Builds the natural-language query text used for BOTH the keyword leg
    and the embedding input for the vector leg of hybrid search.
    """
    parts = []

    event_type = exception_context.get("exception_type")
    if event_type:
        parts.append(EVENT_TYPE_SEARCH_TERMS.get(event_type, str(event_type).replace("_", " ")))
    if exception_context.get("total_value"):
        parts.append(f"purchase value spending limit {exception_context['total_value']}")
    if exception_context.get("is_emergency"):
        parts.append("emergency purchase operational disruption")
    if exception_context.get("is_single_source"):
        parts.append("single source sole source vendor")

    # item_id / supplier_id deliberately excluded: ERP codes never appear
    # in policy prose, so including them only dilutes the query.

    return " ".join(parts) if parts else "procurement policy approval spending rules"


def _embed_query(query_text: str) -> Optional[list[float]]:
    """Embeds the query text for the vector leg. Returns None on failure (degrades to keyword-only)."""
    try:
        client, deployment = _get_embedding_client()
        response = client.embeddings.create(model=deployment, input=[query_text])
        return response.data[0].embedding
    except Exception as exc:
        logger.warning("PolicyService: query embedding failed, falling back to keyword-only: %s", exc)
        return None


# ── Main entry point called by the agent ─────────────────────────────────────

def get_policies_for_exception(
    exception_context: dict,
    tenant_id: str,
) -> list[dict]:
    """
    Called by the agent BEFORE generating recommendations.

    Builds a natural-language query from the exception context, runs a
    HYBRID (keyword + vector) search against Azure AI Search, and returns
    matching policies ranked by Azure's Reciprocal Rank Fusion.

    On any search/embedding/connection failure, logs a warning and returns
    an empty list rather than raising — a transient Azure blip should
    degrade the agent to "no policies found", not take down the whole
    exception analysis.

    Args:
        exception_context: Keys like exception_type, item_description,
                           total_value, supplier_name, is_emergency, etc.
        tenant_id:         Tenant scoping — filters search results.

    Returns:
        List of policy dicts ordered by relevance. Empty list if no
        tenant_id, no matches, or the search call failed.
    """
    if not tenant_id:
        logger.warning("PolicyService: get_policies_for_exception called with empty tenant_id.")
        return []

    query_text = _build_query_text(exception_context)
    safe_tenant_id = _escape_odata_literal(tenant_id)
    logger.debug("PolicyService: query=%r tenant=%s", query_text, tenant_id)

    query_vector = _embed_query(query_text)
    vector_queries = None
    if query_vector is not None:
        vector_queries = [
            VectorizedQuery(
                vector=query_vector,
                k_nearest_neighbors=VECTOR_K_NEAREST,
                fields=VECTOR_FIELD_NAME,
            )
        ]

    try:
        results = _get_search_client().search(
            search_text=query_text,
            vector_queries=vector_queries,  # None => falls back to keyword-only search
            # tenant_id is now a real, filterable field on every chunk (see
            # SCHEMA NOTE above). Make sure the value passed in here matches
            # what's set in policies_docs/_manifest.json / blob metadata --
            # currently that's "default" for all 10 dev policies unless you
            # set POLICY_DEFAULT_TENANT_ID when running convert_policies_to_docs.py.
            filter=f"tenant_id eq '{safe_tenant_id}'",
            select=SEARCH_FIELDS,
            top=MAX_POLICIES_RETURNED,
        )

        policies = []
        for r in results:
            policies.append({
                "id":           r.get("policy_id"),  # was "id" -- key field is now chunk_id,
                                                       # but policy_id is what we want for citations
                "category":     r.get("category"),
                "title":        r.get("title"),
                "chunk_text":   r.get("chunk"),        # was "clause_text"
                "parent_id":    r.get("parent_id"),    # new -- groups chunks from the same source policy
                "search_score": r.get("@search.score"),
            })

    except AzureError as exc:
        # Search is down / misconfigured / throttled. Don't take the
        # whole agent run down with it — degrade gracefully.
        logger.warning(
            "PolicyService: Azure AI Search call failed (tenant=%s): %s",
            tenant_id, exc,
        )
        return []
    except Exception as exc:
        # Defensive catch-all so a malformed/unexpected document shape
        # also degrades gracefully instead of crashing analyze().
        logger.warning(
            "PolicyService: unexpected error processing search results (tenant=%s): %s",
            tenant_id, exc,
        )
        return []

    logger.info("PolicyService: %d policies retrieved for tenant=%s.", len(policies), tenant_id)
    return policies


def format_policies_for_prompt(policies: list[dict]) -> str:
    """
    Converts policy list into a text block injected into the agent's prompt.
    The agent reads this and must cite relevant policies in recommendations.
    """
    if not policies:
        return (
            "APPLICABLE PROCUREMENT POLICIES\n"
            "================================\n"
            "No specific policies retrieved. Apply standard procurement rules.\n"
        )

    lines = [
        "APPLICABLE PROCUREMENT POLICIES",
        "================================",
        "Before finalising recommendations, check each one against these",
        "policies. Cite the policy ID (e.g. POL-001) in any recommendation",
        "where a constraint or approval requirement applies.",
        "",
    ]

    for p in policies:
        policy_id = (p.get("id") or "UNKNOWN").upper()
        lines.append(f"[{policy_id}] {p.get('title', '')}  |  Category: {p.get('category', '')}")
        lines.append(f"Full rule: {p.get('chunk_text', '')}")
        lines.append("")

    return "\n".join(lines)