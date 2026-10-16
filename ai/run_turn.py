"""Manual end-to-end demo: one country observes the world, Gemini decides, the backend executes.

Run from the repo root:
    python ai/run_turn.py                                          # Aurelia, default situation
    python ai/run_turn.py "Caldoria blocked Aurelia's trade."
    python ai/run_turn.py --country aurelia "Garvonia imposed sanctions on us."

It runs against a FRESH in-memory simulation (the starting world) inside this process, using the backend's own
action functions. The running API server's world is not touched, and nothing persists after the script ends.
Needs GEMINI_API_KEY for a real AI decision; without Gemini you see the Phase 4 fallback (NO_ACTION, world unchanged).

Exit codes:
    0  a decision was made and handled (an executed action, or NO_ACTION chosen by the AI)
    1  Gemini unavailable (call failed)        -> FALLBACK NO_ACTION, world unchanged
    2  Gemini answered but invalidly           -> FALLBACK NO_ACTION, world unchanged
    3  the AI's decision was rejected by the backend (world unchanged)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent
sys.path[:0] = [str(AI_DIR.parent), str(AI_DIR)]

from backend.simulation import Simulation  # noqa: E402
from country_turn import create_agent, run_country_turn  # noqa: E402

DEFAULT_SITUATION = "Caldoria blocked Aurelia's trade."
EXIT_OK, EXIT_GEMINI_ERROR, EXIT_INVALID_RESPONSE, EXIT_REJECTED = 0, 1, 2, 3


def _state_line(label: str, before, after, other_id: str | None) -> str:
    line = f"  {label}: GDP {before.gdp:g} -> {after.gdp:g}, stability {before.stability} -> {after.stability}"
    if other_id:
        line += f", relationship with {other_id} {before.relationships.get(other_id, 0)} -> {after.relationships.get(other_id, 0)}"
    return line


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one AI turn for a country against the simulation.")
    parser.add_argument("situation", nargs="?", default=DEFAULT_SITUATION)
    parser.add_argument("--country", default="aurelia", help="country id (only aurelia has an agent for now)")
    args = parser.parse_args()

    sim = Simulation()  # fresh starting world, in this process only
    country_id = args.country.strip().lower()
    before = {c.id: c.model_copy(deep=True) for c in sim.world.countries}
    if country_id not in before:
        parser.error(f"unknown country id '{country_id}'")
    try:
        agent = create_agent(country_id)
    except ValueError as exc:  # e.g. a country that has no agent configured yet
        parser.error(str(exc))
    events_before = len(sim.world.events)

    result = run_country_turn(country_id, args.situation, simulation=sim, agent=agent)
    name = before[country_id].name
    d, a = result.decision, result.action

    print(f"=== {name}: one AI turn (in-memory simulation; the API server's world is not affected) ===")
    print(f"Situation:\n  {result.situation}\n")

    if result.used_fallback:
        label = "Gemini unavailable" if result.fallback_error_code == "gemini_error" else "Gemini gave an invalid answer"
        print(f"AI unavailable -> fallback ({label}):\n  {result.fallback_error}")
        if result.raw_response is not None:
            print(f"  raw reply: {result.raw_response!r}")
        print("\nFALLBACK DECISION (safe default, not chosen by the AI):")
    else:
        print("AI DECISION:")
    print(f"  decision: {d.decision.value}" + (f" -> {d.target}" if d.target else ""))
    print(f"  reason:   {d.reason}\n")

    if a.status == "executed":
        amount = f" (amount {a.amount:g})" if a.amount is not None else ""
        print(f"Execution: {a.action} ACCEPTED by the backend{amount}.")
        print(f"  event #{a.event['id']}: {a.message}")
        print("Result: world state updated.")
        print(_state_line(name, before[country_id], sim.get_country(country_id), a.target))
        print(_state_line(before[a.target].name, before[a.target], sim.get_country(a.target), country_id))
    elif a.status == "no_action":
        print("Execution: NO ACTION. The world was not modified.")
        print("Result: world unchanged.")
    else:
        print(f"Execution: {a.action} REJECTED by the backend (HTTP {a.http_status}): {a.message}")
        print("Result: world unchanged. The action did NOT happen.")
    print(f"\nEvents recorded this run: {len(sim.world.events) - events_before}")

    if not a.ok:
        return EXIT_REJECTED
    if result.used_fallback:
        return EXIT_GEMINI_ERROR if result.fallback_error_code == "gemini_error" else EXIT_INVALID_RESPONSE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())