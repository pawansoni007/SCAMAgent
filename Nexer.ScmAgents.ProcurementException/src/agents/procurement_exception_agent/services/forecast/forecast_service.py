"""
Forecast Service — mock implementation.

Represents calls to the Microsoft Fabric / Forecast API.
In production this would query OneLake or a Fabric Data Agent via the Business API Layer.
"""

from agents.procurement_exception_agent.models import DemandForecast


_MOCK_FORECASTS: dict[str, DemandForecast] = {
    "ITEM001": DemandForecast(item_id="ITEM001", forecast_qty_7d=40,  forecast_qty_30d=160, forecast_confidence=0.90, trend="stable"),
    "ITEM002": DemandForecast(item_id="ITEM002", forecast_qty_7d=80,  forecast_qty_30d=320, forecast_confidence=0.85, trend="increasing"),
    "ITEM003": DemandForecast(item_id="ITEM003", forecast_qty_7d=120, forecast_qty_30d=500, forecast_confidence=0.75, trend="increasing"),
    "ITEM004": DemandForecast(item_id="ITEM004", forecast_qty_7d=30,  forecast_qty_30d=120, forecast_confidence=0.92, trend="stable"),
}


def get_demand_forecast(item_id: str) -> DemandForecast | None:
    """Retrieve demand forecast for an item over 7 and 30 day horizons."""
    return _MOCK_FORECASTS.get(item_id)
