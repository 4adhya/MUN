"""Simulation rules and constants.

This module holds the *consequences* of every player action. Each `apply_*`
function mutates the WorldState it is given and returns an `ActionResult`
describing what happened. It never stores events or touches global state;
`simulation.py` does that (and runs these functions on a scratch copy of the
world, so a failed action can never leave the real world half-changed).

All rules are deterministic: the same world + the same action always gives
the same result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid a circular import at runtime
    from models import Country, WorldState

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

# --- Sanction tuning ---------------------------------------------------------
SANCTION_GDP_LOSS_RATE = 0.03        # target loses 3% of its GDP
SANCTION_STABILITY_LOSS = 5          # target stability points lost
SANCTION_RELATIONSHIP_DROP = 25      # applied to both directions of the pair

# --- Alliance tuning ---------------------------------------------------------
ALLIANCE_RELATIONSHIP_GAIN = 20      # applied to both directions of the pair
ALLIANCE_STABILITY_GAIN = 2          # each ally
# --- Trade tuning --------------------------------------------------------------
# A route's current volume is always base_volume * efficiency / 100.
TRADE_EFFICIENCY_BASELINE = 100      # normal, unsanctioned trade
TRADE_EFFICIENCY_CUT = 0             # sanctioned: route inactive, nothing flows
TRADE_EFFICIENCY_MAX = 150           # hard ceiling for any boost
ALLIANCE_TRADE_EFFICIENCY = 110      # direct routes between new allies run at 110% (a SET, never stacked)

# --- Aid tuning --------------------------------------------------------------
MIN_AID_AMOUNT = 1.0                 # billions of fictional dollars
MAX_AID_AMOUNT = 500.0
MAX_AID_GDP_SHARE = 0.10             # actor may give at most 10% of its GDP at once
AID_ACTOR_GDP_COST_RATE = 0.20       # actor GDP falls by 20% of the amount
AID_TARGET_GDP_GAIN_RATE = 0.40      # target GDP rises by 40% of the amount
AID_STABILITY_PER = 25.0             # +1 stability per 25 aid, capped below
AID_MAX_STABILITY_GAIN = 5
AID_RELATIONSHIP_PER = 10.0          # +1 relationship per 10 aid, capped below
AID_MAX_RELATIONSHIP_GAIN = 15


# --- Errors --------------------------------------------------------------------
class ActionError(Exception):
    """A player action was rejected. `status_code` is the HTTP status to use."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ActionError):
    status_code = 404


class ConflictError(ActionError):
    status_code = 409


@dataclass
class ActionResult:
    """What an action did. `simulation.py` turns this into a DiplomacyEvent."""

    type: str
    message: str
    effects: dict[str, Any] = field(default_factory=dict)


# --- Small helpers ---------------------------------------------------------------
def clamp(value: int, low: int, high: int) -> int:
    """Keep `value` inside [low, high]."""
    return max(low, min(high, value))


def clamp_relationship(value: int) -> int:
    return clamp(value, RELATIONSHIP_MIN, RELATIONSHIP_MAX)


def clamp_stability(value: int) -> int:
    return clamp(value, STABILITY_MIN, STABILITY_MAX)


def _round_gdp(value: float) -> float:
    return round(max(0.0, value), 2)


def find_country(world: "WorldState", country_id: str) -> "Country | None":
    for country in world.countries:
        if country.id == country_id:
            return country
    return None


def validate_parties(world: "WorldState", actor_id: str, target_id: str) -> tuple["Country", "Country"]:
    """Check both countries exist and are different. Returns (actor, target)."""
    actor = find_country(world, actor_id)
    if actor is None:
        raise NotFoundError(f"Actor country '{actor_id}' does not exist")
    target = find_country(world, target_id)
    if target is None:
        raise NotFoundError(f"Target country '{target_id}' does not exist")
    if actor.id == target.id:
        raise ActionError("Actor and target must be different countries")
    return actor, target


def validate_aid_amount(amount: float, actor: "Country") -> None:
    if amount < MIN_AID_AMOUNT:
        raise ActionError(f"Aid amount must be at least {MIN_AID_AMOUNT:g}")
    if amount > MAX_AID_AMOUNT:
        raise ActionError(f"Aid amount cannot exceed {MAX_AID_AMOUNT:g} in a single action")
    limit = round(actor.gdp * MAX_AID_GDP_SHARE, 2)
    if amount > limit:
        raise ActionError(
            f"{actor.name} can give at most {limit:g} in one action "
            f"({int(MAX_AID_GDP_SHARE * 100)}% of its GDP)"
        )


def _shared_alliances(a: "Country", b: "Country") -> list[str]:
    return [name for name in a.alliances if name in b.alliances]


def _routes_between(world: "WorldState", a_id: str, b_id: str):
    pair = {a_id, b_id}
    return [r for r in world.trade_routes if {r.exporter, r.importer} == pair]


def _change_relationship(a: "Country", b: "Country", delta: int) -> int:
    """Move the (symmetric) relationship between a and b by delta. Returns new score."""
    new_score = clamp_relationship(a.relationships.get(b.id, 0) + delta)
    a.relationships[b.id] = new_score
    b.relationships[a.id] = new_score
    return new_score


def refresh_trade_partners(world: "WorldState") -> None:
    """Recompute every country's trade_partners from the ACTIVE trade routes."""
    partners: dict[str, set[str]] = {c.id: set() for c in world.countries}
    for r in world.trade_routes:
        if r.active:
            partners[r.exporter].add(r.importer)
            partners[r.importer].add(r.exporter)
    for c in world.countries:
        c.trade_partners = sorted(partners[c.id])


# --- Trade ---------------------------------------------------------------------
def effective_volume(base_volume: int, efficiency: int) -> int:
    """Current volume of a route: 0 when cut off, otherwise at least 1."""
    if efficiency <= 0:
        return 0
    return max(1, round(base_volume * efficiency / 100))


def pair_is_sanctioned(world: "WorldState", a_id: str, b_id: str) -> bool:
    """True if either country sanctions the other (trade is cut in both directions)."""
    a, b = find_country(world, a_id), find_country(world, b_id)
    if a is None or b is None:
        return False
    return a.id in b.sanctions or b.id in a.sanctions


def _route_state(route) -> dict[str, Any]:
    return {"active": route.active, "efficiency": route.efficiency, "volume": route.volume}


def boost_routes_between(world: "WorldState", a_id: str, b_id: str) -> list[str]:
    """Raise efficiency of the ACTIVE direct routes between two countries.

    The boost is a floor (`max`), not an addition, so applying it again to the
    same pair can never stack. Call `recalculate_trade_effects` afterwards.
    """
    boosted = []
    for route in _routes_between(world, a_id, b_id):
        if route.active and route.efficiency < ALLIANCE_TRADE_EFFICIENCY:
            route.efficiency = ALLIANCE_TRADE_EFFICIENCY
            boosted.append(route.id)
    return boosted


def recalculate_trade_effects(world: "WorldState") -> dict[str, dict[str, Any]]:
    """Bring every trade route and every trade_partners list back in line with the world.

    For each route:
      * if either country sanctions the other -> inactive, efficiency 0, volume 0
      * otherwise -> active (a route that was cut but is no longer sanctioned is
        restored to baseline efficiency); efficiency is kept within sane bounds
      * volume is always recomputed as base_volume * efficiency / 100
    Then trade_partners is rebuilt from the active routes.

    Idempotent: running it twice gives the same result as running it once.
    Returns {route_id: {"before": state, "after": state}} for routes that changed.
    """
    changes: dict[str, dict[str, Any]] = {}
    for route in world.trade_routes:
        before = _route_state(route)

        if pair_is_sanctioned(world, route.exporter, route.importer):
            route.active = False
            route.efficiency = TRADE_EFFICIENCY_CUT
        else:
            if not route.active or route.efficiency <= 0:
                route.active = True
                route.efficiency = TRADE_EFFICIENCY_BASELINE
            route.efficiency = clamp(route.efficiency, 1, TRADE_EFFICIENCY_MAX)
        route.volume = effective_volume(route.base_volume, route.efficiency)

        after = _route_state(route)
        if after != before:
            changes[route.id] = {"before": before, "after": after}

    refresh_trade_partners(world)
    return changes


# --- Actions ---------------------------------------------------------------------
def apply_sanction(world: "WorldState", actor_id: str, target_id: str) -> ActionResult:
    actor, target = validate_parties(world, actor_id, target_id)
    if actor.id in target.sanctions:
        raise ConflictError(f"{actor.name} already sanctions {target.name}")

    target.sanctions.append(actor.id)

    gdp_before, stability_before = target.gdp, target.stability
    target.gdp = _round_gdp(target.gdp * (1 - SANCTION_GDP_LOSS_RATE))
    target.stability = clamp_stability(target.stability - SANCTION_STABILITY_LOSS)
    relationship = _change_relationship(actor, target, -SANCTION_RELATIONSHIP_DROP)

    # Trade between the two countries is cut off (both directions). The sanction
    # is already recorded above, so recalculation does the rest.
    trade_changes = recalculate_trade_effects(world)
    cut_routes = sorted(rid for rid, ch in trade_changes.items() if not ch["after"]["active"])

    return ActionResult(
        type="sanction",
        message=(
            f"{actor.name} imposed sanctions on {target.name}. "
            f"{target.name}'s economy and stability took a hit"
            + (f", and {len(cut_routes)} trade route(s) were suspended." if cut_routes else ".")
        ),
        effects={
            "target_gdp": {"before": gdp_before, "after": target.gdp},
            "target_stability": {"before": stability_before, "after": target.stability},
            "relationship": relationship,
            "trade_routes_deactivated": cut_routes,
            "trade_routes": trade_changes,
        },
    )


def apply_alliance(world: "WorldState", actor_id: str, target_id: str) -> ActionResult:
    actor, target = validate_parties(world, actor_id, target_id)

    shared = _shared_alliances(actor, target)
    if shared:
        raise ConflictError(f"{actor.name} and {target.name} are already allied ({shared[0]})")
    if actor.id in target.sanctions or target.id in actor.sanctions:
        raise ConflictError(
            f"{actor.name} and {target.name} cannot ally while sanctions exist between them"
        )

    first, second = sorted((actor, target), key=lambda c: c.id)
    alliance_name = f"{first.name}-{second.name} Alliance"
    actor.alliances.append(alliance_name)
    target.alliances.append(alliance_name)

    stability_before = {actor.id: actor.stability, target.id: target.stability}
    actor.stability = clamp_stability(actor.stability + ALLIANCE_STABILITY_GAIN)
    target.stability = clamp_stability(target.stability + ALLIANCE_STABILITY_GAIN)
    relationship = _change_relationship(actor, target, ALLIANCE_RELATIONSHIP_GAIN)

    # Direct routes between the new allies run at the alliance efficiency.
    boost_routes_between(world, actor.id, target.id)
    trade_changes = recalculate_trade_effects(world)
    boosted = {
        rid: {"before": ch["before"]["volume"], "after": ch["after"]["volume"]}
        for rid, ch in trade_changes.items()
    }

    return ActionResult(
        type="alliance",
        message=f"{actor.name} and {target.name} formed the {alliance_name}.",
        effects={
            "alliance": alliance_name,
            "stability": {
                actor.id: {"before": stability_before[actor.id], "after": actor.stability},
                target.id: {"before": stability_before[target.id], "after": target.stability},
            },
            "relationship": relationship,
            "trade_routes_boosted": boosted,
            "trade_routes": trade_changes,
        },
    )


def apply_aid(world: "WorldState", actor_id: str, target_id: str, amount: float) -> ActionResult:
    actor, target = validate_parties(world, actor_id, target_id)
    validate_aid_amount(amount, actor)

    actor_gdp_before, target_gdp_before = actor.gdp, target.gdp
    stability_before = target.stability

    actor.gdp = _round_gdp(actor.gdp - amount * AID_ACTOR_GDP_COST_RATE)
    target.gdp = _round_gdp(target.gdp + amount * AID_TARGET_GDP_GAIN_RATE)
    stability_gain = clamp(round(amount / AID_STABILITY_PER), 1, AID_MAX_STABILITY_GAIN)
    target.stability = clamp_stability(target.stability + stability_gain)
    relationship_gain = clamp(round(amount / AID_RELATIONSHIP_PER), 1, AID_MAX_RELATIONSHIP_GAIN)
    relationship = _change_relationship(actor, target, relationship_gain)

    return ActionResult(
        type="aid",
        message=f"{actor.name} sent {amount:g} in aid to {target.name}.",
        effects={
            "amount": amount,
            "actor_gdp": {"before": actor_gdp_before, "after": actor.gdp},
            "target_gdp": {"before": target_gdp_before, "after": target.gdp},
            "target_stability": {"before": stability_before, "after": target.stability},
            "relationship": relationship,
        },
    )


# --- Consistency checker ---------------------------------------------------------
def validate_world(world: "WorldState") -> list[str]:
    """Return a list of consistency problems (empty list == world is valid)."""
    problems: list[str] = []
    ids = {c.id for c in world.countries}

    if len(ids) != len(world.countries):
        problems.append("duplicate country ids")

    active_partners: dict[str, set[str]] = {i: set() for i in ids}
    for r in world.trade_routes:
        if r.active and r.exporter in ids and r.importer in ids:
            active_partners[r.exporter].add(r.importer)
            active_partners[r.importer].add(r.exporter)

    for c in world.countries:
        for other_id, score in c.relationships.items():
            if other_id not in ids:
                problems.append(f"{c.id}: relationship with unknown country {other_id}")
                continue
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
        if set(c.trade_partners) != active_partners[c.id]:
            problems.append(f"{c.id}: trade_partners disagree with active trade routes")
        for sid in c.sanctions:
            if sid not in ids or sid == c.id:
                problems.append(f"{c.id}: invalid sanctioning country {sid}")
        if not STABILITY_MIN <= c.stability <= STABILITY_MAX:
            problems.append(f"{c.id}: stability {c.stability} out of range")
        for resource, amount in c.resources.items():
            if not RESOURCE_MIN <= amount <= RESOURCE_MAX:
                problems.append(f"{c.id}: resource {resource} {amount} out of range")
        if c.gdp < 0:
            problems.append(f"{c.id}: negative gdp")

    for r in world.trade_routes:
        if r.exporter not in ids or r.importer not in ids:
            problems.append(f"trade route {r.id}: unknown country")
        if r.exporter == r.importer:
            problems.append(f"trade route {r.id}: exporter and importer are the same")
        if r.base_volume <= 0:
            problems.append(f"trade route {r.id}: base_volume {r.base_volume} must be positive")
        if r.volume < 0:
            problems.append(f"trade route {r.id}: negative volume")
        if not 0 <= r.efficiency <= TRADE_EFFICIENCY_MAX:
            problems.append(f"trade route {r.id}: efficiency {r.efficiency} out of range")
        elif r.volume != effective_volume(r.base_volume, r.efficiency):
            problems.append(f"trade route {r.id}: volume does not match base_volume * efficiency")
        if r.active and r.efficiency == 0:
            problems.append(f"trade route {r.id}: active route has zero efficiency")
        if not r.active and (r.efficiency != 0 or r.volume != 0):
            problems.append(f"trade route {r.id}: inactive route still has trade flowing")
        if r.exporter in ids and r.importer in ids:
            if r.active == pair_is_sanctioned(world, r.exporter, r.importer):
                problems.append(f"trade route {r.id}: active flag disagrees with sanctions")

    return problems