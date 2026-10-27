"""API shapes for the Phase 2 conference endpoints.

Requests are strict (unknown fields rejected, text trimmed). Responses are explicit views, so internal
bookkeeping (the stored conference record, locks, the raw committee registry) is never serialised.
"""
from __future__ import annotations

from typing import Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .models import Country, DiplomacyEvent, TradeRoute
from .mun import ConferencePhase, ConferenceStatus, MUNWorldMetrics, ParticipantRole


# --- Requests ---------------------------------------------------------------------------------
class ConferenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    # Plain strings on purpose: unknown values get a clear 422 listing the valid ones.
    committee: str = Field(min_length=1, max_length=64, description="UNSC or GLOBAL_CYBERSECURITY")
    topic: str = Field(min_length=1, max_length=300)


class JoinConferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100, description="Participant name")
    role: str = Field(min_length=1, max_length=32, description="GUEST, PARTICIPANT or JURY")
    country: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=64,
        description=(
            "Optional seat request for a PARTICIPANT: a country name, slug or ISO code ('India', 'IND', 'IN'), "
            "validated against the country registry. Omit it to be seated automatically when the conference starts."
        ),
    )


class AdvancePhaseRequest(BaseModel):
    """Body of POST /conference/{id}/advance. The whole body is optional.

    The backend always decides the next phase. `to_phase` is only a stale-screen guard: if it is given, it must
    equal the next valid step (a phase name, or COMPLETED after RESULTS) or the request is rejected with 409.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    to_phase: Optional[str] = Field(
        default=None, min_length=1, max_length=32, description="Optional expected next step; verified, never trusted"
    )


class ActionCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: str = Field(min_length=1, max_length=32, description="An ActionType, e.g. SPEECH or VOTE")


# --- Responses --------------------------------------------------------------------------------
class CommitteeConfigView(BaseModel):
    max_delegates: int
    voting_threshold: float
    allowed_phases: list[ConferencePhase]


class ParticipantView(BaseModel):
    id: str
    name: str
    role: ParticipantRole
    country_code: Optional[str] = Field(default=None, description="ISO alpha-2 code; None until a seat is assigned")
    country_name: Optional[str] = None
    score: float
    joined_at: AwareDatetime


class AssignedCountry(BaseModel):
    country_code: str
    country_id: str
    country_name: str
    flag: Optional[str] = None
    participant_id: str
    participant_name: str


class ActionCheckResponse(BaseModel):
    """Returned only when the action IS allowed now; every refusal is an error response."""

    conference_id: str
    action: str
    phase: ConferencePhase
    allowed: bool = True


class ConferenceWorldView(BaseModel):
    """The conference's own copy of the world, including the MUN metrics."""

    turn: int
    countries: list[Country]
    trade_routes: list[TradeRoute]
    events: list[DiplomacyEvent]
    mun_metrics: MUNWorldMetrics


class ConferenceSnapshot(BaseModel):
    id: str
    name: str
    committee: str
    topic: str
    status: ConferenceStatus
    current_phase: ConferencePhase
    created_at: AwareDatetime
    phase_started_at: Optional[AwareDatetime] = None
    phase_ends_at: Optional[AwareDatetime] = None
    config: CommitteeConfigView
    participant_count: int
    participants: list[ParticipantView]
    assigned_countries: list[AssignedCountry]
    world: Optional[ConferenceWorldView] = Field(default=None, description="None until the conference is started")
    next_phase: Optional[str] = Field(
        default=None,
        description="The one valid next step: a phase name, or COMPLETED after RESULTS. None unless the conference is ACTIVE.",
    )
    allowed_actions: list[str] = Field(
        default_factory=list, description="Action types the current phase permits (empty unless the conference is ACTIVE)"
    )