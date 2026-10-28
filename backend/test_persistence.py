"""Phase 10 tests: SQLite persistence, event history, state reload and deterministic scoring.

These exercise the repository CRUD directly, prove events are persisted, prove a conference's full
state/history reloads into a fresh service after a "restart", and prove delegate scoring is
deterministic and derived only from the recorded event history.

Everything uses an in-memory SQLite database (``sqlite://``) so no file is touched.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.conference_service import ConferenceService, stored_to_record
from backend.main import app
from backend.persistence.db import create_db_engine, create_session_factory, init_db
from backend.persistence.repository import (
    SqlAlchemyConferenceRepository,
    StoredConference,
)
from backend.persistence.scoring import score_participants
from backend.persistence.service import PersistenceService, record_to_stored


@pytest.fixture()
def repo():
    engine = create_db_engine("sqlite://")  # in-memory, shared connection (StaticPool)
    init_db(engine)
    return SqlAlchemyConferenceRepository(create_session_factory(engine))


@pytest.fixture()
def service_with_persistence(repo):
    """A fresh ConferenceService wired to an in-memory SQLite repository."""
    svc = ConferenceService()
    svc.set_persistence(PersistenceService(repo))
    return svc


def _run_full_conference(svc: ConferenceService):
    """Drive a conference through its whole lifecycle on the given service; return ids for assertions."""
    from backend.resolution_service import ResolutionService

    snap = svc.create("Demo", "UNSC", "A topic")
    cid = snap.id
    delegate = svc.join(cid, "India delegation", "PARTICIPANT", "India")
    svc.join(cid, "Jury", "JURY")
    svc.start(cid)
    # ROLL_CALL -> OPENING_SPEECHES, then a real speech
    svc.advance(cid)
    code = delegate.country_code
    svc.submit_speech(cid, delegate.id, code, "The delegation of India calls for calm.")
    return cid, delegate.id, code


# --- repository CRUD ---------------------------------------------------------------------------
def test_repository_crud_roundtrip(repo):
    stored = StoredConference(
        conference={
            "id": "conf-test", "name": "N", "committee": "UNSC", "topic": "T",
            "status": "WAITING", "current_phase": "LOBBY",
            "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        },
        participants=[{"id": "p1", "name": "A", "role": "PARTICIPANT", "country_code": "IN", "score": 0.0}],
        events=[{"id": 1, "turn": 0, "type": "conference_start", "actor": "conf-test",
                 "target": None, "message": "started", "timestamp": "2026-01-01T00:00:00+00:00", "effects": {}}],
    )
    assert repo.get_conference("conf-test") is None  # nothing yet
    repo.save_conference(stored)

    loaded = repo.get_conference("conf-test")
    assert loaded is not None
    assert loaded.conference["name"] == "N"
    assert [p["id"] for p in loaded.participants] == ["p1"]
    assert [e["type"] for e in loaded.events] == ["conference_start"]
    assert repo.list_conference_ids() == ["conf-test"]

    # Update (upsert replaces child rows, never duplicates them).
    stored.participants.append({"id": "p2", "name": "B", "role": "JURY", "country_code": None, "score": 0.0})
    repo.save_conference(stored)
    assert len(repo.get_conference("conf-test").participants) == 2

    repo.delete_conference("conf-test")
    assert repo.get_conference("conf-test") is None
    assert repo.list_conference_ids() == []


def test_repository_append_event_is_append_only(repo):
    repo.save_conference(StoredConference(conference={
        "id": "c", "name": "n", "committee": "UNSC", "topic": "t",
        "status": "ACTIVE", "current_phase": "ROLL_CALL",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
    }))
    ev = {"id": 1, "turn": 0, "type": "speech_submitted", "actor": "india", "target": None,
          "message": "m", "timestamp": "2026-01-01T00:00:00+00:00", "effects": {}}
    repo.append_event("c", ev)
    repo.append_event("c", ev)  # same (conference, seq) must not duplicate
    assert len(repo.get_conference("c").events) == 1
    repo.append_event("c", {**ev, "id": 2})
    assert len(repo.get_conference("c").events) == 2


def test_clear_removes_everything(repo):
    repo.save_conference(StoredConference(conference={
        "id": "c", "name": "n", "committee": "UNSC", "topic": "t", "status": "WAITING",
        "current_phase": "LOBBY", "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }))
    assert repo.list_conference_ids() == ["c"]
    repo.clear()
    assert repo.list_conference_ids() == []


# --- event persistence through the live service ------------------------------------------------
def test_conference_lifecycle_is_persisted(service_with_persistence, repo):
    cid, pid, code = _run_full_conference(service_with_persistence)

    stored = repo.get_conference(cid)
    assert stored is not None
    assert stored.conference["status"] == "ACTIVE"
    assert stored.conference["current_phase"] == "OPENING_SPEECHES"
    # The start event and the speech event are both persisted in the durable history.
    types = [e["type"] for e in stored.events]
    assert "conference_start" in types
    assert "speech_submitted" in types
    assert any(p["country_code"] == code for p in stored.participants)


# --- state reload after a "restart" ------------------------------------------------------------
def test_state_and_history_reload_after_restart(service_with_persistence, repo):
    cid, pid, code = _run_full_conference(service_with_persistence)
    events_before = [e["type"] for e in repo.get_conference(cid).events]

    # Simulate a process restart: a brand-new service, same durable store, nothing in memory.
    fresh = ConferenceService()
    fresh.set_persistence(PersistenceService(repo))
    restored = fresh.load_persisted()
    assert restored == 1

    snap = fresh.get(cid)  # would raise NotFound if the reload failed
    assert snap.id == cid
    assert snap.status == "ACTIVE"
    assert snap.current_phase == "OPENING_SPEECHES"
    assert [c.country_code for c in snap.world.countries][:1] == ["IN"]
    # The reloaded world keeps its full recorded event history.
    reloaded_types = [e.type for e in fresh._get(cid).world.events]
    assert reloaded_types == events_before
    # And the reloaded conference can still be advanced (it is a real live record, not a snapshot).
    nxt = fresh.advance(cid)
    assert nxt.current_phase == "MODERATED_CAUCUS"


def test_stored_to_record_roundtrip_preserves_everything(service_with_persistence, repo):
    cid, pid, code = _run_full_conference(service_with_persistence)
    stored = repo.get_conference(cid)
    record = stored_to_record(stored)
    assert record.conference.id == cid
    assert record.world is not None and len(record.world.events) >= 2
    assert any(p.id == pid for p in record.participants)
    # Re-serialising the rebuilt record reproduces the same conference id and phase.
    again = record_to_stored(record)
    assert again.conference["id"] == cid
    assert again.conference["current_phase"] == "OPENING_SPEECHES"


# --- deterministic scoring ---------------------------------------------------------------------
def test_scoring_is_deterministic_and_event_derived(service_with_persistence):
    cid, pid, code = _run_full_conference(service_with_persistence)
    scores_a = service_with_persistence.get_scores(cid)
    scores_b = service_with_persistence.get_scores(cid)
    assert scores_a == scores_b  # pure function of the recorded history

    me = next(s for s in scores_a if s["participant_id"] == pid)
    assert me["counts"].get("speech") == 1  # the one speech was scored
    assert me["score"] > 0


def test_scoring_rewards_more_activity(service_with_persistence):
    cid, pid, code = _run_full_conference(service_with_persistence)
    before = next(s for s in service_with_persistence.get_scores(cid) if s["participant_id"] == pid)["score"]
    # A second speech should strictly increase the score (deterministic +points).
    service_with_persistence.submit_speech(cid, pid, code, "A second statement from India.")
    after = next(s for s in service_with_persistence.get_scores(cid) if s["participant_id"] == pid)["score"]
    assert after > before


def test_scores_persist_and_reload(service_with_persistence, repo):
    cid, pid, code = _run_full_conference(service_with_persistence)
    stored = repo.get_conference(cid)
    assert stored.scores, "scores should be persisted alongside the conference"
    me = next(s for s in stored.scores if s["participant_id"] == pid)
    assert me["score"] > 0


def test_guests_and_jury_are_not_scored(service_with_persistence):
    cid, pid, code = _run_full_conference(service_with_persistence)
    scores = service_with_persistence.get_scores(cid)
    # Only the single seated delegate is scored; the jury member is not.
    assert len(scores) == 1
    assert scores[0]["participant_id"] == pid


# --- the default (no persistence) behaviour is unchanged ---------------------------------------
def test_default_service_has_no_persistence_and_still_works():
    svc = ConferenceService()  # no persistence attached
    snap = svc.create("Plain", "UNSC", "t")
    assert snap.status == "WAITING"
    assert svc.load_persisted() == 0  # NullPersistenceService restores nothing
    # Scores still compute in-memory from the (empty) history without any database.
    svc.join(snap.id, "D", "PARTICIPANT", "India")
    svc.join(snap.id, "J", "JURY")
    svc.start(snap.id)
    assert svc.get_scores(snap.id) == [
        s for s in svc.get_scores(snap.id)
    ]  # deterministic, no error


# --- the shared app singleton is unaffected by default -----------------------------------------
def test_app_endpoints_still_work_without_persistence_configured():
    client = TestClient(app)
    r = client.post("/conference/create", json={"name": "X", "committee": "UNSC", "topic": "t"})
    assert r.status_code == 201


# --- default-on application configuration (Phase 10 enabled automatically) ---------------------
import backend.main as main
from backend.persistence.db import DEFAULT_DATABASE_URL, resolve_database_url
from backend.persistence.service import NullPersistenceService, PersistenceService


def _clear_persistence_env(monkeypatch):
    monkeypatch.delenv("MUN_PERSISTENCE", raising=False)
    monkeypatch.delenv("MUN_DATABASE_URL", raising=False)


def test_default_database_url_is_relative_sqlite(monkeypatch):
    _clear_persistence_env(monkeypatch)
    assert DEFAULT_DATABASE_URL == "sqlite:///./mun.db"
    assert resolve_database_url() == "sqlite:///./mun.db"


def test_persistence_is_enabled_by_default_with_no_env(monkeypatch):
    _clear_persistence_env(monkeypatch)
    assert main._persistence_enabled() is True


def test_mun_persistence_false_disables(monkeypatch):
    _clear_persistence_env(monkeypatch)
    for value in ("false", "0", "no", "off", "FALSE", "Off"):
        monkeypatch.setenv("MUN_PERSISTENCE", value)
        assert main._persistence_enabled() is False, value


def test_mun_database_url_overrides_default(monkeypatch):
    _clear_persistence_env(monkeypatch)
    monkeypatch.setenv("MUN_DATABASE_URL", "sqlite:///custom.db")
    assert resolve_database_url() == "sqlite:///custom.db"
    # An explicit URL also keeps persistence enabled.
    assert main._persistence_enabled() is True


def test_configure_persistence_defaults_to_sqlite_and_creates_db(monkeypatch, tmp_path):
    """With no env vars, configure_persistence() must enable SQLite and create ./mun.db automatically."""
    _clear_persistence_env(monkeypatch)
    monkeypatch.chdir(tmp_path)  # so the relative ./mun.db lands in a temp dir, not the repo
    try:
        enabled = main.configure_persistence()
        assert enabled is True
        # The shared service now has a real persistence collaborator.
        assert isinstance(main.conference_service.persistence, PersistenceService)
        # A conference created now is persisted to the default file, which is created on disk.
        snap = main.conference_service.create("Default On", "UNSC", "t")
        assert (tmp_path / "mun.db").exists()
        assert snap.id in main.conference_service.persistence.repository.list_conference_ids()
    finally:
        main.conference_service.set_persistence(NullPersistenceService())


def test_default_persistence_round_trips_without_env(monkeypatch, tmp_path):
    """A conference + event persists and reloads with NO environment variables set."""
    _clear_persistence_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    try:
        assert main.configure_persistence() is True
        svc = main.conference_service
        snap = svc.create("No-Env Durability", "UNSC", "topic")
        cid = snap.id
        delegate = svc.join(cid, "India delegation", "PARTICIPANT", "India")
        svc.join(cid, "Jury", "JURY")
        svc.start(cid)
        svc.advance(cid)  # ROLL_CALL -> OPENING_SPEECHES
        svc.submit_speech(cid, delegate.id, delegate.country_code, "India calls for calm.")

        # Rebuild from the default SQLite file into a fresh service (simulated restart).
        from backend.conference_service import ConferenceService
        from backend.persistence.db import create_db_engine, create_session_factory, init_db
        from backend.persistence.repository import SqlAlchemyConferenceRepository

        engine = create_db_engine()  # resolves to sqlite:///./mun.db in tmp_path
        init_db(engine)
        fresh = ConferenceService()
        fresh.set_persistence(PersistenceService(SqlAlchemyConferenceRepository(create_session_factory(engine))))
        assert fresh.load_persisted() == 1
        reloaded = fresh.get(cid)
        assert reloaded.current_phase == "OPENING_SPEECHES"
        assert [e.type for e in fresh._get(cid).world.events] == ["conference_start", "speech_submitted"]
    finally:
        main.conference_service.set_persistence(NullPersistenceService())


def test_mun_persistence_false_keeps_app_in_memory(monkeypatch, tmp_path):
    _clear_persistence_env(monkeypatch)
    monkeypatch.setenv("MUN_PERSISTENCE", "false")
    monkeypatch.chdir(tmp_path)
    assert main.configure_persistence() is False
    # No database file is created when persistence is explicitly disabled.
    assert not (tmp_path / "mun.db").exists()
