"""POST /ai/propose reliability: an AI failure is AI_REQUEST_FAILED, never a successful NO_ACTION.

Gemini is replaced by a scripted FAKE SDK client (real agent, real retry code, real validation).
No network and no real API key are used.
"""
import json
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("google.genai")
from fastapi.testclient import TestClient
from google.genai import errors

from ai import gemini_client
from backend.main import app

client = TestClient(app)

# country id -> (display name, a valid other country to target)
COUNTRIES = {
    "india": ("India", "Brazil"),
    "china": ("China", "Japan"),
    "united-states": ("United States", "China"),
    "brazil": ("Brazil", "India"),
    "japan": ("Japan", "United States"),
}
COUNTRY_IDS = list(COUNTRIES)
SITUATION = "A trade dispute is escalating."


def reply(name, decision="NO_ACTION", target=None):
    return json.dumps({"country": name, "situation": "s", "decision": decision, "target": target, "reason": "r"})


def server_error(code):
    return errors.ServerError(code, {"error": {"code": code, "message": "Internal error encountered.", "status": "X"}})


class ScriptedClient:
    def __init__(self, script):
        self.script, self.calls = list(script), 0
        self.models = self

    def generate_content(self, **kwargs):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item, prompt_feedback=None, candidates=[])


@pytest.fixture
def gemini(monkeypatch, tmp_path):
    """Returns install(script) -> (fake client, recorded backoff delays)."""
    monkeypatch.setattr(gemini_client, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    for name in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODEL", "GEMINI_MAX_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gemini_client, "_semaphore", None)
    delays = []
    monkeypatch.setattr(gemini_client, "_sleep", delays.append)

    def install(script):
        fake = ScriptedClient(script)
        monkeypatch.setattr(gemini_client, "_build_client", lambda key: fake)
        return fake, delays

    return install


def propose(country_id):
    return client.post("/ai/propose", json={"country_id": country_id, "situation": SITUATION})


def snapshot():
    return client.get("/world").json(), client.get("/events").json()


def assert_ai_failure(response, reason, http_status=None, attempts=None):
    body = response.json()
    assert response.status_code == 502
    assert body["status"] == "AI_REQUEST_FAILED" and body["reason"] == reason
    assert body["decision"] is None and body["source"] is None and body["used_fallback"] is False
    assert "NO_ACTION" not in json.dumps(body)  # a failure is never reported as "the country chose no action"
    assert "SAFE FALLBACK" not in json.dumps(body)
    if http_status is not None:
        assert body["upstream_http_status"] == http_status
    if attempts is not None:
        assert body["attempts"] == attempts
    return body


@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_successful_ai_response(gemini, country_id):
    name, target = COUNTRIES[country_id]
    fake, delays = gemini([reply(name, "SANCTION", target)])
    before = snapshot()
    r = propose(country_id)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "SUCCESS" and body["source"] == "ai"
    assert body["used_fallback"] is False and body["error"] is None
    assert body["decision"]["decision"] == "SANCTION" and body["decision"]["target"] == target
    assert fake.calls == 1 and delays == []
    assert snapshot() == before  # a proposal never mutates the world


@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_intentional_no_action_is_a_success(gemini, country_id):
    name, _ = COUNTRIES[country_id]
    fake, _ = gemini([reply(name, "NO_ACTION", None)])
    r = propose(country_id)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "SUCCESS" and body["source"] == "ai"
    assert body["decision"]["decision"] == "NO_ACTION" and body["decision"]["target"] is None
    assert body["used_fallback"] is False and fake.calls == 1


@pytest.mark.parametrize("code", [500, 503])
@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_persistent_http_5xx_is_ai_request_failed_after_bounded_retries(gemini, country_id, code):
    fake, delays = gemini([server_error(code)] * 10)
    before = snapshot()
    body = assert_ai_failure(propose(country_id), f"GEMINI_HTTP_{code}", http_status=code, attempts=3)
    assert body["country"] == COUNTRIES[country_id][0] and body["error_code"] == "gemini_error"
    assert fake.calls == 3 and len(delays) == 2 and delays[1] > delays[0] * 0.99  # retries are bounded and back off
    assert snapshot() == before  # no sanctions, alliances, aid or events


@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_timeout_is_ai_request_failed(gemini, country_id):
    fake, _ = gemini([httpx.ReadTimeout("slow")] * 10)
    before = snapshot()
    assert_ai_failure(propose(country_id), "GEMINI_TIMEOUT", attempts=3)
    assert fake.calls == 3 and snapshot() == before


@pytest.mark.parametrize("bad", ["this is not json", "{}", '{"decision": "ATTACK"}', ""])
@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_malformed_ai_response_is_ai_request_failed_and_not_retried(gemini, country_id, bad):
    fake, delays = gemini([bad, reply("x")])
    before = snapshot()
    r = propose(country_id)
    body = r.json()
    assert r.status_code == 502 and body["status"] == "AI_REQUEST_FAILED"
    assert body["reason"] in {"INVALID_AI_RESPONSE", "GEMINI_EMPTY_RESPONSE"}
    assert body["decision"] is None and body["source"] is None  # (the error text may list NO_ACTION as a valid option)
    assert fake.calls == 1 and delays == []  # validation is not weakened and a bad answer is not "retried into" success
    assert snapshot() == before


def test_reply_for_the_wrong_country_is_still_rejected(gemini):
    gemini([reply("China", "NO_ACTION", None)])
    assert_ai_failure(propose("india"), "INVALID_AI_RESPONSE")


@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_retry_success_returns_the_ai_decision(gemini, country_id):
    name, target = COUNTRIES[country_id]
    fake, delays = gemini([server_error(500), server_error(503), reply(name, "ALLIANCE", target)])
    before = snapshot()
    r = propose(country_id)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "SUCCESS" and body["source"] == "ai"
    assert body["decision"]["decision"] == "ALLIANCE" and body["decision"]["target"] == target
    assert fake.calls == 3 and len(delays) == 2
    assert snapshot() == before


@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_retry_success_with_an_intentional_no_action(gemini, country_id):
    name, _ = COUNTRIES[country_id]
    gemini([httpx.ConnectError("refused"), reply(name, "NO_ACTION", None)])
    body = propose(country_id).json()
    assert body["status"] == "SUCCESS" and body["decision"]["decision"] == "NO_ACTION"


def test_missing_api_key_is_a_configuration_failure(gemini, monkeypatch):
    gemini([reply("India")])
    monkeypatch.delenv("GEMINI_API_KEY")
    r = propose("india")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "AI_REQUEST_FAILED" and body["reason"] == "AI_CONFIGURATION_ERROR"
    assert body["decision"] is None


def test_failure_never_leaks_the_api_key(gemini):
    secret = "fake-key-for-tests"
    leaky = errors.ServerError(500, {"error": {"code": 500, "message": f"key={secret}", "status": "INTERNAL"}})
    gemini([leaky] * 3)
    r = propose("india")
    assert secret not in r.text


def test_failure_detail_is_a_string_the_existing_frontend_client_displays(gemini):
    gemini([server_error(500)] * 3)
    body = propose("india").json()
    assert isinstance(body["detail"], str) and "GEMINI_HTTP_500" in body["detail"]
    assert "not changed" in body["detail"]


def test_a_failed_proposal_can_be_retried_and_then_succeeds(gemini):
    gemini([server_error(503)] * 3 + [reply("India", "NO_ACTION", None)])
    assert propose("india").status_code == 502
    assert propose("india").json()["status"] == "SUCCESS"