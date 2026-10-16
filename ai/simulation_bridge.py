"""Phase 5: the bridge from a validated AI decision to the real simulation.

    CountryDecision (validated)  ->  execute_decision()  ->  Simulation.sanction / alliance / aid

The backend stays the single source of truth. This module contains NO simulation mechanics: it only
translates a decision into one call on the backend's own service layer (`backend.simulation.Simulation`),
which applies the same rules, validation, atomic commit and event recording as POST /actions/*.
Nothing here edits GDP, stability, relationships, trade routes, alliances, sanctions or events.

    SANCTION   -> simulation.sanction(actor, target)
    ALLIANCE   -> simulation.alliance(actor, target)
    AID        -> simulation.aid(actor, target, DEFAULT_AID_AMOUNT)
    NO_ACTION  -> nothing is called; the world is not touched
    anything else -> UnsupportedDecisionError

Outcomes are reported, never faked: if the backend rejects an action the result says "rejected" with the
backend's own message and HTTP-style status code (404 unknown country, 409 duplicate/conflict, 400 invalid).

AID amount: CountryDecision has no amount field, so every AID uses DEFAULT_AID_AMOUNT. The backend allows
1..500 and at most 10% of the actor's GDP, so 10 is valid whenever the actor's GDP is at least 100 (Aurelia
starts at 1800 and stays far above that; the poorest starting country, Istoria, has 310). The backend rules are
NOT changed to fit the AI: if a GDP ever falls below 100, the backend rejects the aid and that is reported.
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel

from backend.rules import ActionError
from backend.simulation import Simulation
from backend.simulation import simulation as shared_simulation
from country_agent import CountryDecision, Decision

logger = logging.getLogger("mun.ai")

DEFAULT_AID_AMOUNT = 10.0  # billions of fictional dollars; see the module docstring


class UnsupportedDecisionError(ValueError):
    """The decision is not one the bridge knows how to execute."""


class BridgeResult(BaseModel):
    """What happened when a decision was handed to the simulation.

    status "executed"  -> the backend accepted the action; `event` and the *_after states are the real result.
    status "no_action" -> NO_ACTION: nothing was called, the world is unchanged.
    status "rejected"  -> the backend refused the action (see `message`, `http_status`); the world is unchanged.
    status "error"     -> unexpected backend failure; the world is unchanged (the backend commits atomically).
    """

    status: Literal["executed", "no_action", "rejected", "error"]
    action: str  # the decision value, e.g. "SANCTION"
    actor: str  # country id
    target: Optional[str] = None  # country id
    amount: Optional[float] = None  # AID only
    message: str
    http_status: Optional[int] = None  # rejected only: the status POST /actions/* would have returned
    event: Optional[dict] = None
    actor_after: Optional[dict] = None
    target_after: Optional[dict] = None

    @property
    def ok(self) -> bool:
        """True for an executed action or a deliberate NO_ACTION; False when the backend said no."""
        return self.status in ("executed", "no_action")

    @property
    def executed(self) -> bool:
        """True only if the backend really changed the world."""
        return self.status == "executed"


def execute_decision(
    decision: CountryDecision, actor_id: str, simulation: Optional[Simulation] = None
) -> BridgeResult:
    """Run one validated decision through the backend's own action functions, exactly once.

    `actor_id` is the acting country's id (not taken from Gemini). Raises ValueError for caller bugs (unknown
    actor, decision made for a different country) and UnsupportedDecisionError for an unknown decision type.
    Backend rejections do NOT raise: they come back as status "rejected".
    """
    sim = simulation if simulation is not None else shared_simulation

    try:
        kind = Decision(decision.decision)
    except ValueError:
        raise UnsupportedDecisionError(f"Unsupported decision: {decision.decision!r}") from None

    actor = sim.get_country(actor_id)
    if actor is None:
        raise ValueError(f"Unknown acting country id '{actor_id}'")
    if decision.country != actor.name:
        raise ValueError(f"Decision is for '{decision.country}' but the acting country is '{actor.name}'")

    if kind is Decision.NO_ACTION:
        return BridgeResult(
            status="no_action",
            action=kind.value,
            actor=actor.id,
            message=f"{actor.name} took no action; the world was not modified.",
        )

    target_id = _resolve_target_id(decision, sim)
    if target_id is None:
        return BridgeResult(
            status="rejected",
            action=kind.value,
            actor=actor.id,
            message=f"Target country '{decision.target}' does not exist",
            http_status=404,
        )

    amount = DEFAULT_AID_AMOUNT if kind is Decision.AID else None
    try:
        if kind is Decision.SANCTION:
            response = sim.sanction(actor.id, target_id)
        elif kind is Decision.ALLIANCE:
            response = sim.alliance(actor.id, target_id)
        else:  # Decision.AID
            response = sim.aid(actor.id, target_id, amount)
    except ActionError as exc:  # the backend refused: report it, do not pretend
        return BridgeResult(
            status="rejected",
            action=kind.value,
            actor=actor.id,
            target=target_id,
            amount=amount,
            message=exc.message,
            http_status=exc.status_code,
        )
    except Exception as exc:  # e.g. the backend's corruption guard; the world is untouched
        logger.exception("Unexpected error while executing %s", kind.value)
        return BridgeResult(
            status="error",
            action=kind.value,
            actor=actor.id,
            target=target_id,
            amount=amount,
            message=f"Unexpected simulation error ({type(exc).__name__}); the world was not modified.",
            http_status=500,
        )

    return BridgeResult(
        status="executed",
        action=kind.value,
        actor=actor.id,
        target=target_id,
        amount=amount,
        message=response.event.message,
        event=response.event.model_dump(mode="json"),
        actor_after=response.actor.model_dump(mode="json") if response.actor else None,
        target_after=response.target.model_dump(mode="json") if response.target else None,
    )


def _resolve_target_id(decision: CountryDecision, sim: Simulation) -> Optional[str]:
    """The agent already derived target_id from the world; for hand-built decisions look the name up."""
    if decision.target_id:
        return decision.target_id
    for country in sim.world.countries:
        if country.name == decision.target:
            return country.id
    return None