"""Phase 7: crises and crisis options - the crisis engine's data, effect tables and state rules.

Pure data and pure functions: no I/O, no clock, no simulation import. Whether a phase PERMITS crisis actions is decided
by `mun.phases` (`ActionType.CRISIS_RESPONSE`, only in the CRISIS phase); who may start, answer or close a crisis is
decided by the service. This module only says what a crisis is, what each response option does, and how a crisis may
change state.

Life of a crisis::

    ACTIVE --resolve (a JURY member)--------> RESOLVED
           --time / phase / conference end--> EXPIRED

ACTIVE is the only open state; RESOLVED and EXPIRED are final. History is append-only: crises are never deleted.

What a response does is NEVER decided by text. Each option carries `effects`, a table of integer deltas on the six
MUN world metrics, and that table is built here from two fixed lookups: the option's `action_type`
(`ACTION_PROFILES`) multiplied by the crisis's `severity` (`SEVERITY_MULTIPLIER`). Same action type + same severity =
same effects, always. Titles and descriptions are for humans (and, later, for agents that want to RECOMMEND an
option); they are never parsed, and no client or AI can supply an effects table of its own.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Iterable, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .enums import ConferencePhase, ConferenceStatus
from .metrics import MUNWorldMetrics
from .models import _to_utc, new_id

# The six MUN world metrics a crisis can change (the field names of MUNWorldMetrics - one source of truth).
METRIC_NAMES: tuple[str, ...] = tuple(MUNWorldMetrics.model_fields)

MAX_TITLE_CHARS = 120
MAX_DESCRIPTION_CHARS = 1000
MAX_EFFECT_DELTA = 50  # an option may move a metric by at most this much (the metrics themselves span 0-100)
MIN_OPTIONS = 2
MAX_OPTIONS = 8
CRISIS_TTL_SECONDS = 8 * 60  # default life of a crisis; the service never lets it outlive the CRISIS phase
MAX_ACTIVE_CRISES = 3  # open crises per conference at once


class CrisisSeverity(str, Enum):
    """Uppercase, exact-match, like the other MUN enums."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CrisisStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"


class CrisisActionType(str, Enum):
    """The kinds of response a crisis option can be. Each has one fixed effect profile (`ACTION_PROFILES`)."""

    DIPLOMACY = "DIPLOMACY"
    HUMANITARIAN_AID = "HUMANITARIAN_AID"
    CYBER_DEFENSE = "CYBER_DEFENSE"
    ECONOMIC_STABILIZATION = "ECONOMIC_STABILIZATION"
    SANCTIONS = "SANCTIONS"
    MILITARY_DEPLOYMENT = "MILITARY_DEPLOYMENT"
    NO_ACTION = "NO_ACTION"


class CrisisEndReason(str, Enum):
    """Why a crisis stopped being ACTIVE."""

    RESOLVED = "RESOLVED"  # a JURY member closed it
    TIME_EXPIRED = "TIME_EXPIRED"  # its `expires_at` passed (which is never later than the CRISIS phase's deadline)
    PHASE_CLOSED = "PHASE_CLOSED"  # the conference left the CRISIS phase, or ended


class CrisisOutcome(str, Enum):
    """How completely the delegates answered a crisis that was RESOLVED (decided by head-count, nothing else)."""

    UNADDRESSED = "UNADDRESSED"  # nobody responded
    PARTIALLY_ADDRESSED = "PARTIALLY_ADDRESSED"  # some, not all, delegates responded
    FULLY_ADDRESSED = "FULLY_ADDRESSED"  # every seated delegate responded


SEVERITY_MULTIPLIER: dict[CrisisSeverity, int] = {
    CrisisSeverity.LOW: 1,
    CrisisSeverity.MEDIUM: 2,
    CrisisSeverity.HIGH: 3,
    CrisisSeverity.CRITICAL: 4,
}

# Base effect of each action type, in metric points at severity LOW (x1). Positive = the metric goes up. Remember the
# metric directions (see `mun.metrics`): stability, trust and cyber-defence are better when higher; tension,
# humanitarian impact and economic risk are worse when higher.
ACTION_PROFILES: dict[CrisisActionType, dict[str, int]] = {
    CrisisActionType.DIPLOMACY: {"world_stability": 2, "diplomatic_tension": -3, "international_trust": 2},
    CrisisActionType.HUMANITARIAN_AID: {
        "humanitarian_impact": -4, "international_trust": 1, "world_stability": 1, "economic_risk": 1,
    },
    CrisisActionType.CYBER_DEFENSE: {"cybersecurity_level": 4, "economic_risk": -1, "international_trust": 1},
    CrisisActionType.ECONOMIC_STABILIZATION: {"economic_risk": -4, "world_stability": 1, "diplomatic_tension": -1},
    CrisisActionType.SANCTIONS: {
        "diplomatic_tension": 3, "economic_risk": 2, "international_trust": -2, "world_stability": -1,
    },
    CrisisActionType.MILITARY_DEPLOYMENT: {
        "diplomatic_tension": 4, "international_trust": -3, "humanitarian_impact": 1, "world_stability": 1,
    },
    CrisisActionType.NO_ACTION: {"world_stability": -1, "humanitarian_impact": 2, "international_trust": -1},
}

# Human-readable labels for the generated options: (title, description).
ACTION_LABELS: dict[CrisisActionType, tuple[str, str]] = {
    CrisisActionType.DIPLOMACY: (
        "Call emergency diplomatic talks",
        "Convene the affected parties and seek a negotiated de-escalation.",
    ),
    CrisisActionType.HUMANITARIAN_AID: (
        "Launch a humanitarian aid effort",
        "Send relief to those affected, at some cost to the budget.",
    ),
    CrisisActionType.CYBER_DEFENSE: (
        "Coordinate cyber defence",
        "Share threat intelligence and harden critical networks together.",
    ),
    CrisisActionType.ECONOMIC_STABILIZATION: (
        "Stabilise the markets",
        "Coordinate emergency economic measures to calm financial risk.",
    ),
    CrisisActionType.SANCTIONS: (
        "Impose sanctions",
        "Apply economic pressure on those held responsible, at a cost to trust.",
    ),
    CrisisActionType.MILITARY_DEPLOYMENT: (
        "Deploy a security force",
        "Show force to contain the situation, raising tension between states.",
    ),
    CrisisActionType.NO_ACTION: (
        "Monitor and wait",
        "Take no action yet. The situation is left to develop on its own.",
    ),
}

DEFAULT_OPTION_TYPES: tuple[CrisisActionType, ...] = (
    CrisisActionType.DIPLOMACY,
    CrisisActionType.HUMANITARIAN_AID,
    CrisisActionType.SANCTIONS,
    CrisisActionType.NO_ACTION,
)


def _check_effects(effects: dict[str, int]) -> dict[str, int]:
    unknown = sorted(set(effects) - set(METRIC_NAMES))
    if unknown:
        raise ValueError(f"unknown metric(s) {', '.join(unknown)}; valid metrics: {', '.join(METRIC_NAMES)}")
    for name, delta in effects.items():
        if abs(delta) > MAX_EFFECT_DELTA:
            raise ValueError(f"effect on {name} must be between -{MAX_EFFECT_DELTA} and {MAX_EFFECT_DELTA}, not {delta}")
    return effects


# Guard: a broken table must fail loudly at import time, never silently at crisis time.
if set(ACTION_PROFILES) != set(CrisisActionType) or set(ACTION_LABELS) != set(CrisisActionType):
    raise RuntimeError("ACTION_PROFILES and ACTION_LABELS must cover every CrisisActionType")
if set(SEVERITY_MULTIPLIER) != set(CrisisSeverity):
    raise RuntimeError("SEVERITY_MULTIPLIER must cover every CrisisSeverity")
for _profile in ACTION_PROFILES.values():
    _check_effects(_profile)
if len({tuple(sorted(p.items())) for p in ACTION_PROFILES.values()}) != len(ACTION_PROFILES):
    raise RuntimeError("every action type must have its own effect profile")
if any(max(abs(v) for v in p.values()) * max(SEVERITY_MULTIPLIER.values()) > MAX_EFFECT_DELTA for p in ACTION_PROFILES.values()):
    raise RuntimeError("a scaled effect would exceed MAX_EFFECT_DELTA")


def scaled_effects(action_type: CrisisActionType, severity: CrisisSeverity) -> dict[str, int]:
    """The effects of an option of `action_type` in a crisis of `severity`: the fixed profile times the multiplier."""
    multiplier = SEVERITY_MULTIPLIER[CrisisSeverity(severity)]
    return {metric: delta * multiplier for metric, delta in ACTION_PROFILES[CrisisActionType(action_type)].items()}


# --- Models -----------------------------------------------------------------------------------------


class CrisisOption(BaseModel):
    """One way to respond to a crisis. `effects` are integer metric deltas, fixed when the crisis is created."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: str = Field(default_factory=lambda: new_id("opt"), min_length=1)
    crisis_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    action_type: CrisisActionType
    effects: dict[str, StrictInt] = Field(
        default_factory=dict,
        description="Metric deltas applied when a delegate picks this option (any of the six MUN world metrics)",
    )

    @field_validator("effects")
    @classmethod
    def _effects_are_known_and_bounded(cls, effects: dict[str, int]) -> dict[str, int]:
        return _check_effects(effects)


class Crisis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(default_factory=lambda: new_id("crisis"), min_length=1)
    conference_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    severity: CrisisSeverity
    status: CrisisStatus = CrisisStatus.ACTIVE
    started_at: AwareDatetime
    expires_at: AwareDatetime
    created_by: str = Field(min_length=1, description="Id of the JURY participant who started the crisis")
    ended_at: Optional[AwareDatetime] = Field(default=None, description="When it was resolved or expired")
    end_reason: Optional[CrisisEndReason] = None
    outcome: Optional[CrisisOutcome] = Field(default=None, description="Set only when the crisis was RESOLVED")

    _utc = field_validator("started_at", "expires_at", "ended_at", mode="after")(_to_utc)

    @model_validator(mode="after")
    def _consistent(self) -> "Crisis":
        if self.expires_at <= self.started_at:
            raise ValueError("expires_at must be after started_at")
        if self.status is CrisisStatus.ACTIVE:
            if self.ended_at is not None or self.end_reason is not None or self.outcome is not None:
                raise ValueError("an ACTIVE crisis has no ended_at, end_reason or outcome")
            return self
        if self.ended_at is None or self.end_reason is None:
            raise ValueError(f"a {self.status.value} crisis needs ended_at and end_reason")
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not be before started_at")
        if self.status is CrisisStatus.RESOLVED:
            if self.end_reason is not CrisisEndReason.RESOLVED or self.outcome is None:
                raise ValueError("a RESOLVED crisis needs end_reason RESOLVED and an outcome")
        elif self.end_reason is CrisisEndReason.RESOLVED or self.outcome is not None:
            raise ValueError("an EXPIRED crisis ends by TIME_EXPIRED or PHASE_CLOSED and has no outcome")
        return self


class CrisisResponse(BaseModel):
    """A delegate's answer to a crisis: which option their country chose, and what it actually did to the world."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: str = Field(default_factory=lambda: new_id("cresp"), min_length=1)
    crisis_id: str = Field(min_length=1)
    conference_id: str = Field(min_length=1)
    participant_id: str = Field(min_length=1)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    option_id: str = Field(min_length=1)
    action_type: CrisisActionType
    applied: dict[str, float] = Field(
        default_factory=dict,
        description="The metric changes that really happened (after clamping to 0-100); metrics that did not move are omitted",
    )
    created_at: AwareDatetime

    _utc = field_validator("created_at", mode="after")(_to_utc)


class CrisisTemplate(BaseModel):
    """A ready-made crisis the backend knows: its text, severity and which kinds of response it offers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z_]*$", max_length=64)
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    severity: CrisisSeverity
    option_types: tuple[CrisisActionType, ...] = Field(min_length=MIN_OPTIONS, max_length=MAX_OPTIONS)


CRISIS_TEMPLATES: dict[str, CrisisTemplate] = {
    t.id: t
    for t in (
        CrisisTemplate(
            id="cyber_attack",
            title="Coordinated cyberattack on financial infrastructure",
            description="Banks and payment networks in several states are offline after a coordinated cyberattack.",
            severity=CrisisSeverity.HIGH,
            option_types=(
                CrisisActionType.CYBER_DEFENSE,
                CrisisActionType.DIPLOMACY,
                CrisisActionType.SANCTIONS,
                CrisisActionType.NO_ACTION,
            ),
        ),
        CrisisTemplate(
            id="humanitarian_disaster",
            title="Mass displacement after a regional disaster",
            description="A regional disaster has displaced hundreds of thousands and aid corridors are overwhelmed.",
            severity=CrisisSeverity.HIGH,
            option_types=(
                CrisisActionType.HUMANITARIAN_AID,
                CrisisActionType.DIPLOMACY,
                CrisisActionType.ECONOMIC_STABILIZATION,
                CrisisActionType.NO_ACTION,
            ),
        ),
        CrisisTemplate(
            id="market_crash",
            title="Global market turmoil",
            description="Stock and currency markets are falling fast and capital is leaving several economies.",
            severity=CrisisSeverity.MEDIUM,
            option_types=(
                CrisisActionType.ECONOMIC_STABILIZATION,
                CrisisActionType.DIPLOMACY,
                CrisisActionType.SANCTIONS,
                CrisisActionType.NO_ACTION,
            ),
        ),
        CrisisTemplate(
            id="border_incident",
            title="Armed incident on a disputed border",
            description="Forces of two neighbouring states have exchanged fire along a disputed border.",
            severity=CrisisSeverity.HIGH,
            option_types=(
                CrisisActionType.DIPLOMACY,
                CrisisActionType.MILITARY_DEPLOYMENT,
                CrisisActionType.SANCTIONS,
                CrisisActionType.NO_ACTION,
            ),
        ),
    )
}


class UnknownCrisisTemplateError(ValueError):
    """The named crisis template does not exist."""


class CrisisStateError(ValueError):
    """The requested crisis state change is not allowed (the crisis is already final)."""


def get_template(template_id: str) -> CrisisTemplate:
    try:
        return CRISIS_TEMPLATES[template_id]
    except KeyError:
        valid = ", ".join(sorted(CRISIS_TEMPLATES))
        raise UnknownCrisisTemplateError(f"Unknown crisis template '{template_id}'. Valid templates: {valid}") from None


# --- Pure rules -------------------------------------------------------------------------------------


def build_options(
    crisis_id: str, severity: CrisisSeverity, action_types: Iterable[CrisisActionType]
) -> list[CrisisOption]:
    """The response options of a crisis, one per action type, in the order given, with their effects worked out.

    Raises ValueError for fewer than MIN_OPTIONS or more than MAX_OPTIONS options, or a repeated action type.
    """
    types = [CrisisActionType(t) for t in action_types]
    if not MIN_OPTIONS <= len(types) <= MAX_OPTIONS:
        raise ValueError(f"A crisis needs between {MIN_OPTIONS} and {MAX_OPTIONS} options, not {len(types)}")
    if len(set(types)) != len(types):
        raise ValueError("A crisis cannot offer the same action type twice")
    options = []
    for action_type in types:
        title, description = ACTION_LABELS[action_type]
        options.append(
            CrisisOption(
                crisis_id=crisis_id,
                title=title,
                description=description,
                action_type=action_type,
                effects=scaled_effects(action_type, severity),
            )
        )
    return options


def is_final(crisis: Crisis) -> bool:
    return crisis.status is not CrisisStatus.ACTIVE


def expiry_reason(
    crisis: Crisis, now: datetime, phase: ConferencePhase, status: ConferenceStatus
) -> Optional[CrisisEndReason]:
    """Why an ACTIVE crisis is over by `now`, or None if it is still open (final crises are never expired again).

    The phase wins over the clock: a crisis cannot outlive the CRISIS phase or the conference.
    """
    if is_final(crisis):
        return None
    if status in (ConferenceStatus.COMPLETED, ConferenceStatus.CANCELLED) or ConferencePhase(phase) is not ConferencePhase.CRISIS:
        return CrisisEndReason.PHASE_CLOSED
    if now >= crisis.expires_at:
        return CrisisEndReason.TIME_EXPIRED
    return None


def close_crisis(
    crisis: Crisis,
    reason: CrisisEndReason,
    now: datetime,
    outcome: Optional[CrisisOutcome] = None,
) -> Crisis:
    """The crisis, closed: RESOLVED for reason RESOLVED, otherwise EXPIRED. A final crisis can never change again."""
    if is_final(crisis):
        raise CrisisStateError(f"Crisis '{crisis.id}' is already {crisis.status.value} and cannot change")
    reason = CrisisEndReason(reason)
    status = CrisisStatus.RESOLVED if reason is CrisisEndReason.RESOLVED else CrisisStatus.EXPIRED
    return Crisis.model_validate(
        {
            **crisis.model_dump(),
            "status": status,
            "ended_at": now,
            "end_reason": reason,
            "outcome": outcome if status is CrisisStatus.RESOLVED else None,
        }
    )


def outcome_for(responses: int, delegates: int) -> CrisisOutcome:
    """UNADDRESSED, PARTIALLY_ADDRESSED or FULLY_ADDRESSED, from the head-count alone."""
    if responses <= 0:
        return CrisisOutcome.UNADDRESSED
    if responses >= delegates:
        return CrisisOutcome.FULLY_ADDRESSED
    return CrisisOutcome.PARTIALLY_ADDRESSED