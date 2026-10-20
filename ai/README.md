# AI layer: Day 1 (one working country agent)

Day 1 proves one thing: **one AI country can observe the current situation, make a structured decision,
safely handle failure, and affect the simulation.**

```
Current world state -> India agent -> Gemini -> CountryDecision -> validation
        -> fallback if the AI fails -> simulation action if appropriate -> updated world / event
```

## What exists

| Piece | File |
| --- | --- |
| Gemini connection (key from env or `.env`, never printed) | `check_gemini.py`, `gemini_client.py` |
| India agent, country profiles, goals and personality | `country_agent.py` |
| World-state context (GDP, stability, resources, alliances, sanctions, trade partners and routes, relationships, recent events), read from the live simulation | `country_agent.py` (`build_briefing`) |
| Structured, strictly validated decisions (`CountryDecision`) | `country_agent.py` |
| Deterministic fallback (always a valid `NO_ACTION`) | `fallback.py` |
| Simulation bridge (the backend stays the single source of truth) | `simulation_bridge.py` |
| One-turn execution, `run_country_turn(country_id, situation)` | `country_turn.py` |
| Demo CLI | `run_turn.py` |

## Supported decisions

`SANCTION`, `ALLIANCE`, `AID` (fixed deterministic amount of 10), `NO_ACTION` (never changes the world).

## Run the demo

```bash
pip install -r ai/requirements.txt
cp .env.example .env            # put your real GEMINI_API_KEY in .env (never commit it)
python ai/run_turn.py
python ai/run_turn.py "Brazil blocked India's trade route."
```

The output says **AI DECISION** (Gemini answered and the answer was valid) or **FALLBACK DECISION**
(Gemini failed or answered badly; India safely does `NO_ACTION`). If the backend rejects an action, the output
says REJECTED and that the action did NOT happen. The demo uses a fresh in-memory world, so it never touches a
running API server. The situation is given to Gemini as context only; it does not tell Gemini what to choose.

## Tests

```bash
python -m pytest ai -q
python -m pytest backend -q
python -m pytest -q
```

All Gemini replies in the tests are mocks. `ai/test_country_agent_live.py` calls the real API only when
`GEMINI_API_KEY` is set, and is skipped (not faked) otherwise or when Gemini is temporarily unavailable.

## Current limitations

- Only **one** country agent is registered in `AGENT_FACTORIES`: **India**. Multiple agents come later (`AGENT_FACTORIES` in
  `country_turn.py` is where they will be registered).
- n8n orchestration comes later.
- No autonomous loops, no turn advancement, no database.
- This is not multi-agent functionality.