"""Pydantic models for the MUN simulation."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Country(BaseModel):
    id: str = Field(description="Stable lowercase slug, e.g. 'aurelia'")
    name: str
    gdp: float = Field(ge=0, description="Gross domestic product in billions of fictional dollars")
    stability: int = Field(ge=0, le=100, description="Internal stability, 0 (collapse) to 100 (rock solid)")
    resources: dict[str, int] = Field(
        default_factory=dict,
        description="Resource stockpile index (0-100) keyed by resource name",
    )
    trade_partners: list[str] = Field(default_factory=list, description="Country ids with an active trade route")
    alliances: list[str] = Field(default_factory=list, description="Names of alliances this country belongs to")
    sanctions: list[str] = Field(
        default_factory=list,
        description="Ids of countries that currently impose sanctions ON this country",
    )
    relationships: dict[str, int] = Field(
        default_factory=dict,
        description="Relationship score toward each other country id, -100 (hostile) to 100 (friendly)",
    )


class TradeRoute(BaseModel):
    id: str
    exporter: str = Field(description="Country id sending the goods")
    importer: str = Field(description="Country id receiving the goods")
    resource: str
    volume: int = Field(
        ge=0,
        description="CURRENT trade volume index = base_volume * efficiency / 100 (0 while the route is inactive)",
    )
    active: bool = True
    base_volume: int = Field(gt=0, description="Normal (100% efficiency) trade volume index; never changes")
    efficiency: int = Field(
        default=100,
        ge=0,
        le=150,
        description="Percent of base_volume actually flowing: 100 = normal, >100 boosted (alliance), 0 = cut off (sanction)",
    )


class DiplomacyEvent(BaseModel):
    id: int = Field(description="Sequential id, starting at 1 after every reset")
    turn: int
    type: str = Field(description="'sanction', 'alliance' or 'aid'")
    actor: str = Field(description="Country id that initiated the event")
    target: Optional[str] = Field(default=None, description="Country id affected, if any")
    message: str = Field(description="Human-readable summary of what happened")
    timestamp: datetime = Field(description="UTC time the event was created")
    effects: dict[str, Any] = Field(default_factory=dict, description="Summary of state changes caused")


class ActionType(str, Enum):
    """Actions a country can take. Handlers arrive in later steps."""
    IMPOSE_SANCTION = "impose_sanction"
    LIFT_SANCTION = "lift_sanction"
    FORM_ALLIANCE = "form_alliance"
    LEAVE_ALLIANCE = "leave_alliance"
    SEND_AID = "send_aid"


class ActionRequest(BaseModel):
    action: ActionType
    actor: str = Field(description="Country id taking the action")
    target: Optional[str] = Field(default=None, description="Country id the action is aimed at")
    amount: Optional[float] = Field(default=None, ge=0, description="Size of the action, e.g. aid amount")
    note: Optional[str] = None


def _normalize_id(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


class _CountryPairRequest(BaseModel):
    """Shared shape of the action requests. Ids are trimmed and lower-cased."""

    model_config = ConfigDict(extra="forbid")

    actor: str = Field(min_length=1, description="Country id taking the action")
    target: str = Field(min_length=1, description="Country id the action is aimed at")

    _normalize = field_validator("actor", "target", mode="before")(_normalize_id)


class SanctionRequest(_CountryPairRequest):
    pass


class AllianceRequest(_CountryPairRequest):
    pass


class AidRequest(_CountryPairRequest):
    amount: float = Field(allow_inf_nan=False, description="Aid amount in billions of fictional dollars")

    @field_validator("amount", mode="before")
    @classmethod
    def _reject_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("amount must be a number")
        return value


class ActionResponse(BaseModel):
    """Returned by every successful action endpoint."""

    event: DiplomacyEvent
    actor: Country = Field(description="Actor country after the action")
    target: Country = Field(description="Target country after the action")


class WorldState(BaseModel):
    turn: int = 0
    countries: list[Country]
    trade_routes: list[TradeRoute]
    events: list[DiplomacyEvent] = Field(default_factory=list)