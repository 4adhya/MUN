"""Ask the Aurelia agent for a PROPOSAL about a situation, using the real Gemini API.

Run from the repo root:
    python ai/run_aurelia.py                                  # default scenario
    python ai/run_aurelia.py "Garvonia imposed sanctions on us."
    python ai/run_aurelia.py --show-prompt "Caldoria blocked our trade route."

Uses the backend's starting world in-process. It does NOT start the API and does NOT execute any action:
the output is a validated proposal only.

The result is labelled "AI DECISION" (Gemini's validated answer) or "FALLBACK DECISION" (Gemini failed or
answered badly, so Aurelia safely does NO_ACTION; the original problem is printed too).

Exit codes (they describe what Gemini did, even when a fallback decision was printed):
    0  Gemini answered with a valid decision                            -> AI DECISION
    1  the call to Gemini failed (missing key, quota, network, 503...)  -> FALLBACK DECISION, "gemini_error"
    2  Gemini answered, but the answer is not a valid decision          -> FALLBACK DECISION, "invalid_response"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent
sys.path[:0] = [str(AI_DIR.parent), str(AI_DIR)]

from country_agent import AureliaAgent  # noqa: E402
from fallback import decide_with_fallback  # noqa: E402
from backend.simulation import create_initial_world  # noqa: E402

DEFAULT_SITUATION = "Caldoria blocked our trade route."
EXIT_OK, EXIT_GEMINI_ERROR, EXIT_INVALID_RESPONSE = 0, 1, 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Get a proposed decision from the Aurelia agent.")
    parser.add_argument("situation", nargs="?", default=DEFAULT_SITUATION)
    parser.add_argument("--show-prompt", action="store_true", help="print the exact prompts sent to Gemini")
    args = parser.parse_args()

    world = create_initial_world()
    agent = AureliaAgent()
    if args.show_prompt:
        print("--- SYSTEM PROMPT ---\n" + agent.build_system_prompt())
        print("\n--- USER PROMPT ---\n" + agent.build_user_prompt(args.situation, world) + "\n")

    outcome = decide_with_fallback(agent, args.situation, world)
    decision_json = json.dumps(outcome.decision.model_dump(mode="json"), indent=2)

    if not outcome.is_fallback:
        print("AI DECISION (a proposal only; nothing was executed):")
        print(decision_json)
        return EXIT_OK

    if outcome.error_code == "invalid_response":
        print("INVALID RESPONSE: Gemini answered, but the answer is not a valid decision.")
        print(f"  reason: {outcome.error}")
        print(f"  raw reply: {outcome.raw_response!r}")
        code = EXIT_INVALID_RESPONSE
    else:
        print("GEMINI ERROR: the call to Gemini failed.")
        print(f"  {outcome.error}")
        code = EXIT_GEMINI_ERROR
    print()
    print("FALLBACK DECISION (a safe default, not chosen by the AI; nothing was executed):")
    print(decision_json)
    return code


if __name__ == "__main__":
    raise SystemExit(main())