"""Unit tests for the India agent.

IMPORTANT: every Gemini reply in this file is a MOCK (a fake `llm` callable returning canned text).
These tests prove our prompt building, parsing and validation. They do NOT prove what the real Gemini
decides; for that see test_country_agent_live.py (needs GEMINI_API_KEY).

Run from ai/:  pytest
"""
import json

import pytest

from ai.check_gemini import CheckError
from ai.country_agent import INDIA_PROFILE, IndiaAgent, Decision, build_briefing, parse_decision, ResponseError
from backend.simulation import Simulation, create_initial_world

SITUATION = "Brazil blocked our trade route."


class FakeLLM:
    """Stands in for Gemini: records every call and returns canned text."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def reply(**overrides):
    body = {
        "country": "India",
        "situation": SITUATION,
        "decision": "SANCTION",
        "target": "Brazil",
        "reason": "The blockade threatens India's food supply, so a targeted response protects our interests.",
    }
    body.update(overrides)
    return json.dumps({k: v for k, v in body.items() if v is not ...})


@pytest.fixture
def world():
    return create_initial_world()


# --- 1. initialisation ---------------------------------------------------------------
def test_agent_initializes_with_india_identity():
    agent = IndiaAgent(llm=FakeLLM(""))
    assert agent.profile is INDIA_PROFILE
    assert agent.profile.name == "India" and agent.profile.country_id == "india"
    assert len(agent.profile.goals) >= 3 and agent.profile.personality


def test_default_agent_needs_no_api_key_until_it_proposes(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    IndiaAgent()  # must not raise


def test_system_prompt_defines_role_options_and_output():
    prompt = IndiaAgent(llm=FakeLLM("")).build_system_prompt()
    assert "India" in prompt and "PROPOSE" in prompt and "Nothing you write is executed" in prompt
    for option in ("SANCTION", "ALLIANCE", "AID", "NO_ACTION"):
        assert option in prompt
    assert "pragmatic" in prompt.lower() and "diplomatic" in prompt.lower()
    assert "JSON" in prompt


# --- 2. country/world information --------------------------------------------------------
def test_briefing_uses_real_simulation_state():
    sim = Simulation()
    sim.alliance("india", "united-states")  # the starting dataset has no alliances: form one through the backend
    world = sim.world
    text = build_briefing(world, INDIA_PROFILE)
    india = next(c for c in world.countries if c.id == "india")
    assert f"GDP: {india.gdp:g}" in text and f"Stability: {india.stability}/100" in text
    assert "tech 60" in text and "India-United States Alliance" in text
    assert "(id:" not in text  # countries are listed by name only: the agent must answer with names
    assert "Brazil, China, France, Russia, United States" in text  # trade partners
    assert "Brazil -> India: food, volume 25" in text  # a route affecting India
    for other in world.countries:
        if other.id != "india":
            assert other.name in text
    assert "relationship with India -14" in text  # China
    assert "allied: yes (India-United States Alliance)" in text


def test_briefing_accepts_world_json_dict(world):
    assert build_briefing(world.model_dump(mode="json"), INDIA_PROFILE) == build_briefing(world, INDIA_PROFILE)


def test_briefing_reflects_sanctions_and_cut_trade():
    sim = Simulation()
    sim.sanction("brazil", "india")  # Brazil sanctions India: route cut
    sim.sanction("india", "china")
    text = build_briefing(sim.world, INDIA_PROFILE)
    assert "Sanctioned by: Brazil" in text
    assert "CUT OFF" in text
    assert "Brazil sanctions India" in text and "India sanctions China" in text
    assert "Active trade partners: France, Russia, United States" in text
    events_part = text.split("=== RECENT DIPLOMACY EVENTS ===")[1]
    assert "Brazil imposed sanctions on India" in events_part and "India imposed sanctions on China" in events_part


def test_briefing_for_unknown_country_fails(world):
    from dataclasses import replace

    with pytest.raises(ValueError):
        build_briefing(world, replace(INDIA_PROFILE, country_id="atlantis"))


# --- 3. situation input ----------------------------------------------------------------------
def test_situation_is_included_in_user_prompt(world):
    prompt = IndiaAgent(llm=FakeLLM("")).build_user_prompt(SITUATION, world)
    assert SITUATION in prompt and "=== SITUATION ===" in prompt
    assert "=== CURRENT STATE OF INDIA" in prompt


@pytest.mark.parametrize("bad", ["", "   ", None, 5, "x" * 1001])
def test_bad_situation_is_rejected(world, bad):
    llm = FakeLLM(reply())
    with pytest.raises(ValueError):
        IndiaAgent(llm=llm).propose(bad, world)
    assert llm.calls == []  # nothing was sent to Gemini


# --- 4. the LLM (Gemini) is called correctly ---------------------------------------------------
def test_propose_calls_llm_once_with_system_and_user_prompts(world):
    llm = FakeLLM(reply())
    agent = IndiaAgent(llm=llm)
    agent.propose(SITUATION, world)
    assert len(llm.calls) == 1
    system_prompt, user_prompt = llm.calls[0]
    assert system_prompt == agent.build_system_prompt()
    assert user_prompt == agent.build_user_prompt(SITUATION, world)
    assert "Brazil -> India: food" in user_prompt  # the affected route reaches Gemini


# --- 5. valid structured response is accepted (MOCKED) ---------------------------------------------
def test_valid_response_is_accepted(world):
    result = IndiaAgent(llm=FakeLLM(reply())).propose(SITUATION, world)
    assert result.ok and result.error is None and result.error_code is None
    d = result.decision
    assert d.country == "India" and d.situation == SITUATION
    assert d.decision is Decision.SANCTION
    assert d.target == "Brazil" and d.target_id == "brazil"
    assert d.reason
    assert set(d.model_dump()) == {"country", "situation", "decision", "target", "reason"}  # exactly five fields


@pytest.mark.parametrize("decision", ["SANCTION", "ALLIANCE", "AID", "NO_ACTION"])
def test_every_allowed_decision_is_accepted(world, decision):
    target = None if decision == "NO_ACTION" else "France"
    result = IndiaAgent(llm=FakeLLM(reply(decision=decision, target=target))).propose(SITUATION, world)
    assert result.ok and result.decision.decision.value == decision


# --- 6. invalid / malformed output (the full strict matrix lives in test_country_decision.py) ---------------
def test_non_string_reply_is_rejected(world):
    for raw in (None, 42, {"decision": "SANCTION"}):
        result = IndiaAgent(llm=FakeLLM(raw)).propose(SITUATION, world)
        assert not result.ok and result.error_code == "invalid_response"


def test_parse_decision_raises_response_error(world):
    with pytest.raises(ResponseError, match="not valid JSON"):
        parse_decision("nope", world, INDIA_PROFILE)


def test_gemini_failure_is_reported_not_raised(world):
    result = IndiaAgent(llm=FakeLLM(CheckError("Gemini rate limit exceeded", 3))).propose(SITUATION, world)
    assert not result.ok and result.error_code == "gemini_error" and "rate limit" in result.error

    result = IndiaAgent(llm=FakeLLM(RuntimeError("secret-token-123"))).propose(SITUATION, world)
    assert not result.ok and result.error_code == "gemini_error"
    assert "RuntimeError" in result.error and "secret-token-123" not in result.error


# --- 7. the agent only proposes ----------------------------------------------------------------------
def test_proposing_never_changes_the_world():
    sim = Simulation()
    before = sim.world.model_dump(mode="json")
    result = IndiaAgent(llm=FakeLLM(reply())).propose(SITUATION, sim.world)
    assert result.ok
    assert sim.world.model_dump(mode="json") == before  # no action executed, no event, no turn
    assert sim.world.events == [] and sim.world.turn == 0


# --- 8. example scenario (MOCKED reply) -----------------------------------------------------------------
def test_example_scenario_with_mocked_gemini(world, capsys):
    """India + 'Brazil blocked our trade route.' The decision here comes from the mock, not from Gemini."""
    result = IndiaAgent(llm=FakeLLM(reply())).propose(SITUATION, world)
    assert result.ok
    print("MOCKED example output:", json.dumps(result.decision.model_dump(mode="json"), indent=2))
    out = capsys.readouterr().out
    assert '"decision": "SANCTION"' in out