"""Tests for the trade-route economy (Prompt 3).

Run from backend/:  python test_trade.py   (or: pytest)
"""
from fastapi.testclient import TestClient

from main import app
from rules import (
    ALLIANCE_TRADE_EFFICIENCY,
    TRADE_EFFICIENCY_MAX,
    recalculate_trade_effects,
    validate_world,
)
from simulation import create_initial_world, simulation

client = TestClient(app)


def reset() -> dict:
    r = client.post("/simulation/reset")
    assert r.status_code == 200
    return r.json()


def world() -> dict:
    return client.get("/world").json()


def routes(w: dict) -> dict:
    return {r["id"]: r for r in w["trade_routes"]}


def pair_ids(w: dict, a: str, b: str) -> set:
    return {r["id"] for r in w["trade_routes"] if {r["exporter"], r["importer"]} == {a, b}}


def partners(w: dict, cid: str) -> set:
    return set(next(c for c in w["countries"] if c["id"] == cid)["trade_partners"])


def act(kind: str, actor: str, target: str, **extra):
    return client.post(f"/actions/{kind}", json={"actor": actor, "target": target, **extra})


def assert_trade_consistent(w: dict) -> None:
    active_links = {c["id"]: set() for c in w["countries"]}
    for r in w["trade_routes"]:
        assert r["volume"] >= 0 and r["base_volume"] > 0
        assert 0 <= r["efficiency"] <= TRADE_EFFICIENCY_MAX
        if r["active"]:
            assert r["volume"] > 0 and r["efficiency"] > 0
            active_links[r["exporter"]].add(r["importer"])
            active_links[r["importer"]].add(r["exporter"])
        else:
            assert r["volume"] == 0 and r["efficiency"] == 0
    for c in w["countries"]:
        assert set(c["trade_partners"]) == active_links[c["id"]], c["id"]
        assert c["gdp"] >= 0 and 0 <= c["stability"] <= 100


# 1. initial trade routes exist --------------------------------------------------
def test_initial_trade_routes_exist():
    w = reset()
    assert len(w["trade_routes"]) == 16
    ids = [r["id"] for r in w["trade_routes"]]
    assert len(set(ids)) == len(ids)
    required = {"id", "exporter", "importer", "resource", "volume", "active", "base_volume", "efficiency"}
    country_ids = {c["id"] for c in w["countries"]}
    for r in w["trade_routes"]:
        assert required <= set(r)
        assert r["exporter"] in country_ids and r["importer"] in country_ids
        assert r["exporter"] != r["importer"]


# 2. normal trade baseline ---------------------------------------------------------
def test_active_routes_have_positive_volume_at_baseline():
    w = reset()
    for r in w["trade_routes"]:
        assert r["active"] is True
        assert r["efficiency"] == 100
        assert r["volume"] > 0
        assert r["volume"] == r["base_volume"]  # normal trade = 100% of base
    assert_trade_consistent(w)
    assert validate_world(simulation.world) == []


# 3 + 4. sanction hits the right routes, not others -------------------------------
def test_sanction_cuts_only_the_direct_routes():
    before = reset()
    pair = pair_ids(before, "caldoria", "eldoria")
    assert len(pair) == 2  # route-04 (caldoria->eldoria) and route-05 (eldoria->caldoria)

    assert act("sanction", "caldoria", "eldoria").status_code == 200
    after = world()

    for rid in pair:  # both directions, whichever side sanctioned
        r = routes(after)[rid]
        assert r["active"] is False and r["volume"] == 0 and r["efficiency"] == 0
        assert r["volume"] < routes(before)[rid]["volume"]
        assert r["base_volume"] == routes(before)[rid]["base_volume"]  # normal level is remembered
    for rid, r in routes(after).items():  # everything else is byte-for-byte unchanged
        if rid not in pair:
            assert r == routes(before)[rid], rid
    assert "eldoria" not in partners(after, "caldoria")
    assert "caldoria" not in partners(after, "eldoria")
    # other partner links of the two countries survive
    assert partners(after, "caldoria") == partners(before, "caldoria") - {"eldoria"}
    assert partners(after, "eldoria") == partners(before, "eldoria") - {"caldoria"}
    assert_trade_consistent(after)


def test_sanction_with_no_direct_route_changes_no_routes():
    before = reset()
    assert not pair_ids(before, "aurelia", "garvonia")
    assert act("sanction", "aurelia", "garvonia").status_code == 200
    after = world()
    assert after["trade_routes"] == before["trade_routes"]
    assert_trade_consistent(after)


def test_sanction_event_reports_trade_effects():
    reset()
    ev = act("sanction", "caldoria", "eldoria").json()["event"]
    assert sorted(ev["effects"]["trade_routes_deactivated"]) == ["route-04", "route-05"]
    assert set(ev["effects"]["trade_routes"]) == {"route-04", "route-05"}
    assert ev["effects"]["trade_routes"]["route-04"]["after"]["volume"] == 0


# 5 + 6. alliance boosts the right routes, not others -------------------------------
def test_alliance_boosts_only_the_direct_routes():
    before = reset()
    pair = pair_ids(before, "garvonia", "fyrnia")  # Meridian Pact vs Sunward Union: not yet allied
    assert len(pair) == 2

    assert act("alliance", "garvonia", "fyrnia").status_code == 200
    after = world()

    for rid in pair:
        r0, r1 = routes(before)[rid], routes(after)[rid]
        assert r1["active"] is True
        assert r1["efficiency"] == ALLIANCE_TRADE_EFFICIENCY
        assert r1["volume"] > r0["volume"]
        assert r1["base_volume"] == r0["base_volume"]
    for rid, r in routes(after).items():
        if rid not in pair:
            assert r == routes(before)[rid], rid
    for cid in ("garvonia", "fyrnia"):  # still trading with the same partners
        assert partners(after, cid) == partners(before, cid)
    assert_trade_consistent(after)


def test_alliance_without_direct_route_changes_no_routes():
    before = reset()
    assert not pair_ids(before, "helvaris", "jorvania")
    assert act("alliance", "helvaris", "jorvania").status_code == 200
    assert world()["trade_routes"] == before["trade_routes"]


def test_alliance_never_creates_routes():
    before = reset()
    act("alliance", "aurelia", "caldoria")
    act("alliance", "garvonia", "fyrnia")
    act("alliance", "helvaris", "jorvania")
    after = world()
    assert [r["id"] for r in after["trade_routes"]] == [r["id"] for r in before["trade_routes"]]


# alliance bonus must not stack -------------------------------------------------------
def test_alliance_bonus_does_not_stack():
    reset()
    act("alliance", "aurelia", "caldoria")
    first = world()
    assert routes(first)["route-03"]["efficiency"] == ALLIANCE_TRADE_EFFICIENCY

    # processing the same relationship again is rejected and changes nothing
    assert act("alliance", "aurelia", "caldoria").status_code == 409
    assert act("alliance", "caldoria", "aurelia").status_code == 409
    assert world() == first

    # recalculating (any number of times) never adds the bonus again
    for _ in range(3):
        assert recalculate_trade_effects(simulation.world) == {}
    assert world() == first

    # allying with a third country does not touch the aurelia-caldoria route
    act("alliance", "caldoria", "dravenia")
    assert routes(world())["route-03"] == routes(first)["route-03"]


# sanction after alliance and the reverse order ---------------------------------------
def test_sanction_overrides_alliance_boost():
    reset()
    act("alliance", "aurelia", "caldoria")
    assert act("sanction", "aurelia", "caldoria").status_code == 200
    r = routes(world())["route-03"]
    assert r["active"] is False and r["volume"] == 0 and r["efficiency"] == 0
    assert_trade_consistent(world())


def test_sanctioned_pair_cannot_ally_so_no_boost_leaks():
    reset()
    act("sanction", "caldoria", "eldoria")
    snapshot = world()
    # rejected (they already share the Meridian Pact), and nothing changes
    assert act("alliance", "caldoria", "eldoria").status_code == 409
    assert world() == snapshot
    assert routes(snapshot)["route-04"]["volume"] == 0


# 7. reset restores trade state -----------------------------------------------------------
def test_reset_restores_original_trade_state():
    original = create_initial_world().model_dump()["trade_routes"]
    act("sanction", "caldoria", "eldoria")
    act("alliance", "garvonia", "fyrnia")
    act("alliance", "aurelia", "caldoria")
    assert world()["trade_routes"] != original

    after_reset = reset()
    assert after_reset["trade_routes"] == original
    assert world()["trade_routes"] == original
    assert_trade_consistent(world())


# 8. values never go negative / out of range ----------------------------------------------
def test_trade_values_never_negative_under_many_actions():
    reset()
    ids = [c["id"] for c in world()["countries"]]
    for a in ids:
        for b in ids:
            if a == b:
                continue
            act("alliance", a, b)  # many will be 409; that is fine
            act("sanction", a, b)
            act("aid", a, b, amount=5)
            assert_trade_consistent(world())
    assert validate_world(simulation.world) == []
    # every pair ended up sanctioned both ways, so no route is left flowing
    assert all(not r["active"] for r in world()["trade_routes"])
    assert all(c["trade_partners"] == [] for c in world()["countries"])


def test_repeated_alliances_never_exceed_efficiency_ceiling():
    reset()
    ids = [c["id"] for c in world()["countries"]]
    for a in ids:
        for b in ids:
            if a != b:
                act("alliance", a, b)
    for r in world()["trade_routes"]:
        assert r["efficiency"] <= max(ALLIANCE_TRADE_EFFICIENCY, 100)
        assert r["efficiency"] <= TRADE_EFFICIENCY_MAX
    assert_trade_consistent(world())


# recalculation function --------------------------------------------------------------------
def test_recalculate_is_idempotent_and_repairs_drift():
    reset()
    act("sanction", "caldoria", "eldoria")
    act("alliance", "garvonia", "fyrnia")
    settled = simulation.world.model_copy(deep=True)
    assert recalculate_trade_effects(simulation.world) == {}
    assert simulation.world == settled

    # corrupt a copy by hand; recalculation repairs it
    broken = settled.model_copy(deep=True)
    broken.trade_routes[0].volume = 9999
    broken.trade_routes[3].active = True      # route-04 is sanctioned, must be cut again
    broken.countries[0].trade_partners = []
    assert validate_world(broken) != []
    changes = recalculate_trade_effects(broken)
    assert "route-01" in changes and "route-04" in changes
    assert validate_world(broken) == []
    assert broken == settled


def test_cut_route_is_restored_when_sanction_is_removed():
    """Future-proofing for 'lift sanction': recalculation brings trade back to normal."""
    reset()
    act("sanction", "caldoria", "eldoria")
    draft = simulation.world.model_copy(deep=True)
    next(c for c in draft.countries if c.id == "eldoria").sanctions.remove("caldoria")
    recalculate_trade_effects(draft)
    for rid in ("route-04", "route-05"):
        r = next(x for x in draft.trade_routes if x.id == rid)
        assert r.active and r.efficiency == 100 and r.volume == r.base_volume
    assert validate_world(draft) == []


def test_validate_world_flags_bad_trade_state():
    reset()
    w = simulation.world.model_copy(deep=True)
    w.trade_routes[0].volume = -4
    assert any("negative volume" in p for p in validate_world(w))
    w = simulation.world.model_copy(deep=True)
    w.trade_routes[0].efficiency = 400
    assert any("efficiency" in p for p in validate_world(w))
    w = simulation.world.model_copy(deep=True)
    w.trade_routes[0].active = False  # inactive but not sanctioned, and still has volume
    assert validate_world(w) != []


# GET /world exposes current trade state ---------------------------------------------------
def test_world_endpoint_shows_current_trade_state():
    before = reset()
    act("sanction", "caldoria", "eldoria")
    mid = world()
    assert routes(mid)["route-04"]["active"] is False
    assert routes(before)["route-04"]["active"] is True
    act("alliance", "garvonia", "fyrnia")
    assert routes(world())["route-08"]["volume"] > routes(mid)["route-08"]["volume"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            reset()
            fn()
            print("PASS", name)
    reset()