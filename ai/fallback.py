"""Phase 4: a safe, deterministic fallback for when Gemini fails or answers with something unusable.

    decide_with_fallback(agent, situation, world) -> AgentOutcome

        Gemini ok + valid decision      -> source "ai",       the AI's decision, no failure info
        Gemini call failed              -> source "fallback", NO_ACTION, failure = "gemini_error"
        Gemini answered, but invalid    -> source "fallback", NO_ACTION, failure = "invalid_response"

The fallback is the same CountryDecision structure the agent normally returns. It is always
NO_ACTION with target null: it never invents a target and never executes anything. The original
failure is kept next to it (error_code / error / raw_response), so nothing is hidden. Error text
comes from the agent, which never includes the API key.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel

from ai.country_agent import MAX_SITUATION_CHARS, CountryAgent, CountryDecision, Decision

FALLBACK_REASON = (
    "AI decision service is temporarily unavailable, so {country} is taking no action "
    "until the situation can be reassessed."
)


def fallback_decision(country: str, situation: str) -> CountryDecision:
    """The one place that defines the fallback: always a valid NO_ACTION, target null, same text every time."""
    return CountryDecision(
        country=country,
        situation=situation.strip()[:MAX_SITUATION_CHARS],
        decision=Decision.NO_ACTION,
        target=None,
        reason=FALLBACK_REASON.format(country=country),
    )


class AgentOutcome(BaseModel):
    """What `decide_with_fallback()` returns. `decision` is ALWAYS a valid CountryDecision.

    source "ai"       -> Gemini's validated decision; the three failure fields are None.
    source "fallback" -> the deterministic fallback; the failure fields say why Gemini was not used:
                         error_code "gemini_error" (the call failed) or "invalid_response" (bad answer).
    """

    source: Literal["ai", "fallback"]
    decision: CountryDecision
    error_code: Optional[Literal["gemini_error", "invalid_response"]] = None
    error: Optional[str] = None
    raw_response: Optional[str] = None  # truncated Gemini reply, only for invalid_response

    @property
    def is_fallback(self) -> bool:
        return self.source == "fallback"


def decide_with_fallback(agent: CountryAgent, situation: str, world: Any) -> AgentOutcome:
    """Ask the agent for a decision; on any AI failure return the fallback instead of an error.

    Still only a proposal: nothing is executed. A blank or too-long `situation` is a caller bug and
    still raises ValueError (it is not an AI failure).
    """
    result = agent.propose(situation, world)
    if result.ok:
        return AgentOutcome(source="ai", decision=result.decision)
    return AgentOutcome(
        source="fallback",
        decision=fallback_decision(agent.profile.name, situation),
        error_code=result.error_code,
        error=result.error,
        raw_response=result.raw_response,
    )