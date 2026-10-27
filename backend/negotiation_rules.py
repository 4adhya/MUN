"""Phase 5: what a negotiation outcome does to the geopolitical world.

This is the ONLY place a negotiation can change a diplomatic relationship, and it works from the OUTCOME alone
(accepted, rejected, countered), never from the proposal or counter-offer text. Free text written by a delegate or
an AI agent is never parsed, interpreted or trusted: two proposals with different wording have identical effects.

Like `rules.py`, the function mutates the world it is given (the service passes a scratch copy and only commits it
after `validate_world` passes) and is deterministic: same world + same outcome = same result. Relationships stay
symmetric and inside [RELATIONSHIP_MIN, RELATIONSHIP_MAX]. Sanctions, alliances, trade, GDP and stability are never
touched here; those still change only through the existing sanction / alliance / aid actions.
"""
from __future__ import annotations

from typing import Optional

from .models import WorldState
from .mun import NegotiationStatus
from .rules import ActionResult, clamp_relationship, validate_parties

# --- Tuning ---------------------------------------------------------------------------------------
NEGOTIATION_ACCEPT_RELATIONSHIP_GAIN = 5    # a deal was struck
NEGOTIATION_COUNTER_RELATIONSHIP_GAIN = 1   # engaging with a counter-offer keeps the channel open
NEGOTIATION_REJECT_RELATIONSHIP_DROP = 2    # a rebuff costs a little goodwill
# EXPIRED (ignored) changes nothing: silence is not a decision.

RELATIONSHIP_DELTAS: dict[NegotiationStatus, int] = {
    NegotiationStatus.ACCEPTED: NEGOTIATION_ACCEPT_RELATIONSHIP_GAIN,
    NegotiationStatus.COUNTERED: NEGOTIATION_COUNTER_RELATIONSHIP_GAIN,
    NegotiationStatus.REJECTED: -NEGOTIATION_REJECT_RELATIONSHIP_DROP,
}

_EVENT_TYPES: dict[NegotiationStatus, str] = {
    NegotiationStatus.ACCEPTED: "negotiation_accepted",
    NegotiationStatus.REJECTED: "negotiation_rejected",
    NegotiationStatus.COUNTERED: "negotiation_countered",
}


def relationship_delta(outcome: NegotiationStatus) -> int:
    """The relationship change an outcome causes (0 for any outcome that is not an answer)."""
    return RELATIONSHIP_DELTAS.get(NegotiationStatus(outcome), 0)


def apply_negotiation_outcome(
    world: WorldState,
    proposer_id: str,
    receiver_id: str,
    outcome: NegotiationStatus,
    negotiation_id: Optional[str] = None,
) -> ActionResult:
    """Apply the fixed relationship change for `outcome` between two countries of `world`.

    `proposer_id` / `receiver_id` are country ids (slugs). Raises the usual ActionError (404 unknown country,
    400 same country) and ValueError if `outcome` is not ACCEPTED, REJECTED or COUNTERED.
    """
    outcome = NegotiationStatus(outcome)
    if outcome not in RELATIONSHIP_DELTAS:
        raise ValueError(f"A {outcome.value} negotiation has no relationship effect to apply")
    proposer, receiver = validate_parties(world, proposer_id, receiver_id)

    before = proposer.relationships.get(receiver.id, 0)
    delta = RELATIONSHIP_DELTAS[outcome]
    after = clamp_relationship(before + delta)
    proposer.relationships[receiver.id] = after  # symmetric, like every other relationship change
    receiver.relationships[proposer.id] = after

    return ActionResult(
        type=_EVENT_TYPES[outcome],
        message=(
            f"{receiver.name} {outcome.value.lower()} a negotiation proposal from {proposer.name}; "
            f"relations moved from {before} to {after}."
        ),
        effects={
            "negotiation_id": negotiation_id,
            "outcome": outcome.value,
            "relationship": {"before": before, "after": after, "delta": after - before},
        },
    )