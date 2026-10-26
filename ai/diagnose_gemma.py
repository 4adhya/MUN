"""Find out which request setting makes Gemma fail or slow. Run from the repo root:  python ai/diagnose_gemma.py

Sends the same tiny request several times, adding one setting at a time (system instruction, JSON mode,
thinking level), and prints the time and result of each. The key is never printed.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.genai import types  # noqa: E402

from ai.check_gemini import TIMEOUT_MS, get_api_key, redact  # noqa: E402
from ai.gemini_client import _build_client, resolve_model  # noqa: E402

PROMPT = 'Pick one country to sanction for a trade dispute. Reply as JSON: {"decision":"SANCTION","target":"<name>"}'
SYSTEM = "You are a geopolitical simulation agent. Reply with JSON only."


def run(label, **cfg):
    key, model = get_api_key(), resolve_model()
    client = _build_client(key)
    t = time.monotonic()
    try:
        r = client.models.generate_content(
            model=model, contents=PROMPT,
            config=types.GenerateContentConfig(http_options=types.HttpOptions(timeout=30_000), **cfg),
        )
        print(f"{label:<34} OK    {time.monotonic() - t:5.1f}s  {(r.text or '').strip()[:60]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"{label:<34} FAIL  {time.monotonic() - t:5.1f}s  {redact(str(exc), key)[:110]}")


if __name__ == "__main__":
    print("model:", resolve_model())
    run("1 plain")
    run("2 + system instruction", system_instruction=SYSTEM)
    run("3 + JSON mode", system_instruction=SYSTEM, response_mime_type="application/json")
    run("4 + thinking minimal", system_instruction=SYSTEM, response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(thinking_level="minimal"))
    run("5 plain + thinking minimal", thinking_config=types.ThinkingConfig(thinking_level="minimal"))
    run("6 JSON mode only", response_mime_type="application/json")