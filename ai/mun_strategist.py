"""Phase 8: AI Country Strategist.

Picks the ONE conference action a country should take next, from what the current phase actually permits
(`mun.phases` via the conference snapshot), using the country's goals and red lines, its allies and opponents, the world
state, the phase, the time left and the conference history (including a dossier on every other delegate).

It only proposes. The reply is checked against the real conference before it is returned: the action must be
permitted in the current phase, a target must be another seated country, a vote must name a resolution that is open
for this country, and an amendment must name an amendable resolution. There is no "do nothing" option, and a failed
AI call is never converted into one: if no action is permitted (lobby, roll call, results) the request is refused
before Gemini is called.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from backend.mun import AMENDABLE_STATUSES, ActionType, VoteChoice
from ai.country_agent import ResponseError
from ai.mun_context import MunContext, full_briefing
from ai.mun_core import COMMON_RULES, AIPreconditionError, AIResult, MunAgent, parse_json_object, require_text, validate_model
from ai.mun_opponent import build_opponent_dossier, dossier_text

NEEDS_TARGET = frozenset({ActionType.NEGOTIATION, ActionType.ALLIANCE})


class StrategyProposal(BaseModel):
    """A validated PROPOSAL for the country's next conference action. Exactly these seven keys."""

    model_config = ConfigDict(extra="forbid")

    country: str
    action: ActionType
    target: Optional[str]  # exact country name, or null
    vote: Optional[VoteChoice]  # only for VOTE
    resolution_id: Optional[str]  # only for VOTE / AMENDMENT / (optionally) RESOLUTION_EDIT
    rationale: str
    expected_outcome: str

    @field_validator("country", "rationale", "expected_outcome")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        require_text(v, "text field")
        if len(v) > 1000:
            raise ValueError("text must be at most 1000 characters")
        return v


SYSTEM_PROMPT = """\
You are the chief strategist for {name}'s delegation in a Model UN committee simulation.
Choose exactly ONE conference action for {name} to take next, in service of its goals and without crossing its red lines.
Weigh: allies and opponents, relationship scores, the world state, the current phase, the time left, and what other
delegates have said, offered, drafted and voted.

Allowed actions right now: {allowed}.
- SPEECH: address the committee. MOTION: raise a procedural motion.
- NEGOTIATION: open talks with ONE other country (target required).
- ALLIANCE: seek an alliance with ONE other country (target required).
- RESOLUTION_EDIT: draft or edit a resolution. AMENDMENT: amend a submitted resolution (resolution_id required).
- CRISIS_RESPONSE: respond to the crisis. VOTE: vote on an open resolution (resolution_id and vote required).

{rules}

Return exactly this JSON object (use null where a key does not apply):
{{"country":"{name}","action":"{allowed_pipe}","target":"exact other country name or null",
"vote":"YES | NO | ABSTAIN or null","resolution_id":"an id from the briefing or null",
"rationale":"brief explanation","expected_outcome":"brief expected result"}}
Rules: action must be one of the allowed actions; target names must match a seated delegate exactly; vote is for VOTE
only; resolution_id must come from the briefing.
"""


class StrategistAgent(MunAgent):
    role = "country-strategist"

    def propose(self, ctx: MunContext, focus: Optional[str] = None) -> AIResult:
        me = ctx.require_me()
        ctx.require_started()
        ctx.require_active("choose an action")
        allowed = sorted(ctx.allowed_actions, key=lambda a: a.value)
        if not allowed:
            raise AIPreconditionError(f"The {ctx.phase.value} phase permits no conference action, so there is nothing to propose")
        if ActionType.VOTE in ctx.allowed_actions and not ctx.open_resolutions_for_me():
            allowed = [a for a in allowed if a is not ActionType.VOTE]
            if not allowed:
                raise AIPreconditionError(f"{me.country_name} has no open resolution left to vote on")

        names = [a.value for a in allowed]
        system = SYSTEM_PROMPT.format(
            name=me.country_name, allowed=", ".join(names), allowed_pipe=" | ".join(names), rules=COMMON_RULES
        )
        dossiers = "\n\n".join(dossier_text(build_opponent_dossier(ctx, d.code)) for d in ctx.delegates if d.code != me.code)
        user = (
            f"{full_briefing(ctx)}\n\n{dossiers}\n\n"
            + (f"=== DELEGATE'S FOCUS ===\n{focus.strip()}\n\n" if focus and focus.strip() else "")
            + f"Choose the single best next action for {me.country_name}. JSON object only."
        )
        meta = {
            "phase": ctx.phase.value,
            "allowed_actions": names,
            "remaining_seconds": ctx.remaining_seconds,
            "holds_the_floor": bool(ctx.speakers.current_speaker and ctx.speakers.current_speaker.participant_id == me.participant_id),
        }

        def parse(raw) -> StrategyProposal:
            out = validate_model(StrategyProposal, parse_json_object(raw), "strategy")
            if out.country != me.country_name:
                raise ResponseError(f"Response is for '{out.country}', expected '{me.country_name}'")
            if out.action not in allowed:
                raise ResponseError(f"Action {out.action.value} is not permitted now; allowed: {', '.join(names)}")

            if out.target is not None:
                target = ctx.delegate_by_name(out.target)
                if target is None:
                    raise ResponseError(f"Unknown target country '{out.target}': it holds no seat in this conference")
                if target.code == me.code:
                    raise ResponseError("The target cannot be the agent's own country")
            elif out.action in NEEDS_TARGET:
                raise ResponseError(f"{out.action.value} requires a target country")

            if out.action is ActionType.VOTE:
                if out.vote is None or out.resolution_id is None:
                    raise ResponseError("A VOTE needs both a vote and a resolution_id")
                if out.resolution_id not in {r.id for r in ctx.open_resolutions_for_me()}:
                    raise ResponseError(f"Resolution '{out.resolution_id}' is not open for {me.country_name} to vote on")
            else:
                if out.vote is not None:
                    raise ResponseError("vote is only allowed with a VOTE action")
                if out.action is ActionType.AMENDMENT:
                    res = ctx.resolution(out.resolution_id) if out.resolution_id else None
                    if res is None or res.status not in AMENDABLE_STATUSES:
                        raise ResponseError("An AMENDMENT needs the resolution_id of a SUBMITTED or UNDER_REVIEW resolution")
                elif out.resolution_id is not None:
                    res = ctx.resolution(out.resolution_id)
                    if res is None:
                        raise ResponseError(f"Unknown resolution '{out.resolution_id}'")
                    if out.action is not ActionType.RESOLUTION_EDIT:
                        raise ResponseError("resolution_id is only allowed with VOTE, AMENDMENT or RESOLUTION_EDIT")
            return out

        return self._run(system, user, parse, label=f"{me.country_name}/strategist", meta=meta)