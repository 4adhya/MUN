"""The persistence service: converts between live ConferenceRecords and the repository.

This is the only module that knows BOTH the in-memory record shape and the stored form. It:
  * snapshots a live record into a ``StoredConference`` (serialising the MUN pydantic objects and
    computing the deterministic scores), and persists it through the repository;
  * appends a single recorded event to the durable log (cheap, append-only);
  * rehydrates a ``StoredConference`` back into a fresh in-memory record so a conference's full
    state/history survives a restart.

It never contains MUN rules and never advances a phase; it mirrors whatever the authoritative
``ConferenceService`` already decided. The AI never reaches this code: only validated service
operations produce the records that get snapshotted here.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from .repository import ConferenceRepository, StoredConference
from .scoring import score_participants

if TYPE_CHECKING:  # avoid a hard import cycle; the record type lives in conference_service
    from ..conference_service import ConferenceRecord

logger = logging.getLogger("worldevent.persistence")


def _dump(obj) -> dict:
    return obj.model_dump(mode="json")


def _dump_list(objs) -> list:
    return [o.model_dump(mode="json") for o in objs]


def compute_scores(record: "ConferenceRecord") -> list[dict]:
    """Deterministic delegate scores for a record, as JSON-ready dicts."""
    breakdowns = score_participants(record.participants, record.world)
    return [
        {
            "participant_id": b.participant_id,
            "country_code": b.country_code,
            "name": b.name,
            "score": b.score,
            "counts": b.counts,
        }
        for b in breakdowns
    ]


def record_to_stored(record: "ConferenceRecord") -> StoredConference:
    """Serialise a live record into the persisted form, including freshly computed scores.

    ``conference`` is exactly ``Conference.model_dump()`` (so it rehydrates cleanly against the
    strict MUN model); the ``updated_at`` convenience column is derived by the repository and never
    injected into this dict.
    """
    conference = _dump(record.conference)
    world = _dump(record.world) if record.world is not None else None
    events = (world or {}).get("events", []) if world is not None else []

    return StoredConference(
        conference=conference,
        participants=_dump_list(record.participants),
        events=events,
        resolutions=_dump_list(record.resolutions),
        votes=_dump_list(record.votes),
        scores=compute_scores(record),
        world=world,
        speeches=_dump_list(record.speeches),
        negotiations=_dump_list(record.negotiations),
    )


class PersistenceService:
    """Persist/reload conferences through a ``ConferenceRepository``.

    Construct it with a concrete repository (``SqlAlchemyConferenceRepository`` today). The
    conference service calls ``persist(record)`` after state changes and ``append_event`` for the
    durable log; ``restore_records`` rebuilds live records at startup.
    """

    def __init__(self, repository: ConferenceRepository) -> None:
        self._repo = repository

    @property
    def repository(self) -> ConferenceRepository:
        return self._repo

    def persist(self, record: "ConferenceRecord") -> None:
        """Snapshot and store a record. Failures are logged, never raised: persistence must never
        break a live, already-validated operation."""
        try:
            self._repo.save_conference(record_to_stored(record))
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to persist conference %s", getattr(record.conference, "id", "?"))

    def append_event(self, conference_id: str, event) -> None:
        try:
            self._repo.append_event(conference_id, _dump(event))
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to append event for conference %s", conference_id)

    def scores_for(self, conference_id: str) -> list[dict]:
        stored = self._repo.get_conference(conference_id)
        return stored.scores if stored else []

    def load(self, conference_id: str) -> Optional[StoredConference]:
        return self._repo.get_conference(conference_id)

    def restore_records(self) -> list["ConferenceRecord"]:
        """Rebuild every persisted conference into a live in-memory record (used at startup)."""
        from ..conference_service import stored_to_record  # local import avoids a cycle

        records: list["ConferenceRecord"] = []
        for stored in self._repo.load_all():
            try:
                records.append(stored_to_record(stored))
            except Exception:  # pragma: no cover - a corrupt row must not stop startup
                logger.exception("Failed to restore conference %s", stored.conference.get("id"))
        return records


class NullPersistenceService:
    """A no-op persistence service: keeps the in-memory behaviour identical when persistence is off.

    Every method is a harmless no-op so the conference service can call persistence unconditionally
    without any branching, and existing tests/behaviour are unaffected.
    """

    def persist(self, record) -> None:
        return None

    def append_event(self, conference_id: str, event) -> None:
        return None

    def scores_for(self, conference_id: str) -> list[dict]:
        return []

    def load(self, conference_id: str):
        return None

    def restore_records(self):
        return []
