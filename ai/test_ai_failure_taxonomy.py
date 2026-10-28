"""Phase 9 - AI reliability & observability.

Proves, with a FAKE Gemini SDK client (scripted replies/errors; no network, no real key):

* every way an AI request can fail has a stable `failure_type`
  (AI_REQUEST_FAILED, TIMEOUT, QUOTA_ERROR, SERVER_ERROR, MODEL_UNAVAILABLE, MALFORMED_RESPONSE, INVALID_OUTPUT);
* transient failures (500/502/503/504, timeouts) are retried a bounded number of times with backoff + jitter,
  permanent ones (429, 404, 401, 400, empty reply) are not;
* parallel agents can never put more than the configured number of requests in flight, and the wait queue is bounded;
* a malformed or invalid AI reply never becomes a decision / MUN action;
* a valid AI NO_ACTION stays distinguishable from every AI failure (in the Python results and in the HTTP bodies);
* logs carry agent/country, model, attempt, status/error type and elapsed time, and never an API key.
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("google.genai")
from fastapi.testclient import TestClient
from google.genai import errors

from ai import gemini_client
from ai.check_gemini import DEFAULT_MODEL, EXIT_API, redact
from ai.country_agent import COUNTRY_PROFILES, CountryAgent
from ai.country_turn import run_country_turn
from ai.delegates import DelegateKind, _failure_detail
from ai.fallback import request_decision
from ai.gemini_client import (
    AI_REQUEST_FAILED,
    FAILURE_TYPES,
    INVALID_OUTPUT,
    MALFORMED_RESPONSE,
    MODEL_UNAVAILABLE,
    QUOTA_ERROR,
    SERVER_ERROR,
    TIMEOUT,
    GeminiRequestError,
)
from ai.mun_core import AIResult, MunAgent, parse_json_object
from ai.country_agent import ResponseError
from backend import ai_routes
from backend.main import app
from backend.simulation import Simulation

api = TestClient(app)

FAKE_KEY = "AIzaSyFakeSecretKeyForTests0123456789"


# --- helpers ------------------------------------------------------------------------------------------------
def server_error(code=503):
    return errors.ServerError(code, {"error": {"code": code, "message": "Service unavailable.", "status": "X"}})


def client_error(code):
    return errors.ClientError(code, {"error": {"code": code, "message": "nope", "status": "X"}})


def reply(country="India", decision="NO_ACTION", target=None, **extra):
    body = {"country": country, "situation": "s", "decision": decision, "target": target, "reason": "because"}
    body.update(extra)
    return json.dumps(body)


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


class BlockingClient:
    """Holds every request open until `release` is set, so a test can keep a Gemini slot occupied."""

    def __init__(self):
        self.models = self
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(10), "test never released the blocked request"
        return SimpleNamespace(text=reply(), prompt_feedback=None, candidates=[])


@pytest.fixture
def delays(monkeypatch, tmp_path):
    """Isolated env, no real waiting, fresh limiter; returns the list of backoff delays that were requested."""
    monkeypatch.setattr(gemini_client, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    for name in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODEL", "GEMINI_MAX_CONCURRENCY", "GEMINI_MAX_QUEUE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gemini_client, "_semaphore", None)
    monkeypatch.setattr(gemini_client, "_waiting", 0)
    recorded = []
    monkeypatch.setattr(gemini_client, "_sleep", recorded.append)
    ai_routes.LLM_OVERRIDE = None
    yield recorded
    ai_routes.LLM_OVERRIDE = None


def install(monkeypatch, client):
    monkeypatch.setattr(gemini_client, "_build_client", lambda key: client)
    return client


def call():
    return gemini_client.generate_json_text("sys", "user", country="India")


def india_agent(llm=None):
    return CountryAgent(COUNTRY_PROFILES["india"], llm)


def propose(llm=None):
    return india_agent(llm).propose("A trade dispute is escalating.", Simulation().world)


def failing_llm(err):
    def llm(system_prompt, user_prompt):
        raise err

    return llm


def canned(text):
    return lambda system_prompt, user_prompt: text


# --- the taxonomy itself ----------------------------------------------------------------------------------------
def test_the_seven_failure_types_exist_with_stable_names():
    assert set(FAILURE_TYPES) == {
        "AI_REQUEST_FAILED", "TIMEOUT", "QUOTA_ERROR", "SERVER_ERROR",
        "MALFORMED_RESPONSE", "MODEL_UNAVAILABLE", "INVALID_OUTPUT",
    }


@pytest.mark.parametrize(
    "reason, status, expected",
    [
        (gemini_client.REASON_TIMEOUT, None, TIMEOUT),
        ("GEMINI_HTTP_429", 429, QUOTA_ERROR),
        ("GEMINI_HTTP_404", 404, MODEL_UNAVAILABLE),
        ("GEMINI_HTTP_500", 500, SERVER_ERROR),
        ("GEMINI_HTTP_503", 503, SERVER_ERROR),
        (gemini_client.REASON_EMPTY, None, MALFORMED_RESPONSE),
        ("GEMINI_HTTP_401", 401, AI_REQUEST_FAILED),
        ("GEMINI_HTTP_400", 400, AI_REQUEST_FAILED),
        (gemini_client.REASON_CONNECTION, None, AI_REQUEST_FAILED),
        (gemini_client.REASON_BUSY, None, AI_REQUEST_FAILED),
        (gemini_client.REASON_UNEXPECTED, None, AI_REQUEST_FAILED),
    ],
)
def test_failure_type_for_each_reason(reason, status, expected):
    assert gemini_client.failure_type_for(reason, status) == expected


# --- retries: transient failures are retried, boundedly, with backoff + jitter ---------------------------------------
@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_server_errors_are_retried_and_a_later_success_is_returned(monkeypatch, delays, code):
    fake = install(monkeypatch, ScriptedClient([server_error(code), reply()]))
    assert call() == reply()
    assert len(fake.calls) == 2 and len(delays) == 1


def test_500_then_503_then_success_uses_all_three_attempts(monkeypatch, delays):
    fake = install(monkeypatch, ScriptedClient([server_error(500), server_error(503), reply()]))
    assert call() == reply()
    assert len(fake.calls) == 3 and len(delays) == 2


def test_retry_exhaustion_is_bounded_and_typed(monkeypatch, delays):
    fake = install(monkeypatch, ScriptedClient([server_error(503)] * 10))
    with pytest.raises(GeminiRequestError) as err:
        call()
    assert len(fake.calls) == 1 + gemini_client.MAX_RETRIES  # never retried forever
    assert err.value.failure_type == SERVER_ERROR and err.value.reason == "GEMINI_HTTP_503"
    assert err.value.attempts == 3 and err.value.retryable


def test_backoff_is_exponential_with_jitter(monkeypatch, delays):
    monkeypatch.setattr(gemini_client, "_uniform", lambda a, b: b)  # worst-case jitter
    install(monkeypatch, ScriptedClient([server_error(500)] * 3))
    with pytest.raises(GeminiRequestError):
        call()
    assert delays == [1.0, 2.0]  # ceiling doubles per retry
    delays.clear()
    monkeypatch.setattr(gemini_client, "_uniform", lambda a, b: a)  # best-case jitter
    install(monkeypatch, ScriptedClient([server_error(500)] * 3))
    with pytest.raises(GeminiRequestError):
        call()
    assert delays == [0.5, 1.0]  # half the ceiling: jitter spreads retries between ceiling/2 and ceiling


def test_real_jitter_stays_inside_its_window(monkeypatch, delays):
    for _ in range(20):
        delays.clear()
        install(monkeypatch, ScriptedClient([server_error(500)] * 3))
        with pytest.raises(GeminiRequestError):
            call()
        assert 0.5 <= delays[0] <= 1.0 and 1.0 <= delays[1] <= 2.0


def test_timeouts_are_retried_then_reported_as_TIMEOUT(monkeypatch, delays):
    fake = install(monkeypatch, ScriptedClient([httpx.ReadTimeout("slow")] * 5))
    with pytest.raises(GeminiRequestError) as err:
        call()
    assert err.value.failure_type == TIMEOUT and err.value.reason == "GEMINI_TIMEOUT"
    assert len(fake.calls) == 3 and err.value.attempts == 3 and len(delays) == 2


def test_a_timeout_followed_by_success_recovers(monkeypatch, delays):
    fake = install(monkeypatch, ScriptedClient([httpx.ReadTimeout("slow"), reply()]))
    assert call() == reply()
    assert len(fake.calls) == 2


@pytest.mark.parametrize(
    "exc, expected",
    [(client_error(429), QUOTA_ERROR), (client_error(404), MODEL_UNAVAILABLE),
     (client_error(401), AI_REQUEST_FAILED), (client_error(400), AI_REQUEST_FAILED)],
)
def test_permanent_errors_are_not_retried_and_are_typed(monkeypatch, delays, exc, expected):
    fake = install(monkeypatch, ScriptedClient([exc, reply()]))
    with pytest.raises(GeminiRequestError) as err:
        call()
    assert err.value.failure_type == expected and not err.value.retryable
    assert len(fake.calls) == 1 and delays == []


def test_unretried_5xx_codes_are_still_SERVER_ERROR_but_not_retried(monkeypatch, delays):
    fake = install(monkeypatch, ScriptedClient([server_error(501), reply()]))
    with pytest.raises(GeminiRequestError) as err:
        call()
    assert err.value.failure_type == SERVER_ERROR and not err.value.retryable and len(fake.calls) == 1


def test_an_empty_reply_is_MALFORMED_RESPONSE_and_not_retried(monkeypatch, delays):
    fake = install(monkeypatch, ScriptedClient(["   ", reply()]))
    with pytest.raises(GeminiRequestError) as err:
        call()
    assert err.value.failure_type == MALFORMED_RESPONSE and err.value.exit_code != EXIT_API
    assert len(fake.calls) == 1 and delays == []


def test_connection_errors_are_retried_and_typed_as_a_generic_request_failure(monkeypatch, delays):
    fake = install(monkeypatch, ScriptedClient([httpx.ConnectError("refused")] * 3))
    with pytest.raises(GeminiRequestError) as err:
        call()
    assert err.value.failure_type == AI_REQUEST_FAILED and len(fake.calls) == 3


# --- country agent: a failure is never a decision; malformed != invalid -----------------------------------------------
@pytest.mark.parametrize(
    "exc, failure_type",
    [
        (server_error(503), SERVER_ERROR),
        (httpx.ReadTimeout("slow"), TIMEOUT),
        (client_error(429), QUOTA_ERROR),
        (client_error(404), MODEL_UNAVAILABLE),
        (client_error(401), AI_REQUEST_FAILED),
    ],
)
def test_ai_failure_has_no_decision_and_a_failure_type(monkeypatch, delays, exc, failure_type):
    install(monkeypatch, ScriptedClient([exc] * 3))
    result = propose()  # the real Gemini wrapper, SDK faked
    assert result.ok is False and result.decision is None
    assert result.error_code == "gemini_error" and result.failure_type == failure_type
    assert "NO_ACTION" not in json.dumps(result.model_dump(mode="json"))


@pytest.mark.parametrize(
    "text",
    ["not json at all", "", "   ", "[1, 2, 3]", '"just a string"', "42", "```json\n" + reply() + "\n```", "Sure! " + reply(), reply()[:-5]],
)
def test_malformed_json_fails_safely_as_MALFORMED_RESPONSE(text):
    result = propose(canned(text))
    assert result.ok is False and result.decision is None
    assert result.error_code == "invalid_response" and result.failure_type == MALFORMED_RESPONSE


@pytest.mark.parametrize(
    "text",
    [
        reply(decision="ATTACK"),  # not an allowed decision
        reply(decision="no_action"),  # wrong case is never repaired
        reply(decision="SANCTION", target="Atlantis"),  # target not in the world
        reply(decision="SANCTION", target="India"),  # own country
        reply(decision="SANCTION", target=None),  # missing target
        reply(decision="NO_ACTION", target="Brazil"),  # NO_ACTION with a target
        reply(country="China"),  # wrong country
        reply(extra_field="x"),  # unknown field
        json.dumps({"country": "India"}),  # missing fields
    ],
)
def test_well_formed_but_unacceptable_json_fails_safely_as_INVALID_OUTPUT(text):
    result = propose(canned(text))
    assert result.ok is False and result.decision is None
    assert result.error_code == "invalid_response" and result.failure_type == INVALID_OUTPUT


def test_a_valid_NO_ACTION_is_a_success_and_carries_no_failure_information():
    result = propose(canned(reply()))
    assert result.ok is True
    assert result.decision is not None and result.decision.decision.value == "NO_ACTION"
    assert result.error_code is None and result.failure_type is None and result.failure_reason is None


def test_valid_action_is_still_accepted():
    result = propose(canned(reply(decision="SANCTION", target="Brazil")))
    assert result.ok and result.decision.decision.value == "SANCTION" and result.decision.target_id == "brazil"


def test_valid_NO_ACTION_and_AI_failure_are_distinguishable_through_request_decision():
    ok = request_decision(india_agent(canned(reply())), "Trade dispute.", Simulation().world)
    assert ok.ok and ok.decision.decision.value == "NO_ACTION" and ok.failure_type is None

    err = GeminiRequestError("down", EXIT_API, reason=gemini_client.REASON_TIMEOUT, retryable=True, attempts=3)
    failed = request_decision(india_agent(failing_llm(err)), "Trade dispute.", Simulation().world)
    assert failed.failed and failed.decision is None
    assert failed.failure_type == TIMEOUT and failed.failure_reason == "GEMINI_TIMEOUT" and failed.attempts == 3


def test_a_failed_country_turn_changes_nothing_and_is_not_a_no_action():
    sim = Simulation()
    before = sim.world.model_dump(mode="json")
    err = GeminiRequestError("busy", EXIT_API, reason="GEMINI_HTTP_429", http_status=429)
    result = run_country_turn("india", "Trade dispute.", simulation=sim, llm=failing_llm(err))
    assert result.ai_failed and result.decision is None and result.action is None and not result.ok
    assert result.failure_type == QUOTA_ERROR
    assert sim.world.model_dump(mode="json") == before


def test_a_malformed_reply_in_a_country_turn_executes_nothing():
    sim = Simulation()
    before = sim.world.model_dump(mode="json")
    result = run_country_turn("india", "Trade dispute.", simulation=sim, llm=canned("{{{"))
    assert result.ai_failed and result.action is None and result.failure_type == MALFORMED_RESPONSE
    assert sim.world.model_dump(mode="json") == before


# --- conference roles (MunAgent) -----------------------------------------------------------------------------------------
def parse_ok(raw):
    return parse_json_object(raw)["value"]


def parse_rejects_content(raw):
    parse_json_object(raw)
    raise ResponseError("content is not acceptable")


def test_conference_role_failure_has_no_output_and_a_type():
    err = GeminiRequestError("down", EXIT_API, reason=gemini_client.REASON_TIMEOUT, retryable=True, attempts=3)
    result = MunAgent(failing_llm(err))._run("s", "u", parse_ok)
    assert isinstance(result, AIResult) and result.ok is False and result.output is None
    assert result.error_code == "gemini_error" and result.failure_type == TIMEOUT


def test_conference_role_malformed_reply_is_MALFORMED_RESPONSE():
    result = MunAgent(canned("not json"))._run("s", "u", parse_ok)
    assert result.ok is False and result.output is None
    assert result.error_code == "invalid_response" and result.failure_type == MALFORMED_RESPONSE


def test_conference_role_unacceptable_content_is_INVALID_OUTPUT():
    result = MunAgent(canned('{"value": 1}'))._run("s", "u", parse_rejects_content)
    assert result.ok is False and result.output is None
    assert result.error_code == "invalid_response" and result.failure_type == INVALID_OUTPUT


def test_conference_role_unexpected_exception_is_a_request_failure_without_leaking_its_text():
    result = MunAgent(failing_llm(RuntimeError(f"boom key={FAKE_KEY}")))._run("s", "u", parse_ok)
    assert result.ok is False and result.output is None and result.failure_type == AI_REQUEST_FAILED
    assert FAKE_KEY not in json.dumps(result.model_dump(mode="json"))


def test_conference_role_valid_reply_is_a_success_without_failure_information():
    result = MunAgent(canned('{"value": "fine"}'))._run("s", "u", parse_ok)
    assert result.ok and result.output == "fine" and result.failure_type is None and result.advisory is True


# --- concurrency ---------------------------------------------------------------------------------------------------------
def test_parallel_opponent_requests_never_exceed_the_in_flight_cap(monkeypatch, delays):
    monkeypatch.setenv("GEMINI_MAX_CONCURRENCY", "2")
    fake = install(monkeypatch, ScriptedClient([reply(name) for name in ["India"] * 12], delay=0.03))

    def ask(_):
        return india_agent().propose("Trade dispute.", Simulation().world)

    with ThreadPoolExecutor(max_workers=12) as pool:  # twelve "opponents" asked at once
        results = list(pool.map(ask, range(12)))
    assert all(r.ok for r in results)
    assert fake.max_in_flight <= 2 and len(fake.calls) == 12


def test_the_default_cap_is_small_and_configurable(monkeypatch, delays):
    assert gemini_client._max_concurrency() == gemini_client.DEFAULT_MAX_CONCURRENT_CALLS == 3
    monkeypatch.setenv("GEMINI_MAX_CONCURRENCY", "1")
    assert gemini_client._max_concurrency() == 1
    monkeypatch.setenv("GEMINI_MAX_CONCURRENCY", "garbage")
    assert gemini_client._max_concurrency() == 3
    monkeypatch.setenv("GEMINI_MAX_CONCURRENCY", "0")
    assert gemini_client._max_concurrency() == 1  # never zero: that would block every request forever


def test_requests_may_wait_in_a_bounded_queue_and_all_complete_in_order_of_slots(monkeypatch, delays):
    monkeypatch.setenv("GEMINI_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("GEMINI_MAX_QUEUE", "2")
    fake = install(monkeypatch, ScriptedClient([reply()] * 3, delay=0.05))
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: call(), range(3)))
    assert results == [reply()] * 3 and fake.max_in_flight == 1
    assert gemini_client._waiting == 0  # the waiting counter always returns to zero


def test_a_full_queue_fails_fast_without_calling_gemini(monkeypatch, delays):
    monkeypatch.setenv("GEMINI_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("GEMINI_MAX_QUEUE", "0")
    blocker = install(monkeypatch, BlockingClient())
    holder = threading.Thread(target=call)
    holder.start()
    try:
        assert blocker.entered.wait(5)  # the only slot is now occupied
        started = time.monotonic()
        with pytest.raises(GeminiRequestError) as err:
            call()
        assert time.monotonic() - started < 2  # failed at once, did not wait for the slot
        assert err.value.reason == gemini_client.REASON_BUSY and err.value.error_type == "QueueFull"
        assert err.value.failure_type == AI_REQUEST_FAILED and not err.value.retryable
        assert blocker.calls == 1  # Gemini was not called for the rejected request
    finally:
        blocker.release.set()
        holder.join(10)
    assert gemini_client._waiting == 0


def test_a_busy_agent_reports_a_failure_not_a_decision(monkeypatch, delays):
    monkeypatch.setenv("GEMINI_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("GEMINI_MAX_QUEUE", "0")
    blocker = install(monkeypatch, BlockingClient())
    holder = threading.Thread(target=call)
    holder.start()
    try:
        assert blocker.entered.wait(5)
        result = propose()
    finally:
        blocker.release.set()
        holder.join(10)
    assert result.ok is False and result.decision is None
    assert result.failure_reason == gemini_client.REASON_BUSY and result.failure_type == AI_REQUEST_FAILED


def test_the_slot_is_released_after_every_kind_of_failure(monkeypatch, delays):
    monkeypatch.setenv("GEMINI_MAX_CONCURRENCY", "1")
    install(monkeypatch, ScriptedClient([server_error(500)] * 3 + [httpx.ReadTimeout("x")] * 3 + ["  ", reply()]))
    for _ in range(3):
        with pytest.raises(GeminiRequestError):
            call()
    assert call() == reply()  # would hang if a failed call kept the only slot


# --- logging ----------------------------------------------------------------------------------------------------------------
def test_gemini_logs_country_model_attempt_status_error_type_failure_type_and_elapsed(monkeypatch, delays, caplog):
    install(monkeypatch, ScriptedClient([server_error(503)] * 3))
    with caplog.at_level(logging.INFO, logger="mun.ai.gemini"):
        with pytest.raises(GeminiRequestError):
            call()
    text = caplog.text
    assert "country=India" in text and f"model={DEFAULT_MODEL}" in text
    assert "attempt=1" in text and "attempt=2" in text and "attempt=3" in text
    assert "http_status=503" in text and "error_type=ServerError" in text
    assert "failure_type=SERVER_ERROR" in text and "elapsed_ms=" in text and "total_ms=" in text


def test_logs_never_contain_the_api_key_even_when_the_provider_echoes_it(monkeypatch, delays, caplog):
    leaky = errors.ServerError(
        503, {"error": {"code": 503, "message": f"bad https://x/v1?key={FAKE_KEY} and {FAKE_KEY}", "status": "X"}}
    )
    install(monkeypatch, ScriptedClient([leaky] * 3))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(GeminiRequestError) as err:
            call()
        propose()  # also through an agent (script exhausted -> unexpected error path)
    assert FAKE_KEY not in caplog.text and "AIza" not in caplog.text
    assert FAKE_KEY not in err.value.message and "AIza" not in err.value.message


def test_redact_masks_key_shaped_text_even_when_the_key_is_not_known():
    assert "AIza" not in redact("see https://x/v1?key=AIzaSyABCDEFGH123456 now", "")
    assert "secret123" not in redact("failed: api_key=secret123 rest", "")
    assert redact("plain message", "") == "plain message"


def test_rejected_output_is_logged_with_agent_model_failure_type_and_elapsed(monkeypatch, delays, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    with caplog.at_level(logging.INFO, logger="mun.ai.agent"):
        propose(canned("not json"))
        propose(canned(reply(decision="ATTACK")))
        propose(canned(reply()))
    text = caplog.text
    assert "agent=India" in text and f"model={DEFAULT_MODEL}" in text and "elapsed_ms=" in text
    assert "failure_type=MALFORMED_RESPONSE" in text and "failure_type=INVALID_OUTPUT" in text
    assert "ai decision ok" in text and "decision=NO_ACTION" in text
    assert "not json" not in text  # the model's raw output is never logged


# --- HTTP: /ai/propose ---------------------------------------------------------------------------------------------------------
def post_propose(country="india"):
    return api.post("/ai/propose", json={"country_id": country, "situation": "A trade dispute is escalating."})


@pytest.mark.parametrize(
    "script, failure_type, upstream",
    [
        ([server_error(503)] * 3, SERVER_ERROR, 503),
        ([server_error(500)] * 3, SERVER_ERROR, 500),
        ([httpx.ReadTimeout("slow")] * 3, TIMEOUT, None),
        ([client_error(429)], QUOTA_ERROR, 429),
        ([client_error(404)], MODEL_UNAVAILABLE, 404),
        ([client_error(401)], AI_REQUEST_FAILED, 401),
    ],
)
def test_propose_exposes_a_clear_failure_state_never_a_no_action(monkeypatch, delays, script, failure_type, upstream):
    install(monkeypatch, ScriptedClient(script))
    response = post_propose()
    body = response.json()
    assert response.status_code == 502
    assert body["status"] == "AI_REQUEST_FAILED" and body["failure_type"] == failure_type
    assert body["decision"] is None and body["source"] is None and body["used_fallback"] is False
    assert body["upstream_http_status"] == upstream
    assert "NO_ACTION" not in json.dumps(body)
    assert FAKE_KEY not in json.dumps(body)


def test_propose_malformed_reply_is_MALFORMED_RESPONSE(monkeypatch, delays):
    install(monkeypatch, ScriptedClient(["this is not json"]))
    body = post_propose().json()
    assert body["status"] == "AI_REQUEST_FAILED" and body["failure_type"] == MALFORMED_RESPONSE
    assert body["decision"] is None and "NO_ACTION" not in json.dumps(body)


def test_propose_invalid_output_is_INVALID_OUTPUT(monkeypatch, delays):
    install(monkeypatch, ScriptedClient([reply(decision="SANCTION", target="Atlantis")]))
    response = post_propose()
    body = response.json()
    assert response.status_code == 502
    assert body["failure_type"] == INVALID_OUTPUT and body["decision"] is None


def test_propose_valid_NO_ACTION_is_a_success_distinct_from_every_failure(monkeypatch, delays):
    install(monkeypatch, ScriptedClient([reply()]))
    response = post_propose()
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "SUCCESS" and body["source"] == "ai"
    assert body["decision"]["decision"] == "NO_ACTION" and "failure_type" not in body


def test_propose_retries_a_503_and_then_returns_the_real_decision(monkeypatch, delays):
    fake = install(monkeypatch, ScriptedClient([server_error(503), reply(decision="AID", target="Brazil")]))
    body = post_propose().json()
    assert body["status"] == "SUCCESS" and body["decision"]["decision"] == "AID" and len(fake.calls) == 2


def test_propose_failure_leaves_the_world_untouched(monkeypatch, delays):
    before = api.get("/world").json()
    install(monkeypatch, ScriptedClient([server_error(503)] * 3))
    assert post_propose().status_code == 502
    assert api.get("/world").json() == before


def test_advisor_empty_reply_is_a_malformed_response_failure(monkeypatch, delays):
    install(monkeypatch, ScriptedClient(["   "]))
    response = api.post("/ai/advisor", json={"country_id": "india", "message": "What should we do?"})
    body = response.json()
    assert response.status_code == 502 and body["failure_type"] == MALFORMED_RESPONSE and body["decision"] is None


def test_advisor_server_error_is_typed(monkeypatch, delays):
    install(monkeypatch, ScriptedClient([server_error(503)] * 3))
    body = api.post("/ai/advisor", json={"country_id": "india", "message": "What should we do?"}).json()
    assert body["status"] == "AI_REQUEST_FAILED" and body["failure_type"] == SERVER_ERROR


# --- HTTP: /ai/mun/* ---------------------------------------------------------------------------------------------------------------
FLOW = ["LOBBY", "ROLL_CALL", "OPENING_SPEECHES", "MODERATED_CAUCUS", "UNMODERATED_CAUCUS",
        "CRISIS", "DRAFTING", "VOTING", "RESULTS"]
STRATEGY = {"country": "India", "action": "NEGOTIATION", "target": "China", "vote": None, "resolution_id": None,
            "rationale": "r", "expected_outcome": "o"}


def conference_in(phase="UNMODERATED_CAUCUS"):
    cid = api.post("/conference/create", json={"name": "C", "committee": "GLOBAL_CYBERSECURITY", "topic": "Peace"}).json()["id"]
    for code in ("IN", "US", "CN"):
        api.post(f"/conference/{cid}/join", json={"name": f"D{code}", "role": "PARTICIPANT", "country": code})
    api.post(f"/conference/{cid}/start")
    for _ in range(len(FLOW)):
        if api.get(f"/conference/{cid}").json()["current_phase"] == phase:
            break
        api.post(f"/conference/{cid}/advance")
    return cid


def strategy(cid):
    return api.post("/ai/mun/strategy", json={"conference_id": cid, "country_code": "IN"})


def set_llm(fn):
    ai_routes.LLM_OVERRIDE = fn


def test_mun_role_service_failure_is_typed_and_has_no_output(delays):
    cid = conference_in()
    err = GeminiRequestError("down", EXIT_API, reason=gemini_client.REASON_TIMEOUT, retryable=True, attempts=3)
    set_llm(failing_llm(err))
    response = strategy(cid)
    body = response.json()
    assert response.status_code == 502
    assert body["status"] == "AI_REQUEST_FAILED" and body["failure_type"] == TIMEOUT
    assert body["output"] is None and body["executed"] is False and body["attempts"] == 3


def test_mun_role_malformed_reply_is_MALFORMED_RESPONSE_with_no_output(delays):
    cid = conference_in()
    set_llm(canned("<html>oops</html>"))
    body = strategy(cid).json()
    assert body["status"] == "AI_REQUEST_FAILED" and body["failure_type"] == MALFORMED_RESPONSE and body["output"] is None


def test_mun_role_invalid_output_is_INVALID_OUTPUT_with_no_output(delays):
    cid = conference_in()
    set_llm(canned(json.dumps({**STRATEGY, "action": "NUKE"})))
    body = strategy(cid).json()
    assert body["status"] == "AI_REQUEST_FAILED" and body["failure_type"] == INVALID_OUTPUT and body["output"] is None


def test_mun_role_valid_reply_is_a_success_without_failure_type(delays):
    cid = conference_in()
    set_llm(canned(json.dumps(STRATEGY)))
    response = strategy(cid)
    body = response.json()
    assert response.status_code == 200 and body["status"] == "SUCCESS" and body["output"]["action"] == "NEGOTIATION"
    assert "failure_type" not in body and body["executed"] is False


# --- delegates endpoint: failure bodies --------------------------------------------------------------------------------------------------
def test_delegate_failure_details_carry_a_failure_type():
    timeout = GeminiRequestError("t", EXIT_API, reason=gemini_client.REASON_TIMEOUT, retryable=True, attempts=3)
    assert _failure_detail(DelegateKind.SPEECH, timeout)["failure_type"] == TIMEOUT
    quota = GeminiRequestError("q", EXIT_API, reason="GEMINI_HTTP_429", http_status=429)
    assert _failure_detail(DelegateKind.SPEECH, quota)["failure_type"] == QUOTA_ERROR
    assert _failure_detail(DelegateKind.SPEECH, json.JSONDecodeError("bad", "x", 0))["failure_type"] == MALFORMED_RESPONSE
    assert _failure_detail(DelegateKind.SPEECH, ValueError("schema"))["failure_type"] == INVALID_OUTPUT
    assert _failure_detail(DelegateKind.SPEECH, RuntimeError("boom"))["failure_type"] == AI_REQUEST_FAILED
    for detail in (_failure_detail(DelegateKind.SPEECH, timeout), _failure_detail(DelegateKind.SPEECH, quota)):
        assert detail["status"] == "AI_REQUEST_FAILED"