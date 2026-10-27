"""Phase 5: negotiations and diplomacy - model, pure state rules, relationship rules, endpoints, events, history."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.conference_service import conference_service
from backend.main import app
from backend.mun import (
    MAX_PROPOSAL_CHARS,
    NEGOTIATION_TTL_SECONDS,
    ConferencePhase,
    ConferenceStatus,
    Negotiation,
    NegotiationAction,
    NegotiationStateError,
    NegotiationStatus,
    apply_response,
    default_expiry,
    expire,
    expire_reason,
    is_finalized,
)
from backend.negotiation_rules import (
    NEGOTIATION_ACCEPT_RELATIONSHIP_GAIN,
    NEGOTIATION_COUNTER_RELATIONSHIP_GAIN,
    NEGOTIATION_REJECT_RELATIONSHIP_DROP,
    apply_negotiation_outcome,
    relationship_delta,
)
from backend.rules import ActionError, validate_world
from backend.simulation import create_initial_world, simulation

client = TestClient(app)
safe_client = TestClient(app, raise_server_exceptions=False)  # lets a deliberate 500 come back as a response

FLOW = [
    "LOBBY", "ROLL_CALL", "OPENING_SPEECHES", "MODERATED_CAUCUS", "UNMODERATED_CAUCUS",
    "CRISIS", "DRAFTING", "VOTING", "RESULTS",
]
NEGOTIATING = {"UNMODERATED_CAUCUS", "CRISIS"}  # written out independently of backend.mun.phases
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


# --- helpers ----------------------------------------------------------------------------------
def make_conference(delegates=3, committee="UNSC", extra_roles=()):
    cid = client.post("/conference/create", json={"name": "Talks", "committee": committee, "topic": "Peace"}).json()["id"]
    for i in range(delegates):
        assert client.post(f"/conference/{cid}/join", json={"name": f"D{i}", "role": "PARTICIPANT"}).status_code == 201
    for i, role in enumerate(extra_roles):
        assert client.post(f"/conference/{cid}/join", json={"name": f"X{i}", "role": role}).status_code == 201
    return cid


def people(cid):
    return {p["name"]: p for p in client.get(f"/conference/{cid}").json()["participants"]}


def started(delegates=3, extra_roles=()):
    cid = make_conference(delegates, extra_roles=extra_roles)
    assert client.post(f"/conference/{cid}/start").status_code == 200
    return cid


def go_to(cid, phase):
    for _ in range(len(FLOW) + 1):
        if client.get(f"/conference/{cid}").json()["current_phase"] == phase:
            return
        assert client.post(f"/conference/{cid}/advance").status_code == 200
    raise AssertionError(f"never reached {phase}")


def talks(delegates=3, extra_roles=(), phase="UNMODERATED_CAUCUS"):
    """A started conference in a negotiating phase. Returns (conference id, participants by name)."""
    cid = started(delegates, extra_roles)
    go_to(cid, phase)
    return cid, people(cid)


def propose(cid, proposer, receiver, text="We offer a joint maritime patrol.", body=None):
    """POST a proposal from participant dict `proposer` to participant dict (or country code) `receiver`.

    `body` overrides or adds raw request fields (used to send invalid or client-controlled ones).
    """
    code = receiver["country_code"] if isinstance(receiver, dict) else receiver
    payload = {"conference_id": cid, "participant_id": proposer["id"], "receiver": code, "proposal": text, **(body or {})}
    return client.post("/negotiation/propose", json=payload)


def respond(negotiation_id, who, action, counter_offer=None, **overrides):
    body = {"participant_id": who["id"] if isinstance(who, dict) else who, "action": action, **overrides}
    if counter_offer is not None:
        body["counter_offer"] = counter_offer
    return client.post(f"/negotiation/{negotiation_id}/respond", json=body)


def open_proposal(cid, proposer, receiver, **kw):
    response = propose(cid, proposer, receiver, **kw)
    assert response.status_code == 201, response.text
    return response.json()


def history(cid, **params):
    return client.get(f"/conference/{cid}/negotiations", params=params)


def world_of(cid):
    return client.get(f"/conference/{cid}").json()["world"]


def world_events(cid):
    return world_of(cid)["events"]


def events_of(cid, event_type):
    return [e for e in world_events(cid) if e["type"] == event_type]


def relationship(cid, a, b):
    """The relationship score between two participants' countries, read from the conference's world."""
    countries = {c["country_code"]: c for c in world_of(cid)["countries"]}
    ca, cb = countries[a["country_code"]], countries[b["country_code"]]
    assert ca["relationships"][cb["id"]] == cb["relationships"][ca["id"]]  # always symmetric
    return ca["relationships"][cb["id"]]


def set_relationship(cid, a, b, score):
    """Test-only: put a relationship at an exact value by editing the stored world."""
    world = conference_service._records[cid].world
    ca = next(c for c in world.countries if c.country_code == a["country_code"])
    cb = next(c for c in world.countries if c.country_code == b["country_code"])
    ca.relationships[cb.id] = score
    cb.relationships[ca.id] = score


@pytest.fixture
def clock(monkeypatch):
    """A movable clock for negotiations: `clock.now`, `clock.advance(seconds=...)`."""

    class Clock:
        now = datetime.now(timezone.utc)

        def advance(self, seconds):
            self.now = self.now + timedelta(seconds=seconds)

    fake = Clock()
    monkeypatch.setattr(conference_service, "_clock", lambda: fake.now)
    return fake


def make_negotiation(**overrides):
    values = dict(
        conference_id="conf-1", proposer="IN", receiver="US", proposal="A deal.", created_at=NOW,
        expires_at=default_expiry(NOW), proposer_participant_id="part-a", receiver_participant_id="part-b",
        phase=ConferencePhase.UNMODERATED_CAUCUS,
    )
    values.update(overrides)
    return Negotiation(**values)


# --- Negotiation model --------------------------------------------------------------------------
def test_new_negotiation_is_pending_with_generated_id_and_no_counter_offer():
    n = make_negotiation()
    assert n.id.startswith("neg-") and n.status is NegotiationStatus.PENDING
    assert n.counter_offer is None and n.responded_at is None


def test_negotiation_status_and_action_values_are_uppercase_names():
    assert {s.value for s in NegotiationStatus} == {"PENDING", "ACCEPTED", "REJECTED", "COUNTERED", "EXPIRED"}
    assert {a.value for a in NegotiationAction} == {"ACCEPT", "REJECT", "COUNTER"}


def test_negotiation_codes_are_normalised_and_checked():
    n = make_negotiation(proposer=" in ", receiver="us")
    assert (n.proposer, n.receiver) == ("IN", "US")
    for bad in ("IND", "1N", ""):
        with pytest.raises(ValidationError):
            make_negotiation(proposer=bad)


@pytest.mark.parametrize(
    "overrides",
    [
        {"receiver": "IN"},  # itself
        {"proposal": "   "},
        {"proposal": "x" * (MAX_PROPOSAL_CHARS + 1)},
        {"expires_at": NOW},  # not after created_at
        {"expires_at": NOW - timedelta(seconds=1)},
        {"created_at": datetime(2026, 1, 1)},  # naive
        {"status": NegotiationStatus.COUNTERED},  # COUNTERED needs a counter_offer
        {"counter_offer": "Counter."},  # a counter_offer needs COUNTERED
        {"id": ""},
        {"conference_id": ""},
    ],
)
def test_negotiation_rejects_invalid_shapes(overrides):
    with pytest.raises(ValidationError):
        make_negotiation(**overrides)


def test_negotiation_forbids_unknown_fields_and_is_immutable():
    with pytest.raises(ValidationError):
        make_negotiation(score=5)
    n = make_negotiation()
    with pytest.raises(ValidationError):
        n.status = NegotiationStatus.ACCEPTED


def test_default_expiry_is_the_ttl_after_creation():
    assert default_expiry(NOW) - NOW == timedelta(seconds=NEGOTIATION_TTL_SECONDS)


# --- Pure state rules ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "action,status",
    [("ACCEPT", NegotiationStatus.ACCEPTED), ("REJECT", NegotiationStatus.REJECTED)],
)
def test_apply_response_accept_and_reject(action, status):
    n = make_negotiation()
    answered = apply_response(n, NegotiationAction(action), None, NOW)
    assert answered.status is status and answered.responded_at == NOW and answered.counter_offer is None
    assert n.status is NegotiationStatus.PENDING  # the original is never changed


def test_apply_response_counter_stores_trimmed_counter_offer():
    answered = apply_response(make_negotiation(), NegotiationAction.COUNTER, "  Fewer patrols, more aid.  ", NOW)
    assert answered.status is NegotiationStatus.COUNTERED and answered.counter_offer == "Fewer patrols, more aid."


@pytest.mark.parametrize("counter_offer", [None, "", "   "])
def test_apply_response_counter_needs_text(counter_offer):
    with pytest.raises(ValueError):
        apply_response(make_negotiation(), NegotiationAction.COUNTER, counter_offer, NOW)


@pytest.mark.parametrize("action", [NegotiationAction.ACCEPT, NegotiationAction.REJECT])
def test_apply_response_accept_and_reject_cannot_carry_a_counter_offer(action):
    with pytest.raises(ValueError):
        apply_response(make_negotiation(), action, "Sneaky terms", NOW)


def test_apply_response_counter_offer_obeys_the_length_limit():
    with pytest.raises(ValidationError):
        apply_response(make_negotiation(), NegotiationAction.COUNTER, "x" * (MAX_PROPOSAL_CHARS + 1), NOW)


@pytest.mark.parametrize("final", [s for s in NegotiationStatus if s is not NegotiationStatus.PENDING])
def test_a_final_negotiation_cannot_be_answered_or_expired_again(final):
    n = make_negotiation(status=final, counter_offer="Counter." if final is NegotiationStatus.COUNTERED else None)
    assert is_finalized(n)
    with pytest.raises(NegotiationStateError):
        apply_response(n, NegotiationAction.ACCEPT, None, NOW)
    with pytest.raises(NegotiationStateError):
        expire(n)
    assert expire_reason(n, NOW + timedelta(days=1), ConferencePhase.DRAFTING) is None


def test_expire_marks_a_pending_negotiation_expired():
    expired = expire(make_negotiation())
    assert expired.status is NegotiationStatus.EXPIRED and expired.responded_at is None


def test_expire_reason_time_and_phase():
    n = make_negotiation()
    during = ConferencePhase.UNMODERATED_CAUCUS
    assert expire_reason(n, NOW + timedelta(seconds=NEGOTIATION_TTL_SECONDS - 1), during) is None
    assert expire_reason(n, n.expires_at, during) == "time_elapsed"
    assert expire_reason(n, NOW, ConferencePhase.CRISIS) is None  # CRISIS also permits negotiation
    for phase in ConferencePhase:
        if phase.value not in NEGOTIATING:
            assert expire_reason(n, NOW, phase) == "phase_closed"
    assert expire_reason(n, n.expires_at, ConferencePhase.DRAFTING) == "phase_closed"  # phase wins


# --- Relationship rules -------------------------------------------------------------------------
def test_relationship_deltas_are_fixed_by_outcome():
    assert relationship_delta(NegotiationStatus.ACCEPTED) == NEGOTIATION_ACCEPT_RELATIONSHIP_GAIN == 5
    assert relationship_delta(NegotiationStatus.COUNTERED) == NEGOTIATION_COUNTER_RELATIONSHIP_GAIN == 1
    assert relationship_delta(NegotiationStatus.REJECTED) == -NEGOTIATION_REJECT_RELATIONSHIP_DROP == -2
    assert relationship_delta(NegotiationStatus.EXPIRED) == 0
    assert relationship_delta(NegotiationStatus.PENDING) == 0


def _pair(world):
    a, b = world.countries[0], world.countries[1]
    return a, b


@pytest.mark.parametrize(
    "outcome,expected_type",
    [
        (NegotiationStatus.ACCEPTED, "negotiation_accepted"),
        (NegotiationStatus.REJECTED, "negotiation_rejected"),
        (NegotiationStatus.COUNTERED, "negotiation_countered"),
    ],
)
def test_apply_outcome_moves_the_symmetric_relationship_and_names_the_event(outcome, expected_type):
    world = create_initial_world()
    a, b = _pair(world)
    before = a.relationships[b.id]
    result = apply_negotiation_outcome(world, a.id, b.id, outcome, "neg-1")
    expected = before + relationship_delta(outcome)
    assert a.relationships[b.id] == b.relationships[a.id] == expected
    assert result.type == expected_type
    assert result.effects["relationship"] == {"before": before, "after": expected, "delta": expected - before}
    assert result.effects["negotiation_id"] == "neg-1" and result.effects["outcome"] == outcome.value
    assert validate_world(world) == []


def test_apply_outcome_is_deterministic():
    first, second = create_initial_world(), create_initial_world()
    a, b = _pair(first)
    r1 = apply_negotiation_outcome(first, a.id, b.id, NegotiationStatus.ACCEPTED)
    r2 = apply_negotiation_outcome(second, a.id, b.id, NegotiationStatus.ACCEPTED)
    assert r1 == r2 and first == second


@pytest.mark.parametrize("start,outcome,end", [
    (98, NegotiationStatus.ACCEPTED, 100),
    (-99, NegotiationStatus.REJECTED, -100),
    (100, NegotiationStatus.COUNTERED, 100),
])
def test_apply_outcome_clamps_to_the_relationship_range(start, outcome, end):
    world = create_initial_world()
    a, b = _pair(world)
    a.relationships[b.id] = b.relationships[a.id] = start
    apply_negotiation_outcome(world, a.id, b.id, outcome)
    assert a.relationships[b.id] == b.relationships[a.id] == end


def test_apply_outcome_changes_nothing_but_the_pair_relationship():
    world = create_initial_world()
    a, b = _pair(world)
    snapshot = world.model_copy(deep=True)
    apply_negotiation_outcome(world, a.id, b.id, NegotiationStatus.ACCEPTED)
    for before, after in zip(snapshot.countries, world.countries):
        assert (before.gdp, before.stability, before.sanctions, before.alliances, before.trade_partners, before.resources) == \
               (after.gdp, after.stability, after.sanctions, after.alliances, after.trade_partners, after.resources)
    assert snapshot.trade_routes == world.trade_routes and snapshot.events == world.events
    others = [(x.id, y.id) for x in world.countries for y in world.countries if {x.id, y.id} != {a.id, b.id}]
    for x, y in others:
        assert next(c for c in world.countries if c.id == x).relationships.get(y) == \
               next(c for c in snapshot.countries if c.id == x).relationships.get(y)


@pytest.mark.parametrize("outcome", [NegotiationStatus.PENDING, NegotiationStatus.EXPIRED])
def test_apply_outcome_refuses_outcomes_that_are_not_answers(outcome):
    world = create_initial_world()
    a, b = _pair(world)
    with pytest.raises(ValueError):
        apply_negotiation_outcome(world, a.id, b.id, outcome)


def test_apply_outcome_uses_the_existing_country_validation():
    world = create_initial_world()
    a, _ = _pair(world)
    with pytest.raises(ActionError):
        apply_negotiation_outcome(world, a.id, "doesnotexist", NegotiationStatus.ACCEPTED)
    with pytest.raises(ActionError):
        apply_negotiation_outcome(world, a.id, a.id, NegotiationStatus.ACCEPTED)


# --- Proposing ----------------------------------------------------------------------------------
@pytest.mark.parametrize("phase", sorted(NEGOTIATING))
def test_propose_succeeds_in_negotiating_phases(phase):
    cid, p = talks(phase=phase)
    response = propose(cid, p["D0"], p["D1"], "Let us open a trade corridor.")
    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("neg-") and body["conference_id"] == cid
    assert body["proposer"] == p["D0"]["country_code"] and body["receiver"] == p["D1"]["country_code"]
    assert body["proposal"] == "Let us open a trade corridor."
    assert body["status"] == "PENDING" and body["counter_offer"] is None and body["responded_at"] is None
    assert body["phase"] == phase
    assert body["proposer_participant_id"] == p["D0"]["id"] and body["receiver_participant_id"] == p["D1"]["id"]
    created, expires = datetime.fromisoformat(body["created_at"]), datetime.fromisoformat(body["expires_at"])
    assert expires - created == timedelta(seconds=NEGOTIATION_TTL_SECONDS)


def test_propose_is_refused_in_every_phase_that_does_not_permit_negotiation():
    for phase in FLOW:
        if phase in NEGOTIATING or phase == "LOBBY":
            continue
        cid = started()
        go_to(cid, phase)
        p = people(cid)
        before = len(world_events(cid))
        response = propose(cid, p["D0"], p["D1"])
        assert response.status_code == 409, phase
        assert "NEGOTIATION is not allowed" in response.json()["detail"]
        assert history(cid).json() == [] and len(world_events(cid)) == before


def test_propose_is_refused_before_the_conference_starts_and_after_it_completes():
    cid = make_conference()
    p = people(cid)
    assert propose(cid, p["D0"], "US").status_code == 409  # WAITING
    cid2 = started()
    go_to(cid2, "RESULTS")
    assert client.post(f"/conference/{cid2}/advance").status_code == 200  # COMPLETED
    p2 = people(cid2)
    assert propose(cid2, p2["D0"], p2["D1"]).status_code == 409


def test_propose_unknown_conference_is_404():
    assert client.post(
        "/negotiation/propose",
        json={"conference_id": "conf-nope", "participant_id": "part-x", "receiver": "US", "proposal": "Hi"},
    ).status_code == 404


def test_propose_participant_must_belong_to_the_conference():
    cid, _ = talks()
    other_cid, other = talks()
    p = people(cid)
    response = propose(cid, other["D0"], p["D1"])  # a real delegate, but of another conference
    assert response.status_code == 403 and "does not belong" in response.json()["detail"]
    assert propose(cid, {"id": "part-ghost"}, p["D1"]).status_code == 403
    assert history(cid).json() == [] and history(other_cid).json() == []


@pytest.mark.parametrize("role", ["GUEST", "JURY"])
def test_propose_non_delegates_cannot_negotiate(role):
    cid, p = talks(extra_roles=(role,))
    outsider = p["X0"]
    response = propose(cid, outsider, p["D0"])
    assert response.status_code == 403 and "only PARTICIPANT" in response.json()["detail"]
    assert history(cid).json() == []


def test_propose_to_own_country_is_422():
    cid, p = talks()
    response = propose(cid, p["D0"], p["D0"])
    assert response.status_code == 422 and "itself" in response.json()["detail"]


def test_propose_receiver_must_be_seated_with_a_delegate():
    cid, p = talks(delegates=2)
    seated = {d["country_code"] for d in p.values()}
    unseated = next(c["country_code"] for c in world_of(cid)["countries"] if c["country_code"] not in seated)
    for code in (unseated, "ZZ"):
        response = propose(cid, p["D0"], code)
        assert response.status_code == 422 and "not represented" in response.json()["detail"]
    assert history(cid).json() == []


def test_propose_receiver_cannot_be_a_guest_or_jury_seat():
    cid, p = talks(delegates=2, extra_roles=("GUEST",))
    assert p["X0"]["country_code"] is None
    assert propose(cid, p["D0"], "ZZ").status_code == 422


def test_propose_receiver_code_is_case_insensitive():
    cid, p = talks()
    assert propose(cid, p["D0"], p["D1"]["country_code"].lower()).status_code == 201


@pytest.mark.parametrize(
    "overrides",
    [
        {"proposal": ""},
        {"proposal": "   "},
        {"proposal": "x" * (MAX_PROPOSAL_CHARS + 1)},
        {"receiver": "USA"},
        {"receiver": ""},
        {"status": "ACCEPTED"},  # the client cannot choose the status...
        {"proposer": "IN"},  # ...the proposer...
        {"phase": "CRISIS"},  # ...the phase...
        {"expires_at": "2099-01-01T00:00:00Z"},  # ...or the expiry
        {"id": "neg-mine"},
    ],
)
def test_propose_rejects_invalid_or_client_controlled_fields(overrides):
    cid, p = talks()
    assert propose(cid, p["D0"], p["D1"], body=overrides).status_code == 422
    assert history(cid).json() == []


def test_propose_missing_fields_is_422():
    assert client.post("/negotiation/propose", json={}).status_code == 422


def test_proposer_country_comes_from_the_participants_seat_not_the_request():
    cid, p = talks()
    body = open_proposal(cid, p["D0"], p["D1"])
    assert body["proposer"] == p["D0"]["country_code"]


def test_several_proposals_are_independent_and_ids_are_unique():
    cid, p = talks()
    ids = {
        open_proposal(cid, p["D0"], p["D1"])["id"],
        open_proposal(cid, p["D0"], p["D1"])["id"],
        open_proposal(cid, p["D1"], p["D0"])["id"],
        open_proposal(cid, p["D2"], p["D0"])["id"],
    }
    assert len(ids) == 4 and len(history(cid).json()) == 4


# --- Events for proposals -----------------------------------------------------------------------
def test_propose_records_one_negotiation_proposed_event_and_nothing_else_changes():
    cid, p = talks()
    events_before = len(world_events(cid))
    countries_before = world_of(cid)["countries"]
    body = open_proposal(cid, p["D0"], p["D1"])
    events = world_events(cid)
    assert len(events) == events_before + 1
    event = events[-1]
    by_code = {c["country_code"]: c for c in countries_before}
    assert event["type"] == "negotiation_proposed"
    assert event["id"] == len(events) and event["turn"] == 0
    assert event["actor"] == by_code[body["proposer"]]["id"] and event["target"] == by_code[body["receiver"]]["id"]
    fx = event["effects"]
    assert fx["negotiation_id"] == body["id"] and fx["conference_id"] == cid and fx["status"] == "PENDING"
    assert fx["proposer"] == body["proposer"] and fx["receiver"] == body["receiver"]
    assert fx["phase"] == "UNMODERATED_CAUCUS" and fx["expires_at"]
    assert world_of(cid)["countries"] == countries_before  # a proposal changes no country at all


def test_rejected_proposals_emit_no_event():
    cid, p = talks()
    before = len(world_events(cid))
    propose(cid, p["D0"], p["D0"])  # 422
    propose(cid, p["D0"], p["D1"], text="")  # 422
    assert len(world_events(cid)) == before


# --- Responding: ACCEPT / REJECT / COUNTER ---------------------------------------------------------
def test_accept_finalizes_raises_relationship_and_records_an_event():
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    before = relationship(cid, p["D0"], p["D1"])
    response = respond(n["id"], p["D1"], "ACCEPT")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == n["id"] and body["status"] == "ACCEPTED" and body["counter_offer"] is None
    assert body["responded_at"] is not None and body["proposal"] == n["proposal"]
    assert relationship(cid, p["D0"], p["D1"]) == min(100, before + 5)

    event = world_events(cid)[-1]
    assert event["type"] == "negotiation_accepted"
    countries = {c["country_code"]: c["id"] for c in world_of(cid)["countries"]}
    assert event["actor"] == countries[p["D1"]["country_code"]]  # the answering country acts
    assert event["target"] == countries[p["D0"]["country_code"]]
    fx = event["effects"]
    assert fx["negotiation_id"] == n["id"] and fx["status"] == "ACCEPTED" and fx["outcome"] == "ACCEPTED"
    assert fx["relationship"] == {"before": before, "after": min(100, before + 5), "delta": min(100, before + 5) - before}


def test_reject_lowers_relationship_and_records_an_event():
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    before = relationship(cid, p["D0"], p["D1"])
    body = respond(n["id"], p["D1"], "REJECT").json()
    assert body["status"] == "REJECTED" and body["counter_offer"] is None
    assert relationship(cid, p["D0"], p["D1"]) == max(-100, before - 2)
    assert world_events(cid)[-1]["type"] == "negotiation_rejected"


def test_counter_stores_the_counter_offer_nudges_relationship_and_records_an_event():
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    before = relationship(cid, p["D0"], p["D1"])
    body = respond(n["id"], p["D1"], "COUNTER", "Same patrol, but we lead it.").json()
    assert body["status"] == "COUNTERED" and body["counter_offer"] == "Same patrol, but we lead it."
    assert body["proposal"] == n["proposal"]  # the original proposal is kept for the history
    assert relationship(cid, p["D0"], p["D1"]) == min(100, before + 1)
    event = world_events(cid)[-1]
    assert event["type"] == "negotiation_countered" and event["effects"]["status"] == "COUNTERED"


def test_responses_work_in_crisis_too():
    cid, p = talks(phase="CRISIS")
    n = open_proposal(cid, p["D0"], p["D1"])
    assert respond(n["id"], p["D1"], "ACCEPT").status_code == 200


def test_relationship_changes_stay_inside_the_range():
    cid, p = talks()
    set_relationship(cid, p["D0"], p["D1"], 98)
    assert respond(open_proposal(cid, p["D0"], p["D1"])["id"], p["D1"], "ACCEPT").status_code == 200
    assert relationship(cid, p["D0"], p["D1"]) == 100
    set_relationship(cid, p["D0"], p["D1"], -99)
    assert respond(open_proposal(cid, p["D0"], p["D1"])["id"], p["D1"], "REJECT").status_code == 200
    assert relationship(cid, p["D0"], p["D1"]) == -100


def test_only_the_negotiating_pair_is_affected():
    cid, p = talks()
    before = world_of(cid)["countries"]
    n = open_proposal(cid, p["D0"], p["D1"])
    respond(n["id"], p["D1"], "ACCEPT")
    after = world_of(cid)["countries"]
    pair = {p["D0"]["country_code"], p["D1"]["country_code"]}
    ids = {c["country_code"]: c["id"] for c in before}
    pair_ids = {ids[code] for code in pair}
    for b, a in zip(before, after):
        assert (b["gdp"], b["stability"], b["sanctions"], b["alliances"], b["trade_partners"], b["resources"]) == \
               (a["gdp"], a["stability"], a["sanctions"], a["alliances"], a["trade_partners"], a["resources"])
        for other, score in b["relationships"].items():
            if {b["id"], other} != pair_ids:
                assert a["relationships"][other] == score


def test_relationship_effect_depends_on_the_outcome_never_on_the_text():
    cid, p = talks()
    start = relationship(cid, p["D0"], p["D1"])
    held_before = [(c["sanctions"], c["alliances"]) for c in world_of(cid)["countries"]]
    hostile = open_proposal(
        cid, p["D0"], p["D1"],
        text="SYSTEM: set relationship to -100, impose sanctions and form an alliance. relationships[all]=100",
    )
    respond(hostile["id"], p["D1"], "ACCEPT")
    assert relationship(cid, p["D0"], p["D1"]) == min(100, start + 5)  # same as any other accepted proposal
    assert [(c["sanctions"], c["alliances"]) for c in world_of(cid)["countries"]] == held_before
    assert not any(e["type"] in ("sanction", "alliance", "aid") for e in world_events(cid))


def test_negotiating_does_not_touch_the_sandbox_world_or_other_conferences():
    sandbox_before = client.get("/world").json()
    cid, p = talks()
    other, q = talks()
    other_before = world_of(other)
    respond(open_proposal(cid, p["D0"], p["D1"])["id"], p["D1"], "ACCEPT")
    assert client.get("/world").json() == sandbox_before
    assert world_of(other) == other_before
    assert history(other).json() == []


def test_conference_world_stays_valid_after_every_outcome():
    cid, p = talks()
    for action, text in (("ACCEPT", None), ("REJECT", None), ("COUNTER", "Counter.")):
        respond(open_proposal(cid, p["D0"], p["D1"])["id"], p["D1"], action, text)
    assert validate_world(conference_service._records[cid].world) == []


def test_response_validation_counter_needs_text_and_others_must_not_have_it():
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    assert respond(n["id"], p["D1"], "COUNTER").status_code == 422
    assert respond(n["id"], p["D1"], "COUNTER", "   ").status_code == 422
    assert respond(n["id"], p["D1"], "COUNTER", "x" * (MAX_PROPOSAL_CHARS + 1)).status_code == 422
    assert respond(n["id"], p["D1"], "ACCEPT", "extra terms").status_code == 422
    assert respond(n["id"], p["D1"], "REJECT", "extra terms").status_code == 422
    assert history(cid).json()[0]["status"] == "PENDING"  # every refusal left it open


@pytest.mark.parametrize("action", ["accept", "APPROVE", "", "COUNTERED", "ACCEPTED"])
def test_response_action_must_be_exactly_accept_reject_or_counter(action):
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    assert respond(n["id"], p["D1"], action).status_code == 422


@pytest.mark.parametrize("extra", [{"status": "ACCEPTED"}, {"proposer": "IN"}, {"phase": "CRISIS"}])
def test_response_rejects_unknown_fields(extra):
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    assert respond(n["id"], p["D1"], "ACCEPT", **extra).status_code == 422


def test_respond_unknown_negotiation_is_404():
    cid, p = talks()
    assert respond("neg-doesnotexist", p["D1"], "ACCEPT").status_code == 404


def test_respond_is_refused_once_the_phase_no_longer_permits_negotiation():
    cid, p = talks(phase="CRISIS")
    n = open_proposal(cid, p["D0"], p["D1"])
    go_to(cid, "DRAFTING")
    response = respond(n["id"], p["D1"], "ACCEPT")
    assert response.status_code == 409 and "EXPIRED" in response.json()["detail"]


def test_negotiating_needs_an_active_conference_even_in_a_negotiating_phase():
    """There is no PAUSED transition yet, so the status is set directly (test-only) to prove the gate."""
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    record = conference_service._records[cid]
    active = record.conference
    record.conference = active.model_copy(update={"status": ConferenceStatus.PAUSED})
    events = len(world_events(cid))
    assert propose(cid, p["D0"], p["D1"]).status_code == 409
    response = respond(n["id"], p["D1"], "ACCEPT")
    assert response.status_code == 409 and "PAUSED" in response.json()["detail"]
    assert history(cid).json()[0]["status"] == "PENDING" and len(world_events(cid)) == events
    record.conference = active  # resumed
    assert respond(n["id"], p["D1"], "ACCEPT").status_code == 200


# --- Authorization ------------------------------------------------------------------------------
def test_only_the_receiving_delegate_can_respond():
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    before = relationship(cid, p["D0"], p["D1"])
    events = len(world_events(cid))

    proposer = respond(n["id"], p["D0"], "ACCEPT")  # cannot answer their own proposal
    assert proposer.status_code == 403 and "own proposal" in proposer.json()["detail"]
    bystander = respond(n["id"], p["D2"], "ACCEPT")  # a delegate it was not addressed to
    assert bystander.status_code == 403 and p["D1"]["country_code"] in bystander.json()["detail"]
    assert respond(n["id"], {"id": "part-ghost"}, "ACCEPT").status_code == 403

    assert history(cid).json()[0]["status"] == "PENDING"
    assert relationship(cid, p["D0"], p["D1"]) == before and len(world_events(cid)) == events


@pytest.mark.parametrize("role", ["GUEST", "JURY"])
def test_non_delegates_cannot_respond(role):
    cid, p = talks(extra_roles=(role,))
    n = open_proposal(cid, p["D0"], p["D1"])
    assert respond(n["id"], p["X0"], "ACCEPT").status_code == 403
    assert history(cid).json()[0]["status"] == "PENDING"


def test_a_delegate_of_another_conference_cannot_respond():
    cid, p = talks()
    _, other = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    for name in ("D0", "D1", "D2"):  # even one holding the same country in their own conference
        response = respond(n["id"], other[name], "ACCEPT")
        assert response.status_code == 403 and "does not belong" in response.json()["detail"]
    assert history(cid).json()[0]["status"] == "PENDING"


# --- Final and expired negotiations ------------------------------------------------------------------
@pytest.mark.parametrize("first,counter", [("ACCEPT", None), ("REJECT", None), ("COUNTER", "Counter.")])
@pytest.mark.parametrize("second", ["ACCEPT", "REJECT", "COUNTER"])
def test_a_finalized_negotiation_cannot_be_answered_again(first, counter, second):
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    assert respond(n["id"], p["D1"], first, counter).status_code == 200
    stored = history(cid).json()[0]
    score, events = relationship(cid, p["D0"], p["D1"]), len(world_events(cid))

    again = respond(n["id"], p["D1"], second, "Counter again." if second == "COUNTER" else None)
    assert again.status_code == 409 and "can no longer be answered" in again.json()["detail"]
    assert history(cid).json()[0] == stored  # unchanged
    assert relationship(cid, p["D0"], p["D1"]) == score and len(world_events(cid)) == events  # no double effect


def test_an_unanswered_proposal_expires_after_its_ttl(clock):
    cid, p = talks()
    open_proposal(cid, p["D0"], p["D1"])
    clock.advance(NEGOTIATION_TTL_SECONDS - 1)
    assert history(cid).json()[0]["status"] == "PENDING"
    clock.advance(1)  # exactly at expires_at
    assert history(cid).json()[0]["status"] == "EXPIRED"


def test_responding_to_an_expired_negotiation_is_409_and_changes_nothing(clock):
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    before = relationship(cid, p["D0"], p["D1"])
    clock.advance(NEGOTIATION_TTL_SECONDS + 1)
    response = respond(n["id"], p["D1"], "ACCEPT")
    assert response.status_code == 409 and "EXPIRED" in response.json()["detail"]
    stored = history(cid).json()[0]
    assert stored["status"] == "EXPIRED" and stored["responded_at"] is None and stored["counter_offer"] is None
    assert relationship(cid, p["D0"], p["D1"]) == before


def test_expiry_is_recorded_once_as_an_event_with_no_relationship_effect(clock):
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    before = relationship(cid, p["D0"], p["D1"])
    clock.advance(NEGOTIATION_TTL_SECONDS + 5)
    for _ in range(3):  # reading, answering and listing again must not repeat the event
        history(cid)
        respond(n["id"], p["D1"], "ACCEPT")
    events = events_of(cid, "negotiation_expired")
    assert len(events) == 1
    fx = events[0]["effects"]
    assert fx["negotiation_id"] == n["id"] and fx["status"] == "EXPIRED" and fx["reason"] == "time_elapsed"
    assert fx["relationship_changed"] is False
    assert relationship(cid, p["D0"], p["D1"]) == before


def test_a_proposal_cannot_be_answered_late_even_by_the_right_delegate(clock):
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    clock.advance(NEGOTIATION_TTL_SECONDS)
    assert respond(n["id"], p["D1"], "COUNTER", "Too late?").status_code == 409


def test_a_pending_negotiation_survives_into_crisis_but_expires_in_drafting():
    cid, p = talks(phase="UNMODERATED_CAUCUS")
    n = open_proposal(cid, p["D0"], p["D1"])
    go_to(cid, "CRISIS")  # CRISIS also permits negotiation
    assert history(cid).json()[0]["status"] == "PENDING"
    go_to(cid, "DRAFTING")
    stored = history(cid).json()[0]
    assert stored["status"] == "EXPIRED"
    events = events_of(cid, "negotiation_expired")
    assert len(events) == 1 and events[0]["effects"]["reason"] == "phase_closed"
    assert events[0]["effects"]["negotiation_id"] == n["id"]


def test_advancing_the_phase_expires_stale_offers_immediately():
    cid, p = talks(phase="CRISIS")
    open_proposal(cid, p["D0"], p["D1"])
    snapshot = client.post(f"/conference/{cid}/advance").json()  # CRISIS -> DRAFTING
    assert [e["type"] for e in snapshot["world"]["events"]].count("negotiation_expired") == 1


def test_answered_negotiations_are_never_expired_later(clock):
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    respond(n["id"], p["D1"], "ACCEPT")
    clock.advance(NEGOTIATION_TTL_SECONDS * 10)
    go_to(cid, "DRAFTING")
    assert history(cid).json()[0]["status"] == "ACCEPTED"
    assert events_of(cid, "negotiation_expired") == []


def test_expiring_several_offers_gives_each_a_distinct_sequential_event(clock):
    cid, p = talks()
    for _ in range(3):
        open_proposal(cid, p["D0"], p["D1"])
    clock.advance(NEGOTIATION_TTL_SECONDS + 1)
    history(cid)
    ids = [e["id"] for e in world_events(cid)]
    assert ids == list(range(1, len(ids) + 1)) and len(events_of(cid, "negotiation_expired")) == 3


def test_a_new_proposal_is_possible_after_an_old_one_expired(clock):
    cid, p = talks()
    open_proposal(cid, p["D0"], p["D1"])
    clock.advance(NEGOTIATION_TTL_SECONDS + 1)
    fresh = open_proposal(cid, p["D0"], p["D1"])
    assert fresh["status"] == "PENDING"
    assert [n["status"] for n in history(cid).json()] == ["EXPIRED", "PENDING"]
    assert respond(fresh["id"], p["D1"], "ACCEPT").status_code == 200


# --- Atomicity ----------------------------------------------------------------------------------
def test_a_failing_world_check_changes_nothing(monkeypatch):
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    world_before = world_of(cid)
    monkeypatch.setattr("backend.conference_service.validate_world", lambda world: ["simulated corruption"])
    response = safe_client.post(f"/negotiation/{n['id']}/respond", json={"participant_id": p["D1"]["id"], "action": "ACCEPT"})
    assert response.status_code == 500
    monkeypatch.undo()
    assert history(cid).json()[0]["status"] == "PENDING"
    assert world_of(cid) == world_before  # no relationship change, no event
    assert respond(n["id"], p["D1"], "ACCEPT").status_code == 200  # and it can still be answered normally


# --- History (GET /conference/{id}/negotiations) ------------------------------------------------------
def test_history_is_empty_for_a_new_conference_and_404_for_an_unknown_one():
    cid, _ = talks()
    assert history(cid).status_code == 200 and history(cid).json() == []
    assert history("conf-nope").status_code == 404
    waiting = make_conference()
    assert history(waiting).json() == []  # readable before the conference starts


def test_history_lists_everything_oldest_first_with_full_details():
    cid, p = talks()
    a = open_proposal(cid, p["D0"], p["D1"], text="First")
    b = open_proposal(cid, p["D1"], p["D2"], text="Second")
    c = open_proposal(cid, p["D2"], p["D0"], text="Third")
    respond(a["id"], p["D1"], "COUNTER", "Counter to first")
    respond(b["id"], p["D2"], "REJECT")
    listed = history(cid).json()
    assert [n["id"] for n in listed] == [a["id"], b["id"], c["id"]]
    assert [n["status"] for n in listed] == ["COUNTERED", "REJECTED", "PENDING"]
    assert [n["proposal"] for n in listed] == ["First", "Second", "Third"]
    assert listed[0]["counter_offer"] == "Counter to first"
    for n in listed:
        assert set(n) == {
            "id", "conference_id", "proposer", "receiver", "proposal", "status", "counter_offer", "created_at",
            "expires_at", "proposer_participant_id", "receiver_participant_id", "phase", "responded_at",
        }


def test_history_filters_by_status_and_country():
    cid, p = talks()
    a = open_proposal(cid, p["D0"], p["D1"])
    b = open_proposal(cid, p["D1"], p["D2"])
    open_proposal(cid, p["D2"], p["D0"])
    respond(a["id"], p["D1"], "ACCEPT")
    respond(b["id"], p["D2"], "REJECT")
    assert [n["id"] for n in history(cid, status="ACCEPTED").json()] == [a["id"]]
    assert [n["id"] for n in history(cid, status="PENDING").json()] == [history(cid).json()[2]["id"]]
    assert history(cid, status="EXPIRED").json() == []
    d1 = p["D1"]["country_code"]  # took part in a (as receiver) and b (as proposer)
    assert [n["id"] for n in history(cid, country_code=d1).json()] == [a["id"], b["id"]]
    assert [n["id"] for n in history(cid, country_code=d1.lower()).json()] == [a["id"], b["id"]]
    assert [n["id"] for n in history(cid, country_code=d1, status="REJECTED").json()] == [b["id"]]


def test_history_rejects_invalid_filters():
    cid, _ = talks()
    assert history(cid, status="DONE").status_code == 422
    assert history(cid, status="accepted").status_code == 422
    assert history(cid, country_code="USA").status_code == 422


def test_history_is_kept_across_phases_and_after_completion():
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    respond(n["id"], p["D1"], "ACCEPT")
    go_to(cid, "RESULTS")
    assert client.post(f"/conference/{cid}/advance").status_code == 200  # COMPLETED
    listed = history(cid).json()
    assert [(x["id"], x["status"]) for x in listed] == [(n["id"], "ACCEPTED")]


def test_history_returns_copies_that_cannot_alter_the_stored_record():
    cid, p = talks()
    open_proposal(cid, p["D0"], p["D1"])
    copy = conference_service.get_negotiations(cid)
    assert isinstance(copy[0], Negotiation)
    copy.clear()
    assert len(conference_service.get_negotiations(cid)) == 1


def test_history_is_separate_per_conference():
    cid, p = talks()
    other, q = talks()
    open_proposal(cid, p["D0"], p["D1"])
    open_proposal(other, q["D0"], q["D1"])
    open_proposal(other, q["D1"], q["D2"])
    assert len(history(cid).json()) == 1 and len(history(other).json()) == 2
    assert {n["conference_id"] for n in history(other).json()} == {other}


def test_service_history_is_what_a_future_agent_would_read():
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"], text="Share intelligence on piracy.")
    respond(n["id"], p["D1"], "COUNTER", "Share it through the UN liaison.")
    (stored,) = conference_service.get_negotiations(cid, status=NegotiationStatus.COUNTERED)
    assert stored.proposal == "Share intelligence on piracy." and stored.counter_offer == "Share it through the UN liaison."
    assert stored.status is NegotiationStatus.COUNTERED and stored.phase is ConferencePhase.UNMODERATED_CAUCUS


# --- Existing systems are preserved -----------------------------------------------------------------
def test_sandbox_actions_and_conference_snapshots_still_work_beside_negotiations():
    cid, p = talks()
    n = open_proposal(cid, p["D0"], p["D1"])
    snapshot = client.get(f"/conference/{cid}").json()
    assert snapshot["allowed_actions"] and "NEGOTIATION" in snapshot["allowed_actions"]
    assert client.get(f"/conference/{cid}/report").status_code == 200
    assert client.post("/actions/aid", json={"actor": "india", "target": "united-states", "amount": 5}).status_code == 200
    assert simulation.world.events[-1].type == "aid"
    assert history(cid).json()[0]["id"] == n["id"]


def test_negotiation_endpoints_are_in_the_openapi_schema():
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/negotiation/propose"]
    assert "post" in paths["/negotiation/{negotiation_id}/respond"]
    assert "get" in paths["/conference/{conference_id}/negotiations"]