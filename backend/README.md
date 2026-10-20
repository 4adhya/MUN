# MUN Simulation Backend

Backend for the MUN geopolitical simulation. It owns the world: 10 fictional countries with GDP, stability, resources,
relationships, alliances, sanctions and trade routes. Players (the React frontend, or AI agents) act through a small
REST API: **sanction**, **ally**, **send aid**. Each action changes the world by fixed rules and is logged as a diplomacy event.
State is in memory only (no database); everything is deterministic.

## Tech stack

Python 3.10+ · FastAPI · Pydantic v2 · Uvicorn · pytest (tests only)

## Folder structure

```
.gitignore
backend/
  main.py             FastAPI app, CORS, error handlers, routes (HTTP layer only)
  models.py           Pydantic models: Country, TradeRoute, DiplomacyEvent, requests/responses, WorldState
  countries.py        Initial fictional world: countries, alliances, trade routes, starting relationships
  rules.py            Tuning constants, apply_sanction / apply_alliance / apply_aid, trade recalculation, validate_world
  simulation.py       Simulation: owns the WorldState, runs actions atomically, event history, reset
  mun/                MUN domain layer (Phase 1): enums, Conference, Participant, CommitteeConfig, MUNWorldMetrics
  conftest.py         pytest fixture: every test starts from the original world
  test_*.py           Tests (see "Tests")
  requirements.txt
  README.md
```

## Setup and run

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

> The command is `uvicorn main:app --reload` (`module:attribute`); `uvicorn main --reload` fails.

| | |
|---|---|
| Backend base URL | `http://127.0.0.1:8000` |
| Frontend connects to | `http://127.0.0.1:8000` (e.g. `VITE_API_URL=http://127.0.0.1:8000`) |
| Swagger UI / OpenAPI | `http://127.0.0.1:8000/docs` · `http://127.0.0.1:8000/openapi.json` |
| Allowed browser origins | `http://localhost:5173`, `http://127.0.0.1:5173` (Vite), `:3000` (same hosts) |

CORS is an explicit allow-list, not `*`. For a deployed frontend set `CORS_ORIGINS` to a comma-separated list
(this replaces the defaults): `CORS_ORIGINS=https://my-app.vercel.app,http://localhost:5173 uvicorn main:app`

**Environment variables:** only `CORS_ORIGINS` (optional, see above). No secrets or API keys are needed or used.

State lives in memory: restarting the server or calling `POST /simulation/reset` returns the same starting world.

## API contract

All bodies are JSON. Country ids are lowercase slugs (`aurelia, brevania, caldoria, dravenia, eldoria, fyrnia, garvonia, helvaris, istoria, jorvania`);
action requests trim and lower-case ids, so `" Aurelia "` works. Unknown extra fields in action bodies are rejected (422).

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/health` | `{"status": "ok"}` |
| GET  | `/world` | Full state: turn, countries, trade routes, event history |
| GET  | `/countries/{country_id}` | One country (same shape as in `/world`) |
| POST | `/actions/sanction` | Actor sanctions target |
| POST | `/actions/alliance` | Actor and target form an alliance |
| POST | `/actions/aid` | Actor sends aid to target |
| GET  | `/events?limit=20` | Diplomacy feed, newest first (`limit` 1-100) |
| POST | `/simulation/reset` | Restore the starting world, clear events |

### GET /world

Returns everything needed to render the map. `events` is the full history, **oldest first** (use `/events` for a newest-first feed).

```json
{
  "turn": 0,
  "countries": [
    {
      "id": "eldoria", "name": "Eldoria", "gdp": 520.0, "stability": 68,
      "resources": {"food": 70, "oil": 35, "tech": 30},
      "trade_partners": ["caldoria", "helvaris"],
      "alliances": ["Meridian Pact"],
      "sanctions": [],
      "relationships": {"aurelia": 0, "caldoria": 43, "istoria": -25, "...": 0}
    }
  ],
  "trade_routes": [
    {"id": "route-04", "exporter": "caldoria", "importer": "eldoria", "resource": "oil",
     "volume": 35, "active": true, "base_volume": 35, "efficiency": 100}
  ],
  "events": []
}
```

- `gdp`: billions of fictional dollars. `stability`: 0-100. `resources`: stockpile index 0-100.
- `relationships[other_id]`: -100 (hostile) to 100 (friendly), symmetric, one entry per other country.
- `sanctions`: ids of countries that currently sanction THIS country. `trade_partners`: derived from ACTIVE routes.
- Trade route: `volume` is the CURRENT flow = `base_volume * efficiency / 100`. `efficiency` 100 = normal, 110 = allied, 0 = cut off.
  `active` is `false` while either country sanctions the other (then `volume` is 0).

### GET /countries/{country_id}

`GET /countries/eldoria` returns the single country object shown above (identical to its entry in `/world`).
Case-insensitive. Unknown id: `404 {"detail": "Country 'atlantis' not found"}`.

### POST /actions/sanction

```json
{"actor": "caldoria", "target": "eldoria"}
```

Target loses 3% GDP and 5 stability, relationship drops 25 (both directions), the actor is added to `target.sanctions`,
and every direct route between the two (both directions) becomes inactive with volume 0.
Rejected with 409 if the actor already sanctions the target (the opposite direction is a separate sanction).

### POST /actions/alliance

```json
{"actor": "garvonia", "target": "fyrnia"}
```

Creates a named alliance (`"Fyrnia-Garvonia Alliance"`, ids sorted) recorded on both countries; relationship +20, stability +2 each;
active direct routes between them run at efficiency 110. Rejected with 409 if they already share any alliance
(including a bloc such as the Northern Accord) or if either sanctions the other.

### POST /actions/aid

```json
{"actor": "aurelia", "target": "istoria", "amount": 100}
```

`amount` is 1-500 and at most 10% of the actor's GDP. Target gains 40% of the amount as GDP plus stability (+1 to +5);
actor loses 20% of the amount in GDP; relationship +1 to +15.

**Every action returns the same shape** (the updated countries, so the UI can refresh without a second call):

```json
{
  "event":  { "...see below..." },
  "actor":  { "...country after the action..." },
  "target": { "...country after the action..." }
}
```

A failed action never changes the world.

### GET /events

A plain JSON array, newest first. Each event:

```json
{
  "id": 1, "turn": 0, "type": "sanction", "actor": "caldoria", "target": "eldoria",
  "message": "Caldoria imposed sanctions on Eldoria. Eldoria's economy and stability took a hit, and 2 trade route(s) were suspended.",
  "timestamp": "2026-10-16T04:50:50.994783Z",
  "effects": {
    "target_gdp": {"before": 520.0, "after": 504.4},
    "target_stability": {"before": 68, "after": 63},
    "relationship": 18,
    "trade_routes_deactivated": ["route-04", "route-05"],
    "trade_routes": {"route-04": {"before": {"active": true, "efficiency": 100, "volume": 35},
                                  "after":  {"active": false, "efficiency": 0, "volume": 0}}}
  }
}
```

`type` is `sanction`, `alliance` or `aid`. `id` is sequential from 1 after every reset. `timestamp` is UTC ISO-8601.
Render `message`; `effects` is optional detail and its keys differ per `type`.

### POST /simulation/reset

No body. Restores countries, relationships, alliances, sanctions and trade routes, clears events, and returns the fresh world
(same shape as `GET /world`).

### For the AI layer (Person 3)

No AI-specific endpoints: an agent uses the same API as the frontend. Observe with `GET /world` and `GET /countries/{id}`,
remember with `GET /events`, act with the three `POST /actions/*` endpoints. Treat a 4xx as "that move is not legal right now"
(the `detail` text says why) and pick another.

## Errors

| Status | When | Body |
|--------|------|------|
| 400 | actor == target, or invalid aid amount (<1, >500, or >10% of actor GDP) | `{"detail": "text"}` |
| 404 | unknown country id (path or body); unknown route | `{"detail": "text"}` |
| 405 | wrong HTTP method | `{"detail": "Method Not Allowed"}` |
| 409 | duplicate sanction/alliance, or alliance while sanctioned | `{"detail": "text"}` |
| 422 | malformed body/query (missing field, wrong type, bad JSON, NaN/Infinity, `limit` out of 1-100) | `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` |
| 500 | unexpected bug; details only in the server log | `{"detail": "Internal server error"}` |

Note `detail` is a string for every error except 422, where it is a list.

## Tests

```bash
cd backend
python -m pytest -q          # full suite (88 tests); also works from the repo root: pytest -q backend
```

| File | Covers |
|------|--------|
| `test_smoke.py` | health, world shape, country lookup, consistency, CORS |
| `test_actions.py` | sanction / alliance / aid rules, errors, events, reset |
| `test_trade.py` | trade routes: sanction cuts, alliance boosts, no stacking, never negative, reset |
| `test_api_contract.py` | the HTTP contract above: shapes, status codes, CORS, `/docs`, `/openapi.json`, frontend and AI workflows |
| `test_state_safety.py` | repeated and failing actions: seeded 400-step fuzz run, failed actions change nothing, corrupting rules are blocked |

## Trade model

Each route has `base_volume` (normal level, never changes), `efficiency` (percent flowing, 0-150) and `volume`
(= `base_volume * efficiency / 100`). Rules live in `rules.py`:

- **Normal:** active, efficiency 100, volume == base_volume.
- **Sanction:** direct routes between the pair become inactive, efficiency 0, volume 0. Other routes are untouched.
- **Alliance:** active direct routes are set to efficiency 110 (a floor, never added), so it cannot stack. No routes are created.
- `recalculate_trade_effects(world)` rebuilds route state and `trade_partners` from the sanctions in the world. It is idempotent and
  `simulation.py` runs it after every action. `validate_world` checks the result.

Everything is deterministic: restarting the server always gives the same world.

## MUN domain layer (`backend/mun/`) - Phase 1

Data models only; it sits on top of the geopolitical simulation and never imports it (`backend.models` imports
`backend.mun.metrics`, not the other way round). No endpoints, phase transitions, voting or persistence yet.

| Module | Contents |
|--------|----------|
| `enums.py` | `ConferenceStatus`, `ConferencePhase`, `ParticipantRole`, `Committee` (uppercase string values, exact match) |
| `models.py` | `Conference`, `Participant` (UTC-aware timestamps, generated ids such as `conf-3fa9c1d2e4b7`) |
| `committees.py` | `CommitteeConfig`, `COMMITTEE_CONFIGS` (UNSC, GLOBAL_CYBERSECURITY), `get_committee_config()` |
| `metrics.py` | `MUNWorldMetrics`: six 0-100 metrics; `WorldState.mun_metrics` holds them |

`Country` gained optional `country_code` (ISO alpha-2, e.g. `IN`) and `flag`; `Participant.country_code` uses the same code.
`WorldState.mun_metrics` is excluded from serialization, so `GET /world` is unchanged until a later phase exposes it.