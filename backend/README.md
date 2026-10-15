# MUN Backend (Person 2: backend + simulation)

FastAPI service holding the in-memory simulation state for 10 fictional countries.
No database, no AI. Players can sanction, ally and send aid; every action is logged as a diplomacy event.

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
| GET    | `/world`                 | Full state: turn, countries, trade routes, events |
| GET    | `/countries/{country_id}`| One country (404 if unknown), e.g. `/countries/aurelia` |
| POST   | `/actions/sanction`      | `{"actor","target"}`: target loses GDP/stability, relationship drops, trade between the pair is suspended |
| POST   | `/actions/alliance`      | `{"actor","target"}`: both record the alliance, relationship and stability rise, trade between them grows |
| POST   | `/actions/aid`           | `{"actor","target","amount"}`: target gains stability and GDP, actor GDP dips, relationship improves |
| GET    | `/events`                | Recent diplomacy events, newest first (`?limit=1..100`, default 20) |
| POST   | `/simulation/reset`      | Restore the original starting world and clear all events |

Errors: `404` unknown country, `409` duplicate sanction/alliance (or alliance while sanctioned),
`400` actor == target or invalid aid amount, `422` malformed request. A failed action never changes the world.

## Files

| File            | Purpose                                                        |
|-----------------|----------------------------------------------------------------|
| `main.py`       | FastAPI app, CORS, routes (no business logic)                  |
| `models.py`     | Pydantic models: Country, TradeRoute, DiplomacyEvent, request/response models, WorldState |
| `countries.py`  | Hard-coded countries, alliances, trade routes, starting relationships |
| `simulation.py` | `Simulation`: owns the `WorldState`, runs actions atomically, event history, reset |
| `rules.py`      | Tuning constants, `apply_sanction/alliance/aid`, errors, `validate_world` |
| `test_smoke.py` | Smoke tests: `python test_smoke.py` (or `pytest`)              |
| `test_actions.py` | Action/event/reset tests: `python test_actions.py` (or `pytest`) |
| `conftest.py`   | pytest fixture that resets the world before every test         |

## Data conventions

- Countries: `aurelia, brevania, caldoria, dravenia, eldoria, fyrnia, garvonia, helvaris, istoria, jorvania`
- `gdp`: billions of fictional dollars. `stability`: 0-100. `resources`: stockpile index 0-100.
- `relationships[other_id]`: -100 (hostile) to 100 (friendly). Symmetric at the start.
- `sanctions`: ids of countries that currently sanction THIS country (empty at start).
- `trade_partners` is derived from `trade_routes`, so they always agree.
- Initial relationships are computed deterministically: +25 per shared alliance,
  +3 per 10 trade volume between the pair, plus hand-tuned grudges/friendships.
- Everything is deterministic: restarting the server always gives the same world.