"""Fallback tests: Gemini failure or an unusable reply gives a deterministic, valid NO_ACTION. All Gemini replies are MOCKS."""
import json

import pytest

from backend.simulation import Simulation
from ai.check_gemini import CheckError
from ai.country_agent import IndiaAgent, CountryDecision, Decision
from ai.fallback import FALLBACK_REASON, decide_with_fallback, fallback_decision

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

    return decide_with_fallback(IndiaAgent(llm=llm), SITUATION, Simulation().world)


def test_valid_gemini_reply_is_an_ai_decision():
    out = outcome_for(good_reply())
    assert out.source == "ai" and not out.is_fallback
    assert out.decision.decision is Decision.SANCTION and out.decision.target == "Brazil"
    assert out.error_code is None and out.error is None


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
def test_any_ai_failure_gives_the_deterministic_fallback(bad, code):
    out = outcome_for(bad)
    assert out.source == "fallback" and out.is_fallback and out.error_code == code
    assert out.decision.decision is Decision.NO_ACTION and out.decision.target is None
    assert out.decision.reason == FALLBACK_REASON.format(country="India")


def test_fallback_is_valid_for_the_decision_model_and_identical_every_time():
    first, second = fallback_decision("India", SITUATION), fallback_decision("India", SITUATION)
    assert first == second
    assert CountryDecision.model_validate(first.model_dump(mode="json")).decision is Decision.NO_ACTION


def test_fallback_error_text_never_contains_the_api_key(monkeypatch):
    secret = "AIza-super-secret-test-key"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    out = outcome_for(RuntimeError(f"failed with key {secret}"))
    assert secret not in (out.error or "") and secret not in (out.raw_response or "")
    assert secret not in out.decision.model_dump_json()