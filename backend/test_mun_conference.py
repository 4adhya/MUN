"""Phase 1: Conference model."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.mun import Committee, Conference, ConferencePhase, ConferenceStatus


def make(**over):
    return Conference(**{"name": "Cyber Summit", "committee": "GLOBAL_CYBERSECURITY", "topic": "Global Cybersecurity Crisis", **over})


def test_valid_conference_gets_defaults():
    c = make()
    assert c.id.startswith("conf-") and len(c.id) > 5
    assert c.committee is Committee.GLOBAL_CYBERSECURITY
    assert c.status is ConferenceStatus.WAITING
    assert c.current_phase is ConferencePhase.LOBBY
    assert c.phase_started_at is None and c.phase_ends_at is None
    assert c.created_at.tzinfo is not None and c.created_at.utcoffset() == timedelta(0)


def test_ids_are_unique():
    assert len({make().id for _ in range(50)}) == 50


@pytest.mark.parametrize("status", [s.value for s in ConferenceStatus])
def test_every_status_accepted(status):
    assert make(status=status).status.value == status


@pytest.mark.parametrize("phase", [p.value for p in ConferencePhase])
def test_every_phase_accepted(phase):
    assert make(current_phase=phase).current_phase.value == phase


def test_required_phases_exist():
    assert {p.value for p in ConferencePhase} >= {
        "LOBBY", "ROLL_CALL", "OPENING_SPEECHES", "MODERATED_CAUCUS", "UNMODERATED_CAUCUS",
        "CRISIS", "DRAFTING", "VOTING", "RESULTS",
    }


@pytest.mark.parametrize("bad", ["RUNNING", "active", "", None, 3])
def test_invalid_status_rejected(bad):
    with pytest.raises(ValidationError):
        make(status=bad)


@pytest.mark.parametrize("bad", ["INTERMISSION", "lobby", "", None])
def test_invalid_phase_rejected(bad):
    with pytest.raises(ValidationError):
        make(current_phase=bad)


@pytest.mark.parametrize("missing", ["name", "committee", "topic"])
def test_required_fields(missing):
    data = {"name": "X", "committee": "UNSC", "topic": "T"}
    del data[missing]
    with pytest.raises(ValidationError):
        Conference(**data)


@pytest.mark.parametrize("field", ["name", "topic"])
def test_blank_text_rejected(field):
    with pytest.raises(ValidationError):
        make(**{field: "   "})


def test_invalid_committee_rejected():
    with pytest.raises(ValidationError):
        make(committee="NATO")


def test_naive_datetimes_rejected():
    for field in ("phase_started_at", "phase_ends_at", "created_at"):
        with pytest.raises(ValidationError):
            make(**{field: datetime(2026, 1, 1, 12, 0)})


def test_aware_datetimes_normalised_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    c = make(phase_started_at=datetime(2026, 1, 1, 17, 30, tzinfo=ist))
    assert c.phase_started_at.utcoffset() == timedelta(0)
    assert c.phase_started_at == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_phase_window_must_be_ordered():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert make(phase_started_at=t, phase_ends_at=t + timedelta(minutes=5)).phase_ends_at > t
    with pytest.raises(ValidationError):
        make(phase_started_at=t, phase_ends_at=t - timedelta(minutes=5))


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        make(commitee="UNSC")


def test_json_round_trip():
    c = make(status="ACTIVE", current_phase="VOTING")
    again = Conference.model_validate_json(c.model_dump_json())
    assert again == c and '"status":"ACTIVE"' in c.model_dump_json()