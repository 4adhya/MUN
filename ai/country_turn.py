"""Phase 5: one complete AI turn for one country, executed ONCE per call.

    run_country_turn("india", "Brazil blocked our trade route.")

        simulation world  ->  situation + briefing  ->  Gemini  ->  validated CountryDecision
        -> simulation_bridge.execute_decision() -> backend action (or nothing for a deliberate NO_ACTION)
        -> TurnResult (decision, backend result, event, new state)

If Gemini fails or answers with something invalid there is NO decision: the turn ends with source "failed",
`decision` and `action` are None, nothing is executed and the world is untouched. A failure is never turned
into a NO_ACTION, so it cannot be mistaken for a country that chose to do nothing.

No loops, no turn advancement, no scheduling: calling it again is a new, separate turn (the backend's
duplicate protections still apply). It is country-agnostic: add another agent to AGENT_FACTORIES later and
call run_country_turn("china") the same way. Only India is configured for now.
"""
from __future__ import annotations

from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel

from backend.country_registry import find_world_country
from backend.simulation import Simulation
from backend.simulation import simulation as shared_simulation
from ai.country_agent import LLM, CountryAgent, CountryDecision, IndiaAgent
from ai.fallback import request_decision
from ai.simulation_bridge import BridgeResult, execute_decision

# country id -> factory(llm) building that country's agent. India is the only one so far.
AGENT_FACTORIES: dict[str, Callable[[Optional[LLM]], CountryAgent]] = {
    "india": lambda llm=None: IndiaAgent(llm=llm),
}

NO_INCIDENT_SITUATION = "No new incident. Review the current state and decide whether any action is needed."


class TurnResult(BaseModel):
    """Everything a caller (CLI today, n8n later) needs from one turn.

    source "ai"     -> `decision` is Gemini's validated decision and `action` is what the backend did with it.
    source "failed" -> no decision exists: `decision` and `action` are None and the failure fields say why.
    """

    country_id: str
    situation: str
    source: Literal["ai", "failed"]
    decision: Optional[CountryDecision] = None  # None when the AI failed; a failure is never a NO_ACTION
    error_code: Optional[str] = None  # "gemini_error" | "invalid_response" when source == "failed"
    error: Optional[str] = None  # why there is no decision (never contains the API key)
    failure_reason: Optional[str] = None  # e.g. GEMINI_HTTP_503, GEMINI_TIMEOUT, INVALID_AI_RESPONSE
    http_status: Optional[int] = None
    attempts: Optional[int] = None
    raw_response: Optional[str] = None  # truncated Gemini reply, only for invalid_response
    action: Optional[BridgeResult] = None  # what the backend did (or refused to do); None when the AI failed

    @property
    def ai_failed(self) -> bool:
        return self.source == "failed"

    @property
    def ok(self) -> bool:
        """True only if the AI produced a decision AND the backend did not reject it. An AI failure is never ok."""
        return self.action is not None and self.action.ok

    @property
    def world_changed(self) -> bool:
        return self.action is not None and self.action.executed


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
    `country_id` is resolved through the country registry ("India", "india", "IND" ...), the same way the API does.
    Gemini problems never raise and never become a decision: the result has source "failed", no decision, no action,
    and the world is untouched. A backend rejection never raises (status "rejected").
    A blank/too-long `situation`, an unknown country or an unconfigured agent raise ValueError (caller bugs).
    """
    sim = simulation if simulation is not None else shared_simulation
    country = find_world_country(sim.world, country_id)
    if country is None:
        raise ValueError(f"Unknown country id '{str(country_id).strip()}'")
    country_id = country.id

    agent = agent if agent is not None else create_agent(country_id, llm)
    if agent.profile.country_id != country_id:
        raise ValueError(f"Agent is for '{agent.profile.country_id}', not '{country_id}'")

    world = sim.world  # the real current state; the agent's briefing is built from it
    situation = situation if situation is not None else default_situation(world, country_id)

    outcome = request_decision(agent, situation, world)  # a validated AI decision, or a failure (no decision)
    if outcome.failed:
        return TurnResult(
            country_id=country_id,
            situation=situation.strip(),
            source="failed",
            error_code=outcome.error_code,
            error=outcome.error,
            failure_reason=outcome.failure_reason,
            http_status=outcome.http_status,
            attempts=outcome.attempts,
            raw_response=outcome.raw_response,
        )

    action = execute_decision(outcome.decision, country_id, sim)  # backend validation stays authoritative
    return TurnResult(
        country_id=country_id,
        situation=situation.strip(),
        source="ai",
        decision=outcome.decision,
        action=action,
    )