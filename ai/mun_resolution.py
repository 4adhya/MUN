"""Phase 8: AI Resolution Assistant.

Four proposal-only tools for one country, all working on a stored resolution:

    suggest_clauses     new clauses for a DRAFT resolution
    review_resolution   an assessment of the text, cross-checked against deterministic structure checks
    suggest_amendments  ADD / MODIFY / REMOVE amendments for a SUBMITTED or UNDER_REVIEW resolution
    estimate_support    how each delegate is likely to vote, plus a PROJECTED tally

Nothing is written. Suggested clauses and amendments are validated with the backend's own request rules
(`ResolutionAmendRequest`, the clause length and count limits) and against the stored resolution (clause ids exist,
the only operative clause is not removed). The support estimate is a projection: the AI proposes each delegate's likely
vote, but the projected result is computed by `mun.voting.tally` under the committee's real voting rules (veto, majority,
abstentions), and real recorded votes always replace estimates. It is labelled `official: false`; only the backend's own
tally after voting decides a resolution.
"""
from __future__ import annotations

from enum import Enum
from types import SimpleNamespace
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.resolution_schemas import ResolutionAmendRequest, ResolutionView
from backend.mun import (
    AMENDABLE_STATUSES,
    MAX_CLAUSE_CHARS,
    MAX_CLAUSES,
    ActionType,
    AmendmentAction,
    ClauseType,
    ResolutionStatus,
    VoteChoice,
    VoteResult,
    is_resolution_final,
    operative_count,
    tally,
)
from ai.country_agent import ResponseError
from ai.mun_context import MunContext, conference_brief, country_brief, history_brief, render_resolution
from ai.mun_core import COMMON_RULES, AIPreconditionError, AIResult, MunAgent, describe, parse_json_object, require_text, validate_model
from ai.mun_opponent import build_opponent_dossier, dossier_text

MAX_SUGGESTED_CLAUSES = 5
MAX_SUGGESTED_AMENDMENTS = 3
PLACEHOLDER_PARTICIPANT = "ai-proposal"  # only used to run the request validator; never sent anywhere


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _text(v: str, limit: int = 400) -> str:
    require_text(v, "text field")
    if len(v) > limit:
        raise ValueError(f"text must be at most {limit} characters")
    return v


# --- clause suggestions --------------------------------------------------------------------------------
class ClauseSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ClauseType
    text: str = Field(min_length=1, max_length=MAX_CLAUSE_CHARS)
    rationale: str

    @field_validator("text")
    @classmethod
    def _t(cls, v: str) -> str:
        return require_text(v, "text")

    @field_validator("rationale")
    @classmethod
    def _r(cls, v: str) -> str:
        return _text(v, 300)


class ClauseSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str
    suggestions: list[ClauseSuggestion] = Field(min_length=1, max_length=MAX_SUGGESTED_CLAUSES)

    @field_validator("country")
    @classmethod
    def _c(cls, v: str) -> str:
        return require_text(v, "country")


# --- review --------------------------------------------------------------------------------------------------
class Readiness(str, Enum):
    NOT_READY = "NOT_READY"
    NEEDS_WORK = "NEEDS_WORK"
    READY = "READY"


class IssueSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_number: Optional[int] = Field(ge=1)
    severity: IssueSeverity
    issue: str

    @field_validator("issue")
    @classmethod
    def _i(cls, v: str) -> str:
        return _text(v, 400)


class ResolutionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str
    readiness: Readiness
    summary: str
    strengths: list[str] = Field(max_length=4)
    weaknesses: list[str] = Field(max_length=4)
    issues: list[ReviewIssue] = Field(max_length=6)

    @field_validator("country")
    @classmethod
    def _c(cls, v: str) -> str:
        return require_text(v, "country")

    @field_validator("summary")
    @classmethod
    def _s(cls, v: str) -> str:
        return _text(v, 600)

    @field_validator("strengths", "weaknesses")
    @classmethod
    def _items(cls, items: list[str]) -> list[str]:
        return [_text(i, 300) for i in items]


# --- amendments ---------------------------------------------------------------------------------------------
class AmendmentSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: AmendmentAction
    clause_id: Optional[str]
    type: Optional[ClauseType]
    text: Optional[str] = Field(max_length=MAX_CLAUSE_CHARS)
    rationale: str

    @field_validator("rationale")
    @classmethod
    def _r(cls, v: str) -> str:
        return _text(v, 300)


class AmendmentSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str
    amendments: list[AmendmentSuggestion] = Field(min_length=1, max_length=MAX_SUGGESTED_AMENDMENTS)

    @field_validator("country")
    @classmethod
    def _c(cls, v: str) -> str:
        return require_text(v, "country")


# --- support estimate ---------------------------------------------------------------------------------------
class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class VoteEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str
    likely_vote: VoteChoice
    confidence: Confidence
    reason: str

    @field_validator("country")
    @classmethod
    def _c(cls, v: str) -> str:
        return require_text(v, "country")

    @field_validator("reason")
    @classmethod
    def _r(cls, v: str) -> str:
        return _text(v, 300)


class SupportEstimate(BaseModel):
    """What the AI is asked for: per-delegate likely votes and a short summary."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    estimates: list[VoteEstimate] = Field(min_length=1)

    @field_validator("summary")
    @classmethod
    def _s(cls, v: str) -> str:
        return _text(v, 600)


class SupportProjection(BaseModel):
    """What the endpoint returns: the AI's estimates plus a tally computed deterministically from them."""

    official: bool = False
    resolution_id: str
    summary: str
    estimates: list[VoteEstimate]
    recorded_votes: dict[str, str] = Field(description="Real votes already cast (country code -> choice); they replace estimates")
    projected_result: VoteResult = Field(description="mun.voting.tally over recorded votes + estimates, NOT an official result")


# --- prompts ---------------------------------------------------------------------------------------------------
HEAD = "You are the resolution assistant for {name}'s delegation in a Model UN committee.\n"

CLAUSES_PROMPT = HEAD + """\
Suggest 1 to {max_n} NEW clauses for the DRAFT resolution below that advance {name}'s interests, fit the agenda, can
win broad support, and cross none of {name}'s red lines. Preambulatory clauses give context; operative clauses
prescribe action and begin with an action verb. Do not repeat an existing clause.

{rules}

Return exactly this JSON object:
{{"country":"{name}","suggestions":[{{"type":"PREAMBULATORY | OPERATIVE","text":"the clause","rationale":"why it helps"}}]}}
"""

REVIEW_PROMPT = HEAD + """\
Review the resolution below for {name}: coherence, fit with the agenda, clarity and enforceability of operative
clauses, balance, likelihood of support, and any clause that crosses {name}'s red lines. Reference clauses by number
(clause_number, or null for an issue with the whole text). readiness: NOT_READY (serious problems), NEEDS_WORK
(fixable), READY (could go to a vote as is). Be honest and specific.

{rules}

Return exactly this JSON object:
{{"country":"{name}","readiness":"NOT_READY | NEEDS_WORK | READY","summary":"brief assessment",
"strengths":["0-4 short points"],"weaknesses":["0-4 short points"],
"issues":[{{"clause_number":1,"severity":"MINOR | MAJOR","issue":"what is wrong"}}]}}
"""

AMEND_PROMPT = HEAD + """\
Suggest 1 to {max_n} amendments to the SUBMITTED resolution below that would move it toward {name}'s interests while
keeping enough support to pass. ADD needs type and text (clause_id null). MODIFY needs a clause_id from the briefing and
a new text and/or type. REMOVE needs a clause_id and no text or type. Never remove or retype the only operative clause.

{rules}

Return exactly this JSON object (null where a key does not apply):
{{"country":"{name}","amendments":[{{"action":"ADD | MODIFY | REMOVE","clause_id":"id or null",
"type":"PREAMBULATORY | OPERATIVE or null","text":"clause text or null","rationale":"why"}}]}}
"""

SUPPORT_PROMPT = HEAD + """\
Estimate how EVERY delegate listed under "Delegates to estimate" would vote on the resolution below, from their
goals, red lines, relationships, speeches, negotiations, sponsorship and past votes in the briefing. These are estimates,
not results; use ABSTAIN only when a country would plausibly abstain. Give each delegate exactly one entry.

{rules}

Return exactly this JSON object:
{{"summary":"brief overall picture","estimates":[{{"country":"exact country name","likely_vote":"YES | NO | ABSTAIN",
"confidence":"LOW | MEDIUM | HIGH","reason":"short evidence-based reason"}}]}}
"""


class ResolutionAssistant(MunAgent):
    role = "resolution-assistant"

    # -- shared -------------------------------------------------------------------------------------
    def _resolution(self, ctx: MunContext, resolution_id: str) -> ResolutionView:
        ctx.require_started()
        res = ctx.resolution(resolution_id)
        if res is None:
            raise AIPreconditionError(f"Resolution '{resolution_id}' not found in conference '{ctx.conference_id}'")
        return res

    @staticmethod
    def _user(ctx: MunContext, res: ResolutionView, extra: str = "", *, opponents: bool = False) -> str:
        parts = [conference_brief(ctx), country_brief(ctx), history_brief(ctx, full_resolutions=False),
                 "=== RESOLUTION UNDER DISCUSSION ===\n" + render_resolution(res, full=True)]
        if opponents:
            me = ctx.require_me()
            parts += [dossier_text(build_opponent_dossier(ctx, d.code)) for d in ctx.delegates if d.code != me.code]
        if extra.strip():
            parts.append(extra.strip())
        return "\n\n".join(parts)

    # -- clauses --------------------------------------------------------------------------------------
    def suggest_clauses(self, ctx: MunContext, resolution_id: str, focus: Optional[str] = None) -> AIResult:
        me = ctx.require_me()
        res = self._resolution(ctx, resolution_id)
        if res.status is not ResolutionStatus.DRAFT:
            raise AIPreconditionError(
                f"Resolution '{res.id}' is {res.status.value}; only a DRAFT takes new clauses (use amendments for a submitted one)"
            )
        room = MAX_CLAUSES - len(res.clauses)
        if room <= 0:
            raise AIPreconditionError(f"Resolution '{res.id}' already has the maximum of {MAX_CLAUSES} clauses")
        system = CLAUSES_PROMPT.format(name=me.country_name, max_n=min(MAX_SUGGESTED_CLAUSES, room), rules=COMMON_RULES)
        user = self._user(ctx, res, f"=== DELEGATE'S FOCUS ===\n{focus}" if focus else "") + "\n\nSuggest clauses. JSON object only."
        existing = {_norm(c.text) for c in res.clauses}

        def parse(raw) -> ClauseSuggestions:
            out = validate_model(ClauseSuggestions, parse_json_object(raw), "clause suggestions")
            if out.country != me.country_name:
                raise ResponseError(f"Response is for '{out.country}', expected '{me.country_name}'")
            if len(out.suggestions) > room:
                raise ResponseError(f"Too many clauses: the resolution has room for {room} more")
            seen = set(existing)
            for s in out.suggestions:
                key = _norm(s.text)
                if key in seen:
                    raise ResponseError("A suggested clause repeats an existing or earlier suggested clause")
                seen.add(key)
            return out

        meta = {"resolution_id": res.id, "editable_now": ctx.active and ActionType.RESOLUTION_EDIT in ctx.allowed_actions,
                "is_sponsor": me.code in res.sponsors}
        return self._run(system, user, parse, label=f"{me.country_name}/resolution", meta=meta)

    # -- review ---------------------------------------------------------------------------------------
    def review_resolution(self, ctx: MunContext, resolution_id: str) -> AIResult:
        me = ctx.require_me()
        res = self._resolution(ctx, resolution_id)
        pre = sum(1 for c in res.clauses if c.type is ClauseType.PREAMBULATORY)
        ops = operative_count(res)
        findings = []
        if ops == 0:
            findings.append("The resolution has no operative clause.")
        if pre == 0:
            findings.append("The resolution has no preambulatory clause.")
        if not res.clauses:
            findings.append("The resolution has no clauses at all.")
        meta = {"resolution_id": res.id, "status": res.status.value, "preambulatory_clauses": pre, "operative_clauses": ops,
                "structural_findings": findings, "official_result": res.result.model_dump(mode="json") if res.result else None}
        system = REVIEW_PROMPT.format(name=me.country_name, rules=COMMON_RULES)
        user = self._user(ctx, res, "Structural findings (deterministic): " + (" ".join(findings) or "none")) + "\n\nReview it. JSON object only."
        numbers = {c.number for c in res.clauses}

        def parse(raw) -> ResolutionReview:
            out = validate_model(ResolutionReview, parse_json_object(raw), "review")
            if out.country != me.country_name:
                raise ResponseError(f"Response is for '{out.country}', expected '{me.country_name}'")
            for issue in out.issues:
                if issue.clause_number is not None and issue.clause_number not in numbers:
                    raise ResponseError(f"Issue refers to clause {issue.clause_number}, which does not exist")
            if findings and out.readiness is Readiness.READY:
                raise ResponseError("The review calls the resolution READY despite structural problems: " + " ".join(findings))
            return out

        return self._run(system, user, parse, label=f"{me.country_name}/resolution", meta=meta)

    # -- amendments ---------------------------------------------------------------------------------
    def suggest_amendments(self, ctx: MunContext, resolution_id: str, focus: Optional[str] = None) -> AIResult:
        me = ctx.require_me()
        res = self._resolution(ctx, resolution_id)
        if res.status not in AMENDABLE_STATUSES:
            raise AIPreconditionError(f"Resolution '{res.id}' is {res.status.value}; only a SUBMITTED or UNDER_REVIEW resolution can be amended")
        system = AMEND_PROMPT.format(name=me.country_name, max_n=MAX_SUGGESTED_AMENDMENTS, rules=COMMON_RULES)
        user = self._user(ctx, res, f"=== DELEGATE'S FOCUS ===\n{focus}" if focus else "") + "\n\nSuggest amendments. JSON object only."
        clauses = {c.id: c for c in res.clauses}

        def parse(raw) -> AmendmentSuggestions:
            out = validate_model(AmendmentSuggestions, parse_json_object(raw), "amendment suggestions")
            if out.country != me.country_name:
                raise ResponseError(f"Response is for '{out.country}', expected '{me.country_name}'")
            operatives = {cid for cid, c in clauses.items() if c.type is ClauseType.OPERATIVE}
            touched: set[str] = set()
            for a in out.amendments:
                try:  # the backend's own request rules decide whether the fields fit the action
                    ResolutionAmendRequest(
                        participant_id=PLACEHOLDER_PARTICIPANT, action=a.action, clause_id=a.clause_id, type=a.type, text=a.text
                    )
                except ValidationError as exc:
                    raise ResponseError(f"Invalid amendment: {describe(exc)}") from None
                if a.action is AmendmentAction.ADD:
                    if a.type is ClauseType.OPERATIVE:
                        operatives.add(f"new-{len(operatives)}-{len(touched)}")
                    continue
                clause = clauses.get(a.clause_id)
                if clause is None:
                    raise ResponseError(f"Amendment refers to unknown clause '{a.clause_id}'")
                if a.clause_id in touched:
                    raise ResponseError(f"Clause '{a.clause_id}' is amended twice in one suggestion")
                touched.add(a.clause_id)
                if a.action is AmendmentAction.MODIFY and (a.text is None or a.text == clause.text) and (a.type is None or a.type is clause.type):
                    raise ResponseError(f"The MODIFY of clause '{a.clause_id}' changes nothing")
                if a.action is AmendmentAction.REMOVE or (a.type is ClauseType.PREAMBULATORY):
                    operatives.discard(a.clause_id)
            if not operatives:
                raise ResponseError("The amendments would leave the resolution without an operative clause")
            return out

        meta = {"resolution_id": res.id, "amendable_now": ctx.active and ActionType.AMENDMENT in ctx.allowed_actions,
                "is_sponsor": me.code in res.sponsors}
        return self._run(system, user, parse, label=f"{me.country_name}/resolution", meta=meta)

    # -- support estimate ---------------------------------------------------------------------------
    def estimate_support(self, ctx: MunContext, resolution_id: str) -> AIResult:
        me = ctx.require_me()
        res = self._resolution(ctx, resolution_id)
        if is_resolution_final(res):
            raise AIPreconditionError(f"Resolution '{res.id}' is already {res.status.value}; its official result stands")
        if res.status is ResolutionStatus.DRAFT:
            raise AIPreconditionError(f"Resolution '{res.id}' is still a DRAFT; support can be estimated once it is submitted")
        recorded = {v.country_code: v.choice for v in res.votes}
        pending = [d for d in ctx.delegates if d.code not in recorded]
        system = SUPPORT_PROMPT.format(name=me.country_name, rules=COMMON_RULES)
        listing = "\n".join(f"- {d.country_name}" for d in pending) or "- none (every delegate has voted)"
        dossiers = "\n\n".join(dossier_text(build_opponent_dossier(ctx, d.code)) for d in ctx.delegates if d.code != me.code)
        user = self._user(ctx, res) + f"\n\n{dossiers}\n\n=== Delegates to estimate ===\n{listing}\n\nEstimate the votes. JSON object only."
        if not pending:
            raise AIPreconditionError(f"Every delegate has already voted on '{res.id}'; read the roll call instead")

        def parse(raw) -> SupportProjection:
            out = validate_model(SupportEstimate, parse_json_object(raw), "support estimate")
            expected = {d.country_name: d for d in pending}
            seen: set[str] = set()
            for e in out.estimates:
                if e.country in seen:
                    raise ResponseError(f"'{e.country}' is estimated twice")
                seen.add(e.country)
                if ctx.delegate_by_name(e.country) is None:
                    raise ResponseError(f"Unknown country '{e.country}': it holds no seat in this conference")
                if e.country not in expected:
                    raise ResponseError(f"'{e.country}' has already voted; the recorded vote stands")
            missing = sorted(set(expected) - seen)
            if missing:
                raise ResponseError("The estimate is missing: " + ", ".join(missing))
            votes = [SimpleNamespace(country_code=code, choice=choice) for code, choice in recorded.items()]
            votes += [SimpleNamespace(country_code=expected[e.country].code, choice=e.likely_vote) for e in out.estimates]
            projected = tally(votes, [d.code for d in ctx.delegates], ctx.rules)
            return SupportProjection(
                resolution_id=res.id, summary=out.summary, estimates=out.estimates,
                recorded_votes={k: v.value for k, v in recorded.items()}, projected_result=projected,
            )

        meta = {"resolution_id": res.id, "status": res.status.value, "estimate_only": True}
        return self._run(system, user, parse, label=f"{me.country_name}/resolution", meta=meta)