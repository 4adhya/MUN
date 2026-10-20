"""LIVE test: calls the real Gemini API. Skipped automatically when no real GEMINI_API_KEY is available.

    export GEMINI_API_KEY=...   (or put it in .env at the repo root)
    cd ai && pytest test_country_agent_live.py -s

Nothing is mocked here. The assertions check that the reply is valid and structured, NOT which decision
Gemini picks (SANCTION, ALLIANCE, AID and NO_ACTION are all acceptable).

If Gemini itself is temporarily unavailable (HTTP 5xx such as 503, rate limit/quota, network problem) the test is
SKIPPED, because that is outside our code. Anything else still FAILS: a rejected API key, an unknown model, an empty
reply, or an answer that is not a valid decision.
"""
import json
import os

import pytest

from ai.check_gemini import PLACEHOLDER_KEY, REPO_ROOT, load_env_file
from ai.country_agent import IndiaAgent, Decision
from backend.simulation import create_initial_world

load_env_file(REPO_ROOT / ".env")
_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

pytestmark = pytest.mark.skipif(
    not _KEY or _KEY == PLACEHOLDER_KEY, reason="GEMINI_API_KEY not set: live Gemini test NOT run"
)

# Messages from check_gemini.classify_error that mean "Gemini is unavailable right now" (not our bug, not a config error).
UNAVAILABLE_MARKERS = (
    "Gemini service error",  # HTTP 5xx, e.g. 503 "high demand"
    "rate limit or quota exceeded",  # HTTP 429
    "Could not reach the Gemini API",  # network / timeout
)


def test_live_india_brazil_blocked_our_trade_route():
    world = create_initial_world()
    result = IndiaAgent().propose("Brazil blocked our trade route.", world)
    print("LIVE Gemini result:", json.dumps(result.model_dump(mode="json"), indent=2))

    if not result.ok and result.error_code == "gemini_error" and any(m in result.error for m in UNAVAILABLE_MARKERS):
        pytest.skip(f"Gemini is temporarily unavailable, live test NOT run: {result.error}")

    assert result.ok, f"{result.error_code}: {result.error}"
    d = result.decision
    assert d.country == "India"
    assert d.decision in set(Decision)
    assert d.reason
    if d.decision is Decision.NO_ACTION:
        assert d.target is None
    else:
        assert d.target_id in {c.id for c in world.countries} - {"india"}