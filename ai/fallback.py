"""Phase 4: the outcome of asking an agent for a decision. An AI failure is a FAILURE, never a decision.

    request_decision(agent, situation, world) -> AgentOutcome

        Gemini ok + valid decision      -> source "ai",     the AI's validated decision, no failure info
        Gemini call failed              -> source "failed", decision None, error_code "gemini_error"
        Gemini answered, but invalid    -> source "failed", decision None, error_code "invalid_response"

(This module used to invent a NO_ACTION when the AI failed. It no longer does: a country that could not
be reached must never look like a country that chose to do nothing. The module keeps its file name so
existing imports of `ai.fallback` keep resolving.)

A failed outcome carries no CountryDecision at all, so nothing downstream can execute it or mistake it for
a deliberate NO_ACTION. The failure details are kept next to it (error_code / error / failure_reason /
http_status / attempts / raw_response). Error text comes from the agent, which never includes the API key.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, model_validator

from ai.country_agent import CountryAgent, CountryDecision


class AgentOutcome(BaseModel):
    """What `request_decision()` returns.

    source "ai"     -> `decision` is Gemini's validated decision; every failure field is None.
    source "failed" -> `decision` is None; the failure fields say why no decision exists:
                       error_code "gemini_error" (the call failed) or "invalid_response" (unusable answer).
    """

    source: Literal["ai", "failed"]
    decision: Optional[CountryDecision] = None
    error_code: Optional[Literal["gemini_error", "invalid_response"]] = None
    error: Optional[str] = None
    failure_reason: Optional[str] = None  # e.g. GEMINI_HTTP_503, GEMINI_TIMEOUT, INVALID_AI_RESPONSE
    http_status: Optional[int] = None
    attempts: Optional[int] = None
    raw_response: Optional[str] = None  # truncated Gemini reply, only for invalid_response

    @model_validator(mode="after")
    def _decision_only_when_the_ai_succeeded(self) -> "AgentOutcome":
        if self.source == "ai" and self.decision is None:
            raise ValueError("an AI outcome needs a decision")
        if self.source == "failed" and self.decision is not None:
            raise ValueError("a failed outcome must not carry a decision")
        return self

    @property
    def ok(self) -> bool:
        return self.source == "ai"

    @property
    def failed(self) -> bool:
        return self.source == "failed"


def request_decision(agent: CountryAgent, situation: str, world: Any) -> AgentOutcome:
    """Ask the agent for a decision. An AI failure comes back as a failed outcome, not as an exception or a decision.

    Still only a proposal: nothing is executed. A blank or too-long `situation` is a caller bug and
    still raises ValueError (it is not an AI failure).
    """
    result = agent.propose(situation, world)
    if result.ok:
        return AgentOutcome(source="ai", decision=result.decision)
    return AgentOutcome(
        source="failed",
        error_code=result.error_code,
        error=result.error,
        failure_reason=result.failure_reason,
        http_status=result.http_status,
        attempts=result.attempts,
        raw_response=result.raw_response,
    )