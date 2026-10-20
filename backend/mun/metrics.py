"""MUN-specific global metrics that sit on top of the geopolitical WorldState.

Every metric is a float on the same 0-100 scale. Direction differs per metric:

  higher is better : world_stability, international_trust, cybersecurity_level
  higher is worse  : diplomatic_tension, humanitarian_impact, economic_risk

(`humanitarian_impact` is the severity of humanitarian harm, so 0 = none.)
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

METRIC_MIN = 0.0
METRIC_MAX = 100.0


def _metric(default: float, description: str):
    return Field(default=default, ge=METRIC_MIN, le=METRIC_MAX, allow_inf_nan=False, description=description)


class MUNWorldMetrics(BaseModel):
    # validate_assignment: later phases mutate metrics in place; an out-of-range
    # assignment must fail loudly rather than silently corrupt the world.
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    world_stability: float = _metric(75.0, "Overall global stability, 0-100 (higher is better)")
    diplomatic_tension: float = _metric(30.0, "Level of diplomatic tension between states, 0-100 (higher is worse)")
    humanitarian_impact: float = _metric(20.0, "Severity of humanitarian harm, 0-100 (higher is worse)")
    international_trust: float = _metric(60.0, "Trust between states in the committee, 0-100 (higher is better)")
    cybersecurity_level: float = _metric(50.0, "Global cyber-defence readiness, 0-100 (higher is better)")
    economic_risk: float = _metric(25.0, "Risk of economic disruption, 0-100 (higher is worse)")