"""Phase 5 tests: the bridge turns a validated decision into the backend's own actions.

Everything runs against a fresh in-process `Simulation()`; the real backend rules decide every outcome.
No Gemini is involved here (decisions are built by hand).

Run from the repo root:  pytest ai/test_simulation_bridge.py
"""
from types import SimpleNamespace

import pytest

from backend.rules import MAX_AID_AMOUNT, MAX_AID_GDP_SHARE, MIN_AID_AMOUNT
from backend.simulation import Simulation
from ai.country_agent import CountryDecision, Decision
from ai.simulation_bridge import DEFAULT_AID_AMOUNT, BridgeResult, UnsupportedDecisionError, execute_decision


@pytest.fixture
def sim():
    return Simulation()


def decision(kind, target=None, country="India", target_id=None):
    d = CountryDecision(
        country=country,
        situation="Brazil blocked India's trade route.",
        decision=kind,
        target=target,
        reason="Test decision.",
    )
    if target_id:
        d._target_id = target_id
    return d


def country(sim, cid):
    return sim.get_country(cid)


def world_dump(sim):
    return sim.world.model_dump(mode="json")


# --- 1. SANCTION --------------------------------------------------------------------------------------
def test_sanction_runs_the_backend_action_and_changes_the_world(sim):
    cal_before = country(sim, "brazil").model_copy(deep=True)
    result = execute_decision(decision("SANCTION", "Brazil"), "india", sim)

    assert result.status == "executed" and result.ok and result.executed
    assert (result.action, result.actor, result.target) == ("SANCTION", "india", "brazil")
    cal = country(sim, "brazil")
    assert "india" in cal.sanctions
    assert cal.gdp < cal_before.gdp and cal.stability < cal_before.stability
    assert cal.relationships["india"] < cal_before.relationships["india"]
    route = next(r for r in sim.world.trade_routes if r.exporter == "brazil" and r.importer == "india")
    assert route.active is False  # trade cut by the backend's own rules
    assert len(sim.world.events) == 1 and sim.world.events[0].type == "sanction"
    assert result.event["id"] == 1 and result.event["type"] == "sanction" and result.event["actor"] == "india"
    assert result.message == sim.world.events[0].message
    assert result.target_after["id"] == "brazil" and result.target_after["sanctions"] == ["india"]


# --- 2. ALLIANCE --------------------------------------------------------------------------------------
def test_alliance_runs_the_backend_action(sim):
    before_a, before_c = country(sim, "india").model_copy(deep=True), country(sim, "brazil").model_copy(deep=True)
    result = execute_decision(decision("ALLIANCE", "Brazil"), "india", sim)

    assert result.status == "executed" and result.action == "ALLIANCE"
    a, c = country(sim, "india"), country(sim, "brazil")
    assert "Brazil-India Alliance" in a.alliances and "Brazil-India Alliance" in c.alliances
    assert a.relationships["brazil"] > before_a.relationships["brazil"]
    assert a.stability > before_a.stability and c.stability > before_c.stability
    assert len(sim.world.events) == 1 and sim.world.events[0].type == "alliance"
    assert result.event["type"] == "alliance"


# --- 3. AID --------------------------------------------------------------------------------------------
def test_aid_uses_the_deterministic_default_amount(sim):
    a0, i0 = country(sim, "india").model_copy(deep=True), country(sim, "france").model_copy(deep=True)
    result = execute_decision(decision("AID", "France"), "india", sim)

    assert result.status == "executed" and result.amount == DEFAULT_AID_AMOUNT == 10.0
    a, i = country(sim, "india"), country(sim, "france")
    assert a.gdp == pytest.approx(a0.gdp - 2.0)  # backend: actor pays 20% of the amount
    assert i.gdp == pytest.approx(i0.gdp + 4.0)  # backend: target gains 40% of the amount
    assert i.stability > i0.stability and i.relationships["india"] > i0.relationships["india"]
    assert sim.world.events[0].type == "aid" and sim.world.events[0].effects["amount"] == 10.0
    assert result.event["effects"]["amount"] == 10.0


def test_default_aid_amount_is_valid_for_every_starting_country(sim):
    assert MIN_AID_AMOUNT <= DEFAULT_AID_AMOUNT <= MAX_AID_AMOUNT
    for c in sim.world.countries:
        assert DEFAULT_AID_AMOUNT <= round(c.gdp * MAX_AID_GDP_SHARE, 2), c.id


def test_aid_the_backend_refuses_is_reported_not_forced(sim):
    country(sim, "india").gdp = 50.0  # 10% of 50 = 5, so an amount of 10 is over the backend's limit
    before = world_dump(sim)
    result = execute_decision(decision("AID", "France"), "india", sim)

    assert result.status == "rejected" and not result.ok and not result.executed
    assert result.http_status == 400 and "at most" in result.message and result.amount == 10.0
    assert world_dump(sim) == before  # nothing was changed and the rules were not bent


# --- 4. NO_ACTION --------------------------------------------------------------------------------------
def test_no_action_does_not_touch_the_world_or_call_the_backend(sim):
    calls = []
    for name in ("sanction", "alliance", "aid"):
        setattr(sim, name, lambda *a, _n=name, **k: calls.append(_n))
    before = world_dump(sim)

    result = execute_decision(decision("NO_ACTION"), "india", sim)

    assert result.status == "no_action" and result.ok and not result.executed
    assert result.event is None and result.target is None and result.http_status is None
    assert calls == [] and world_dump(sim) == before and sim.world.events == []


# --- 7. backend rejection ----------------------------------------------------------------------------------
def test_backend_rejection_is_reported_and_never_claimed_as_success(sim):
    sim.alliance("india", "france")  # the starting dataset has no alliances: form one first
    before = world_dump(sim)
    result = execute_decision(decision("ALLIANCE", "France"), "india", sim)  # already allied

    assert result.status == "rejected" and not result.ok and not result.executed
    assert result.http_status == 409 and "already" in result.message.lower()
    assert result.event is None and result.actor_after is None
    assert world_dump(sim) == before and len(sim.world.events) == 1  # only the setup alliance event


def test_unknown_target_is_rejected_with_404(sim):
    before = world_dump(sim)
    d = CountryDecision(country="India", situation="s", decision=Decision.SANCTION, target="Atlantis", reason="r")
    result = execute_decision(d, "india", sim)
    assert result.status == "rejected" and result.http_status == 404
    assert world_dump(sim) == before


def test_unexpected_backend_failure_is_an_error_result_not_a_crash(sim):
    def boom(*_a, **_k):
        raise RuntimeError("internal details")

    sim.sanction = boom
    result = execute_decision(decision("SANCTION", "Brazil"), "india", sim)
    assert result.status == "error" and not result.ok and result.http_status == 500
    assert "RuntimeError" in result.message and "internal details" not in result.message


# --- 8. repeated execution ----------------------------------------------------------------------------------
def test_duplicate_protection_still_applies_to_repeated_decisions(sim):
    first = execute_decision(decision("SANCTION", "Brazil"), "india", sim)
    after_first = world_dump(sim)
    second = execute_decision(decision("SANCTION", "Brazil"), "india", sim)

    assert first.status == "executed"
    assert second.status == "rejected" and second.http_status == 409
    assert world_dump(sim) == after_first and len(sim.world.events) == 1

    assert execute_decision(decision("ALLIANCE", "China"), "india", sim).status == "executed"
    assert execute_decision(decision("ALLIANCE", "China"), "india", sim).status == "rejected"
    assert len(sim.world.events) == 2


def test_repeated_aid_is_allowed_by_the_backend_each_time(sim):
    assert execute_decision(decision("AID", "France"), "india", sim).executed
    assert execute_decision(decision("AID", "France"), "india", sim).executed
    assert [e.type for e in sim.world.events] == ["aid", "aid"]


# --- the bridge only delegates -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind, method, args",
    [
        ("SANCTION", "sanction", ("india", "brazil")),
        ("ALLIANCE", "alliance", ("india", "brazil")),
        ("AID", "aid", ("india", "brazil", 10.0)),
    ],
)
def test_each_decision_calls_exactly_its_backend_action(sim, kind, method, args):
    calls = []
    for name in ("sanction", "alliance", "aid"):
        original = getattr(sim, name)
        setattr(sim, name, lambda *a, _o=original, _n=name: (calls.append((_n, a)), _o(*a))[1])

    execute_decision(decision(kind, "Brazil"), "india", sim)
    assert calls == [(method, args)]


def test_target_id_from_the_agent_is_used_when_present(sim):
    result = execute_decision(decision("SANCTION", "Brazil", target_id="brazil"), "india", sim)
    assert result.target == "brazil"


# --- unsupported / caller errors ------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["ATTACK", "", None, 7])
def test_unsupported_decisions_are_rejected_loudly(sim, bad):
    before = world_dump(sim)
    fake = SimpleNamespace(decision=bad, country="India", target="Brazil", target_id="brazil")
    with pytest.raises(UnsupportedDecisionError):
        execute_decision(fake, "india", sim)
    assert world_dump(sim) == before


def test_unknown_actor_or_mismatched_country_is_a_caller_error(sim):
    with pytest.raises(ValueError, match="Unknown acting country"):
        execute_decision(decision("NO_ACTION"), "atlantis", sim)
    with pytest.raises(ValueError, match="acting country"):
        execute_decision(decision("SANCTION", "China", country="Brazil"), "india", sim)  # not India's decision


def test_result_model_properties():
    r = BridgeResult(status="rejected", action="AID", actor="india", message="no", http_status=400)
    assert not r.ok and not r.executed