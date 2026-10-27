"""Phase 4: speeches and the speaker queue - model, pure floor rules, endpoints, events, history."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.conference_service import conference_service
from backend.main import app
from backend.mun import (
    MAX_SPEECH_CHARS,
    ConferencePhase,
    NoSpeakersRemainingError,
    SpeakerState,
    Speech,
    open_floor,
    pass_floor,
)

client = TestClient(app)

FLOW = [
    "LOBBY", "ROLL_CALL", "OPENING_SPEECHES", "MODERATED_CAUCUS", "UNMODERATED_CAUCUS",
    "CRISIS", "DRAFTING", "VOTING", "RESULTS",
]
SPEAKING = {"OPENING_SPEECHES", "MODERATED_CAUCUS"}  # written out independently of backend.mun.phases


# --- helpers ----------------------------------------------------------------------------------
def make_conference(delegates=3, committee="UNSC", extra_roles=()):
    """A conference that has been created and joined but NOT started. Returns its id."""
    cid = client.post("/conference/create", json={"name": "Debate", "committee": committee, "topic": "Peace"}).json()["id"]
    for i in range(delegates):
        assert client.post(f"/conference/{cid}/join", json={"name": f"D{i}", "role": "PARTICIPANT"}).status_code == 201
    for i, role in enumerate(extra_roles):
        assert client.post(f"/conference/{cid}/join", json={"name": f"X{i}", "role": role}).status_code == 201
    return cid


def people(cid):
    """Participants of a conference by name, as the snapshot shows them."""
    return {p["name"]: p for p in client.get(f"/conference/{cid}").json()["participants"]}


def started(delegates=3, committee="UNSC", extra_roles=()):
    cid = make_conference(delegates, committee, extra_roles)
    assert client.post(f"/conference/{cid}/start").status_code == 200
    return cid


def go_to(cid, phase):
    for _ in range(len(FLOW) + 1):
        current = client.get(f"/conference/{cid}").json()["current_phase"]
        if current == phase:
            return
        assert client.post(f"/conference/{cid}/advance").status_code == 200
    raise AssertionError(f"never reached {phase}")


def speak(cid, who, text="Madam President, we call for calm.", **overrides):
    """POST a speech for the delegate `who` (a participant dict); body fields can be overridden."""
    body = {"participant_id": who["id"], "country_code": who["country_code"], "text": text, **overrides}
    return client.post(f"/conference/{cid}/speech", json=body)


def speeches(cid, **params):
    return client.get(f"/conference/{cid}/speeches", params=params)


def speakers(cid):
    return client.get(f"/conference/{cid}/speakers").json()


def next_speaker(cid):
    return client.post(f"/conference/{cid}/speaker/next")


def world_events(cid):
    return client.get(f"/conference/{cid}").json()["world"]["events"]


# --- Speech model -----------------------------------------------------------------------------
def make_speech(**overrides):
    data = dict(conference_id="conf-1", participant_id="part-1", country_code="IN", text="Hello", phase="OPENING_SPEECHES")
    return Speech(**{**data, **overrides})


def test_speech_has_the_required_fields_and_generated_id():
    s = make_speech()
    assert list(Speech.model_fields) == ["id", "conference_id", "participant_id", "country_code", "text", "phase", "created_at"]
    assert s.id.startswith("speech-") and make_speech().id != s.id
    assert s.created_at.utcoffset().total_seconds() == 0
    assert s.phase is ConferencePhase.OPENING_SPEECHES


def test_speech_normalises_and_validates_input():
    assert make_speech(country_code=" in ", text="  padded  ").country_code == "IN"
    assert make_speech(text="  padded  ").text == "padded"
    for bad in (
        dict(text=""), dict(text="   "), dict(text="x" * (MAX_SPEECH_CHARS + 1)),
        dict(country_code="IND"), dict(country_code="1N"), dict(phase="NOT_A_PHASE"),
        dict(conference_id=""), dict(participant_id=""), dict(extra_field="nope"),
    ):
        with pytest.raises(ValidationError):
            make_speech(**bad)
    assert len(make_speech(text="x" * MAX_SPEECH_CHARS).text) == MAX_SPEECH_CHARS


def test_speech_is_immutable_and_rejects_naive_timestamps():
    s = make_speech()
    with pytest.raises(ValidationError):
        s.text = "edited"
    from datetime import datetime
    with pytest.raises(ValidationError):
        make_speech(created_at=datetime(2026, 1, 1))


# --- pure floor rules -------------------------------------------------------------------------
def test_open_floor_gives_the_floor_to_the_first_delegate():
    state = open_floor(ConferencePhase.OPENING_SPEECHES, ["a", "b", "c"])
    assert state == SpeakerState(phase=ConferencePhase.OPENING_SPEECHES, current="a", queue=("b", "c"), completed=())


@pytest.mark.parametrize("phase", [p for p in FLOW if p not in SPEAKING])
def test_open_floor_is_empty_in_phases_without_speeches(phase):
    assert open_floor(ConferencePhase(phase), ["a", "b"]) == SpeakerState()


def test_open_floor_drops_duplicates_keeps_order_and_handles_nobody():
    assert open_floor(ConferencePhase.MODERATED_CAUCUS, ["b", "a", "b"]).queue == ("a",)
    assert open_floor(ConferencePhase.MODERATED_CAUCUS, ["b", "a", "b"]).current == "b"
    assert open_floor(ConferencePhase.MODERATED_CAUCUS, []) == SpeakerState(phase=ConferencePhase.MODERATED_CAUCUS)


def test_pass_floor_walks_the_queue_then_runs_dry():
    state = open_floor(ConferencePhase.OPENING_SPEECHES, ["a", "b"])
    state = pass_floor(state)
    assert (state.current, state.queue, state.completed) == ("b", (), ("a",))
    state = pass_floor(state)
    assert (state.current, state.queue, state.completed) == (None, (), ("a", "b"))
    with pytest.raises(NoSpeakersRemainingError):
        pass_floor(state)


def test_pass_floor_without_an_open_queue_raises_and_never_mutates():
    with pytest.raises(NoSpeakersRemainingError):
        pass_floor(SpeakerState())
    original = open_floor(ConferencePhase.OPENING_SPEECHES, ["a", "b"])
    pass_floor(original)
    assert original.current == "a" and original.queue == ("b",)


# --- submitting a speech ----------------------------------------------------------------------
def test_first_delegate_can_speak_when_opening_speeches_begin():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d0 = people(cid)["D0"]
    r = speak(cid, d0, "Peace through dialogue.")
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("speech-")
    assert body["conference_id"] == cid and body["participant_id"] == d0["id"]
    assert body["country_code"] == d0["country_code"] and body["text"] == "Peace through dialogue."
    assert body["phase"] == "OPENING_SPEECHES" and body["created_at"]


def test_country_code_is_case_insensitive_and_text_is_trimmed():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d0 = people(cid)["D0"]
    body = speak(cid, d0, "  trimmed  ", country_code=d0["country_code"].lower()).json()
    assert body["country_code"] == d0["country_code"] and body["text"] == "trimmed"


def test_speeches_are_stored_in_order_and_survive_the_whole_conference():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d = people(cid)
    assert speak(cid, d["D0"], "first").status_code == 201
    assert next_speaker(cid).status_code == 200
    assert speak(cid, d["D1"], "second").status_code == 201
    stored = speeches(cid).json()
    assert [s["text"] for s in stored] == ["first", "second"]
    assert [s["participant_id"] for s in stored] == [d["D0"]["id"], d["D1"]["id"]]

    go_to(cid, "RESULTS")
    assert client.post(f"/conference/{cid}/advance").json()["status"] == "COMPLETED"
    assert [s["text"] for s in speeches(cid).json()] == ["first", "second"]  # still there once completed


def test_the_current_speaker_may_speak_more_than_once_in_a_turn():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d0 = people(cid)["D0"]
    assert speak(cid, d0, "one").status_code == 201
    assert speak(cid, d0, "two").status_code == 201
    assert len(speeches(cid).json()) == 2


def test_each_speech_records_the_phase_it_was_given_in():
    cid = started(delegates=2)
    go_to(cid, "OPENING_SPEECHES")
    d0 = people(cid)["D0"]
    speak(cid, d0, "opening")
    go_to(cid, "MODERATED_CAUCUS")
    speak(cid, d0, "caucus")
    assert [(s["text"], s["phase"]) for s in speeches(cid).json()] == [
        ("opening", "OPENING_SPEECHES"), ("caucus", "MODERATED_CAUCUS"),
    ]


def test_global_cybersecurity_committee_speaks_too():
    cid = started(delegates=2, committee="GLOBAL_CYBERSECURITY")
    go_to(cid, "OPENING_SPEECHES")
    assert speak(cid, people(cid)["D0"]).status_code == 201


# --- phase gating (the backend phase is authoritative) ----------------------------------------
def test_speeches_are_accepted_only_in_speaking_phases():
    cid = started(delegates=2)
    d0 = people(cid)["D0"]
    seen = []
    for phase in FLOW[1:]:  # LOBBY is gone once the conference has started
        go_to(cid, phase)
        before = len(speeches(cid).json())
        r = speak(cid, d0, f"in {phase}")
        seen.append((phase, r.status_code))
        if phase in SPEAKING:
            assert r.status_code == 201, phase
            assert len(speeches(cid).json()) == before + 1
        else:
            assert r.status_code == 409, phase
            assert "not allowed during" in r.json()["detail"] and phase in r.json()["detail"]
            assert len(speeches(cid).json()) == before
    assert [p for p, code in seen if code == 201] == ["OPENING_SPEECHES", "MODERATED_CAUCUS"]


def test_speech_before_the_conference_starts_is_rejected():
    cid = make_conference()
    d0 = people(cid)["D0"]
    r = client.post(f"/conference/{cid}/speech", json={"participant_id": d0["id"], "country_code": "IN", "text": "hi"})
    assert r.status_code == 409 and "has not started" in r.json()["detail"]


def test_speech_after_the_conference_completes_is_rejected():
    cid = started(delegates=1)
    go_to(cid, "RESULTS")
    client.post(f"/conference/{cid}/advance")
    r = speak(cid, people(cid)["D0"])
    assert r.status_code == 409 and "completed" in r.json()["detail"]


def test_a_client_cannot_choose_the_phase_or_id():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d0 = people(cid)["D0"]
    for extra in ({"phase": "VOTING"}, {"id": "speech-forged"}, {"created_at": "2020-01-01T00:00:00Z"}):
        assert speak(cid, d0, **extra).status_code == 422
    assert speeches(cid).json() == []


def test_phase_gate_agrees_with_the_phase3_action_check():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    assert client.post(f"/conference/{cid}/actions/check", json={"action": "SPEECH"}).status_code == 200
    go_to(cid, "UNMODERATED_CAUCUS")
    assert client.post(f"/conference/{cid}/actions/check", json={"action": "SPEECH"}).status_code == 409


# --- authorization ----------------------------------------------------------------------------
def test_unknown_participant_is_forbidden():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    r = client.post(f"/conference/{cid}/speech", json={"participant_id": "part-nope", "country_code": "IN", "text": "hi"})
    assert r.status_code == 403 and "does not belong" in r.json()["detail"]
    assert speeches(cid).json() == []


def test_participant_of_another_conference_is_forbidden():
    a, b = started(), started()
    go_to(a, "OPENING_SPEECHES")
    go_to(b, "OPENING_SPEECHES")
    outsider = people(b)["D0"]
    r = client.post(
        f"/conference/{a}/speech",
        json={"participant_id": outsider["id"], "country_code": outsider["country_code"], "text": "hi"},
    )
    assert r.status_code == 403
    assert speeches(a).json() == [] and speeches(b).json() == []


@pytest.mark.parametrize("role", ["GUEST", "JURY"])
def test_guests_and_jury_cannot_speak(role):
    cid = started(delegates=2, extra_roles=[role])
    go_to(cid, "OPENING_SPEECHES")
    outsider = people(cid)["X0"]
    r = client.post(f"/conference/{cid}/speech", json={"participant_id": outsider["id"], "country_code": "IN", "text": "hi"})
    assert r.status_code == 403 and role in r.json()["detail"]
    assert speeches(cid).json() == []
    assert all(e["participant_id"] != outsider["id"] for e in speakers(cid)["queue"])  # never queued either


def test_country_must_match_the_participants_assigned_country():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d = people(cid)
    other = d["D1"]["country_code"]
    r = speak(cid, d["D0"], country_code=other)
    assert r.status_code == 403 and "Country mismatch" in r.json()["detail"]
    assert speak(cid, d["D0"], country_code="ZZ").status_code == 403  # well-formed but nobody's seat
    assert speeches(cid).json() == []


def test_malformed_requests_are_422_and_store_nothing():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d0 = people(cid)["D0"]
    url = f"/conference/{cid}/speech"
    assert speak(cid, d0, text="").status_code == 422
    assert speak(cid, d0, text="   ").status_code == 422
    assert speak(cid, d0, text="x" * (MAX_SPEECH_CHARS + 1)).status_code == 422
    assert speak(cid, d0, country_code="IND").status_code == 422
    assert speak(cid, d0, text="x" * MAX_SPEECH_CHARS).status_code == 201  # the limit itself is fine
    assert client.post(url, json={}).status_code == 422
    assert client.post(url, json={"participant_id": d0["id"], "text": "no country"}).status_code == 422
    assert client.post(url, json={"participant_id": d0["id"], "country_code": "IN", "text": 5}).status_code == 422
    assert len(speeches(cid).json()) == 1


# --- speaker queue and turns ------------------------------------------------------------------
def test_speakers_before_start_and_in_roll_call_are_empty_and_closed():
    cid = make_conference()

    def assert_closed_and_empty():
        view = speakers(cid)
        assert view["speaking_open"] is False and view["current_speaker"] is None
        assert view["queue"] == [] and view["completed"] == []
        return view

    assert assert_closed_and_empty()["phase"] == "LOBBY"
    client.post(f"/conference/{cid}/start")
    assert assert_closed_and_empty()["phase"] == "ROLL_CALL"


def test_entering_a_speaking_phase_opens_the_floor_in_join_order():
    cid = started(delegates=3, extra_roles=["GUEST", "JURY"])
    go_to(cid, "OPENING_SPEECHES")
    d = people(cid)
    view = speakers(cid)
    assert view["conference_id"] == cid and view["status"] == "ACTIVE" and view["phase"] == "OPENING_SPEECHES"
    assert view["speaking_open"] is True
    assert view["current_speaker"]["participant_id"] == d["D0"]["id"]
    assert [e["participant_id"] for e in view["queue"]] == [d["D1"]["id"], d["D2"]["id"]]
    assert view["completed"] == []
    assert view["current_speaker"]["participant_name"] == "D0"
    assert view["current_speaker"]["country_code"] == d["D0"]["country_code"]
    assert view["current_speaker"]["country_name"] == d["D0"]["country_name"]


def test_only_the_speaker_holding_the_floor_may_speak():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d = people(cid)
    r = speak(cid, d["D1"])
    assert r.status_code == 409 and "not your turn" in r.json()["detail"] and d["D0"]["country_name"] in r.json()["detail"]
    assert speeches(cid).json() == []

    assert next_speaker(cid).status_code == 200
    assert speak(cid, d["D1"]).status_code == 201
    assert speak(cid, d["D0"]).status_code == 409  # D0's turn is over
    assert speak(cid, d["D2"]).status_code == 409  # D2 has not been called yet


def test_next_speaker_moves_the_floor_and_reports_the_new_queue():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d = people(cid)
    r = next_speaker(cid)
    assert r.status_code == 200
    view = r.json()
    assert view["current_speaker"]["participant_id"] == d["D1"]["id"]
    assert [e["participant_id"] for e in view["queue"]] == [d["D2"]["id"]]
    assert [e["participant_id"] for e in view["completed"]] == [d["D0"]["id"]]
    assert view == speakers(cid)


def test_the_last_speaker_can_finish_and_then_the_queue_is_exhausted():
    cid = started(delegates=2)
    go_to(cid, "OPENING_SPEECHES")
    d = people(cid)
    next_speaker(cid)
    view = next_speaker(cid).json()  # D1 finishes: nobody holds the floor
    assert view["current_speaker"] is None and view["queue"] == []
    assert [e["participant_id"] for e in view["completed"]] == [d["D0"]["id"], d["D1"]["id"]]
    assert view["speaking_open"] is True  # the phase still permits speeches; the queue has simply run dry

    r = next_speaker(cid)
    assert r.status_code == 409 and "exhausted" in r.json()["detail"]
    assert speak(cid, d["D0"]).status_code == 409 and speak(cid, d["D1"]).status_code == 409
    assert speakers(cid) == view  # a rejected request changed nothing


def test_the_queue_is_rebuilt_for_each_speaking_phase_and_emptied_between():
    cid = started(delegates=2)
    go_to(cid, "OPENING_SPEECHES")
    d = people(cid)
    next_speaker(cid)
    next_speaker(cid)
    assert speakers(cid)["current_speaker"] is None

    go_to(cid, "MODERATED_CAUCUS")
    view = speakers(cid)
    assert view["phase"] == "MODERATED_CAUCUS" and view["completed"] == []
    assert view["current_speaker"]["participant_id"] == d["D0"]["id"]
    assert [e["participant_id"] for e in view["queue"]] == [d["D1"]["id"]]

    go_to(cid, "UNMODERATED_CAUCUS")
    view = speakers(cid)
    assert view["speaking_open"] is False and view["current_speaker"] is None
    assert view["queue"] == [] and view["completed"] == []


def test_next_speaker_is_rejected_when_there_is_no_queue():
    cid = make_conference()
    r = next_speaker(cid)
    assert r.status_code == 409 and "has not started" in r.json()["detail"]
    client.post(f"/conference/{cid}/start")
    assert next_speaker(cid).status_code == 409  # ROLL_CALL
    go_to(cid, "VOTING")
    r = next_speaker(cid)
    assert r.status_code == 409 and "no speaker queue" in r.json()["detail"]
    go_to(cid, "RESULTS")
    client.post(f"/conference/{cid}/advance")  # completes the conference
    assert next_speaker(cid).status_code == 409
    view = speakers(cid)
    assert view["status"] == "COMPLETED" and view["speaking_open"] is False and view["queue"] == []


# --- events -----------------------------------------------------------------------------------
def test_submitting_a_speech_emits_a_conference_event():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d0 = people(cid)["D0"]
    before = world_events(cid)
    assert [e["type"] for e in before] == ["conference_start"]

    speech = speak(cid, d0, "A statement.").json()
    events = world_events(cid)
    assert len(events) == len(before) + 1
    event = events[-1]
    assert event["type"] == "speech_submitted"
    assert event["id"] == len(events) and event["target"] is None
    assert d0["country_name"] in event["message"] and "OPENING_SPEECHES" in event["message"]
    assert event["timestamp"] == speech["created_at"]
    fx = event["effects"]
    assert fx["speech_id"] == speech["id"] and fx["participant_id"] == d0["id"] and fx["conference_id"] == cid
    assert fx["country_code"] == d0["country_code"] and fx["phase"] == "OPENING_SPEECHES"
    assert fx["characters"] == len("A statement.")
    assert "A statement." not in str(event)  # the text lives in the speech history, not duplicated in the event


def test_event_actor_is_the_speaking_countrys_id():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d0 = people(cid)["D0"]
    speak(cid, d0)
    country_ids = {c["id"] for c in client.get(f"/conference/{cid}").json()["world"]["countries"]}
    assert world_events(cid)[-1]["actor"] in country_ids


def test_every_accepted_speech_gets_its_own_sequential_event():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d = people(cid)
    speak(cid, d["D0"])
    next_speaker(cid)
    speak(cid, d["D1"])
    events = world_events(cid)
    assert [e["id"] for e in events] == [1, 2, 3]
    assert [e["type"] for e in events] == ["conference_start", "speech_submitted", "speech_submitted"]


def test_rejected_speeches_emit_no_event():
    cid = started()
    d = people(cid)
    speak(cid, d["D0"])  # ROLL_CALL: wrong phase
    go_to(cid, "OPENING_SPEECHES")
    speak(cid, d["D1"])  # not their turn
    speak(cid, d["D0"], country_code="ZZ")  # wrong country
    speak(cid, d["D0"], text="")  # invalid
    assert [e["type"] for e in world_events(cid)] == ["conference_start"]


def test_speech_events_do_not_disturb_the_report():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    speak(cid, people(cid)["D0"])
    report = client.get(f"/conference/{cid}/report")
    assert report.status_code == 200
    body = report.json()
    assert [e["type"] for e in body["diplomatic_events"]] == ["conference_start", "speech_submitted"]
    assert body["outcome"]["totals"]["actions"] == 0  # a speech is not a sanction, alliance or aid action


def test_speeches_leave_the_geopolitical_world_untouched():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    world_before = client.get(f"/conference/{cid}").json()["world"]
    speak(cid, people(cid)["D0"])
    world_after = client.get(f"/conference/{cid}").json()["world"]
    for key in ("turn", "countries", "trade_routes", "mun_metrics"):
        assert world_after[key] == world_before[key]
    assert client.get("/events").json() == []  # nothing leaks into the sandbox world either


# --- history ----------------------------------------------------------------------------------
def test_unknown_conference_is_404_on_every_endpoint():
    ghost = "conf-doesnotexist"
    body = {"participant_id": "part-1", "country_code": "IN", "text": "hi"}
    assert client.post(f"/conference/{ghost}/speech", json=body).status_code == 404
    assert client.get(f"/conference/{ghost}/speeches").status_code == 404
    assert client.get(f"/conference/{ghost}/speakers").status_code == 404
    assert client.post(f"/conference/{ghost}/speaker/next").status_code == 404


def test_history_is_empty_for_a_new_conference_and_isolated_between_conferences():
    a, b = started(), started()
    assert speeches(a).json() == [] and speeches(b).json() == []
    go_to(a, "OPENING_SPEECHES")
    speak(a, people(a)["D0"], "only in A")
    assert [s["text"] for s in speeches(a).json()] == ["only in A"]
    assert speeches(b).json() == []


def test_history_can_be_filtered_by_phase_and_country():
    cid = started(delegates=2)
    go_to(cid, "OPENING_SPEECHES")
    d = people(cid)
    speak(cid, d["D0"], "a-open")
    next_speaker(cid)
    speak(cid, d["D1"], "b-open")
    go_to(cid, "MODERATED_CAUCUS")
    speak(cid, d["D0"], "a-caucus")

    texts = lambda r: [s["text"] for s in r.json()]  # noqa: E731
    assert texts(speeches(cid, phase="OPENING_SPEECHES")) == ["a-open", "b-open"]
    assert texts(speeches(cid, phase="MODERATED_CAUCUS")) == ["a-caucus"]
    assert texts(speeches(cid, country_code=d["D0"]["country_code"])) == ["a-open", "a-caucus"]
    assert texts(speeches(cid, country_code=d["D1"]["country_code"].lower())) == ["b-open"]
    assert texts(speeches(cid, phase="MODERATED_CAUCUS", country_code=d["D1"]["country_code"])) == []
    assert speeches(cid, phase="NOT_A_PHASE").status_code == 422
    assert speeches(cid, country_code="IND").status_code == 422


def test_history_returned_to_callers_cannot_alter_the_store():
    """Later AI agents read history through the service; what they get back is a copy."""
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    speak(cid, people(cid)["D0"], "original")
    history = conference_service.get_speeches(cid)
    assert [s.text for s in history] == ["original"]
    history.clear()
    with pytest.raises(ValidationError):
        conference_service.get_speeches(cid)[0].text = "tampered"
    assert [s.text for s in conference_service.get_speeches(cid)] == ["original"]
    assert [s["text"] for s in speeches(cid).json()] == ["original"]


def test_service_level_submit_returns_a_speech_and_validates_like_the_api():
    cid = started()
    go_to(cid, "OPENING_SPEECHES")
    d0 = people(cid)["D0"]
    speech = conference_service.submit_speech(cid, d0["id"], d0["country_code"].lower(), "direct call")
    assert isinstance(speech, Speech) and speech.country_code == d0["country_code"] and speech.text == "direct call"
    from backend.conference_service import InvalidRequestError
    with pytest.raises(InvalidRequestError):
        conference_service.submit_speech(cid, d0["id"], d0["country_code"], "x" * (MAX_SPEECH_CHARS + 1))
    assert len(conference_service.get_speeches(cid)) == 1


def test_openapi_documents_the_new_endpoints():
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/conference/{conference_id}/speech"]
    assert "get" in paths["/conference/{conference_id}/speeches"]
    assert "get" in paths["/conference/{conference_id}/speakers"]
    assert "post" in paths["/conference/{conference_id}/speaker/next"]