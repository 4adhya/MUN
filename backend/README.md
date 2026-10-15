# MUN Backend (Person 2: backend + simulation)

FastAPI service holding the in-memory simulation state for 10 fictional countries.
No database, no AI, no actions yet (sanctions / alliances / aid come in later steps).

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

## Files

| File            | Purpose                                                        |
|-----------------|----------------------------------------------------------------|
| `main.py`       | FastAPI app, CORS, routes                                      |
| `models.py`     | Pydantic models: Country, TradeRoute, DiplomacyEvent, ActionRequest, WorldState |
| `countries.py`  | Hard-coded countries, alliances, trade routes, starting relationships |
| `simulation.py` | `Simulation` class that owns the in-memory `WorldState`        |
| `rules.py`      | Limits, clamp helpers, `validate_world` consistency checker    |
| `test_smoke.py` | Smoke tests: `python test_smoke.py` (or `pytest`)              |

## Data conventions

- Countries: `aurelia, brevania, caldoria, dravenia, eldoria, fyrnia, garvonia, helvaris, istoria, jorvania`
- `gdp`: billions of fictional dollars. `stability`: 0-100. `resources`: stockpile index 0-100.
- `relationships[other_id]`: -100 (hostile) to 100 (friendly). Symmetric at the start.
- `sanctions`: ids of countries that currently sanction THIS country (empty at start).
- `trade_partners` is derived from `trade_routes`, so they always agree.
- Initial relationships are computed deterministically: +25 per shared alliance,
  +3 per 10 trade volume between the pair, plus hand-tuned grudges/friendships.
- Everything is deterministic: restarting the server always gives the same world.
