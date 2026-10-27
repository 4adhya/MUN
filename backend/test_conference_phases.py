"""Phase 3: the MUN state machine - central flow, advance endpoint, deadlines, per-phase action permissions."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.mun import (
    PHASE_ORDER,
    REQUIRED_PHASES,
    ActionType,
    ConferencePhase,
    InvalidTransitionError,
    allowed_actions,
    check_transition,
    next_phase,
)
from backend.mun.phases import PHASE_DURATION_SECONDS

client = TestClient(app)

FLOW = [
    "LOBBY", "ROLL_CALL", "OPENING_SPEECHES", "MODERATED_CAUCUS", "UNMODERATED_CAUCUS",
    "CRISIS", "DRAFTING", "VOTING", "RESULTS",
]
# Written out independently of backend.mun.phases: the specification the endpoint must match.
EXPECTED_ACTIONS = {
    "LOBBY": set(),
    "ROLL_CALL": set(),
    "OPENING_SPEECHES": {"SPEECH"},
    "MODERATED_CAUCUS": {"SPEECH", "MOTION"},
    "UNMODERATED_CAUCUS": {"NEGOTIATION", "ALLIANCE", "RESOLUTION_EDIT"},
    "CRISIS": {"CRISIS_RESPONSE", "NEGOTIATION"},
    "DRAFTING": {"RESOLUTION_EDIT", "AMENDMENT"},
    "VOTING": {"VOTE"},
    "RESULTS": set(),
}
ALL_ACTIONS = sorted(a.value for a in ActionType)
ENUM_ORDER = [a.value for a in ActionType]  # the order the snapshot lists allowed_actions in


def started(delegates=2):
    conference_id = client.post(
        "/conference/create", json={"name": "Phases", "committee": "UNSC", "topic": "Order"}
    ).json()["id"]
    for i in range(delegates):
        client.post(f"/conference/{conference_id}/join", json={"name": f"D{i}", "role": "PARTICIPANT"})
    assert client.post(f"/conference/{conference_id}/start").status_code == 200
    return conference_id


def advance(conference_id, **body):
    return client.post(f"/conference/{conference_id}/advance", json=body) if body else client.post(
        f"/conference/{conference_id}/advance"
    )


def snapshot(conference_id):
    return client.get(f"/conference/{conference_id}").json()


def check(conference_id, action):
    return client.post(f"/conference/{conference_id}/actions/check", json={"action": action})


def when(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- the central definition ---------------------------------------------------------------------------------
def test_flow_is_defined_once_and_in_the_required_order():
    assert [p.value for p in PHASE_ORDER] == FLOW
    assert set(PHASE_ORDER) == set(ConferencePhase)
    assert REQUIRED_PHASES >= {ConferencePhase.ROLL_CALL, ConferencePhase.RESULTS}


def test_next_phase_walks_the_flow_and_ends_after_results():
    walked = [ConferencePhase.LOBBY]
    while (following := next_phase(walked[-1])) is not None:
        walked.append(following)
    assert [p.value for p in walked] == FLOW


def test_committee_may_drop_debate_phases_but_never_roll_call_or_results():
    allowed = [ConferencePhase.LOBBY, ConferencePhase.VOTING]
    assert next_phase(ConferencePhase.LOBBY, allowed) is ConferencePhase.ROLL_CALL
    assert next_phase(ConferencePhase.ROLL_CALL, allowed) is ConferencePhase.VOTING
    assert next_phase(ConferencePhase.VOTING, allowed) is ConferencePhase.RESULTS
    assert next_phase(ConferencePhase.RESULTS, allowed) is None


@pytest.mark.parametrize(
    "current, target",
    [
        ("LOBBY", "OPENING_SPEECHES"),  # skipping ROLL_CALL
        ("ROLL_CALL", "VOTING"),  # skipping the debate
        ("VOTING", "ROLL_CALL"),  # rewinding
        ("CRISIS", "CRISIS"),  # repeating
        ("VOTING", None),  # completing without RESULTS
    ],
)
def test_check_transition_rejects_anything_but_the_next_step(current, target):
    with pytest.raises(InvalidTransitionError, match="Invalid phase transition"):
        check_transition(ConferencePhase(current), ConferencePhase(target) if target else None)


def test_check_transition_accepts_the_next_step_and_completion_after_results():
    check_transition(ConferencePhase.ROLL_CALL, ConferencePhase.OPENING_SPEECHES)
    check_transition(ConferencePhase.RESULTS, None)


@pytest.mark.parametrize("phase", FLOW)
def test_permissions_match_the_specification(phase):
    assert {a.value for a in allowed_actions(ConferencePhase(phase))} == EXPECTED_ACTIONS[phase]


# --- start and advance --------------------------------------------------------------------------------------
def test_start_enters_roll_call_untimed_and_reports_the_next_step():
    body = snapshot(started())
    assert body["status"] == "ACTIVE" and body["current_phase"] == "ROLL_CALL"
    assert body["phase_started_at"] and body["phase_ends_at"] is None
    assert body["next_phase"] == "OPENING_SPEECHES" and body["allowed_actions"] == []


def test_a_conference_that_has_not_started_has_no_next_step_and_cannot_advance():
    conference_id = client.post("/conference/create", json={"name": "n", "committee": "UNSC", "topic": "t"}).json()["id"]
    client.post(f"/conference/{conference_id}/join", json={"name": "D", "role": "PARTICIPANT"})
    body = snapshot(conference_id)
    assert body["current_phase"] == "LOBBY" and body["next_phase"] is None and body["allowed_actions"] == []
    response = advance(conference_id)
    assert response.status_code == 409 and "has not started" in response.json()["detail"]
    assert snapshot(conference_id)["current_phase"] == "LOBBY"


def test_full_flow_from_roll_call_to_completed():
    conference_id = started()
    seen = ["ROLL_CALL"]
    while True:
        before = snapshot(conference_id)
        response = advance(conference_id)
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] == "COMPLETED":
            break
        seen.append(body["current_phase"])
        assert body["status"] == "ACTIVE"
        assert when(body["phase_started_at"]) >= when(before["phase_started_at"])
    assert seen == FLOW[1:]  # ROLL_CALL ... RESULTS, in order, nothing skipped
    assert body["current_phase"] == "RESULTS"  # status and phase are separate: the phase stays RESULTS
    assert body["next_phase"] is None and body["allowed_actions"] == [] and body["phase_ends_at"] is None


def test_results_comes_before_completed_and_a_completed_conference_cannot_advance_again():
    conference_id = started()
    for _ in range(len(FLOW) - 2):  # ROLL_CALL -> RESULTS
        assert advance(conference_id).status_code == 200
    at_results = snapshot(conference_id)
    assert at_results["current_phase"] == "RESULTS" and at_results["status"] == "ACTIVE"
    assert at_results["next_phase"] == "COMPLETED"

    assert advance(conference_id).json()["status"] == "COMPLETED"
    again = advance(conference_id)
    assert again.status_code == 409 and "already completed" in again.json()["detail"]
    assert snapshot(conference_id)["status"] == "COMPLETED"


def test_completed_conference_has_a_final_report():
    conference_id = started()
    for _ in range(len(FLOW) - 1):
        advance(conference_id)
    assert snapshot(conference_id)["status"] == "COMPLETED"
    assert client.get(f"/conference/{conference_id}/report").json()["report_type"] == "CONFERENCE_FINAL"


def test_advance_unknown_conference_is_404():
    response = advance("conf-doesnotexist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Conference 'conf-doesnotexist' not found"}


def test_advance_does_not_touch_the_world_or_participants():
    conference_id = started()
    before = snapshot(conference_id)
    advance(conference_id)
    after = snapshot(conference_id)
    assert after["world"] == before["world"] and after["participants"] == before["participants"]


def test_phases_are_per_conference():
    first, second = started(), started()
    advance(first)
    assert snapshot(first)["current_phase"] == "OPENING_SPEECHES" and snapshot(second)["current_phase"] == "ROLL_CALL"


# --- the client cannot choose or force a phase ----------------------------------------------------------------
def test_matching_to_phase_is_accepted_as_a_stale_screen_guard():
    conference_id = started()
    assert advance(conference_id, to_phase="OPENING_SPEECHES").json()["current_phase"] == "OPENING_SPEECHES"


@pytest.mark.parametrize("to_phase", ["VOTING", "RESULTS", "ROLL_CALL", "LOBBY", "COMPLETED"])
def test_skipping_rewinding_or_repeating_is_rejected_and_changes_nothing(to_phase):
    conference_id = started()
    before = snapshot(conference_id)
    response = advance(conference_id, to_phase=to_phase)
    assert response.status_code == 409
    assert "Invalid phase transition" in response.json()["detail"] and "OPENING_SPEECHES" in response.json()["detail"]
    assert snapshot(conference_id) == before


def test_debate_cannot_be_reached_without_roll_call():
    conference_id = client.post("/conference/create", json={"name": "n", "committee": "UNSC", "topic": "t"}).json()["id"]
    client.post(f"/conference/{conference_id}/join", json={"name": "D", "role": "PARTICIPANT"})
    assert advance(conference_id, to_phase="OPENING_SPEECHES").status_code == 409  # not started: no phase change at all
    assert snapshot(conference_id)["current_phase"] == "LOBBY"


def test_completed_can_only_be_requested_straight_after_results():
    conference_id = started()
    assert advance(conference_id, to_phase="COMPLETED").status_code == 409
    for _ in range(len(FLOW) - 2):
        advance(conference_id)
    assert advance(conference_id, to_phase="COMPLETED").json()["status"] == "COMPLETED"


@pytest.mark.parametrize("body", [{"to_phase": "NOPE"}, {"to_phase": "voting"}, {"to_phase": ""}, {"phase": "VOTING"}, {"to_phase": 3}])
def test_malformed_or_unknown_phase_requests_are_422(body):
    conference_id = started()
    assert advance(conference_id, **body).status_code == 422
    assert snapshot(conference_id)["current_phase"] == "ROLL_CALL"


def test_status_and_phase_cannot_be_set_through_other_endpoints():
    conference_id = started()
    for path, body in (
        (f"/conference/{conference_id}/join", {"name": "X", "role": "GUEST", "current_phase": "VOTING"}),
        (f"/conference/{conference_id}/start", {"current_phase": "VOTING"}),
    ):
        client.post(path, json=body)
    body = snapshot(conference_id)
    assert body["current_phase"] == "ROLL_CALL" and body["status"] == "ACTIVE"


# --- deadlines -------------------------------------------------------------------------------------------------
def test_each_phase_gets_its_deadline_from_the_central_durations():
    conference_id = started()
    for phase in FLOW[2:]:  # OPENING_SPEECHES ... RESULTS
        body = advance(conference_id).json()
        assert body["current_phase"] == phase
        seconds = PHASE_DURATION_SECONDS[ConferencePhase(phase)]
        if seconds is None:
            assert body["phase_ends_at"] is None
        else:
            assert when(body["phase_ends_at"]) - when(body["phase_started_at"]) == timedelta(seconds=seconds)


# --- actions allowed only in the right phase --------------------------------------------------------------------
def test_action_gate_matches_the_phase_permissions_in_every_phase():
    conference_id = started()
    for phase in FLOW[1:]:
        assert snapshot(conference_id)["current_phase"] == phase
        assert snapshot(conference_id)["allowed_actions"] == [a for a in ENUM_ORDER if a in EXPECTED_ACTIONS[phase]]
        for action in ALL_ACTIONS:
            response = check(conference_id, action)
            if action in EXPECTED_ACTIONS[phase]:
                assert response.status_code == 200, (phase, action)
                assert response.json() == {"conference_id": conference_id, "action": action, "phase": phase, "allowed": True}
            else:
                assert response.status_code == 409, (phase, action)
                assert f"{action} is not allowed during {phase}" in response.json()["detail"]
        if phase != "RESULTS":
            advance(conference_id)


def test_a_refused_action_changes_nothing():
    conference_id = started()
    before = snapshot(conference_id)
    assert check(conference_id, "VOTE").status_code == 409
    assert snapshot(conference_id) == before


def test_actions_are_refused_before_start_and_after_completion():
    conference_id = client.post("/conference/create", json={"name": "n", "committee": "UNSC", "topic": "t"}).json()["id"]
    response = check(conference_id, "SPEECH")
    assert response.status_code == 409 and "has not started" in response.json()["detail"]

    conference_id = started()
    for _ in range(len(FLOW) - 1):
        advance(conference_id)
    response = check(conference_id, "VOTE")
    assert response.status_code == 409 and "already completed" in response.json()["detail"]


@pytest.mark.parametrize("action", ["DANCE", "speech", "", "Vote"])
def test_unknown_action_types_are_422(action):
    response = check(started(), action)
    assert response.status_code == 422
    if action:
        assert "Invalid action" in response.json()["detail"]


def test_action_check_unknown_conference_is_404():
    assert check("conf-doesnotexist", "SPEECH").status_code == 404