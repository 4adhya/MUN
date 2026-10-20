"""FastAPI entry point for the WorldEvent geopolitical simulation.

Run from the project root:
    python3 -m uvicorn backend.main:app --reload --port 8000

The backend remains the source of truth for world state and action validation.
AI agents propose actions; they never execute actions directly.
"""

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

AI_DIR = Path(__file__).resolve().parent.parent / "ai"

if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from ai.country_agent import COUNTRY_PROFILES, AgentProfile, CountryAgent
from ai.fallback import decide_with_fallback
from ai.gemini_client import resolve_model

from .country_registry import CountryRecord, find_world_country, resolve_country
from .models import (
    ActionResponse,
    AidRequest,
    AllianceRequest,
    Country,
    DiplomacyEvent,
    ErrorResponse,
    SanctionRequest,
    WorldState,
)
from .rules import ActionError
from .simulation import simulation

logger = logging.getLogger("worldevent")

app = FastAPI(
    title="WorldEvent API",
    version="0.4.0",
    description=(
        "Geopolitical simulation API with country data, trade routes, "
        "diplomatic relationships, sanctions, alliances, aid and AI proposals. "
        "Simulation state is currently held in memory."
    ),
)

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


def cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "")
    custom = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    return custom or DEFAULT_CORS_ORIGINS


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ActionError)
def action_error_handler(_request: Request, exc: ActionError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


@app.exception_handler(RequestValidationError)
def validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    detail = [
        {
            "loc": list(error.get("loc", ())),
            "msg": str(error.get("msg", "")),
            "type": str(error.get("type", "")),
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(Exception)
def unexpected_error_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception("Unhandled request error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


ACTION_ERRORS = {
    400: {
        "model": ErrorResponse,
        "description": "Invalid action or aid amount.",
    },
    404: {
        "model": ErrorResponse,
        "description": "Actor or target country does not exist.",
    },
    409: {
        "model": ErrorResponse,
        "description": "Duplicate or conflicting action.",
    },
}


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"], summary="Backend health check")
def health() -> dict:
    return {"status": "ok"}


@app.get(
    "/world",
    response_model=WorldState,
    tags=["world"],
    summary="Get the complete world state",
)
def get_world() -> WorldState:
    return simulation.world


@app.get(
    "/countries/{country_id}",
    response_model=Country,
    tags=["world"],
    summary="Get a country by ID",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Country not found.",
        }
    },
)
def get_country(country_id: str) -> Country:
    country = find_world_country(simulation.world, country_id)

    if country is None:
        raise HTTPException(
            status_code=404,
            detail=f"Country '{country_id}' not found",
        )

    return country


@app.get(
    "/events",
    response_model=list[DiplomacyEvent],
    tags=["events"],
    summary="Get recent diplomatic events",
)
def get_events(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[DiplomacyEvent]:
    return simulation.recent_events(limit)


# ---------------------------------------------------------------------------
# AI proposals
# ---------------------------------------------------------------------------

class AIProposalRequest(BaseModel):
    country_id: str = Field(
        default="india",
        min_length=1,
        max_length=64,
    )
    situation: str = Field(
        min_length=1,
        max_length=1000,
    )


def profile_from_record(record: CountryRecord) -> AgentProfile:
    """Generic advisor profile for a dataset country that has no hand-written profile or simulated state."""
    place = record.subregion or record.region or "the world"
    facts = [f"Region: {place}"]
    if record.capital:
        facts.append(f"Capital: {', '.join(record.capital)}")
    facts.append(f"ISO codes: {record.cca2} / {record.cca3}")
    if record.un_member is not None:
        facts.append(f"UN member state: {'yes' if record.un_member else 'no'}")
    return AgentProfile(
        country_id=record.slug,
        name=record.name,
        personality=(
            f"Represents {record.name} ({place}). Pragmatic and guided by national interest, regional "
            "security and economic stability. Prefers proportionate, de-escalatory responses."
        ),
        goals=(
            f"Protect {record.name}'s sovereignty, security and domestic stability.",
            "Preserve economic resilience and useful trade relationships.",
            "Build diplomatic partnerships that serve regional stability.",
            "Respond proportionately and avoid unnecessary escalation.",
        ),
        background=" | ".join(facts),
    )


def resolve_model_or_none():
    """Configured Gemma model name, or None if the configuration is invalid."""
    try:
        return resolve_model()
    except Exception:
        return None


@app.post(
    "/ai/propose",
    tags=["AI"],
    summary="Generate a country-specific AI proposal",
)
def propose_ai_action(req: AIProposalRequest) -> dict:
    """Generate a validated proposal without executing it."""

    world = simulation.world

    # Any identifier the client sends ("India", "india", "IND", "afghanistan", "AFG", ...) is resolved
    # through the country dataset; the simulated world is only needed for the live state briefing.
    country = find_world_country(world, req.country_id)
    record = resolve_country(req.country_id)

    if country is None and record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Country '{req.country_id}' not found",
        )

    if country is not None:
        # The selected country determines the identity of the agent.
        profile = COUNTRY_PROFILES.get(country.id)

        if profile is None:
            profile = COUNTRY_PROFILES.get(
                country.id.replace("_", "-")
            )

        if profile is None:
            raise HTTPException(
                status_code=400,
                detail=f"No AI profile configured for {country.name}",
            )
    else:
        # A real country that is not simulated: derive its profile from the dataset record.
        profile = profile_from_record(record)
    agent = CountryAgent(profile)

    outcome = decide_with_fallback(
        agent,
        req.situation,
        world,
    )

    return {
        "source": outcome.source,
        # Model name that produced this decision; None for a fallback, so a fallback is never attributed to Gemma.
        "model": resolve_model_or_none() if outcome.source == "ai" else None,
        "used_fallback": outcome.is_fallback,
        "error_code": outcome.error_code,
        "error": outcome.error,
        "decision": outcome.decision.model_dump(mode="json"),
    }


# ---------------------------------------------------------------------------
# Validated simulation actions
# ---------------------------------------------------------------------------

@app.post(
    "/actions/sanction",
    response_model=ActionResponse,
    tags=["actions"],
    summary="Apply sanctions",
    responses=ACTION_ERRORS,
)
def post_sanction(req: SanctionRequest) -> ActionResponse:
    return simulation.sanction(req.actor, req.target)


@app.post(
    "/actions/alliance",
    response_model=ActionResponse,
    tags=["actions"],
    summary="Form an alliance",
    responses=ACTION_ERRORS,
)
def post_alliance(req: AllianceRequest) -> ActionResponse:
    return simulation.alliance(req.actor, req.target)


@app.post(
    "/actions/aid",
    response_model=ActionResponse,
    tags=["actions"],
    summary="Send aid",
    responses=ACTION_ERRORS,
)
def post_aid(req: AidRequest) -> ActionResponse:
    return simulation.aid(
        req.actor,
        req.target,
        req.amount,
    )


@app.post(
    "/simulation/reset",
    response_model=WorldState,
    tags=["simulation"],
    summary="Reset the simulation",
)
def reset_simulation() -> WorldState:
    return simulation.reset()