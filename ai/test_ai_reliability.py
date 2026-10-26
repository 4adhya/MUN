"""Reliability tests for the Gemini layer: retries, backoff, fallback model, concurrency cap, logging.

Everything here uses a FAKE Gemini SDK client (scripted replies/errors). No network, no real key.
"""
import json
import logging
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("google.genai")
from google.genai import errors

from ai import gemini_client
from ai.check_gemini import DEFAULT_MODEL, EXIT_CONFIG, CheckError
from ai.country_agent import COUNTRY_PROFILES, CountryAgent
from backend.simulation import Simulation

FAKE_KEY = "AIza-fake-secret-key-for-tests"


def server_error(code=500, status="INTERNAL"):
    return errors.ServerError(code, {"error": {"code": code, "message": "Internal error encountered.", "status": status}})


def client_error(code):
    return errors.ClientError(code, {"error": {"code": code, "message": "nope", "status": "X"}})


def ok_reply(country="India", decision="NO_ACTION", target=None):
    return json.dumps(
        {"country": country, "situation": "s", "decision": decision, "target": target, "reason": "because"}
    )


class ScriptedClient:
    """models.generate_content() pops the next scripted item: an Exception is raised, a str is the reply text."""

    def __init__(self, script, delay=0.0):
        self.script, self.calls, self.delay = list(script), [], delay
        self.models = self
        self.in_flight = self.max_in_flight = 0
        self._lock = threading.Lock()

    def generate_content(self, **kwargs):
        with self._lock:
            self.calls.append(kwargs)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            item = self.script.pop(0)
        try:
            if self.delay:
                time.sleep(self.delay)
            if isinstance(item, Exception):
                raise item
            return SimpleNamespace(text=item, prompt_feedback=None, candidates=[])
        finally:
            with self._lock:
                self.in_flight -= 1

    @property
    def models_used(self):
        return [c["model"] for c in self.calls]


@pytest.fixture
def sleeps(monkeypatch, tmp_path):
    """Isolated env, no real waiting; returns the list of backoff delays that were requested."""
    monkeypatch.setattr(gemini_client, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    for name in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODEL", "GEMINI_MAX_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gemini_client, "_semaphore", None)
    recorded = []
    monkeypatch.setattr(gemini_client, "_sleep", recorded.append)
    return recorded


def install(monkeypatch, client):
    monkeypatch.setattr(gemini_client, "_build_client", lambda key: client)
    return client


def call():
    return gemini_client.generate_json_text("sys", "user", country="India")


# --- retry behaviour ----------------------------------------------------------------------------
@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_transient_http_errors_are_retried_and_can_succeed(monkeypatch, sleeps, code):
    fake = install(monkeypatch, ScriptedClient([server_error(code), ok_reply()]))
    assert call() == ok_reply()
    assert len(fake.calls) == 2 and len(sleeps) == 1


@pytest.mark.parametrize(
    "exc, reason",
    [
        (httpx.ReadTimeout("slow"), "GEMINI_TIMEOUT"),
        (httpx.ConnectTimeout("slow"), "GEMINI_TIMEOUT"),
        (httpx.ConnectError("refused"), "GEMINI_CONNECTION_ERROR"),
        (ConnectionResetError("reset"), "GEMINI_CONNECTION_ERROR"),
    ],
)
def test_timeouts_and_connection_errors_are_retried(monkeypatch, sleeps, exc, reason):
    fake = install(monkeypatch, ScriptedClient([exc, exc, exc]))
    with pytest.raises(gemini_client.GeminiRequestError) as err:
        call()
    assert err.value.reason == reason and err.value.retryable and err.value.attempts == 3
    assert len(fake.calls) == 3


def test_retry_exhaustion_is_bounded_and_reports_the_http_status(monkeypatch, sleeps):
    fake = install(monkeypatch, ScriptedClient([server_error(500)] * 10))
    with pytest.raises(gemini_client.GeminiRequestError) as err:
        call()
    assert len(fake.calls) == 1 + gemini_client.MAX_RETRIES == 3  # never infinite
    assert err.value.reason == "GEMINI_HTTP_500" and err.value.http_status == 500 and err.value.attempts == 3
    assert FAKE_KEY not in err.value.message


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429])
def test_client_errors_are_not_retried(monkeypatch, sleeps, code):
    fake = install(monkeypatch, ScriptedClient([client_error(code), ok_reply()]))
    with pytest.raises(gemini_client.GeminiRequestError) as err:
        call()
    assert len(fake.calls) == 1 and sleeps == []
    assert err.value.reason == f"GEMINI_HTTP_{code}" and not err.value.retryable


def test_empty_reply_and_unexpected_errors_are_not_retried(monkeypatch, sleeps):
    fake = install(monkeypatch, ScriptedClient(["   ", RuntimeError("boom"), ok_reply()]))
    with pytest.raises(gemini_client.GeminiRequestError) as empty:
        call()
    assert empty.value.reason == "GEMINI_EMPTY_RESPONSE" and len(fake.calls) == 1
    with pytest.raises(gemini_client.GeminiRequestError) as unexpected:
        call()
    assert unexpected.value.reason == "GEMINI_UNEXPECTED_ERROR" and len(fake.calls) == 2


def test_backoff_is_exponential_with_jitter_and_capped(monkeypatch, sleeps):
    monkeypatch.setattr(gemini_client, "_uniform", lambda lo, hi: lo)
    assert [gemini_client._backoff_delay(i) for i in range(5)] == [0.5, 1.0, 2.0, 4.0, 4.0]
    monkeypatch.setattr(gemini_client, "_uniform", lambda lo, hi: hi)
    assert [gemini_client._backoff_delay(i) for i in range(5)] == [1.0, 2.0, 4.0, 8.0, 8.0]
    monkeypatch.undo()  # real jitter stays inside the window
    for _ in range(50):
        assert 1.0 <= gemini_client._backoff_delay(1) <= 2.0


def test_delays_between_attempts_increase(monkeypatch, sleeps):
    monkeypatch.setattr(gemini_client, "_uniform", lambda lo, hi: hi)
    install(monkeypatch, ScriptedClient([server_error(503)] * 3))
    with pytest.raises(CheckError):
        call()
    assert sleeps == [1.0, 2.0]  # 2 pauses for 3 attempts, the second longer


def test_total_time_budget_stops_retrying(monkeypatch, sleeps):
    clock = [0.0]
    monkeypatch.setattr(gemini_client, "_now", lambda: clock[0])
    monkeypatch.setattr(gemini_client, "_sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(gemini_client, "_uniform", lambda lo, hi: lo)
    monkeypatch.setattr(gemini_client, "TOTAL_BUDGET_SECONDS", 11.0)
    fake = install(monkeypatch, ScriptedClient([server_error(500)] * 5))
    with pytest.raises(gemini_client.GeminiRequestError):
        call()
    assert len(fake.calls) == 2  # a third attempt would leave less than the 10 s Gemini minimum


def test_no_attempt_is_ever_sent_with_a_deadline_under_gemini_minimum(monkeypatch, sleeps):
    """Regression: Gemini answers HTTP 400 'deadline 2s is too short, minimum is 10s' for tiny deadlines."""
    clock = [0.0]
    monkeypatch.setattr(gemini_client, "_now", lambda: clock[0])
    monkeypatch.setattr(gemini_client, "_sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(gemini_client, "_uniform", lambda lo, hi: lo)
    fake = install(monkeypatch, ScriptedClient([server_error(500)] * 5))

    original = fake.generate_content

    def slow_failure(**kwargs):  # the first attempt burns almost the whole budget before failing
        clock[0] += 52.0 if not fake.calls else 0.0
        return original(**kwargs)

    fake.generate_content = slow_failure
    with pytest.raises(gemini_client.GeminiRequestError) as err:
        call()
    assert len(fake.calls) == 1 and err.value.reason == "GEMINI_HTTP_500"  # 3 s left: no retry is started
    assert all(c["config"].http_options.timeout >= 10_000 for c in fake.calls)


def test_every_attempt_deadline_is_at_least_ten_seconds(monkeypatch, sleeps):
    monkeypatch.setattr(gemini_client, "TOTAL_BUDGET_SECONDS", 12.0)
    fake = install(monkeypatch, ScriptedClient([server_error(503)] * 5))
    with pytest.raises(CheckError):
        call()
    assert fake.calls and all(c["config"].http_options.timeout >= 10_000 for c in fake.calls)


def test_attempt_timeout_never_exceeds_remaining_budget(monkeypatch, sleeps):
    fake = install(monkeypatch, ScriptedClient([ok_reply()]))
    call()
    timeout = fake.calls[0]["config"].http_options.timeout
    assert timeout <= gemini_client.TOTAL_BUDGET_SECONDS * 1000


# --- fallback model --------------------------------------------------------------------------------
def test_no_fallback_model_is_configured_by_default(monkeypatch, sleeps):
    assert gemini_client.resolve_fallback_model(DEFAULT_MODEL) is None
    fake = install(monkeypatch, ScriptedClient([server_error(503)] * 3))
    with pytest.raises(CheckError):
        call()
    assert set(fake.models_used) == {DEFAULT_MODEL}


def test_configured_fallback_model_gets_one_attempt_after_the_primary_fails(monkeypatch, sleeps):
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemma-4-31b-it")
    fake = install(monkeypatch, ScriptedClient([server_error(503)] * 3 + [ok_reply()]))
    assert call() == ok_reply()
    assert fake.models_used == [DEFAULT_MODEL] * 3 + ["gemma-4-31b-it"]


def test_failing_fallback_model_ends_with_a_failure(monkeypatch, sleeps):
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemma-4-31b-it")
    fake = install(monkeypatch, ScriptedClient([server_error(500)] * 4))
    with pytest.raises(gemini_client.GeminiRequestError) as err:
        call()
    assert len(fake.calls) == 4 and err.value.attempts == 4 and err.value.model == "gemma-4-31b-it"


@pytest.mark.parametrize("bad", ["gemini-2.5-flash", DEFAULT_MODEL])
def test_non_gemma_or_identical_fallback_is_ignored(monkeypatch, sleeps, bad):
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", bad)
    assert gemini_client.resolve_fallback_model(DEFAULT_MODEL) is None
    fake = install(monkeypatch, ScriptedClient([server_error(500)] * 3))
    with pytest.raises(CheckError):
        call()
    assert set(fake.models_used) == {DEFAULT_MODEL}


def test_fallback_model_is_not_tried_after_a_non_transient_error(monkeypatch, sleeps):
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemma-4-31b-it")
    fake = install(monkeypatch, ScriptedClient([client_error(401), ok_reply()]))
    with pytest.raises(CheckError):
        call()
    assert len(fake.calls) == 1


def test_config_errors_still_make_no_call(monkeypatch, sleeps):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    fake = install(monkeypatch, ScriptedClient([ok_reply()]))
    with pytest.raises(CheckError) as err:
        call()
    assert err.value.exit_code == EXIT_CONFIG and fake.calls == []


# --- concurrency cap -------------------------------------------------------------------------------------
def test_concurrent_requests_are_capped(monkeypatch, sleeps):
    monkeypatch.setenv("GEMINI_MAX_CONCURRENCY", "2")
    fake = install(monkeypatch, ScriptedClient([ok_reply()] * 8, delay=0.05))
    results, failures = [], []

    def worker():
        try:
            results.append(call())
        except Exception as exc:  # pragma: no cover - would fail the assertions below
            failures.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert failures == [] and len(results) == 8
    assert fake.max_in_flight == 2  # eight agents asked at once, never more than two requests in flight


def test_slot_is_released_after_failures(monkeypatch, sleeps):
    monkeypatch.setenv("GEMINI_MAX_CONCURRENCY", "1")
    install(monkeypatch, ScriptedClient([server_error(500)] * 3 + [ok_reply()]))
    with pytest.raises(CheckError):
        call()
    assert call() == ok_reply()  # would hang if a failed call kept the only slot


# --- logging ------------------------------------------------------------------------------------------------
def test_logs_country_model_attempt_status_error_type_elapsed_and_never_the_key(monkeypatch, sleeps, caplog):
    leaky = errors.ServerError(500, {"error": {"code": 500, "message": f"oops key={FAKE_KEY}", "status": "INTERNAL"}})
    install(monkeypatch, ScriptedClient([leaky, ok_reply()]))
    with caplog.at_level(logging.INFO, logger="mun.ai.gemini"):
        call()
    text = caplog.text
    assert "country=India" in text and f"model={DEFAULT_MODEL}" in text and "attempt=1" in text
    assert "http_status=500" in text and "error_type=ServerError" in text and "elapsed_ms=" in text
    assert "attempt=2" in text
    assert FAKE_KEY not in text


# --- agent integration: failures are failures, not decisions -----------------------------------------------------
@pytest.mark.parametrize("country_id", ["india", "china", "united-states", "brazil", "japan"])
def test_agent_reports_failure_details_and_never_a_decision(monkeypatch, sleeps, country_id):
    install(monkeypatch, ScriptedClient([server_error(503)] * 3))
    agent = CountryAgent(COUNTRY_PROFILES[country_id])  # default llm = the real Gemini wrapper, SDK faked
    result = agent.propose("Trade dispute.", Simulation().world)
    assert not result.ok and result.decision is None
    assert result.error_code == "gemini_error" and result.failure_reason == "GEMINI_HTTP_503"
    assert result.http_status == 503 and result.attempts == 3


def test_agent_labels_log_lines_with_its_country(monkeypatch, sleeps, caplog):
    install(monkeypatch, ScriptedClient([server_error(500), ok_reply("Japan")]))
    with caplog.at_level(logging.INFO, logger="mun.ai.gemini"):
        result = CountryAgent(COUNTRY_PROFILES["japan"]).propose("Trade dispute.", Simulation().world)
    assert result.ok and "country=Japan" in caplog.text
    

# --- speed: thinking off, per-attempt cap, client reuse -------------------------------------------------------
@pytest.fixture
def fresh_thinking(monkeypatch):
    monkeypatch.setattr(gemini_client, "_thinking_rejected", set())
    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    monkeypatch.delenv("GEMINI_ATTEMPT_TIMEOUT_SECONDS", raising=False)


def test_gemma4_calls_ask_for_minimal_thinking(monkeypatch, sleeps, fresh_thinking):
    fake = install(monkeypatch, ScriptedClient([ok_reply()]))
    call()
    thinking = fake.calls[0]["config"].thinking_config
    assert thinking is not None and str(thinking.thinking_level).lower().endswith("minimal")


def test_thinking_level_can_be_overridden_or_switched_off(monkeypatch, sleeps, fresh_thinking):
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "default")
    fake = install(monkeypatch, ScriptedClient([ok_reply()]))
    call()
    assert fake.calls[0]["config"].thinking_config is None


def test_thinking_level_is_not_sent_to_other_models(fresh_thinking):
    assert gemini_client._thinking_config("gemma-3-27b-it") is None
    assert gemini_client._thinking_config(None) is None


def test_rejected_thinking_level_is_retried_once_without_it_and_remembered(monkeypatch, sleeps, fresh_thinking):
    rejection = errors.ClientError(
        400, {"error": {"code": 400, "message": "Thinking level is not supported for this model.", "status": "INVALID_ARGUMENT"}}
    )
    fake = install(monkeypatch, ScriptedClient([rejection, ok_reply(), ok_reply()]))
    assert call() == ok_reply()
    assert len(fake.calls) == 2 and sleeps == []  # repeated at once: no backoff, and not counted as a retry
    assert fake.calls[0]["config"].thinking_config is not None and fake.calls[1]["config"].thinking_config is None
    call()  # later calls do not send it again
    assert fake.calls[2]["config"].thinking_config is None


def test_unrelated_400_is_not_mistaken_for_a_thinking_rejection(monkeypatch, sleeps, fresh_thinking):
    fake = install(monkeypatch, ScriptedClient([client_error(400), ok_reply()]))
    with pytest.raises(CheckError):
        call()
    assert len(fake.calls) == 1


def test_one_attempt_never_gets_the_whole_budget(monkeypatch, sleeps, fresh_thinking):
    fake = install(monkeypatch, ScriptedClient([ok_reply()]))
    call()
    assert fake.calls[0]["config"].http_options.timeout == int(gemini_client.ATTEMPT_TIMEOUT_SECONDS * 1000)
    assert gemini_client.ATTEMPT_TIMEOUT_SECONDS < gemini_client.TOTAL_BUDGET_SECONDS / 2 + 5


def test_attempt_cap_is_configurable_but_never_below_the_gemini_minimum(monkeypatch, fresh_thinking):
    monkeypatch.setenv("GEMINI_ATTEMPT_TIMEOUT_SECONDS", "40")
    assert gemini_client._attempt_cap_seconds() == 40
    monkeypatch.setenv("GEMINI_ATTEMPT_TIMEOUT_SECONDS", "2")
    assert gemini_client._attempt_cap_seconds() == gemini_client.MIN_ATTEMPT_SECONDS
    monkeypatch.setenv("GEMINI_ATTEMPT_TIMEOUT_SECONDS", "junk")
    assert gemini_client._attempt_cap_seconds() == gemini_client.ATTEMPT_TIMEOUT_SECONDS


def test_the_sdk_client_is_reused_between_calls():
    assert gemini_client._build_client(FAKE_KEY) is gemini_client._build_client(FAKE_KEY)