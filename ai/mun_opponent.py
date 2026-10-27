"""Phase 8: AI Opponent Intelligence.

Two layers, kept apart on purpose:

1. `build_opponent_dossier` - DETERMINISTIC. Counts and lists what an opponent has actually done in this conference:
   speeches, negotiations (and how it answers offers), resolutions it sponsors or signs, its recorded votes, and the
   world events and relationship score that involve it. No AI is involved, so the numbers are always correct.
2. `OpponentIntelligenceAgent.assess` - qualitative. Gemini reads the dossier and proposes a likely stance,
   observed patterns and leverage points. It can only describe; nothing is executed.

The other roles (strategist, speech, negotiation, resolution assistant) reuse the dossier text as context, so every
role reasons from the same record of what the opponent said and did.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.mun import NegotiationStatus
from ai.country_agent import ResponseError
from ai.mun_context import MunContext, full_briefing, _clip
from ai.mun_core import COMMON_RULES, AIPreconditionError, AIResult, MunAgent, parse_json_object, require_text, validate_model

DOSSIER_SPEECHES = 3
DOSSIER_EVENTS = 5


class OpponentDossier(BaseModel):
    """Facts only. Built from backend records; the AI never writes any of it."""

    country_code: str
    country_name: str
    relationship_with_me: Optional[int] = Field(default=None, description="Relationship score -100..100 toward me, if known")
    shared_alliances: list[str] = Field(default_factory=list)
    sanctions_note: Optional[str] = None
    speech_count: int = 0
    recent_speeches: list[str] = Field(default_factory=list)
    negotiations_proposed: int = 0
    negotiations_received: int = 0
    accepted_as_receiver: int = 0
    rejected_as_receiver: int = 0
    countered_as_receiver: int = 0
    acceptance_rate: Optional[float] = Field(default=None, description="accepted / answered offers; None if none answered")
    negotiations_with_me: list[str] = Field(default_factory=list)
    resolutions_sponsored: list[str] = Field(default_factory=list)
    resolutions_signed: list[str] = Field(default_factory=list)
    votes: list[str] = Field(default_factory=list)
    recent_events: list[str] = Field(default_factory=list)


def build_opponent_dossier(ctx: MunContext, opponent_code: str) -> OpponentDossier:
    opponent = ctx.delegate_by_code(opponent_code)
    if opponent is None:
        raise AIPreconditionError(f"Country '{opponent_code}' holds no seat in conference '{ctx.conference_id}'")
    if ctx.me is not None and opponent.code == ctx.me.code:
        raise AIPreconditionError("A country cannot be its own opponent")
    code = opponent.code

    speeches = [s for s in ctx.speeches if s.country_code == code]
    proposed = [n for n in ctx.negotiations if n.proposer == code]
    received = [n for n in ctx.negotiations if n.receiver == code]
    count = lambda status: sum(1 for n in received if n.status is status)  # noqa: E731
    accepted, rejected, countered = (
        count(NegotiationStatus.ACCEPTED), count(NegotiationStatus.REJECTED), count(NegotiationStatus.COUNTERED)
    )
    answered = accepted + rejected + countered

    dossier = OpponentDossier(
        country_code=code,
        country_name=opponent.country_name,
        speech_count=len(speeches),
        recent_speeches=[_clip(s.text, 240) for s in speeches[-DOSSIER_SPEECHES:]],
        negotiations_proposed=len(proposed),
        negotiations_received=len(received),
        accepted_as_receiver=accepted,
        rejected_as_receiver=rejected,
        countered_as_receiver=countered,
        acceptance_rate=round(accepted / answered, 2) if answered else None,
        resolutions_sponsored=[f'"{r.title}" ({r.status.value})' for r in ctx.resolutions if code in r.sponsors],
        resolutions_signed=[f'"{r.title}" ({r.status.value})' for r in ctx.resolutions if code in r.signatories],
        votes=[
            f'"{r.title}": {v.choice.value}' for r in ctx.resolutions for v in r.votes if v.country_code == code
        ],
    )

    world = ctx.world
    if world is not None:
        by_id = {c.id: c for c in world.countries}
        theirs = by_id.get(opponent.country_id)
        mine = by_id.get(ctx.me.country_id) if ctx.me else None
        if mine is not None and theirs is not None:
            dossier.relationship_with_me = mine.relationships.get(theirs.id)
            dossier.shared_alliances = sorted(set(mine.alliances) & set(theirs.alliances))
            notes = []
            if theirs.id in mine.sanctions:
                notes.append(f"{opponent.country_name} sanctions {mine.name}")
            if mine.id in theirs.sanctions:
                notes.append(f"{mine.name} sanctions {opponent.country_name}")
            dossier.sanctions_note = "; ".join(notes) or None
        dossier.recent_events = [
            f"turn {e.turn}: {e.message}"
            for e in world.events
            if opponent.country_id in (e.actor, e.target)
        ][-DOSSIER_EVENTS:]

    if ctx.me is not None:
        dossier.negotiations_with_me = [
            f"[{n.id}] {ctx.country_name(n.proposer)} -> {ctx.country_name(n.receiver)} {n.status.value}: "
            f"{_clip(n.proposal, 160)}"
            for n in ctx.negotiations
            if {n.proposer, n.receiver} == {code, ctx.me.code}
        ][-4:]
    return dossier


def dossier_text(d: OpponentDossier) -> str:
    rate = f"{d.acceptance_rate:.0%}" if d.acceptance_rate is not None else "no answered offers yet"
    rel = f"{d.relationship_with_me:+d}" if d.relationship_with_me is not None else "unknown"
    lines = [
        f"=== OPPONENT RECORD: {d.country_name} ({d.country_code}) ===",
        f"Relationship with you: {rel} | shared alliances: {', '.join(d.shared_alliances) or 'none'} | "
        f"sanctions: {d.sanctions_note or 'none'}",
        f"Speeches given: {d.speech_count}",
        *[f"  - \"{s}\"" for s in d.recent_speeches],
        f"Negotiations proposed {d.negotiations_proposed}, received {d.negotiations_received} "
        f"(accepted {d.accepted_as_receiver}, rejected {d.rejected_as_receiver}, countered {d.countered_as_receiver}; "
        f"acceptance rate {rate})",
        *[f"  - {n}" for n in d.negotiations_with_me],
        "Resolutions sponsored: " + (", ".join(d.resolutions_sponsored) or "none"),
        "Resolutions signed: " + (", ".join(d.resolutions_signed) or "none"),
        "Recorded votes: " + (", ".join(d.votes) or "none"),
        "Recent world events involving them: " + ("; ".join(d.recent_events) or "none"),
    ]
    return "\n".join(lines)


# --- the AI assessment -------------------------------------------------------------------------------
class Stance(str, Enum):
    SUPPORTIVE = "SUPPORTIVE"
    NEUTRAL = "NEUTRAL"
    OPPOSED = "OPPOSED"
    UNCLEAR = "UNCLEAR"


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OpponentAssessment(BaseModel):
    """A validated PROPOSAL describing an opponent. Exactly these keys."""

    model_config = ConfigDict(extra="forbid")

    country: str
    likely_stance: Stance
    confidence: Confidence
    observed_patterns: list[str] = Field(min_length=1, max_length=4)
    leverage_points: list[str] = Field(max_length=3)
    recommended_approach: str = Field(max_length=600)

    @field_validator("country", "recommended_approach")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return require_text(v, "text field")

    @field_validator("observed_patterns", "leverage_points")
    @classmethod
    def _items(cls, items: list[str]) -> list[str]:
        for item in items:
            require_text(item, "list item")
            if len(item) > 300:
                raise ValueError("list items must be at most 300 characters")
        return items


SYSTEM_PROMPT = """\
You are the opponent-intelligence analyst for {me}'s delegation in a Model UN committee.
Assess how {opponent} is likely to behave toward {me}, using ONLY the recorded speeches, negotiations, resolutions,
votes and world events in the briefing. If the record is thin, say so with LOW confidence and stance UNCLEAR.

{rules}

Return exactly this JSON object:
{{"country":"{opponent}","likely_stance":"SUPPORTIVE | NEUTRAL | OPPOSED | UNCLEAR","confidence":"LOW | MEDIUM | HIGH",
"observed_patterns":["1-4 short evidence-based observations"],"leverage_points":["0-3 short points"],
"recommended_approach":"one or two sentences"}}
"""


class OpponentIntelligenceAgent(MunAgent):
    role = "opponent-intelligence"

    def assess(self, ctx: MunContext, opponent_code: str) -> AIResult:
        me = ctx.require_me()
        ctx.require_started()
        dossier = build_opponent_dossier(ctx, opponent_code)
        system = SYSTEM_PROMPT.format(me=me.country_name, opponent=dossier.country_name, rules=COMMON_RULES)
        user = (
            f"{full_briefing(ctx)}\n\n{dossier_text(dossier)}\n\n"
            f"Assess {dossier.country_name}'s likely behaviour toward {me.country_name}. JSON object only."
        )

        def parse(raw) -> OpponentAssessment:
            out = validate_model(OpponentAssessment, parse_json_object(raw), "opponent assessment")
            if out.country != dossier.country_name:
                raise ResponseError(f"Response is for '{out.country}', expected '{dossier.country_name}'")
            return out

        return self._run(system, user, parse, label=f"{me.country_name}/intel", meta={"dossier": dossier.model_dump(mode="json")})