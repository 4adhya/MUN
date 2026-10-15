"""FastAPI entry point.

Run from the backend/ folder:
    uvicorn main:app --reload
"""
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from models import (
    ActionResponse,
    AidRequest,
    AllianceRequest,
    Country,
    DiplomacyEvent,
    SanctionRequest,
    WorldState,
)
from rules import ActionError
from simulation import simulation

app = FastAPI(title="MUN Simulation API", version="0.2.0")

# Allow the Vite/React dev server to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ActionError)
def action_error_handler(_request: Request, exc: ActionError) -> JSONResponse:
    """Rejected actions (404 unknown country, 409 duplicate, 400 invalid...)."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/world", response_model=WorldState)
def get_world() -> WorldState:
    return simulation.world


@app.get("/countries/{country_id}", response_model=Country)
def get_country(country_id: str) -> Country:
    country = simulation.get_country(country_id.lower())
    if country is None:
        raise HTTPException(status_code=404, detail=f"Country '{country_id}' not found")
    return country


# --- Player actions: routes only, all logic lives in simulation.py / rules.py ---
@app.post("/actions/sanction", response_model=ActionResponse)
def post_sanction(req: SanctionRequest) -> ActionResponse:
    return simulation.sanction(req.actor, req.target)


@app.post("/actions/alliance", response_model=ActionResponse)
def post_alliance(req: AllianceRequest) -> ActionResponse:
    return simulation.alliance(req.actor, req.target)


@app.post("/actions/aid", response_model=ActionResponse)
def post_aid(req: AidRequest) -> ActionResponse:
    return simulation.aid(req.actor, req.target, req.amount)


@app.get("/events", response_model=list[DiplomacyEvent])
def get_events(limit: int = Query(20, ge=1, le=100)) -> list[DiplomacyEvent]:
    """Most recent diplomacy events, newest first."""
    return simulation.recent_events(limit)


@app.post("/simulation/reset", response_model=WorldState)
def reset_simulation() -> WorldState:
    return simulation.reset()