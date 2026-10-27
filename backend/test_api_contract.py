"""API contract tests (Prompt 4): what Person 1 (frontend) and Person 3 (AI) rely on.

Run from backend/:  python test_api_contract.py   (or: pytest)
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend import main as backend_main
from backend.main import DEFAULT_CORS_ORIGINS, app, cors_origins
from backend.simulation import simulation

client = TestClient(app)

COUNTRY_FIELDS = {"id", "name", "gdp", "stability", "resources", "trade_partners",
                  "alliances", "sanctions", "relationships"}
ROUTE_FIELDS = {"id", "exporter", "importer", "resource", "volume", "active", "base_volume", "efficiency"}
EVENT_FIELDS = {"id", "turn", "type", "actor", "target", "message", "timestamp", "effects"}


def world() -> dict:
    return client.get("/world").json()


def country(w: dict, cid: str) -> dict:
    return next(c for c in w["countries"] if c["id"] == cid)


def route(w: dict, rid: str) -> dict:
    return next(r for r in w["trade_routes"] if r["id"] == rid)


def post(path: str, body):
    return client.post(path, json=body)


# 1. health ------------------------------------------------------------------------
def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


# 2. world --------------------------------------------------------------------------
def test_world_contains_everything_the_frontend_needs():
    r = client.get("/world")
    assert r.status_code == 200
    w = r.json()
    json.dumps(w)  # JSON-serializable
    assert set(w) == {"turn", "countries", "trade_routes", "events"}
    assert w["turn"] == 0 and w["events"] == []
    assert len(w["countries"]) == 8
    ids = [c["id"] for c in w["countries"]]
    assert len(set(ids)) == 8
    for c in w["countries"]:
        assert COUNTRY_FIELDS <= set(c)
        assert c["name"] and isinstance(c["gdp"], (int, float)) and 0 <= c["stability"] <= 100
        assert isinstance(c["resources"], dict) and c["resources"]
        assert set(c["relationships"]) == set(ids) - {c["id"]}
        assert c["sanctions"] == [] and isinstance(c["alliances"], list)  # the starting world has no sanctions
    assert len(w["trade_routes"]) == 16
    for t in w["trade_routes"]:
        assert ROUTE_FIELDS <= set(t)


# 3 + 4. country detail -----------------------------------------------------------------
def test_country_detail():
    r = client.get("/countries/india")
    assert r.status_code == 200
    c = r.json()
    assert COUNTRY_FIELDS <= set(c)
    assert c == country(world(), "india")  # same representation as /world, nothing duplicated differently
    assert client.get("/countries/INDIA").json() == c
    assert client.get("/countries/%20India%20").status_code == 200


def test_country_unknown_is_404_json():
    r = client.get("/countries/atlantis")
    assert r.status_code == 404
    assert "atlantis" in r.json()["detail"]


# 5. sanction ---------------------------------------------------------------------------
def test_sanction_contract():
    r = post("/actions/sanction", {"actor": "india", "target": "united-states"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"event", "actor", "target"}
    assert EVENT_FIELDS <= set(body["event"])
    assert body["event"]["type"] == "sanction"
    assert COUNTRY_FIELDS <= set(body["actor"]) and COUNTRY_FIELDS <= set(body["target"])
    w = world()
    assert body["target"] == country(w, "united-states")  # response matches /world
    assert "india" in country(w, "united-states")["sanctions"]
    assert route(w, "route-01")["active"] is False
    assert len(w["events"]) == 1


# 6. alliance ----------------------------------------------------------------------------
def test_alliance_contract():
    r = post("/actions/alliance", {"actor": "china", "target": "japan"})
    assert r.status_code == 200
    body = r.json()
    assert body["event"]["type"] == "alliance" and EVENT_FIELDS <= set(body["event"])
    w = world()
    assert body["actor"] == country(w, "china") and body["target"] == country(w, "japan")
    assert "China-Japan Alliance" in country(w, "japan")["alliances"]
    assert route(w, "route-04")["volume"] > route(w, "route-04")["base_volume"]


# 7. aid -------------------------------------------------------------------------------------
def test_aid_contract():
    before = world()
    r = post("/actions/aid", {"actor": "india", "target": "brazil", "amount": 100})
    assert r.status_code == 200
    body = r.json()
    assert body["event"]["type"] == "aid" and EVENT_FIELDS <= set(body["event"])
    w = world()
    assert body["target"] == country(w, "brazil")
    assert country(w, "brazil")["gdp"] > country(before, "brazil")["gdp"]
    assert country(w, "india")["gdp"] < country(before, "india")["gdp"]


# 8. events ------------------------------------------------------------------------------------
def test_events_feed():
    assert client.get("/events").json() == []
    post("/actions/sanction", {"actor": "india", "target": "united-states"})
    post("/actions/alliance", {"actor": "china", "target": "japan"})
    post("/actions/aid", {"actor": "france", "target": "brazil", "amount": 50})
    feed = client.get("/events").json()
    assert [e["type"] for e in feed] == ["aid", "alliance", "sanction"]  # newest first
    assert [e["id"] for e in feed] == [3, 2, 1]
    for e in feed:
        assert EVENT_FIELDS <= set(e)
        assert e["message"] and e["actor"] and e["target"] and e["timestamp"]
    stamps = [e["timestamp"] for e in feed]
    assert stamps == sorted(stamps, reverse=True)
    assert [e["id"] for e in world()["events"]] == [1, 2, 3]  # /world history is oldest first
    assert len(client.get("/events?limit=1").json()) == 1


# 9. reset ----------------------------------------------------------------------------------------
def test_reset_restores_everything():
    original = client.post("/simulation/reset").json()
    post("/actions/sanction", {"actor": "india", "target": "united-states"})
    post("/actions/alliance", {"actor": "china", "target": "japan"})
    post("/actions/aid", {"actor": "india", "target": "brazil", "amount": 100})
    assert world() != original
    again = client.post("/simulation/reset").json()
    assert again == original == world()
    assert again["events"] == [] and client.get("/events").json() == []
    assert all(c["sanctions"] == [] for c in again["countries"])
    assert all(r["active"] and r["efficiency"] == 100 for r in again["trade_routes"])


# 10. errors ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("path,body,status", [
    ("/actions/sanction", {"actor": "ghost", "target": "india"}, 404),
    ("/actions/alliance", {"actor": "india", "target": "ghost"}, 404),
    ("/actions/aid", {"actor": "ghost", "target": "india", "amount": 10}, 404),
    ("/actions/sanction", {"actor": "india", "target": "india"}, 400),
    ("/actions/alliance", {"actor": "india", "target": "india"}, 400),
    ("/actions/aid", {"actor": "india", "target": "india", "amount": 10}, 400),
    ("/actions/aid", {"actor": "india", "target": "brazil", "amount": 0}, 400),
    ("/actions/aid", {"actor": "india", "target": "brazil", "amount": -5}, 400),
    ("/actions/aid", {"actor": "india", "target": "brazil", "amount": 99999}, 400),
    ("/actions/aid", {"actor": "india", "target": "brazil", "amount": "lots"}, 422),
    ("/actions/aid", {"actor": "india", "target": "brazil"}, 422),
    ("/actions/sanction", {"actor": "india"}, 422),
    ("/actions/sanction", {}, 422),
])
def test_error_status_codes_and_shape(path, body, status):
    r = post(path, body)
    assert r.status_code == status
    detail = r.json()["detail"]
    if status == 422:
        assert isinstance(detail, list) and all({"loc", "msg", "type"} <= set(d) for d in detail)
    else:
        assert isinstance(detail, str) and detail


def test_duplicate_actions_are_409():
    assert post("/actions/sanction", {"actor": "india", "target": "united-states"}).status_code == 200
    r = post("/actions/sanction", {"actor": "india", "target": "united-states"})
    assert r.status_code == 409 and isinstance(r.json()["detail"], str)
    assert post("/actions/alliance", {"actor": "china", "target": "japan"}).status_code == 200
    assert post("/actions/alliance", {"actor": "china", "target": "japan"}).status_code == 409


@pytest.mark.parametrize("raw", [
    '{"actor": "india", "target": "brazil", "amount": NaN}',
    '{"actor": "india", "target": "brazil", "amount": Infinity}',
    '{"actor": "india", "target": "brazil", "amount": -Infinity}',
    '{"actor": "india", "target": "brazil", "amount": 1e999}',
    "not json",
    "",
    "[]",
])
def test_bad_bodies_are_422_never_500(raw):
    # Regression: a literal NaN used to make the 422 body unserializable -> bare 500.
    r = client.post("/actions/aid", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 422
    json.dumps(r.json())
    assert world()["events"] == []


def test_unknown_route_and_bad_method_are_json():
    assert client.get("/nope").status_code == 404 and "detail" in client.get("/nope").json()
    r = client.put("/world")
    assert r.status_code == 405 and "detail" in r.json()
    assert client.get("/events?limit=0").status_code == 422
    assert client.get("/events?limit=abc").status_code == 422


def test_unexpected_error_is_json_500_without_traceback(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(simulation, "sanction", boom)
    safe = TestClient(app, raise_server_exceptions=False)
    r = safe.post("/actions/sanction", json={"actor": "india", "target": "united-states"})
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal server error"}
    assert "secret" not in r.text and "Traceback" not in r.text


# 11. trade behaviour still works through the API ---------------------------------------------------
def test_trade_behaviour_through_api():
    before = world()
    post("/actions/sanction", {"actor": "india", "target": "united-states"})
    post("/actions/alliance", {"actor": "china", "target": "japan"})
    post("/actions/alliance", {"actor": "france", "target": "united-kingdom"})
    after = world()
    for rid in ("route-01", "route-02"):  # india <-> united-states, both directions
        assert route(after, rid)["active"] is False and route(after, rid)["volume"] == 0
    for rid in ("route-04", "route-07"):  # china->japan, france->united-kingdom
        assert route(after, rid)["efficiency"] == 110 and route(after, rid)["volume"] > route(before, rid)["volume"]
    assert route(after, "route-09") == route(before, "route-09")  # russia->china: unrelated
    assert "united-states" not in country(after, "india")["trade_partners"]


# CORS ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"])
def test_cors_allows_local_frontends(origin):
    r = client.options("/actions/aid", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == origin
    g = client.get("/world", headers={"Origin": origin})
    assert g.headers["access-control-allow-origin"] == origin


def test_cors_rejects_unknown_origin_and_is_not_wildcard():
    r = client.get("/world", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    assert "*" not in cors_origins()


def test_cors_origins_env(monkeypatch):
    assert cors_origins() == DEFAULT_CORS_ORIGINS
    monkeypatch.setenv("CORS_ORIGINS", "https://my-app.vercel.app/, http://localhost:5173 ,")
    assert cors_origins() == ["https://my-app.vercel.app", "http://localhost:5173"]
    monkeypatch.setenv("CORS_ORIGINS", "  ")
    assert cors_origins() == DEFAULT_CORS_ORIGINS


# OpenAPI / Swagger ------------------------------------------------------------------------------------------
def test_docs_and_openapi():
    assert client.get("/docs").status_code == 200
    assert "swagger" in client.get("/docs").text.lower()
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    expected = {
        ("get", "/health"), ("get", "/world"), ("get", "/countries/{country_id}"), ("get", "/events"),
        ("post", "/actions/sanction"), ("post", "/actions/alliance"), ("post", "/actions/aid"),
        ("post", "/simulation/reset"),
    }
    found = {(m, p) for p, ms in spec["paths"].items() for m in ms}
    assert expected <= found
    for m, p in expected:
        op = spec["paths"][p][m]
        assert op.get("summary") and op.get("tags"), (m, p)
    for p in ("/actions/sanction", "/actions/alliance", "/actions/aid"):
        assert {"400", "404", "409", "422"} <= set(spec["paths"][p]["post"]["responses"])
    assert "404" in spec["paths"]["/countries/{country_id}"]["get"]["responses"]


# 12. the exact frontend workflow -------------------------------------------------------------------------
def test_frontend_workflow():
    start = client.get("/world").json()                                   # 2. load the map
    a, b = start["countries"][0]["id"], start["countries"][2]["id"]       # 3. pick two countries
    assert post("/actions/sanction", {"actor": a, "target": b}).status_code == 200       # 4.
    assert post("/actions/aid", {"actor": a, "target": start["countries"][7]["id"], "amount": 20}).status_code == 200
    mid = client.get("/world").json()                                     # 5. refresh the map
    assert mid != start and len(mid["events"]) == 2
    feed = client.get("/events").json()                                   # 6. diplomacy feed
    assert [e["type"] for e in feed] == ["aid", "sanction"]
    detail = client.get(f"/countries/{b}").json()                         # 7. detail panel
    assert detail["sanctions"] == [a] and detail["relationships"][a] < start["countries"][2]["relationships"][a]
    assert client.post("/simulation/reset").json() == start               # 8.
    assert client.get("/world").json() == start                           # 9.
    assert client.get("/events").json() == []


# 13. AI agent workflow: observe -> propose (POST /ai/propose) -> act through the existing action endpoints -------
def test_ai_agent_can_observe_decide_and_act_with_existing_endpoints(monkeypatch):
    w = client.get("/world").json()                                       # observe
    weakest = min(w["countries"], key=lambda c: c["stability"])
    richest = max(w["countries"], key=lambda c: c["gdp"])
    detail = client.get(f"/countries/{weakest['id']}").json()             # inspect
    assert detail["stability"] == weakest["stability"]

    # POST /ai/propose is the one intentional AI endpoint. Gemini is replaced by a canned reply so the test
    # needs no API key and no network; the real agent, validation and fallback code still run.
    canned = json.dumps({
        "country": richest["name"],
        "situation": f"{weakest['name']} is the least stable country.",
        "decision": "AID",
        "target": weakest["name"],
        "reason": f"Aid helps stabilise {weakest['name']}.",
    })
    real_agent = backend_main.CountryAgent
    monkeypatch.setattr(backend_main, "CountryAgent", lambda profile: real_agent(profile, llm=lambda system, user: canned))

    r = post("/ai/propose", {"country_id": richest["id"], "situation": f"{weakest['name']} is the least stable country."})
    assert r.status_code == 200                                           # decide: a validated proposal
    proposal = r.json()
    assert proposal["source"] == "ai" and proposal["used_fallback"] is False
    assert proposal["error_code"] is None and proposal["error"] is None
    assert proposal["decision"]["decision"] == "AID" and proposal["decision"]["country"] == richest["name"]
    assert proposal["decision"]["target"] == weakest["name"]
    assert client.get("/events").json() == []                             # a proposal never changes the world

    r = post("/actions/aid", {"actor": richest["id"], "target": weakest["id"], "amount": 10})  # act
    assert r.status_code == 200
    history = client.get("/events").json()                                # remember
    assert history[0]["actor"] == richest["id"] and history[0]["target"] == weakest["id"]

    # Execution still goes through /actions/*: /ai/propose and /ai/advisor (advice only) are the only world-simulation AI
    # paths, and there is no agent API. Phase 8 adds the conference AI roles under /ai/mun/*: POST-only, proposal-only.
    paths = app.openapi()["paths"]
    ai_paths = sorted(p for p in paths if ("agent" in p or "ai" in p.split("/")) and not p.startswith("/ai/mun/"))
    assert ai_paths == ["/ai/advisor", "/ai/propose"]  # advisor chat = advice only; execution is still /actions/*
    assert all(list(paths[p]) == ["post"] for p in paths if p.startswith("/ai/mun/"))


# 14. /ai/propose names the Gemma model for AI decisions; an AI failure is an explicit failure, never a decision ---
def test_ai_proposal_reports_gemma_model_and_ai_failure_is_not_a_decision(monkeypatch):
    real_agent = backend_main.CountryAgent
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(backend_main, "resolve_model", lambda: "gemma-4-26b-a4b-it")

    def boom(system, user):
        raise RuntimeError("simulated Gemma outage")

    monkeypatch.setattr(backend_main, "CountryAgent", lambda profile: real_agent(profile, llm=boom))
    body = {"country_id": "india", "situation": "Test incident."}
    r = post("/ai/propose", body)
    failed = r.json()
    assert r.status_code == 502
    assert failed["status"] == "AI_REQUEST_FAILED" and failed["reason"] == "GEMINI_UNEXPECTED_ERROR"
    assert failed["decision"] is None and failed["source"] is None and failed["used_fallback"] is False
    assert "NO_ACTION" not in json.dumps(failed)                          # an AI failure is never a NO_ACTION decision
    assert client.get("/events").json() == []                             # and it changed nothing

    canned = json.dumps({"country": "India", "situation": "s", "decision": "NO_ACTION", "target": None, "reason": "r"})
    monkeypatch.setattr(backend_main, "CountryAgent", lambda profile: real_agent(profile, llm=lambda s, u: canned))
    ok = post("/ai/propose", body).json()
    assert ok["status"] == "SUCCESS" and ok["source"] == "ai" and ok["model"] == "gemma-4-26b-a4b-it"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))