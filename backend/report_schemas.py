"""API shapes for the simulation report.

Everything in a report is derived from recorded simulation data (the event log, the current world and
the initial world). Fields that cannot be derived are Optional and None rather than guessed.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import AwareDatetime, BaseModel, Field

from .mun import ConferencePhase, ConferenceStatus, MUNWorldMetrics, ParticipantRole

ReportType = Literal["SIMULATION_SNAPSHOT", "CONFERENCE_FINAL", "CONFERENCE_INTERIM"]


class ReportParticipant(BaseModel):
    name: str
    role: ParticipantRole
    country_name: Optional[str] = None


class ReportConference(BaseModel):
    id: str
    name: str
    committee: str
    topic: str
    status: ConferenceStatus
    current_phase: ConferencePhase
    participants: list[ReportParticipant]


class ReportCountry(BaseModel):
    id: str
    name: str
    flag: Optional[str] = None
    delegate: Optional[str] = Field(default=None, description="Participant seated as this country (conference reports only)")
    actions_initiated: int = 0
    actions_received: int = 0


class ReportEvent(BaseModel):
    id: int
    turn: int
    type: str
    actor: str
    actor_name: str
    target: Optional[str] = None
    target_name: Optional[str] = None
    message: str
    timestamp: AwareDatetime


class ReportSanction(BaseModel):
    event_id: int
    turn: int
    imposed_by: str
    imposed_by_name: str
    target: str
    target_name: str
    target_gdp_before: Optional[float] = None
    target_gdp_after: Optional[float] = None
    target_stability_before: Optional[int] = None
    target_stability_after: Optional[int] = None
    trade_routes_suspended: list[str] = Field(default_factory=list)


class ReportAlliance(BaseModel):
    event_id: int
    turn: int
    name: Optional[str] = None
    members: list[str]
    member_names: list[str]


class ReportAid(BaseModel):
    event_id: int
    turn: int
    donor: str
    donor_name: str
    recipient: str
    recipient_name: str
    amount: Optional[float] = Field(default=None, description="Billions of illustrative simulation dollars")
    donor_gdp_before: Optional[float] = None
    donor_gdp_after: Optional[float] = None
    recipient_gdp_before: Optional[float] = None
    recipient_gdp_after: Optional[float] = None


class ReportTradeChange(BaseModel):
    route_id: str
    exporter: str
    importer: str
    resource: str
    active_before: bool
    active_after: bool
    volume_before: int
    volume_after: int
    efficiency_before: int
    efficiency_after: int


class ReportCountryChange(BaseModel):
    id: str
    name: str
    gdp_before: float
    gdp_after: float
    stability_before: int
    stability_after: int
    alliances_added: list[str] = Field(default_factory=list)
    sanctions_received_from: list[str] = Field(default_factory=list, description="Country names newly sanctioning this country")


class ReportTotals(BaseModel):
    actions: int = 0
    sanctions: int = 0
    alliances: int = 0
    aid_transfers: int = 0
    total_aid_amount: float = 0.0
    trade_routes_changed: int = 0
    countries_changed: int = 0


class ReportOutcome(BaseModel):
    summary: str
    highlights: list[str] = Field(default_factory=list)
    totals: ReportTotals


class SimulationReport(BaseModel):
    report_type: ReportType
    generated_at: AwareDatetime
    turn: int
    event_count: int
    activity_recorded: bool = Field(description="False when no diplomatic action has been taken")
    conference: Optional[ReportConference] = None
    participating_countries: list[ReportCountry]
    alliances: list[ReportAlliance]
    sanctions: list[ReportSanction]
    aid: list[ReportAid]
    trade_changes: list[ReportTradeChange]
    diplomatic_events: list[ReportEvent]
    world_changes: list[ReportCountryChange]
    mun_metrics: Optional[MUNWorldMetrics] = Field(default=None, description="Conference reports only")
    outcome: ReportOutcome