"""
Tenant configuration service.

Provides tenant-specific rules, decision weights, approval policy, and prompt
variables. This implementation uses an in-memory store with demo tenants.
"""

from pydantic import BaseModel, Field


class TenantRules(BaseModel):
    approved_suppliers_only: bool = Field(default=True)
    min_supplier_reliability: float = Field(default=0.85, ge=0.0, le=1.0)
    allow_emergency_override: bool = Field(default=False)


class TenantWeights(BaseModel):
    delivery_risk: float = Field(default=0.35)
    supplier_reliability: float = Field(default=0.25)
    cost_impact: float = Field(default=0.20)
    inventory_criticality: float = Field(default=0.20)


class TenantApprovalPolicy(BaseModel):
    always_requires_human_approval: bool = Field(default=True)
    low_confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    high_value_threshold: float = Field(default=50000.0)


class TenantConfig(BaseModel):
    tenant_id: str
    rules: TenantRules = Field(default_factory=TenantRules)
    weights: TenantWeights = Field(default_factory=TenantWeights)
    approval_policy: TenantApprovalPolicy = Field(default_factory=TenantApprovalPolicy)

    def prompt_variables(self) -> dict[str, str]:
        """Variables substituted into prompt package placeholders at load time."""
        return {
            "min_supplier_reliability": f"{self.rules.min_supplier_reliability:.2f}",
            "weight_delivery_risk": f"{self.weights.delivery_risk:.2f}",
            "weight_supplier_reliability": f"{self.weights.supplier_reliability:.2f}",
            "weight_cost_impact": f"{self.weights.cost_impact:.2f}",
            "weight_inventory_criticality": f"{self.weights.inventory_criticality:.2f}",
        }


class TenantConfigService:
    """In-memory tenant configuration store seeded with demo tenants."""

    def __init__(self) -> None:
        self._configs: dict[str, TenantConfig] = {}
        self._seed()

    def _seed(self) -> None:
        self.upsert(TenantConfig(
            tenant_id="nexer-demo",
            rules=TenantRules(
                approved_suppliers_only=True,
                min_supplier_reliability=0.85,
                allow_emergency_override=False,
            ),
            weights=TenantWeights(
                delivery_risk=0.35,
                supplier_reliability=0.25,
                cost_impact=0.20,
                inventory_criticality=0.20,
            ),
            approval_policy=TenantApprovalPolicy(
                always_requires_human_approval=True,
                low_confidence_threshold=0.75,
                high_value_threshold=50000.0,
            ),
        ))
        self.upsert(TenantConfig(
            tenant_id="USF-01",
            rules=TenantRules(
                approved_suppliers_only=True,
                min_supplier_reliability=0.90,
                allow_emergency_override=False,
            ),
            weights=TenantWeights(
                delivery_risk=0.40,
                supplier_reliability=0.30,
                cost_impact=0.10,
                inventory_criticality=0.20,
            ),
            approval_policy=TenantApprovalPolicy(
                always_requires_human_approval=True,
                low_confidence_threshold=0.80,
                high_value_threshold=25000.0,
            ),
        ))

    def upsert(self, config: TenantConfig) -> None:
        self._configs[config.tenant_id] = config

    def get(self, tenant_id: str) -> TenantConfig | None:
        return self._configs.get(tenant_id)

    def get_or_default(self, tenant_id: str) -> TenantConfig:
        """Return the tenant's config, or platform defaults if not registered."""
        return self._configs.get(tenant_id) or TenantConfig(tenant_id=tenant_id)
