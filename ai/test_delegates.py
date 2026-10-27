
"""Mocked tests for the Phase 8 AI delegates."""
import json

import pytest
from fastapi import HTTPException

from ai.delegates import (
    DelegateKind,
    DelegateRequest,
    SpeechKind,
    build_context,
    generate_delegate,
)
from backend.conference_service import conference_service
from backend.simulation import simulation


def make_conference(phase=None):
    snap = conference_service.create(
        "Phase 8 test",
        "UNSC",
        "Protection of critical infrastructure",
    )
    conference_service.join(
        snap.id, "India Delegate", "PARTICIPANT", "India"
    )
    conference_service.start(snap.id)

    if phase:
        while conference_service.get(snap.id).current_phase.value != phase:
            conference_service.advance(snap.id)

    return snap.id


def make_request(cid, **kwargs):
    return DelegateRequest(conference_id=cid, country_code="IN", **kwargs)


def valid_payload(kind):
    if kind == DelegateKind.STRATEGIST:
        return {
            "strategic_assessment": "Protect infrastructure while avoiding escalation.",
            "objectives": ["Resilience"],
            "red_lines": ["Sovereignty"],
            "recommended_actions": ["Share threat indicators"],
            "confidence": 0.8,
        }

    if kind == DelegateKind.SPEECH:
        speech = (
            "India supports resilient infrastructure through practical "
            "cooperation and respect for sovereignty."
        )
        return {
            "speech": speech,
            "key_points": ["Cooperation"],
            "word_count": len(speech.split()),
        }

    if kind == DelegateKind.NEGOTIATOR:
        return {
            "recommendation": "COUNTER",
            "rationale": "The offer lacks verification safeguards.",
            "proposed_terms": ["Independent review"],
            "counter_offer": "Add independent review and reciprocal reporting.",
        }

    if kind == DelegateKind.CRISIS:
        return {
            "assessment": "Escalation risk is elevated.",
            "response_options": ["Open emergency talks"],
            "preferred_response": "Open emergency talks",
            "escalation_risks": ["Misinterpretation"],
        }

    if kind == DelegateKind.RESOLUTION:
        return {
            "preambulatory_clauses": [{
                "text": "Recognizing the value of cooperation,",
                "rationale": "Frames a shared objective.",
            }],
            "operative_clauses": [{
                "text": "1. Encourages voluntary incident reporting;",
                "rationale": "A practical, nonbinding step.",
            }],
            "amendments": [],
            "feasibility": "Feasible as a voluntary mechanism.",
            "likely_support": [],
            "likely_opposition": [],
        }

    if kind == DelegateKind.CHAIR:
        return {
            "debate_summary": "Delegates discussed infrastructure resilience.",
            "procedural_issues": [],
            "suggested_transition": "UNMODERATED_CAUCUS",
            "transition_rationale": "More negotiation time may help.",
        }

    return {
        "feedback": "Feedback is based on recorded evidence only.",
        "proposed_scores": [{
            "country_code": "IN",
            "diplomacy": 80,
            "speaking": 75,
            "negotiation": 70,
            "strategy": 80,
            "crisis_management": 60,
            "resolution_quality": 70,
            "country_alignment": 85,
            "evidence": ["Recorded opening speech"],
        }],
        "limitations": ["Limited recorded debate"],
    }


@pytest.fixture(autouse=True)
def reset_state():
    conference_service.clear()
    simulation.reset()
    yield
    conference_service.clear()
    simulation.reset()


@pytest.mark.parametrize(
    "kind,phase,extra",
    [
        (DelegateKind.STRATEGIST, "OPENING_SPEECHES", {}),
        (
            DelegateKind.SPEECH,
            "OPENING_SPEECHES",
            {"speech_kind": SpeechKind.OPENING},
        ),
        (
            DelegateKind.NEGOTIATOR,
            "UNMODERATED_CAUCUS",
            {"offer": "Reciprocal incident reporting"},
        ),
        (DelegateKind.RESOLUTION, "DRAFTING", {}),
        (DelegateKind.CHAIR, "OPENING_SPEECHES", {}),
        (DelegateKind.JUDGE, "RESULTS", {}),
    ],
)
def test_supported_modules(kind, phase, extra):
    cid = make_conference(phase)
    before = conference_service.get(cid).model_dump(mode="json")

    result = generate_delegate(
        kind,
        make_request(cid, **extra),
        generator=lambda *_a, **_kw: json.dumps(valid_payload(kind)),
    )

    assert result["status"] == "SUCCESS"
    assert result["kind"] == kind.value
    assert conference_service.get(cid).model_dump(mode="json") == before


def test_country_context_uses_real_conference_data():
    cid = make_conference("OPENING_SPEECHES")
    context = build_context(cid, "IN")

    assert context["conference"]["committee"] == "UNSC"
    assert context["conference"]["agenda"] == (
        "Protection of critical infrastructure"
    )
    assert context["country"]["name"] == "India"
    assert context["country"]["official_profile"]["interests"]
    assert isinstance(context["events"], list)
    assert isinstance(context["speeches"], list)


def test_malformed_output_returns_failure():
    cid = make_conference("OPENING_SPEECHES")

    with pytest.raises(HTTPException) as error:
        generate_delegate(
            DelegateKind.STRATEGIST,
            make_request(cid),
            generator=lambda *_a, **_kw: "{bad json",
        )

    assert error.value.status_code == 502
    assert error.value.detail["status"] == "AI_REQUEST_FAILED"


def test_generation_exception_does_not_mutate_conference():
    cid = make_conference("OPENING_SPEECHES")
    before = conference_service.get(cid).model_dump(mode="json")

    def fail(*_a, **_kw):
        raise RuntimeError("private provider error")

    with pytest.raises(HTTPException) as error:
        generate_delegate(
            DelegateKind.STRATEGIST,
            make_request(cid),
            generator=fail,
        )

    assert error.value.status_code == 502
    assert "private provider error" not in str(error.value.detail)
    assert conference_service.get(cid).model_dump(mode="json") == before


def test_phase_restrictions():
    cid = make_conference("ROLL_CALL")

    with pytest.raises(HTTPException) as speech_error:
        generate_delegate(
            DelegateKind.SPEECH,
            make_request(cid, speech_kind=SpeechKind.OPENING),
            generator=lambda *_a, **_kw: "{}",
        )
    assert speech_error.value.status_code == 409

    with pytest.raises(HTTPException) as negotiation_error:
        generate_delegate(
            DelegateKind.NEGOTIATOR,
            make_request(cid, offer="Deal"),
            generator=lambda *_a, **_kw: "{}",
        )
    assert negotiation_error.value.status_code == 409

    with pytest.raises(HTTPException) as judge_error:
        generate_delegate(
            DelegateKind.JUDGE,
            make_request(cid),
            generator=lambda *_a, **_kw: "{}",
        )
    assert judge_error.value.status_code == 409


def test_crisis_agent_rejects_unknown_crisis():
    cid = make_conference("CRISIS")

    with pytest.raises(HTTPException) as error:
        generate_delegate(
            DelegateKind.CRISIS,
            make_request(cid, crisis_id="invented-crisis"),
            generator=lambda *_a, **_kw: json.dumps(
                valid_payload(DelegateKind.CRISIS)
            ),
        )

    assert error.value.status_code == 409
    assert "No active crisis is stored" in error.value.detail


def test_invalid_speech_word_count_is_rejected():
    cid = make_conference("OPENING_SPEECHES")
    speech_data = valid_payload(DelegateKind.SPEECH)
    speech_data["word_count"] += 1

    with pytest.raises(HTTPException) as error:
        generate_delegate(
            DelegateKind.SPEECH,
            make_request(cid, speech_kind=SpeechKind.OPENING),
            generator=lambda *_a, **_kw: json.dumps(speech_data),
        )

    assert error.value.status_code == 502
