"""Gemini wrapper for the country agents.

Reuses the Phase 1 connection code in check_gemini.py (key loading, model choice, timeout,
key-free error messages, empty-response handling) and adds what an agent needs on top:
a system instruction, a request for JSON output, bounded retries and a concurrency cap.

    generate_json_text(system_instruction, prompt, country=None) -> raw reply text
    Raises check_gemini.CheckError (message never contains the API key) on any failure.
    Failures of the call itself are raised as GeminiRequestError (a CheckError subclass) that also
    carries a machine-readable `reason` such as "GEMINI_HTTP_500", the upstream HTTP status and the
    number of attempts, so callers can report an AI failure instead of guessing.

Reliability policy (all values are constants below, nothing is retried forever):

    * Transient failures are retried: HTTP 500 / 502 / 503 / 504, request timeouts and connection errors.
      Everything else (bad key, 400, 404, 429 quota, empty reply, unexpected errors) fails at once.
    * 1 first attempt + MAX_RETRIES retries on the configured model, with exponential backoff and jitter:
      the n-th retry waits between ceiling/2 and ceiling seconds, where ceiling = BASE_DELAY_SECONDS * 2**n
      (capped at MAX_DELAY_SECONDS), i.e. about 0.5-1 s, then 1-2 s.
    * The whole call (waiting for a slot + every attempt + every pause) is limited to TOTAL_BUDGET_SECONDS,
      which is below the frontend's 60 s timeout, so a caller always gets a clear answer.
    * A fallback model is used ONLY if GEMINI_FALLBACK_MODEL is set to a gemma-* model different from the
      primary one. It gets one attempt, after the primary model failed with a transient error. No fallback
      model is configured by default and none is invented.
    * At most GEMINI_MAX_CONCURRENCY (default 3) Gemini requests are in flight at the same time in this
      process, so several country agents asked at once queue up instead of hammering the API. The queue itself is
      bounded too (GEMINI_MAX_QUEUE, default 12 waiting attempts): beyond that a request fails at once with
      GEMINI_BUSY instead of piling up threads that would all wait for the same slots.

Failure taxonomy (Phase 9). Every failure carries a stable `failure_type` next to its detailed `reason`:

    AI_REQUEST_FAILED   the request could not be completed and no more specific type applies (bad key, bad
                        request, connection error, no free slot, unexpected error)
    TIMEOUT             the request (or every retry of it) timed out
    QUOTA_ERROR         HTTP 429: rate limit or quota (permanent for this call: not retried)
    SERVER_ERROR        HTTP 5xx from Gemini (500/502/503/504 are retried; the rest are not)
    MODEL_UNAVAILABLE   HTTP 404: the configured model does not exist for this key (not retried)
    MALFORMED_RESPONSE  Gemini answered, but not with usable JSON (empty, blocked, not JSON, not an object)
    INVALID_OUTPUT      valid JSON that does not satisfy the schema or the conference/world checks

The last two are raised by the agents when they parse a reply; the first five are produced here.

Speed policy (why the AI advisor used to be slow and end in "HTTP 504 Deadline expired"):

    * Gemma 4 can spend most of a request "thinking" before it writes a ~60-token JSON decision. These agents
      only need a quick structured pick, so every Gemma 4 call asks for thinking_level="minimal" (thinking off).
      If the API/SDK rejects that setting, the model is remembered and the call is repeated once without it.
      Override with GEMINI_THINKING_LEVEL (e.g. "high"), or set it to "default" to send nothing.
    * Each attempt is capped at ATTEMPT_TIMEOUT_SECONDS (default 25, env GEMINI_ATTEMPT_TIMEOUT_SECONDS) instead of
      being allowed to burn the whole budget. A hung/overloaded request is abandoned early, so the retry (or the
      fallback model) still has time to answer inside the budget.
    * The SDK client is created once and reused (no new TLS connection per call).
"""
from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import Optional

from ai.check_gemini import (
    DEFAULT_MODEL,
    EXIT_API,
    EXIT_CONFIG,
    EXIT_EMPTY,
    REPO_ROOT,
    TIMEOUT_MS,
    CheckError,
    classify_error,
    extract_text,
    get_api_key,
    load_env_file,
)

logger = logging.getLogger("mun.ai.gemini")

ALLOWED_MODEL_PREFIXES = ("gemma-",)  # strict: this app only ever runs Gemma models (via the Gemini API)

TEMPERATURE = 0.5  # low: we want consistent, sensible decisions rather than creative ones
JSON_MIME_TYPE = "application/json"

# --- retry / concurrency policy -------------------------------------------------------------
MAX_RETRIES = 2  # 1 first attempt + 2 retries = 3 attempts on the primary model, never more (delays ~1 s, then ~2 s)
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 8.0
TOTAL_BUDGET_SECONDS = 35.0  # bound slow upstream requests; frontend timeout is 70 s
MIN_ATTEMPT_SECONDS = 10.0  # the Gemini API rejects any request deadline under 10 s (HTTP 400), so never start an
#                            attempt with less than this left in the budget
ATTEMPT_TIMEOUT_SECONDS = 15.0  # fail stalled attempts earlier
ATTEMPT_TIMEOUT_ENV = "GEMINI_ATTEMPT_TIMEOUT_SECONDS"
THINKING_LEVEL_ENV = "GEMINI_THINKING_LEVEL"
DEFAULT_THINKING_LEVEL = "minimal"  # Gemma 4: "minimal" = thinking off, "high" = thinking on (low/medium are rejected)
DEFAULT_MAX_CONCURRENT_CALLS = 3  # council uses two slots, leaving one for the advisor
RETRYABLE_HTTP_STATUSES = frozenset({500, 502, 503, 504})
FALLBACK_MODEL_ENV = "GEMINI_FALLBACK_MODEL"
MAX_CONCURRENCY_ENV = "GEMINI_MAX_CONCURRENCY"
DEFAULT_MAX_QUEUED_CALLS = 12  # attempts allowed to WAIT for a slot; more than this fail fast instead of piling up
MAX_QUEUE_ENV = "GEMINI_MAX_QUEUE"

# --- failure types (stable, machine-readable; see the taxonomy in the module docstring) ----------------------------
AI_REQUEST_FAILED = "AI_REQUEST_FAILED"
TIMEOUT = "TIMEOUT"
QUOTA_ERROR = "QUOTA_ERROR"
SERVER_ERROR = "SERVER_ERROR"
MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
INVALID_OUTPUT = "INVALID_OUTPUT"
FAILURE_TYPES = (
    AI_REQUEST_FAILED, TIMEOUT, QUOTA_ERROR, SERVER_ERROR, MALFORMED_RESPONSE, MODEL_UNAVAILABLE, INVALID_OUTPUT,
)

# --- failure reasons (stable, machine-readable) ------------------------------------------------
REASON_CONFIG = "AI_CONFIGURATION_ERROR"
REASON_TIMEOUT = "GEMINI_TIMEOUT"
REASON_CONNECTION = "GEMINI_CONNECTION_ERROR"
REASON_EMPTY = "GEMINI_EMPTY_RESPONSE"
REASON_BUSY = "GEMINI_BUSY"
REASON_API_ERROR = "GEMINI_API_ERROR"
REASON_UNEXPECTED = "GEMINI_UNEXPECTED_ERROR"
REASON_GENERIC = "GEMINI_ERROR"
# HTTP failures use f"GEMINI_HTTP_{status}", e.g. "GEMINI_HTTP_500".

# Indirection so tests can run instantly and deterministically.
_sleep = time.sleep
_now = time.monotonic
_uniform = random.uniform


def failure_type_for(reason: Optional[str], http_status: Optional[int]) -> str:
    """The failure type for a failed Gemini call, from its detailed reason and upstream HTTP status."""
    if reason == REASON_TIMEOUT:
        return TIMEOUT
    if http_status == 429:
        return QUOTA_ERROR
    if http_status == 404:
        return MODEL_UNAVAILABLE
    if http_status is not None and http_status >= 500:
        return SERVER_ERROR
    if reason == REASON_EMPTY:
        return MALFORMED_RESPONSE
    return AI_REQUEST_FAILED


class GeminiRequestError(CheckError):
    """The call to Gemini failed. Still a CheckError (key-free message, exit code), plus structured details."""

    def __init__(
        self,
        message: str,
        exit_code: int,
        *,
        reason: str,
        http_status: Optional[int] = None,
        retryable: bool = False,
        attempts: int = 1,
        model: Optional[str] = None,
        error_type: Optional[str] = None,
        failure_type: Optional[str] = None,
    ) -> None:
        super().__init__(message, exit_code)
        self.failure_type = failure_type or failure_type_for(reason, http_status)
        self.reason = reason
        self.http_status = http_status
        self.retryable = retryable
        self.attempts = attempts
        self.model = model
        self.error_type = error_type


# --- SDK objects ----------------------------------------------------------------------------------
_clients: dict = {}
_clients_lock = threading.Lock()
_thinking_rejected: set = set()  # models whose API refused a thinking level: we stop sending it to them


def _build_client(key: str):
    """One SDK client per API key, reused for every call (a new client per call re-did the TLS handshake)."""
    from google import genai
    from google.genai import types

    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
            _clients[key] = client
        return client


def _attempt_cap_seconds() -> float:
    raw = os.environ.get(ATTEMPT_TIMEOUT_ENV, "").strip()
    try:
        value = float(raw) if raw else ATTEMPT_TIMEOUT_SECONDS
    except ValueError:
        value = ATTEMPT_TIMEOUT_SECONDS
    return max(MIN_ATTEMPT_SECONDS, value)  # Gemini rejects deadlines under 10 s


def _thinking_config(model: Optional[str]):
    """ThinkingConfig for a Gemma 4 call, or None to send nothing (other models, opted out, or already rejected)."""
    if not model or not model.lower().startswith("gemma-4") or model in _thinking_rejected:
        return None
    level = (os.environ.get(THINKING_LEVEL_ENV, "").strip() or DEFAULT_THINKING_LEVEL).lower()
    if level in ("default", "none", "off"):
        return None
    from google.genai import types

    if "thinking_level" not in types.ThinkingConfig.model_fields:  # older google-genai: upgrade to use this
        return None
    try:
        return types.ThinkingConfig(thinking_level=level)
    except Exception:  # unknown level name: send nothing rather than fail the call
        logger.warning("Ignoring %s=%r (not a valid thinking level)", THINKING_LEVEL_ENV, level)
        return None


def _build_config(system_instruction: str, timeout_ms: Optional[int] = None, json_mode: bool = True,
                  model: Optional[str] = None, use_thinking: bool = True):
    from google.genai import types

    http_options = types.HttpOptions(timeout=timeout_ms) if timeout_ms else None  # per-request timeout override
    return types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type=JSON_MIME_TYPE if json_mode else None,  # None: plain-text reply (advisor chat)
        temperature=0.5,
        max_output_tokens=2048 if json_mode else 1024,  # leave room for complete JSON and advisor replies
        thinking_config=_thinking_config(model) if use_thinking else None,  # thinking off for Gemma 4: it was the main source of delay
        http_options=http_options,
    )


def _is_thinking_rejection(exc: Exception, model: str) -> bool:
    """True if the API refused the thinking setting we sent (HTTP 400 mentioning thinking)."""
    from google.genai import errors

    return (
        isinstance(exc, errors.ClientError)
        and getattr(exc, "code", None) == 400
        and "thinking" in str(exc).lower()
        and _thinking_config(model) is not None
    )


def resolve_model() -> str:
    """The model every agent call uses: GEMINI_MODEL if set, else DEFAULT_MODEL (a Gemma model).

    Refuses anything that is not a Gemma model (e.g. a leftover Gemini Flash value in .env), so the
    demo can never quietly run on another model. Raises CheckError (exit code EXIT_CONFIG).
    """
    load_env_file(REPO_ROOT / ".env")  # real environment variables still win
    model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    if not model.lower().startswith(ALLOWED_MODEL_PREFIXES):
        raise CheckError(
            f"GEMINI_MODEL '{model}' is not a Gemma model. This app only runs gemma-* models; "
            "set GEMINI_MODEL to a Gemma model available to your API key.",
            EXIT_CONFIG,
        )
    return model


def resolve_fallback_model(primary: str) -> Optional[str]:
    """The optional second model, or None. Only GEMINI_FALLBACK_MODEL can enable it; nothing is invented.

    Ignored (with a warning) if it is not a gemma-* model or equals the primary model.
    """
    load_env_file(REPO_ROOT / ".env")
    model = os.environ.get(FALLBACK_MODEL_ENV, "").strip()
    if not model or model == primary:
        return None
    if not model.lower().startswith(ALLOWED_MODEL_PREFIXES):
        logger.warning("Ignoring %s: it is not a Gemma model", FALLBACK_MODEL_ENV)
        return None
    return model


# --- concurrency cap -----------------------------------------------------------------------------------
_semaphore: Optional[threading.BoundedSemaphore] = None
_semaphore_lock = threading.Lock()


def _max_concurrency() -> int:
    raw = os.environ.get(MAX_CONCURRENCY_ENV, "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_CONCURRENT_CALLS
    except ValueError:
        value = DEFAULT_MAX_CONCURRENT_CALLS
    return max(1, value)


_waiting = 0  # attempts currently waiting for a slot
_waiting_lock = threading.Lock()


def _max_queue() -> int:
    raw = os.environ.get(MAX_QUEUE_ENV, "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_QUEUED_CALLS
    except ValueError:
        value = DEFAULT_MAX_QUEUED_CALLS
    return max(0, value)


def _acquire_slot(semaphore: threading.BoundedSemaphore, timeout: float) -> str:
    """Take a Gemini slot. Returns "ok", "timeout" (no slot in time) or "full" (too many are already waiting)."""
    global _waiting
    if semaphore.acquire(blocking=False):
        return "ok"
    with _waiting_lock:
        if _waiting >= _max_queue():
            return "full"
        _waiting += 1
    try:
        return "ok" if semaphore.acquire(timeout=timeout) else "timeout"
    finally:
        with _waiting_lock:
            _waiting -= 1


def _get_semaphore() -> threading.BoundedSemaphore:
    """One process-wide limit shared by every country agent (created on first use)."""
    global _semaphore
    with _semaphore_lock:
        if _semaphore is None:
            _semaphore = threading.BoundedSemaphore(_max_concurrency())
        return _semaphore


# --- failure classification and backoff ------------------------------------------------------------------
def _classify_attempt(exc: Exception, key: str, model: str) -> GeminiRequestError:
    """Turn one failed attempt into a GeminiRequestError: reason, HTTP status, retryable or not. Key-free."""
    from google.genai import errors

    try:
        import httpx
    except ImportError:  # httpx ships with google-genai; this is only a guard
        httpx = None

    base = classify_error(exc, key, model)  # redacted, human-readable message + exit code
    status: Optional[int] = None
    retryable = False

    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        status = code if isinstance(code, int) else None
        reason = f"GEMINI_HTTP_{status}" if status is not None else REASON_API_ERROR
        retryable = isinstance(exc, errors.ServerError) and status in RETRYABLE_HTTP_STATUSES
    elif isinstance(exc, TimeoutError) or (httpx is not None and isinstance(exc, httpx.TimeoutException)):
        reason, retryable = REASON_TIMEOUT, True
    elif isinstance(exc, ConnectionError) or (httpx is not None and isinstance(exc, httpx.TransportError)):
        reason, retryable = REASON_CONNECTION, True
    else:
        reason = REASON_UNEXPECTED

    return GeminiRequestError(
        base.message,
        base.exit_code,
        reason=reason,
        http_status=status,
        retryable=retryable,
        model=model,
        error_type=type(exc).__name__,
    )


def _backoff_delay(retry_index: int) -> float:
    """Exponential backoff with jitter: retry 0 -> 0.5-1 s, retry 1 -> 1-2 s, ... capped at MAX_DELAY_SECONDS."""
    ceiling = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * (2**retry_index))
    return ceiling / 2 + _uniform(0, ceiling / 2)


def _finalize(err: GeminiRequestError, attempts: int) -> GeminiRequestError:
    message = err.message if attempts <= 1 else f"{err.message} (gave up after {attempts} attempts)"
    return GeminiRequestError(
        message,
        err.exit_code,
        reason=err.reason,
        http_status=err.http_status,
        retryable=err.retryable,
        attempts=attempts,
        model=err.model,
        error_type=err.error_type,
        failure_type=err.failure_type,
    )


def failure_fields(err: CheckError) -> dict:
    """The machine-readable failure details of any Gemini-call error, for AgentResult / AIResult / AdvisorResult.

    Works for a GeminiRequestError and for a plain CheckError (missing key, non-Gemma model): the latter has no
    reason/type of its own, so it is reported as a configuration problem.
    """
    reason = getattr(err, "reason", None) or (REASON_CONFIG if err.exit_code == EXIT_CONFIG else REASON_GENERIC)
    return {
        "failure_reason": reason,
        "failure_type": getattr(err, "failure_type", None) or AI_REQUEST_FAILED,
        "http_status": getattr(err, "http_status", None),
        "attempts": getattr(err, "attempts", None),
    }


def safe_model_name() -> Optional[str]:
    """The configured model for log lines and error bodies, or None if the configuration is invalid."""
    try:
        return resolve_model()
    except Exception:
        return None


# --- the call ----------------------------------------------------------------------------------------------
def generate_json_text(system_instruction: str, prompt: str, country: Optional[str] = None) -> str:
    """One logical Gemma call (JSON mode) with bounded retries. Returns the raw reply text.

    Parsing/validation stays in the agent. `country` is only used to label log lines.
    """
    return _generate(system_instruction, prompt, country, json_mode=True)


def generate_text(system_instruction: str, prompt: str, country: Optional[str] = None) -> str:
    """Same reliability policy as generate_json_text, but a plain-text reply (used by the advisor chat)."""
    return _generate(system_instruction, prompt, country, json_mode=False)


def _generate(system_instruction: str, prompt: str, country: Optional[str], json_mode: bool) -> str:
    primary = resolve_model()
    key = get_api_key()  # raises CheckError if missing or still the placeholder
    fallback = resolve_fallback_model(primary)

    try:
        client = _build_client(key)
    except ImportError:
        raise CheckError(
            "The google-genai package is not installed. Run: pip install -r ai/requirements.txt",
            EXIT_CONFIG,
        ) from None

    plan = [(primary, 1 + MAX_RETRIES)]
    if fallback:
        plan.append((fallback, 1))  # one attempt, only after the primary model failed with a transient error

    label = country or "-"
    semaphore = _get_semaphore()
    started = _now()
    attempt = 0
    last_error: Optional[GeminiRequestError] = None
    drop_thinking = False  # set after a failed attempt that carried a thinking level: later attempts go without it

    for model, allowed in plan:
        if last_error is not None and not last_error.retryable:
            break  # a non-transient failure (bad key, quota, ...) is not fixed by another model
        for try_index in range(allowed):
            remaining = TOTAL_BUDGET_SECONDS - (_now() - started)
            if remaining < MIN_ATTEMPT_SECONDS:
                break

            attempt += 1
            slot = _acquire_slot(semaphore, remaining)
            if slot != "ok":
                queue_error = "QueueFull" if slot == "full" else "QueueTimeout"
                last_error = GeminiRequestError(
                    "The AI is handling too many requests right now; try again shortly."
                    if slot == "full"
                    else "Too many AI requests are in progress; no Gemini slot became free in time.",
                    EXIT_API,
                    reason=REASON_BUSY,
                    retryable=False,
                    model=model,
                    error_type=queue_error,
                )
                logger.warning(
                    "gemini call failed country=%s model=%s attempt=%d http_status=- error_type=%s "
                    "reason=%s failure_type=%s elapsed_ms=%d",
                    label, model, attempt, queue_error, REASON_BUSY, last_error.failure_type,
                    int((_now() - started) * 1000),
                )
                break

            attempt_started = _now()
            try:
                remaining = TOTAL_BUDGET_SECONDS - (attempt_started - started)  # slot wait used part of the budget
                if remaining < MIN_ATTEMPT_SECONDS:
                    last_error = GeminiRequestError(
                        "The AI request ran out of time while waiting for a free Gemini slot.",
                        EXIT_API,
                        reason=REASON_BUSY,
                        retryable=False,
                        model=model,
                        error_type="QueueTimeout",
                    )
                    break
                # >= 10 s: guaranteed by the check above. Capped per attempt so one stuck call cannot eat the budget.
                timeout_ms = int(min(TIMEOUT_MS, remaining * 1000, _attempt_cap_seconds() * 1000))
                try:
                    # json_mode decides response_mime_type: True -> "application/json" (agent decisions),
                    # False -> plain text (advisor chat).
                    config = _build_config(system_instruction, timeout_ms, json_mode, model, not drop_thinking)
                    try:
                        response = client.models.generate_content(model=model, contents=prompt, config=config)
                    except Exception as exc:
                        if not _is_thinking_rejection(exc, model):
                            raise
                        # This model/API refuses the thinking setting: remember that and repeat the call without it.
                        _thinking_rejected.add(model)
                        logger.warning("gemini model=%s rejected the thinking level; retrying without it", model)
                        config = _build_config(system_instruction, timeout_ms, json_mode, model)
                        response = client.models.generate_content(model=model, contents=prompt, config=config)
                    text = extract_text(response, key)
                except GeminiRequestError:
                    raise
                except CheckError as exc:  # extract_text: empty / blocked reply (not a transport problem)
                    raise GeminiRequestError(
                        exc.message, EXIT_EMPTY, reason=REASON_EMPTY, model=model, error_type="EmptyResponse"
                    ) from None
                except Exception as exc:  # classified; never let a raw traceback (or the key) escape
                    raise _classify_attempt(exc, key, model) from None
            except GeminiRequestError as err:
                last_error = err
                if err.retryable and not drop_thinking and _thinking_config(model) is not None:
                    drop_thinking = True  # a 5xx/timeout may be caused by the thinking setting: retry without it
                elapsed_ms = int((_now() - attempt_started) * 1000)
                logger.warning(
                    "gemini call failed country=%s model=%s attempt=%d http_status=%s error_type=%s reason=%s "
                    "failure_type=%s retryable=%s elapsed_ms=%d",
                    label, model, attempt, err.http_status if err.http_status is not None else "-",
                    err.error_type or "-", err.reason, err.failure_type, err.retryable, elapsed_ms,
                )
            else:
                logger.info(
                    "gemini call ok country=%s model=%s attempt=%d elapsed_ms=%d total_ms=%d",
                    label, model, attempt, int((_now() - attempt_started) * 1000), int((_now() - started) * 1000),
                )
                return text
            finally:
                semaphore.release()

            if not last_error.retryable:
                break
            if try_index + 1 < allowed:  # another attempt on the same model: back off first
                delay = _backoff_delay(try_index)
                if TOTAL_BUDGET_SECONDS - (_now() - started) - delay < MIN_ATTEMPT_SECONDS:
                    break  # no time left for a useful retry
                logger.info("gemini retry country=%s model=%s next_attempt=%d delay_s=%.2f", label, model, attempt + 1, delay)
                _sleep(delay)

    if last_error is None:  # the budget was gone before the first attempt (cannot normally happen)
        last_error = GeminiRequestError(
            "The AI request ran out of time.", EXIT_API, reason=REASON_BUSY, model=primary, error_type="Budget"
        )
    final = _finalize(last_error, attempt)
    logger.error(
        "gemini request failed country=%s model=%s attempts=%d reason=%s failure_type=%s http_status=%s total_ms=%d",
        label, final.model, attempt, final.reason, final.failure_type,
        final.http_status if final.http_status is not None else "-", int((_now() - started) * 1000),
    )
    raise final