"""Tests for gemini_client.py with a FAKE Gemini SDK client: no network, no real key.

They check that we call the SDK the way we intend (model, prompt, system instruction, JSON mode)
and that failures turn into key-free CheckErrors. They do not talk to Google.
"""
import pytest

pytest.importorskip("google.genai")

import gemini_client
from check_gemini import DEFAULT_MODEL, EXIT_API, EXIT_CONFIG, CheckError

FAKE_KEY = "fake-key-for-tests-123456"


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeClient:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeResponse(self.reply)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.setattr(gemini_client, "REPO_ROOT", tmp_path)  # so a real .env is never read
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)


def install(monkeypatch, client):
    monkeypatch.setattr(gemini_client, "_build_client", lambda key: client)
    return client


def test_calls_generate_content_with_system_instruction_and_json_mode(monkeypatch):
    client = install(monkeypatch, FakeClient(reply='{"ok": true}'))
    text = gemini_client.generate_json_text("SYSTEM TEXT", "USER TEXT")

    assert text == '{"ok": true}'
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == DEFAULT_MODEL
    assert call["contents"] == "USER TEXT"
    config = call["config"]
    assert config.system_instruction == "SYSTEM TEXT"
    assert config.response_mime_type == "application/json"
    assert config.temperature == gemini_client.TEMPERATURE


def test_model_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "my-model")
    client = install(monkeypatch, FakeClient(reply="{}"))
    gemini_client.generate_json_text("s", "u")
    assert client.calls[0]["model"] == "my-model"


def test_missing_key_is_a_config_error_and_no_call_is_made(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    client = install(monkeypatch, FakeClient(reply="{}"))
    with pytest.raises(CheckError) as err:
        gemini_client.generate_json_text("s", "u")
    assert err.value.exit_code == EXIT_CONFIG and client.calls == []


def test_api_errors_become_check_errors_without_the_key(monkeypatch):
    install(monkeypatch, FakeClient(error=RuntimeError(f"connection reset (key={FAKE_KEY})")))
    with pytest.raises(CheckError) as err:
        gemini_client.generate_json_text("s", "u")
    assert err.value.exit_code == EXIT_API
    assert FAKE_KEY not in err.value.message


def test_empty_reply_is_a_check_error(monkeypatch):
    install(monkeypatch, FakeClient(reply="   "))
    with pytest.raises(CheckError):
        gemini_client.generate_json_text("s", "u")


def test_real_sdk_objects_can_be_built():
    """Builds the real SDK client/config (no request is sent) to catch SDK API mismatches."""
    assert gemini_client._build_client(FAKE_KEY) is not None
    assert gemini_client._build_config("sys").system_instruction == "sys"