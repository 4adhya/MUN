"""API shapes for the Phase 6 resolution and voting endpoints.

A stored resolution is returned as `ResolutionView`: the `backend.mun.Resolution` itself plus the roll-call of votes
cast on it. Requests are strict: unknown fields are rejected, so a client can never send its own `id`, `status`,
`number`, `result` or `phase`; the backend decides all of them. Who is acting always comes from `participant_id`,
and the acting country always comes from that participant's seat.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .mun import (
    MAX_CLAUSE_CHARS,
    MAX_SPONSORS,
    MAX_TITLE_CHARS,
    AmendmentAction,
    ClauseType,
    Resolution,
    ResolutionStatus,
    Vote,
    VoteChoice,
    VoteResult,
)


def _code(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


class ResolutionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conference_id: str = Field(min_length=1, max_length=64, description="The conference the resolution is drafted in")
    participant_id: str = Field(min_length=1, max_length=64, description="The delegate creating it (becomes a sponsor)")
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    sponsors: list[str] = Field(
        default_factory=list,
        max_length=MAX_SPONSORS,
        description="Extra sponsoring countries (ISO alpha-2); each must be seated in the conference. The creator's "
        "own country is always a sponsor.",
    )

    @field_validator("sponsors", mode="before")
    @classmethod
    def _normalise_sponsors(cls, value: Any) -> Any:
        return [_code(v) for v in value] if isinstance(value, list) else value


class ClauseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    participant_id: str = Field(min_length=1, max_length=64)
    type: ClauseType = Field(description="PREAMBULATORY or OPERATIVE")
    text: str = Field(min_length=1, max_length=MAX_CLAUSE_CHARS)


class ClauseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    participant_id: str = Field(min_length=1, max_length=64)
    text: Optional[str] = Field(default=None, min_length=1, max_length=MAX_CLAUSE_CHARS)
    type: Optional[ClauseType] = None

    @model_validator(mode="after")
    def _something_changes(self) -> "ClauseUpdateRequest":
        if self.text is None and self.type is None:
            raise ValueError("give a new text, a new type or both")
        return self


class ResolutionAmendRequest(BaseModel):
    """ADD needs `type` and `text`; MODIFY needs `clause_id` and a new `text` and/or `type`; REMOVE needs `clause_id`."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    participant_id: str = Field(min_length=1, max_length=64)
    action: AmendmentAction
    clause_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    type: Optional[ClauseType] = None
    text: Optional[str] = Field(default=None, min_length=1, max_length=MAX_CLAUSE_CHARS)

    @model_validator(mode="after")
    def _fields_match_action(self) -> "ResolutionAmendRequest":
        if self.action is AmendmentAction.ADD:
            if self.type is None or self.text is None:
                raise ValueError("an ADD amendment needs a type and a text")
            if self.clause_id is not None:
                raise ValueError("an ADD amendment cannot name a clause_id; the backend creates the clause")
        elif self.action is AmendmentAction.MODIFY:
            if self.clause_id is None:
                raise ValueError("a MODIFY amendment needs a clause_id")
            if self.text is None and self.type is None:
                raise ValueError("a MODIFY amendment needs a new text, a new type or both")
        else:  # REMOVE
            if self.clause_id is None:
                raise ValueError("a REMOVE amendment needs a clause_id")
            if self.text is not None or self.type is not None:
                raise ValueError("a REMOVE amendment cannot carry a text or a type")
        return self


class ResolutionActorRequest(BaseModel):
    """Body of the endpoints that only need to say who is acting (submit, sign)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    participant_id: str = Field(min_length=1, max_length=64)


class VoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    participant_id: str = Field(min_length=1, max_length=64, description="The delegate voting")
    country_code: str = Field(
        pattern=r"^[A-Z]{2}$", description="The country being voted for; it must be the participant's own seat"
    )
    vote: VoteChoice = Field(description="YES, NO or ABSTAIN")

    @field_validator("country_code", mode="before")
    @classmethod
    def _normalise_code(cls, value: Any) -> Any:
        return _code(value)


class ResolutionView(Resolution):
    """A resolution as the API returns it: the resolution plus its roll call (oldest vote first)."""

    votes: list[Vote] = Field(default_factory=list, description="Votes cast so far; public (a roll-call vote)")


class VoteResponse(BaseModel):
    """What a cast vote returns. `result` is present only when this vote completed the voting."""

    vote: Vote
    resolution_status: ResolutionStatus
    result: Optional[VoteResult] = Field(
        default=None, description="The official result, when this was the last vote and the resolution is decided"
    )