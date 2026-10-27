"""API shapes for the Phase 7 crisis endpoints.

A stored crisis is returned as `CrisisView`: the `backend.mun.crisis.Crisis` itself plus its response options and the
responses given so far. Requests are strict: unknown fields are rejected, so a client can never send its own `id`,
`status`, `effects`, `expires_at` or `outcome`; the backend decides all of them. In particular the effects of an option
come only from the backend's fixed tables (see `mun.crisis`), never from a request. Who is acting always comes from
`participant_id`, and a responding country always has to be that participant's own seat.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .mun.crisis import (
    MAX_DESCRIPTION_CHARS,
    MAX_OPTIONS,
    MAX_TITLE_CHARS,
    MIN_OPTIONS,
    Crisis,
    CrisisActionType,
    CrisisOption,
    CrisisResponse,
    CrisisSeverity,
)
from .mun.metrics import MUNWorldMetrics


class CrisisCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conference_id: str = Field(min_length=1, max_length=64, description="The conference the crisis happens in")
    participant_id: str = Field(min_length=1, max_length=64, description="The JURY member starting the crisis")
    template_id: Optional[str] = Field(
        default=None,
        pattern=r"^[a-z][a-z_]*$",
        max_length=64,
        description="A ready-made crisis (see GET /crisis-templates). Its text, severity and options are the defaults.",
    )
    title: Optional[str] = Field(default=None, min_length=1, max_length=MAX_TITLE_CHARS)
    description: Optional[str] = Field(default=None, min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    severity: Optional[CrisisSeverity] = Field(default=None, description="LOW, MEDIUM, HIGH or CRITICAL")
    option_types: Optional[list[CrisisActionType]] = Field(
        default=None,
        min_length=MIN_OPTIONS,
        max_length=MAX_OPTIONS,
        description="Which kinds of response to offer, each at most once. The backend works out each option's effects.",
    )

    @model_validator(mode="after")
    def _custom_crisis_is_complete(self) -> "CrisisCreateRequest":
        if self.template_id is None:
            missing = [n for n in ("title", "description", "severity") if getattr(self, n) is None]
            if missing:
                raise ValueError(f"{', '.join(missing)} required when no template_id is given")
        if self.option_types is not None and len(set(self.option_types)) != len(self.option_types):
            raise ValueError("option_types must not repeat an action type")
        return self


class CrisisRespondRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    participant_id: str = Field(min_length=1, max_length=64, description="The delegate responding")
    country_code: str = Field(
        pattern=r"^[A-Z]{2}$", description="ISO alpha-2 code; it must be the country the participant represents"
    )
    option_id: str = Field(min_length=1, max_length=64, description="The crisis option the country chooses")

    @field_validator("country_code", mode="before")
    @classmethod
    def _normalise_code(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class CrisisResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    participant_id: str = Field(min_length=1, max_length=64, description="The JURY member closing the crisis")


class CrisisView(Crisis):
    """A crisis with its options and the responses given to it so far (oldest first)."""

    options: list[CrisisOption] = Field(default_factory=list)
    responses: list[CrisisResponse] = Field(default_factory=list)


class CrisisRespondResult(BaseModel):
    """Returned when a response was accepted: the response, the crisis after it, and the conference's metrics now."""

    response: CrisisResponse
    crisis: CrisisView
    mun_metrics: MUNWorldMetrics


class CrisisPreview(BaseModel):
    """What an option WOULD do right now. Read-only: producing this changes nothing and emits no event."""

    crisis_id: str
    option_id: str
    action_type: CrisisActionType
    effects: dict[str, int]
    current: dict[str, float]
    projected: dict[str, float]
    applied: dict[str, float]