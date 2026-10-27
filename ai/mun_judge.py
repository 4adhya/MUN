"""Phase 8: AI Judge.

Evaluates a COMPLETED conference in two clearly separated layers:

1. DETERMINISTIC facts (`JudgeFacts`), computed from the conference records and never by the AI: what every delegation
   actually did (speeches, negotiations and how they ended, resolutions sponsored/signed/passed, votes cast), every
   resolution with its OFFICIAL vote result as the backend computed it, and the final world metrics and event counts.
2. QUALITATIVE feedback (`JudgeFeedback`) from Gemini: an overall assessment, highlights, concerns and per-delegate
   strengths and improvements with a qualitative rating.

The AI feedback cannot change a result or a score: official results are copied from the backend into the facts, the
feedback schema has no number or result field, and the feedback must cover exactly the seated delegates (no unknown or
missing country). It is feedback, not scoring: nothing here writes `Participant.score`.
"""
from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.mun import ConferenceStatus, NegotiationStatus, ResolutionStatus, VoteChoice
from ai.country_agent import ResponseError
from ai.mun_context import MunContext, history_brief
from ai.mun_core import COMMON_RULES, AIPreconditionError, AIResult, MunAgent, parse_json_object, require_text, validate_model


class DelegateRecord(BaseModel):
    country_code: str
    country_name: str
    participant_name: str
    speeches: int = 0
    negotiations_proposed: int = 0
    negotiations_received: int = 0
    proposals_accepted: int = Field(default=0, description="Offers this country proposed that were ACCEPTED")
    offers_accepted: int = Field(default=0, description="Offers this country received and ACCEPTED")
    resolutions_sponsored: int = 0
    resolutions_signed: int = 0
    sponsored_passed: int = 0
    votes_yes: int = 0
    votes_no: int = 0
    votes_abstain: int = 0


class ResolutionOutcome(BaseModel):
    id: str
    title: str
    status: str
    sponsors: list[str]
    signatories: list[str]
    clauses: int
    amendments: int
    official_result: Optional[dict] = Field(default=None, description="The backend's VoteResult, copied unchanged")


class JudgeFacts(BaseModel):
    """Everything here comes from backend records. The AI never writes any of it."""

    conference_id: str
    committee: str
    agenda: str
    status: str
    final_phase: str
    delegates: list[DelegateRecord]
    resolutions: list[ResolutionOutcome]
    resolutions_passed: int
    resolutions_failed: int
    total_speeches: int
    negotiations_by_status: dict[str, int]
    world_event_counts: dict[str, int]
    final_mun_metrics: dict[str, float]


def build_judge_facts(ctx: MunContext) -> JudgeFacts:
    if ctx.status is not ConferenceStatus.COMPLETED:
        raise AIPreconditionError(
            f"Conference '{ctx.conference_id}' is {ctx.status.value}; the judge evaluates a COMPLETED conference"
        )
    world = ctx.require_started()
    records = []
    for d in ctx.delegates:
        sponsored = [r for r in ctx.resolutions if d.code in r.sponsors]
        votes = [v.choice for r in ctx.resolutions for v in r.votes if v.country_code == d.code]
        records.append(
            DelegateRecord(
                country_code=d.code,
                country_name=d.country_name,
                participant_name=d.participant_name,
                speeches=sum(1 for s in ctx.speeches if s.country_code == d.code),
                negotiations_proposed=sum(1 for n in ctx.negotiations if n.proposer == d.code),
                negotiations_received=sum(1 for n in ctx.negotiations if n.receiver == d.code),
                proposals_accepted=sum(1 for n in ctx.negotiations if n.proposer == d.code and n.status is NegotiationStatus.ACCEPTED),
                offers_accepted=sum(1 for n in ctx.negotiations if n.receiver == d.code and n.status is NegotiationStatus.ACCEPTED),
                resolutions_sponsored=len(sponsored),
                resolutions_signed=sum(1 for r in ctx.resolutions if d.code in r.signatories),
                sponsored_passed=sum(1 for r in sponsored if r.status is ResolutionStatus.PASSED),
                votes_yes=votes.count(VoteChoice.YES),
                votes_no=votes.count(VoteChoice.NO),
                votes_abstain=votes.count(VoteChoice.ABSTAIN),
            )
        )
    return JudgeFacts(
        conference_id=ctx.conference_id,
        committee=ctx.snapshot.committee,
        agenda=ctx.snapshot.topic,
        status=ctx.status.value,
        final_phase=ctx.phase.value,
        delegates=records,
        resolutions=[
            ResolutionOutcome(
                id=r.id, title=r.title, status=r.status.value, sponsors=list(r.sponsors), signatories=list(r.signatories),
                clauses=len(r.clauses), amendments=len(r.amendments),
                official_result=r.result.model_dump(mode="json") if r.result else None,
            )
            for r in ctx.resolutions
        ],
        resolutions_passed=sum(1 for r in ctx.resolutions if r.status is ResolutionStatus.PASSED),
        resolutions_failed=sum(1 for r in ctx.resolutions if r.status is ResolutionStatus.FAILED),
        total_speeches=len(ctx.speeches),
        negotiations_by_status=dict(Counter(n.status.value for n in ctx.negotiations)),
        world_event_counts=dict(Counter(e.type for e in world.events)),
        final_mun_metrics={k: float(v) for k, v in world.mun_metrics.model_dump().items()},
    )


def facts_text(f: JudgeFacts) -> str:
    lines = [
        "=== DETERMINISTIC RESULTS (computed by the backend; do not contradict) ===",
        f"{f.committee} - {f.agenda}. Resolutions passed {f.resolutions_passed}, failed {f.resolutions_failed}. "
        f"Speeches {f.total_speeches}. Negotiations: {f.negotiations_by_status or 'none'}. World events: {f.world_event_counts or 'none'}.",
        "Final world metrics: " + ", ".join(f"{k} {v:g}" for k, v in f.final_mun_metrics.items()),
        "Delegations:",
    ]
    for d in f.delegates:
        lines.append(
            f"- {d.country_name} ({d.participant_name}): {d.speeches} speeches; negotiations proposed {d.negotiations_proposed} "
            f"(accepted {d.proposals_accepted}), received {d.negotiations_received} (accepted {d.offers_accepted}); "
            f"sponsored {d.resolutions_sponsored} (passed {d.sponsored_passed}), signed {d.resolutions_signed}; "
            f"votes YES {d.votes_yes} / NO {d.votes_no} / ABSTAIN {d.votes_abstain}"
        )
    for r in f.resolutions:
        res = r.official_result
        lines.append(
            f"Resolution \"{r.title}\" [{r.id}] {r.status}"
            + (f": {res['reason']}" if res else "") + f" (sponsors {', '.join(r.sponsors)})"
        )
    return "\n".join(lines)


class Rating(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    STRONG = "STRONG"
    SOLID = "SOLID"
    DEVELOPING = "DEVELOPING"


class DelegateFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str
    rating: Rating
    strengths: list[str] = Field(min_length=1, max_length=3)
    improvements: list[str] = Field(min_length=1, max_length=3)

    @field_validator("country")
    @classmethod
    def _c(cls, v: str) -> str:
        return require_text(v, "country")

    @field_validator("strengths", "improvements")
    @classmethod
    def _items(cls, items: list[str]) -> list[str]:
        for item in items:
            require_text(item, "list item")
            if len(item) > 300:
                raise ValueError("list items must be at most 300 characters")
        return items


class JudgeFeedback(BaseModel):
    """Qualitative feedback from the AI. No numbers, no results, no scores."""

    model_config = ConfigDict(extra="forbid")

    overall_assessment: str = Field(max_length=1200)
    highlights: list[str] = Field(min_length=1, max_length=5)
    concerns: list[str] = Field(max_length=5)
    delegate_feedback: list[DelegateFeedback] = Field(min_length=1)

    @field_validator("overall_assessment")
    @classmethod
    def _o(cls, v: str) -> str:
        return require_text(v, "overall_assessment")

    @field_validator("highlights", "concerns")
    @classmethod
    def _items(cls, items: list[str]) -> list[str]:
        for item in items:
            require_text(item, "list item")
            if len(item) > 300:
                raise ValueError("list items must be at most 300 characters")
        return items


class JudgeEvaluation(BaseModel):
    """What the endpoint returns: the deterministic facts and, separately, the AI's qualitative feedback."""

    deterministic: JudgeFacts
    qualitative: JudgeFeedback
    scores_changed: bool = False


SYSTEM_PROMPT = """\
You are the judge of a completed Model UN committee ({committee}). Give qualitative feedback on how the delegations
performed against the agenda, using ONLY the deterministic results and the conference record in the briefing.
- The deterministic results are authoritative. Never contradict them, never invent results, and never give numeric
  scores or declare winners: you give feedback, not scores.
- Judge diplomacy: quality and consistency of speeches, constructive negotiation, drafting, coalition-building, and
  voting that matches stated positions. Be fair, specific, and constructive.
- Provide feedback for EVERY delegation listed, exactly once: {countries}.

{rules}

Return exactly this JSON object:
{{"overall_assessment":"short paragraph","highlights":["1-5 short points"],"concerns":["0-5 short points"],
"delegate_feedback":[{{"country":"exact country name","rating":"OUTSTANDING | STRONG | SOLID | DEVELOPING",
"strengths":["1-3 short points"],"improvements":["1-3 short points"]}}]}}
"""


class JudgeAgent(MunAgent):
    role = "judge"

    def evaluate(self, ctx: MunContext) -> AIResult:
        facts = build_judge_facts(ctx)  # refuses anything but a COMPLETED conference, before Gemini is called
        if not ctx.delegates:
            raise AIPreconditionError("The conference has no seated delegations to evaluate")
        names = [d.country_name for d in ctx.delegates]
        system = SYSTEM_PROMPT.format(committee=ctx.snapshot.committee, countries=", ".join(names), rules=COMMON_RULES)
        user = f"{facts_text(facts)}\n\n{history_brief(ctx)}\n\nEvaluate the conference. JSON object only."

        def parse(raw) -> JudgeEvaluation:
            feedback = validate_model(JudgeFeedback, parse_json_object(raw), "judge feedback")
            seen: set[str] = set()
            for entry in feedback.delegate_feedback:
                if ctx.delegate_by_name(entry.country) is None:
                    raise ResponseError(f"Unknown country '{entry.country}': it held no seat in this conference")
                if entry.country in seen:
                    raise ResponseError(f"Feedback for '{entry.country}' is given twice")
                seen.add(entry.country)
            missing = [n for n in names if n not in seen]
            if missing:
                raise ResponseError("Feedback is missing for: " + ", ".join(missing))
            return JudgeEvaluation(deterministic=facts, qualitative=feedback)

        return self._run(system, user, parse, label="judge", meta={"deterministic_results_are_authoritative": True})