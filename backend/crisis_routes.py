"""Phase 7: the crisis endpoints, as one router that `main.py` includes.

Kept in its own module so the crisis API stays a clean, stable surface (and `main.py` only gains one line). Every
rule lives in `crisis_service`; the routes only translate HTTP. Errors are raised as `ActionError`s and turned into
`{"detail": ...}` responses by the app's existing handler.

No route lets a client or an AI set an effect, a status or a metric: requests are strict (unknown fields are
rejected) and consequences come only from the backend's fixed tables. The only endpoint that looks at what an option
would do is the read-only preview.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from .crisis_schemas import (
    CrisisCreateRequest,
    CrisisPreview,
    CrisisRespondRequest,
    CrisisRespondResult,
    CrisisResolveRequest,
    CrisisView,
)
from .crisis_service import crisis_service
from .models import ErrorResponse
from .mun.crisis import CrisisStatus, CrisisTemplate

router = APIRouter(tags=["crises"])

CRISIS_ERRORS = {
    403: {"model": ErrorResponse, "description": "Participant is not in this conference, has the wrong role (JURY starts and resolves crises, delegates respond), or the country does not match."},
    404: {"model": ErrorResponse, "description": "Conference or crisis not found."},
    409: {"model": ErrorResponse, "description": "Conference not ACTIVE, phase is not CRISIS, the crisis is already resolved or expired, the country already responded, or too many crises are open."},
    422: {"model": ErrorResponse, "description": "Invalid request, unknown template, or the option does not belong to this crisis."},
}


@router.get(
    "/crisis-templates",
    response_model=list[CrisisTemplate],
    summary="The ready-made crises the backend knows (title, severity and which responses each offers)",
)
def list_crisis_templates() -> list[CrisisTemplate]:
    return crisis_service.templates()


@router.post(
    "/crisis",
    response_model=CrisisView,
    status_code=201,
    summary="Start a crisis (a JURY member, CRISIS phase only); the backend works out each option's effects",
    responses=CRISIS_ERRORS,
)
def create_crisis(req: CrisisCreateRequest) -> CrisisView:
    return crisis_service.create_crisis(
        req.conference_id,
        req.participant_id,
        template_id=req.template_id,
        title=req.title,
        description=req.description,
        severity=req.severity,
        option_types=req.option_types,
    )


@router.get(
    "/crisis/{crisis_id}",
    response_model=CrisisView,
    summary="A crisis with its response options and the responses given so far",
    responses={404: CRISIS_ERRORS[404]},
)
def get_crisis(crisis_id: str) -> CrisisView:
    return crisis_service.get(crisis_id)


@router.post(
    "/crisis/{crisis_id}/respond",
    response_model=CrisisRespondResult,
    status_code=201,
    summary="Respond for your own country (CRISIS phase only, once per country); the option's effects change the world",
    responses=CRISIS_ERRORS,
)
def respond_to_crisis(crisis_id: str, req: CrisisRespondRequest) -> CrisisRespondResult:
    return crisis_service.respond(crisis_id, req.participant_id, req.country_code, req.option_id)


@router.post(
    "/crisis/{crisis_id}/resolve",
    response_model=CrisisView,
    summary="Close an ACTIVE crisis (a JURY member, CRISIS phase only)",
    responses=CRISIS_ERRORS,
)
def resolve_crisis(crisis_id: str, req: CrisisResolveRequest) -> CrisisView:
    return crisis_service.resolve(crisis_id, req.participant_id)


@router.get(
    "/crisis/{crisis_id}/options/{option_id}/preview",
    response_model=CrisisPreview,
    summary="What an option would do to the conference's metrics right now (read-only; changes nothing)",
    responses={404: CRISIS_ERRORS[404], 422: CRISIS_ERRORS[422]},
)
def preview_crisis_option(crisis_id: str, option_id: str) -> CrisisPreview:
    return crisis_service.preview_option(crisis_id, option_id)


@router.get(
    "/conference/{conference_id}/crises",
    response_model=list[CrisisView],
    summary="Crises of a conference, oldest first (optionally filtered by status)",
    responses={404: CRISIS_ERRORS[404], 422: CRISIS_ERRORS[422]},
)
def list_crises(
    conference_id: str,
    status: Optional[CrisisStatus] = Query(default=None, description="Only crises with this status"),
) -> list[CrisisView]:
    return crisis_service.list_crises(conference_id, status)