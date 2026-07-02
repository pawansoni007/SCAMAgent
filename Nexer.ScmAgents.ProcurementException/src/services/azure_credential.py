"""Azure credential selection for local development and deployed apps."""

from __future__ import annotations

import os
import logging

from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential


def get_azure_credential() -> TokenCredential:
    """Return the right Azure credential for the current runtime."""
    if _is_running_in_azure_app_service():
        logging.info(
            "Azure credential selected: ManagedIdentityCredential "
            "(site=%s, has_identity_endpoint=%s, has_msi_endpoint=%s)",
            os.environ.get("WEBSITE_SITE_NAME") or "unknown",
            bool(os.environ.get("IDENTITY_ENDPOINT")),
            bool(os.environ.get("MSI_ENDPOINT")),
        )
        return ManagedIdentityCredential()

    logging.info(
        "Azure credential selected: DefaultAzureCredential for local runtime "
        "(interactive_browser_excluded=True)"
    )
    return DefaultAzureCredential(
        exclude_interactive_browser_credential=True,
    )


def _is_running_in_azure_app_service() -> bool:
    return any(
        os.environ.get(name)
        for name in (
            "IDENTITY_ENDPOINT",
            "MSI_ENDPOINT",
            "WEBSITE_INSTANCE_ID",
        )
    )
