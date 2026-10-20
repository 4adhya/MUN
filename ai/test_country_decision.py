"""Phase 3: strict validation of the structured decision (CountryDecision).

Every Gemini reply in this file is a MOCK: a canned string handed to the agent through a fake `llm`.
These tests prove that valid decisions are accepted and that anything else is rejected, never
repaired. They say nothing about what the real Gemini would decide (see test_country_agent_live.py).

Run from ai/:  pytest
"""
import json
import sys

import pytest
from pydantic import ValidationError

from ai import run_agent
from ai.check_gemini import CheckError
from ai.country_agent import (
    INDIA_PROFILE,
    IndiaAgent,
    CountryDecision,
    Decision,
    ResponseError,
    parse_decision,
)
from backend.simulation import create_initial_world

SITUATION = "Brazil blocked our trade route."

# The example decision from the Phase 3 brief.
GOOD = {
    "country": "India",
    "situation": "Brazil blocked India's trade route.",
    "decision": "SANCTION",
    "target": "Brazil",
    "reason": "Brazil's action threatens India's trade and economic stability.",
}


def body(**overrides):
    """GOOD with some fields changed; pass `field=...` to remove a field."""
    data = {**GOOD, **overrides}
    return {k: v for k, v in data.items() if v is not ...}


def raw(**overrides):
    return json.dumps(body(**overrides))


@pytest.fixture
def world():
    return create_initial_world()


def propose(text, world):
    """Run the whole agent pipeline with a mocked Gemini that replies `text`."""
    return IndiaAgent(llm=lambda system_prompt, user_prompt: text).propose(SITUATION, world)


def assert_rejected(result, expected_error=None):
    assert result.ok is False
    assert result.decision is None
    assert result.error_code == "invalid_response"  # a validation failure, NOT a Gemini/API failure
    assert result.error
    if expected_error:
        assert expected_error in result.error


# --- 1-4. valid decisions are accepted ----------------------------------------------------------
@pytest.mark.parametrize(
    "decision, target, target_id",
    [
        ("SANCTION", "Brazil", "brazil"),
        ("ALLIANCE", "Japan", "japan"),
        ("AID", "France", "france"),
        ("NO_ACTION", None, None),
    ],
)
def test_valid_decisions_are_accepted(world, decision, target, target_id):
    result = propose(raw(decision=decision, target=target), world)
    assert result.ok and result.error is None and result.error_code is None
    d = result.decision
    assert isinstance(d, CountryDecision)
    assert d.decision is Decision(decision)
    assert d.target == target and d.target_id == target_id
    assert d.country == "India" and d.situation and d.reason


def test_the_brief_example_round_trips_exactly(world):
    result = propose(json.dumps(GOOD), world)
    assert result.ok
    assert result.decision.model_dump(mode="json") == GOOD  # exactly the five fields, nothing added


def test_no_action_requires_an_explicit_null_target(world):
    result = propose(raw(decision="NO_ACTION", target=None), world)
    assert result.ok and result.decision.target is None and result.decision.target_id is None


# --- 5-9, 11. invalid decisions are rejected -----------------------------------------------------
REJECTED = {
    # 5. invalid decision value
    "decision NUKE": (raw(decision="NUKE"), "decision"),
    "decision empty": (raw(decision=""), "decision"),
    "decision number": (raw(decision=5), "decision"),
    "decision null": (raw(decision=None), "decision"),
    "decision list": (raw(decision=["SANCTION"]), "decision"),
    "decision missing": (raw(decision=...), "decision: Field required"),
    # 6. missing target for SANCTION / ALLIANCE / AID
    "sanction target missing": (raw(target=...), "target: Field required"),
    "sanction target null": (raw(target=None), "SANCTION requires a target"),
    "sanction target empty": (raw(target=""), "SANCTION requires a target"),
    "sanction target blank": (raw(target="  "), "SANCTION requires a target"),
    "alliance target missing": (raw(decision="ALLIANCE", target=...), "target: Field required"),
    "alliance target null": (raw(decision="ALLIANCE", target=None), "ALLIANCE requires a target"),
    "aid target missing": (raw(decision="AID", target=...), "target: Field required"),
    "aid target null": (raw(decision="AID", target=None), "AID requires a target"),
    # 7. target = India
    "sanction self": (raw(target="India"), "own country"),
    "alliance self": (raw(decision="ALLIANCE", target="India"), "own country"),
    "aid self": (raw(decision="AID", target="India"), "own country"),
    # 8. target not in the world state
    "sanction unknown": (raw(target="Atlantis"), "Unknown target country 'Atlantis'"),
    "alliance unknown": (raw(decision="ALLIANCE", target="Atlantis"), "Unknown target country"),
    "aid unknown": (raw(decision="AID", target="Atlantis"), "Unknown target country"),
    "target number": (raw(target=7), "target"),
    "target list": (raw(target=["Brazil"]), "target"),
    # 9. NO_ACTION with a non-null target
    "no_action target country": (raw(decision="NO_ACTION", target="Brazil"), "must not have a target"),
    "no_action target india": (raw(decision="NO_ACTION", target="India"), "must not have a target"),
    "no_action target empty string": (raw(decision="NO_ACTION", target=""), "must not have a target"),
    "no_action target 'none'": (raw(decision="NO_ACTION", target="none"), "must not have a target"),
    "no_action target 'null'": (raw(decision="NO_ACTION", target="null"), "must not have a target"),
    "no_action target missing": (raw(decision="NO_ACTION", target=...), "target: Field required"),
    # 1-3, 6. country / situation / reason
    "country wrong": (raw(country="Brazil"), "expected 'India'"),
    "country missing": (raw(country=...), "country: Field required"),
    "country null": (raw(country=None), "country"),
    "situation missing": (raw(situation=...), "situation: Field required"),
    "situation empty": (raw(situation=""), "situation"),
    "situation blank": (raw(situation="   "), "situation"),
    "situation number": (raw(situation=5), "situation"),
    "situation too long": (raw(situation="x" * 1001), "situation"),
    "reason missing": (raw(reason=...), "reason: Field required"),
    "reason empty": (raw(reason=""), "reason"),
    "reason blank": (raw(reason="   "), "reason"),
    "reason null": (raw(reason=None), "reason"),
    "reason number": (raw(reason=5), "reason"),
    "reason too long": (raw(reason="x" * 1001), "reason"),
    # 8. extra / unexpected fields
    "extra field": (raw(confidence=0.9), "confidence: Extra inputs are not permitted"),
    "extra target_id": (raw(target_id="brazil"), "target_id: Extra inputs are not permitted"),
    "extra amount": (raw(decision="AID", target="France", amount=50), "amount: Extra inputs are not permitted"),
}


@pytest.mark.parametrize("text, expected_error", list(REJECTED.values()), ids=list(REJECTED))
def test_invalid_decisions_are_rejected(world, text, expected_error):
    assert_rejected(propose(text, world), expected_error)


# --- 9 (rule 9). nothing is silently repaired ---------------------------------------------------------
NOT_REPAIRED = {
    "lower-case decision": raw(decision="sanction"),
    "mixed-case decision": raw(decision="Sanction"),
    "padded decision": raw(decision=" SANCTION "),
    "decision with space": raw(decision="NO ACTION", target=None),
    "decision with hyphen": raw(decision="NO-ACTION", target=None),
    "target as id": raw(target="brazil"),
    "target upper-case": raw(target="BRAZIL"),
    "target padded": raw(target=" Brazil "),
    "country as id": raw(country="india"),
    "country lower-case": raw(country="INDIA"),
    "country padded": raw(country="India "),
    "code fence": "```json\n" + raw() + "\n```",
    "prose before json": "Sure! Here you go: " + raw(),
    "prose after json": raw() + "\nHope that helps!",
}


@pytest.mark.parametrize("text", list(NOT_REPAIRED.values()), ids=list(NOT_REPAIRED))
def test_near_misses_are_rejected_not_repaired(world, text):
    assert_rejected(propose(text, world))


# --- 10. malformed / non-JSON replies -------------------------------------------------------------------
MALFORMED = {
    "empty": ("", "empty response"),
    "whitespace": ("  \n\t ", "empty response"),
    "plain prose": ("I think India should sanction Brazil.", "not valid JSON"),
    "truncated": ('{"country": "India", "decision": "SANC', "not valid JSON"),
    "trailing comma": (raw()[:-1] + ",}", "not valid JSON"),
    "single quotes": ("{'country': 'India'}", "not valid JSON"),
    "json array": ("[]", "must be an object"),
    "json array of decisions": ("[" + raw() + "]", "must be an object"),
    "json string": ('"SANCTION"', "must be an object"),
    "json number": ("42", "must be an object"),
    "json null": ("null", "must be an object"),
    "empty object": ("{}", "Field required"),
}


@pytest.mark.parametrize("text, expected_error", list(MALFORMED.values()), ids=list(MALFORMED))
def test_malformed_replies_are_rejected(world, text, expected_error):
    result = propose(text, world)
    assert_rejected(result, expected_error)
    assert result.raw_response is not None and len(result.raw_response) <= 500


@pytest.mark.parametrize("not_text", [None, 42, {"decision": "SANCTION"}, ["SANCTION"]])
def test_non_string_replies_are_rejected(world, not_text):
    assert_rejected(propose(not_text, world))


# --- 10 (rule). validation errors are distinguishable from Gemini/API errors ---------------------------------
def test_validation_errors_and_gemini_errors_have_different_codes(world):
    invalid = propose("not json", world)
    assert invalid.ok is False and invalid.error_code == "invalid_response" and invalid.raw_response == "not json"

    def gemini_503(system_prompt, user_prompt):
        raise CheckError("Gemini service error (HTTP 503); this is on Google's side, retry shortly.", 3)

    down = IndiaAgent(llm=gemini_503).propose(SITUATION, world)
    assert down.ok is False and down.error_code == "gemini_error" and down.raw_response is None
    assert "503" in down.error
    assert invalid.error_code != down.error_code


# --- the model itself --------------------------------------------------------------------------------------------
def test_model_accepts_exactly_the_five_fields():
    d = CountryDecision.model_validate(GOOD)
    assert d.decision is Decision.SANCTION and d.target_id is None  # target_id is only set against a world
    assert set(d.model_dump()) == set(GOOD)


@pytest.mark.parametrize(
    "overrides",
    [
        {"decision": "sanction"},
        {"decision": "NO_ACTION"},  # GOOD has a target
        {"target": None},  # SANCTION without target
        {"target": ...},  # key missing
        {"extra": 1},
        {"reason": " "},
    ],
)
def test_model_rejects_invalid_data(overrides):
    with pytest.raises(ValidationError):
        CountryDecision.model_validate(body(**overrides))


def test_parse_decision_works_on_world_json_and_derives_target_id(world):
    decision = parse_decision(raw(), world.model_dump(mode="json"), INDIA_PROFILE)
    assert decision.target == "Brazil" and decision.target_id == "brazil"


def test_parse_decision_raises_response_error_for_bad_input(world):
    with pytest.raises(ResponseError, match="Unknown target country"):
        parse_decision(raw(target="Atlantis"), world, INDIA_PROFILE)


def test_target_must_exist_in_the_world_that_was_passed_in(world):
    data = world.model_dump(mode="json")
    data["countries"] = [c for c in data["countries"] if c["id"] != "brazil"]  # Brazil is not in THIS world
    with pytest.raises(ResponseError, match="Unknown target country 'Brazil'"):
        parse_decision(raw(), data, INDIA_PROFILE)


# --- proposal only: nothing is executed -------------------------------------------------------------------------------
def test_validated_decision_does_not_touch_the_world(world):
    before = world.model_dump(mode="json")
    assert propose(raw(), world).ok
    assert world.model_dump(mode="json") == before


# --- CLI: python ai/run_agent.py ---------------------------------------------------------------------------------------
def run_cli(monkeypatch, capsys, reply, *args):
    def make_agent():
        def llm(system_prompt, user_prompt):
            if isinstance(reply, Exception):
                raise reply
            return reply

        return IndiaAgent(llm=llm)

    monkeypatch.setattr(run_agent, "IndiaAgent", make_agent)
    monkeypatch.setattr(sys, "argv", ["run_agent.py", *args])
    code = run_agent.main()
    return code, capsys.readouterr().out


def test_cli_prints_the_validated_decision(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, json.dumps(GOOD), SITUATION)
    assert code == run_agent.EXIT_OK
    assert "nothing was executed" in out
    assert json.loads(out[out.index("{"):]) == GOOD


def test_cli_show_prompt_still_works(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, json.dumps(GOOD), "--show-prompt", SITUATION)
    assert code == 0
    assert "--- SYSTEM PROMPT ---" in out and "--- USER PROMPT ---" in out and SITUATION in out
    assert "=== CURRENT STATE OF INDIA ===" in out


def test_cli_exit_codes_distinguish_the_failure_kind(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, "not json at all", SITUATION)
    assert code == run_agent.EXIT_INVALID_RESPONSE == 2
    assert "INVALID RESPONSE" in out and "not valid JSON" in out and "not json at all" in out

    code, out = run_cli(monkeypatch, capsys, CheckError("Gemini service error (HTTP 503)", 3), SITUATION)
    assert code == run_agent.EXIT_GEMINI_ERROR == 1
    assert "GEMINI ERROR" in out and "503" in out