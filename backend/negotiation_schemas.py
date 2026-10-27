"""API shapes for the Phase 5 negotiation endpoints.

A stored negotiation is returned as `backend.mun.Negotiation` itself. Requests are strict: unknown fields are
rejected, so a client can never send its own `id`, `status`, `phase`, `proposer` or `expires_at`; the backend
decides all of them (the proposer's country comes from the proposing participant's seat).
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .mun import MAX_PROPOSAL_CHARS, NegotiationAction


class NegotiationProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conference_id: str = Field(min_length=1, max_length=64, description="The conference the negotiation is in")
    participant_id: str = Field(min_length=1, max_length=64, description="The delegate making the proposal")
    receiver: str = Field(
        pattern=r"^[A-Z]{2}$",
        description="ISO alpha-2 code of the country being proposed to; it must be seated in the conference",
    )
    proposal: str = Field(min_length=1, max_length=MAX_PROPOSAL_CHARS, description="The proposal, as free text")

    @field_validator("receiver", mode="before")
    @classmethod
    def _normalise_code(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class NegotiationRespondRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    participant_id: str = Field(min_length=1, max_length=64, description="The delegate answering (the receiver)")
    action: NegotiationAction = Field(description="ACCEPT, REJECT or COUNTER")
    counter_offer: Optional[str] = Field(
        default=None,
        max_length=MAX_PROPOSAL_CHARS,
        description="Required for COUNTER; not allowed for ACCEPT or REJECT",
    )

    @model_validator(mode="after")
    def _counter_offer_matches_action(self) -> "NegotiationRespondRequest":
        has_text = bool(self.counter_offer and self.counter_offer.strip())
        if self.action is NegotiationAction.COUNTER and not has_text:
            raise ValueError("counter_offer is required when action is COUNTER")
        if self.action is not NegotiationAction.COUNTER and self.counter_offer is not None:
            raise ValueError(f"counter_offer is only allowed when action is COUNTER, not {self.action.value}")
        return self