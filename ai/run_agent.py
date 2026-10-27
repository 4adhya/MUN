"""Ask the India agent for a PROPOSAL about a situation, using the real Gemini API.

Run from the repo root:
    python ai/run_agent.py                                    # default scenario
    python ai/run_agent.py "China imposed sanctions on us."
    python ai/run_agent.py --show-prompt "Brazil blocked our trade route."

Uses the backend's starting world in-process. It does NOT start the API and does NOT execute any action:
the output is a validated proposal only.

The result is "AI DECISION" (Gemini's validated answer) or a failure report (Gemini failed or answered badly).
A failure prints NO decision at all: it is never turned into a NO_ACTION.

Exit codes:
    0  Gemini answered with a valid decision                            -> AI DECISION
    1  the call to Gemini failed (missing key, quota, network, 503...)  -> "gemini_error", no decision
    2  Gemini answered, but the answer is not a valid decision          -> "invalid_response", no decision
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent
sys.path[:0] = [str(AI_DIR.parent), str(AI_DIR)]

from ai.country_agent import IndiaAgent  # noqa: E402
from ai.fallback import request_decision  # noqa: E402
from backend.simulation import create_initial_world  # noqa: E402

DEFAULT_SITUATION = "Brazil blocked our trade route."
EXIT_OK, EXIT_GEMINI_ERROR, EXIT_INVALID_RESPONSE = 0, 1, 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Get a proposed decision from the India agent.")
    parser.add_argument("situation", nargs="?", default=DEFAULT_SITUATION)
    parser.add_argument("--show-prompt", action="store_true", help="print the exact prompts sent to Gemini")
    args = parser.parse_args()

    world = create_initial_world()
    agent = IndiaAgent()
    if args.show_prompt:
        print("--- SYSTEM PROMPT ---\n" + agent.build_system_prompt())
        print("\n--- USER PROMPT ---\n" + agent.build_user_prompt(args.situation, world) + "\n")

    outcome = request_decision(agent, args.situation, world)

    if outcome.ok:
        print("AI DECISION (a proposal only; nothing was executed):")
        print(json.dumps(outcome.decision.model_dump(mode="json"), indent=2))
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
    print("NO DECISION: the AI request failed, so there is nothing to propose or execute.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())