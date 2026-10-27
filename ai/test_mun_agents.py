"""Phase 8: the conference AI roles.

Every Gemini reply here is a MOCK (a canned string given to the role through a fake `llm`). The conferences are real:
they are built through the backend API, so the context, the phase gates, the resolutions and the voting rules are the
real ones. The tests prove that valid proposals are accepted, that anything malformed or inconsistent with the
conference is rejected (never repaired), that an AI failure never becomes a valid MUN action, and that no role ever
changes a conference.
"""
import json

import pytest
from fastapi.testclient import TestClient

from ai.check_gemini import EXIT_CONFIG, CheckError
from ai.mun_chair import ChairAgent, claims_an_outcome
from ai.mun_context import build_context
from ai.mun_core import AIPreconditionError, AIResult
from ai.mun_crisis import CrisisAgent, CrisisBrief
from ai.mun_judge import JudgeAgent, build_judge_facts
from ai.mun_negotiation import NegotiationAgent
from ai.mun_opponent import OpponentIntelligenceAgent, build_opponent_dossier
from ai.mun_resolution import ResolutionAssistant
from ai.mun_speech import SpeechAgent
from ai.mun_strategist import StrategistAgent
from backend.main import app
from backend.rules import NotFoundError

client = TestClient(app)
FLOW = ["LOBBY", "ROLL_CALL", "OPENING_SPEECHES", "MODERATED_CAUCUS", "UNMODERATED_CAUCUS",
        "CRISIS", "DRAFTING", "VOTING", "RESULTS"]
NAMES = {"IN": "India", "US": "United States", "CN": "China"}


# --- helpers -------------------------------------------------------------------------------------------------
class Fake:
    """A scripted Gemini: returns `reply` (a dict is JSON-encoded) and remembers every prompt it was given."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return json.dumps(self.reply) if isinstance(self.reply, (dict, list)) else self.reply


def conference(phase, committee="GLOBAL_CYBERSECURITY", codes=("IN", "US", "CN")):
    cid = client.post("/conference/create", json={"name": "C", "committee": committee, "topic": "Cyber peace"}).json()["id"]
    for code in codes:
        r = client.post(f"/conference/{cid}/join", json={"name": f"Delegate {code}", "role": "PARTICIPANT", "country": code})
        assert r.status_code == 201
    assert client.post(f"/conference/{cid}/start").status_code == 200
    for _ in range(len(FLOW) + 1):
        if client.get(f"/conference/{cid}").json()["current_phase"] == phase:
            break
        assert client.post(f"/conference/{cid}/advance").status_code == 200
    people = {p["country_code"]: p for p in client.get(f"/conference/{cid}").json()["participants"]}
    return cid, people


def ctx(cid, code=None):
    return build_context(cid, code)


def state(cid):
    """Everything an AI role must never change."""
    return (
        client.get(f"/conference/{cid}").json(),
        client.get(f"/conference/{cid}/speeches").json(),
        client.get(f"/conference/{cid}/negotiations").json(),
        client.get(f"/conference/{cid}/resolutions").json() if client.get(f"/conference/{cid}/resolutions").status_code == 200 else None,
    )


def draft_resolution(cid, who, clause="Calls upon all states to cooperate.", submit=True):
    rid = client.post("/resolution", json={"conference_id": cid, "participant_id": who["id"], "title": "Digital Peace"}).json()["id"]
    client.post(f"/resolution/{rid}/clause", json={"participant_id": who["id"], "type": "PREAMBULATORY", "text": "Recalling the UN Charter."})
    client.post(f"/resolution/{rid}/clause", json={"participant_id": who["id"], "type": "OPERATIVE", "text": clause})
    if submit:
        assert client.post(f"/resolution/{rid}/submit", json={"participant_id": who["id"]}).status_code == 200
    return rid


def assert_failed(result, code):
    assert isinstance(result, AIResult)
    assert result.ok is False and result.output is None
    assert result.error_code == code


# =================================================================================================================
# context
# =================================================================================================================
def test_context_reads_committee_agenda_phase_delegates_and_time():
    cid, _ = conference("UNMODERATED_CAUCUS")
    c = ctx(cid, "IN")
    assert c.snapshot.committee == "GLOBAL_CYBERSECURITY" and c.snapshot.topic == "Cyber peace"
    assert c.phase.value == "UNMODERATED_CAUCUS" and c.active
    assert {d.country_name for d in c.delegates} == set(NAMES.values())
    assert c.me.country_name == "India"
    assert c.remaining_seconds is not None and c.remaining_seconds > 0
    assert {a.value for a in c.allowed_actions} == {"NEGOTIATION", "ALLIANCE", "RESOLUTION_EDIT"}


def test_context_rejects_unseated_country_and_unknown_conference():
    cid, _ = conference("OPENING_SPEECHES")
    with pytest.raises(AIPreconditionError):
        ctx(cid, "BR")
    with pytest.raises(NotFoundError):
        ctx("conf-missing")


# =================================================================================================================
# strategist
# =================================================================================================================
GOOD_STRATEGY = {"country": "India", "action": "NEGOTIATION", "target": "United States", "vote": None,
                 "resolution_id": None, "rationale": "Shared interest in cyber norms.", "expected_outcome": "A joint position."}


def test_strategist_accepts_a_valid_proposal_and_uses_context():
    cid, _ = conference("UNMODERATED_CAUCUS")
    fake = Fake(GOOD_STRATEGY)
    result = StrategistAgent(fake).propose(ctx(cid, "IN"))
    assert result.ok and result.advisory and result.output.action.value == "NEGOTIATION"
    system, user = fake.calls[0]
    assert "Cyber peace" in user and "UNMODERATED_CAUCUS" in user and "RED LINES" in user and "OPPONENT RECORD" in user
    assert "ALLIANCE | NEGOTIATION | RESOLUTION_EDIT" in system  # only what the phase permits is offered
    assert result.meta["allowed_actions"] == ["ALLIANCE", "NEGOTIATION", "RESOLUTION_EDIT"]


@pytest.mark.parametrize(
    "change",
    [
        {"action": "VOTE", "vote": "YES", "resolution_id": "res-x"},  # not permitted in this phase
        {"action": "NO_ACTION"},  # not a MUN action at all
        {"action": "negotiation"},  # wrong case
        {"target": "Atlantis"},
        {"target": "India"},  # own country
        {"target": None},  # NEGOTIATION needs a target
        {"vote": "YES"},  # vote only with VOTE
        {"resolution_id": "res-nope"},
        {"country": "China"},
        {"rationale": "  "},
        {"extra": "field"},
    ],
)
def test_strategist_rejects_invalid_proposals(change):
    cid, _ = conference("UNMODERATED_CAUCUS")
    result = StrategistAgent(Fake({**GOOD_STRATEGY, **change})).propose(ctx(cid, "IN"))
    assert_failed(result, "invalid_response")


@pytest.mark.parametrize("raw", ["", "not json", "[]", "```json\n{}\n```", '{"country":"India"}'])
def test_strategist_rejects_malformed_replies(raw):
    cid, _ = conference("UNMODERATED_CAUCUS")
    assert_failed(StrategistAgent(Fake(raw)).propose(ctx(cid, "IN")), "invalid_response")


def test_strategist_vote_must_name_an_open_resolution():
    cid, people = conference("DRAFTING")
    rid = draft_resolution(cid, people["IN"])
    client.post(f"/conference/{cid}/advance")  # VOTING
    vote = {**GOOD_STRATEGY, "country": "United States", "action": "VOTE", "target": None, "vote": "YES", "resolution_id": rid}
    assert StrategistAgent(Fake(vote)).propose(ctx(cid, "US")).ok
    assert_failed(StrategistAgent(Fake({**vote, "resolution_id": "res-zzz"})).propose(ctx(cid, "US")), "invalid_response")
    client.post(f"/resolution/{rid}/vote", json={"participant_id": people["US"]["id"], "country_code": "US", "vote": "YES"})
    fake = Fake(vote)  # US has voted: nothing left to vote on, refused before Gemini
    with pytest.raises(AIPreconditionError):
        StrategistAgent(fake).propose(ctx(cid, "US"))
    assert fake.calls == []


@pytest.mark.parametrize("phase", ["LOBBY", "ROLL_CALL", "RESULTS"])
def test_strategist_refuses_phases_with_no_actions_before_calling_gemini(phase):
    cid, _ = conference("ROLL_CALL") if phase != "RESULTS" else conference("RESULTS")
    fake = Fake(GOOD_STRATEGY)
    with pytest.raises(AIPreconditionError):
        StrategistAgent(fake).propose(ctx(cid, "IN"))
    assert fake.calls == []


def test_gemini_failure_is_a_failure_never_a_decision():
    cid, _ = conference("UNMODERATED_CAUCUS")
    for error in (CheckError("quota exceeded", 3), CheckError("no key", EXIT_CONFIG), RuntimeError("boom")):
        result = StrategistAgent(Fake(error)).propose(ctx(cid, "IN"))
        assert_failed(result, "gemini_error")
        assert "NO_ACTION" not in result.model_dump_json()


# =================================================================================================================
# speech
# =================================================================================================================
def speech(**change):
    return {"country": "India", "speech_type": "OPENING", "text": "India believes in cooperation.",
            "addressed_countries": ["China"], **change}


def test_opening_speech_is_drafted_and_flagged_submittable_for_the_speaker():
    cid, _ = conference("OPENING_SPEECHES")
    result = SpeechAgent(Fake(speech())).draft(ctx(cid, "IN"), "OPENING")
    assert result.ok and result.output.text.startswith("India")
    assert result.meta["submittable_now"] is True  # India joined first and holds the floor
    other = SpeechAgent(Fake(speech(country="China"))).draft(ctx(cid, "CN"), "OPENING")
    assert other.meta["submittable_now"] is False


def test_speech_types_must_fit_the_phase_before_gemini_is_called():
    cid, _ = conference("MODERATED_CAUCUS")
    fake = Fake(speech())
    with pytest.raises(AIPreconditionError):
        SpeechAgent(fake).draft(ctx(cid, "IN"), "OPENING")  # belongs to OPENING_SPEECHES
    with pytest.raises(AIPreconditionError):
        SpeechAgent(fake).draft(ctx(cid, "IN"), "REBUTTAL")  # needs a target
    with pytest.raises(AIPreconditionError):
        SpeechAgent(fake).draft(ctx(cid, "IN"), "CAUCUS", "US")  # takes no target
    cid2, _ = conference("OPENING_SPEECHES")
    with pytest.raises(AIPreconditionError):
        SpeechAgent(fake).draft(ctx(cid2, "IN"), "CAUCUS")
    with pytest.raises(AIPreconditionError):
        SpeechAgent(fake).draft(ctx(cid2, "IN"), "CLOSING")  # too early
    with pytest.raises(AIPreconditionError):
        SpeechAgent(fake).draft(ctx(cid2, "IN"), "SONNET")
    cid3, _ = conference("UNMODERATED_CAUCUS")
    with pytest.raises(AIPreconditionError):
        SpeechAgent(fake).draft(ctx(cid3, "IN"), "REBUTTAL", "US")  # this phase permits no speeches
    assert fake.calls == []


def test_rebuttal_response_and_closing():
    cid, people = conference("MODERATED_CAUCUS")
    client.post(f"/conference/{cid}/speeches", json={"participant_id": people["US"]["id"], "country_code": "US", "text": "x"})
    rebuttal = speech(speech_type="REBUTTAL", addressed_countries=["United States"])
    fake = Fake(rebuttal)
    assert SpeechAgent(fake).draft(ctx(cid, "IN"), "REBUTTAL", "US").ok
    assert "OPPONENT RECORD: United States" in fake.calls[0][1]
    assert SpeechAgent(Fake({**rebuttal, "speech_type": "RESPONSE"})).draft(ctx(cid, "IN"), "RESPONSE", "US").ok
    assert_failed(SpeechAgent(Fake(speech(speech_type="REBUTTAL", addressed_countries=["China"]))).draft(ctx(cid, "IN"), "REBUTTAL", "US"), "invalid_response")
    assert SpeechAgent(Fake(speech(speech_type="CLOSING"))).draft(ctx(cid, "IN"), "CLOSING").ok
    with pytest.raises(AIPreconditionError):
        SpeechAgent(Fake(rebuttal)).draft(ctx(cid, "IN"), "REBUTTAL", "IN")


@pytest.mark.parametrize(
    "change",
    [{"speech_type": "CAUCUS"}, {"text": ""}, {"text": "x" * 5001}, {"addressed_countries": ["Atlantis"]},
     {"addressed_countries": ["India"]}, {"addressed_countries": ["China", "China"]}, {"country": "China"}, {"extra": 1}],
)
def test_speech_rejects_invalid_drafts(change):
    cid, _ = conference("OPENING_SPEECHES")
    assert_failed(SpeechAgent(Fake(speech(**change))).draft(ctx(cid, "IN"), "OPENING"), "invalid_response")


# =================================================================================================================
# negotiation
# =================================================================================================================
def offer_from_us(cid, people):
    r = client.post("/negotiation/propose", json={"conference_id": cid, "participant_id": people["US"]["id"],
                                                  "receiver": "IN", "proposal": "Joint cyber exercises."})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def reply(**change):
    return {"country": "India", "action": "ACCEPT", "counter_offer": None, "crosses_red_line": False, "reason": "Fits.", **change}


def test_respond_accept_reject_counter():
    cid, people = conference("UNMODERATED_CAUCUS")
    nid = offer_from_us(cid, people)
    fake = Fake(reply())
    assert NegotiationAgent(fake).respond(ctx(cid, "IN"), nid).ok
    assert "Joint cyber exercises." in fake.calls[0][1] and "RED LINES" in fake.calls[0][1]
    assert NegotiationAgent(Fake(reply(action="REJECT", crosses_red_line=True))).respond(ctx(cid, "IN"), nid).ok
    counter = NegotiationAgent(Fake(reply(action="COUNTER", counter_offer="Exercises plus data sharing limits."))).respond(ctx(cid, "IN"), nid)
    assert counter.ok and counter.output.counter_offer.startswith("Exercises")


@pytest.mark.parametrize(
    "change",
    [{"action": "COUNTER"}, {"action": "COUNTER", "counter_offer": " "}, {"counter_offer": "terms"},
     {"action": "REJECT", "counter_offer": "terms"}, {"crosses_red_line": True},  # ACCEPT across a red line
     {"action": "MAYBE"}, {"action": "NO_ACTION"}, {"country": "China"}, {"crosses_red_line": "yes"}],
)
def test_respond_rejects_inconsistent_replies(change):
    cid, people = conference("UNMODERATED_CAUCUS")
    nid = offer_from_us(cid, people)
    assert_failed(NegotiationAgent(Fake(reply(**change))).respond(ctx(cid, "IN"), nid), "invalid_response")


def test_respond_preconditions():
    cid, people = conference("UNMODERATED_CAUCUS")
    nid = offer_from_us(cid, people)
    fake = Fake(reply())
    with pytest.raises(AIPreconditionError):
        NegotiationAgent(fake).respond(ctx(cid, "US"), nid)  # the proposer cannot answer its own offer
    with pytest.raises(AIPreconditionError):
        NegotiationAgent(fake).respond(ctx(cid, "IN"), "neg-missing")
    client.post(f"/negotiation/{nid}/respond", json={"participant_id": people["IN"]["id"], "action": "REJECT"})
    with pytest.raises(AIPreconditionError):
        NegotiationAgent(fake).respond(ctx(cid, "IN"), nid)  # already final
    cid2, _ = conference("MODERATED_CAUCUS")
    with pytest.raises(AIPreconditionError):
        NegotiationAgent(fake).propose_offer(ctx(cid2, "IN"), "US")  # phase does not permit negotiating
    assert fake.calls == []


def test_propose_offer():
    cid, _ = conference("UNMODERATED_CAUCUS")
    good = {"country": "India", "receiver": "China", "proposal": "A trade corridor for cyber-secure goods.", "reason": "Mutual gain."}
    assert NegotiationAgent(Fake(good)).propose_offer(ctx(cid, "IN"), "CN").ok
    assert_failed(NegotiationAgent(Fake({**good, "receiver": "United States"})).propose_offer(ctx(cid, "IN"), "CN"), "invalid_response")
    assert_failed(NegotiationAgent(Fake({**good, "proposal": "x" * 2001})).propose_offer(ctx(cid, "IN"), "CN"), "invalid_response")
    with pytest.raises(AIPreconditionError):
        NegotiationAgent(Fake(good)).propose_offer(ctx(cid, "IN"), "IN")


# =================================================================================================================
# crisis
# =================================================================================================================
CRISIS = CrisisBrief(title="Grid hack", description="A cyberattack has disabled a regional power grid.")


def analysis(**change):
    return {"country": "India", "severity": "HIGH", "summary": "A serious infrastructure attack.",
            "affected_countries": ["China"], "key_risks": ["Escalation"],
            "recommended_responses": [{"kind": "NEGOTIATE", "target": "China", "description": "Open talks.", "rationale": "De-escalate."},
                                      {"kind": "STATEMENT", "target": None, "description": "Condemn.", "rationale": "Signal."}],
            **change}


def test_crisis_analysis_and_phase_permissions():
    cid, _ = conference("CRISIS")
    fake = Fake(analysis())
    result = CrisisAgent(fake).analyze(ctx(cid, "IN"), CRISIS)
    assert result.ok and result.output.severity.value == "HIGH" and "Grid hack" in fake.calls[0][1]
    assert result.meta["crisis_phase_open"] is True
    assert result.meta["permitted_now"] == {"STATEMENT": False, "NEGOTIATE": True, "RESOLUTION": False,
                                            "ALLIANCE": False, "SANCTION": None, "AID": None}


@pytest.mark.parametrize(
    "change",
    [{"severity": "EXTREME"}, {"affected_countries": ["Atlantis"]}, {"affected_countries": ["China", "China"]},
     {"key_risks": []}, {"recommended_responses": []},
     {"recommended_responses": [{"kind": "SANCTION", "target": None, "description": "d", "rationale": "r"}]},
     {"recommended_responses": [{"kind": "AID", "target": "India", "description": "d", "rationale": "r"}]},
     {"recommended_responses": [{"kind": "WAIT", "target": None, "description": "d", "rationale": "r"}]},
     {"recommended_responses": [{"kind": "STATEMENT", "target": None, "description": "d", "rationale": "r"}] * 4}],
)
def test_crisis_rejects_invalid_analyses(change):
    cid, _ = conference("CRISIS")
    assert_failed(CrisisAgent(Fake(analysis(**change))).analyze(ctx(cid, "IN"), CRISIS), "invalid_response")


# =================================================================================================================
# resolution assistant
# =================================================================================================================
def test_suggest_clauses_for_a_draft():
    cid, people = conference("DRAFTING")
    rid = draft_resolution(cid, people["IN"], submit=False)
    good = {"country": "India", "suggestions": [{"type": "OPERATIVE", "text": "Establishes a rapid-response cyber desk.", "rationale": "Speed."}]}
    assert ResolutionAssistant(Fake(good)).suggest_clauses(ctx(cid, "IN"), rid).ok
    dup = {"country": "India", "suggestions": [{"type": "OPERATIVE", "text": "calls upon all states to cooperate.", "rationale": "Dup."}]}
    assert_failed(ResolutionAssistant(Fake(dup)).suggest_clauses(ctx(cid, "IN"), rid), "invalid_response")
    assert_failed(ResolutionAssistant(Fake({**good, "suggestions": []})).suggest_clauses(ctx(cid, "IN"), rid), "invalid_response")
    assert_failed(ResolutionAssistant(Fake({**good, "suggestions": [{"type": "OPERATIVE", "text": "t"}]})).suggest_clauses(ctx(cid, "IN"), rid), "invalid_response")
    client.post(f"/resolution/{rid}/submit", json={"participant_id": people["IN"]["id"]})
    with pytest.raises(AIPreconditionError):  # a submitted resolution takes amendments, not new clauses
        ResolutionAssistant(Fake(good)).suggest_clauses(ctx(cid, "IN"), rid)


def review(**change):
    return {"country": "India", "readiness": "NEEDS_WORK", "summary": "Reasonable but vague.", "strengths": ["Clear preamble"],
            "weaknesses": ["No timeline"], "issues": [{"clause_number": 2, "severity": "MAJOR", "issue": "No enforcement."}], **change}


def test_review_checks_clause_numbers_and_structure():
    cid, people = conference("DRAFTING")
    rid = draft_resolution(cid, people["IN"])
    ok = ResolutionAssistant(Fake(review())).review_resolution(ctx(cid, "IN"), rid)
    assert ok.ok and ok.meta["operative_clauses"] == 1 and ok.meta["structural_findings"] == []
    assert_failed(ResolutionAssistant(Fake(review(issues=[{"clause_number": 9, "severity": "MINOR", "issue": "x"}]))).review_resolution(ctx(cid, "IN"), rid), "invalid_response")
    assert_failed(ResolutionAssistant(Fake(review(readiness="PERFECT"))).review_resolution(ctx(cid, "IN"), rid), "invalid_response")
    empty = client.post("/resolution", json={"conference_id": cid, "participant_id": people["IN"]["id"], "title": "Empty"}).json()["id"]
    bad = ResolutionAssistant(Fake(review(readiness="READY", issues=[]))).review_resolution(ctx(cid, "IN"), empty)
    assert_failed(bad, "invalid_response")  # READY despite no operative clause
    with pytest.raises(AIPreconditionError):
        ResolutionAssistant(Fake(review())).review_resolution(ctx(cid, "IN"), "res-missing")


def test_amendment_suggestions_are_checked_against_the_stored_resolution():
    cid, people = conference("DRAFTING")
    rid = draft_resolution(cid, people["IN"])
    clauses = client.get(f"/resolution/{rid}").json()["clauses"]
    operative = next(c for c in clauses if c["type"] == "OPERATIVE")["id"]
    pre = next(c for c in clauses if c["type"] == "PREAMBULATORY")["id"]

    def amend(*items):
        return {"country": "United States", "amendments": [{"clause_id": None, "type": None, "text": None, "rationale": "Better.", **i} for i in items]}

    run = lambda reply: ResolutionAssistant(Fake(reply)).suggest_amendments(ctx(cid, "US"), rid)  # noqa: E731
    assert run(amend({"action": "ADD", "type": "OPERATIVE", "text": "Creates an annual review."})).ok
    assert run(amend({"action": "MODIFY", "clause_id": operative, "text": "Urges all states to cooperate."})).ok
    assert run(amend({"action": "REMOVE", "clause_id": pre})).ok
    for bad in (
        amend({"action": "REMOVE", "clause_id": operative}),  # would leave no operative clause
        amend({"action": "MODIFY", "clause_id": "clause-nope", "text": "t"}),
        amend({"action": "ADD", "clause_id": operative, "type": "OPERATIVE", "text": "t"}),
        amend({"action": "ADD", "type": "OPERATIVE"}),  # no text
        amend({"action": "REMOVE", "clause_id": pre, "text": "t"}),
        amend({"action": "MODIFY", "clause_id": operative}),
        amend({"action": "MODIFY", "clause_id": operative, "text": "Calls upon all states to cooperate."}),  # changes nothing
        amend({"action": "REMOVE", "clause_id": pre}, {"action": "MODIFY", "clause_id": pre, "text": "t"}),
        amend({"action": "SWAP"}),
    ):
        assert_failed(run(bad), "invalid_response")
    draft = draft_resolution(cid, people["IN"], submit=False)
    with pytest.raises(AIPreconditionError):
        ResolutionAssistant(Fake(amend())).suggest_amendments(ctx(cid, "US"), draft)


def estimate(votes, summary="Split."):
    return {"summary": summary, "estimates": [{"country": NAMES[c], "likely_vote": v, "confidence": "MEDIUM", "reason": "Because."} for c, v in votes.items()]}


def test_support_estimate_projects_a_tally_with_the_real_rules():
    cid, people = conference("DRAFTING")
    rid = draft_resolution(cid, people["IN"])
    result = ResolutionAssistant(Fake(estimate({"IN": "YES", "US": "YES", "CN": "NO"}))).estimate_support(ctx(cid, "IN"), rid)
    out = result.output
    assert result.ok and out.official is False
    assert (out.projected_result.yes, out.projected_result.no) == (2, 1) and out.projected_result.passed is True
    veto = ResolutionAssistant(Fake(estimate({"IN": "NO", "US": "NO", "CN": "NO"}))).estimate_support(ctx(cid, "IN"), rid)
    assert veto.output.projected_result.passed is False
    for bad in (
        estimate({"IN": "YES", "US": "YES"}),  # China missing
        estimate({"IN": "YES", "US": "YES", "CN": "MAYBE"}),
        {**estimate({"IN": "YES", "US": "YES", "CN": "YES"}), "estimates": estimate({"IN": "YES"})["estimates"] * 3},
        {"summary": "s", "estimates": [{"country": "Atlantis", "likely_vote": "YES", "confidence": "LOW", "reason": "r"}]},
    ):
        assert_failed(ResolutionAssistant(Fake(bad)).estimate_support(ctx(cid, "IN"), rid), "invalid_response")


def test_support_estimate_keeps_recorded_votes_and_refuses_final_or_draft():
    cid, people = conference("DRAFTING")
    rid = draft_resolution(cid, people["IN"])
    draft = draft_resolution(cid, people["IN"], submit=False)
    with pytest.raises(AIPreconditionError):
        ResolutionAssistant(Fake({})).estimate_support(ctx(cid, "IN"), draft)
    client.post(f"/conference/{cid}/advance")  # VOTING
    client.post(f"/resolution/{rid}/vote", json={"participant_id": people["CN"]["id"], "country_code": "CN", "vote": "NO"})
    ok = ResolutionAssistant(Fake(estimate({"IN": "YES", "US": "YES"}))).estimate_support(ctx(cid, "IN"), rid)
    assert ok.ok and ok.output.recorded_votes == {"CN": "NO"}
    assert_failed(ResolutionAssistant(Fake(estimate({"IN": "YES", "US": "YES", "CN": "YES"}))).estimate_support(ctx(cid, "IN"), rid), "invalid_response")
    for code in ("IN", "US"):
        client.post(f"/resolution/{rid}/vote", json={"participant_id": people[code]["id"], "country_code": code, "vote": "YES"})
    with pytest.raises(AIPreconditionError):  # decided: the official result stands
        ResolutionAssistant(Fake({})).estimate_support(ctx(cid, "IN"), rid)


# =================================================================================================================
# opponent intelligence
# =================================================================================================================
def test_dossier_is_deterministic_and_assessment_uses_it():
    cid, people = conference("UNMODERATED_CAUCUS")
    nid = offer_from_us(cid, people)
    client.post(f"/negotiation/{nid}/respond", json={"participant_id": people["IN"]["id"], "action": "ACCEPT"})
    d = build_opponent_dossier(ctx(cid, "IN"), "US")
    assert d.country_name == "United States" and d.negotiations_proposed == 1 and d.negotiations_with_me
    assert build_opponent_dossier(ctx(cid, "US"), "IN").acceptance_rate == 1.0
    assert d.relationship_with_me is not None
    good = {"country": "United States", "likely_stance": "SUPPORTIVE", "confidence": "LOW", "observed_patterns": ["Proposed talks."],
            "leverage_points": [], "recommended_approach": "Build on the accepted offer."}
    fake = Fake(good)
    result = OpponentIntelligenceAgent(fake).assess(ctx(cid, "IN"), "US")
    assert result.ok and result.meta["dossier"]["negotiations_proposed"] == 1 and "OPPONENT RECORD" in fake.calls[0][1]
    for bad in ({"likely_stance": "HATES"}, {"country": "China"}, {"observed_patterns": []}, {"confidence": "CERTAIN"}):
        assert_failed(OpponentIntelligenceAgent(Fake({**good, **bad})).assess(ctx(cid, "IN"), "US"), "invalid_response")
    with pytest.raises(AIPreconditionError):
        OpponentIntelligenceAgent(Fake(good)).assess(ctx(cid, "IN"), "IN")


# =================================================================================================================
# chair
# =================================================================================================================
def test_chair_gives_guidance_and_decides_nothing():
    cid, _ = conference("MODERATED_CAUCUS")
    good = {"guidance": "The phase permits speeches and motions; the chair may recognise the next speaker.",
            "procedural_options": ["Recognise the next speaker."], "cautions": []}
    before = state(cid)
    result = ChairAgent(Fake(good)).guide(ctx(cid), "What can we do now?")
    assert result.ok and result.meta["decides_nothing"] is True and result.meta["phase"] == "MODERATED_CAUCUS"
    assert result.meta["next_step"] == "UNMODERATED_CAUCUS" and "MOTION" in result.meta["allowed_actions"]
    assert state(cid) == before


@pytest.mark.parametrize(
    "text",
    ["The resolution has been passed.", "I hereby rule the motion out of order.", "I declare the vote closed.",
     "The motion was rejected.", "I open the voting now."],
)
def test_chair_cannot_declare_outcomes(text):
    cid, _ = conference("VOTING")
    reply = {"guidance": text, "procedural_options": ["Wait."], "cautions": []}
    assert_failed(ChairAgent(Fake(reply)).guide(ctx(cid)), "invalid_response")
    assert_failed(ChairAgent(Fake({"guidance": "ok", "procedural_options": [text], "cautions": []})).guide(ctx(cid)), "invalid_response")


def test_chair_procedural_explanations_are_not_flagged():
    for text in ("A resolution passes when it meets the required majority.", "The chair may rule on a motion; delegates can appeal.",
                 "Voting opens in the next phase."):
        assert not claims_an_outcome(text)


def test_chair_schema_rejects_extra_fields_and_long_questions():
    cid, _ = conference("VOTING")
    assert_failed(ChairAgent(Fake({"guidance": "g", "procedural_options": ["o"], "cautions": [], "ruling": "passed"})).guide(ctx(cid)), "invalid_response")
    with pytest.raises(ValueError):
        ChairAgent(Fake({})).guide(ctx(cid), "q" * 501)


# =================================================================================================================
# judge
# =================================================================================================================
def finish(cid):
    for _ in range(len(FLOW) + 1):
        if client.get(f"/conference/{cid}").json()["status"] == "COMPLETED":
            return
        assert client.post(f"/conference/{cid}/advance").status_code == 200


def feedback(names=("India", "United States", "China"), **change):
    return {"overall_assessment": "A constructive session.", "highlights": ["Good drafting."], "concerns": [],
            "delegate_feedback": [{"country": n, "rating": "SOLID", "strengths": ["Clear."], "improvements": ["Be bolder."]} for n in names], **change}


def test_judge_needs_a_completed_conference_and_keeps_official_results():
    cid, people = conference("DRAFTING")
    rid = draft_resolution(cid, people["IN"])
    fake = Fake(feedback())
    with pytest.raises(AIPreconditionError):
        JudgeAgent(fake).evaluate(ctx(cid))
    assert fake.calls == []
    client.post(f"/conference/{cid}/advance")  # VOTING
    for code, vote in (("IN", "YES"), ("US", "YES"), ("CN", "NO")):
        client.post(f"/resolution/{rid}/vote", json={"participant_id": people[code]["id"], "country_code": code, "vote": vote})
    finish(cid)
    official = client.get(f"/resolution/{rid}").json()
    result = JudgeAgent(Fake(feedback())).evaluate(ctx(cid))
    facts = result.output.deterministic
    assert result.ok and result.output.scores_changed is False
    assert facts.resolutions_passed == 1 and facts.resolutions[0].official_result["yes"] == 2
    assert facts.resolutions[0].official_result == official["result"]  # copied from the backend unchanged
    india = next(d for d in facts.delegates if d.country_code == "IN")
    assert india.resolutions_sponsored == 1 and india.sponsored_passed == 1 and india.votes_yes == 1
    assert len(result.output.qualitative.delegate_feedback) == 3
    assert build_judge_facts(ctx(cid)) == facts  # deterministic


@pytest.mark.parametrize(
    "reply",
    [feedback(names=("India", "United States")), feedback(names=("India", "India", "United States", "China")),
     feedback(names=("India", "United States", "China", "Atlantis")),
     feedback(overall_assessment=""), feedback(highlights=[]), feedback(score=97),
     feedback(delegate_feedback=[{"country": "India", "rating": "GREAT", "strengths": ["a"], "improvements": ["b"]}])],
)
def test_judge_rejects_incomplete_or_invalid_feedback(reply):
    cid, _ = conference("DRAFTING")
    finish(cid)
    assert_failed(JudgeAgent(Fake(reply)).evaluate(ctx(cid)), "invalid_response")


def test_judge_gemini_failure_has_no_evaluation():
    cid, _ = conference("DRAFTING")
    finish(cid)
    assert_failed(JudgeAgent(Fake(CheckError("down", 3))).evaluate(ctx(cid)), "gemini_error")


# =================================================================================================================
# no role changes a conference
# =================================================================================================================
def test_no_role_changes_the_conference():
    cid, people = conference("UNMODERATED_CAUCUS")
    nid = offer_from_us(cid, people)
    rid = draft_resolution(cid, people["IN"], submit=False)
    before = state(cid)
    StrategistAgent(Fake(GOOD_STRATEGY)).propose(ctx(cid, "IN"))
    NegotiationAgent(Fake(reply(action="COUNTER", counter_offer="c"))).respond(ctx(cid, "IN"), nid)
    CrisisAgent(Fake(analysis())).analyze(ctx(cid, "IN"), CRISIS)
    ResolutionAssistant(Fake({"country": "India", "suggestions": [{"type": "OPERATIVE", "text": "New.", "rationale": "r"}]})).suggest_clauses(ctx(cid, "IN"), rid)
    ChairAgent(Fake({"guidance": "g", "procedural_options": ["o"], "cautions": []})).guide(ctx(cid))
    assert state(cid) == before