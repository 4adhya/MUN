"""Ask the Aurelia agent for a PROPOSAL about a situation, using the real Gemini API.

Run from the repo root:
    python ai/run_aurelia.py                                  # default scenario
    python ai/run_aurelia.py "Garvonia imposed sanctions on us."
    python ai/run_aurelia.py --show-prompt "Caldoria blocked our trade route."

Uses the backend's starting world in-process. It does NOT start the API and does NOT execute any action:
the output is a validated proposal only.

Exit codes:
    0  Gemini answered with a valid decision
    1  the call to Gemini failed (missing key, quota, network, 503...)  -> error_code "gemini_error"
    2  Gemini answered, but the answer is not a valid decision          -> error_code "invalid_response"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent
sys.path[:0] = [str(AI_DIR.parent / "backend"), str(AI_DIR)]

from country_agent import AureliaAgent  # noqa: E402
from simulation import create_initial_world  # noqa: E402

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

    result = agent.propose(args.situation, world)

    if result.ok:
        print("VALIDATED DECISION (a proposal only; nothing was executed):")
        print(json.dumps(result.decision.model_dump(mode="json"), indent=2))
        return EXIT_OK

    if result.error_code == "invalid_response":
        print("INVALID RESPONSE: Gemini answered, but the answer is not a valid decision.")
        print(f"  reason: {result.error}")
        print(f"  raw reply: {result.raw_response!r}")
        return EXIT_INVALID_RESPONSE

    print("GEMINI ERROR: the call to Gemini failed.")
    print(f"  {result.error}")
    return EXIT_GEMINI_ERROR


if __name__ == "__main__":
    raise SystemExit(main())