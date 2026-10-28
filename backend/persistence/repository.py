"""The repository abstraction: the ONE seam between MUN logic and the database.

``ConferenceRepository`` is an abstract interface defined purely in terms of plain Python data
(``StoredConference`` and JSON-ready dicts/lists). MUN services depend on this interface, never on
SQLAlchemy, so the storage engine can be replaced (SQLite -> PostgreSQL) by writing a new concrete
repository and changing one line of wiring — no MUN logic changes.

``SqlAlchemyConferenceRepository`` is the only implementation today. It is engine-agnostic SQLAlchemy;
``db.py`` is what pins it to SQLite.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from .models_orm import (
    ConferenceRow,
    EventRow,
    ParticipantRow,
    ResolutionRow,
    ScoreRow,
    VoteRow,
)


@dataclass
class StoredConference:
    """A fully serialised conference as persisted/loaded — plain JSON-ready data, no ORM, no pydantic.

    ``conference``/``participants``/``events``/``resolutions``/``votes``/``world``/``speeches``/
    ``negotiations`` are the ``model_dump(mode="json")`` forms of the matching MUN objects, so the
    persistence service can rebuild the live record losslessly.
    """

    conference: dict
    participants: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    resolutions: list[dict] = field(default_factory=list)
    votes: list[dict] = field(default_factory=list)
    scores: list[dict] = field(default_factory=list)
    world: Optional[dict] = None
    speeches: list[dict] = field(default_factory=list)
    negotiations: list[dict] = field(default_factory=list)


class ConferenceRepository(ABC):
    """Durable storage for conferences and their history. Implementations must be safe to call from
    FastAPI's sync thread pool."""

    @abstractmethod
    def save_conference(self, stored: StoredConference) -> None:
        """Insert or fully replace a conference and all of its child rows (idempotent upsert)."""

    @abstractmethod
    def append_event(self, conference_id: str, event: dict) -> None:
        """Append a single recorded world event (append-only; duplicates by (conference, seq) ignored)."""

    @abstractmethod
    def save_scores(self, conference_id: str, scores: list[dict]) -> None:
        """Replace the stored deterministic scores for a conference."""

    @abstractmethod
    def get_conference(self, conference_id: str) -> Optional[StoredConference]:
        """Load one conference with all its history, or None if it was never persisted."""

    @abstractmethod
    def list_conference_ids(self) -> list[str]:
        """Every persisted conference id."""

    @abstractmethod
    def load_all(self) -> list[StoredConference]:
        """Load every persisted conference (used to rehydrate state after a restart)."""

    @abstractmethod
    def delete_conference(self, conference_id: str) -> None:
        """Remove a conference and its history (no error if it does not exist)."""

    @abstractmethod
    def clear(self) -> None:
        """Remove every persisted conference (used by tests)."""


class SqlAlchemyConferenceRepository(ConferenceRepository):
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    # --- writes ---------------------------------------------------------------------------------
    def save_conference(self, stored: StoredConference) -> None:
        conf = stored.conference
        cid = conf["id"]
        with self._session_factory() as session:
            # Replace any existing rows for this conference, then rewrite from the snapshot. Child rows
            # are deleted explicitly (not relying on DB-level ON DELETE CASCADE, which SQLite only
            # honours with PRAGMA foreign_keys=ON) so an upsert never collides with stale rows.
            for table in (ParticipantRow, EventRow, ResolutionRow, VoteRow, ScoreRow):
                session.execute(delete(table).where(table.conference_id == cid))
            session.execute(delete(ConferenceRow).where(ConferenceRow.id == cid))
            session.flush()

            session.add(
                ConferenceRow(
                    id=cid,
                    name=conf["name"],
                    committee=conf["committee"],
                    topic=conf["topic"],
                    status=conf["status"],
                    current_phase=conf["current_phase"],
                    created_at=str(conf.get("created_at")),
                    updated_at=str(conf.get("updated_at") or conf.get("created_at")),
                    conference_data=conf,
                    world_data=stored.world,
                    speeches_data=stored.speeches,
                    negotiations_data=stored.negotiations,
                )
            )
            for p in stored.participants:
                session.add(
                    ParticipantRow(
                        id=p["id"],
                        conference_id=cid,
                        name=p["name"],
                        role=p["role"],
                        country_code=p.get("country_code"),
                        score=float(p.get("score") or 0.0),
                        data=p,
                    )
                )
            for e in stored.events:
                session.add(
                    EventRow(
                        conference_id=cid,
                        event_id=int(e["id"]),
                        turn=int(e.get("turn") or 0),
                        type=e["type"],
                        actor=e.get("actor"),
                        target=e.get("target"),
                        message=e.get("message") or "",
                        timestamp=str(e.get("timestamp")),
                        data=e,
                    )
                )
            for r in stored.resolutions:
                session.add(
                    ResolutionRow(
                        id=r["id"],
                        conference_id=cid,
                        title=r.get("title") or "",
                        status=r.get("status") or "DRAFT",
                        data=r,
                    )
                )
            for v in stored.votes:
                session.add(
                    VoteRow(
                        id=v["id"],
                        conference_id=cid,
                        resolution_id=v["resolution_id"],
                        participant_id=v["participant_id"],
                        country_code=v.get("country_code"),
                        choice=v["choice"],
                        data=v,
                    )
                )
            for s in stored.scores:
                session.add(
                    ScoreRow(
                        conference_id=cid,
                        participant_id=s["participant_id"],
                        country_code=s.get("country_code"),
                        score=float(s.get("score") or 0.0),
                        breakdown=s,
                    )
                )
            session.commit()

    def append_event(self, conference_id: str, event: dict) -> None:
        with self._session_factory() as session:
            exists = session.execute(
                select(EventRow.row_id).where(
                    EventRow.conference_id == conference_id,
                    EventRow.event_id == int(event["id"]),
                )
            ).first()
            if exists is not None:
                return  # append-only: never store the same world event twice
            session.add(
                EventRow(
                    conference_id=conference_id,
                    event_id=int(event["id"]),
                    turn=int(event.get("turn") or 0),
                    type=event["type"],
                    actor=event.get("actor"),
                    target=event.get("target"),
                    message=event.get("message") or "",
                    timestamp=str(event.get("timestamp")),
                    data=event,
                )
            )
            session.commit()

    def save_scores(self, conference_id: str, scores: list[dict]) -> None:
        with self._session_factory() as session:
            session.execute(delete(ScoreRow).where(ScoreRow.conference_id == conference_id))
            for s in scores:
                session.add(
                    ScoreRow(
                        conference_id=conference_id,
                        participant_id=s["participant_id"],
                        country_code=s.get("country_code"),
                        score=float(s.get("score") or 0.0),
                        breakdown=s,
                    )
                )
            session.commit()

    def delete_conference(self, conference_id: str) -> None:
        with self._session_factory() as session:
            for table in (ParticipantRow, EventRow, ResolutionRow, VoteRow, ScoreRow):
                session.execute(delete(table).where(table.conference_id == conference_id))
            session.execute(delete(ConferenceRow).where(ConferenceRow.id == conference_id))
            session.commit()

    def clear(self) -> None:
        with self._session_factory() as session:
            for table in (ParticipantRow, EventRow, ResolutionRow, VoteRow, ScoreRow):
                session.execute(delete(table))
            session.execute(delete(ConferenceRow))
            session.commit()

    # --- reads ----------------------------------------------------------------------------------
    def _to_stored(self, session, row: ConferenceRow) -> StoredConference:
        participants = session.execute(
            select(ParticipantRow).where(ParticipantRow.conference_id == row.id)
        ).scalars().all()
        events = session.execute(
            select(EventRow).where(EventRow.conference_id == row.id).order_by(EventRow.event_id)
        ).scalars().all()
        resolutions = session.execute(
            select(ResolutionRow).where(ResolutionRow.conference_id == row.id)
        ).scalars().all()
        votes = session.execute(
            select(VoteRow).where(VoteRow.conference_id == row.id)
        ).scalars().all()
        scores = session.execute(
            select(ScoreRow).where(ScoreRow.conference_id == row.id).order_by(ScoreRow.score.desc())
        ).scalars().all()
        return StoredConference(
            conference=row.conference_data,
            participants=[p.data for p in participants],
            events=[e.data for e in events],
            resolutions=[r.data for r in resolutions],
            votes=[v.data for v in votes],
            scores=[s.breakdown for s in scores],
            world=row.world_data,
            speeches=row.speeches_data or [],
            negotiations=row.negotiations_data or [],
        )

    def get_conference(self, conference_id: str) -> Optional[StoredConference]:
        with self._session_factory() as session:
            row = session.get(ConferenceRow, conference_id)
            if row is None:
                return None
            return self._to_stored(session, row)

    def list_conference_ids(self) -> list[str]:
        with self._session_factory() as session:
            return list(session.execute(select(ConferenceRow.id)).scalars().all())

    def load_all(self) -> list[StoredConference]:
        with self._session_factory() as session:
            rows = session.execute(select(ConferenceRow)).scalars().all()
            return [self._to_stored(session, row) for row in rows]
