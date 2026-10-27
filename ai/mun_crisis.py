"""Phase 8: AI Crisis Agent.

Analyses a crisis the caller describes and recommends responses for one country. The backend has no crisis object yet,
so the crisis arrives as text (`CrisisBrief`) and is treated purely as data. The agent returns a severity, the
countries it affects, the main risks and up to three recommended responses.

Every recommendation names a kind of response that maps onto something the backend can really do, and the backend
still gates it. `meta["permitted_now"]` says, deterministically, which kinds the CURRENT phase permits (the conference
phase gate for SPEECH / NEGOTIATION / RESOLUTION_EDIT / ALLIANCE; sanctions and aid are world actions with no phase
gate, so they show `null`). Recommending a response is never doing it.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.mun import ActionType
from ai.country_agent import ResponseError
from ai.mun_context import MunContext, full_briefing
from ai.mun_core import COMMON_RULES, AIPreconditionError, AIResult, MunAgent, parse_json_object, require_text, validate_model
from ai.mun_opponent import build_opponent_dossier, dossier_text

MAX_CRISIS_TITLE = 200
MAX_CRISIS_TEXT = 2000


class CrisisBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=MAX_CRISIS_TITLE)
    description: str = Field(min_length=1, max_length=MAX_CRISIS_TEXT)


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ResponseKind(str, Enum):
    STATEMENT = "STATEMENT"  # a speech
    NEGOTIATE = "NEGOTIATE"  # open talks with a country
    RESOLUTION = "RESOLUTION"  # draft or amend committee text
    ALLIANCE = "ALLIANCE"
    SANCTION = "SANCTION"
    AID = "AID"


# Which backend gate decides whether each kind is permitted in the current phase (None: not phase-gated).
GATE: dict[ResponseKind, Optional[ActionType]] = {
    ResponseKind.STATEMENT: ActionType.SPEECH,
    ResponseKind.NEGOTIATE: ActionType.NEGOTIATION,
    ResponseKind.RESOLUTION: ActionType.RESOLUTION_EDIT,
    ResponseKind.ALLIANCE: ActionType.ALLIANCE,
    ResponseKind.SANCTION: None,
    ResponseKind.AID: None,
}
NEEDS_TARGET = frozenset({ResponseKind.NEGOTIATE, ResponseKind.ALLIANCE, ResponseKind.SANCTION, ResponseKind.AID})


class RecommendedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ResponseKind
    target: Optional[str]  # exact country name; required for NEGOTIATE / ALLIANCE / SANCTION / AID
    description: str = Field(max_length=500)
    rationale: str = Field(max_length=400)

    @field_validator("description", "rationale")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return require_text(v, "text field")


class CrisisAnalysis(BaseModel):
    """A validated PROPOSAL. Exactly these six keys."""

    model_config = ConfigDict(extra="forbid")

    country: str
    severity: Severity
    summary: str = Field(max_length=600)
    affected_countries: list[str] = Field(max_length=8)
    key_risks: list[str] = Field(min_length=1, max_length=5)
    recommended_responses: list[RecommendedResponse] = Field(min_length=1, max_length=3)

    @field_validator("country", "summary")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return require_text(v, "text field")

    @field_validator("key_risks")
    @classmethod
    def _risks(cls, items: list[str]) -> list[str]:
        for item in items:
            require_text(item, "risk")
            if len(item) > 300:
                raise ValueError("risks must be at most 300 characters")
        return items

    @model_validator(mode="after")
    def _no_duplicate_countries(self) -> "CrisisAnalysis":
        if len(set(self.affected_countries)) != len(self.affected_countries):
            raise ValueError("affected_countries must not repeat a country")
        return self


SYSTEM_PROMPT = """\
You are the crisis analyst for {name}'s delegation in a Model UN committee. A crisis has been reported.
Assess its severity, which seated countries it affects, the main risks to {name}, and recommend one to three responses
that protect {name}'s interests, respect its red lines and avoid needless escalation.
Response kinds: STATEMENT (a speech), NEGOTIATE (talks with one country), RESOLUTION (committee text), ALLIANCE,
SANCTION, AID. NEGOTIATE, ALLIANCE, SANCTION and AID need a target (an exact seated country name); STATEMENT and
RESOLUTION use target null. Prefer the least escalatory response that works. Phase now: {phase}.

{rules}

Return exactly this JSON object:
{{"country":"{name}","severity":"LOW | MEDIUM | HIGH | CRITICAL","summary":"brief assessment",
"affected_countries":["exact seated country names"],"key_risks":["1-5 short risks"],
"recommended_responses":[{{"kind":"STATEMENT | NEGOTIATE | RESOLUTION | ALLIANCE | SANCTION | AID","target":"country name or null",
"description":"what to do","rationale":"why"}}]}}
"""


class CrisisAgent(MunAgent):
    role = "crisis-agent"

    def analyze(self, ctx: MunContext, crisis: CrisisBrief) -> AIResult:
        me = ctx.require_me()
        ctx.require_started()
        ctx.require_active("analyse a crisis")
        system = SYSTEM_PROMPT.format(name=me.country_name, phase=ctx.phase.value, rules=COMMON_RULES)
        dossiers = "\n\n".join(dossier_text(build_opponent_dossier(ctx, d.code)) for d in ctx.delegates if d.code != me.code)
        user = (
            f"{full_briefing(ctx)}\n\n{dossiers}\n\n=== CRISIS (data) ===\nTitle: {crisis.title}\n{crisis.description}\n\n"
            f"Analyse the crisis for {me.country_name}. JSON object only."
        )
        permitted = {
            kind.value: (None if gate is None else gate in ctx.allowed_actions) for kind, gate in GATE.items()
        }
        meta = {"phase": ctx.phase.value, "crisis_phase_open": ctx.phase.value == "CRISIS", "permitted_now": permitted}

        def parse(raw) -> CrisisAnalysis:
            out = validate_model(CrisisAnalysis, parse_json_object(raw), "crisis analysis")
            if out.country != me.country_name:
                raise ResponseError(f"Response is for '{out.country}', expected '{me.country_name}'")
            for name in out.affected_countries:
                if ctx.delegate_by_name(name) is None:
                    raise ResponseError(f"Unknown affected country '{name}': it holds no seat in this conference")
            for response in out.recommended_responses:
                if response.target is not None:
                    target = ctx.delegate_by_name(response.target)
                    if target is None:
                        raise ResponseError(f"Unknown target country '{response.target}': it holds no seat in this conference")
                    if target.code == me.code:
                        raise ResponseError("A recommended response cannot target the agent's own country")
                elif response.kind in NEEDS_TARGET:
                    raise ResponseError(f"{response.kind.value} requires a target country")
            return out

        return self._run(system, user, parse, label=f"{me.country_name}/crisis", meta=meta)