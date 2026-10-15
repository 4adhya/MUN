"""Pydantic models for the MUN simulation."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


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
    volume: int = Field(gt=0, description="Trade volume index")
    active: bool = True


class DiplomacyEvent(BaseModel):
    id: int
    turn: int
    type: str = Field(description="e.g. 'sanction', 'alliance', 'aid' (used in later steps)")
    actor: str = Field(description="Country id that initiated the event")
    target: Optional[str] = Field(default=None, description="Country id affected, if any")
    description: str
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


class WorldState(BaseModel):
    turn: int = 0
    countries: list[Country]
    trade_routes: list[TradeRoute]
    events: list[DiplomacyEvent] = Field(default_factory=list)
