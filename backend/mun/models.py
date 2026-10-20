"""MUN domain models: Conference and Participant.

Pure data + shape validation. No endpoints, no phase transitions, no join logic
(Phases 2-3). Nothing here imports the geopolitical simulation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import Committee, ConferencePhase, ConferenceStatus, ParticipantRole


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _to_utc(value: Any) -> Any:
    # AwareDatetime already rejects naive values; normalise the rest to UTC.
    return value.astimezone(timezone.utc) if isinstance(value, datetime) else value


class Conference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(default_factory=lambda: new_id("conf"), min_length=1)
    name: str = Field(min_length=1, max_length=100)
    committee: Committee
    topic: str = Field(min_length=1, max_length=300)
    status: ConferenceStatus = ConferenceStatus.WAITING
    current_phase: ConferencePhase = ConferencePhase.LOBBY
    phase_started_at: Optional[AwareDatetime] = Field(
        default=None, description="UTC time the current phase began; None until the conference starts"
    )
    phase_ends_at: Optional[AwareDatetime] = Field(
        default=None, description="UTC time the current phase is due to end; None for untimed phases"
    )
    created_at: AwareDatetime = Field(default_factory=utcnow)

    _utc = field_validator("phase_started_at", "phase_ends_at", "created_at", mode="after")(_to_utc)

    @model_validator(mode="after")
    def _phase_window_is_ordered(self) -> "Conference":
        if self.phase_started_at and self.phase_ends_at and self.phase_ends_at < self.phase_started_at:
            raise ValueError("phase_ends_at must not be before phase_started_at")
        return self


class Participant(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(default_factory=lambda: new_id("part"), min_length=1)
    name: str = Field(min_length=1, max_length=100)
    role: ParticipantRole
    country_code: Optional[str] = Field(
        default=None,
        pattern=r"^[A-Z]{2}$",
        description="ISO 3166-1 alpha-2 code matching Country.country_code; None for guests/jury without a seat",
    )
    conference_id: str = Field(min_length=1)
    score: float = Field(default=0.0, allow_inf_nan=False)
    joined_at: AwareDatetime = Field(default_factory=utcnow)

    _utc = field_validator("joined_at", mode="after")(_to_utc)

    @field_validator("country_code", mode="before")
    @classmethod
    def _normalise_code(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value