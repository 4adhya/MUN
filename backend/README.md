# MUN Backend (Person 2: backend + simulation)

FastAPI service holding the in-memory simulation state for 10 fictional countries.
No database, no AI. Players can sanction, ally and send aid; every action is logged as a diplomacy event.
Trade routes react to sanctions and alliances (see "Trade model").

## Run

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

> Note: the command is `uvicorn main:app --reload` (`module:attribute`).
> `uvicorn main --reload` fails with "Import string must be in format <module>:<attribute>".

Server: http://127.0.0.1:8000  ·  Interactive docs: http://127.0.0.1:8000/docs

CORS allows `http://localhost:5173` and `http://127.0.0.1:5173` (Vite) plus port 3000.

## Endpoints

| Method | Path                     | Description                                   |
|--------|--------------------------|-----------------------------------------------|
| GET    | `/health`                | `{"status": "ok"}`                            |
| GET    | `/world`                 | Full state: turn, countries, trade routes (current values), events |
| GET    | `/countries/{country_id}`| One country (404 if unknown), e.g. `/countries/aurelia` |
| POST   | `/actions/sanction`      | `{"actor","target"}`: target loses GDP/stability, relationship drops, trade between the pair is cut |
| POST   | `/actions/alliance`      | `{"actor","target"}`: both record the alliance, relationship and stability rise, trade between them grows |
| POST   | `/actions/aid`           | `{"actor","target","amount"}`: target gains stability and GDP, actor GDP dips, relationship improves |
| GET    | `/events`                | Recent diplomacy events, newest first (`?limit=1..100`, default 20) |
| POST   | `/simulation/reset`      | Restore the original starting world and clear all events |

Errors: `404` unknown country, `409` duplicate sanction/alliance (or alliance while sanctioned),
`400` actor == target or invalid aid amount, `422` malformed request. A failed action never changes the world.

## Trade model

Each route in `trade_routes` has:

| Field         | Meaning |
|---------------|---------|
| `id`, `exporter`, `importer`, `resource` | unchanged |
| `base_volume` | the route's normal trade level. Never changes. |
| `efficiency`  | percent of the base level actually flowing: `100` normal, `110` allied, `0` cut off (max `150`) |
| `volume`      | CURRENT volume = `base_volume * efficiency / 100` (so `0` while cut off) |
| `active`      | `false` when either country sanctions the other |

Rules (all in `rules.py`):

- **Normal trade:** active, efficiency 100, volume == base_volume.
- **Sanction (A on B):** every direct route between A and B, in both directions, becomes inactive with efficiency 0 and volume 0.
  Other routes are untouched. `trade_partners` drops the pair.
- **Alliance (A with B):** every active direct route between A and B is set to efficiency 110. It is a floor, not an addition,
  so it can never stack. No routes are created.
- **`recalculate_trade_effects(world)`:** rebuilds route state and `trade_partners` from the sanctions in the world.
  Idempotent. `simulation.py` runs it after every action as a safety net. A cut route whose sanction no longer exists is
  restored to efficiency 100 (ready for a future "lift sanction").
- `validate_world` checks volume >= 0, efficiency 0-150, volume == base * efficiency, active flag vs sanctions,
  and `trade_partners` vs active routes.

## Files

| File            | Purpose                                                        |
|-----------------|----------------------------------------------------------------|
| `main.py`       | FastAPI app, CORS, routes (no business logic)                  |
| `models.py`     | Pydantic models: Country, TradeRoute, DiplomacyEvent, request/response models, WorldState |
| `countries.py`  | Hard-coded countries, alliances, trade routes, starting relationships |
| `simulation.py` | `Simulation`: owns the `WorldState`, runs actions atomically, event history, reset |
| `rules.py`      | Tuning constants, `apply_sanction/alliance/aid`, trade recalculation, errors, `validate_world` |
| `test_smoke.py` | Smoke tests: `python test_smoke.py` (or `pytest`)              |
| `test_actions.py` | Action/event/reset tests: `python test_actions.py` (or `pytest`) |
| `test_trade.py` | Trade-route tests: `python test_trade.py` (or `pytest`)        |
| `conftest.py`   | pytest fixture that resets the world before every test         |

## Data conventions

- Countries: `aurelia, brevania, caldoria, dravenia, eldoria, fyrnia, garvonia, helvaris, istoria, jorvania`
- `gdp`: billions of fictional dollars. `stability`: 0-100. `resources`: stockpile index 0-100.
- `relationships[other_id]`: -100 (hostile) to 100 (friendly). Symmetric at the start.
- `sanctions`: ids of countries that currently sanction THIS country (empty at start).
- `trade_partners` is derived from ACTIVE `trade_routes`, so they always agree.
- Initial relationships are computed deterministically: +25 per shared alliance,
  +3 per 10 trade volume between the pair, plus hand-tuned grudges/friendships.
- Everything is deterministic: restarting the server always gives the same world.