"""API shapes for the Phase 4 speech and speaker-queue endpoints.

A stored speech is returned as `backend.mun.Speech` itself. Requests are strict: unknown fields are rejected, so a
client can never send its own `phase` or `id` - the backend decides both.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .mun import MAX_SPEECH_CHARS, ConferencePhase, ConferenceStatus


# --- Requests ---------------------------------------------------------------------------------
class SpeechSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    participant_id: str = Field(min_length=1, max_length=64, description="The delegate giving the speech")
    country_code: str = Field(
        pattern=r"^[A-Z]{2}$",
        description="ISO alpha-2 code of the country being spoken for; must be the delegate's assigned country",
    )
    text: str = Field(min_length=1, max_length=MAX_SPEECH_CHARS, description="The speech")

    @field_validator("country_code", mode="before")
    @classmethod
    def _normalise_code(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


# --- Responses --------------------------------------------------------------------------------
class SpeakerEntry(BaseModel):
    participant_id: str
    participant_name: str
    country_code: Optional[str] = None
    country_name: Optional[str] = None


class SpeakerQueueView(BaseModel):
    conference_id: str
    status: ConferenceStatus
    phase: ConferencePhase
    speaking_open: bool = Field(
        description="True while the conference is ACTIVE and its current phase permits speeches"
    )
    current_speaker: Optional[SpeakerEntry] = Field(default=None, description="The delegate holding the floor, if any")
    queue: list[SpeakerEntry] = Field(default_factory=list, description="Delegates still waiting, in speaking order")
    completed: list[SpeakerEntry] = Field(
        default_factory=list, description="Delegates whose turn is over, in the order they spoke"
    )