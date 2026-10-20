"""Gemini wrapper for the country agents.

Reuses the Phase 1 connection code in check_gemini.py (key loading, model choice, timeout,
key-free error messages, empty-response handling) and only adds what an agent needs on top:
a system instruction and a request for JSON output.

    generate_json_text(system_instruction, prompt) -> raw reply text
    Raises check_gemini.CheckError (message never contains the API key) on any failure.
"""
from __future__ import annotations

import os

from ai.check_gemini import (
    DEFAULT_MODEL,
    EXIT_CONFIG,
    REPO_ROOT,
    TIMEOUT_MS,
    CheckError,
    classify_error,
    extract_text,
    get_api_key,
    load_env_file,
)

GEMMA_PREFIX = "gemma-"  # the hackathon requires a Gemma model; anything else is refused, never silently used

TEMPERATURE = 0.5  # low: we want consistent, sensible decisions rather than creative ones
JSON_MIME_TYPE = "application/json"


def _build_client(key: str):
    from google import genai
    from google.genai import types

    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))




def _build_config(system_instruction: str):
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        temperature=0.5,
        max_output_tokens=2048,  # was 400: Gemma hit MAX_TOKENS before finishing the JSON,
    )




def resolve_model() -> str:
    """The model every agent call uses: GEMINI_MODEL if set, else DEFAULT_MODEL (a Gemma model).

    Refuses anything that is not a Gemma model (e.g. a leftover Gemini Flash value in .env), so the
    demo can never quietly run on another model. Raises CheckError (exit code EXIT_CONFIG).
    """
    load_env_file(REPO_ROOT / ".env")  # real environment variables still win
    model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    if not model.lower().startswith(GEMMA_PREFIX):
        raise CheckError(
            f"GEMINI_MODEL is '{model}', which is not a Gemma model. This project must use Gemma through the "
            f"Gemini API (default: {DEFAULT_MODEL}). Remove GEMINI_MODEL from your environment/.env or set it "
            f"to a gemma-* model.",
            EXIT_CONFIG,
        )
    return model


def generate_json_text(system_instruction: str, prompt: str) -> str:
    """One Gemma call through the Gemini API. Returns the raw reply text (parsing/validation is in the agent)."""
    model = resolve_model()
    key = get_api_key()  # raises CheckError if missing or still the placeholder

    try:
        client = _build_client(key)
        config = _build_config(system_instruction)
    except ImportError:
        raise CheckError(
            "The google-genai package is not installed. Run: pip install -r ai/requirements.txt",
            EXIT_CONFIG,
        ) from None

    try:
        response = client.models.generate_content(model=model, contents=prompt, config=config)
    except Exception as exc:  # classified; never let a raw traceback (or the key) escape
        raise classify_error(exc, key, model) from None
    return extract_text(response, key)