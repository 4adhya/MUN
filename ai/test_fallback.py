"""Outcome tests: a Gemini failure or an unusable reply is a FAILURE with no decision, never a NO_ACTION.

All Gemini replies are MOCKS. (File name kept from the old fallback tests.)
"""
import json

import pytest

from backend.simulation import Simulation
from ai.check_gemini import CheckError
from ai.country_agent import IndiaAgent, Decision
from ai.fallback import AgentOutcome, request_decision

SITUATION = "Brazil blocked India's trade route."


def good_reply(decision="SANCTION", target="Brazil"):
    return json.dumps(
        {"country": "India", "situation": "Trade blocked.", "decision": decision, "target": target, "reason": "Protect trade."}
    )


def outcome_for(llm_result):
    def llm(system_prompt, user_prompt):
        if isinstance(llm_result, Exception):
            raise llm_result
        return llm_result

    return request_decision(IndiaAgent(llm=llm), SITUATION, Simulation().world)


def test_valid_gemini_reply_is_an_ai_decision():
    out = outcome_for(good_reply())
    assert out.source == "ai" and out.ok and not out.failed
    assert out.decision.decision is Decision.SANCTION and out.decision.target == "Brazil"
    assert out.error_code is None and out.error is None and out.failure_reason is None


def test_a_deliberate_ai_no_action_is_still_an_ai_decision():
    out = outcome_for(good_reply("NO_ACTION", None))
    assert out.source == "ai" and out.ok and out.decision.decision is Decision.NO_ACTION


@pytest.mark.parametrize(
    "bad, code",
    [
        (CheckError("Gemini service error (HTTP 503)", 3), "gemini_error"),
        (RuntimeError("boom"), "gemini_error"),
        ("not json at all", "invalid_response"),
        ("", "invalid_response"),
        (good_reply("ATTACK", "Brazil"), "invalid_response"),
        (good_reply("SANCTION", "Atlantis"), "invalid_response"),
    ],
    ids=["unavailable", "unexpected", "malformed", "empty", "invalid_decision", "unknown_target"],
)
def test_any_ai_failure_is_a_failure_with_no_decision(bad, code):
    out = outcome_for(bad)
    assert out.source == "failed" and out.failed and not out.ok
    assert out.error_code == code and out.error and out.failure_reason
    assert out.decision is None  # in particular, never a NO_ACTION


def test_a_failed_outcome_cannot_carry_a_decision_and_an_ai_outcome_needs_one():
    decision = outcome_for(good_reply()).decision
    with pytest.raises(ValueError):
        AgentOutcome(source="failed", decision=decision)
    with pytest.raises(ValueError):
        AgentOutcome(source="ai")


def test_failure_error_text_never_contains_the_api_key(monkeypatch):
    secret = "AIza-super-secret-test-key"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    out = outcome_for(RuntimeError(f"failed with key {secret}"))
    assert secret not in (out.error or "") and secret not in (out.raw_response or "")
    assert secret not in out.model_dump_json()