"""Phase 10: lightweight SQLite persistence for the MUN simulation.

This package adds durable storage and deterministic delegate scoring WITHOUT introducing a second
state machine. The in-memory `ConferenceService` remains the single authoritative owner of live
state; persistence only mirrors that state to a relational store so a conference's state, event
history, resolutions/votes and scores survive a process restart.

Design boundaries (so SQLite can later be swapped for PostgreSQL without touching MUN logic):

  * ``ConferenceRepository`` (repository.py) is an ABSTRACT interface. ``SqlAlchemyConferenceRepository``
    is the only concrete implementation today; it talks to SQLite through SQLAlchemy. MUN services
    depend on the interface, never on SQLAlchemy.
  * ``PersistenceService`` (service.py) snapshots a live ``ConferenceRecord`` into the repository and
    rehydrates records back out. It is the only code that converts between the domain objects and the
    stored rows.
  * ``scoring.py`` derives deterministic delegate scores from the recorded event history (a pure
    function of what actually happened — never from AI output).

Nothing here lets the AI write persisted state: only the validated ``ConferenceService`` produces the
records that get persisted, exactly as before (AI proposes -> backend validates -> deterministic rules
apply -> state changes -> event recorded -> [new] snapshot persisted).
"""
from __future__ import annotations

from .repository import ConferenceRepository, SqlAlchemyConferenceRepository, StoredConference
from .scoring import ScoreBreakdown, score_participants
from .service import PersistenceService, NullPersistenceService

__all__ = [
    "ConferenceRepository",
    "SqlAlchemyConferenceRepository",
    "StoredConference",
    "ScoreBreakdown",
    "score_participants",
    "PersistenceService",
    "NullPersistenceService",
]
