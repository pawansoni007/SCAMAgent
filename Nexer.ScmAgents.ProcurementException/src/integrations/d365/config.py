"""
D365 Finance & Operations connection configuration.

Loads the OData endpoint and Entra ID (Azure AD) service-principal credentials
from environment variables. In Azure these come from the Function App's
application settings; locally they come from local.settings.json.

Environment variables:
  D365_ODATA_BASE_URL    Base environment URL, e.g.
                         https://<env>.operations.<region>.dynamics.com
  D365_DATA_AREA_ID      Default company/legal entity, e.g. "USMF"
  D365_ENTRA_TENANT_ID   Entra ID tenant (directory) ID
  D365_ENTRA_CLIENT_ID   App registration (client) ID with D365 F&O access
  D365_CLIENT_SECRET     Client secret for the app registration
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class D365ConfigError(RuntimeError):
    """Raised when required D365 configuration is missing or invalid."""


_REQUIRED = (
    "D365_ODATA_BASE_URL",
    "D365_ENTRA_TENANT_ID",
    "D365_ENTRA_CLIENT_ID",
    "D365_CLIENT_SECRET",
)


@dataclass(frozen=True)
class D365Config:
    """Immutable D365 F&O connection settings."""

    base_url: str
    tenant_id: str
    client_id: str
    client_secret: str
    data_area_id: str = ""

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "D365Config":
        """Build configuration from environment variables.

        Raises:
            D365ConfigError: if any required variable is missing or empty.
        """
        source = env if env is not None else os.environ

        missing = [name for name in _REQUIRED if not source.get(name)]
        if missing:
            raise D365ConfigError(
                "Missing required D365 settings: " + ", ".join(missing)
            )

        return cls(
            base_url=source["D365_ODATA_BASE_URL"].rstrip("/"),
            tenant_id=source["D365_ENTRA_TENANT_ID"],
            client_id=source["D365_ENTRA_CLIENT_ID"],
            client_secret=source["D365_CLIENT_SECRET"],
            data_area_id=(source.get("D365_DATA_AREA_ID") or "").strip(),
        )

    @property
    def authority(self) -> str:
        """Entra ID token authority for this tenant."""
        return f"https://login.microsoftonline.com/{self.tenant_id}"

    @property
    def scope(self) -> str:
        """OAuth2 scope for a D365 F&O resource token (client-credentials)."""
        return f"{self.base_url}/.default"

    @property
    def odata_root(self) -> str:
        """Root URL for OData data entities, e.g. {base}/data."""
        return f"{self.base_url}/data"
