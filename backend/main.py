"""FastAPI entry point.

Run from the backend/ folder:
    uvicorn main:app --reload

Routes only: all game logic lives in simulation.py / rules.py.
"""
import logging
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from models import (
    ActionResponse,
    AidRequest,
    AllianceRequest,
    Country,
    DiplomacyEvent,
    ErrorResponse,
    SanctionRequest,
    WorldState,
)
from rules import ActionError
from simulation import simulation

logger = logging.getLogger("mun")

app = FastAPI(
    title="MUN Simulation API",
    version="0.3.0",
    description=(
        "Backend for the MUN geopolitical simulation: 10 fictional countries with GDP, stability, "
        "resources, relationships, alliances, sanctions and trade routes. State is in memory; "
        "POST /simulation/reset restores the starting world."
    ),
)

# --- CORS ------------------------------------------------------------------------
# Local Vite/React dev servers by default. For a deployed frontend, set CORS_ORIGINS to a
# comma-separated list, e.g.  CORS_ORIGINS=https://my-app.vercel.app,http://localhost:5173
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


def cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "")
    custom = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    return custom or DEFAULT_CORS_ORIGINS


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Errors ------------------------------------------------------------------------
@app.exception_handler(ActionError)
def action_error_handler(_request: Request, exc: ActionError) -> JSONResponse:
    """Rejected actions (404 unknown country, 409 duplicate, 400 invalid...)."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(RequestValidationError)
def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 for malformed requests. Only loc/msg/type are returned: FastAPI's default also
    echoes the raw input, which crashes into a 500 for values such as NaN."""
    detail = [
        {"loc": list(err.get("loc", ())), "msg": str(err.get("msg", "")), "type": str(err.get("type", ""))}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(Exception)
def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Last resort: a JSON 500 instead of a bare text page. The traceback goes to the server log only."""
    logger.exception("Unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Error responses documented in /docs for the action endpoints.
ACTION_ERRORS = {
    400: {"model": ErrorResponse, "description": "Actor and target are the same country, or invalid aid amount"},
    404: {"model": ErrorResponse, "description": "Actor or target country does not exist"},
    409: {"model": ErrorResponse, "description": "Duplicate or conflicting action (e.g. already sanctioned / allied)"},
}


# --- Read endpoints -------------------------------------------------------------------
@app.get("/health", tags=["system"], summary="Liveness check")
def health() -> dict:
    return {"status": "ok"}


@app.get(
    "/world",
    response_model=WorldState,
    tags=["world"],
    summary="Full current world state",
    description=(
        "Everything needed to render the simulation: turn, all countries (GDP, stability, resources, "
        "relationships, alliances, sanctions, trade partners), all trade routes with their current "
        "status/efficiency/volume, and the full event history (oldest first)."
    ),
)
def get_world() -> WorldState:
    return simulation.world


@app.get(
    "/countries/{country_id}",
    response_model=Country,
    tags=["world"],
    summary="One country's current state",
    description="Case-insensitive id, e.g. `/countries/aurelia`.",
    responses={404: {"model": ErrorResponse, "description": "Unknown country id"}},
)
def get_country(country_id: str) -> Country:
    country = simulation.get_country(country_id.strip().lower())
    if country is None:
        raise HTTPException(status_code=404, detail=f"Country '{country_id}' not found")
    return country


@app.get(
    "/events",
    response_model=list[DiplomacyEvent],
    tags=["events"],
    summary="Diplomacy event feed (newest first)",
    description="Most recent events, newest first. `limit` is 1-100 (default 20).",
)
def get_events(limit: int = Query(20, ge=1, le=100)) -> list[DiplomacyEvent]:
    return simulation.recent_events(limit)


# --- Player actions: routes only ---------------------------------------------------------
@app.post(
    "/actions/sanction",
    response_model=ActionResponse,
    tags=["actions"],
    summary="Actor sanctions target",
    description="Target loses GDP and stability, relationship drops, and every direct trade route between the two is cut.",
    responses=ACTION_ERRORS,
)
def post_sanction(req: SanctionRequest) -> ActionResponse:
    return simulation.sanction(req.actor, req.target)


@app.post(
    "/actions/alliance",
    response_model=ActionResponse,
    tags=["actions"],
    summary="Actor forms an alliance with target",
    description="Both countries join a new bilateral alliance; relationship and stability rise and direct trade routes run at 110%.",
    responses=ACTION_ERRORS,
)
def post_alliance(req: AllianceRequest) -> ActionResponse:
    return simulation.alliance(req.actor, req.target)


@app.post(
    "/actions/aid",
    response_model=ActionResponse,
    tags=["actions"],
    summary="Actor sends aid to target",
    description="Amount is 1-500 and at most 10% of the actor's GDP. Target gains GDP and stability, actor's GDP dips slightly, relationship improves.",
    responses=ACTION_ERRORS,
)
def post_aid(req: AidRequest) -> ActionResponse:
    return simulation.aid(req.actor, req.target, req.amount)


@app.post(
    "/simulation/reset",
    response_model=WorldState,
    tags=["simulation"],
    summary="Restore the starting world",
    description="Resets countries, relationships, alliances, sanctions, trade routes and clears all events. Returns the fresh world.",
)
def reset_simulation() -> WorldState:
    return simulation.reset()