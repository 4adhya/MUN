"""Phase 8: the /ai/mun/* endpoints. Gemini is replaced by a canned reply (LLM_OVERRIDE); conferences are real.

Proves: a valid proposal comes back as advisory and not executed, a bad conference state is 409 (not an AI failure),
an AI failure is 502/503 with no `output` (never a valid MUN action), and every endpoint is POST-only and strict.
"""
import json

import pytest
from fastapi.testclient import TestClient

import backend.ai_routes as ai_routes
from ai.check_gemini import EXIT_CONFIG, CheckError
from backend.main import app

client = TestClient(app)
FLOW = ["LOBBY", "ROLL_CALL", "OPENING_SPEECHES", "MODERATED_CAUCUS", "UNMODERATED_CAUCUS",
        "CRISIS", "DRAFTING", "VOTING", "RESULTS"]


def conference(phase):
    cid = client.post("/conference/create", json={"name": "C", "committee": "GLOBAL_CYBERSECURITY", "topic": "Peace"}).json()["id"]
    for code in ("IN", "US", "CN"):
        client.post(f"/conference/{cid}/join", json={"name": f"D{code}", "role": "PARTICIPANT", "country": code})
    client.post(f"/conference/{cid}/start")
    for _ in range(len(FLOW)):
        if client.get(f"/conference/{cid}").json()["current_phase"] == phase:
            break
        client.post(f"/conference/{cid}/advance")
    return cid


@pytest.fixture
def llm():
    ai_routes.LLM_OVERRIDE = None
    yield lambda reply: setattr(ai_routes, "LLM_OVERRIDE", (lambda s, u: json.dumps(reply) if not isinstance(reply, (str, Exception)) else _raise(reply)))
    ai_routes.LLM_OVERRIDE = None


def _raise(reply):
    if isinstance(reply, Exception):
        raise reply
    return reply


STRATEGY = {"country": "India", "action": "NEGOTIATION", "target": "China", "vote": None, "resolution_id": None,
            "rationale": "r", "expected_outcome": "o"}


def test_success_is_advisory_and_changes_nothing(llm):
    cid = conference("UNMODERATED_CAUCUS")
    before = client.get(f"/conference/{cid}").json()
    llm(STRATEGY)
    r = client.post("/ai/mun/strategy", json={"conference_id": cid, "country_code": "in"})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "SUCCESS" and body["role"] == "country-strategist"
    assert body["advisory"] is True and body["executed"] is False
    assert body["output"]["action"] == "NEGOTIATION" and body["meta"]["phase"] == "UNMODERATED_CAUCUS"
    assert client.get(f"/conference/{cid}").json() == before
    assert client.get(f"/conference/{cid}/negotiations").json() == []


def test_invalid_ai_output_is_a_502_with_no_output(llm):
    cid = conference("UNMODERATED_CAUCUS")
    for bad in ("not json", {**STRATEGY, "action": "NO_ACTION"}, {**STRATEGY, "target": "Atlantis"}):
        llm(bad)
        r = client.post("/ai/mun/strategy", json={"conference_id": cid, "country_code": "IN"})
        body = r.json()
        assert r.status_code == 502 and body["status"] == "AI_REQUEST_FAILED" and body["error_code"] == "invalid_response"
        assert body["output"] is None and body["executed"] is False and "NO_ACTION" not in json.dumps(body["output"])


def test_gemini_failures_map_to_502_and_503(llm):
    cid = conference("UNMODERATED_CAUCUS")
    llm(CheckError("quota", 3))
    r = client.post("/ai/mun/strategy", json={"conference_id": cid, "country_code": "IN"})
    assert r.status_code == 502 and r.json()["error_code"] == "gemini_error" and r.json()["output"] is None
    llm(CheckError("no key", EXIT_CONFIG))
    r = client.post("/ai/mun/strategy", json={"conference_id": cid, "country_code": "IN"})
    assert r.status_code == 503 and r.json()["output"] is None


def test_conference_state_problems_are_409_unknown_conference_404(llm):
    llm(STRATEGY)
    lobby = client.post("/conference/create", json={"name": "C", "committee": "GLOBAL_CYBERSECURITY", "topic": "P"}).json()["id"]
    assert client.post("/ai/mun/strategy", json={"conference_id": lobby, "country_code": "IN"}).status_code == 409
    cid = conference("OPENING_SPEECHES")
    assert client.post("/ai/mun/strategy", json={"conference_id": cid, "country_code": "BR"}).status_code == 409  # not seated
    assert client.post("/ai/mun/speech", json={"conference_id": cid, "country_code": "IN", "speech_type": "CAUCUS"}).status_code == 409
    assert client.post("/ai/mun/judge", json={"conference_id": cid}).status_code == 409  # not completed
    assert client.post("/ai/mun/chair", json={"conference_id": "conf-missing"}).status_code == 404


def test_requests_are_validated_strictly():
    cid = "conf-x"
    for path, body in (
        ("/ai/mun/strategy", {"conference_id": cid}),
        ("/ai/mun/strategy", {"conference_id": cid, "country_code": "INDIA"}),
        ("/ai/mun/strategy", {"conference_id": cid, "country_code": "IN", "extra": 1}),
        ("/ai/mun/speech", {"conference_id": cid, "country_code": "IN", "speech_type": "RANT"}),
        ("/ai/mun/crisis", {"conference_id": cid, "country_code": "IN", "crisis": {"title": "", "description": "d"}}),
        ("/ai/mun/chair", {"conference_id": cid, "question": "q" * 501}),
        ("/ai/mun/opponent", {"conference_id": cid, "country_code": "IN"}),
    ):
        assert client.post(path, json=body).status_code == 422, (path, body)


def test_other_roles_over_http(llm):
    cid = conference("OPENING_SPEECHES")
    llm({"country": "India", "speech_type": "OPENING", "text": "India speaks.", "addressed_countries": []})
    r = client.post("/ai/mun/speech", json={"conference_id": cid, "country_code": "IN", "speech_type": "OPENING"})
    assert r.status_code == 200 and r.json()["output"]["text"] == "India speaks." and r.json()["meta"]["submittable_now"] is True
    assert client.get(f"/conference/{cid}/speeches").json() == []  # drafted, never submitted
    llm({"guidance": "Speakers are heard in order.", "procedural_options": ["Recognise the next speaker."], "cautions": []})
    r = client.post("/ai/mun/chair", json={"conference_id": cid, "question": "What next?"})
    assert r.status_code == 200 and r.json()["meta"]["decides_nothing"] is True
    llm({"guidance": "The resolution has been passed.", "procedural_options": ["x"], "cautions": []})
    assert client.post("/ai/mun/chair", json={"conference_id": cid}).status_code == 502


def test_endpoints_are_post_only():
    paths = [p for p in app.openapi()["paths"] if p.startswith("/ai/mun/")]
    assert len(paths) == 12
    for p in paths:
        assert list(app.openapi()["paths"][p]) == ["post"]
        assert client.get(p).status_code == 405