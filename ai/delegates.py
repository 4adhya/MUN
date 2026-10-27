
"""Phase 8 MUN delegate agents. All outputs are proposals; the backend remains authoritative."""
from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any, Optional, Type

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai.country_agent import COUNTRY_PROFILES
from ai.gemini_client import generate_json_text
from backend.conference_service import conference_service
from backend.mun import (
    ConferencePhase,
    ConferenceStatus,
    ParticipantRole,
)
from backend.resolution_service import resolution_service

logger = logging.getLogger("worldevent.ai.delegates")
router = APIRouter(prefix="/delegates", tags=["AI delegates"])

MAX_CONTEXT_CHARS = 9000
MAX_HISTORY_ITEMS = 12


class DelegateKind(str, Enum):
    STRATEGIST = "STRATEGIST"
    SPEECH = "SPEECH"
    NEGOTIATOR = "NEGOTIATOR"
    CRISIS = "CRISIS"
    RESOLUTION = "RESOLUTION"
    CHAIR = "CHAIR"
    JUDGE = "JUDGE"


class SpeechKind(str, Enum):
    OPENING = "OPENING"
    MODERATED_CAUCUS = "MODERATED_CAUCUS"
    REBUTTAL = "REBUTTAL"
    CLOSING = "CLOSING"


class DelegateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conference_id: str = Field(min_length=1, max_length=64)
    country_code: str = Field(pattern=r"^[A-Za-z]{2}$")
    task: Optional[str] = Field(default=None, max_length=2000)
    speech_kind: Optional[SpeechKind] = None
    offer: Optional[str] = Field(default=None, max_length=1500)
    resolution_id: Optional[str] = Field(default=None, max_length=64)
    crisis_id: Optional[str] = Field(default=None, max_length=64)
    speech_limit_words: int = Field(default=180, ge=40, le=500)

    @model_validator(mode="after")
    def normalize_code(self):
        self.country_code = self.country_code.upper()
        return self


class StrategistOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategic_assessment: str = Field(min_length=1, max_length=1800)
    objectives: list[str] = Field(min_length=1, max_length=5)
    red_lines: list[str] = Field(default_factory=list, max_length=5)
    recommended_actions: list[str] = Field(min_length=1, max_length=5)
    confidence: float = Field(ge=0, le=1)


class SpeechOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speech: str = Field(min_length=1, max_length=5000)
    key_points: list[str] = Field(default_factory=list, max_length=5)
    word_count: int = Field(ge=1, le=500)

    @model_validator(mode="after")
    def check_word_count(self):
        actual = len(self.speech.split())
        if actual != self.word_count:
            raise ValueError("word_count must match speech")
        return self


class NegotiatorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: str = Field(
        pattern=r"^(ACCEPT|REJECT|COUNTER|PROPOSE|NO_ACTION)$"
    )
    rationale: str = Field(min_length=1, max_length=1200)
    proposed_terms: list[str] = Field(default_factory=list, max_length=6)
    counter_offer: Optional[str] = Field(default=None, max_length=1500)

    @model_validator(mode="after")
    def counter_required(self):
        if self.recommendation == "COUNTER" and not self.counter_offer:
            raise ValueError("COUNTER requires counter_offer")
        return self


class CrisisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment: str = Field(min_length=1, max_length=1200)
    response_options: list[str] = Field(min_length=1, max_length=4)
    preferred_response: str = Field(min_length=1, max_length=500)
    escalation_risks: list[str] = Field(default_factory=list, max_length=4)


class Clause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1500)
    rationale: str = Field(min_length=1, max_length=500)


class ResolutionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preambulatory_clauses: list[Clause] = Field(default_factory=list, max_length=8)
    operative_clauses: list[Clause] = Field(default_factory=list, max_length=8)
    amendments: list[str] = Field(default_factory=list, max_length=5)
    feasibility: str = Field(min_length=1, max_length=1000)
    likely_support: list[str] = Field(default_factory=list, max_length=8)
    likely_opposition: list[str] = Field(default_factory=list, max_length=8)


class ChairOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    debate_summary: str = Field(min_length=1, max_length=1800)
    procedural_issues: list[str] = Field(default_factory=list, max_length=6)
    suggested_transition: Optional[str] = Field(
        default=None,
        pattern=(
            r"^(ROLL_CALL|OPENING_SPEECHES|MODERATED_CAUCUS|"
            r"UNMODERATED_CAUCUS|CRISIS|DRAFTING|VOTING|"
            r"RESULTS|COMPLETED)$"
        ),
    )
    transition_rationale: str = Field(default="", max_length=700)


class ScoreProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    diplomacy: int = Field(ge=0, le=100)
    speaking: int = Field(ge=0, le=100)
    negotiation: int = Field(ge=0, le=100)
    strategy: int = Field(ge=0, le=100)
    crisis_management: int = Field(ge=0, le=100)
    resolution_quality: int = Field(ge=0, le=100)
    country_alignment: int = Field(ge=0, le=100)
    evidence: list[str] = Field(default_factory=list, max_length=8)


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: str = Field(min_length=1, max_length=2000)
    proposed_scores: list[ScoreProposal] = Field(default_factory=list, max_length=40)
    limitations: list[str] = Field(default_factory=list, max_length=6)


OUTPUT_MODELS: dict[DelegateKind, Type[BaseModel]] = {
    DelegateKind.STRATEGIST: StrategistOutput,
    DelegateKind.SPEECH: SpeechOutput,
    DelegateKind.NEGOTIATOR: NegotiatorOutput,
    DelegateKind.CRISIS: CrisisOutput,
    DelegateKind.RESOLUTION: ResolutionOutput,
    DelegateKind.CHAIR: ChairOutput,
    DelegateKind.JUDGE: JudgeOutput,
}


PHASE_RULES = {
    DelegateKind.STRATEGIST: set(ConferencePhase),
    DelegateKind.SPEECH: {
        ConferencePhase.OPENING_SPEECHES,
        ConferencePhase.MODERATED_CAUCUS,
        ConferencePhase.CRISIS,
        ConferencePhase.RESULTS,
    },
    DelegateKind.NEGOTIATOR: {
        ConferencePhase.UNMODERATED_CAUCUS,
        ConferencePhase.CRISIS,
    },
    DelegateKind.CRISIS: {ConferencePhase.CRISIS},
    DelegateKind.RESOLUTION: {ConferencePhase.DRAFTING},
    DelegateKind.CHAIR: set(ConferencePhase),
    DelegateKind.JUDGE: {ConferencePhase.RESULTS},
}


SYSTEM_PROMPTS = {
    DelegateKind.STRATEGIST: (
        "You are a Model UN country strategist. Use only supplied conference "
        "facts and country profile. Mark unknowns as unknown. Return JSON "
        "matching schema."
    ),
    DelegateKind.SPEECH: (
        "You are a Model UN delegate speechwriter. Stay aligned with the "
        "country profile, committee agenda and recorded debate. Never invent "
        "events, agreements, votes or quotes. Respect word limit. Return JSON "
        "matching schema."
    ),
    DelegateKind.NEGOTIATOR: (
        "You are a Model UN negotiator. Evaluate offers against national "
        "interests, red lines and recorded negotiation history. Advise only; "
        "do not accept offers or commit any party. Return JSON matching schema."
    ),
    DelegateKind.CRISIS: (
        "You are a Model UN crisis adviser. Use only the active crisis details "
        "in supplied state. Do not invent crisis facts or execute actions. "
        "Return JSON matching schema."
    ),
    DelegateKind.RESOLUTION: (
        "You are a Model UN resolution adviser. Draft lawful, implementable "
        "clauses and assess support only from supplied positions/history. "
        "Do not invent votes or official endorsements. Return JSON matching schema."
    ),
    DelegateKind.CHAIR: (
        "You are an impartial Model UN chair. Summarize recorded proceedings "
        "and identify procedural concerns. A transition is only a suggestion; "
        "the backend state machine alone authorizes transitions. Return JSON "
        "matching schema."
    ),
    DelegateKind.JUDGE: (
        "You are a Model UN evaluator. Score only from recorded conference "
        "evidence; avoid unsupported assumptions. Scores are proposals only "
        "and must be independently validated/calculated by backend. Return "
        "JSON matching schema."
    ),
}


def _dump(value: Any) -> Any:
    """Convert Pydantic models, enums and collections to JSON-safe values."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _dump(item) for key, item in value.items()}
    return value


def build_context(conference_id: str, country_code: str) -> dict[str, Any]:
    """Build a read-only prompt snapshot from stored conference state."""
    with conference_service._lock:
        record = conference_service._get(conference_id)
        conf = record.conference

        if record.world is None:
            raise HTTPException(
                status_code=409,
                detail="Conference has not started",
            )

        participant = next(
            (
                person
                for person in record.participants
                if person.country_code == country_code
                and person.role == ParticipantRole.PARTICIPANT
            ),
            None,
        )

        if participant is None:
            raise HTTPException(
                status_code=404,
                detail=f"Country {country_code} has no participant seat in this conference",
            )

        country = next(
            (
                item
                for item in record.world.countries
                if item.country_code == country_code
            ),
            None,
        )

        if country is None:
            raise HTTPException(
                status_code=404,
                detail=f"Country {country_code} is absent from conference world state",
            )

        profile = (
            COUNTRY_PROFILES.get(country.id)
            or COUNTRY_PROFILES.get(country.id.replace("_", "-"))
        )

        speeches = list(record.speeches)[-MAX_HISTORY_ITEMS:]
        negotiations = [
            negotiation
            for negotiation in record.negotiations
            if country_code in (
                negotiation.proposer,
                negotiation.receiver,
            )
        ][-MAX_HISTORY_ITEMS:]
        resolutions = list(record.resolutions)[-MAX_HISTORY_ITEMS:]
        votes = list(record.votes)[-MAX_HISTORY_ITEMS:]
        events = list(record.world.events)[-MAX_HISTORY_ITEMS:]

        context = {
            "conference": {
                "id": conf.id,
                "name": conf.name,
                "committee": conf.committee.value,
                "agenda": conf.topic,
                "status": conf.status.value,
                "phase": conf.current_phase.value,
            },
            "country": {
                "code": country_code,
                "name": country.name,
                "participant": participant.name,
                "world_state": _dump(country),
                "official_profile": (
                    {
                        "personality": profile.personality,
                        "interests": list(profile.goals),
                        "red_lines": (
                            "Not explicitly configured in the existing profile; "
                            "do not present inferred limits as official policy."
                        ),
                        "background": profile.background,
                    }
                    if profile
                    else None
                ),
                "allies": [
                    {
                        "country_id": other.id,
                        "country_name": other.name,
                        "relationship_score": country.relationships.get(other.id),
                    }
                    for other in record.world.countries
                    if other.id != country.id
                    and (
                        other.id in country.trade_partners
                        or country.relationships.get(other.id, 0) >= 50
                        or set(other.alliances).intersection(country.alliances)
                    )
                ],
            },
            "delegates": [
                {
                    "country_code": person.country_code,
                    "name": person.name,
                    "role": person.role.value,
                }
                for person in record.participants
                if person.country_code
            ],
            "speeches": [_dump(item) for item in speeches],
            "negotiations": [_dump(item) for item in negotiations],
            "resolutions": [_dump(item) for item in resolutions],
            "votes": [_dump(item) for item in votes],
            "events": [_dump(item) for item in events],
            "active_crisis": None,
        }

    # Trim history if needed without changing the stored conference.
    encoded = json.dumps(context, ensure_ascii=False, default=str)

    if len(encoded) > MAX_CONTEXT_CHARS:
        for key in (
            "events",
            "speeches",
            "negotiations",
            "resolutions",
            "votes",
        ):
            context[key] = context[key][-4:]
            encoded = json.dumps(context, ensure_ascii=False, default=str)
            if len(encoded) <= MAX_CONTEXT_CHARS:
                break

    return context


def generate_delegate(
    kind: DelegateKind | str,
    request: DelegateRequest,
    *,
    generator=None,
) -> dict[str, Any]:
    """Generate and validate advice; failures never become NO_ACTION."""
    kind = DelegateKind(kind)
    context = build_context(
        request.conference_id,
        request.country_code,
    )

    phase = ConferencePhase(context["conference"]["phase"])

    if phase not in PHASE_RULES[kind]:
        raise HTTPException(
            status_code=409,
            detail=f"{kind.value} advice is not available during {phase.value}",
        )

    # The current state model has no persisted crisis object. Do not invent one.
    if kind is DelegateKind.CRISIS:
        raise HTTPException(
            status_code=409,
            detail=(
                "No active crisis is stored in conference state; "
                "crisis advice unavailable"
            ),
        )

    if (
        kind is DelegateKind.JUDGE
        and context["conference"]["status"] != ConferenceStatus.COMPLETED.value
        and phase != ConferencePhase.RESULTS
    ):
        raise HTTPException(
            status_code=409,
            detail="Judging is only available after debate, in RESULTS or completed state",
        )

    if kind is DelegateKind.SPEECH:
        if not request.speech_kind:
            raise HTTPException(
                status_code=422,
                detail="speech_kind is required for speech generation",
            )

        if (
            request.speech_kind == SpeechKind.OPENING
            and phase != ConferencePhase.OPENING_SPEECHES
        ):
            raise HTTPException(
                status_code=409,
                detail="Opening speeches are only available in OPENING_SPEECHES",
            )

        if (
            request.speech_kind == SpeechKind.MODERATED_CAUCUS
            and phase != ConferencePhase.MODERATED_CAUCUS
        ):
            raise HTTPException(
                status_code=409,
                detail="Moderated-caucus speeches require MODERATED_CAUCUS",
            )

        if (
            request.speech_kind == SpeechKind.CLOSING
            and phase != ConferencePhase.RESULTS
        ):
            raise HTTPException(
                status_code=409,
                detail="Closing statements are only available in RESULTS",
            )

        if request.speech_kind == SpeechKind.REBUTTAL and phase not in {
            ConferencePhase.OPENING_SPEECHES,
            ConferencePhase.MODERATED_CAUCUS,
            ConferencePhase.CRISIS,
        }:
            raise HTTPException(
                status_code=409,
                detail="Rebuttals are unavailable during this phase",
            )

        context["speech_kind"] = request.speech_kind.value
        context["speech_limit_words"] = request.speech_limit_words

    if kind is DelegateKind.NEGOTIATOR:
        context["current_offer"] = request.offer
        if not request.offer:
            context["task"] = (
                request.task
                or "Suggest a negotiation proposal consistent with recorded history."
            )

    if kind is DelegateKind.RESOLUTION and request.resolution_id:
        try:
            target_resolution = resolution_service.get(request.resolution_id)
            context["target_resolution"] = _dump(target_resolution)
        except Exception:
            raise HTTPException(
                status_code=404,
                detail="Resolution not found",
            ) from None

        if (
            context["target_resolution"].get("conference_id")
            != request.conference_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Resolution does not belong to this conference",
            )

    context["task"] = (
        request.task
        or context.get("task")
        or f"Provide {kind.value.lower()} advice for the assigned country."
    )

    context_json = json.dumps(
        context,
        ensure_ascii=False,
        default=str,
    )
    call = generator or generate_json_text

    try:
        raw = call(
            SYSTEM_PROMPTS[kind],
            f"Return only JSON for the required schema. Context:\n{context_json}",
            country=context["country"]["name"],
        )

        parsed = json.loads(raw)
        output = OUTPUT_MODELS[kind].model_validate(parsed)

        if (
            kind is DelegateKind.SPEECH
            and output.word_count > request.speech_limit_words
        ):
            raise ValueError("Generated speech exceeds the requested word limit")

        response = {
            "status": "SUCCESS",
            "kind": kind.value,
            "country_code": request.country_code,
            "phase": phase.value,
            "advice": output.model_dump(mode="json"),
            "source": "ai",
        }

        if kind is DelegateKind.JUDGE:
            seated = {
                delegate["country_code"]
                for delegate in context["delegates"]
            }
            score_codes = [
                score.country_code
                for score in output.proposed_scores
            ]

            if any(code not in seated for code in score_codes):
                raise ValueError(
                    "Judge proposed scores for a country not seated in this conference"
                )

            if len(score_codes) != len(set(score_codes)):
                raise ValueError(
                    "Judge returned duplicate score entries for a country"
                )

            dimensions = (
                "diplomacy",
                "speaking",
                "negotiation",
                "strategy",
                "crisis_management",
                "resolution_quality",
                "country_alignment",
            )

            # Backend aggregation is deterministic; AI scores remain proposals.
            response["final_scores"] = [
                {
                    "country_code": score.country_code,
                    "overall_score": round(
                        sum(
                            getattr(score, field)
                            for field in dimensions
                        ) / len(dimensions),
                        2,
                    ),
                }
                for score in output.proposed_scores
            ]

        return response

    except HTTPException:
        raise
    except Exception as exc:
        # Never log provider exception text, which may contain sensitive data.
        logger.warning(
            "delegate generation failed kind=%s error_type=%s",
            kind.value,
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=502,
            detail={
                "status": "AI_REQUEST_FAILED",
                "kind": kind.value,
                "error": (
                    "AI generation failed or returned invalid structured output; "
                    "no advice was accepted."
                ),
            },
        ) from None


@router.post("/{kind}")
def generate_delegate_endpoint(
    kind: DelegateKind,
    request: DelegateRequest,
) -> dict[str, Any]:
    """Advice-only endpoint; no conference/world mutations are performed."""
    return generate_delegate(kind, request)
