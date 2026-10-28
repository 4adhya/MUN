"""Relational tables mirroring the authoritative in-memory MUN records.

Each row keeps a few queryable top-level columns PLUS a ``data`` JSON blob holding the full domain
object exactly as the MUN pydantic models serialise it. The JSON blob keeps the MUN models the single
source of truth for shape (no field has to be re-declared relationally and kept in sync), while the
columns make the common lookups (by conference, by status, ordering by sequence) efficient and make
the schema portable to PostgreSQL unchanged (all columns are standard SQL types).

Nothing here contains MUN logic; these are plain storage rows written and read by the repository.
"""
from __future__ import annotations

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class ConferenceRow(Base):
    __tablename__ = "conferences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    committee: Mapped[str] = mapped_column(String(64), nullable=False)
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    current_phase: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)
    # Full snapshots of the parts that have no table of their own (the conference's world, speeches,
    # negotiations). The entities that DO have tables (participants, events, resolutions, votes,
    # scores) are stored as rows, below, so they can be queried independently.
    conference_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    world_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    speeches_data: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    negotiations_data: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    participants: Mapped[list["ParticipantRow"]] = relationship(
        back_populates="conference", cascade="all, delete-orphan", passive_deletes=True
    )
    events: Mapped[list["EventRow"]] = relationship(
        back_populates="conference", cascade="all, delete-orphan", passive_deletes=True
    )
    resolutions: Mapped[list["ResolutionRow"]] = relationship(
        back_populates="conference", cascade="all, delete-orphan", passive_deletes=True
    )
    votes: Mapped[list["VoteRow"]] = relationship(
        back_populates="conference", cascade="all, delete-orphan", passive_deletes=True
    )
    scores: Mapped[list["ScoreRow"]] = relationship(
        back_populates="conference", cascade="all, delete-orphan", passive_deletes=True
    )


class ParticipantRow(Base):
    __tablename__ = "participants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conference_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    conference: Mapped[ConferenceRow] = relationship(back_populates="participants")


class EventRow(Base):
    """One recorded DiplomacyEvent of a conference's world. Append-only history."""

    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("conference_id", "event_id", name="uq_event_conference_seq"),)

    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conference_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[int] = mapped_column(Integer, nullable=False)  # sequence within the conference world
    turn: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    conference: Mapped[ConferenceRow] = relationship(back_populates="events")


class ResolutionRow(Base):
    __tablename__ = "resolutions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conference_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    conference: Mapped[ConferenceRow] = relationship(back_populates="resolutions")


class VoteRow(Base):
    __tablename__ = "votes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conference_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resolution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    participant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    choice: Mapped[str] = mapped_column(String(16), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    conference: Mapped[ConferenceRow] = relationship(back_populates="votes")


class ScoreRow(Base):
    """Deterministic delegate score, derived from the recorded event history."""

    __tablename__ = "scores"
    __table_args__ = (UniqueConstraint("conference_id", "participant_id", name="uq_score_conference_participant"),)

    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conference_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conferences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)

    conference: Mapped[ConferenceRow] = relationship(back_populates="scores")
