"""Phase 1: Participant model."""
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.mun import Participant, ParticipantRole


def make(**over):
    return Participant(**{"name": "Palak", "role": "PARTICIPANT", "conference_id": "conf-1", "country_code": "IN", **over})


def test_valid_participant_with_country():
    p = make()
    assert p.id.startswith("part-")
    assert p.role is ParticipantRole.PARTICIPANT
    assert p.country_code == "IN" and p.conference_id == "conf-1"
    assert p.score == 0.0
    assert p.joined_at.tzinfo is not None and p.joined_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize("role", ["GUEST", "PARTICIPANT", "JURY"])
def test_all_roles_accepted(role):
    assert make(role=role).role.value == role


def test_country_is_optional_for_guest_and_jury():
    assert make(role="GUEST", country_code=None).country_code is None
    assert Participant(name="J", role="JURY", conference_id="c").country_code is None


def test_country_code_normalised():
    assert make(country_code=" gb ").country_code == "GB"


@pytest.mark.parametrize("bad", ["IND", "I", "1N", "", "india"])
def test_bad_country_code_rejected(bad):
    with pytest.raises(ValidationError):
        make(country_code=bad)


@pytest.mark.parametrize("bad", ["ADMIN", "participant", "", None, 1])
def test_invalid_role_rejected(bad):
    with pytest.raises(ValidationError):
        make(role=bad)


@pytest.mark.parametrize("missing", ["name", "role", "conference_id"])
def test_missing_required_fields_rejected(missing):
    data = {"name": "A", "role": "GUEST", "conference_id": "c"}
    del data[missing]
    with pytest.raises(ValidationError):
        Participant(**data)


def test_blank_name_and_conference_rejected():
    with pytest.raises(ValidationError):
        make(name=" ")
    with pytest.raises(ValidationError):
        make(conference_id="")


def test_score_can_be_negative_but_not_nan():
    assert make(score=-2.5).score == -2.5
    with pytest.raises(ValidationError):
        make(score=float("nan"))


def test_naive_joined_at_rejected():
    with pytest.raises(ValidationError):
        make(joined_at=datetime(2026, 1, 1))


def test_json_round_trip():
    p = make(score=12)
    assert Participant.model_validate_json(p.model_dump_json()) == p