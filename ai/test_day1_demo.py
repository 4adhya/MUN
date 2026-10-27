"""Day 1 acceptance tests: one complete India turn, end to end. Every Gemini reply is a MOCK (no live API).

    world -> India agent -> (mock) Gemini -> CountryDecision -> validation
          -> simulation action if appropriate -> updated world / event   (an AI failure = no decision)

Run from the repo root:  python -m pytest ai/test_day1_demo.py -q
"""
import json
import sys

import pytest

from ai import run_turn
from backend.simulation import Simulation
from ai.check_gemini import CheckError
from ai.country_agent import IndiaAgent
from ai.country_turn import AGENT_FACTORIES, run_country_turn

SITUATION = "Brazil blocked India's trade route."


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def reply(decision, target, **overrides):
    body = {"country": "India", "situation": "Trade route blocked.", "decision": decision, "target": target,
            "reason": "Protect India's interests.", **overrides}
    return json.dumps(body)


@pytest.fixture
def sim():
    return Simulation()


def dump(sim):
    return sim.world.model_dump(mode="json")


def allied_simulation():
    """A starting world in which India and France are already allied (the starting dataset has no alliances)."""
    sim = Simulation()
    sim.alliance("india", "france")
    return sim


def turn(sim, llm_reply, situation=SITUATION):
    llm = FakeLLM(llm_reply)
    return run_country_turn("india", situation, simulation=sim, llm=llm), llm


# --- Gemini succeeds -> AI decision reaches the simulation -----------------------------------------------------------
def test_ai_sanction_changes_the_world_and_records_an_event(sim):
    before = sim.get_country("brazil").model_copy(deep=True)
    result, _ = turn(sim, reply("SANCTION", "Brazil"))
    assert result.source == "ai" and result.action.status == "executed" and result.world_changed
    assert "india" in sim.get_country("brazil").sanctions
    assert sim.get_country("brazil").gdp < before.gdp
    assert len(sim.world.events) == 1 and "India" in sim.world.events[0].message


def test_ai_alliance_changes_the_world(sim):
    result, _ = turn(sim, reply("ALLIANCE", "France"))
    assert result.action.status == "executed" and result.world_changed
    assert "France-India Alliance" in sim.get_country("india").alliances
    assert "France-India Alliance" in sim.get_country("france").alliances
    assert len(sim.world.events) == 1


def test_ai_aid_uses_the_default_amount(sim):
    gdp_before = sim.get_country("france").gdp
    result, _ = turn(sim, reply("AID", "France"))
    assert result.action.status == "executed" and result.action.amount == 10.0
    assert sim.get_country("france").gdp > gdp_before and len(sim.world.events) == 1


def test_ai_no_action_does_not_mutate_the_world(sim):
    before = dump(sim)
    result, _ = turn(sim, reply("NO_ACTION", None))
    assert result.source == "ai" and result.action.status == "no_action" and result.ok and not result.world_changed
    assert dump(sim) == before and sim.world.events == []


# --- Gemini fails -> no decision (never a NO_ACTION), world untouched ---------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [CheckError("Gemini service error (HTTP 503)", 3), "{not json", reply("ATTACK", "Brazil"), reply("SANCTION", "Atlantis")],
    ids=["unavailable", "malformed", "invalid_decision", "unknown_target"],
)
def test_ai_failure_is_not_a_no_action_and_never_touches_the_world(sim, bad):
    before = dump(sim)
    result, _ = turn(sim, bad)
    assert result.source == "failed" and result.ai_failed
    assert result.decision is None and result.action is None and not result.ok
    assert dump(sim) == before and sim.world.events == []


# --- the backend says no -> clear failure, never a fake success -------------------------------------------------------------
def test_backend_rejection_is_a_clear_failure():
    sim = allied_simulation()
    before = dump(sim)
    result, _ = turn(sim, reply("ALLIANCE", "France"))  # already allied
    assert result.source == "ai" and result.action.status == "rejected" and not result.ok
    assert dump(sim) == before and len(sim.world.events) == 1  # only the setup alliance event


# --- the situation is context, not an instruction; all four decisions stay open ------------------------------------------------
def test_the_situation_is_context_and_every_decision_stays_possible(sim):
    _, llm = turn(sim, reply("NO_ACTION", None))
    system_prompt, user_prompt = llm.calls[0]
    assert SITUATION in user_prompt and SITUATION not in system_prompt
    for option in ("SANCTION", "ALLIANCE", "AID", "NO_ACTION"):
        assert option in system_prompt
    assert "must sanction" not in (system_prompt + user_prompt).lower()


@pytest.mark.parametrize("decision,target", [("SANCTION", "Brazil"), ("ALLIANCE", "France"), ("AID", "France"), ("NO_ACTION", None)])
def test_the_same_situation_can_lead_to_each_decision(decision, target):
    result, _ = turn(Simulation(), reply(decision, target))
    assert result.decision.decision.value == decision and result.action.ok


# --- India is briefed from the real world state ------------------------------------------------------------------------------
def test_the_briefing_comes_from_the_live_world(sim):
    sim.sanction("brazil", "india")
    _, llm = turn(sim, reply("NO_ACTION", None))
    prompt = llm.calls[0][1]
    me = sim.get_country("india")
    for expected in (f"GDP: {me.gdp:g}", f"Stability: {me.stability}/100", "Alliances:", "Sanctioned by: Brazil",
                     "Active trade partners:", "Trade routes involving India:", "CUT OFF", "relationship with India",
                     "Brazil imposed sanctions on India"):
        assert expected in prompt, expected


def test_the_briefing_follows_the_world_when_it_changes(sim):
    _, first = turn(sim, reply("NO_ACTION", None))
    sim.sanction("india", "china")
    _, second = turn(sim, reply("NO_ACTION", None))
    assert first.calls[0][1] != second.calls[0][1] and "India sanctions China" in second.calls[0][1]


# --- reuse for Day 2, without adding agents now ---------------------------------------------------------------------------------------
def test_only_india_is_configured_and_the_turn_function_takes_a_country_id(sim):
    assert list(AGENT_FACTORIES) == ["india"]
    with pytest.raises(ValueError):
        run_country_turn("brazil", SITUATION, simulation=sim, llm=FakeLLM(reply("NO_ACTION", None)))


def test_one_turn_asks_gemini_once(sim):
    _, llm = turn(sim, reply("NO_ACTION", None))
    assert len(llm.calls) == 1


# --- the demo CLI ---------------------------------------------------------------------------------------------------------------------------
def run_cli(monkeypatch, capsys, llm_reply, *args):
    monkeypatch.setattr(run_turn, "create_agent", lambda country_id: IndiaAgent(llm=FakeLLM(llm_reply)))
    monkeypatch.setattr(sys, "argv", ["run_turn.py", *args])
    code = run_turn.main()
    return code, capsys.readouterr().out


def test_cli_ai_sanction_is_labelled_ai_and_shows_the_world_result(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, reply("SANCTION", "Brazil"))
    assert code == 0 and "INDIA AI TURN" in out and "AI DECISION" in out and "AI REQUEST FAILED" not in out
    for section in ("Country:", "Situation:", "World context:", "Decision:", "Target:", "Reason:", "Execution:",
                    "SANCTION APPLIED", "World Result", "Event:"):
        assert section in out, section
    assert SITUATION in out and "GDP:" in out and "Stability:" in out and "Trade partners:" in out


def test_cli_ai_failure_is_labelled_a_failure_and_world_unchanged(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, CheckError("Gemini service error (HTTP 503)", 3))
    assert code == run_turn.EXIT_GEMINI_ERROR
    assert "AI REQUEST FAILED" in out and "AI DECISION" not in out and "NO_ACTION" not in out and "FALLBACK" not in out
    assert "UNCHANGED" in out and "APPLIED" not in out


def test_cli_rejection_never_claims_success(monkeypatch, capsys):
    monkeypatch.setattr(run_turn, "Simulation", allied_simulation)  # India and France are already allied
    code, out = run_cli(monkeypatch, capsys, reply("ALLIANCE", "France"))
    assert code == run_turn.EXIT_REJECTED and "REJECTED" in out and "did NOT happen" in out
    assert "APPLIED" not in out and "ACCEPTED" not in out


def test_cli_never_prints_the_api_key(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-super-secret-test-key")
    _, out = run_cli(monkeypatch, capsys, RuntimeError("boom"))
    assert "AIza-super-secret-test-key" not in out