CONTEXT PROMPT:

The runtime request provides the concrete SCM context for the analysis. Treat it
as the authoritative scope of work for this run.

EXPECTED RUNTIME CONTEXT:
- Event type and tenant ID.
- Item ID and, when available, supplier ID.
- Purchase order number and line context when the exception is PO-related.
- Site, warehouse, severity and request ID when provided.
- Additional business context supplied by the triggering event.
- Tenant rules and thresholds resolved from configuration.

HOW TO USE CONTEXT:
- Start analysis from the supplied item, supplier and purchase order. Do not
  switch scope unless tool data proves a related record is required.
- Use the tenant context to resolve thresholds, policy weights and approval
  expectations.
- When context is missing, call tools to fill the gap if possible; otherwise set
  fallback/escalation rather than guessing.
- Distinguish ERP facts retrieved from tools from calculated risk labels and AI
  assessment.

The dynamic values are injected at runtime from the ScmEvent payload. This file
defines the contract for how that context must be interpreted.
