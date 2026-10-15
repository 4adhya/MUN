"""In-memory simulation state.

`Simulation` owns the one and only WorldState. For now it can only build the
initial world and read from it; actions (sanctions, alliances, aid) are added
in later steps and will mutate state through this class using rules.py.
"""
from __future__ import annotations

from typing import Optional

from countries import build_countries, build_trade_routes
from models import Country, WorldState
from rules import validate_world


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

    @property
    def world(self) -> WorldState:
        return self._world

    def get_country(self, country_id: str) -> Optional[Country]:
        for country in self._world.countries:
            if country.id == country_id:
                return country
        return None

    def reset(self) -> WorldState:
        """Throw away all state and rebuild the initial world."""
        self._world = create_initial_world()
        return self._world


# Single shared instance used by the API.
simulation = Simulation()
