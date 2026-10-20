"""Tests for sanction / alliance / aid / events / reset.

Run from backend/:  python test_actions.py   (or: pytest)
"""
from fastapi.testclient import TestClient

from backend.main import app
from backend.rules import find_country, validate_world
from backend.simulation import create_initial_world, simulation

client = TestClient(app)


def fresh_world() -> dict:
    r = client.post("/simulation/reset")
    assert r.status_code == 200
    return r.json()


def country(world: dict, cid: str) -> dict:
    return next(c for c in world["countries"] if c["id"] == cid)


def get_world() -> dict:
    return client.get("/world").json()


def post(path: str, body) -> "object":
    return client.post(path, json=body)


# --- Sanction ----------------------------------------------------------------
def test_sanction_effects():
    before = fresh_world()
    r = post("/actions/sanction", {"actor": "india", "target": "united-states"})
    assert r.status_code == 200, r.text
    after = get_world()

    t0, t1 = country(before, "united-states"), country(after, "united-states")
    assert t1["gdp"] < t0["gdp"]
    assert t1["stability"] < t0["stability"]
    assert "india" in t1["sanctions"]
    assert t1["relationships"]["india"] < t0["relationships"]["india"]
    assert country(after, "india")["relationships"]["united-states"] == t1["relationships"]["india"]

    # the united-states->india energy route is now inactive and no longer a partner link
    route = next(x for x in after["trade_routes"] if x["exporter"] == "united-states" and x["importer"] == "india")
    assert route["active"] is False
    assert "india" not in t1["trade_partners"]
    # unrelated routes untouched (route-04 is china->japan)
    assert next(x for x in after["trade_routes"] if x["id"] == "route-04")["active"] is True
    # unrelated countries untouched
    assert country(after, "japan") == country(before, "japan")
    assert validate_world(simulation.world) == []


def test_sanction_response_and_event():
    fresh_world()
    r = post("/actions/sanction", {"actor": "India", "target": " UNITED-STATES "}).json()  # ids are normalized
    ev = r["event"]
    assert {"id", "type", "actor", "target", "message", "timestamp"} <= set(ev)
    assert ev["type"] == "sanction" and ev["actor"] == "india" and ev["target"] == "united-states"
    assert r["target"]["id"] == "united-states"


def test_sanction_errors():
    fresh_world()
    assert post("/actions/sanction", {"actor": "atlantis", "target": "india"}).status_code == 404
    assert post("/actions/sanction", {"actor": "india", "target": "atlantis"}).status_code == 404
    assert post("/actions/sanction", {"actor": "india", "target": "india"}).status_code == 400
    assert post("/actions/sanction", {"actor": "india", "target": "united-states"}).status_code == 200
    dup = post("/actions/sanction", {"actor": "india", "target": "united-states"})
    assert dup.status_code == 409 and "already" in dup.json()["detail"]
    # opposite direction is a different sanction and is allowed
    assert post("/actions/sanction", {"actor": "united-states", "target": "india"}).status_code == 200


# --- Alliance ------------------------------------------------------------------
def test_alliance_effects():
    before = fresh_world()
    r = post("/actions/alliance", {"actor": "india", "target": "united-states"})
    assert r.status_code == 200, r.text
    after = get_world()
    a0, a1 = country(before, "india"), country(after, "india")
    c0, c1 = country(before, "united-states"), country(after, "united-states")

    assert "India-United States Alliance" in a1["alliances"] and "India-United States Alliance" in c1["alliances"]
    assert a1["relationships"]["united-states"] > a0["relationships"]["united-states"]
    assert a1["relationships"]["united-states"] == c1["relationships"]["india"]
    assert a1["stability"] > a0["stability"] and c1["stability"] > c0["stability"]
    old = next(x for x in before["trade_routes"] if x["id"] == "route-02")  # united-states -> india energy
    new = next(x for x in after["trade_routes"] if x["id"] == "route-02")
    assert new["volume"] > old["volume"]
    assert r.json()["event"]["type"] == "alliance"
    assert validate_world(simulation.world) == []


def test_alliance_errors():
    fresh_world()
    assert post("/actions/alliance", {"actor": "india", "target": "india"}).status_code == 400
    assert post("/actions/alliance", {"actor": "nowhere", "target": "india"}).status_code == 404
    assert post("/actions/alliance", {"actor": "india", "target": "nowhere"}).status_code == 404
    # already allied through an alliance that was in the world before this action (the starting world has
    # no alliances, so seed one shared by both countries)
    for cid in ("india", "united-kingdom"):
        find_country(simulation.world, cid).alliances.append("Seeded Test Alliance")
    seeded = post("/actions/alliance", {"actor": "india", "target": "united-kingdom"})
    assert seeded.status_code == 409 and "already allied" in seeded.json()["detail"]
    # duplicate, in either direction
    assert post("/actions/alliance", {"actor": "india", "target": "united-states"}).status_code == 200
    assert post("/actions/alliance", {"actor": "india", "target": "united-states"}).status_code == 409
    assert post("/actions/alliance", {"actor": "united-states", "target": "india"}).status_code == 409
    # cannot ally with a country you sanction
    assert post("/actions/sanction", {"actor": "france", "target": "russia"}).status_code == 200
    assert post("/actions/alliance", {"actor": "russia", "target": "france"}).status_code == 409


# --- Aid -----------------------------------------------------------------------
def test_aid_effects():
    before = fresh_world()
    r = post("/actions/aid", {"actor": "india", "target": "brazil", "amount": 50})
    assert r.status_code == 200, r.text
    after = get_world()
    a0, a1 = country(before, "india"), country(after, "india")
    i0, i1 = country(before, "brazil"), country(after, "brazil")

    assert i1["stability"] > i0["stability"]
    assert i1["gdp"] > i0["gdp"]
    assert a1["gdp"] < a0["gdp"]
    assert a0["gdp"] - a1["gdp"] < 50  # "slightly"
    assert i1["relationships"]["india"] > i0["relationships"]["india"]
    assert r.json()["event"]["type"] == "aid"
    assert validate_world(simulation.world) == []


def test_aid_errors():
    fresh_world()
    ok = {"actor": "india", "target": "brazil"}
    assert post("/actions/aid", {**ok, "amount": 0}).status_code == 400
    assert post("/actions/aid", {**ok, "amount": -5}).status_code == 400
    assert post("/actions/aid", {**ok, "amount": 100000}).status_code == 400
    assert post("/actions/aid", {**ok, "amount": 400}).status_code == 400      # over 10% of India's GDP (390)
    assert post("/actions/aid", {"actor": "russia", "target": "india", "amount": 300}).status_code == 400  # >10% of 2200
    assert post("/actions/aid", {**ok, "amount": "lots"}).status_code == 422
    assert post("/actions/aid", {**ok, "amount": True}).status_code == 422
    assert post("/actions/aid", ok).status_code == 422                          # missing amount
    assert post("/actions/aid", {"actor": "x", "target": "brazil", "amount": 10}).status_code == 404
    assert post("/actions/aid", {"actor": "india", "target": "x", "amount": 10}).status_code == 404
    assert post("/actions/aid", {"actor": "india", "target": "india", "amount": 10}).status_code == 400


# --- Malformed requests --------------------------------------------------------
def test_malformed_requests():
    fresh_world()
    for path in ("/actions/sanction", "/actions/alliance", "/actions/aid"):
        assert post(path, {}).status_code == 422
        assert post(path, {"actor": "india"}).status_code == 422
        assert post(path, {"actor": 5, "target": "united-states", "amount": 10}).status_code == 422
        assert post(path, {"actor": "", "target": "united-states", "amount": 10}).status_code == 422
        assert post(path, {"actor": "india", "target": "united-states", "amount": 10, "extra": 1}).status_code == 422
        assert client.post(path, content="not json", headers={"content-type": "application/json"}).status_code == 422
        assert client.post(path).status_code == 422
    assert get_world()["events"] == []


# --- Failed actions never change anything -----------------------------------------
def test_failed_actions_do_not_modify_world():
    fresh_world()
    post("/actions/sanction", {"actor": "india", "target": "united-states"})
    post("/actions/alliance", {"actor": "china", "target": "japan"})
    snapshot = get_world()
    bad = [
        ("/actions/sanction", {"actor": "india", "target": "united-states"}),   # duplicate sanction
        ("/actions/sanction", {"actor": "india", "target": "india"}),
        ("/actions/alliance", {"actor": "china", "target": "japan"}),           # already allied
        ("/actions/alliance", {"actor": "india", "target": "united-states"}),   # sanctioned pair
        ("/actions/aid", {"actor": "india", "target": "brazil", "amount": -1}),
        ("/actions/aid", {"actor": "ghost", "target": "brazil", "amount": 10}),
    ]
    for path, body in bad:
        assert post(path, body).status_code >= 400
    assert get_world() == snapshot  # same state, same events


# --- Events ----------------------------------------------------------------------
def test_events():
    fresh_world()
    assert client.get("/events").json() == []
    post("/actions/sanction", {"actor": "india", "target": "united-states"})
    post("/actions/alliance", {"actor": "france", "target": "united-kingdom"})
    post("/actions/aid", {"actor": "france", "target": "brazil", "amount": 50})
    events = client.get("/events").json()
    assert [e["type"] for e in events] == ["aid", "alliance", "sanction"]  # newest first
    assert [e["id"] for e in events] == [3, 2, 1]
    for e in events:
        assert e["message"] and e["timestamp"] and e["actor"] and e["target"]
    assert len(client.get("/events?limit=2").json()) == 2
    assert len(get_world()["events"]) == 3  # full history, oldest first
    assert client.get("/events?limit=0").status_code == 422
    assert client.get("/events?limit=101").status_code == 422


# --- Reset -----------------------------------------------------------------------
def test_reset_restores_original_world():
    original = create_initial_world().model_dump()
    post("/actions/sanction", {"actor": "india", "target": "united-states"})
    post("/actions/alliance", {"actor": "france", "target": "united-kingdom"})
    post("/actions/aid", {"actor": "france", "target": "brazil", "amount": 50})
    assert get_world() != original

    assert client.post("/simulation/reset").json() == original
    assert get_world() == original
    assert client.get("/events").json() == []
    # event ids start over
    r = post("/actions/sanction", {"actor": "india", "target": "united-states"})
    assert r.json()["event"]["id"] == 1


def test_values_stay_in_range_under_repeated_actions():
    fresh_world()
    for target in ("brazil", "japan"):
        for _ in range(12):
            post("/actions/aid", {"actor": "india", "target": target, "amount": 100})
    assert validate_world(simulation.world) == []
    assert all(0 <= c.stability <= 100 for c in simulation.world.countries)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
    fresh_world()