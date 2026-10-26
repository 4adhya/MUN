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
| Gemma-via-Gemini-API connection (key from env or `.env`, never printed) | `check_gemini.py`, `gemini_client.py` |
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

## Speed and the "HTTP 504 Deadline expired" error

The AI advisor must answer in a few seconds. What makes it fast (all in `ai/gemini_client.py`):

- **Gemma 4 thinking is switched off** (`thinking_level="minimal"`). Thinking can take tens of seconds, and the
  server deadline we send (`x-server-timeout`) then expires: that is the "504 Deadline expired" message.
  Needs `google-genai>=1.51` (`pip install -U -r ai/requirements.txt`). If the API ever refuses the setting, the call is
  repeated once without it automatically.
- **Each attempt is capped** at 25 s so a stuck request leaves time for a retry.
- The SDK client is reused between calls.

Optional `.env` settings:

```
GEMINI_FALLBACK_MODEL=gemma-4-31b-it   # a second Gemma model, tried once if the primary keeps failing
GEMINI_ATTEMPT_TIMEOUT_SECONDS=25      # per-attempt cap (minimum 10)
GEMINI_THINKING_LEVEL=minimal          # "high" turns thinking back on; "default" sends nothing
```