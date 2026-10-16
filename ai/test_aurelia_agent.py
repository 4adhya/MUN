"""Unit tests for the Aurelia agent.

IMPORTANT: every Gemini reply in this file is a MOCK (a fake `llm` callable returning canned text).
These tests prove our prompt building, parsing and validation. They do NOT prove what the real Gemini
decides; for that see test_aurelia_live.py (needs GEMINI_API_KEY).

Run from ai/:  pytest
"""
import json

import pytest

from check_gemini import CheckError
from country_agent import AURELIA_PROFILE, AureliaAgent, Decision, build_briefing, parse_decision, ResponseError
from backend.simulation import Simulation, create_initial_world

SITUATION = "Caldoria blocked our trade route."


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
        "country": "Aurelia",
        "situation": SITUATION,
        "decision": "SANCTION",
        "target": "Caldoria",
        "reason": "The blockade threatens Aurelia's oil supply, so a targeted response protects our interests.",
    }
    body.update(overrides)
    return json.dumps({k: v for k, v in body.items() if v is not ...})


@pytest.fixture
def world():
    return create_initial_world()


# --- 1. initialisation ---------------------------------------------------------------
def test_agent_initializes_with_aurelia_identity():
    agent = AureliaAgent(llm=FakeLLM(""))
    assert agent.profile is AURELIA_PROFILE
    assert agent.profile.name == "Aurelia" and agent.profile.country_id == "aurelia"
    assert len(agent.profile.goals) >= 3 and agent.profile.personality


def test_default_agent_needs_no_api_key_until_it_proposes(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    AureliaAgent()  # must not raise


def test_system_prompt_defines_role_options_and_output():
    prompt = AureliaAgent(llm=FakeLLM("")).build_system_prompt()
    assert "Aurelia" in prompt and "PROPOSE" in prompt and "Nothing you write is executed" in prompt
    for option in ("SANCTION", "ALLIANCE", "AID", "NO_ACTION"):
        assert option in prompt
    assert "pragmatic" in prompt.lower() and "diplomacy" in prompt.lower()
    assert "JSON" in prompt


# --- 2. country/world information --------------------------------------------------------
def test_briefing_uses_real_simulation_state(world):
    text = build_briefing(world, AURELIA_PROFILE)
    aurelia = next(c for c in world.countries if c.id == "aurelia")
    assert f"GDP: {aurelia.gdp:g}" in text and f"Stability: {aurelia.stability}/100" in text
    assert "tech 85" in text and "Northern Accord" in text
    assert "(id:" not in text  # countries are listed by name only: the agent must answer with names
    assert "Brevania, Caldoria, Istoria" in text  # trade partners
    assert "Caldoria -> Aurelia: oil, volume 50" in text  # a route affecting Aurelia
    for other in world.countries:
        if other.id != "aurelia":
            assert other.name in text
    assert "relationship with Aurelia -45" in text  # Garvonia
    assert "allied: yes (Northern Accord)" in text


def test_briefing_accepts_world_json_dict(world):
    assert build_briefing(world.model_dump(mode="json"), AURELIA_PROFILE) == build_briefing(world, AURELIA_PROFILE)


def test_briefing_reflects_sanctions_and_cut_trade():
    sim = Simulation()
    sim.sanction("caldoria", "aurelia")  # Caldoria sanctions Aurelia: route cut
    sim.sanction("aurelia", "garvonia")
    text = build_briefing(sim.world, AURELIA_PROFILE)
    assert "Sanctioned by: Caldoria" in text
    assert "CUT OFF" in text
    assert "Caldoria sanctions Aurelia" in text and "Aurelia sanctions Garvonia" in text
    assert "Active trade partners: Brevania, Istoria" in text
    events_part = text.split("=== RECENT DIPLOMACY EVENTS ===")[1]
    assert "Caldoria imposed sanctions on Aurelia" in events_part and "Aurelia imposed sanctions on Garvonia" in events_part


def test_briefing_for_unknown_country_fails(world):
    from dataclasses import replace

    with pytest.raises(ValueError):
        build_briefing(world, replace(AURELIA_PROFILE, country_id="atlantis"))


# --- 3. situation input ----------------------------------------------------------------------
def test_situation_is_included_in_user_prompt(world):
    prompt = AureliaAgent(llm=FakeLLM("")).build_user_prompt(SITUATION, world)
    assert SITUATION in prompt and "=== SITUATION ===" in prompt
    assert "=== CURRENT STATE OF AURELIA" in prompt


@pytest.mark.parametrize("bad", ["", "   ", None, 5, "x" * 1001])
def test_bad_situation_is_rejected(world, bad):
    llm = FakeLLM(reply())
    with pytest.raises(ValueError):
        AureliaAgent(llm=llm).propose(bad, world)
    assert llm.calls == []  # nothing was sent to Gemini


# --- 4. the LLM (Gemini) is called correctly ---------------------------------------------------
def test_propose_calls_llm_once_with_system_and_user_prompts(world):
    llm = FakeLLM(reply())
    agent = AureliaAgent(llm=llm)
    agent.propose(SITUATION, world)
    assert len(llm.calls) == 1
    system_prompt, user_prompt = llm.calls[0]
    assert system_prompt == agent.build_system_prompt()
    assert user_prompt == agent.build_user_prompt(SITUATION, world)
    assert "Caldoria -> Aurelia: oil" in user_prompt  # the affected route reaches Gemini


# --- 5. valid structured response is accepted (MOCKED) ---------------------------------------------
def test_valid_response_is_accepted(world):
    result = AureliaAgent(llm=FakeLLM(reply())).propose(SITUATION, world)
    assert result.ok and result.error is None and result.error_code is None
    d = result.decision
    assert d.country == "Aurelia" and d.situation == SITUATION
    assert d.decision is Decision.SANCTION
    assert d.target == "Caldoria" and d.target_id == "caldoria"
    assert d.reason
    assert set(d.model_dump()) == {"country", "situation", "decision", "target", "reason"}  # exactly five fields


@pytest.mark.parametrize("decision", ["SANCTION", "ALLIANCE", "AID", "NO_ACTION"])
def test_every_allowed_decision_is_accepted(world, decision):
    target = None if decision == "NO_ACTION" else "Brevania"
    result = AureliaAgent(llm=FakeLLM(reply(decision=decision, target=target))).propose(SITUATION, world)
    assert result.ok and result.decision.decision.value == decision


# --- 6. invalid / malformed output (the full strict matrix lives in test_country_decision.py) ---------------
def test_non_string_reply_is_rejected(world):
    for raw in (None, 42, {"decision": "SANCTION"}):
        result = AureliaAgent(llm=FakeLLM(raw)).propose(SITUATION, world)
        assert not result.ok and result.error_code == "invalid_response"


def test_parse_decision_raises_response_error(world):
    with pytest.raises(ResponseError, match="not valid JSON"):
        parse_decision("nope", world, AURELIA_PROFILE)


def test_gemini_failure_is_reported_not_raised(world):
    result = AureliaAgent(llm=FakeLLM(CheckError("Gemini rate limit exceeded", 3))).propose(SITUATION, world)
    assert not result.ok and result.error_code == "gemini_error" and "rate limit" in result.error

    result = AureliaAgent(llm=FakeLLM(RuntimeError("secret-token-123"))).propose(SITUATION, world)
    assert not result.ok and result.error_code == "gemini_error"
    assert "RuntimeError" in result.error and "secret-token-123" not in result.error


# --- 7. the agent only proposes ----------------------------------------------------------------------
def test_proposing_never_changes_the_world():
    sim = Simulation()
    before = sim.world.model_dump(mode="json")
    result = AureliaAgent(llm=FakeLLM(reply())).propose(SITUATION, sim.world)
    assert result.ok
    assert sim.world.model_dump(mode="json") == before  # no action executed, no event, no turn
    assert sim.world.events == [] and sim.world.turn == 0


# --- 8. example scenario (MOCKED reply) -----------------------------------------------------------------
def test_example_scenario_with_mocked_gemini(world, capsys):
    """Aurelia + 'Caldoria blocked our trade route.' The decision here comes from the mock, not from Gemini."""
    result = AureliaAgent(llm=FakeLLM(reply())).propose(SITUATION, world)
    assert result.ok
    print("MOCKED example output:", json.dumps(result.decision.model_dump(mode="json"), indent=2))
    out = capsys.readouterr().out
    assert '"decision": "SANCTION"' in out