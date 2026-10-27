"""Day 1 demo: one country observes the world, Gemini decides, the backend executes. Run ONCE per command.

Run from the repo root:
    python ai/run_turn.py                                          # India, default situation
    python ai/run_turn.py "Brazil blocked India's trade route."
    python ai/run_turn.py --country india "China imposed sanctions on us."

It runs against a FRESH in-memory simulation (the starting world) inside this process, using the backend's own
action functions. The running API server's world is not touched, and nothing persists after the script ends.
Needs GEMINI_API_KEY for a real AI decision. Without Gemini the turn FAILS: no decision exists, nothing is
executed and the world is unchanged. A failure is never reported as a NO_ACTION.
The situation is given to Gemini as context only. It never tells the AI which decision to make.

Exit codes:
    0  a decision was made and handled (an executed action, or NO_ACTION chosen by the AI)
    1  Gemini unavailable (call failed)        -> AI REQUEST FAILED, no decision, world unchanged
    2  Gemini answered but invalidly           -> AI REQUEST FAILED, no decision, world unchanged
    3  the AI's decision was rejected by the backend (world unchanged)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent
sys.path[:0] = [str(AI_DIR.parent), str(AI_DIR)]

from backend.country_registry import find_world_country  # noqa: E402
from backend.simulation import Simulation  # noqa: E402
from ai.country_turn import create_agent, run_country_turn  # noqa: E402

DEFAULT_SITUATION = "Brazil blocked India's trade route."
EXIT_OK, EXIT_GEMINI_ERROR, EXIT_INVALID_RESPONSE, EXIT_REJECTED = 0, 1, 2, 3
LINE = "-" * 50


def _world_lines(country, names: dict[str, str], other_id: str | None = None) -> list[str]:
    """GDP / stability / trade partners (and the relationship with `other_id`) for one country."""
    partners = ", ".join(names[i] for i in country.trade_partners) or "none"
    lines = [f"GDP: {country.gdp:g}", f"Stability: {country.stability}", f"Trade partners: {partners}"]
    if other_id:
        lines.append(f"Relationship with {names[other_id]}: {country.relationships.get(other_id, 0):+d}")
    return lines


def _block(title: str, lines: list[str] | str) -> None:
    print(f"{title}:")
    for line in [lines] if isinstance(lines, str) else lines:
        print(line)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one AI turn for a country against the simulation.")
    parser.add_argument("situation", nargs="?", default=DEFAULT_SITUATION)
    parser.add_argument("--country", default="india", help="country id, name or code (only india has an agent for now)")
    args = parser.parse_args()

    sim = Simulation()  # fresh starting world, in this process only
    resolved = find_world_country(sim.world, args.country)  # same registry lookup as the API ("India", "IND", ...)
    if resolved is None:
        parser.error(f"unknown country id '{args.country.strip()}'")
    country_id = resolved.id
    before = {c.id: c.model_copy(deep=True) for c in sim.world.countries}
    try:
        agent = create_agent(country_id)
    except ValueError as exc:  # e.g. a country that has no agent configured yet
        parser.error(str(exc))
    names = {cid: c.name for cid, c in before.items()}
    events_before = len(sim.world.events)
    name = names[country_id]

    result = run_country_turn(country_id, args.situation, simulation=sim, agent=agent)
    d, a = result.decision, result.action

    print(LINE)
    print(f"MUN SIMULATOR — {name.upper()} AI TURN")
    print(LINE + "\n")
    print("(in-memory simulation; the API server's world is not affected)\n")
    _block("Country", name)
    _block("Situation", result.situation)
    _block("World context", _world_lines(before[country_id], names))

    if result.ai_failed:
        label = "Gemini unavailable" if result.error_code == "gemini_error" else "Gemini gave an invalid answer"
        print(f"AI REQUEST FAILED ({label}):\n{result.error}")
        if result.raw_response is not None:
            print(f"raw reply: {result.raw_response!r}")
        print()
        _block("AI Decision", "NONE. No decision was made, so there is nothing to execute (this is not a choice to do nothing).")
        _block("Execution", "NOT EXECUTED. No action was attempted.")
        _block("World", "UNCHANGED (world unchanged)")
    else:
        _block("AI Decision", "AI DECISION (chosen by Gemini, validated)")
        _block("Decision", f"decision: {d.decision.value}" + (f" -> {d.target}" if d.target else ""))
        if d.target:
            _block("Target", d.target)
        _block("Reason", d.reason)

        if a.status == "executed":
            amount = f" (amount {a.amount:g})" if a.amount is not None else ""
            _block("Execution", f"{a.action} ACCEPTED by the backend{amount}. {a.action} APPLIED.")
            print("Result: world state updated.\n")
            after_me, after_other = sim.get_country(country_id), sim.get_country(a.target)
            _block(f"World Result — {name}", _world_lines(after_me, names, a.target))
            _block(f"World Result — {names[a.target]}", _world_lines(after_other, names, country_id))
            _block("Event", f"#{a.event['id']}: {a.message}")
        elif a.status == "no_action":
            _block("Execution", "NO ACTION. The world was not modified.")
            _block("World", "UNCHANGED (world unchanged)")
        else:
            _block("Execution", f"{a.action} REJECTED by the backend (HTTP {a.http_status}): {a.message}")
            _block("World", "UNCHANGED (world unchanged). The action did NOT happen.")

    print(f"Events recorded this run: {len(sim.world.events) - events_before}")
    print(LINE)

    if result.ai_failed:
        return EXIT_GEMINI_ERROR if result.error_code == "gemini_error" else EXIT_INVALID_RESPONSE
    if not a.ok:
        return EXIT_REJECTED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())