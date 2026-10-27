"""Phase 5 tests: one full AI turn  world -> Gemini (MOCKED) -> validation -> backend action -> result.

Every Gemini reply here is a MOCK. Nothing calls the live API. Each test uses a fresh `Simulation()`.

Run from the repo root:  pytest ai/test_country_turn.py
"""
import json
import sys

import pytest

from ai import run_turn
from backend.simulation import Simulation
from ai.check_gemini import CheckError
from ai.country_agent import IndiaAgent
from ai.country_turn import AGENT_FACTORIES, NO_INCIDENT_SITUATION, create_agent, default_situation, run_country_turn

SITUATION = "Brazil blocked India's trade."


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def reply(decision="SANCTION", target="Brazil", **overrides):
    body = {
        "country": "India",
        "situation": "Brazil blocked our trade route.",
        "decision": decision,
        "target": target,
        "reason": "Protects India's trade interests.",
        **overrides,
    }
    return json.dumps(body)


@pytest.fixture
def sim():
    return Simulation()


def turn(sim, llm_reply, situation=SITUATION):
    llm = FakeLLM(llm_reply)
    return run_country_turn("india", situation, simulation=sim, llm=llm), llm


def dump(sim):
    return sim.world.model_dump(mode="json")


def allied_simulation():
    """A starting world in which India and France are already allied (the starting dataset has no alliances)."""
    sim = Simulation()
    sim.alliance("india", "france")
    return sim


# --- successful AI decisions reach the backend --------------------------------------------------------------------
def test_ai_sanction_is_executed_through_the_backend(sim):
    result, llm = turn(sim, reply("SANCTION", "Brazil"))
    assert result.source == "ai" and not result.ai_failed
    assert result.error_code is None and result.error is None
    assert result.decision.decision.value == "SANCTION" and result.decision.target == "Brazil"
    assert result.ok and result.world_changed and result.action.status == "executed"
    assert "india" in sim.get_country("brazil").sanctions
    assert len(sim.world.events) == 1 and result.action.event["type"] == "sanction"
    assert len(llm.calls) == 1  # Gemini asked exactly once


def test_ai_alliance_is_executed(sim):
    result, _ = turn(sim, reply("ALLIANCE", "China"))
    assert result.action.status == "executed" and result.action.action == "ALLIANCE"
    assert "China-India Alliance" in sim.get_country("china").alliances
    assert sim.world.events[0].type == "alliance"


def test_ai_aid_is_executed_with_the_default_amount(sim):
    before = sim.get_country("france").gdp
    result, _ = turn(sim, reply("AID", "France"))
    assert result.action.status == "executed" and result.action.amount == 10.0
    assert sim.get_country("france").gdp == pytest.approx(before + 4.0)
    assert result.action.event["effects"]["amount"] == 10.0


def test_ai_no_action_does_not_mutate_the_world(sim):
    before = dump(sim)
    result, _ = turn(sim, reply("NO_ACTION", None, reason="Nothing needs doing."))
    assert result.source == "ai" and not result.ai_failed  # a genuine AI choice, not a failure
    assert result.action.status == "no_action" and result.ok and not result.world_changed
    assert dump(sim) == before and sim.world.events == []


# --- AI failure: no decision, never a NO_ACTION ------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_reply, code",
    [
        (CheckError("Gemini service error (HTTP 503); this is on Google's side, retry shortly.", 3), "gemini_error"),
        (CheckError("Gemini request timed out", 3), "gemini_error"),
        (RuntimeError("socket exploded"), "gemini_error"),
        ("", "invalid_response"),
        ("not json", "invalid_response"),
        (reply("ATTACK", "Brazil"), "invalid_response"),
        (reply("SANCTION", "Atlantis"), "invalid_response"),
        (reply("SANCTION", None), "invalid_response"),
    ],
    ids=["503", "timeout", "unexpected", "empty", "malformed", "bad_decision", "bad_target", "missing_target"],
)
def test_gemini_failure_or_invalid_reply_is_a_failure_not_a_no_action(sim, bad_reply, code):
    before = dump(sim)
    result, _ = turn(sim, bad_reply)  # must not raise

    assert result.source == "failed" and result.ai_failed
    assert result.error_code == code and result.error and result.failure_reason
    assert result.decision is None and result.action is None  # no NO_ACTION, nothing attempted
    assert not result.ok and not result.world_changed
    assert dump(sim) == before and sim.world.events == []


def test_invalid_reply_is_kept_for_debugging_but_gemini_errors_have_none(sim):
    bad, _ = turn(sim, "not json")
    down, _ = turn(sim, CheckError("Gemini service error (HTTP 503)", 3))
    assert bad.raw_response == "not json" and down.raw_response is None


# --- backend rejection ---------------------------------------------------------------------------------------------------
def test_valid_ai_decision_rejected_by_the_backend_is_not_reported_as_success():
    sim = allied_simulation()
    before = dump(sim)
    result, _ = turn(sim, reply("ALLIANCE", "France"))  # valid decision, but already allied

    assert result.source == "ai" and not result.ai_failed  # the AI was fine
    assert result.action.status == "rejected" and result.action.http_status == 409
    assert not result.ok and not result.world_changed
    assert result.action.event is None
    assert dump(sim) == before and len(sim.world.events) == 1  # only the setup alliance event


def test_repeating_a_turn_keeps_the_duplicate_protection(sim):
    first, _ = turn(sim, reply("SANCTION", "Brazil"))
    after_first = dump(sim)
    second, _ = turn(sim, reply("SANCTION", "Brazil"))

    assert first.action.status == "executed"
    assert second.action.status == "rejected" and second.action.http_status == 409
    assert dump(sim) == after_first and len(sim.world.events) == 1


# --- real world state reaches the agent ---------------------------------------------------------------------------------------
def test_the_agent_prompt_is_built_from_the_current_simulation_state(sim):
    sim.sanction("brazil", "india")  # change the real world first
    result, llm = turn(sim, reply("NO_ACTION", None), situation="Review please.")
    prompt = llm.calls[0][1]
    assert "Sanctioned by: Brazil" in prompt  # current sanctions
    assert f"GDP: {sim.get_country('india').gdp:g}" in prompt and "Stability:" in prompt
    assert "CUT OFF" in prompt  # the trade route the sanction cut
    assert "Brazil imposed sanctions on India" in prompt  # recent events
    assert "Review please." in prompt and result.situation == "Review please."


def test_default_situation_comes_from_the_latest_event_aimed_at_the_country(sim):
    assert default_situation(sim.world, "india") == NO_INCIDENT_SITUATION
    sim.sanction("brazil", "india")
    sim.sanction("india", "china")  # aimed at someone else: ignored
    text = default_situation(sim.world, "india")
    assert "Brazil imposed sanctions on India" in text

    result = run_country_turn("india", simulation=sim, llm=FakeLLM(reply("NO_ACTION", None)))
    assert result.situation == text


# --- one call = one turn; country-agnostic plumbing ----------------------------------------------------------------------------
def test_one_call_asks_gemini_once_and_never_loops(sim):
    llm = FakeLLM(reply("SANCTION", "Brazil"))
    run_country_turn("india", SITUATION, simulation=sim, llm=llm)
    assert len(llm.calls) == 1 and sim.world.turn == 0 and len(sim.world.events) == 1


def test_country_id_is_a_parameter_and_is_validated(sim):
    assert isinstance(create_agent("india"), IndiaAgent) and set(AGENT_FACTORIES) == {"india"}
    with pytest.raises(ValueError, match="No agent is configured"):
        run_country_turn("brazil", SITUATION, simulation=sim, llm=FakeLLM(""))  # exists, but no agent yet
    with pytest.raises(ValueError, match="Unknown country"):
        run_country_turn("atlantis", SITUATION, simulation=sim, llm=FakeLLM(""))
    assert run_country_turn("  INDIA ", SITUATION, simulation=sim, llm=FakeLLM(reply("NO_ACTION", None))).ok


@pytest.mark.parametrize("alias", ["India", "IND", "IN", " india "])
def test_country_is_resolved_through_the_registry_like_the_api(sim, alias):
    result = run_country_turn(alias, SITUATION, simulation=sim, llm=FakeLLM(reply("NO_ACTION", None)))
    assert result.country_id == "india" and result.ok


def test_agent_for_the_wrong_country_is_refused(sim):
    with pytest.raises(ValueError, match="not 'brazil'"):
        run_country_turn("brazil", SITUATION, simulation=sim, agent=IndiaAgent(llm=FakeLLM("")))


def test_bad_situation_is_a_caller_error_not_an_ai_failure(sim):
    with pytest.raises(ValueError):
        run_country_turn("india", "   ", simulation=sim, llm=FakeLLM(reply()))
    assert sim.world.events == []


def test_default_agent_is_only_built_without_needing_a_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    create_agent("india")  # building the agent must not need a key


# --- the shared backend instance is the default -----------------------------------------------------------------------------------
def test_default_simulation_is_the_shared_backend_instance():
    from backend.simulation import simulation as shared

    shared.reset()
    try:
        result = run_country_turn("india", SITUATION, llm=FakeLLM(reply("SANCTION", "Brazil")))
        assert result.action.status == "executed" and len(shared.world.events) == 1
    finally:
        shared.reset()


# --- CLI ----------------------------------------------------------------------------------------------------------------------------
def run_cli(monkeypatch, capsys, llm_reply, *args):
    monkeypatch.setattr(run_turn, "create_agent", lambda country_id: IndiaAgent(llm=FakeLLM(llm_reply)))
    monkeypatch.setattr(sys, "argv", ["run_turn.py", *args])
    code = run_turn.main()
    return code, capsys.readouterr().out


def test_cli_shows_a_successful_flow(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, reply("SANCTION", "Brazil"), SITUATION)
    assert code == run_turn.EXIT_OK
    assert "AI DECISION" in out and "decision: SANCTION -> Brazil" in out
    assert "SANCTION ACCEPTED by the backend" in out and "world state updated" in out
    assert "Events recorded this run: 1" in out and "FALLBACK" not in out


def test_cli_shows_an_ai_failure_as_a_failure_not_a_decision(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, CheckError("Gemini service error (HTTP 503)", 3), SITUATION)
    assert code == run_turn.EXIT_GEMINI_ERROR
    assert "AI REQUEST FAILED" in out and "No decision was made" in out and "NOT EXECUTED" in out
    assert "AI DECISION" not in out and "NO_ACTION" not in out and "NO ACTION" not in out and "FALLBACK" not in out
    assert "world unchanged" in out and "Events recorded this run: 0" in out and "ACCEPTED" not in out


def test_cli_invalid_reply_and_rejection_exit_codes(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, "not json", SITUATION)
    assert code == run_turn.EXIT_INVALID_RESPONSE and "AI REQUEST FAILED" in out and "not json" in out
    assert "FALLBACK" not in out and "NO_ACTION" not in out

    monkeypatch.setattr(run_turn, "Simulation", allied_simulation)  # India and France are already allied
    code, out = run_cli(monkeypatch, capsys, reply("ALLIANCE", "France"), SITUATION)
    assert code == run_turn.EXIT_REJECTED
    assert "REJECTED by the backend (HTTP 409)" in out and "did NOT happen" in out and "ACCEPTED" not in out


def test_cli_no_action_from_the_ai(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, reply("NO_ACTION", None), SITUATION)
    assert code == run_turn.EXIT_OK and "AI DECISION" in out and "NO ACTION" in out and "FALLBACK" not in out


def test_cli_unknown_country_exits_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run_turn.py", "--country", "atlantis", SITUATION])
    with pytest.raises(SystemExit) as exc:
        run_turn.main()
    assert exc.value.code == 2