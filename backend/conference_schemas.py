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