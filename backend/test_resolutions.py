"""Phase 6: resolutions, clauses, amendments, voting and the official result - through the API."""
import ast
import inspect

import pytest
from fastapi.testclient import TestClient

import backend.mun.voting as voting_module
import backend.resolution_service as resolution_service_module
from backend.conference_service import conference_service
from backend.main import app
from backend.mun import CommitteeConfig, VotingRules

client = TestClient(app)

FLOW = [
    "LOBBY", "ROLL_CALL", "OPENING_SPEECHES", "MODERATED_CAUCUS", "UNMODERATED_CAUCUS",
    "CRISIS", "DRAFTING", "VOTING", "RESULTS",
]
P5 = ["CN", "FR", "GB", "RU", "US"]


# --- helpers ---------------------------------------------------------------------------------
def make_conference(committee="GLOBAL_CYBERSECURITY", countries=("IN", "US", "CN"), extra_roles=()):
    cid = client.post("/conference/create", json={"name": "Council", "committee": committee, "topic": "Peace"}).json()["id"]
    for code in countries:
        body = {"name": f"Delegate {code}", "role": "PARTICIPANT", "country": code}
        assert client.post(f"/conference/{cid}/join", json=body).status_code == 201
    for i, role in enumerate(extra_roles):
        assert client.post(f"/conference/{cid}/join", json={"name": f"X{i}", "role": role}).status_code == 201
    return cid


def snapshot(cid):
    return client.get(f"/conference/{cid}").json()


def people(cid):
    """Participants by ISO country code (delegates) and by name (everyone else)."""
    result = {}
    for p in snapshot(cid)["participants"]:
        result[p["country_code"] or p["name"]] = p
    return result


def go_to(cid, phase):
    for _ in range(len(FLOW) + 1):
        if snapshot(cid)["current_phase"] == phase:
            return
        assert client.post(f"/conference/{cid}/advance").status_code == 200
    raise AssertionError(f"never reached {phase}")


def started(committee="GLOBAL_CYBERSECURITY", countries=("IN", "US", "CN"), extra_roles=(), phase="DRAFTING"):
    cid = make_conference(committee, countries, extra_roles)
    assert client.post(f"/conference/{cid}/start").status_code == 200
    go_to(cid, phase)
    return cid, people(cid)


def create(cid, who, title="Protecting the Digital Commons", **extra):
    return client.post(
        "/resolution", json={"conference_id": cid, "participant_id": who["id"], "title": title, **extra}
    )


def new_resolution(cid, who, **extra):
    response = create(cid, who, **extra)
    assert response.status_code == 201, response.text
    return response.json()


def add_clause(rid, who, text="Calls upon all states to cooperate.", type_="OPERATIVE"):
    return client.post(f"/resolution/{rid}/clause", json={"participant_id": who["id"], "type": type_, "text": text})


def submit(rid, who):
    return client.post(f"/resolution/{rid}/submit", json={"participant_id": who["id"]})


def submitted(cid, who, **extra):
    """A resolution with one operative clause, already SUBMITTED (the conference must be in a drafting phase)."""
    rid = new_resolution(cid, who, **extra)["id"]
    assert add_clause(rid, who).status_code == 201
    response = submit(rid, who)
    assert response.status_code == 200, response.text
    return rid


def amend(rid, who, **body):
    return client.post(f"/resolution/{rid}/amend", json={"participant_id": who["id"], **body})


def vote(rid, who, choice, code=None, **overrides):
    body = {"participant_id": who["id"], "country_code": code or who["country_code"], "vote": choice, **overrides}
    return client.post(f"/resolution/{rid}/vote", json=body)


def cast(rid, who, choice):
    response = vote(rid, who, choice)
    assert response.status_code == 201, response.text
    return response.json()


def get(rid):
    response = client.get(f"/resolution/{rid}")
    assert response.status_code == 200, response.text
    return response.json()


def events(cid, *types):
    found = snapshot(cid)["world"]["events"]
    return [e for e in found if e["type"] in types] if types else found


def set_rules(cid, **rule_fields):
    """Replace the conference's voting rules (rules are configuration, so a conference may carry its own)."""
    record = conference_service._records[cid]
    data = record.config.model_dump()
    data["voting_rules"] = VotingRules(**rule_fields)
    if rule_fields.get("majority") == "QUALIFIED":
        data["voting_threshold"] = rule_fields["threshold"]
    record.config = CommitteeConfig(**data)


# --- creating a resolution -------------------------------------------------------------------
def test_create_returns_a_draft_with_the_documented_fields():
    cid, P = started()
    body = new_resolution(cid, P["IN"])
    assert body["id"].startswith("res-")
    assert body["conference_id"] == cid and body["title"] == "Protecting the Digital Commons"
    assert body["status"] == "DRAFT" and body["created_by"] == P["IN"]["id"]
    assert body["sponsors"] == ["IN"] and body["signatories"] == []
    assert body["clauses"] == [] and body["amendments"] == [] and body["result"] is None and body["votes"] == []


def test_create_adds_extra_sponsors_and_always_includes_the_creators_country():
    cid, P = started()
    body = new_resolution(cid, P["IN"], sponsors=["us", "IN", "US"])
    assert body["sponsors"] == ["IN", "US"]


def test_create_is_allowed_in_the_unmoderated_caucus_too():
    cid, P = started(phase="UNMODERATED_CAUCUS")
    assert create(cid, P["IN"]).status_code == 201


def test_create_emits_an_event_attributed_to_the_creators_country():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    [event] = events(cid, "resolution_created")
    assert event["actor"] == "india" and event["effects"]["resolution_id"] == rid
    assert event["effects"]["sponsors"] == ["IN"] and event["effects"]["conference_id"] == cid


@pytest.mark.parametrize("phase", ["ROLL_CALL", "OPENING_SPEECHES", "MODERATED_CAUCUS", "CRISIS", "VOTING", "RESULTS"])
def test_create_is_refused_in_phases_that_do_not_permit_drafting(phase):
    cid, P = started(phase=phase)
    response = create(cid, P["IN"])
    assert response.status_code == 409 and "RESOLUTION_EDIT" in response.json()["detail"]
    assert events(cid, "resolution_created") == []


def test_create_is_refused_before_the_conference_starts():
    cid = make_conference()
    who = people(cid)["IN"]
    assert create(cid, who).status_code == 409


def test_create_rejects_unknown_conference_unknown_participant_and_non_delegates():
    cid, P = started(extra_roles=("GUEST", "JURY"))
    assert client.post("/resolution", json={"conference_id": "conf-nope", "participant_id": "x", "title": "T"}).status_code == 404
    assert create(cid, {"id": "part-nope"}).status_code == 403
    assert create(cid, P["X0"]).status_code == 403  # GUEST
    assert create(cid, P["X1"]).status_code == 403  # JURY


def test_create_rejects_a_participant_of_another_conference():
    cid, P = started()
    _, other = started()
    assert create(cid, other["IN"]).status_code == 403


def test_create_rejects_unseated_sponsors():
    cid, P = started()
    response = create(cid, P["IN"], sponsors=["RU"])
    assert response.status_code == 422 and "RU" in response.json()["detail"]
    assert client.get(f"/conference/{cid}/resolutions").json() == []


@pytest.mark.parametrize(
    "extra",
    [{"title": ""}, {"title": "  "}, {"title": "x" * 201}, {"status": "PASSED"}, {"id": "res-mine"}, {"result": None},
     {"sponsors": ["USA"]}, {"sponsors": "US"}],
)
def test_create_rejects_invalid_or_client_controlled_fields(extra):
    cid, P = started()
    payload = {"conference_id": cid, "participant_id": P["IN"]["id"], "title": "Fine", **extra}
    assert client.post("/resolution", json=payload).status_code == 422


# --- clauses ---------------------------------------------------------------------------------
def test_clauses_are_numbered_in_reading_order_with_preambulatory_first():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    op1 = add_clause(rid, P["IN"], "Operative one").json()
    assert [c["number"] for c in op1["clauses"]] == [1]
    pre = add_clause(rid, P["IN"], "Recalling the charter", "PREAMBULATORY").json()
    assert [(c["number"], c["type"], c["text"]) for c in pre["clauses"]] == [
        (1, "PREAMBULATORY", "Recalling the charter"),
        (2, "OPERATIVE", "Operative one"),
    ]
    op2 = add_clause(rid, P["IN"], "Operative two").json()
    assert [c["text"] for c in op2["clauses"]] == ["Recalling the charter", "Operative one", "Operative two"]
    assert [c["number"] for c in op2["clauses"]] == [1, 2, 3]
    clause = op2["clauses"][0]
    assert clause["id"].startswith("clause-") and clause["resolution_id"] == rid and clause["created_by"] == P["IN"]["id"]


def test_add_clause_returns_201_and_emits_an_event():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    response = add_clause(rid, P["IN"])
    assert response.status_code == 201
    clause_id = response.json()["clauses"][0]["id"]
    [event] = events(cid, "resolution_clause_added")
    assert event["effects"]["clause_id"] == clause_id and event["effects"]["clause_type"] == "OPERATIVE"


def test_patch_changes_text_and_keeps_the_clause_id():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    clause = add_clause(rid, P["IN"], "Old text").json()["clauses"][0]
    response = client.patch(
        f"/resolution/{rid}/clause/{clause['id']}", json={"participant_id": P["IN"]["id"], "text": "New text"}
    )
    assert response.status_code == 200
    [changed] = response.json()["clauses"]
    assert changed["id"] == clause["id"] and changed["text"] == "New text" and changed["number"] == 1
    assert len(events(cid, "resolution_clause_updated")) == 1


def test_patch_can_move_a_clause_between_types_and_renumbers():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    add_clause(rid, P["IN"], "First", "OPERATIVE")
    second = add_clause(rid, P["IN"], "Second", "OPERATIVE").json()["clauses"][1]
    response = client.patch(
        f"/resolution/{rid}/clause/{second['id']}", json={"participant_id": P["IN"]["id"], "type": "PREAMBULATORY"}
    ).json()
    assert [(c["number"], c["type"], c["text"]) for c in response["clauses"]] == [
        (1, "PREAMBULATORY", "Second"),
        (2, "OPERATIVE", "First"),
    ]


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"type": "OTHER"}, {"number": 3, "text": "x"}, {"text": "x" * 2001}])
def test_patch_rejects_empty_or_invalid_changes(body):
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    clause = add_clause(rid, P["IN"]).json()["clauses"][0]
    response = client.patch(f"/resolution/{rid}/clause/{clause['id']}", json={"participant_id": P["IN"]["id"], **body})
    assert response.status_code == 422


def test_delete_removes_and_renumbers():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    add_clause(rid, P["IN"], "Pre", "PREAMBULATORY")
    add_clause(rid, P["IN"], "Op A")
    op_b = add_clause(rid, P["IN"], "Op B").json()["clauses"][2]
    first_op = get(rid)["clauses"][1]
    response = client.delete(f"/resolution/{rid}/clause/{first_op['id']}", params={"participant_id": P["IN"]["id"]})
    assert response.status_code == 200
    assert [(c["number"], c["text"]) for c in response.json()["clauses"]] == [(1, "Pre"), (2, "Op B")]
    assert response.json()["clauses"][1]["id"] == op_b["id"]
    assert len(events(cid, "resolution_clause_removed")) == 1


def test_unknown_clause_and_unknown_resolution_are_404():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    body = {"participant_id": P["IN"]["id"], "text": "x"}
    assert client.patch(f"/resolution/{rid}/clause/clause-nope", json=body).status_code == 404
    assert client.delete(f"/resolution/{rid}/clause/clause-nope", params={"participant_id": P["IN"]["id"]}).status_code == 404
    assert add_clause("res-nope", P["IN"]).status_code == 404
    assert client.get("/resolution/res-nope").status_code == 404


def test_delete_requires_a_participant_id():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    clause = add_clause(rid, P["IN"]).json()["clauses"][0]
    assert client.delete(f"/resolution/{rid}/clause/{clause['id']}").status_code == 422


def test_only_sponsors_may_edit_clauses():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    clause = add_clause(rid, P["IN"]).json()["clauses"][0]
    assert add_clause(rid, P["US"]).status_code == 403
    assert client.patch(f"/resolution/{rid}/clause/{clause['id']}", json={"participant_id": P["US"]["id"], "text": "hijack"}).status_code == 403
    assert client.delete(f"/resolution/{rid}/clause/{clause['id']}", params={"participant_id": P["US"]["id"]}).status_code == 403
    assert get(rid)["clauses"][0]["text"] == "Calls upon all states to cooperate."


def test_a_signatory_does_not_gain_the_right_to_edit():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    assert client.post(f"/resolution/{rid}/sign", json={"participant_id": P["US"]["id"]}).status_code == 200
    assert add_clause(rid, P["US"]).status_code == 403


def test_a_co_sponsor_may_edit_clauses():
    cid, P = started()
    rid = new_resolution(cid, P["IN"], sponsors=["US"])["id"]
    assert add_clause(rid, P["US"]).status_code == 201


def test_clause_edits_are_refused_outside_drafting_phases():
    cid, P = started(phase="UNMODERATED_CAUCUS")
    rid = new_resolution(cid, P["IN"])["id"]
    clause = add_clause(rid, P["IN"]).json()["clauses"][0]
    go_to(cid, "VOTING")
    assert add_clause(rid, P["IN"]).status_code == 409
    assert client.patch(f"/resolution/{rid}/clause/{clause['id']}", json={"participant_id": P["IN"]["id"], "text": "x"}).status_code == 409
    assert client.delete(f"/resolution/{rid}/clause/{clause['id']}", params={"participant_id": P["IN"]["id"]}).status_code == 409


def test_clause_limits_are_enforced():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    assert add_clause(rid, P["IN"], "x" * 2001).status_code == 422
    assert add_clause(rid, P["IN"], "  ").status_code == 422
    assert client.post(f"/resolution/{rid}/clause", json={"participant_id": P["IN"]["id"], "type": "OPERATIVE", "text": "ok", "number": 9}).status_code == 422
    assert client.post(f"/resolution/{rid}/clause", json={"participant_id": P["IN"]["id"], "type": "SIDEBAR", "text": "ok"}).status_code == 422
    for i in range(50):
        assert add_clause(rid, P["IN"], f"Clause {i}").status_code == 201
    over = add_clause(rid, P["IN"], "one too many")
    assert over.status_code == 422 and len(get(rid)["clauses"]) == 50


# --- submit and review -----------------------------------------------------------------------
def test_submit_needs_an_operative_clause():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    assert submit(rid, P["IN"]).status_code == 422  # nothing at all
    add_clause(rid, P["IN"], "Recalling", "PREAMBULATORY")
    assert submit(rid, P["IN"]).status_code == 422  # preambulatory only
    assert get(rid)["status"] == "DRAFT" and events(cid, "resolution_submitted") == []


def test_submit_freezes_the_text_and_emits_an_event():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    body = get(rid)
    assert body["status"] == "SUBMITTED"
    clause_id = body["clauses"][0]["id"]
    assert add_clause(rid, P["IN"]).status_code == 409
    assert client.patch(f"/resolution/{rid}/clause/{clause_id}", json={"participant_id": P["IN"]["id"], "text": "x"}).status_code == 409
    assert client.delete(f"/resolution/{rid}/clause/{clause_id}", params={"participant_id": P["IN"]["id"]}).status_code == 409
    assert submit(rid, P["IN"]).status_code == 409  # already submitted
    [event] = events(cid, "resolution_submitted")
    assert event["effects"]["resolution_id"] == rid and event["effects"]["status"] == "SUBMITTED"


def test_only_a_sponsor_may_submit():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    add_clause(rid, P["IN"])
    assert submit(rid, P["US"]).status_code == 403
    assert get(rid)["status"] == "DRAFT"


def test_review_moves_submitted_to_under_review_only():
    cid, P = started()
    draft = new_resolution(cid, P["IN"])["id"]
    assert client.post(f"/resolution/{draft}/review").status_code == 409  # still a DRAFT
    rid = submitted(cid, P["IN"])
    response = client.post(f"/resolution/{rid}/review")
    assert response.status_code == 200 and response.json()["status"] == "UNDER_REVIEW"
    assert client.post(f"/resolution/{rid}/review").status_code == 409
    assert len(events(cid, "resolution_under_review")) == 1
    assert client.post("/resolution/res-nope/review").status_code == 404


def test_sign_adds_a_signatory_once():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    assert client.post(f"/resolution/{rid}/sign", json={"participant_id": P["IN"]["id"]}).status_code == 409  # sponsor
    first = client.post(f"/resolution/{rid}/sign", json={"participant_id": P["US"]["id"]})
    assert first.status_code == 200 and first.json()["signatories"] == ["US"]
    assert client.post(f"/resolution/{rid}/sign", json={"participant_id": P["US"]["id"]}).status_code == 409
    assert len(events(cid, "resolution_signed")) == 1


def test_guests_cannot_sign_or_submit():
    cid, P = started(extra_roles=("GUEST",))
    rid = new_resolution(cid, P["IN"])["id"]
    assert client.post(f"/resolution/{rid}/sign", json={"participant_id": P["X0"]["id"]}).status_code == 403
    assert submit(rid, P["X0"]).status_code == 403


# --- amendments ------------------------------------------------------------------------------
def test_amend_is_refused_for_a_draft_and_outside_the_drafting_phase():
    cid, P = started()
    draft = new_resolution(cid, P["IN"])["id"]
    response = amend(draft, P["IN"], action="ADD", type="OPERATIVE", text="x")
    assert response.status_code == 409 and "DRAFT" in response.json()["detail"]

    cid2, P2 = started(phase="UNMODERATED_CAUCUS")
    rid = submitted(cid2, P2["IN"])
    response = amend(rid, P2["IN"], action="ADD", type="OPERATIVE", text="x")
    assert response.status_code == 409 and "AMENDMENT" in response.json()["detail"]


def test_amend_add_modify_remove_are_applied_recorded_and_emitted():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    original = get(rid)["clauses"][0]

    added = amend(rid, P["IN"], action="ADD", type="PREAMBULATORY", text="Deeply concerned")
    assert added.status_code == 201
    body = added.json()
    assert [(c["number"], c["type"]) for c in body["clauses"]] == [(1, "PREAMBULATORY"), (2, "OPERATIVE")]
    assert body["status"] == "SUBMITTED"

    modified = amend(rid, P["IN"], action="MODIFY", clause_id=original["id"], text="Urges all states to cooperate.").json()
    assert modified["clauses"][1]["text"] == "Urges all states to cooperate."

    extra = amend(rid, P["IN"], action="ADD", type="OPERATIVE", text="Decides to remain seized.").json()
    new_clause = extra["clauses"][2]
    removed = amend(rid, P["IN"], action="REMOVE", clause_id=new_clause["id"]).json()
    assert [c["text"] for c in removed["clauses"]] == ["Deeply concerned", "Urges all states to cooperate."]

    history = removed["amendments"]
    assert [a["action"] for a in history] == ["ADD", "MODIFY", "ADD", "REMOVE"]
    assert history[1]["previous_text"] == "Calls upon all states to cooperate." and history[1]["text"] == "Urges all states to cooperate."
    assert history[3]["previous_text"] == "Decides to remain seized." and history[3]["text"] is None
    assert all(a["proposed_by"] == P["IN"]["id"] and a["country_code"] == "IN" and a["resolution_id"] == rid for a in history)
    assert len(events(cid, "resolution_amended")) == 4


def test_amend_works_while_under_review():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    client.post(f"/resolution/{rid}/review")
    assert amend(rid, P["IN"], action="ADD", type="OPERATIVE", text="More").status_code == 201
    assert get(rid)["status"] == "UNDER_REVIEW"


def test_amend_cannot_remove_or_retype_the_last_operative_clause():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    clause = get(rid)["clauses"][0]
    assert amend(rid, P["IN"], action="REMOVE", clause_id=clause["id"]).status_code == 422
    assert amend(rid, P["IN"], action="MODIFY", clause_id=clause["id"], type="PREAMBULATORY").status_code == 422
    body = get(rid)
    assert len(body["clauses"]) == 1 and body["amendments"] == []


def test_amend_rejects_noop_unknown_clause_and_bad_bodies():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    clause = get(rid)["clauses"][0]
    assert amend(rid, P["IN"], action="MODIFY", clause_id=clause["id"], text=clause["text"]).status_code == 422
    assert amend(rid, P["IN"], action="MODIFY", clause_id="clause-nope", text="x").status_code == 404
    assert amend(rid, P["IN"], action="REMOVE", clause_id="clause-nope").status_code == 404
    for bad in [
        {"action": "ADD"},
        {"action": "ADD", "type": "OPERATIVE", "text": "x", "clause_id": clause["id"]},
        {"action": "MODIFY", "text": "x"},
        {"action": "MODIFY", "clause_id": clause["id"]},
        {"action": "REMOVE"},
        {"action": "REMOVE", "clause_id": clause["id"], "text": "x"},
        {"action": "DELETE", "clause_id": clause["id"]},
    ]:
        assert amend(rid, P["IN"], **bad).status_code == 422, bad
    assert get(rid)["amendments"] == []


def test_only_sponsors_may_amend():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    assert amend(rid, P["US"], action="ADD", type="OPERATIVE", text="x").status_code == 403


# --- voting: gates ---------------------------------------------------------------------------
def test_voting_opens_by_itself_in_the_voting_phase_and_only_for_submitted_resolutions():
    cid, P = started()
    draft = new_resolution(cid, P["IN"])["id"]
    rid = submitted(cid, P["IN"])
    review = submitted(cid, P["US"])
    client.post(f"/resolution/{review}/review")
    assert get(rid)["status"] == "SUBMITTED"
    go_to(cid, "VOTING")
    assert get(rid)["status"] == "VOTING" and get(review)["status"] == "VOTING"
    assert get(draft)["status"] == "DRAFT"
    assert len(events(cid, "resolution_voting_opened")) == 2


def test_voting_is_refused_outside_the_voting_phase():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    response = vote(rid, P["IN"], "YES")
    assert response.status_code == 409 and "VOTE" in response.json()["detail"]
    assert get(rid)["votes"] == [] and events(cid, "vote_cast") == []


def test_a_draft_resolution_cannot_be_voted_on():
    cid, P = started()
    draft = new_resolution(cid, P["IN"])["id"]
    go_to(cid, "VOTING")
    response = vote(draft, P["IN"], "YES")
    assert response.status_code == 409 and "DRAFT" in response.json()["detail"]


def test_vote_validates_participant_country_conference_and_input():
    cid, P = started(extra_roles=("GUEST",))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    _, other = started()
    assert vote("res-nope", P["IN"], "YES").status_code == 404
    assert client.post(f"/resolution/{rid}/vote", json={"participant_id": "part-nope", "country_code": "IN", "vote": "YES"}).status_code == 403
    assert vote(rid, other["IN"], "YES").status_code == 403  # a delegate of a different conference
    assert vote(rid, P["X0"], "YES", code="IN").status_code == 403  # a guest has no vote
    assert vote(rid, P["IN"], "YES", code="US").status_code == 403  # somebody else's country
    assert vote(rid, P["IN"], "YES", code="in").status_code == 201  # codes are normalised
    for bad in ["yes", "MAYBE", "", None]:
        assert vote(rid, P["US"], bad).status_code == 422
    for bad in [{"country_code": "USA"}, {"country_code": ""}, {"extra": 1}, {"result": "PASSED"}]:
        assert vote(rid, P["US"], "YES", **bad).status_code == 422
    assert [v["country_code"] for v in get(rid)["votes"]] == ["IN"]


def test_a_second_vote_is_refused_even_if_it_is_identical():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    cast(rid, P["IN"], "YES")
    for choice in ("YES", "NO", "ABSTAIN"):
        response = vote(rid, P["IN"], choice)
        assert response.status_code == 409 and "already voted" in response.json()["detail"]
    assert len(get(rid)["votes"]) == 1 and len(events(cid, "vote_cast")) == 1


def test_a_vote_on_a_decided_resolution_is_refused():
    cid, P = started(countries=("IN", "US"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    cast(rid, P["IN"], "YES")
    assert cast(rid, P["US"], "YES")["resolution_status"] == "PASSED"
    again = vote(rid, P["US"], "NO")
    assert again.status_code == 409


def test_a_stored_vote_describes_who_voted_and_where():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    body = cast(rid, P["IN"], "ABSTAIN")
    stored = body["vote"]
    assert stored["id"].startswith("vote-") and stored["resolution_id"] == rid and stored["conference_id"] == cid
    assert stored["participant_id"] == P["IN"]["id"] and stored["country_code"] == "IN"
    assert stored["choice"] == "ABSTAIN" and stored["phase"] == "VOTING"
    assert body["resolution_status"] == "VOTING" and body["result"] is None


# --- voting: official results ----------------------------------------------------------------
def test_simple_majority_committee_passes_and_the_last_vote_closes_the_vote():
    cid, P = started(countries=("IN", "US", "CN", "FR", "GB"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    for code in ("IN", "US"):
        assert cast(rid, P[code], "YES")["result"] is None
    cast(rid, P["CN"], "NO")
    cast(rid, P["FR"], "ABSTAIN")  # ignored in a simple majority
    last = cast(rid, P["GB"], "YES")
    assert last["resolution_status"] == "PASSED"
    result = last["result"]
    assert (result["passed"], result["yes"], result["no"], result["abstain"], result["absent"]) == (True, 3, 1, 1, 0)
    assert (result["counted"], result["required_yes"], result["vetoed_by"]) == (4, 3, [])
    assert result["yes_countries"] == ["GB", "IN", "US"] and result["abstain_countries"] == ["FR"]
    body = get(rid)
    assert body["status"] == "PASSED" and body["result"] == result
    assert [v["country_code"] for v in body["votes"]] == ["IN", "US", "CN", "FR", "GB"]


def test_simple_majority_committee_fails_on_a_tie():
    cid, P = started(countries=("IN", "US", "CN", "FR"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    for code, choice in (("IN", "YES"), ("US", "YES"), ("CN", "NO"), ("FR", "NO")):
        last = cast(rid, P[code], choice)
    assert last["resolution_status"] == "FAILED" and last["result"]["passed"] is False


def test_unsc_veto_by_a_permanent_member_fails_a_resolution_with_a_huge_majority():
    cid, P = started("UNSC", ("US", "RU", "CN", "FR", "GB", "IN", "JP", "BR"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    for code in ("US", "CN", "FR", "GB", "IN", "JP", "BR"):
        assert cast(rid, P[code], "YES")["result"] is None
    last = cast(rid, P["RU"], "NO")
    result = last["result"]
    assert last["resolution_status"] == "FAILED"
    assert (result["yes"], result["no"], result["passed"], result["vetoed_by"]) == (7, 1, False, ["RU"])
    assert "Vetoed" in result["reason"]
    [event] = events(cid, "resolution_result")
    assert event["effects"]["vetoed_by"] == ["RU"] and event["effects"]["status"] == "FAILED"


def test_unsc_abstention_by_a_permanent_member_is_not_a_veto():
    cid, P = started("UNSC", ("US", "RU", "CN", "FR", "GB", "IN", "JP", "BR"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    for code in ("US", "CN", "FR", "GB", "IN", "JP", "BR"):
        cast(rid, P[code], "YES")
    last = cast(rid, P["RU"], "ABSTAIN")
    assert last["resolution_status"] == "PASSED" and last["result"]["vetoed_by"] == []
    assert last["result"]["required_yes"] == 5  # ceil(0.6 * 8): abstentions and absences count toward the total


def test_unsc_non_permanent_no_is_not_a_veto_and_abstentions_count_against():
    cid, P = started("UNSC", ("US", "RU", "CN", "FR", "GB", "IN", "JP", "BR"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    for code in ("US", "RU", "CN", "FR", "GB"):
        cast(rid, P[code], "YES")
    cast(rid, P["IN"], "NO")
    cast(rid, P["JP"], "NO")
    last = cast(rid, P["BR"], "NO")
    assert last["result"]["passed"] is True and last["result"]["vetoed_by"] == []  # 5 YES meets 5 of 8

    cid, P = started("UNSC", ("US", "RU", "CN", "FR", "GB", "IN", "JP", "BR"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    for code in ("US", "RU", "CN", "FR"):
        cast(rid, P[code], "YES")
    for code in ("GB", "IN", "JP", "BR"):
        last = cast(rid, P[code], "ABSTAIN")
    assert last["result"]["passed"] is False  # 4 YES is short of the 5 needed; abstaining did not help


def test_unsc_absent_permanent_member_does_not_veto_when_the_phase_ends():
    cid, P = started("UNSC", ("US", "RU", "CN", "FR", "GB", "IN", "JP", "BR"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    for code in ("CN", "FR", "GB", "IN", "JP"):
        cast(rid, P[code], "YES")
    assert get(rid)["status"] == "VOTING"  # US, RU and BR still have not voted
    go_to(cid, "RESULTS")
    body = get(rid)
    assert body["status"] == "PASSED"
    result = body["result"]
    assert (result["yes"], result["absent"], result["counted"], result["vetoed_by"]) == (5, 3, 8, [])
    assert result["absent_countries"] == ["BR", "RU", "US"]


def test_a_committee_without_veto_ignores_a_no_from_a_permanent_member():
    cid, P = started("GLOBAL_CYBERSECURITY", ("US", "RU", "IN"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    cast(rid, P["IN"], "YES")
    cast(rid, P["RU"], "YES")
    last = cast(rid, P["US"], "NO")
    assert last["resolution_status"] == "PASSED" and last["result"]["vetoed_by"] == []


def test_leaving_the_voting_phase_closes_the_vote_exactly_once():
    cid, P = started(countries=("IN", "US", "CN", "FR"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    cast(rid, P["IN"], "YES")
    cast(rid, P["US"], "YES")
    go_to(cid, "RESULTS")
    first = get(rid)
    assert first["status"] == "PASSED" and first["result"]["absent"] == 2  # absentees are ignored in a simple majority
    for _ in range(3):
        assert get(rid) == first
    client.post(f"/conference/{cid}/advance")  # the conference completes
    assert snapshot(cid)["status"] == "COMPLETED" and get(rid) == first
    assert len(events(cid, "resolution_result")) == 1 and len(events(cid, "resolution_voting_opened")) == 1


def test_a_submitted_resolution_nobody_voted_on_fails_when_voting_ends():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    go_to(cid, "RESULTS")
    body = get(rid)
    assert body["status"] == "FAILED" and body["result"]["yes"] == 0 and body["result"]["absent"] == 3
    assert "no YES" in body["result"]["reason"]
    assert [e["type"] for e in events(cid, "resolution_voting_opened", "resolution_result")] == [
        "resolution_voting_opened", "resolution_result"
    ]


def test_a_draft_stays_a_draft_forever():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    go_to(cid, "RESULTS")
    assert get(rid)["status"] == "DRAFT" and events(cid, "resolution_result") == []


def test_several_resolutions_are_decided_independently():
    cid, P = started(countries=("IN", "US", "CN"))
    first = submitted(cid, P["IN"], title="First")
    second = submitted(cid, P["US"], title="Second")
    go_to(cid, "VOTING")
    for who in ("IN", "US", "CN"):
        cast(first, P[who], "YES")
    assert get(first)["status"] == "PASSED" and get(second)["status"] == "VOTING"
    for who in ("IN", "US", "CN"):
        cast(second, P[who], "NO")
    assert get(second)["status"] == "FAILED"
    assert len(events(cid, "resolution_result")) == 2


# --- configurable rules ----------------------------------------------------------------------
def test_rules_are_read_from_the_conferences_committee_configuration():
    cid, P = started(countries=("IN", "US", "CN"))
    set_rules(cid, majority="QUALIFIED", threshold=1.0)  # unanimity
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    cast(rid, P["IN"], "YES")
    cast(rid, P["US"], "YES")
    last = cast(rid, P["CN"], "NO")
    assert last["result"]["passed"] is False and last["result"]["required_yes"] == 3
    assert last["result"]["rules"]["majority"] == "QUALIFIED" and last["result"]["rules"]["threshold"] == 1.0


def test_abstention_behaviour_is_configurable_per_committee():
    outcomes = {}
    for behaviour in ("IGNORED", "COUNTS_AGAINST"):
        cid, P = started(countries=("IN", "US", "CN", "FR"))
        set_rules(cid, majority="SIMPLE", abstention=behaviour)
        rid = submitted(cid, P["IN"])
        go_to(cid, "VOTING")
        cast(rid, P["IN"], "YES")
        for code in ("US", "CN", "FR"):
            last = cast(rid, P[code], "ABSTAIN")
        outcomes[behaviour] = last["result"]["passed"]
    assert outcomes == {"IGNORED": True, "COUNTS_AGAINST": False}  # 1 of 1 counted vs 1 of 4 counted


def test_a_veto_can_be_configured_for_any_committee():
    cid, P = started("GLOBAL_CYBERSECURITY", ("IN", "US", "CN"))
    set_rules(cid, veto_enabled=True, veto_members=["CN"])
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    cast(rid, P["IN"], "YES")
    cast(rid, P["US"], "YES")
    last = cast(rid, P["CN"], "NO")
    assert last["result"]["vetoed_by"] == ["CN"] and last["resolution_status"] == "FAILED"


# --- determinism, events and isolation -------------------------------------------------------
def run_scripted_vote():
    cid, P = started("UNSC", ("US", "RU", "CN", "FR", "GB", "IN", "JP", "BR"))
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    script = [("IN", "YES"), ("JP", "NO"), ("US", "YES"), ("CN", "ABSTAIN"), ("FR", "YES"), ("GB", "YES"), ("BR", "YES"), ("RU", "YES")]
    for code, choice in script:
        cast(rid, P[code], choice)
    return get(rid)["result"]


def test_the_same_votes_always_give_the_same_official_result():
    results = [run_scripted_vote() for _ in range(3)]
    assert results[0] == results[1] == results[2]
    assert results[0]["passed"] is True and (results[0]["yes"], results[0]["required_yes"]) == (6, 5)


def test_the_result_is_decided_by_code_not_by_any_ai():
    """Neither the service nor the tally imports any AI/LLM code, so no model can influence an outcome."""
    for module in (resolution_service_module, voting_module):
        imported = set()
        for node in ast.walk(ast.parse(inspect.getsource(module))):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(("." * node.level) + (node.module or ""))
        for name in imported:
            assert name.split(".")[0] not in {"ai", "google", "anthropic", "openai"}, (module.__name__, name)
            assert "gemini" not in name.lower() and "advisor" not in name.lower(), (module.__name__, name)


def test_every_step_emits_an_event_in_order():
    cid, P = started(countries=("IN", "US"))
    start = len(events(cid))
    rid = new_resolution(cid, P["IN"])["id"]
    clause = add_clause(rid, P["IN"], "Pre", "PREAMBULATORY").json()["clauses"][0]
    add_clause(rid, P["IN"], "Op")
    client.patch(f"/resolution/{rid}/clause/{clause['id']}", json={"participant_id": P["IN"]["id"], "text": "Pre 2"})
    client.post(f"/resolution/{rid}/sign", json={"participant_id": P["US"]["id"]})
    submit(rid, P["IN"])
    amend(rid, P["IN"], action="ADD", type="OPERATIVE", text="More")
    client.post(f"/resolution/{rid}/review")
    go_to(cid, "VOTING")
    cast(rid, P["IN"], "YES")
    cast(rid, P["US"], "YES")
    types = [e["type"] for e in events(cid)[start:] if e["type"].startswith(("resolution_", "vote_"))]
    assert types == [
        "resolution_created", "resolution_clause_added", "resolution_clause_added", "resolution_clause_updated",
        "resolution_signed", "resolution_submitted", "resolution_amended", "resolution_under_review",
        "resolution_voting_opened", "vote_cast", "vote_cast", "resolution_result",
    ]
    ids = [e["id"] for e in events(cid)]
    assert ids == list(range(1, len(ids) + 1))  # event ids stay sequential


def test_a_rejected_request_emits_no_event_and_changes_nothing():
    cid, P = started()
    rid = new_resolution(cid, P["IN"])["id"]
    before_events, before = len(events(cid)), get(rid)
    add_clause(rid, P["US"])  # 403
    add_clause(rid, P["IN"], "")  # 422
    submit(rid, P["IN"])  # 422: no operative clause
    vote(rid, P["IN"], "YES")  # 409
    assert len(events(cid)) == before_events and get(rid) == before


def test_resolutions_and_votes_never_change_the_world():
    cid, P = started(countries=("IN", "US", "CN"))
    before = snapshot(cid)["world"]
    rid = submitted(cid, P["IN"])
    go_to(cid, "VOTING")
    for code in ("IN", "US", "CN"):
        cast(rid, P[code], "YES")
    after = snapshot(cid)["world"]
    assert after["countries"] == before["countries"] and after["trade_routes"] == before["trade_routes"]
    assert after["mun_metrics"] == before["mun_metrics"]
    assert snapshot(cid)["participants"] and all(p["score"] == 0 for p in snapshot(cid)["participants"])


def test_conferences_do_not_share_resolutions():
    cid_a, A = started()
    cid_b, B = started()
    rid = new_resolution(cid_a, A["IN"])["id"]
    assert client.get(f"/conference/{cid_b}/resolutions").json() == []
    assert add_clause(rid, B["IN"]).status_code == 403  # a delegate of another conference


# --- reading ---------------------------------------------------------------------------------
def test_list_resolutions_supports_a_status_filter():
    cid, P = started()
    draft = new_resolution(cid, P["IN"], title="Draft one")["id"]
    sent = submitted(cid, P["US"], title="Sent one")
    everything = client.get(f"/conference/{cid}/resolutions").json()
    assert [r["id"] for r in everything] == [draft, sent]
    assert [r["id"] for r in client.get(f"/conference/{cid}/resolutions", params={"status": "SUBMITTED"}).json()] == [sent]
    assert client.get(f"/conference/{cid}/resolutions", params={"status": "voting"}).status_code == 422
    assert client.get("/conference/conf-nope/resolutions").status_code == 404


def test_the_get_response_has_every_documented_field():
    cid, P = started()
    rid = submitted(cid, P["IN"])
    body = get(rid)
    assert {"id", "conference_id", "title", "status", "created_by", "sponsors", "signatories", "clauses", "amendments"} <= set(body)
    assert {"id", "resolution_id", "number", "type", "text", "created_by"} == set(body["clauses"][0])