"""
D365 Finance & Operations OData client.

A thin, synchronous wrapper over the F&O OData v4 endpoint
({base_url}/data/{EntitySet}) that handles:

  * OAuth2 client-credentials auth via Entra ID (azure-identity
    ClientSecretCredential, which caches and refreshes tokens internally);
  * standard OData query options ($select, $filter, $top, $orderby, $expand);
  * server-side paging (@odata.nextLink) for full result sets;
  * cross-company queries and dataAreaId scoping.

The client is intentionally read-first: F&O write/action endpoints exist but
are deliberately not exposed here, mirroring the agent's "no autonomous ERP
mutation" governance rule.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

import requests
from azure.core.credentials import TokenCredential
from azure.identity import ClientSecretCredential

from integrations.d365.config import D365Config
from services.debug_trace import record_debug_call

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30  # seconds
_DEFAULT_PAGE_CAP = 10_000  # safety cap on total rows fetched via paging


class D365ODataError(RuntimeError):
    """Raised when an OData request fails (HTTP error or transport failure)."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class D365ODataClient:
    """Synchronous OData client for D365 Finance & Operations."""

    def __init__(
        self,
        config: D365Config | None = None,
        *,
        credential: TokenCredential | None = None,
        session: requests.Session | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._config = config or D365Config.from_env()
        self._credential = credential or ClientSecretCredential(
            tenant_id=self._config.tenant_id,
            client_id=self._config.client_id,
            client_secret=self._config.client_secret,
        )
        self._session = session or requests.Session()
        self._timeout = timeout

    # ------------------------------------------------------------------ auth
    def _bearer_token(self) -> str:
        # ClientSecretCredential caches the token and only calls Entra ID
        # again when the current token is close to expiry.
        return self._credential.get_token(self._config.scope).token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._bearer_token()}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
        }

    # --------------------------------------------------------------- queries
    def query(
        self,
        entity_set: str,
        *,
        select: Optional[Iterable[str]] = None,
        filter: Optional[str] = None,
        top: Optional[int] = None,
        orderby: Optional[str] = None,
        expand: Optional[str] = None,
        cross_company: bool = False,
        scope_to_company: bool = True,
        page_cap: int = _DEFAULT_PAGE_CAP,
    ) -> list[dict[str, Any]]:
        """Fetch records from an OData entity set, following paging links.

        Args:
            entity_set: The OData entity set name, e.g. "PurchaseOrderHeadersV2".
            select: Field names to project ($select).
            filter: Raw OData $filter expression (caller is responsible for
                escaping string literals — see ``escape_literal``).
            top: Maximum number of records to request from the server.
            orderby: $orderby expression, e.g. "PurchaseOrderNumber desc".
            expand: $expand expression for navigation properties.
            cross_company: If True, query across all companies (adds
                cross-company=true).
            scope_to_company: If True and a default data_area_id is configured,
                AND a ``dataAreaId eq '<company>'`` clause onto the filter.
                D365 stores dataAreaId lowercase and OData string comparison is
                case-sensitive, so the value is lowercased; this also implies
                cross-company=true so the target company is reachable
                regardless of the service principal's default company.
            page_cap: Safety limit on total records returned across pages.

        Returns:
            List of entity records as dictionaries.
        """
        params: dict[str, str] = {}

        apply_company = scope_to_company and bool(self._config.data_area_id)
        effective_filter = self._build_filter(filter, apply_company)
        if effective_filter:
            params["$filter"] = effective_filter
        if select:
            params["$select"] = ",".join(select)
        if orderby:
            params["$orderby"] = orderby
        if expand:
            params["$expand"] = expand
        if top is not None:
            params["$top"] = str(top)
        if cross_company or apply_company:
            params["cross-company"] = "true"

        url: Optional[str] = f"{self._config.odata_root}/{entity_set}"
        results: list[dict[str, Any]] = []
        record_debug_call(
            "d365_query",
            "D365ODataClient.query",
            arguments={
                "entity_set": entity_set,
                "select": list(select) if select else None,
                "filter": filter,
                "effective_filter": effective_filter,
                "top": top,
                "orderby": orderby,
                "expand": expand,
                "cross_company": cross_company,
                "scope_to_company": scope_to_company,
                "data_area_id": self._config.data_area_id,
            },
            entity=entity_set,
            metadata={"params": params},
        )

        # First request carries the query params; subsequent requests follow
        # the absolute @odata.nextLink URL returned by the server.
        first = True
        while url and len(results) < page_cap:
            payload = self._get(url, params=params if first else None)
            results.extend(payload.get("value", []))
            url = payload.get("@odata.nextLink")
            first = False

        return results[:page_cap]

    def get_first(self, entity_set: str, **kwargs: Any) -> dict[str, Any] | None:
        """Return the first matching record, or None. Forces $top=1."""
        record_debug_call(
            "d365_query",
            "D365ODataClient.get_first",
            arguments={"entity_set": entity_set, **kwargs},
            entity=entity_set,
        )
        kwargs["top"] = 1
        kwargs["page_cap"] = 1
        records = self.query(entity_set, **kwargs)
        return records[0] if records else None

    def list_entity_sets(self) -> list[str]:
        """Return the names of all OData entity sets (service document).

        Useful as an auth + connectivity smoke test: it exercises the token
        flow and the OData root without assuming any specific entity exists.
        """
        payload = self._get(self._config.odata_root)
        return [item.get("name", "") for item in payload.get("value", [])]

    def test_connection(self) -> bool:
        """Return True if the service document can be retrieved (auth OK)."""
        self.list_entity_sets()
        return True

    # --------------------------------------------------------------- helpers
    def _build_filter(self, filter: Optional[str], apply_company: bool) -> Optional[str]:
        if apply_company:
            # D365 dataAreaId is stored lowercase; OData eq is case-sensitive.
            company = self.escape_literal(self._config.data_area_id.lower())
            company_clause = f"dataAreaId eq '{company}'"
            if filter:
                return f"({filter}) and {company_clause}"
            return company_clause
        return filter

    @staticmethod
    def escape_literal(value: str) -> str:
        """Escape a string for safe inclusion in an OData literal."""
        return value.replace("'", "''")

    def _get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            response = self._session.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise D365ODataError(f"D365 OData request failed: {exc}") from exc

        if not response.ok:
            snippet = response.text[:2000] if response.text else ""
            logger.error(
                "D365 OData %s -> %s: %s", url, response.status_code, snippet
            )
            raise D365ODataError(
                f"D365 OData request to {url} failed with HTTP {response.status_code}",
                status_code=response.status_code,
                body=snippet,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise D365ODataError(
                f"D365 OData response from {url} was not valid JSON"
            ) from exc
