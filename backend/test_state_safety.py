"""State-safety tests (Prompt 5): repeated and failing actions must never corrupt the world.

Run from backend/:  python test_state_safety.py   (or: pytest)
"""
import random

import pytest
from fastapi.testclient import TestClient

import simulation as sim_module
from main import app
from rules import ActionResult, ConflictError, find_country, validate_world
from simulation import create_initial_world, simulation

client = TestClient(app)
safe_client = TestClient(app, raise_server_exceptions=False)  # returns 500s instead of raising

IDS = ["aurelia", "brevania", "caldoria", "dravenia", "eldoria",
       "fyrnia", "garvonia", "helvaris", "istoria", "jorvania"]


def snapshot() -> dict:
    return simulation.world.model_dump()


def post(kind: str, actor: str, target: str, **extra):
    return client.post(f"/actions/{kind}", json={"actor": actor, "target": target, **extra})


def assert_world_sane() -> None:
    assert validate_world(simulation.world) == []
    for c in simulation.world.countries:
        assert c.gdp >= 0 and 0 <= c.stability <= 100
        assert all(-100 <= v <= 100 for v in c.relationships.values())
        assert all(0 <= v <= 100 for v in c.resources.values())
    for r in simulation.world.trade_routes:
        assert r.volume >= 0 and r.base_volume > 0 and 0 <= r.efficiency <= 150


# --- scripted sequence from the QA brief ----------------------------------------
def test_sanction_aid_alliance_aid_reset_sequence():
    original = create_initial_world().model_dump()

    assert post("sanction", "aurelia", "caldoria").status_code == 200
    assert_world_sane()
    assert post("aid", "helvaris", "istoria", amount=100).status_code == 200
    assert_world_sane()
    # aurelia sanctions caldoria, so that pair may NOT ally; garvonia/fyrnia may
    assert post("alliance", "aurelia", "caldoria").status_code == 409
    assert post("alliance", "garvonia", "fyrnia").status_code == 200
    assert_world_sane()
    assert post("aid", "garvonia", "fyrnia", amount=20).status_code == 200
    assert_world_sane()
    assert len(simulation.world.events) == 4

    assert client.post("/simulation/reset").json() == original
    assert snapshot() == original
    assert_world_sane()


# --- seeded fuzz: valid and invalid actions mixed ----------------------------------
def test_fuzz_mixed_actions_keep_world_valid_and_failures_change_nothing():
    rng = random.Random(20261016)
    amounts = [-5, 0, 0.5, 1, 10, 33.33, 50, 100, 500, 1000]
    successes = 0
    statuses = set()

    for _ in range(400):
        kind = rng.choice(["sanction", "alliance", "aid", "aid"])
        actor = rng.choice(IDS + ["ghost"])
        target = rng.choice(IDS + ["ghost", actor])
        extra = {"amount": rng.choice(amounts)} if kind == "aid" else {}

        before = snapshot()
        r = post(kind, actor, target, **extra)
        statuses.add(r.status_code)

        if r.status_code == 200:
            successes += 1
            assert len(simulation.world.events) == len(before["events"]) + 1
        else:
            assert r.status_code in (400, 404, 409), r.text
            assert snapshot() == before  # a rejected action changes NOTHING
        assert_world_sane()

    assert statuses == {200, 400, 404, 409}  # the run really exercised every outcome
    assert len(simulation.world.events) == successes
    assert [e.id for e in simulation.world.events] == list(range(1, successes + 1))
    assert client.post("/simulation/reset").json() == create_initial_world().model_dump()


def test_actions_never_change_resources():
    start = {c["id"]: c["resources"] for c in snapshot()["countries"]}
    post("sanction", "caldoria", "eldoria")
    post("alliance", "garvonia", "fyrnia")
    post("aid", "aurelia", "istoria", amount=100)
    assert {c.id: c.resources for c in simulation.world.countries} == start


def test_validate_world_flags_resource_out_of_range():
    w = simulation.world.model_copy(deep=True)
    w.countries[0].resources["tech"] = 150
    assert any("resource" in p for p in validate_world(w))
    w = simulation.world.model_copy(deep=True)
    w.countries[0].resources["tech"] = -1
    assert any("resource" in p for p in validate_world(w))


# --- atomicity: a rule that fails midway must not leave partial changes -----------------
def test_rule_that_mutates_then_rejects_leaves_world_untouched(monkeypatch):
    def mutate_then_reject(world, _actor, _target):
        caldoria = find_country(world, "caldoria")
        caldoria.gdp = 1.0
        caldoria.stability = 0
        world.trade_routes[0].active = False
        raise ConflictError("rejected halfway")

    monkeypatch.setattr(sim_module, "apply_sanction", mutate_then_reject)
    before = snapshot()
    r = post("sanction", "aurelia", "caldoria")
    assert r.status_code == 409 and r.json() == {"detail": "rejected halfway"}
    assert snapshot() == before


@pytest.mark.parametrize("corrupt", [
    lambda w: setattr(find_country(w, "caldoria"), "gdp", -5.0),
    lambda w: setattr(find_country(w, "caldoria"), "stability", 150),
    lambda w: find_country(w, "caldoria").relationships.__setitem__("aurelia", 999),
    lambda w: find_country(w, "caldoria").relationships.__setitem__("aurelia", -7),  # breaks symmetry
    lambda w: setattr(w.trade_routes[0], "base_volume", 0),  # recalculation cannot repair a bad base level
])
def test_rule_that_would_corrupt_the_world_is_blocked(monkeypatch, corrupt):
    def corrupting_rule(world, _actor, _target):
        corrupt(world)
        return ActionResult(type="sanction", message="corrupting", effects={})

    monkeypatch.setattr(sim_module, "apply_sanction", corrupting_rule)
    before = snapshot()
    r = safe_client.post("/actions/sanction", json={"actor": "aurelia", "target": "caldoria"})
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"}
    assert snapshot() == before
    assert simulation.world.events == []


def test_derived_trade_state_is_repaired_not_rejected(monkeypatch):
    """volume/active/trade_partners are derived, so a rule that leaves them wrong is healed by recalculation."""
    def sloppy_rule(world, _actor, _target):
        world.trade_routes[0].volume = -3
        world.countries[0].trade_partners = []
        return ActionResult(type="sanction", message="sloppy", effects={})

    monkeypatch.setattr(sim_module, "apply_sanction", sloppy_rule)
    assert post("sanction", "aurelia", "garvonia").status_code == 200
    route = simulation.world.trade_routes[0]
    assert route.volume == route.base_volume > 0
    assert_world_sane()


def test_world_still_works_after_a_blocked_corruption(monkeypatch):
    monkeypatch.setattr(
        sim_module, "apply_sanction",
        lambda w, *_: (setattr(find_country(w, "caldoria"), "gdp", -1.0), ActionResult("sanction", "x"))[1],
    )
    assert safe_client.post("/actions/sanction", json={"actor": "aurelia", "target": "caldoria"}).status_code == 500
    monkeypatch.undo()
    assert post("sanction", "aurelia", "caldoria").status_code == 200  # server keeps serving valid actions
    assert_world_sane()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))