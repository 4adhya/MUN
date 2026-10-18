"""Phase 1: prove we can reach Gemini. Gemini API key -> Python -> Gemini -> one simple reply.

Run from the repo root:
    pip install -r ai/requirements.txt
    cp .env.example .env        # then put your real key in .env (never commit it)
    python ai/check_gemini.py

The key is read from the GEMINI_API_KEY environment variable (or from a .env file in the repo
root; real environment variables win). It is never printed or logged.
Optional: GEMINI_MODEL overrides the default model if Google renames or retires it.

Exit codes: 0 reached Gemini and got a reply | 1 key missing or still the placeholder |
            2 key rejected | 3 network/API failure | 4 empty or unusable reply
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROMPT = "Reply with exactly: Gemini connection successful."
EXPECTED = "Gemini connection successful."
DEFAULT_MODEL = "gemini-3.5-flash"
TIMEOUT_MS = 90_000
PLACEHOLDER_KEY = "your_api_key_here"
REPO_ROOT = Path(__file__).resolve().parent.parent

EXIT_OK, EXIT_CONFIG, EXIT_BAD_KEY, EXIT_API, EXIT_EMPTY = 0, 1, 2, 3, 4


class CheckError(Exception):
    """A failure with a user-facing message and the process exit code to use."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


# --- configuration -----------------------------------------------------------------
def load_env_file(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, '#' comments, optional quotes.

    Existing environment variables are never overridden.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and name not in os.environ:
            os.environ[name] = value


def get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise CheckError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env in the repo root, put your key in it "
            "(or export GEMINI_API_KEY), then run this again. Get a key at https://aistudio.google.com/apikey",
            EXIT_CONFIG,
        )
    if key == PLACEHOLDER_KEY:
        raise CheckError(
            "GEMINI_API_KEY is still the placeholder from .env.example. Replace it with your real key in .env.",
            EXIT_CONFIG,
        )
    return key


# --- errors and response handling ------------------------------------------------------
def redact(text: str, key: str) -> str:
    """Remove the API key from any text before it can be shown, and keep it short."""
    if key:
        text = text.replace(key, "***")
    return text if len(text) <= 300 else text[:300] + "..."


def classify_error(exc: Exception, key: str, model: str) -> CheckError:
    """Turn any exception from the SDK or network into a clear, key-free message."""
    from google.genai import errors

    detail = redact(getattr(exc, "message", None) or str(exc), key)

    if isinstance(exc, errors.ClientError):
        code = exc.code
        if code in (401, 403) or (code == 400 and "api key" in detail.lower()):
            return CheckError(
                f"Gemini rejected the API key (HTTP {code}). Check that GEMINI_API_KEY is correct, active and "
                f"allowed to use the Gemini API. Details: {detail}",
                EXIT_BAD_KEY,
            )
        if code == 404:
            return CheckError(
                f"Model '{model}' was not found (HTTP 404). Set GEMINI_MODEL to a model your key can use. "
                f"Details: {detail}",
                EXIT_API,
            )
        if code == 429:
            return CheckError(
                f"Gemini rate limit or quota exceeded (HTTP 429). Wait a moment and retry. Details: {detail}",
                EXIT_API,
            )
        return CheckError(f"Gemini rejected the request (HTTP {code}). Details: {detail}", EXIT_API)

    if isinstance(exc, errors.ServerError):
        return CheckError(
            f"Gemini service error (HTTP {exc.code}); this is on Google's side, retry shortly. Details: {detail}",
            EXIT_API,
        )
    if isinstance(exc, errors.APIError):
        return CheckError(f"Gemini API error. Details: {detail}", EXIT_API)

    return CheckError(
        f"Could not reach the Gemini API ({type(exc).__name__}). Check your internet connection, proxy and "
        f"firewall. Details: {detail}",
        EXIT_API,
    )


def extract_text(response, key: str = "") -> str:
    """Return the reply text, or raise CheckError if there is nothing usable."""
    try:
        text = (response.text or "").strip()
    except Exception:  # the SDK can raise on malformed/blocked responses
        text = ""
    if text:
        return text

    reason = ""
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        reason = f" Prompt was blocked: {feedback.block_reason}."
    else:
        candidates = getattr(response, "candidates", None) or []
        finish = getattr(candidates[0], "finish_reason", None) if candidates else None
        if finish:
            reason = f" Finish reason: {finish}."
    raise CheckError(redact(f"Gemini returned an empty response.{reason}", key), EXIT_EMPTY)


# --- the actual call ------------------------------------------------------------------------
def ask_gemini(prompt: str, key: str, model: str) -> str:
    from google import genai
    from google.genai import types

    try:
        client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
        response = client.models.generate_content(model=model, contents=prompt)
    except Exception as exc:  # classified below; never let a raw traceback (or the key) escape
        raise classify_error(exc, key, model) from None
    return extract_text(response, key)


def main() -> int:
    load_env_file(REPO_ROOT / ".env")
    model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    key = ""
    try:
        key = get_api_key()
        print("Gemini connection test")
        print(f"  model : {model}")
        print("  key   : GEMINI_API_KEY found")
        print(f"  prompt: {PROMPT}")
        reply = ask_gemini(PROMPT, key, model)
    except CheckError as err:
        print(f"ERROR: {err.message}", file=sys.stderr)
        print("RESULT: Gemini connection NOT verified.", file=sys.stderr)
        return err.exit_code

    print("Response from Gemini:")
    print(f"  {reply}")
    if reply != EXPECTED:
        print(f"NOTE: connected, but the reply was not the exact text requested ({EXPECTED!r}).")
    print("RESULT: Gemini connection verified.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())