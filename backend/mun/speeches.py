"""Phase 4: speeches and the speaker queue (the debate engine's data and rules).

Pure data and pure functions: no I/O, no clock, no simulation import. Whether a phase PERMITS speeches is decided
by `mun.phases` (`ActionType.SPEECH`); this module only says what a speech is and who holds the floor.

The floor works like this:

  * When a conference enters a phase that permits speeches, `open_floor` seats every delegate in the queue (in the
    order given) and gives the floor to the first one.
  * Only the delegate holding the floor may submit speeches (several are allowed during one turn).
  * `pass_floor` (the chair's "next speaker") moves the current speaker to `completed` and gives the floor to the
    next delegate in the queue. After the last delegate it leaves nobody holding the floor.
  * Entering any other phase discards the queue (`open_floor` returns an empty `SpeakerState`).

Speeches themselves are never discarded: they are an append-only history for the conference.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from .enums import ConferencePhase
from .models import _to_utc, new_id, utcnow
from .phases import ActionType, is_action_allowed

MAX_SPEECH_CHARS = 5000


class Speech(BaseModel):
    """One speech given by a delegate. Immutable: history is never edited."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: str = Field(default_factory=lambda: new_id("speech"), min_length=1)
    conference_id: str = Field(min_length=1)
    participant_id: str = Field(min_length=1)
    country_code: str = Field(
        pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2 code of the country the delegate spoke for"
    )
    text: str = Field(min_length=1, max_length=MAX_SPEECH_CHARS)
    phase: ConferencePhase = Field(description="The conference phase the speech was given in (set by the backend)")
    created_at: AwareDatetime = Field(default_factory=utcnow)

    _utc = field_validator("created_at", mode="after")(_to_utc)

    @field_validator("country_code", mode="before")
    @classmethod
    def _normalise_code(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class NoSpeakersRemainingError(ValueError):
    """The floor cannot be passed: no queue is open, or every delegate has already had a turn."""


@dataclass(frozen=True)
class SpeakerState:
    """Who holds the floor and who is waiting, as participant ids. Immutable; the functions below return new states."""

    phase: Optional[ConferencePhase] = None  # the speaking phase this queue belongs to; None = no floor is open
    current: Optional[str] = None  # the delegate holding the floor
    queue: tuple[str, ...] = ()  # delegates still waiting, in speaking order
    completed: tuple[str, ...] = ()  # delegates whose turn is over, in the order they spoke


def open_floor(phase: ConferencePhase, speaker_ids: Iterable[str]) -> SpeakerState:
    """The speaker state when a conference enters `phase`.

    A phase that does not permit speeches (or has no delegates) gets an empty state. Otherwise the first delegate
    holds the floor and the rest queue behind them. Duplicates are dropped; the given order is kept.
    """
    phase = ConferencePhase(phase)
    if not is_action_allowed(phase, ActionType.SPEECH):
        return SpeakerState()
    ids = tuple(dict.fromkeys(speaker_ids))
    if not ids:
        return SpeakerState(phase=phase)
    return SpeakerState(phase=phase, current=ids[0], queue=ids[1:])


def pass_floor(state: SpeakerState) -> SpeakerState:
    """The state after the current speaker's turn ends. Raises NoSpeakersRemainingError if there is nothing to pass."""
    if state.phase is None:
        raise NoSpeakersRemainingError("No speaker queue is open in this phase")
    if state.current is None and not state.queue:
        raise NoSpeakersRemainingError("The speaker queue is exhausted: every delegate has already had a turn")
    completed = state.completed + ((state.current,) if state.current is not None else ())
    if state.queue:
        return SpeakerState(phase=state.phase, current=state.queue[0], queue=state.queue[1:], completed=completed)
    return SpeakerState(phase=state.phase, current=None, queue=(), completed=completed)