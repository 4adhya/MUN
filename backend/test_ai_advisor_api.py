"""POST /ai/advisor: advice-only chat. Gemini is a scripted FAKE SDK client (real retry code, no network/key)."""
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
COUNTRY_IDS = ["india", "china", "united-states", "brazil", "japan"]


def server_error(code):
    return errors.ServerError(code, {"error": {"code": code, "message": "Internal error encountered.", "status": "X"}})


class ScriptedClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item, prompt_feedback=None, candidates=[])


@pytest.fixture
def gemini(monkeypatch, tmp_path):
    monkeypatch.setattr(gemini_client, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    for name in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODEL", "GEMINI_MAX_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gemini_client, "_semaphore", None)
    monkeypatch.setattr(gemini_client, "_sleep", lambda s: None)

    def install(script):
        fake = ScriptedClient(script)
        monkeypatch.setattr(gemini_client, "_build_client", lambda key: fake)
        return fake

    return install


def ask(country_id="india", message="What should we do?", history=None):
    return client.post("/ai/advisor", json={"country_id": country_id, "message": message, "history": history or []})


def snapshot():
    return client.get("/world").json(), client.get("/events").json()


@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_advisor_replies_with_plain_text_advice(gemini, country_id):
    fake = gemini(["Open talks first, then reassess.\n- Keep trade routes open."])
    before = snapshot()
    r = ask(country_id)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "SUCCESS"
    assert body["reply"].startswith("Open talks first") and body["model"]
    config = fake.calls[0]["config"]
    assert config.response_mime_type is None  # plain text, not JSON mode
    assert snapshot() == before  # advice never mutates the world


def test_history_reaches_the_model(gemini):
    fake = gemini(["ok"])
    history = [{"role": "user", "text": "Is Brazil a threat?"}, {"role": "advisor", "text": "Not currently."}]
    ask("india", "And China?", history)
    prompt = fake.calls[0]["contents"]
    assert "Delegate: Is Brazil a threat?" in prompt and "Advisor: Not currently." in prompt and "And China?" in prompt


@pytest.mark.parametrize("country_id", COUNTRY_IDS)
def test_persistent_503_is_ai_request_failed_after_bounded_retries(gemini, country_id):
    fake = gemini([server_error(503)] * 10)
    before = snapshot()
    r = ask(country_id)
    body = r.json()
    assert r.status_code == 502 and body["status"] == "AI_REQUEST_FAILED" and body["reason"] == "GEMINI_HTTP_503"
    assert body["attempts"] == 3 and len(fake.calls) == 3
    assert "reply" not in body and body["decision"] is None  # no invented advice
    assert snapshot() == before


def test_timeout_and_http_500(gemini):
    gemini([httpx.ReadTimeout("slow")] * 3)
    assert ask().json()["reason"] == "GEMINI_TIMEOUT"
    gemini([server_error(500)] * 3)
    assert ask().json()["reason"] == "GEMINI_HTTP_500"


def test_retry_success_returns_advice(gemini):
    fake = gemini([server_error(500), server_error(503), "Hold firm but talk."])
    body = ask().json()
    assert body["status"] == "SUCCESS" and body["reply"] == "Hold firm but talk." and len(fake.calls) == 3


def test_empty_reply_is_a_failure(gemini):
    gemini(["   "])
    r = ask()
    assert r.status_code == 502 and r.json()["status"] == "AI_REQUEST_FAILED"


def test_request_validation_and_unknown_country(gemini):
    fake = gemini(["unused"])
    assert ask(message="").status_code == 422
    assert ask(message="x" * 1001).status_code == 422
    assert ask(history=[{"role": "robot", "text": "hi"}]).status_code == 422
    assert ask(history=[{"role": "user", "text": "hi"}] * 17).status_code == 422
    assert ask(message="   ").status_code == 422
    assert ask(country_id="atlantis-xyz").status_code == 404
    assert fake.calls == []  # nothing reached Gemini


def test_missing_key_is_a_configuration_failure(gemini, monkeypatch):
    gemini(["unused"])
    monkeypatch.delenv("GEMINI_API_KEY")
    r = ask()
    assert r.status_code == 503 and r.json()["reason"] == "AI_CONFIGURATION_ERROR"


def test_failure_never_leaks_the_key(gemini):
    leaky = errors.ServerError(500, {"error": {"code": 500, "message": "key=fake-key-for-tests", "status": "X"}})
    gemini([leaky] * 3)
    assert "fake-key-for-tests" not in ask().text