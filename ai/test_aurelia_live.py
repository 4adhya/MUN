"""LIVE test: calls the real Gemini API. Skipped automatically when no real GEMINI_API_KEY is available.

    export GEMINI_API_KEY=...   (or put it in .env at the repo root)
    cd ai && pytest test_aurelia_live.py -s

Nothing is mocked here. The assertions check that the reply is valid and structured, NOT which decision
Gemini picks (SANCTION, ALLIANCE, AID and NO_ACTION are all acceptable).
"""
import json
import os

import pytest

from check_gemini import PLACEHOLDER_KEY, REPO_ROOT, load_env_file
from country_agent import AureliaAgent, Decision
from simulation import create_initial_world

load_env_file(REPO_ROOT / ".env")
_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

pytestmark = pytest.mark.skipif(
    not _KEY or _KEY == PLACEHOLDER_KEY, reason="GEMINI_API_KEY not set: live Gemini test NOT run"
)


def test_live_aurelia_caldoria_blocked_our_trade_route():
    world = create_initial_world()
    result = AureliaAgent().propose("Caldoria blocked our trade route.", world)
    print("LIVE Gemini result:", json.dumps(result.model_dump(mode="json"), indent=2))

    assert result.ok, f"{result.error_code}: {result.error}"
    d = result.decision
    assert d.country == "Aurelia"
    assert d.decision in set(Decision)
    assert d.reason
    if d.decision is Decision.NO_ACTION:
        assert d.target is None
    else:
        assert d.target_id in {c.id for c in world.countries} - {"aurelia"}