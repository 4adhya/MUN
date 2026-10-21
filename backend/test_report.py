"""Report generation: sandbox report, conference report, empty and error cases, and honesty of the data."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.countries import build_countries
from backend.main import app
from backend.models import DiplomacyEvent, WorldState
from backend.mun import Conference, ConferenceStatus, Participant, ParticipantRole
from backend.report_service import build_report
from backend.simulation import create_initial_world

client = TestClient(app)


def report():
    response = client.get("/simulation/report")
    assert response.status_code == 200, response.text
    return response.json()


def act(kind, actor, target, **extra):
    response = client.post(f"/actions/{kind}", json={"actor": actor, "target": target, **extra})
    assert response.status_code == 200, response.text
    return response.json()


# --- empty ----------------------------------------------------------------------------------------
def test_empty_simulation_gives_a_valid_empty_report():
    r = report()
    assert r["report_type"] == "SIMULATION_SNAPSHOT"
    assert r["activity_recorded"] is False
    assert r["event_count"] == 0
    for section in ("participating_countries", "alliances", "sanctions", "aid", "trade_changes",
                    "diplomatic_events", "world_changes"):
        assert r[section] == [], section
    assert r["conference"] is None and r["mun_metrics"] is None
    assert r["outcome"]["totals"] == {
        "actions": 0, "sanctions": 0, "alliances": 0, "aid_transfers": 0,
        "total_aid_amount": 0.0, "trade_routes_changed": 0, "countries_changed": 0,
    }
    assert "No diplomatic actions were recorded" in r["outcome"]["summary"]
    assert r["outcome"]["highlights"] == []


def test_report_is_empty_again_after_reset():
    act("sanction", "india", "china")
    assert report()["activity_recorded"] is True
    assert client.post("/simulation/reset").status_code == 200
    assert report()["activity_recorded"] is False


# --- populated --------------------------------------------------------------------------------------
def run_session():
    act("sanction", "united-states", "russia")
    act("alliance", "india", "japan")
    act("aid", "france", "brazil", amount=10)


def test_report_contains_every_section_from_the_recorded_actions():
    run_session()
    r = report()

    assert r["activity_recorded"] is True and r["event_count"] == 3

    [sanction] = r["sanctions"]
    assert (sanction["imposed_by"], sanction["target"]) == ("united-states", "russia")
    assert sanction["imposed_by_name"] == "United States" and sanction["target_name"] == "Russia"
    assert sanction["target_gdp_after"] < sanction["target_gdp_before"]
    assert sanction["target_stability_after"] < sanction["target_stability_before"]

    [alliance] = r["alliances"]
    assert alliance["members"] == ["india", "japan"]
    assert alliance["member_names"] == ["India", "Japan"]
    assert alliance["name"] == "India-Japan Alliance"

    [aid] = r["aid"]
    assert (aid["donor"], aid["recipient"], aid["amount"]) == ("france", "brazil", 10)
    assert aid["recipient_gdp_after"] > aid["recipient_gdp_before"]
    assert aid["donor_gdp_after"] < aid["donor_gdp_before"]

    assert [e["type"] for e in r["diplomatic_events"]] == ["sanction", "alliance", "aid"]
    assert [e["id"] for e in r["diplomatic_events"]] == [1, 2, 3]

    totals = r["outcome"]["totals"]
    assert (totals["actions"], totals["sanctions"], totals["alliances"], totals["aid_transfers"]) == (3, 1, 1, 1)
    assert totals["total_aid_amount"] == 10
    summary = r["outcome"]["summary"]
    assert "3 diplomatic actions were recorded: 1 sanction, 1 alliance and 1 aid transfer." in summary
    assert "Total aid sent: 10" in summary
    assert "5 countries ended with" in summary


def test_participating_countries_are_exactly_those_that_acted_or_were_targeted():
    run_session()
    by_id = {c["id"]: c for c in report()["participating_countries"]}
    assert set(by_id) == {"united-states", "russia", "india", "japan", "france", "brazil"}
    assert by_id["united-states"]["actions_initiated"] == 1 and by_id["united-states"]["actions_received"] == 0
    assert by_id["russia"]["actions_initiated"] == 0 and by_id["russia"]["actions_received"] == 1
    assert by_id["united-states"]["flag"]


def test_world_changes_match_the_live_world_state():
    run_session()
    world = {c["id"]: c for c in client.get("/world").json()["countries"]}
    start = {c.id: c for c in build_countries()}
    changes = {c["id"]: c for c in report()["world_changes"]}

    assert set(changes) == {"russia", "india", "japan", "france", "brazil"}  # the sanctioner itself is unchanged
    for cid, change in changes.items():
        assert change["gdp_after"] == world[cid]["gdp"]
        assert change["stability_after"] == world[cid]["stability"]
        assert change["gdp_before"] == start[cid].gdp
        assert change["stability_before"] == start[cid].stability
    assert changes["russia"]["sanctions_received_from"] == ["United States"]
    assert changes["india"]["alliances_added"] == ["India-Japan Alliance"]


def test_trade_changes_reflect_routes_suspended_by_a_sanction():
    result = act("sanction", "india", "china")
    suspended = set(result["event"]["effects"]["trade_routes_deactivated"])
    assert suspended, "this scenario is expected to cut at least one route"

    r = report()
    assert set(r["sanctions"][0]["trade_routes_suspended"]) == suspended
    cut = {t["route_id"] for t in r["trade_changes"] if t["active_before"] and not t["active_after"]}
    assert cut == suspended
    assert all(t["volume_after"] == 0 for t in r["trade_changes"] if t["route_id"] in suspended)
    assert f"Trade routes suspended: {len(suspended)}" in r["outcome"]["highlights"]


def test_single_action_wording_is_singular():
    act("sanction", "india", "china")
    summary = report()["outcome"]["summary"]
    assert "1 diplomatic action was recorded: 1 sanction." in summary
    assert "countrys" not in summary


# --- honesty: nothing is invented -------------------------------------------------------------------
def test_rejected_actions_never_appear_in_the_report():
    act("sanction", "india", "china")
    duplicate = client.post("/actions/sanction", json={"actor": "india", "target": "china"})
    assert duplicate.status_code == 409
    missing = client.post("/actions/aid", json={"actor": "india", "target": "atlantis", "amount": 5})
    assert missing.status_code == 404

    r = report()
    assert len(r["sanctions"]) == 1 and r["aid"] == []
    assert r["outcome"]["totals"]["actions"] == 1


def test_report_events_are_exactly_the_events_endpoint():
    run_session()
    api_events = sorted(client.get("/events?limit=100").json(), key=lambda e: e["id"])
    reported = report()["diplomatic_events"]
    assert [(e["id"], e["type"], e["actor"], e["target"], e["message"]) for e in reported] == [
        (e["id"], e["type"], e["actor"], e["target"], e["message"]) for e in api_events
    ]


def test_generating_a_report_is_read_only_and_repeatable():
    run_session()
    world_before = client.get("/world").json()
    events_before = client.get("/events?limit=100").json()

    first, second = report(), report()
    first.pop("generated_at"), second.pop("generated_at")
    assert first == second
    assert client.get("/world").json() == world_before
    assert client.get("/events?limit=100").json() == events_before


def test_report_endpoint_rejects_non_get_methods():
    assert client.post("/simulation/report").status_code == 405


# --- builder edge cases ---------------------------------------------------------------------------
def test_builder_tolerates_events_with_missing_effects():
    world = create_initial_world()
    world.events.append(
        DiplomacyEvent(
            id=1, turn=0, type="aid", actor="france", target="brazil", message="Aid sent.",
            timestamp=datetime.now(timezone.utc), effects={},
        )
    )
    r = build_report(world, create_initial_world())
    assert r.aid[0].amount is None and r.aid[0].recipient_gdp_after is None
    assert r.outcome.totals.total_aid_amount == 0.0


def test_builder_does_not_mutate_its_inputs():
    world, baseline = create_initial_world(), create_initial_world()
    before = world.model_dump(mode="json"), baseline.model_dump(mode="json")
    build_report(world, baseline)
    assert (world.model_dump(mode="json"), baseline.model_dump(mode="json")) == before


def test_unknown_country_ids_in_events_do_not_crash_the_builder():
    world = create_initial_world()
    world.events.append(
        DiplomacyEvent(
            id=1, turn=0, type="sanction", actor="ghost", target="russia", message="x",
            timestamp=datetime.now(timezone.utc), effects={},
        )
    )
    r = build_report(world, create_initial_world())
    assert r.sanctions[0].imposed_by_name == "ghost"
    assert [c.id for c in r.participating_countries] == ["russia"]


# --- conference reports -----------------------------------------------------------------------------
def make_conference(delegates=2):
    cid = client.post(
        "/conference/create", json={"name": "Spring MUN", "committee": "UNSC", "topic": "Ceasefire talks"}
    ).json()["id"]
    for name in ["Asha", "Ben", "Chen"][:delegates]:
        assert client.post(f"/conference/{cid}/join", json={"name": name, "role": "PARTICIPANT"}).status_code == 201
    return cid


def test_conference_report_unknown_conference_is_404():
    response = client.get("/conference/conf-doesnotexist/report")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_conference_report_before_start_is_409():
    cid = make_conference()
    response = client.get(f"/conference/{cid}/report")
    assert response.status_code == 409
    assert "has not started" in response.json()["detail"]


def test_started_conference_report_lists_delegates_and_start_event():
    cid = make_conference(delegates=2)
    client.post(f"/conference/{cid}/start")

    response = client.get(f"/conference/{cid}/report")
    assert response.status_code == 200
    r = response.json()

    assert r["report_type"] == "CONFERENCE_INTERIM"
    assert r["conference"]["id"] == cid and r["conference"]["committee"] == "UNSC"
    assert r["conference"]["status"] == "ACTIVE" and r["conference"]["current_phase"] == "ROLL_CALL"
    assert [(p["name"], p["country_name"]) for p in r["conference"]["participants"]] == [
        ("Asha", "India"), ("Ben", "United States"),
    ]
    assert [(c["name"], c["delegate"]) for c in r["participating_countries"]] == [
        ("India", "Asha"), ("United States", "Ben"),
    ]
    assert r["activity_recorded"] is False
    assert [e["type"] for e in r["diplomatic_events"]] == ["conference_start"]
    assert r["mun_metrics"]["world_stability"] == 75.0
    assert r["sanctions"] == [] and r["alliances"] == [] and r["aid"] == []


def test_conference_report_is_isolated_from_the_sandbox_world():
    cid = make_conference(delegates=1)
    client.post(f"/conference/{cid}/start")
    act("sanction", "india", "china")  # sandbox action

    assert report()["sanctions"] != []
    r = client.get(f"/conference/{cid}/report").json()
    assert r["sanctions"] == [] and r["world_changes"] == []


def test_conference_report_does_not_change_the_conference():
    cid = make_conference()
    client.post(f"/conference/{cid}/start")
    before = client.get(f"/conference/{cid}").json()
    client.get(f"/conference/{cid}/report")
    assert client.get(f"/conference/{cid}").json() == before


def test_completed_conference_is_reported_as_final():
    world = create_initial_world()
    conference = Conference(name="Done", committee="UNSC", topic="Topic", status=ConferenceStatus.COMPLETED)
    participant = Participant(name="Asha", role=ParticipantRole.PARTICIPANT, country_code="IN", conference_id=conference.id)
    r = build_report(world, create_initial_world(), conference=conference, participants=[participant])
    assert r.report_type == "CONFERENCE_FINAL"
    assert r.participating_countries[0].delegate == "Asha"