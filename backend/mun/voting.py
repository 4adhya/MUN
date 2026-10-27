"""Phase 6: voting - the vote model, configurable voting rules and the deterministic tally.

Pure data and pure functions: no I/O, no clock, no simulation import, and no AI. Whether a phase PERMITS voting is
decided by `mun.phases` (`ActionType.VOTE`: the VOTING phase only); this module only says what a vote is and how a
set of votes becomes an OFFICIAL result.

The official result is a function of three things and nothing else: the votes cast, the countries entitled to vote,
and the committee's `VotingRules`. Same inputs, same result, every time. Nothing in here reads free text, and no
language model is ever consulted: an AI agent may propose how a country votes, but the number that decides a
resolution is always computed here.

How a result is computed (`tally`)::

    counted    = YES + NO
                 + ABSTAIN   if rules.abstention is COUNTS_AGAINST   (otherwise abstentions are ignored)
                 + ABSENT    if rules.absent_counts_against          (otherwise non-voters are ignored)
    required   = counted // 2 + 1                       for a SIMPLE majority (strictly more than half)
               = ceil(threshold * counted)              for a QUALIFIED majority (threshold met or exceeded)
    passed     = YES >= required  and  no veto

    veto       = rules.veto_enabled and a country in rules.veto_members voted NO.
                 An ABSTENTION or an absence by a veto holder is NOT a veto (this is the real UN Security
                 Council practice). A veto fails the resolution whatever the count is.

A resolution with no YES votes never passes. All arithmetic is done on integers (the threshold is converted to an
exact fraction first), so a result can never depend on floating point rounding.
"""
from __future__ import annotations

from enum import Enum
from fractions import Fraction
from typing import Any, Iterable, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import ConferencePhase
from .models import _to_utc, new_id, utcnow


class VoteChoice(str, Enum):
    """Uppercase, exact-match, like the other MUN enums."""

    YES = "YES"
    NO = "NO"
    ABSTAIN = "ABSTAIN"


class MajorityType(str, Enum):
    SIMPLE = "SIMPLE"  # strictly more than half of the votes that count
    QUALIFIED = "QUALIFIED"  # at least `threshold` of the votes that count (e.g. 3/5, 2/3)


class AbstentionBehavior(str, Enum):
    IGNORED = "IGNORED"  # an abstention is not counted at all ("present and voting" = YES + NO)
    COUNTS_AGAINST = "COUNTS_AGAINST"  # an abstention counts toward the total, so it works like a NO


class Vote(BaseModel):
    """One country's vote on one resolution. Immutable: a vote is never changed and never withdrawn."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: str = Field(default_factory=lambda: new_id("vote"), min_length=1)
    resolution_id: str = Field(min_length=1)
    conference_id: str = Field(min_length=1)
    participant_id: str = Field(min_length=1)
    country_code: str = Field(pattern=r"^[A-Z]{2}$", description="ISO alpha-2 code of the country that voted")
    choice: VoteChoice
    phase: ConferencePhase = Field(description="The phase the vote was cast in (set by the backend)")
    cast_at: AwareDatetime = Field(default_factory=utcnow)

    _utc = field_validator("cast_at", mode="after")(_to_utc)

    @field_validator("country_code", mode="before")
    @classmethod
    def _normalise_code(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class VotingRules(BaseModel):
    """How a committee turns votes into an outcome. Pure configuration: add a rule by changing data, not code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    majority: MajorityType = MajorityType.SIMPLE
    threshold: Optional[float] = Field(
        default=None,
        gt=0.5,
        le=1,
        allow_inf_nan=False,
        description="Required fraction of counted votes in favour (inclusive). Only for a QUALIFIED majority.",
    )
    abstention: AbstentionBehavior = AbstentionBehavior.IGNORED
    absent_counts_against: bool = Field(
        default=False,
        description="True: a seated delegate who never voted counts toward the total, like a NO (e.g. 9 of 15 members)",
    )
    veto_enabled: bool = False
    veto_members: tuple[str, ...] = Field(
        default=(), description="ISO alpha-2 codes of the countries whose NO vote vetoes the resolution"
    )

    @field_validator("veto_members", mode="before")
    @classmethod
    def _normalise_members(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple, set, frozenset)):
            return tuple(sorted(v.strip().upper() if isinstance(v, str) else v for v in value))
        return value

    @field_validator("veto_members")
    @classmethod
    def _valid_members(cls, members: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(members)) != len(members):
            raise ValueError("veto_members must not contain duplicates")
        for code in members:
            if len(code) != 2 or not code.isalpha() or not code.isupper():
                raise ValueError(f"veto member '{code}' is not an ISO alpha-2 country code")
        return members

    @model_validator(mode="after")
    def _consistent(self) -> "VotingRules":
        if self.majority is MajorityType.QUALIFIED and self.threshold is None:
            raise ValueError("a QUALIFIED majority needs a threshold")
        if self.majority is MajorityType.SIMPLE and self.threshold is not None:
            raise ValueError("a SIMPLE majority takes no threshold")
        if self.veto_enabled and not self.veto_members:
            raise ValueError("veto_enabled needs at least one veto member")
        if self.veto_members and not self.veto_enabled:
            raise ValueError("veto_members are only allowed when veto_enabled is true")
        return self


class VoteResult(BaseModel):
    """The official result of a vote. Computed by `tally`; stored with the resolution it decided."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    yes: int = Field(ge=0)
    no: int = Field(ge=0)
    abstain: int = Field(ge=0)
    absent: int = Field(ge=0, description="Eligible delegates who never voted")
    eligible: int = Field(ge=0, description="Countries entitled to vote")
    counted: int = Field(ge=0, description="The total the majority is measured against (see the module docstring)")
    required_yes: int = Field(ge=1, description="YES votes needed to pass, before any veto")
    vetoed_by: tuple[str, ...] = Field(default=(), description="Veto holders who voted NO (empty without a veto)")
    reason: str = Field(description="One human-readable sentence explaining the outcome")
    yes_countries: tuple[str, ...] = ()
    no_countries: tuple[str, ...] = ()
    abstain_countries: tuple[str, ...] = ()
    absent_countries: tuple[str, ...] = ()
    rules: VotingRules = Field(description="The rules the result was computed under")


class VotingError(ValueError):
    """The votes handed to `tally` are inconsistent (a duplicate, or a country that was not eligible)."""


def threshold_fraction(threshold: float) -> Fraction:
    """The exact fraction for a configured threshold (0.6 -> 3/5, 0.6666... -> 2/3). No float math is left after this."""
    return Fraction(threshold).limit_denominator(1000)


def required_yes(counted: int, rules: VotingRules) -> int:
    """The smallest YES count that satisfies the majority out of `counted` (never less than 1)."""
    if rules.majority is MajorityType.SIMPLE:
        needed = counted // 2 + 1
    else:
        fraction = threshold_fraction(rules.threshold)  # type: ignore[arg-type]  # validated: QUALIFIED has one
        needed = -((-fraction.numerator * counted) // fraction.denominator)  # integer ceiling
    return max(1, needed)


def tally(votes: Iterable[Any], eligible_countries: Iterable[str], rules: VotingRules) -> VoteResult:
    """Compute the official result.

    `votes` are objects with `country_code` and `choice` (normally `Vote`). `eligible_countries` are the ISO codes
    entitled to vote. Raises VotingError for a duplicate vote or a vote from a country that is not eligible: the
    service validates both before storing a vote, so this only fires on a bug.
    """
    eligible = sorted(set(eligible_countries))
    cast: dict[str, VoteChoice] = {}
    for vote in votes:
        code = vote.country_code
        if code in cast:
            raise VotingError(f"{code} voted more than once")
        if code not in eligible:
            raise VotingError(f"{code} is not entitled to vote")
        cast[code] = VoteChoice(vote.choice)

    yes_countries = tuple(c for c in eligible if cast.get(c) is VoteChoice.YES)
    no_countries = tuple(c for c in eligible if cast.get(c) is VoteChoice.NO)
    abstain_countries = tuple(c for c in eligible if cast.get(c) is VoteChoice.ABSTAIN)
    absent_countries = tuple(c for c in eligible if c not in cast)
    yes, no, abstain, absent = (len(yes_countries), len(no_countries), len(abstain_countries), len(absent_countries))

    counted = yes + no
    if rules.abstention is AbstentionBehavior.COUNTS_AGAINST:
        counted += abstain
    if rules.absent_counts_against:
        counted += absent
    needed = required_yes(counted, rules)
    vetoed_by = tuple(c for c in no_countries if rules.veto_enabled and c in rules.veto_members)

    majority_name = (
        "simple majority"
        if rules.majority is MajorityType.SIMPLE
        else f"qualified majority of {threshold_fraction(rules.threshold)}"  # type: ignore[arg-type]
    )
    if vetoed_by:
        passed = False
        reason = f"Vetoed: {', '.join(vetoed_by)} voted NO and holds a veto ({yes} YES, {no} NO, {abstain} ABSTAIN)."
    elif yes == 0:
        passed = False
        reason = f"Failed: no YES votes were cast ({no} NO, {abstain} ABSTAIN, {absent} absent)."
    elif yes >= needed:
        passed = True
        reason = f"Passed: {yes} YES of {counted} counted; {needed} required ({majority_name})."
    else:
        passed = False
        reason = f"Failed: {yes} YES of {counted} counted; {needed} required ({majority_name})."

    return VoteResult(
        passed=passed,
        yes=yes,
        no=no,
        abstain=abstain,
        absent=absent,
        eligible=len(eligible),
        counted=counted,
        required_yes=needed,
        vetoed_by=vetoed_by,
        reason=reason,
        yes_countries=yes_countries,
        no_countries=no_countries,
        abstain_countries=abstain_countries,
        absent_countries=absent_countries,
        rules=rules,
    )