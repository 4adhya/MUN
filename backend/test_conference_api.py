"""Phase 2: conference creation, joining, viewing, starting and country assignment."""
import pytest
from fastapi.testclient import TestClient

from backend.conference_service import InvalidRequestError, assign_countries
from backend.country_registry import DEFAULT_DATASET_PATH, _dataset_path
from backend.countries import build_countries
from backend.main import app
from backend.mun import Participant, ParticipantRole

client = TestClient(app)

# ISO alpha-3 codes ("IND", "JPN") need the world-countries dataset (`npm install`); names and alpha-2 codes do not.
needs_dataset = pytest.mark.skipif(
    not _dataset_path().exists(),
    reason=f"world-countries dataset not found ({DEFAULT_DATASET_PATH}); run `npm install`",
)

# Countries of the existing world, in the order they are seated.
WORLD_ORDER = [c.country_code for c in build_countries()]
METRICS = {
    "world_stability": 75.0,
    "diplomatic_tension": 30.0,
    "humanitarian_impact": 20.0,
    "international_trust": 60.0,
    "cybersecurity_level": 50.0,
    "economic_risk": 25.0,
}


def create(committee="UNSC", **over):
    body = {"name": "Spring MUN", "committee": committee, "topic": "Ceasefire talks", **over}
    return client.post("/conference/create", json=body)


def join(conference_id, name="Asha", role="PARTICIPANT", country=None):
    body = {"name": name, "role": role}
    if country is not None:
        body["country"] = country
    return client.post(f"/conference/{conference_id}/join", json=body)


def make_conference(delegates=0, committee="UNSC"):
    conference_id = create(committee).json()["id"]
    for i in range(delegates):
        assert join(conference_id, name=f"Delegate {i + 1}").status_code == 201
    return conference_id


# --- create -------------------------------------------------------------------------------------
def test_create_conference():
    response = create()
    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("conf-")
    assert (body["name"], body["committee"], body["topic"]) == ("Spring MUN", "UNSC", "Ceasefire talks")
    assert body["status"] == "WAITING" and body["current_phase"] == "LOBBY"
    assert body["created_at"] and body["phase_started_at"] is None and body["phase_ends_at"] is None
    assert body["config"] == {
        "max_delegates": 15,
        "voting_threshold": 0.6,
        "allowed_phases": body["config"]["allowed_phases"],
    }
    assert body["config"]["allowed_phases"][0] == "LOBBY"
    assert body["participants"] == [] and body["assigned_countries"] == [] and body["world"] is None


def test_create_uses_committee_config():
    body = create("GLOBAL_CYBERSECURITY").json()
    assert body["config"]["max_delegates"] == 30 and body["config"]["voting_threshold"] == 0.5


def test_conference_ids_are_unique():
    assert len({create().json()["id"] for _ in range(10)}) == 10


@pytest.mark.parametrize("committee", ["NATO", "unsc", "", "UNSC2"])
def test_invalid_committee_rejected(committee):
    response = create(committee)
    assert response.status_code == 422
    if committee:
        assert "Invalid committee" in response.json()["detail"] and "UNSC" in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"committee": "UNSC", "topic": "t"},
        {"name": "n", "topic": "t"},
        {"name": "n", "committee": "UNSC"},
        {"name": "   ", "committee": "UNSC", "topic": "t"},
        {"name": "n", "committee": "UNSC", "topic": "t", "status": "ACTIVE"},
        {"name": "x" * 101, "committee": "UNSC", "topic": "t"},
    ],
)
def test_invalid_create_body_rejected(body):
    assert client.post("/conference/create", json=body).status_code == 422


# --- join ---------------------------------------------------------------------------------------
def test_join_conference():
    conference_id = make_conference()
    response = join(conference_id, name="  Asha  ", role="PARTICIPANT")
    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("part-") and body["name"] == "Asha"
    assert body["role"] == "PARTICIPANT" and body["conference_id"] == conference_id
    assert body["country_code"] is None  # seats are assigned at start


@pytest.mark.parametrize("role", ["GUEST", "PARTICIPANT", "JURY"])
def test_every_valid_role_can_join(role):
    assert join(make_conference(), role=role).status_code == 201


@pytest.mark.parametrize("role", ["DELEGATE", "participant", "", "ADMIN"])
def test_invalid_role_rejected(role):
    conference_id = make_conference()
    response = join(conference_id, role=role)
    assert response.status_code == 422
    if role:
        assert "Invalid role" in response.json()["detail"]
    assert client.get(f"/conference/{conference_id}").json()["participant_count"] == 0


def test_join_unknown_conference_is_404():
    response = join("conf-doesnotexist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Conference 'conf-doesnotexist' not found"}


def test_join_with_blank_name_rejected():
    assert join(make_conference(), name="  ").status_code == 422


def test_participant_limit_reached():
    conference_id = make_conference(delegates=15)  # UNSC allows 15 delegates
    response = join(conference_id, name="One too many")
    assert response.status_code == 409
    assert "Participant limit reached" in response.json()["detail"]
    assert client.get(f"/conference/{conference_id}").json()["participant_count"] == 15


def test_observers_do_not_use_delegate_seats():
    conference_id = make_conference(delegates=14)
    assert join(conference_id, name="Judge", role="JURY").status_code == 201
    assert join(conference_id, name="Guest", role="GUEST").status_code == 201
    assert join(conference_id, name="Last delegate").status_code == 201
    assert join(conference_id, name="Extra delegate").status_code == 409


# --- get ----------------------------------------------------------------------------------------
def test_get_conference_before_start():
    conference_id = make_conference(delegates=2)
    body = client.get(f"/conference/{conference_id}").json()
    assert body["id"] == conference_id and body["status"] == "WAITING"
    assert body["participant_count"] == 2
    assert [p["name"] for p in body["participants"]] == ["Delegate 1", "Delegate 2"]
    assert all(p["country_code"] is None and p["country_name"] is None for p in body["participants"])
    assert body["assigned_countries"] == [] and body["world"] is None


def test_get_unknown_conference_is_404():
    response = client.get("/conference/conf-doesnotexist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Conference 'conf-doesnotexist' not found"}


def test_snapshot_exposes_no_internal_fields():
    body = client.get(f"/conference/{make_conference(delegates=1)}").json()
    assert set(body) == {
        "id", "name", "committee", "topic", "status", "current_phase", "created_at", "phase_started_at",
        "phase_ends_at", "config", "participant_count", "participants", "assigned_countries", "world",
        "next_phase", "allowed_actions",  # Phase 3: the backend tells the UI what comes next and what is permitted
    }
    assert "conference_id" not in body["participants"][0]


# --- start --------------------------------------------------------------------------------------
def test_start_conference():
    conference_id = make_conference(delegates=3)
    response = client.post(f"/conference/{conference_id}/start")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ACTIVE" and body["current_phase"] == "ROLL_CALL"
    assert body["phase_started_at"] is not None and body["phase_ends_at"] is None
    assert body["world"]["mun_metrics"] == METRICS
    assert [c["country_code"] for c in body["world"]["countries"]] == WORLD_ORDER
    assert body["world"]["turn"] == 0

    # GET returns the same started conference
    assert client.get(f"/conference/{conference_id}").json() == body


def test_start_creates_conference_start_event():
    conference_id = make_conference(delegates=2)
    events = client.post(f"/conference/{conference_id}/start").json()["world"]["events"]
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "conference_start" and event["id"] == 1 and event["actor"] == conference_id
    assert event["effects"]["assigned_countries"] == WORLD_ORDER[:2]
    assert "started" in event["message"]


def test_start_does_not_touch_the_sandbox_world():
    before = client.get("/world").json()
    client.post(f"/conference/{make_conference(delegates=2)}/start")
    assert client.get("/world").json() == before
    assert client.get("/events").json() == []


def test_conferences_have_independent_worlds():
    first, second = make_conference(delegates=1), make_conference(delegates=1)
    client.post(f"/conference/{first}/start")
    client.post(f"/conference/{second}/start")
    w1 = client.get(f"/conference/{first}").json()["world"]
    w2 = client.get(f"/conference/{second}").json()["world"]
    assert w1["events"][0]["actor"] == first and w2["events"][0]["actor"] == second


# --- country assignment ---------------------------------------------------------------------------
def test_countries_assigned_deterministically_in_join_order():
    conference_id = make_conference(delegates=4)
    body = client.post(f"/conference/{conference_id}/start").json()
    codes = [p["country_code"] for p in body["participants"]]
    assert codes == WORLD_ORDER[:4]
    assert [a["country_code"] for a in body["assigned_countries"]] == codes
    assert [a["participant_name"] for a in body["assigned_countries"]] == [f"Delegate {i}" for i in range(1, 5)]
    first = body["assigned_countries"][0]
    assert (first["country_id"], first["country_name"]) == ("india", "India")
    assert body["participants"][0]["country_name"] == "India"


def test_assignment_is_repeatable_across_conferences():
    results = []
    for _ in range(2):
        conference_id = make_conference(delegates=5)
        body = client.post(f"/conference/{conference_id}/start").json()
        results.append([p["country_code"] for p in body["participants"]])
    assert results[0] == results[1]


def test_no_duplicate_countries_when_a_full_committee_is_seated():
    # The world now has far more countries than any committee seats, so fill the committee to its
    # delegate cap and confirm every delegate still gets a distinct country.
    from backend.mun import get_committee_config

    cap = get_committee_config("UNSC").max_delegates
    body = client.post(f"/conference/{make_conference(delegates=cap)}/start").json()
    codes = [p["country_code"] for p in body["participants"]]
    assert len(codes) == cap
    assert len(set(codes)) == cap  # no duplicates
    assert all(code for code in codes)  # everyone got a real seat


def test_observers_get_no_country():
    conference_id = make_conference()
    join(conference_id, name="Judge", role="JURY")
    join(conference_id, name="Delegate")
    join(conference_id, name="Guest", role="GUEST")
    body = client.post(f"/conference/{conference_id}/start").json()
    by_name = {p["name"]: p for p in body["participants"]}
    assert by_name["Delegate"]["country_code"] == WORLD_ORDER[0]
    assert by_name["Judge"]["country_code"] is None and by_name["Guest"]["country_code"] is None
    assert len(body["assigned_countries"]) == 1


def test_the_world_has_more_countries_than_any_committee_seats():
    # Because every registered country is now playable, seating can never run out within a
    # committee's delegate cap. The "no available country" guard is still exercised directly below.
    from backend.mun import get_committee_config

    assert len(WORLD_ORDER) > get_committee_config("UNSC").max_delegates
    assert len(WORLD_ORDER) > get_committee_config("GLOBAL_CYBERSECURITY").max_delegates


def test_assign_countries_rejects_when_countries_run_out():
    # Direct unit coverage of the "No available country" guard (unreachable through normal joins now
    # that the world is registry-sized, but still valid logic).
    one_country = build_countries()[:1]  # only a single seat available
    delegates = [
        Participant(name="A", role=ParticipantRole.PARTICIPANT, conference_id="c"),
        Participant(name="B", role=ParticipantRole.PARTICIPANT, conference_id="c"),
    ]
    with pytest.raises(InvalidRequestError, match="No available country"):
        assign_countries(delegates, one_country)


def test_assign_countries_rejects_duplicate_assignment():
    countries = build_countries()
    p1 = Participant(name="A", role=ParticipantRole.PARTICIPANT, conference_id="c", country_code="IN")
    p2 = Participant(name="B", role=ParticipantRole.PARTICIPANT, conference_id="c", country_code="IN")
    with pytest.raises(Exception, match="Duplicate country assignment"):
        assign_countries([p1, p2], countries)


def test_assign_countries_skips_countries_already_held_and_does_not_mutate_input():
    countries = build_countries()
    held = Participant(name="A", role=ParticipantRole.PARTICIPANT, conference_id="c", country_code="IN")
    new = Participant(name="B", role=ParticipantRole.PARTICIPANT, conference_id="c")
    result = assign_countries([held, new], countries)
    assert [p.country_code for p in result] == ["IN", WORLD_ORDER[1]]
    assert new.country_code is None


# --- invalid starts / state errors -------------------------------------------------------------------
def test_start_unknown_conference_is_404():
    response = client.post("/conference/conf-doesnotexist/start")
    assert response.status_code == 404
    assert response.json() == {"detail": "Conference 'conf-doesnotexist' not found"}


def test_cannot_start_without_delegates():
    conference_id = make_conference()
    join(conference_id, name="Judge", role="JURY")
    response = client.post(f"/conference/{conference_id}/start")
    assert response.status_code == 409
    assert "at least one PARTICIPANT" in response.json()["detail"]
    assert client.get(f"/conference/{conference_id}").json()["status"] == "WAITING"


def test_cannot_start_empty_conference():
    assert client.post(f"/conference/{make_conference()}/start").status_code == 409


def test_cannot_join_after_start():
    conference_id = make_conference(delegates=1)
    client.post(f"/conference/{conference_id}/start")
    response = join(conference_id, name="Latecomer")
    assert response.status_code == 409
    assert "already started" in response.json()["detail"]
    assert client.get(f"/conference/{conference_id}").json()["participant_count"] == 1


def test_cannot_start_twice():
    conference_id = make_conference(delegates=2)
    first = client.post(f"/conference/{conference_id}/start").json()
    response = client.post(f"/conference/{conference_id}/start")
    assert response.status_code == 409
    assert "already started" in response.json()["detail"]
    assert client.get(f"/conference/{conference_id}").json() == first  # untouched


def test_completed_conference_cannot_join_or_start():
    from backend.conference_service import conference_service
    from backend.mun import ConferenceStatus

    conference_id = make_conference(delegates=1)
    record = conference_service._records[conference_id]
    record.conference = record.conference.model_copy(update={"status": ConferenceStatus.COMPLETED})
    for response in (join(conference_id), client.post(f"/conference/{conference_id}/start")):
        assert response.status_code == 409
        assert "already completed" in response.json()["detail"]


# --- country seats are validated against the country registry -------------------------------------------
@pytest.mark.parametrize(
    "alias", ["India", "india", "IN", " india ", pytest.param("IND", marks=needs_dataset)]
)
def test_join_with_a_country_resolves_it_through_the_registry(alias):
    conference_id = make_conference()
    response = join(conference_id, country=alias)
    assert response.status_code == 201
    assert response.json()["country_code"] == "IN"

    body = client.get(f"/conference/{conference_id}").json()  # visible before the conference starts
    assert body["participants"][0]["country_code"] == "IN" and body["participants"][0]["country_name"] == "India"
    assert [a["country_id"] for a in body["assigned_countries"]] == ["india"]
    assert body["status"] == "WAITING" and body["world"] is None


def test_requested_seat_is_honoured_at_start_and_others_fill_the_remaining_seats():
    conference_id = make_conference()
    join(conference_id, name="Claude", country="France")
    join(conference_id, name="Auto")  # no request: first free seat in world order
    body = client.post(f"/conference/{conference_id}/start").json()
    by_name = {p["name"]: p["country_code"] for p in body["participants"]}
    assert by_name["Claude"] == "FR" and by_name["Auto"] == WORLD_ORDER[0]
    codes = list(by_name.values())
    assert len(codes) == len(set(codes))


def test_a_country_cannot_be_held_by_two_participants():
    conference_id = make_conference()
    assert join(conference_id, name="First", country="Japan").status_code == 201
    aliases = ["japan", "Japan", "JP"] + (["JPN"] if _dataset_path().exists() else [])
    for alias in aliases:
        response = join(conference_id, name="Second", country=alias)
        assert response.status_code == 409
        assert "already assigned" in response.json()["detail"]
    assert client.get(f"/conference/{conference_id}").json()["participant_count"] == 1


@pytest.mark.parametrize("country", ["atlantis", "wakanda", "ZZZ"])
def test_unknown_country_is_rejected_and_nobody_joins(country):
    conference_id = make_conference()
    response = join(conference_id, country=country)
    assert response.status_code == 422
    assert "Unknown country" in response.json()["detail"]
    assert client.get(f"/conference/{conference_id}").json()["participant_count"] == 0


def test_a_registered_non_featured_country_can_be_seated():
    # Every registered country is now playable, so a delegate may take a seat as Afghanistan.
    conference_id = make_conference()
    response = join(conference_id, country="afghanistan")
    assert response.status_code == 201, response.text
    assert response.json()["country_code"] == "AF"
    assert client.get(f"/conference/{conference_id}").json()["participant_count"] == 1


@pytest.mark.parametrize("role", ["GUEST", "JURY"])
def test_only_delegates_can_request_a_country(role):
    conference_id = make_conference()
    response = join(conference_id, role=role, country="India")
    assert response.status_code == 422
    assert "Only PARTICIPANT" in response.json()["detail"]
    assert client.get(f"/conference/{conference_id}").json()["participant_count"] == 0


def test_blank_country_is_rejected():
    assert join(make_conference(), country="  ").status_code == 422


def test_requested_seat_failure_does_not_block_the_limit_or_the_conference():
    conference_id = make_conference(delegates=1)
    assert join(conference_id, name="Bad", country="atlantis").status_code == 422
    assert client.post(f"/conference/{conference_id}/start").status_code == 200


def test_assign_countries_rejects_a_seat_that_is_not_in_the_world():
    held = Participant(name="A", role=ParticipantRole.PARTICIPANT, conference_id="c", country_code="ZZ")
    with pytest.raises(InvalidRequestError, match="Invalid country assignment"):
        assign_countries([held], build_countries())