"""Phase 6: resolutions, clauses and amendments - the drafting engine's data and state rules.

Pure data and pure functions: no I/O, no clock, no simulation import. Whether a phase PERMITS drafting, amending or
voting is decided by `mun.phases` (`RESOLUTION_EDIT`, `AMENDMENT`, `VOTE`); who may do it is decided by the service.
This module only says what a resolution is, how it may change state, and how its clauses are laid out.

Life of a resolution::

    DRAFT --submit--> SUBMITTED --review--> UNDER_REVIEW --\\
                          \\------------------------------------+--> VOTING --> PASSED
                                                                              \\-> FAILED

DRAFT is the only editable state: clauses are added, rewritten and removed freely. Once SUBMITTED the text is frozen
except through recorded AMENDMENTS (a sponsor's "friendly amendment", applied immediately and kept in the history).
VOTING opens when the conference reaches its VOTING phase; PASSED and FAILED are final and are set only from the
deterministic tally in `mun.voting`. The history is append-only: nothing is deleted once it leaves DRAFT.

Clauses are kept in reading order: every PREAMBULATORY clause first, then every OPERATIVE clause, and `number` is
the clause's 1-based position in that order. Numbers are rewritten whenever a clause is added, moved or removed; a
clause's `id` never changes.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import _to_utc, new_id, utcnow
from .voting import VoteResult

MAX_TITLE_CHARS = 200
MAX_CLAUSE_CHARS = 2000
MAX_CLAUSES = 50
MAX_SPONSORS = 10


class ResolutionStatus(str, Enum):
    """Uppercase, exact-match, like the other MUN enums."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VOTING = "VOTING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ClauseType(str, Enum):
    PREAMBULATORY = "PREAMBULATORY"
    OPERATIVE = "OPERATIVE"


class AmendmentAction(str, Enum):
    ADD = "ADD"
    MODIFY = "MODIFY"
    REMOVE = "REMOVE"


S = ResolutionStatus

# The only legal status changes. Anything not listed here is refused.
ALLOWED_TRANSITIONS: dict[ResolutionStatus, frozenset[ResolutionStatus]] = {
    S.DRAFT: frozenset({S.SUBMITTED}),
    S.SUBMITTED: frozenset({S.UNDER_REVIEW, S.VOTING}),
    S.UNDER_REVIEW: frozenset({S.VOTING}),
    S.VOTING: frozenset({S.PASSED, S.FAILED}),
    S.PASSED: frozenset(),
    S.FAILED: frozenset(),
}
FINAL_STATUSES: frozenset[ResolutionStatus] = frozenset({S.PASSED, S.FAILED})
# Statuses in which the text may still change, and how: directly (DRAFT) or only by amendment.
EDITABLE_STATUSES: frozenset[ResolutionStatus] = frozenset({S.DRAFT})
AMENDABLE_STATUSES: frozenset[ResolutionStatus] = frozenset({S.SUBMITTED, S.UNDER_REVIEW})

# Guard: every status must be placed in the flow, never forgotten.
if set(ALLOWED_TRANSITIONS) != set(ResolutionStatus):
    raise RuntimeError("ALLOWED_TRANSITIONS must cover every ResolutionStatus")


class ResolutionStateError(ValueError):
    """The resolution cannot take this step in its current status."""


class Clause(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(default_factory=lambda: new_id("clause"), min_length=1)
    resolution_id: str = Field(min_length=1)
    number: int = Field(ge=1, description="1-based position in reading order (preambulatory first)")
    type: ClauseType
    text: str = Field(min_length=1, max_length=MAX_CLAUSE_CHARS)
    created_by: str = Field(min_length=1, description="Id of the participant who wrote the clause")


class Amendment(BaseModel):
    """A recorded change to a SUBMITTED resolution. Immutable history."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: str = Field(default_factory=lambda: new_id("amend"), min_length=1)
    resolution_id: str = Field(min_length=1)
    proposed_by: str = Field(min_length=1, description="Id of the sponsoring participant who made the amendment")
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    action: AmendmentAction
    clause_id: str = Field(min_length=1, description="The clause added, modified or removed")
    clause_type: ClauseType = Field(description="The type the clause has after the amendment (its old type for REMOVE)")
    text: Optional[str] = Field(default=None, max_length=MAX_CLAUSE_CHARS, description="New text; None for REMOVE")
    previous_text: Optional[str] = Field(default=None, description="Text before the amendment; None for ADD")
    created_at: AwareDatetime = Field(default_factory=utcnow)

    _utc = field_validator("created_at", mode="after")(_to_utc)


class Resolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(default_factory=lambda: new_id("res"), min_length=1)
    conference_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    status: ResolutionStatus = ResolutionStatus.DRAFT
    created_by: str = Field(min_length=1, description="Id of the participant who created the resolution")
    sponsors: list[str] = Field(
        min_length=1, max_length=MAX_SPONSORS, description="ISO alpha-2 codes of the sponsoring countries (may edit)"
    )
    signatories: list[str] = Field(
        default_factory=list, description="ISO alpha-2 codes of countries that signed in support (do not edit)"
    )
    clauses: list[Clause] = Field(default_factory=list, max_length=MAX_CLAUSES)
    amendments: list[Amendment] = Field(default_factory=list)
    result: Optional[VoteResult] = Field(default=None, description="The official vote result; set when PASSED or FAILED")
    created_at: AwareDatetime = Field(default_factory=utcnow)
    updated_at: AwareDatetime = Field(default_factory=utcnow)

    _utc = field_validator("created_at", "updated_at", mode="after")(_to_utc)

    @field_validator("sponsors", "signatories", mode="before")
    @classmethod
    def _normalise_codes(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return [v.strip().upper() if isinstance(v, str) else v for v in value]
        return value

    @field_validator("sponsors", "signatories")
    @classmethod
    def _valid_codes(cls, codes: list[str]) -> list[str]:
        if len(set(codes)) != len(codes):
            raise ValueError("a country may appear only once")
        for code in codes:
            if len(code) != 2 or not code.isalpha() or not code.isupper():
                raise ValueError(f"'{code}' is not an ISO alpha-2 country code")
        return codes

    @model_validator(mode="after")
    def _consistent(self) -> "Resolution":
        if set(self.sponsors) & set(self.signatories):
            raise ValueError("a sponsor cannot also be a signatory")
        ids = [c.id for c in self.clauses]
        if len(set(ids)) != len(ids):
            raise ValueError("clause ids must be unique")
        if any(c.resolution_id != self.id for c in self.clauses):
            raise ValueError("every clause must belong to this resolution")
        if any(a.resolution_id != self.id for a in self.amendments):
            raise ValueError("every amendment must belong to this resolution")
        if [c.number for c in self.clauses] != list(range(1, len(self.clauses) + 1)):
            raise ValueError("clause numbers must run 1..n in order")
        types = [c.type for c in self.clauses]
        if types != sorted(types, key=lambda t: t is ClauseType.OPERATIVE):
            raise ValueError("preambulatory clauses must come before operative clauses")
        if self.status is not ResolutionStatus.DRAFT and operative_count(self) == 0:
            raise ValueError("a submitted resolution needs at least one operative clause")
        if (self.status in FINAL_STATUSES) != (self.result is not None):
            raise ValueError("a result is required when the status is PASSED or FAILED, and only then")
        if self.result is not None and self.result.passed != (self.status is ResolutionStatus.PASSED):
            raise ValueError("the status must match the result")
        return self


def operative_count(resolution: Resolution) -> int:
    return sum(1 for c in resolution.clauses if c.type is ClauseType.OPERATIVE)


def is_final(resolution: Resolution) -> bool:
    return resolution.status in FINAL_STATUSES


def check_transition(current: ResolutionStatus, target: ResolutionStatus) -> None:
    """Raise ResolutionStateError unless `current` -> `target` is a legal step."""
    current, target = ResolutionStatus(current), ResolutionStatus(target)
    if target not in ALLOWED_TRANSITIONS[current]:
        wanted = ", ".join(s.value for s in sorted(ALLOWED_TRANSITIONS[current], key=lambda s: s.value)) or "none"
        raise ResolutionStateError(
            f"A {current.value} resolution cannot become {target.value}; allowed next status: {wanted}"
        )


def _rebuild(resolution: Resolution, **update: Any) -> Resolution:
    # Re-validated on purpose: model_copy skips validation, and every change must keep the invariants.
    return Resolution.model_validate({**resolution.model_dump(), **update})


def layout_clauses(clauses: list[Clause]) -> list[Clause]:
    """Clauses in reading order (preambulatory first, each group keeping its order) with numbers 1..n."""
    ordered = sorted(clauses, key=lambda c: c.type is ClauseType.OPERATIVE)  # stable sort
    return [c.model_copy(update={"number": n}) for n, c in enumerate(ordered, start=1)]


def find_clause(resolution: Resolution, clause_id: str) -> Optional[Clause]:
    return next((c for c in resolution.clauses if c.id == clause_id), None)


def with_status(resolution: Resolution, status: ResolutionStatus, now: datetime, **extra: Any) -> Resolution:
    """The resolution after a legal status change (ResolutionStateError otherwise)."""
    check_transition(resolution.status, status)
    return _rebuild(resolution, status=status, updated_at=now, **extra)


def with_clause_added(
    resolution: Resolution, clause_type: ClauseType, text: str, created_by: str, now: datetime
) -> tuple[Resolution, Clause]:
    """The resolution with a new clause at the end of its type's group, and that clause (renumbered)."""
    clause = Clause(resolution_id=resolution.id, number=len(resolution.clauses) + 1, type=clause_type, text=text, created_by=created_by)
    laid_out = layout_clauses([*resolution.clauses, clause])
    updated = _rebuild(resolution, clauses=[c.model_dump() for c in laid_out], updated_at=now)
    return updated, find_clause(updated, clause.id)  # type: ignore[return-value]


def with_clause_changed(
    resolution: Resolution, clause_id: str, text: Optional[str], clause_type: Optional[ClauseType], now: datetime
) -> tuple[Resolution, Clause]:
    """The resolution with one clause's text and/or type changed. Raises KeyError for an unknown clause id."""
    old = find_clause(resolution, clause_id)
    if old is None:
        raise KeyError(clause_id)
    changed = old.model_copy(
        update={"text": text if text is not None else old.text, "type": clause_type if clause_type is not None else old.type}
    )
    others = [changed if c.id == clause_id else c for c in resolution.clauses]
    if changed.type is not old.type:  # moving between groups: it goes to the end of its new group
        others = [c for c in others if c.id != clause_id] + [changed]
    laid_out = layout_clauses(others)
    updated = _rebuild(resolution, clauses=[c.model_dump() for c in laid_out], updated_at=now)
    return updated, find_clause(updated, clause_id)  # type: ignore[return-value]


def with_clause_removed(resolution: Resolution, clause_id: str, now: datetime) -> tuple[Resolution, Clause]:
    """The resolution without one clause (renumbered), and the removed clause. Raises KeyError for an unknown id."""
    old = find_clause(resolution, clause_id)
    if old is None:
        raise KeyError(clause_id)
    laid_out = layout_clauses([c for c in resolution.clauses if c.id != clause_id])
    return _rebuild(resolution, clauses=[c.model_dump() for c in laid_out], updated_at=now), old


def with_signatory(resolution: Resolution, country_code: str, now: datetime) -> Resolution:
    return _rebuild(resolution, signatories=[*resolution.signatories, country_code], updated_at=now)


def with_amendment(resolution: Resolution, amendment: Amendment, now: datetime) -> Resolution:
    """Apply an already-built amendment's change to the clauses and append it to the history."""
    if amendment.action is AmendmentAction.ADD:
        clause = Clause(
            id=amendment.clause_id,
            resolution_id=resolution.id,
            number=len(resolution.clauses) + 1,
            type=amendment.clause_type,
            text=amendment.text or "",
            created_by=amendment.proposed_by,
        )
        clauses = layout_clauses([*resolution.clauses, clause])
    elif amendment.action is AmendmentAction.MODIFY:
        old = find_clause(resolution, amendment.clause_id)
        if old is None:
            raise KeyError(amendment.clause_id)
        changed = old.model_copy(update={"text": amendment.text or old.text, "type": amendment.clause_type})
        rest = [c for c in resolution.clauses if c.id != amendment.clause_id]
        # A clause that keeps its type keeps its place; one that changes type goes to the end of its new group.
        clauses = layout_clauses(
            [changed if c.id == amendment.clause_id else c for c in resolution.clauses]
            if changed.type is old.type
            else [*rest, changed]
        )
    else:
        clauses = layout_clauses([c for c in resolution.clauses if c.id != amendment.clause_id])
    return _rebuild(
        resolution,
        clauses=[c.model_dump() for c in clauses],
        amendments=[*(a.model_dump() for a in resolution.amendments), amendment.model_dump()],
        updated_at=now,
    )