"""In-memory simulation state.

`Simulation` owns the one and only WorldState. Every player action goes
through `_execute`, which:

  1. copies the world,
  2. runs a rule from rules.py on the copy, then recalculates trade state,
  3. checks the copy is still consistent,
  4. records a DiplomacyEvent, and only then
  5. swaps the copy in as the real world.

If anything fails in steps 1-4 the real world is left exactly as it was.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Optional

from .countries import build_countries, build_trade_routes
from .models import ActionResponse, Country, DiplomacyEvent, WorldState
from .rules import (
    ActionResult,
    apply_aid,
    apply_alliance,
    apply_sanction,
    find_country,
    recalculate_trade_effects,
    validate_world,
)


def create_initial_world() -> WorldState:
    world = WorldState(
        turn=0,
        countries=build_countries(),
        trade_routes=build_trade_routes(),
        events=[],  # empty event history
    )
    problems = validate_world(world)
    if problems:  # fail loudly at startup rather than serve a broken world
        raise ValueError("Initial world is inconsistent: " + "; ".join(problems))
    return world


class Simulation:
    def __init__(self) -> None:
        self._world: WorldState = create_initial_world()
        self._lock = RLock()  # FastAPI runs sync routes in a thread pool

    @property
    def world(self) -> WorldState:
        return self._world

    def get_country(self, country_id: str) -> Optional[Country]:
        return find_country(self._world, country_id)

    # --- Actions ---------------------------------------------------------------
    def sanction(self, actor: str, target: str) -> ActionResponse:
        return self._execute(actor, target, lambda w: apply_sanction(w, actor, target))

    def alliance(self, actor: str, target: str) -> ActionResponse:
        return self._execute(actor, target, lambda w: apply_alliance(w, actor, target))

    def aid(self, actor: str, target: str, amount: float) -> ActionResponse:
        return self._execute(actor, target, lambda w: apply_aid(w, actor, target, amount))

    def _execute(
        self,
        actor: str,
        target: str,
        rule: Callable[[WorldState], ActionResult],
    ) -> ActionResponse:
        with self._lock:
            draft = self._world.model_copy(deep=True)
            result = rule(draft)  # raises ActionError on invalid actions
            recalculate_trade_effects(draft)  # idempotent safety net: routes + trade_partners stay in sync

            problems = validate_world(draft)
            if problems:  # a rule bug must never corrupt the real world
                raise RuntimeError("Action would corrupt the world: " + "; ".join(problems))

            event = DiplomacyEvent(
                id=len(draft.events) + 1,
                turn=draft.turn,
                type=result.type,
                actor=actor,
                target=target,
                message=result.message,
                timestamp=datetime.now(timezone.utc),
                effects=result.effects,
            )
            draft.events.append(event)

            self._world = draft  # commit
            return ActionResponse(
                event=event,
                actor=find_country(draft, actor),
                target=find_country(draft, target),
            )

    # --- Events ----------------------------------------------------------------
    def recent_events(self, limit: int = 20) -> list[DiplomacyEvent]:
        """Newest first."""
        with self._lock:
            return list(reversed(self._world.events))[:limit]

    # --- Reset -----------------------------------------------------------------
    def reset(self) -> WorldState:
        """Throw away all state (including events) and rebuild the initial world."""
        with self._lock:
            self._world = create_initial_world()
            return self._world


# Single shared instance used by the API.
simulation = Simulation()