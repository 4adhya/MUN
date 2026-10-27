"""Phase 8: AI Negotiation Agent.

Two jobs, both proposal-only:

* `propose_offer` - drafts a new offer from this country to another seated country.
* `respond`       - answers a PENDING offer addressed to this country with ACCEPT, REJECT or COUNTER.

Decisions weigh the country's interests and RED LINES, the relationship score and the opponent's record. The reply is
validated with the same rules the backend applies to a real answer (`mun.negotiations.apply_response`): a COUNTER needs
a counter-offer and ACCEPT/REJECT must not carry one. An ACCEPT that the model itself flags as crossing a red line is
rejected as inconsistent. Whether the offer is still open, whether the phase permits negotiating and what the answer
does to relations stay with the backend: nothing here is sent or applied.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.mun import MAX_PROPOSAL_CHARS, ActionType, NegotiationAction, NegotiationStatus
from ai.country_agent import ResponseError
from ai.mun_context import MunContext, full_briefing
from ai.mun_core import COMMON_RULES, AIPreconditionError, AIResult, MunAgent, parse_json_object, require_text, validate_model
from ai.mun_opponent import build_opponent_dossier, dossier_text


class OfferDraft(BaseModel):
    """A validated PROPOSAL for a new offer. Exactly these four keys."""

    model_config = ConfigDict(extra="forbid")

    country: str
    receiver: str
    proposal: str = Field(min_length=1, max_length=MAX_PROPOSAL_CHARS)
    reason: str = Field(max_length=800)

    @field_validator("country", "receiver", "proposal", "reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return require_text(v, "text field")


class NegotiationReply(BaseModel):
    """A validated PROPOSAL for how to answer an offer. Exactly these five keys."""

    model_config = ConfigDict(extra="forbid")

    country: str
    action: NegotiationAction
    counter_offer: Optional[str] = Field(max_length=MAX_PROPOSAL_CHARS)  # required key; null unless COUNTER
    crosses_red_line: bool
    reason: str = Field(max_length=800)

    @field_validator("country", "reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return require_text(v, "text field")

    @model_validator(mode="after")
    def _counter_matches_action(self) -> "NegotiationReply":
        has_text = self.counter_offer is not None and bool(self.counter_offer.strip())
        if self.counter_offer is not None and not has_text:
            raise ValueError("counter_offer must be null or non-empty")
        if self.action is NegotiationAction.COUNTER and not has_text:
            raise ValueError("a COUNTER needs a counter_offer")
        if self.action is not NegotiationAction.COUNTER and self.counter_offer is not None:
            raise ValueError(f"a {self.action.value} cannot carry a counter_offer (it must be null)")
        if self.action is NegotiationAction.ACCEPT and self.crosses_red_line:
            raise ValueError("an ACCEPT cannot cross a red line")
        return self


OFFER_PROMPT = """\
You are the chief negotiator for {name}'s delegation in a Model UN committee. Draft ONE offer from {name} to {receiver}.
It must advance {name}'s interests, stay inside its red lines, be specific and realistic given the relationship and
the record, and leave room for the other side to say yes. Keep it under 120 words.

{rules}

Return exactly this JSON object:
{{"country":"{name}","receiver":"{receiver}","proposal":"the offer text","reason":"why this offer suits {name}"}}
"""

REPLY_PROMPT = """\
You are the chief negotiator for {name}'s delegation in a Model UN committee. {proposer} has made {name} an offer.
Decide how {name} answers:
- ACCEPT: the offer serves {name}'s interests and crosses none of its red lines. counter_offer must be null.
- REJECT: the offer harms {name}'s interests or crosses a red line and cannot be repaired. counter_offer must be null.
- COUNTER: there is a deal to be had on different terms. counter_offer holds the terms (under 120 words).
Set crosses_red_line to true if the ORIGINAL offer would cross one of {name}'s red lines (then ACCEPT is invalid).
Weigh interests, red lines, the relationship score, the opponent's record, and the time left in the phase.

{rules}

Return exactly this JSON object:
{{"country":"{name}","action":"ACCEPT | REJECT | COUNTER","counter_offer":"terms or null","crosses_red_line":true,
"reason":"brief explanation"}}
"""


class NegotiationAgent(MunAgent):
    role = "negotiation-agent"

    @staticmethod
    def _require_negotiating(ctx: MunContext) -> None:
        ctx.require_started()
        ctx.require_active("negotiate")
        if ActionType.NEGOTIATION not in ctx.allowed_actions:
            raise AIPreconditionError(f"{ctx.phase.value} does not permit negotiation")

    def propose_offer(self, ctx: MunContext, receiver_code: str, goal: Optional[str] = None) -> AIResult:
        me = ctx.require_me()
        self._require_negotiating(ctx)
        receiver = ctx.delegate_by_code(receiver_code)
        if receiver is None:
            raise AIPreconditionError(f"Country '{receiver_code}' holds no seat in conference '{ctx.conference_id}'")
        if receiver.code == me.code:
            raise AIPreconditionError("A country cannot negotiate with itself")

        system = OFFER_PROMPT.format(name=me.country_name, receiver=receiver.country_name, rules=COMMON_RULES)
        user = (
            f"{full_briefing(ctx)}\n\n{dossier_text(build_opponent_dossier(ctx, receiver.code))}\n\n"
            + (f"=== DELEGATE'S GOAL ===\n{goal.strip()}\n\n" if goal and goal.strip() else "")
            + f"Draft the offer from {me.country_name} to {receiver.country_name}. JSON object only."
        )

        def parse(raw) -> OfferDraft:
            out = validate_model(OfferDraft, parse_json_object(raw), "offer")
            if out.country != me.country_name:
                raise ResponseError(f"Response is for '{out.country}', expected '{me.country_name}'")
            if out.receiver != receiver.country_name:
                raise ResponseError(f"Response offers to '{out.receiver}', expected '{receiver.country_name}'")
            return out

        meta = {"phase": ctx.phase.value, "receiver_code": receiver.code, "remaining_seconds": ctx.remaining_seconds}
        return self._run(system, user, parse, label=f"{me.country_name}/negotiation", meta=meta)

    def respond(self, ctx: MunContext, negotiation_id: str) -> AIResult:
        me = ctx.require_me()
        self._require_negotiating(ctx)
        offer = ctx.negotiation(negotiation_id)
        if offer is None:
            raise AIPreconditionError(f"Negotiation '{negotiation_id}' not found in conference '{ctx.conference_id}'")
        if offer.receiver != me.code:
            raise AIPreconditionError(f"Negotiation '{negotiation_id}' is not addressed to {me.country_name}")
        if offer.status is not NegotiationStatus.PENDING:
            raise AIPreconditionError(f"Negotiation '{negotiation_id}' is already {offer.status.value} and cannot be answered")
        proposer = ctx.delegate_by_code(offer.proposer)

        system = REPLY_PROMPT.format(name=me.country_name, proposer=ctx.country_name(offer.proposer), rules=COMMON_RULES)
        dossier = dossier_text(build_opponent_dossier(ctx, offer.proposer)) if proposer else ""
        user = (
            f"{full_briefing(ctx)}\n\n{dossier}\n\n"
            f"=== OFFER TO ANSWER [{offer.id}] from {ctx.country_name(offer.proposer)} ===\n{offer.proposal}\n\n"
            f"Decide {me.country_name}'s answer. JSON object only."
        )

        def parse(raw) -> NegotiationReply:
            out = validate_model(NegotiationReply, parse_json_object(raw), "negotiation reply")
            if out.country != me.country_name:
                raise ResponseError(f"Response is for '{out.country}', expected '{me.country_name}'")
            return out

        meta = {
            "phase": ctx.phase.value,
            "negotiation_id": offer.id,
            "proposer_code": offer.proposer,
            "remaining_seconds": ctx.remaining_seconds,
            "offer_expires_at": offer.expires_at.isoformat(),
        }
        return self._run(system, user, parse, label=f"{me.country_name}/negotiation", meta=meta)