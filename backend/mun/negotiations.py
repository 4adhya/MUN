"""Phase 5: negotiations between two delegates (the diplomacy engine's data and state rules).

Pure data and pure functions: no I/O, no clock, no simulation import. Whether a phase PERMITS negotiating is
decided by `mun.phases` (`ActionType.NEGOTIATION`: UNMODERATED_CAUCUS and CRISIS); this module only says what a
negotiation is and how it may change state.

Life of a negotiation::

    PENDING --ACCEPT---> ACCEPTED
            --REJECT---> REJECTED
            --COUNTER--> COUNTERED   (the counter-offer text is stored; the receiver's answer is final)
            --time/phase-> EXPIRED

PENDING is the only open state. ACCEPTED, REJECTED, COUNTERED and EXPIRED are final: a finalized negotiation is
never answered again and never edited. To follow up on a counter-offer, the original proposer opens a new
negotiation. History is append-only: negotiations are never deleted, so later AI agents can read all of them.

A negotiation expires when EITHER its `expires_at` time has passed OR the conference has moved to a phase that no
longer permits negotiating (an offer made in an unmoderated caucus survives into the crisis, which also permits
negotiation, but not into drafting). The proposal and counter-offer
are free text for humans (and, later, agents) to read. They are never parsed: what a negotiation does to the world
is decided only by the deterministic rules in `backend/negotiation_rules.py`, from the outcome alone.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import ConferencePhase
from .models import _to_utc, new_id, utcnow
from .phases import ActionType, is_action_allowed

MAX_PROPOSAL_CHARS = 2000
NEGOTIATION_TTL_SECONDS = 5 * 60  # how long an unanswered proposal stays open


class NegotiationStatus(str, Enum):
    """Uppercase, exact-match, like the other MUN enums."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    COUNTERED = "COUNTERED"
    EXPIRED = "EXPIRED"


class NegotiationAction(str, Enum):
    """What the receiver can answer."""

    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    COUNTER = "COUNTER"


# The status each answer leads to. One place, so the endpoint, the events and the rules cannot disagree.
ACTION_OUTCOME: dict[NegotiationAction, NegotiationStatus] = {
    NegotiationAction.ACCEPT: NegotiationStatus.ACCEPTED,
    NegotiationAction.REJECT: NegotiationStatus.REJECTED,
    NegotiationAction.COUNTER: NegotiationStatus.COUNTERED,
}

FINAL_STATUSES: frozenset[NegotiationStatus] = frozenset(
    {
        NegotiationStatus.ACCEPTED,
        NegotiationStatus.REJECTED,
        NegotiationStatus.COUNTERED,
        NegotiationStatus.EXPIRED,
    }
)

# Guard: a new status must be classified as open or final, never forgotten.
if FINAL_STATUSES | {NegotiationStatus.PENDING} != set(NegotiationStatus):
    raise RuntimeError("Every NegotiationStatus must be PENDING or in FINAL_STATUSES")


class NegotiationStateError(ValueError):
    """The negotiation cannot take this step: it is already final (answered or expired)."""


class Negotiation(BaseModel):
    """One proposal from one delegate to another. Immutable: a change of state produces a new object."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: str = Field(default_factory=lambda: new_id("neg"), min_length=1)
    conference_id: str = Field(min_length=1)
    proposer: str = Field(pattern=r"^[A-Z]{2}$", description="ISO alpha-2 code of the proposing country")
    receiver: str = Field(pattern=r"^[A-Z]{2}$", description="ISO alpha-2 code of the receiving country")
    proposal: str = Field(min_length=1, max_length=MAX_PROPOSAL_CHARS)
    status: NegotiationStatus = NegotiationStatus.PENDING
    counter_offer: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=MAX_PROPOSAL_CHARS,
        description="The receiver's counter-offer; present only when the status is COUNTERED",
    )
    created_at: AwareDatetime = Field(default_factory=utcnow)
    expires_at: AwareDatetime = Field(description="UTC time after which an unanswered proposal expires")

    # Bookkeeping that makes the history self-contained for readers (UI, AI agents). Set by the backend.
    proposer_participant_id: str = Field(min_length=1)
    receiver_participant_id: str = Field(min_length=1)
    phase: ConferencePhase = Field(description="The conference phase the proposal was made in (set by the backend)")
    responded_at: Optional[AwareDatetime] = Field(
        default=None, description="UTC time the receiver answered; None while PENDING or EXPIRED"
    )

    _utc = field_validator("created_at", "expires_at", "responded_at", mode="after")(_to_utc)

    @field_validator("proposer", "receiver", mode="before")
    @classmethod
    def _normalise_code(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _consistent(self) -> "Negotiation":
        if self.proposer == self.receiver:
            raise ValueError("a country cannot negotiate with itself")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if (self.status is NegotiationStatus.COUNTERED) != (self.counter_offer is not None):
            raise ValueError("counter_offer is required when the status is COUNTERED, and only then")
        return self


def default_expiry(created_at: datetime) -> datetime:
    """When a proposal made at `created_at` expires if nobody answers."""
    return created_at + timedelta(seconds=NEGOTIATION_TTL_SECONDS)


def is_finalized(negotiation: Negotiation) -> bool:
    return negotiation.status in FINAL_STATUSES


def should_expire(negotiation: Negotiation, now: datetime, current_phase: ConferencePhase) -> bool:
    """True if `negotiation` is still PENDING but its time is up or `current_phase` no longer permits negotiating."""
    return expire_reason(negotiation, now, current_phase) is not None


def expire_reason(negotiation: Negotiation, now: datetime, current_phase: ConferencePhase) -> Optional[str]:
    """Why a PENDING negotiation must expire, or None if it may stay open.

    'phase_closed' (the phase no longer permits NEGOTIATION, per `mun.phases`) wins over 'time_elapsed'.
    """
    if negotiation.status is not NegotiationStatus.PENDING:
        return None
    if not is_action_allowed(current_phase, ActionType.NEGOTIATION):
        return "phase_closed"
    if now >= negotiation.expires_at:
        return "time_elapsed"
    return None


def expire(negotiation: Negotiation) -> Negotiation:
    """The EXPIRED version of a PENDING negotiation. A final negotiation cannot expire."""
    if is_finalized(negotiation):
        raise NegotiationStateError(
            f"Negotiation '{negotiation.id}' is already {negotiation.status.value} and cannot expire"
        )
    return negotiation.model_copy(update={"status": NegotiationStatus.EXPIRED})


def apply_response(
    negotiation: Negotiation,
    action: NegotiationAction,
    counter_offer: Optional[str],
    now: datetime,
) -> Negotiation:
    """The negotiation after the receiver's answer. Only a PENDING negotiation can be answered.

    COUNTER needs a non-blank `counter_offer` (ValueError); ACCEPT and REJECT must not carry one.
    Raises NegotiationStateError if the negotiation is final (including EXPIRED).
    """
    action = NegotiationAction(action)
    if is_finalized(negotiation):
        raise NegotiationStateError(
            f"Negotiation '{negotiation.id}' is already {negotiation.status.value} and can no longer be answered"
        )
    text = counter_offer.strip() if isinstance(counter_offer, str) else None
    if action is NegotiationAction.COUNTER:
        if not text:
            raise ValueError("A COUNTER response needs a counter_offer")
    elif text:
        raise ValueError(f"A {action.value} response cannot carry a counter_offer")
    update: dict[str, Any] = {"status": ACTION_OUTCOME[action], "responded_at": now}
    if action is NegotiationAction.COUNTER:
        update["counter_offer"] = text
    # Re-validated on purpose: model_copy skips validation, and a counter-offer must pass the same limits.
    return Negotiation.model_validate({**negotiation.model_dump(), **update})