from .policy_service import (
    get_policies_for_exception,
    format_policies_for_prompt,
)

# Alias for backward compatibility
get_procurement_policies = get_policies_for_exception

__all__ = [
    "get_procurement_policies",
    "get_policies_for_exception",
    "format_policies_for_prompt",
]