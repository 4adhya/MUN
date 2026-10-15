"""Simulation rules and constants.

Step 1 only holds the shared limits and a consistency checker. Later steps
(sanctions, alliances, aid) will put their rule logic here so that every
change to the world goes through one small, readable place.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a circular import at runtime
    from models import WorldState

# --- Limits -----------------------------------------------------------------
STABILITY_MIN = 0
STABILITY_MAX = 100
RELATIONSHIP_MIN = -100  # open hostility
RELATIONSHIP_MAX = 100   # closest friendship
RESOURCE_MIN = 0
RESOURCE_MAX = 100

# --- Initial relationship tuning (used by countries.py) ----------------------
SHARED_ALLIANCE_BONUS = 25
TRADE_ROUTE_BONUS_PER_10_VOLUME = 3


def clamp(value: int, low: int, high: int) -> int:
    """Keep `value` inside [low, high]."""
    return max(low, min(high, value))


def clamp_relationship(value: int) -> int:
    return clamp(value, RELATIONSHIP_MIN, RELATIONSHIP_MAX)


def clamp_stability(value: int) -> int:
    return clamp(value, STABILITY_MIN, STABILITY_MAX)


def validate_world(world: "WorldState") -> list[str]:
    """Return a list of consistency problems (empty list == world is valid)."""
    problems: list[str] = []
    ids = {c.id for c in world.countries}

    if len(ids) != len(world.countries):
        problems.append("duplicate country ids")

    for c in world.countries:
        for other_id, score in c.relationships.items():
            if other_id not in ids:
                problems.append(f"{c.id}: relationship with unknown country {other_id}")
            if other_id == c.id:
                problems.append(f"{c.id}: relationship with itself")
            if not RELATIONSHIP_MIN <= score <= RELATIONSHIP_MAX:
                problems.append(f"{c.id}->{other_id}: relationship {score} out of range")
            back = next(o for o in world.countries if o.id == other_id).relationships.get(c.id)
            if back != score:
                problems.append(f"{c.id}<->{other_id}: relationship not symmetric")
        for pid in c.trade_partners:
            if pid not in ids:
                problems.append(f"{c.id}: unknown trade partner {pid}")
        if not STABILITY_MIN <= c.stability <= STABILITY_MAX:
            problems.append(f"{c.id}: stability {c.stability} out of range")

    for r in world.trade_routes:
        if r.exporter not in ids or r.importer not in ids:
            problems.append(f"trade route {r.id}: unknown country")
        if r.exporter == r.importer:
            problems.append(f"trade route {r.id}: exporter and importer are the same")

    return problems
