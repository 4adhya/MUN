"""Phase 7: what a crisis response does to a conference's MUN world metrics.

This is the ONLY place a crisis can change a world metric, and it works from an option's `effects` table alone (integer
deltas fixed by `mun.crisis` from the option's action type and the crisis's severity), never from any text. Free text
written by a delegate or an AI agent is never parsed, interpreted or trusted: nothing here even receives it.

Like `negotiation_rules.py`, `apply_effects` mutates the world it is given (the service passes a scratch copy of the
CONFERENCE's world and only commits it after `validate_world` passes) and is deterministic: same metrics + same effects
= same result. It never reads a clock or any global state, so it can never touch the shared sandbox simulation. Every
metric stays inside [METRIC_MIN, METRIC_MAX]; a delta that would push past an end is clamped, and the change that
really happened is reported as `applied`.

`project_effects` computes the same result WITHOUT touching anything, so an advisor (an AI, later) can ask "what would
this option do?" without any way to change the world.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .models import WorldState
from .mun.crisis import METRIC_NAMES
from .mun.metrics import METRIC_MAX, METRIC_MIN, MUNWorldMetrics


@dataclass(frozen=True)
class MetricChange:
    """The result of applying (or projecting) a set of effects on the six MUN metrics."""

    before: dict[str, float]
    after: dict[str, float]
    applied: dict[str, float] = field(default_factory=dict)  # only the metrics that really moved

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def project_effects(metrics: MUNWorldMetrics, effects: Mapping[str, int]) -> MetricChange:
    """What `effects` would do to `metrics`. Pure: `metrics` is not modified."""
    unknown = sorted(set(effects) - set(METRIC_NAMES))
    if unknown:
        raise ValueError(f"Unknown world metric(s): {', '.join(unknown)}")
    before = {name: float(getattr(metrics, name)) for name in METRIC_NAMES}
    after = dict(before)
    for name, delta in effects.items():
        after[name] = round(min(METRIC_MAX, max(METRIC_MIN, before[name] + delta)), 6)
    applied = {name: round(after[name] - before[name], 6) for name in METRIC_NAMES if after[name] != before[name]}
    return MetricChange(before=before, after=after, applied=applied)


def apply_effects(world: WorldState, effects: Mapping[str, int]) -> MetricChange:
    """Apply `effects` to `world.mun_metrics` (the world is modified in place) and report what changed.

    Raises ValueError for an unknown metric; in that case nothing is changed.
    """
    change = project_effects(world.mun_metrics, effects)
    for name, value in change.after.items():
        if name in change.applied:  # validate_assignment keeps every metric inside 0-100
            setattr(world.mun_metrics, name, value)
    return change