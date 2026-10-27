"""The MUN phase state machine, defined in ONE place.

    LOBBY -> ROLL_CALL -> OPENING_SPEECHES -> MODERATED_CAUCUS -> UNMODERATED_CAUCUS
          -> CRISIS -> DRAFTING -> VOTING -> RESULTS -> (conference status becomes COMPLETED)

Phase and status are separate things: `ConferencePhase` says where the debate is, `ConferenceStatus` says
whether the conference is running. COMPLETED is a status; finishing RESULTS completes the conference and the
phase stays RESULTS. Nothing outside this module hard-codes the order, the permissions or the durations.

This module is pure data and pure functions (no I/O, no clock, no simulation import). It defines what each phase
PERMITS; the speeches, negotiations, resolutions, voting, crisis handling and scoring those permissions will
guard are later phases.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, Optional

from .enums import ConferencePhase


class ActionType(str, Enum):
    """Kinds of conference action a phase can permit. Uppercase, exact-match, like the other MUN enums."""

    SPEECH = "SPEECH"
    MOTION = "MOTION"
    NEGOTIATION = "NEGOTIATION"
    ALLIANCE = "ALLIANCE"
    RESOLUTION_EDIT = "RESOLUTION_EDIT"
    CRISIS_RESPONSE = "CRISIS_RESPONSE"
    AMENDMENT = "AMENDMENT"
    VOTE = "VOTE"


COMPLETED_STEP = "COMPLETED"  # what follows RESULTS: the conference STATUS (not a phase) becomes COMPLETED

P = ConferencePhase

# The one authoritative order. Every phase appears exactly once.
PHASE_ORDER: tuple[ConferencePhase, ...] = (
    P.LOBBY,
    P.ROLL_CALL,
    P.OPENING_SPEECHES,
    P.MODERATED_CAUCUS,
    P.UNMODERATED_CAUCUS,
    P.CRISIS,
    P.DRAFTING,
    P.VOTING,
    P.RESULTS,
)

# Never skipped, whatever a committee's `allowed_phases` says: ROLL_CALL must precede any debate and
# RESULTS must precede completion.
REQUIRED_PHASES: frozenset[ConferencePhase] = frozenset({P.LOBBY, P.ROLL_CALL, P.RESULTS})

# What each phase permits. A phase missing here permits nothing (LOBBY, ROLL_CALL, RESULTS).
PHASE_ACTIONS: dict[ConferencePhase, frozenset[ActionType]] = {
    P.LOBBY: frozenset(),
    P.ROLL_CALL: frozenset(),
    P.OPENING_SPEECHES: frozenset({ActionType.SPEECH}),
    P.MODERATED_CAUCUS: frozenset({ActionType.SPEECH, ActionType.MOTION}),
    P.UNMODERATED_CAUCUS: frozenset({ActionType.NEGOTIATION, ActionType.ALLIANCE, ActionType.RESOLUTION_EDIT}),
    P.CRISIS: frozenset({ActionType.CRISIS_RESPONSE, ActionType.NEGOTIATION}),
    P.DRAFTING: frozenset({ActionType.RESOLUTION_EDIT, ActionType.AMENDMENT}),
    P.VOTING: frozenset({ActionType.VOTE}),
    P.RESULTS: frozenset(),
}

# Deadline length per phase in seconds; None = untimed (the phase ends when the conference is advanced).
# ROLL_CALL and RESULTS are untimed: they wait for the chair, not for a clock.
PHASE_DURATION_SECONDS: dict[ConferencePhase, Optional[int]] = {
    P.LOBBY: None,
    P.ROLL_CALL: None,
    P.OPENING_SPEECHES: 15 * 60,
    P.MODERATED_CAUCUS: 15 * 60,
    P.UNMODERATED_CAUCUS: 10 * 60,
    P.CRISIS: 10 * 60,
    P.DRAFTING: 15 * 60,
    P.VOTING: 5 * 60,
    P.RESULTS: None,
}

# Guard: adding a ConferencePhase without placing it in the flow must fail loudly at import time.
if set(PHASE_ORDER) != set(ConferencePhase) or len(PHASE_ORDER) != len(set(PHASE_ORDER)):
    raise RuntimeError("PHASE_ORDER must list every ConferencePhase exactly once")
if set(PHASE_ACTIONS) != set(ConferencePhase) or set(PHASE_DURATION_SECONDS) != set(ConferencePhase):
    raise RuntimeError("PHASE_ACTIONS and PHASE_DURATION_SECONDS must cover every ConferencePhase")


class InvalidTransitionError(ValueError):
    """The requested phase step is not the next valid one."""


def next_phase(
    current: ConferencePhase, allowed_phases: Optional[Iterable[ConferencePhase]] = None
) -> Optional[ConferencePhase]:
    """The phase that follows `current`, or None after RESULTS (the conference then completes).

    Optional debate phases a committee does not allow (`allowed_phases`) are skipped; REQUIRED_PHASES never are.
    """
    allowed = set(allowed_phases) if allowed_phases is not None else None
    for candidate in PHASE_ORDER[PHASE_ORDER.index(ConferencePhase(current)) + 1:]:
        if allowed is None or candidate in REQUIRED_PHASES or candidate in allowed:
            return candidate
    return None


def check_transition(
    current: ConferencePhase,
    target: Optional[ConferencePhase],
    allowed_phases: Optional[Iterable[ConferencePhase]] = None,
) -> None:
    """Accept only the single next step; raise InvalidTransitionError for a skip, a rewind or a repeat.

    `target` None means "complete the conference", which is only valid straight after RESULTS.
    """
    expected = next_phase(current, allowed_phases)
    if target is expected:
        return
    shown = target.value if target is not None else COMPLETED_STEP
    wanted = expected.value if expected is not None else COMPLETED_STEP
    raise InvalidTransitionError(
        f"Invalid phase transition {ConferencePhase(current).value} -> {shown}: the only valid next step is {wanted}"
    )


def allowed_actions(phase: ConferencePhase) -> frozenset[ActionType]:
    return PHASE_ACTIONS[ConferencePhase(phase)]


def is_action_allowed(phase: ConferencePhase, action: ActionType) -> bool:
    return ActionType(action) in allowed_actions(phase)


def phase_deadline(phase: ConferencePhase, started_at: datetime) -> Optional[datetime]:
    """When a phase that began at `started_at` is due to end, or None for an untimed phase."""
    seconds = PHASE_DURATION_SECONDS[ConferencePhase(phase)]
    return started_at + timedelta(seconds=seconds) if seconds is not None else None