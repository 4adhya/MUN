"""Phase 5: one complete AI turn for one country, executed ONCE per call.

    run_country_turn("india", "Brazil blocked our trade route.")

        simulation world  ->  situation + briefing  ->  Gemini  ->  validated CountryDecision
        (Gemini failed or invalid -> Phase 4 fallback NO_ACTION)
        -> simulation_bridge.execute_decision() -> backend action (or nothing for NO_ACTION)
        -> TurnResult (decision, fallback info, backend result, event, new state)

No loops, no turn advancement, no scheduling: calling it again is a new, separate turn (the backend's
duplicate protections still apply). It is country-agnostic: add another agent to AGENT_FACTORIES later and
call run_country_turn("china") the same way. Only India is configured for now.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from pydantic import BaseModel

from backend.simulation import Simulation
from backend.simulation import simulation as shared_simulation
from ai.country_agent import LLM, CountryAgent, CountryDecision, IndiaAgent
from ai.fallback import decide_with_fallback
from ai.simulation_bridge import BridgeResult, execute_decision

# country id -> factory(llm) building that country's agent. India is the only one so far.
AGENT_FACTORIES: dict[str, Callable[[Optional[LLM]], CountryAgent]] = {
    "india": lambda llm=None: IndiaAgent(llm=llm),
}

NO_INCIDENT_SITUATION = "No new incident. Review the current state and decide whether any action is needed."


class TurnResult(BaseModel):
    """Everything a caller (CLI today, n8n later) needs from one turn."""

    country_id: str
    situation: str
    decision: CountryDecision  # the AI's decision, or the safe fallback
    source: str  # "ai" or "fallback"
    used_fallback: bool
    fallback_error_code: Optional[str] = None  # "gemini_error" | "invalid_response" when used_fallback
    fallback_error: Optional[str] = None  # why the AI decision was not used (never contains the API key)
    raw_response: Optional[str] = None  # truncated Gemini reply, only for invalid_response
    action: BridgeResult  # what the backend did (or refused to do)

    @property
    def ok(self) -> bool:
        """False only when the backend rejected the action. A fallback NO_ACTION is still ok."""
        return self.action.ok

    @property
    def world_changed(self) -> bool:
        return self.action.executed


def create_agent(country_id: str, llm: Optional[LLM] = None) -> CountryAgent:
    factory = AGENT_FACTORIES.get(country_id)
    if factory is None:
        configured = ", ".join(sorted(AGENT_FACTORIES))
        raise ValueError(f"No agent is configured for country '{country_id}' (configured: {configured})")
    return factory(llm)


def default_situation(world: Any, country_id: str) -> str:
    """Latest diplomacy event aimed at the country, else a neutral prompt to review the state."""
    country = next((c for c in world.countries if c.id == country_id), None)
    if country is not None:
        for event in reversed(world.events):
            if event.target == country_id:
                return f"Recent diplomatic event affecting {country.name}: {event.message}"
    return NO_INCIDENT_SITUATION


def run_country_turn(
    country_id: str,
    situation: Optional[str] = None,
    *,
    simulation: Optional[Simulation] = None,
    agent: Optional[CountryAgent] = None,
    llm: Optional[LLM] = None,
) -> TurnResult:
    """Observe the world, let the country's agent decide, execute through the backend, report. Once.

    `simulation` defaults to the shared backend instance; `agent`/`llm` exist so tests can inject a mocked Gemini.
    Gemini problems never raise (fallback NO_ACTION); a backend rejection never raises (status "rejected").
    A blank/too-long `situation`, an unknown country or an unconfigured agent raise ValueError (caller bugs).
    """
    sim = simulation if simulation is not None else shared_simulation
    country_id = country_id.strip().lower()
    if sim.get_country(country_id) is None:
        raise ValueError(f"Unknown country id '{country_id}'")

    agent = agent if agent is not None else create_agent(country_id, llm)
    if agent.profile.country_id != country_id:
        raise ValueError(f"Agent is for '{agent.profile.country_id}', not '{country_id}'")

    world = sim.world  # the real current state; the agent's briefing is built from it
    situation = situation if situation is not None else default_situation(world, country_id)

    outcome = decide_with_fallback(agent, situation, world)  # AI decision, or Phase 4 fallback
    action = execute_decision(outcome.decision, country_id, sim)  # backend validation stays authoritative

    return TurnResult(
        country_id=country_id,
        situation=situation.strip(),
        decision=outcome.decision,
        source=outcome.source,
        used_fallback=outcome.is_fallback,
        fallback_error_code=outcome.error_code,
        fallback_error=outcome.error,
        raw_response=outcome.raw_response,
        action=action,
    )