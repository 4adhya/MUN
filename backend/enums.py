"""Enums for the MUN domain layer.

All enums are `str` enums whose value equals their name, so they serialize to
plain uppercase strings in JSON (e.g. "MODERATED_CAUCUS"). Matching is exact:
"active" is rejected, "ACTIVE" is accepted.
"""
from __future__ import annotations

from enum import Enum


class ConferenceStatus(str, Enum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ConferencePhase(str, Enum):
    """Phases a conference can be in. Transition rules belong to Phase 3."""

    LOBBY = "LOBBY"
    ROLL_CALL = "ROLL_CALL"
    OPENING_SPEECHES = "OPENING_SPEECHES"
    MODERATED_CAUCUS = "MODERATED_CAUCUS"
    UNMODERATED_CAUCUS = "UNMODERATED_CAUCUS"
    CRISIS = "CRISIS"
    DRAFTING = "DRAFTING"
    VOTING = "VOTING"
    RESULTS = "RESULTS"


class ParticipantRole(str, Enum):
    GUEST = "GUEST"
    PARTICIPANT = "PARTICIPANT"
    JURY = "JURY"


class Committee(str, Enum):
    UNSC = "UNSC"
    GLOBAL_CYBERSECURITY = "GLOBAL_CYBERSECURITY"