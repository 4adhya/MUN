"""Phase 8: HTTP endpoints for the conference AI roles (strategist, speech, negotiation, crisis, resolution assistant,
opponent intelligence, chair, judge).

Every endpoint is READ-ONLY and PROPOSAL-ONLY. It reads the conference, asks one AI role for a recommendation and
returns it. It never submits a speech, answers a negotiation, edits a resolution, casts a vote, advances a phase or
touches the world: to act on a recommendation, a client sends the normal backend request, which validates it again.

    success          200  {"status": "SUCCESS", "advisory": true, "executed": false, "output": {...}, "meta": {...}}
    conference state 409  the request does not fit the conference (not started, wrong phase, unknown seat, ...)
    unknown id       404  conference not found (the app-wide handler)
    AI failure       502 / 503  {"status": "AI_REQUEST_FAILED", "output": null, ...}   (503: the AI is not configured)

An AI failure is never turned into a valid MUN action: the failure body has no `output` at all, so it cannot be
mistaken for a country that chose to wait, accept, abstain or pass.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai.country_agent import LLM
from ai.gemini_client import AI_REQUEST_FAILED, REASON_CONFIG, resolve_model
from ai.mun_chair import MAX_QUESTION_CHARS, ChairAgent
from ai.mun_context import build_context
from ai.mun_core import AIPreconditionError, AIResult
from ai.mun_crisis import CrisisAgent, CrisisBrief
from ai.mun_judge import JudgeAgent
from ai.mun_negotiation import NegotiationAgent
from ai.mun_opponent import OpponentIntelligenceAgent
from ai.mun_resolution import ResolutionAssistant
from ai.mun_speech import SpeechAgent, SpeechType
from ai.mun_strategist import StrategistAgent

logger = logging.getLogger("worldevent.ai")

router = APIRouter(prefix="/ai/mun", tags=["AI (conference)"])

# Tests (or a deployment) may set this to replace Gemini for every role; None means the real Gemini client.
LLM_OVERRIDE: Optional[LLM] = None

AI_STATUS_SUCCESS = "SUCCESS"
AI_STATUS_FAILED = "AI_REQUEST_FAILED"
MAX_TEXT = 500


# --- requests (strict: unknown fields are rejected) ----------------------------------------------------------
class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conference_id: str = Field(min_length=1, max_length=64)


class _CountryRequest(_Request):
    country_code: str = Field(pattern=r"^[A-Za-z]{2}$", description="ISO alpha-2 code of the country the AI speaks for")

    @field_validator("country_code", mode="after")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


def _code(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


class StrategyRequest(_CountryRequest):
    focus: Optional[str] = Field(default=None, max_length=MAX_TEXT)


class SpeechRequest(_CountryRequest):
    speech_type: SpeechType
    target_code: Optional[str] = Field(default=None, pattern=r"^[A-Za-z]{2}$", description="Country answered (REBUTTAL / RESPONSE)")
    brief: Optional[str] = Field(default=None, max_length=MAX_TEXT)


class OfferRequest(_CountryRequest):
    receiver_code: str = Field(pattern=r"^[A-Za-z]{2}$")
    goal: Optional[str] = Field(default=None, max_length=MAX_TEXT)


class NegotiationReplyRequest(_CountryRequest):
    negotiation_id: str = Field(min_length=1, max_length=64)


class CrisisRequest(_CountryRequest):
    crisis: CrisisBrief


class ResolutionRequest(_CountryRequest):
    resolution_id: str = Field(min_length=1, max_length=64)


class ResolutionFocusRequest(ResolutionRequest):
    focus: Optional[str] = Field(default=None, max_length=MAX_TEXT)


class OpponentRequest(_CountryRequest):
    opponent_code: str = Field(pattern=r"^[A-Za-z]{2}$")


class ChairRequest(_Request):
    question: Optional[str] = Field(default=None, max_length=MAX_QUESTION_CHARS)


class JudgeRequest(_Request):
    pass


# --- shared response handling -------------------------------------------------------------------------------
def _model_or_none() -> Optional[str]:
    try:
        return resolve_model()
    except Exception:
        return None


def _failure(result: AIResult) -> JSONResponse:
    reason = result.failure_reason or AI_STATUS_FAILED
    failure_type = result.failure_type or AI_REQUEST_FAILED
    logger.warning(
        "conference ai failed role=%s failure_type=%s reason=%s upstream_http_status=%s attempts=%s",
        result.role, failure_type, reason, result.http_status, result.attempts,
    )
    return JSONResponse(
        status_code=503 if reason == REASON_CONFIG else 502,
        content={
            "status": AI_STATUS_FAILED,
            "role": result.role,
            "failure_type": failure_type,
            "reason": reason,
            "error_code": result.error_code,
            "detail": f"AI request failed ({failure_type}/{reason}): {result.error} Nothing was changed and no recommendation was made.",
            "upstream_http_status": result.http_status,
            "attempts": result.attempts,
            "model_attempted": _model_or_none(),
            "advisory": True,
            "executed": False,
            "output": None,
            "meta": result.meta,
        },
    )


def _answer(call: Callable[[], AIResult]) -> Any:
    try:
        result = call()
    except AIPreconditionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if not result.ok:
        return _failure(result)
    return {
        "status": AI_STATUS_SUCCESS,
        "role": result.role,
        "advisory": True,
        "executed": False,
        "model": _model_or_none(),
        "output": result.output.model_dump(mode="json"),
        "meta": result.meta,
    }


# --- endpoints ----------------------------------------------------------------------------------------------
@router.post("/strategy", summary="Country strategist: propose the country's next conference action")
def propose_strategy(req: StrategyRequest) -> Any:
    return _answer(lambda: StrategistAgent(LLM_OVERRIDE).propose(build_context(req.conference_id, req.country_code), req.focus))


@router.post("/speech", summary="Speech agent: draft an opening, caucus, rebuttal, response or closing speech")
def draft_speech(req: SpeechRequest) -> Any:
    return _answer(lambda: SpeechAgent(LLM_OVERRIDE).draft(build_context(req.conference_id, req.country_code), req.speech_type.value, req.target_code, req.brief))


@router.post("/negotiation/offer", summary="Negotiation agent: draft a new offer to another country")
def draft_offer(req: OfferRequest) -> Any:
    return _answer(lambda: NegotiationAgent(LLM_OVERRIDE).propose_offer(build_context(req.conference_id, req.country_code), req.receiver_code, req.goal))


@router.post("/negotiation/respond", summary="Negotiation agent: propose ACCEPT, REJECT or COUNTER for a pending offer")
def respond_to_offer(req: NegotiationReplyRequest) -> Any:
    return _answer(lambda: NegotiationAgent(LLM_OVERRIDE).respond(build_context(req.conference_id, req.country_code), req.negotiation_id))


@router.post("/crisis", summary="Crisis agent: analyse a crisis and recommend responses")
def analyse_crisis(req: CrisisRequest) -> Any:
    return _answer(lambda: CrisisAgent(LLM_OVERRIDE).analyze(build_context(req.conference_id, req.country_code), req.crisis))


@router.post("/resolution/clauses", summary="Resolution assistant: suggest clauses for a DRAFT resolution")
def suggest_clauses(req: ResolutionFocusRequest) -> Any:
    return _answer(lambda: ResolutionAssistant(LLM_OVERRIDE).suggest_clauses(build_context(req.conference_id, req.country_code), req.resolution_id, req.focus))


@router.post("/resolution/review", summary="Resolution assistant: review a resolution")
def review_resolution(req: ResolutionRequest) -> Any:
    return _answer(lambda: ResolutionAssistant(LLM_OVERRIDE).review_resolution(build_context(req.conference_id, req.country_code), req.resolution_id))


@router.post("/resolution/amendments", summary="Resolution assistant: suggest amendments for a submitted resolution")
def suggest_amendments(req: ResolutionFocusRequest) -> Any:
    return _answer(lambda: ResolutionAssistant(LLM_OVERRIDE).suggest_amendments(build_context(req.conference_id, req.country_code), req.resolution_id, req.focus))


@router.post("/resolution/support", summary="Resolution assistant: estimate support (projected tally, not official)")
def estimate_support(req: ResolutionRequest) -> Any:
    return _answer(lambda: ResolutionAssistant(LLM_OVERRIDE).estimate_support(build_context(req.conference_id, req.country_code), req.resolution_id))


@router.post("/opponent", summary="Opponent intelligence: assess another delegation from the conference record")
def assess_opponent(req: OpponentRequest) -> Any:
    return _answer(lambda: OpponentIntelligenceAgent(LLM_OVERRIDE).assess(build_context(req.conference_id, req.country_code), req.opponent_code))


@router.post("/chair", summary="AI chair: procedural guidance only (decides nothing)")
def chair_guidance(req: ChairRequest) -> Any:
    return _answer(lambda: ChairAgent(LLM_OVERRIDE).guide(build_context(req.conference_id), req.question))


@router.post("/judge", summary="AI judge: deterministic results plus qualitative feedback for a COMPLETED conference")
def judge_conference(req: JudgeRequest) -> Any:
    return _answer(lambda: JudgeAgent(LLM_OVERRIDE).evaluate(build_context(req.conference_id)))