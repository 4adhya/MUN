"""Phase 8: AI Chair.

Gives procedural guidance (what the rules of the current phase allow, how a motion or speaker queue works, what the
usual next step is) WITHOUT deciding anything. It cannot move the conference, rule on a motion, open or close a vote,
or declare a result: the backend advances phases and computes every outcome.

Two safeguards keep it in that lane:

* the output schema has no field for a ruling, a result or a phase change, and the procedural facts a client sees
  (`meta`: phase, permitted actions, next step, time left, speaker queue, open negotiations and votes) are computed
  by the backend side, not by the AI;
* any reply that tries to declare an outcome ("the resolution has been passed", "I hereby rule ...") is rejected as an
  invalid response instead of being shown as the chair's word.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.mun import NegotiationStatus, ResolutionStatus
from ai.country_agent import ResponseError
from ai.mun_context import MunContext, conference_brief, history_brief
from ai.mun_core import COMMON_RULES, AIResult, MunAgent, parse_json_object, require_text, validate_model

MAX_QUESTION_CHARS = 500

# Phrases that would present an AI statement as an official ruling or result.
OUTCOME_CLAIMS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # "the resolution has been passed", "the motion was rejected", "the vote is hereby carried"
        r"\b(resolution|motion|amendment|vote)\b[^.\n]{0,80}\b(has been|have been|is hereby|was)\s+(passed|adopted|carried|approved|failed|rejected|defeated|vetoed)\b",
        # a first-person ruling: "I declare", "I hereby rule", "the chair hereby decides"
        r"\bI\s+(hereby\s+)?(declare|rule|decree|decide)\b",
        r"\bthe chair\s+hereby\s+(declares?|rules?|decrees?|decides?)\b",
        r"\bit is (hereby\s+)?(ruled|declared|decreed)\b",
        # opening / closing / ending business by fiat: "I open the voting", "the chair hereby closes the debate"
        r"\b(I|the chair\s+hereby)\s+(hereby\s+)?(open|opens|close|closes|advance|advances|end|ends|adjourn|adjourns)\b[^.\n]{0,30}\b(voting|the vote|the session|the phase|the debate)\b",
    )
)


def claims_an_outcome(text: str) -> bool:
    return any(p.search(text) for p in OUTCOME_CLAIMS)


class ChairGuidance(BaseModel):
    """A validated piece of procedural GUIDANCE. Exactly these three keys; there is no ruling or outcome field."""

    model_config = ConfigDict(extra="forbid")

    guidance: str = Field(max_length=800)
    procedural_options: list[str] = Field(min_length=1, max_length=5)
    cautions: list[str] = Field(max_length=4)

    @field_validator("guidance")
    @classmethod
    def _g(cls, v: str) -> str:
        return require_text(v, "guidance")

    @field_validator("procedural_options", "cautions")
    @classmethod
    def _items(cls, items: list[str]) -> list[str]:
        for item in items:
            require_text(item, "list item")
            if len(item) > 300:
                raise ValueError("list items must be at most 300 characters")
        return items


SYSTEM_PROMPT = """\
You are the procedural adviser to the Chair of a Model UN committee ({committee}). You give GUIDANCE ONLY.
- Explain what is procedurally possible now, using the phase, the actions the phase permits, the time left, the speaker
  queue and the pending business in the briefing. Offer 1-5 procedural options a chair could consider (e.g. moving to
  the next speaker, hearing a motion, reminding delegates of a deadline).
- You DECIDE NOTHING. Never rule on a motion, open or close a vote, advance the phase, or state or imply a result of
  any vote or resolution. Say what the options are and that the chair and the committee decide, and that the backend
  applies the rules. Do not use the first person to issue a ruling.
- Stay neutral between delegations; never favour a country or a position.

{rules}

Return exactly this JSON object:
{{"guidance":"short procedural explanation","procedural_options":["1-5 short options"],"cautions":["0-4 short cautions"]}}
"""


class ChairAgent(MunAgent):
    role = "chair"

    def guide(self, ctx: MunContext, question: Optional[str] = None) -> AIResult:
        question = question.strip() if isinstance(question, str) else None
        if question is not None and len(question) > MAX_QUESTION_CHARS:
            raise ValueError(f"question is too long (max {MAX_QUESTION_CHARS} characters)")
        speakers = ctx.speakers
        pending = [n for n in ctx.negotiations if n.status is NegotiationStatus.PENDING]
        meta = {
            "status": ctx.status.value,
            "phase": ctx.phase.value,
            "next_step": ctx.snapshot.next_phase,
            "allowed_actions": sorted(a.value for a in ctx.allowed_actions),
            "remaining_seconds": ctx.remaining_seconds,
            "current_speaker": speakers.current_speaker.country_name if speakers.current_speaker else None,
            "speakers_waiting": len(speakers.queue),
            "pending_negotiations": len(pending),
            "resolutions_by_status": {
                s.value: sum(1 for r in ctx.resolutions if r.status is s) for s in ResolutionStatus
                if any(r.status is s for r in ctx.resolutions)
            },
            "decides_nothing": True,
        }
        system = SYSTEM_PROMPT.format(committee=ctx.snapshot.committee, rules=COMMON_RULES)
        user = (
            f"{conference_brief(ctx)}\n\n{history_brief(ctx, full_resolutions=False)}\n\n"
            f"=== QUESTION TO THE CHAIR'S ADVISER ===\n{question or 'Give procedural guidance for the current phase.'}\n\n"
            "Give procedural guidance only. JSON object only."
        )

        def parse(raw) -> ChairGuidance:
            out = validate_model(ChairGuidance, parse_json_object(raw), "chair guidance")
            for text in (out.guidance, *out.procedural_options, *out.cautions):
                if claims_an_outcome(text):
                    raise ResponseError("The guidance declares a ruling or an outcome, which the chair adviser may not do")
            return out

        return self._run(system, user, parse, label="chair", meta=meta)