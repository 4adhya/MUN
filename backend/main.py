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
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

AI_DIR = Path(__file__).resolve().parent.parent / "ai"

if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from ai.advisor import MAX_HISTORY_TURNS, MAX_MESSAGE_CHARS, DiplomaticAdvisor
from ai.country_agent import COUNTRY_PROFILES, AgentProfile, AgentResult, CountryAgent
from ai.gemini_client import REASON_CONFIG, resolve_model

from .ai_routes import router as conference_ai_router
from .conference_schemas import (
    ActionCheckRequest,
    ActionCheckResponse,
    AdvancePhaseRequest,
    ConferenceCreateRequest,
    ConferenceSnapshot,
    JoinConferenceRequest,
)
from .conference_service import conference_service
from .crisis_routes import router as crisis_router
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
from .mun import ConferencePhase, Negotiation, NegotiationStatus, Participant, ResolutionStatus, Speech
from .negotiation_schemas import NegotiationProposeRequest, NegotiationRespondRequest
from .report_schemas import SimulationReport
from .report_service import build_report
from .resolution_schemas import (
    ClauseCreateRequest,
    ClauseUpdateRequest,
    ResolutionActorRequest,
    ResolutionAmendRequest,
    ResolutionCreateRequest,
    ResolutionView,
    VoteRequest,
    VoteResponse,
)
from .resolution_service import resolution_service
from .rules import ActionError
from .simulation import create_initial_world, simulation
from .speech_schemas import SpeakerQueueView, SpeechSubmitRequest

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


app.include_router(conference_ai_router)  # Phase 8: proposal-only conference AI roles (see ai_routes.py)


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
# MUN conferences (Phase 2: create, join, view, start)
# ---------------------------------------------------------------------------

CONFERENCE_ERRORS = {
    404: {"model": ErrorResponse, "description": "Conference not found."},
    409: {"model": ErrorResponse, "description": "Conference is not WAITING, is full, or cannot start."},
    422: {"model": ErrorResponse, "description": "Invalid committee, role or request, or no available country."},
}


@app.post(
    "/conference/create",
    response_model=ConferenceSnapshot,
    status_code=201,
    tags=["conference"],
    summary="Create a conference (WAITING, phase LOBBY)",
    responses={422: CONFERENCE_ERRORS[422]},
)
def create_conference(req: ConferenceCreateRequest) -> ConferenceSnapshot:
    return conference_service.create(req.name, req.committee, req.topic)


@app.post(
    "/conference/{conference_id}/join",
    response_model=Participant,
    status_code=201,
    tags=["conference"],
    summary="Join a WAITING conference (optionally requesting a country seat)",
    responses=CONFERENCE_ERRORS,
)
def join_conference(conference_id: str, req: JoinConferenceRequest) -> Participant:
    return conference_service.join(conference_id, req.name, req.role, req.country)


@app.get(
    "/conference/{conference_id}",
    response_model=ConferenceSnapshot,
    tags=["conference"],
    summary="Get a conference snapshot",
    responses={404: CONFERENCE_ERRORS[404]},
)
def get_conference(conference_id: str) -> ConferenceSnapshot:
    return conference_service.get(conference_id)


@app.post(
    "/conference/{conference_id}/start",
    response_model=ConferenceSnapshot,
    tags=["conference"],
    summary="Start a conference: assign countries, create the world, enter ROLL_CALL (LOBBY -> ROLL_CALL)",
    responses=CONFERENCE_ERRORS,
)
def start_conference(conference_id: str) -> ConferenceSnapshot:
    return conference_service.start(conference_id)


@app.post(
    "/conference/{conference_id}/advance",
    response_model=ConferenceSnapshot,
    tags=["conference"],
    summary="Advance the conference one valid phase (the backend decides which); after RESULTS it completes",
    responses={404: CONFERENCE_ERRORS[404], 409: CONFERENCE_ERRORS[409], 422: CONFERENCE_ERRORS[422]},
)
def advance_conference(conference_id: str, req: Optional[AdvancePhaseRequest] = None) -> ConferenceSnapshot:
    return conference_service.advance(conference_id, req.to_phase if req else None)


@app.post(
    "/conference/{conference_id}/actions/check",
    response_model=ActionCheckResponse,
    tags=["conference"],
    summary="Ask whether an action type is allowed in the conference's current phase (performs nothing)",
    responses={404: CONFERENCE_ERRORS[404], 409: CONFERENCE_ERRORS[409], 422: CONFERENCE_ERRORS[422]},
)
def check_conference_action(conference_id: str, req: ActionCheckRequest) -> ActionCheckResponse:
    return conference_service.check_action(conference_id, req.action)


@app.get(
    "/conference/{conference_id}/report",
    response_model=SimulationReport,
    tags=["report"],
    summary="Report for a started conference (read-only)",
    responses={404: CONFERENCE_ERRORS[404], 409: CONFERENCE_ERRORS[409]},
)
def get_conference_report(conference_id: str) -> SimulationReport:
    return conference_service.report(conference_id)


# ---------------------------------------------------------------------------
# MUN speeches and the speaker queue (Phase 4)
# ---------------------------------------------------------------------------

SPEECH_ERRORS = {
    403: {"model": ErrorResponse, "description": "Participant is not in this conference, cannot speak, or the country does not match."},
    404: CONFERENCE_ERRORS[404],
    409: {"model": ErrorResponse, "description": "Conference not ACTIVE, phase does not permit speeches, or not the speaker's turn."},
    422: {"model": ErrorResponse, "description": "Invalid speech or request."},
}


@app.post(
    "/conference/{conference_id}/speech",
    response_model=Speech,
    status_code=201,
    tags=["speeches"],
    summary="Submit a speech (only the delegate holding the floor, only in a phase that permits speeches)",
    responses=SPEECH_ERRORS,
)
def submit_speech(conference_id: str, req: SpeechSubmitRequest) -> Speech:
    return conference_service.submit_speech(conference_id, req.participant_id, req.country_code, req.text)


@app.get(
    "/conference/{conference_id}/speeches",
    response_model=list[Speech],
    tags=["speeches"],
    summary="Speech history of a conference, oldest first (optionally filtered by phase and/or country)",
    responses={404: CONFERENCE_ERRORS[404], 422: SPEECH_ERRORS[422]},
)
def list_speeches(
    conference_id: str,
    phase: Optional[ConferencePhase] = Query(default=None, description="Only speeches given in this phase"),
    country_code: Optional[str] = Query(
        default=None, min_length=2, max_length=2, description="Only speeches for this ISO alpha-2 country code"
    ),
) -> list[Speech]:
    return conference_service.get_speeches(conference_id, phase, country_code)


@app.get(
    "/conference/{conference_id}/speakers",
    response_model=SpeakerQueueView,
    tags=["speeches"],
    summary="Speaker queue: who holds the floor, who is waiting, who has spoken",
    responses={404: CONFERENCE_ERRORS[404]},
)
def get_speakers(conference_id: str) -> SpeakerQueueView:
    return conference_service.get_speakers(conference_id)


@app.post(
    "/conference/{conference_id}/speaker/next",
    response_model=SpeakerQueueView,
    tags=["speeches"],
    summary="End the current speaker's turn and give the floor to the next delegate",
    responses={404: CONFERENCE_ERRORS[404], 409: SPEECH_ERRORS[409]},
)
def next_speaker(conference_id: str) -> SpeakerQueueView:
    return conference_service.next_speaker(conference_id)


# ---------------------------------------------------------------------------
# MUN negotiations and diplomacy (Phase 5)
# ---------------------------------------------------------------------------

NEGOTIATION_ERRORS = {
    403: {"model": ErrorResponse, "description": "Participant is not in this conference, cannot negotiate, or is not the delegate the proposal was addressed to."},
    404: {"model": ErrorResponse, "description": "Conference or negotiation not found."},
    409: {"model": ErrorResponse, "description": "Conference not ACTIVE, phase does not permit negotiation, or the negotiation is already final (answered or expired)."},
    422: {"model": ErrorResponse, "description": "Invalid request, receiver not seated in the conference, or COUNTER without a counter-offer."},
}


@app.post(
    "/negotiation/propose",
    response_model=Negotiation,
    status_code=201,
    tags=["negotiations"],
    summary="Propose a negotiation to another delegate's country (only in phases that permit negotiation)",
    responses=NEGOTIATION_ERRORS,
)
def propose_negotiation(req: NegotiationProposeRequest) -> Negotiation:
    return conference_service.propose_negotiation(req.conference_id, req.participant_id, req.receiver, req.proposal)


@app.post(
    "/negotiation/{negotiation_id}/respond",
    response_model=Negotiation,
    tags=["negotiations"],
    summary="Receiving delegate accepts, rejects or counters a PENDING negotiation",
    responses=NEGOTIATION_ERRORS,
)
def respond_to_negotiation(negotiation_id: str, req: NegotiationRespondRequest) -> Negotiation:
    return conference_service.respond_negotiation(negotiation_id, req.participant_id, req.action, req.counter_offer)


@app.get(
    "/conference/{conference_id}/negotiations",
    response_model=list[Negotiation],
    tags=["negotiations"],
    summary="Negotiation history of a conference, oldest first (optionally filtered by status and/or country)",
    responses={404: NEGOTIATION_ERRORS[404], 422: NEGOTIATION_ERRORS[422]},
)
def list_negotiations(
    conference_id: str,
    status: Optional[NegotiationStatus] = Query(default=None, description="Only negotiations with this status"),
    country_code: Optional[str] = Query(
        default=None,
        min_length=2,
        max_length=2,
        description="Only negotiations this ISO alpha-2 country took part in (as proposer or receiver)",
    ),
) -> list[Negotiation]:
    return conference_service.get_negotiations(conference_id, status, country_code)


# ---------------------------------------------------------------------------
# MUN resolutions and voting (Phase 6)
# ---------------------------------------------------------------------------

RESOLUTION_ERRORS = {
    403: {"model": ErrorResponse, "description": "Participant is not in this conference, is not a delegate, is not a sponsor, or the country does not match."},
    404: {"model": ErrorResponse, "description": "Conference, resolution or clause not found."},
    409: {"model": ErrorResponse, "description": "Conference not ACTIVE, phase does not permit the action, or the resolution is in the wrong status (or the country already voted)."},
    422: {"model": ErrorResponse, "description": "Invalid request or content (blank or too long text, no operative clause, unseated sponsor)."},
}


@app.post(
    "/resolution",
    response_model=ResolutionView,
    status_code=201,
    tags=["resolutions"],
    summary="Start drafting a resolution (status DRAFT; the creator's country is a sponsor)",
    responses=RESOLUTION_ERRORS,
)
def create_resolution(req: ResolutionCreateRequest) -> ResolutionView:
    return resolution_service.create_resolution(req.conference_id, req.participant_id, req.title, req.sponsors)


@app.get(
    "/resolution/{resolution_id}",
    response_model=ResolutionView,
    tags=["resolutions"],
    summary="A resolution with its clauses, amendments, roll-call votes and (once decided) its official result",
    responses={404: RESOLUTION_ERRORS[404]},
)
def get_resolution(resolution_id: str) -> ResolutionView:
    return resolution_service.get(resolution_id)


@app.post(
    "/resolution/{resolution_id}/clause",
    response_model=ResolutionView,
    status_code=201,
    tags=["resolutions"],
    summary="Add a clause to a DRAFT resolution (sponsors only); clauses are renumbered in reading order",
    responses=RESOLUTION_ERRORS,
)
def add_clause(resolution_id: str, req: ClauseCreateRequest) -> ResolutionView:
    return resolution_service.add_clause(resolution_id, req.participant_id, req.type, req.text)


@app.patch(
    "/resolution/{resolution_id}/clause/{clause_id}",
    response_model=ResolutionView,
    tags=["resolutions"],
    summary="Change a clause's text and/or type in a DRAFT resolution (sponsors only)",
    responses=RESOLUTION_ERRORS,
)
def update_clause(resolution_id: str, clause_id: str, req: ClauseUpdateRequest) -> ResolutionView:
    return resolution_service.update_clause(resolution_id, clause_id, req.participant_id, req.text, req.type)


@app.delete(
    "/resolution/{resolution_id}/clause/{clause_id}",
    response_model=ResolutionView,
    tags=["resolutions"],
    summary="Remove a clause from a DRAFT resolution (sponsors only); returns the renumbered resolution",
    responses=RESOLUTION_ERRORS,
)
def remove_clause(
    resolution_id: str,
    clause_id: str,
    participant_id: str = Query(min_length=1, max_length=64, description="The sponsoring delegate removing the clause"),
) -> ResolutionView:
    return resolution_service.remove_clause(resolution_id, clause_id, participant_id.strip())


@app.post(
    "/resolution/{resolution_id}/amend",
    response_model=ResolutionView,
    status_code=201,
    tags=["resolutions"],
    summary="Amend a SUBMITTED or UNDER_REVIEW resolution (a sponsor's friendly amendment, DRAFTING phase only)",
    responses=RESOLUTION_ERRORS,
)
def amend_resolution(resolution_id: str, req: ResolutionAmendRequest) -> ResolutionView:
    return resolution_service.amend(resolution_id, req.participant_id, req.action, req.clause_id, req.type, req.text)


@app.post(
    "/resolution/{resolution_id}/sign",
    response_model=ResolutionView,
    tags=["resolutions"],
    summary="Sign a resolution in support (a delegate who is not a sponsor)",
    responses=RESOLUTION_ERRORS,
)
def sign_resolution(resolution_id: str, req: ResolutionActorRequest) -> ResolutionView:
    return resolution_service.sign(resolution_id, req.participant_id)


@app.post(
    "/resolution/{resolution_id}/submit",
    response_model=ResolutionView,
    tags=["resolutions"],
    summary="Submit a DRAFT resolution (sponsors only; needs an operative clause); its text is then frozen",
    responses=RESOLUTION_ERRORS,
)
def submit_resolution(resolution_id: str, req: ResolutionActorRequest) -> ResolutionView:
    return resolution_service.submit(resolution_id, req.participant_id)


@app.post(
    "/resolution/{resolution_id}/review",
    response_model=ResolutionView,
    tags=["resolutions"],
    summary="The chair takes a SUBMITTED resolution under review (no participant needed, like advancing the phase)",
    responses={404: RESOLUTION_ERRORS[404], 409: RESOLUTION_ERRORS[409]},
)
def review_resolution(resolution_id: str) -> ResolutionView:
    return resolution_service.review(resolution_id)


@app.post(
    "/resolution/{resolution_id}/vote",
    response_model=VoteResponse,
    status_code=201,
    tags=["resolutions"],
    summary="Vote YES, NO or ABSTAIN for your own country (VOTING phase only; one final vote per country)",
    responses=RESOLUTION_ERRORS,
)
def vote_on_resolution(resolution_id: str, req: VoteRequest) -> VoteResponse:
    return resolution_service.vote(resolution_id, req.participant_id, req.country_code, req.vote)


@app.get(
    "/conference/{conference_id}/resolutions",
    response_model=list[ResolutionView],
    tags=["resolutions"],
    summary="Resolutions of a conference, oldest first (optionally filtered by status)",
    responses={404: RESOLUTION_ERRORS[404], 422: RESOLUTION_ERRORS[422]},
)
def list_resolutions(
    conference_id: str,
    status: Optional[ResolutionStatus] = Query(default=None, description="Only resolutions with this status"),
) -> list[ResolutionView]:
    return resolution_service.list_resolutions(conference_id, status)


# MUN crises (Phase 7): all crisis routes live in crisis_routes.py
app.include_router(crisis_router)


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


def resolve_ai_profile(world, country_id: str) -> AgentProfile:
    """The AI identity for any identifier the client sends ("India", "india", "IND", "afghanistan", ...).

    Resolved through the country dataset; the simulated world is only needed for the live state briefing.
    Raises HTTPException 404 for an unknown country and 400 for a simulated country without an AI profile.
    """
    country = find_world_country(world, country_id)
    record = resolve_country(country_id)

    if country is None and record is None:
        raise HTTPException(status_code=404, detail=f"Country '{country_id}' not found")

    if country is not None:
        # The selected country determines the identity of the agent.
        profile = COUNTRY_PROFILES.get(country.id)
        if profile is None:
            profile = COUNTRY_PROFILES.get(country.id.replace("_", "-"))
        if profile is None:
            raise HTTPException(status_code=400, detail=f"No AI profile configured for {country.name}")
        return profile

    # A real country that is not simulated: derive its profile from the dataset record.
    return profile_from_record(record)


AI_STATUS_SUCCESS = "SUCCESS"
AI_STATUS_FAILED = "AI_REQUEST_FAILED"


def ai_failure_response(country_name: str, result: Any) -> JSONResponse:  # AgentResult or AdvisorResult
    """The explicit answer when no AI decision exists (Gemini failed or its reply was unusable).

    Deliberately NOT shaped like a decision: there is no `decision` object and no NO_ACTION, so a client can
    never mistake an AI failure for a country that chose to do nothing. The world is never touched.
    HTTP 502 (upstream/AI failure) or 503 (the AI is not configured); `detail` is the human-readable text the
    existing frontend client already shows.
    """
    reason = result.failure_reason or AI_STATUS_FAILED
    logger.warning(
        "ai proposal failed country=%s reason=%s upstream_http_status=%s attempts=%s",
        country_name, reason, result.http_status, result.attempts,
    )
    return JSONResponse(
        status_code=503 if reason == REASON_CONFIG else 502,
        content={
            "status": AI_STATUS_FAILED,
            "reason": reason,
            "error_code": result.error_code,
            "detail": (
                f"AI request failed ({reason}): {result.error} "
                "No decision was made and the simulation was not changed."
            ),
            "country": country_name,
            "upstream_http_status": result.http_status,
            "attempts": result.attempts,
            "model_attempted": resolve_model_or_none(),
            "source": None,
            "used_fallback": False,
            "decision": None,
        },
    )


@app.post(
    "/ai/propose",
    tags=["AI"],
    summary="Generate a country-specific AI proposal",
)
def propose_ai_action(req: AIProposalRequest) -> dict:
    """Generate a validated proposal without executing it."""

    world = simulation.world
    profile = resolve_ai_profile(world, req.country_id)
    agent = CountryAgent(profile)

    # An AI failure is NEVER turned into a decision: no fallback NO_ACTION is fabricated here.
    result = agent.propose(req.situation, world)
    if not result.ok:
        return ai_failure_response(profile.name, result)

    return {
        "status": AI_STATUS_SUCCESS,
        "source": "ai",
        "model": resolve_model_or_none(),
        "used_fallback": False,
        "error_code": None,
        "error": None,
        "decision": result.decision.model_dump(mode="json"),
    }


class AdvisorTurn(BaseModel):
    role: Literal["user", "advisor"]
    text: str = Field(max_length=MAX_MESSAGE_CHARS)


class AdvisorChatRequest(BaseModel):
    country_id: str = Field(default="india", min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    history: list[AdvisorTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS * 2)


@app.post(
    "/ai/advisor",
    tags=["AI"],
    summary="Ask the diplomatic advisor (advice only)",
)
def ask_advisor(req: AdvisorChatRequest) -> Any:
    """Free-text strategic advice grounded in the live world state. Never executes anything or changes the world."""
    if not req.message.strip():
        raise HTTPException(status_code=422, detail="message must not be blank")
    world = simulation.world
    profile = resolve_ai_profile(world, req.country_id)

    result = DiplomaticAdvisor(profile).reply(req.message, [t.model_dump() for t in req.history], world)
    if not result.ok:
        return ai_failure_response(profile.name, result)

    return {
        "status": AI_STATUS_SUCCESS,
        "country": profile.name,
        "reply": result.reply,
        "model": resolve_model_or_none(),
    }


# ---------------------------------------------------------------------------
# Simulation report
# ---------------------------------------------------------------------------

@app.get(
    "/simulation/report",
    response_model=SimulationReport,
    tags=["report"],
    summary="Generate the report for the current simulation (read-only)",
    description=(
        "Summarises only what is recorded in the simulation: its event log and the change between the "
        "initial and current world. Never modifies state. With no actions taken it returns a valid report "
        "with empty sections and activity_recorded=false."
    ),
)
def get_simulation_report() -> SimulationReport:
    return build_report(simulation.world, create_initial_world())


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