"""Phase 1: CommitteeConfig."""
import pytest
from pydantic import ValidationError

from backend.mun import (
    COMMITTEE_CONFIGS,
    Committee,
    CommitteeConfig,
    ConferencePhase,
    UnknownCommitteeError,
    get_committee_config,
)


def make(**over):
    return CommitteeConfig(**{
        "committee": "UNSC", "topic": "T", "max_delegates": 15, "voting_threshold": 0.6,
        "allowed_phases": ["LOBBY", "VOTING"], **over,
    })


def test_unsc_accepted():
    cfg = make()
    assert cfg.committee is Committee.UNSC and cfg.allowed_phases == [ConferencePhase.LOBBY, ConferencePhase.VOTING]


def test_global_cybersecurity_accepted():
    assert make(committee="GLOBAL_CYBERSECURITY", topic="Global Cybersecurity Crisis").committee is Committee.GLOBAL_CYBERSECURITY


@pytest.mark.parametrize("bad", ["NATO", "unsc", "", None])
def test_invalid_committee_rejected(bad):
    with pytest.raises(ValidationError):
        make(committee=bad)


@pytest.mark.parametrize("field,bad", [
    ("max_delegates", 0), ("max_delegates", -1), ("max_delegates", 1000),
    ("voting_threshold", 0), ("voting_threshold", 1.2), ("voting_threshold", float("nan")),
    ("allowed_phases", []), ("allowed_phases", ["LOBBY", "LOBBY"]), ("allowed_phases", ["NOPE"]),
    ("topic", ""),
])
def test_invalid_values_rejected(field, bad):
    with pytest.raises(ValidationError):
        make(**{field: bad})


@pytest.mark.parametrize("missing", ["committee", "topic", "max_delegates", "voting_threshold", "allowed_phases"])
def test_required_fields(missing):
    data = {"committee": "UNSC", "topic": "T", "max_delegates": 5, "voting_threshold": 0.5, "allowed_phases": ["LOBBY"]}
    del data[missing]
    with pytest.raises(ValidationError):
        CommitteeConfig(**data)


def test_registry_covers_every_committee():
    assert set(COMMITTEE_CONFIGS) == set(Committee)
    for committee, cfg in COMMITTEE_CONFIGS.items():
        assert cfg.committee is committee


def test_global_cybersecurity_default_topic():
    assert get_committee_config("GLOBAL_CYBERSECURITY").topic == "Global Cybersecurity Crisis"


def test_lookup_accepts_enum_or_string_and_rejects_unknown():
    assert get_committee_config(Committee.UNSC).committee is Committee.UNSC
    assert get_committee_config("UNSC").max_delegates == 15
    with pytest.raises(UnknownCommitteeError):
        get_committee_config("NATO")


def test_lookup_returns_a_copy():
    cfg = get_committee_config("UNSC")
    cfg.allowed_phases.clear()
    cfg.max_delegates = 1
    assert get_committee_config("UNSC").allowed_phases and get_committee_config("UNSC").max_delegates == 15