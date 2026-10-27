"""Phase 8: AI Speech Agent.

Drafts one speech for a seated country: an OPENING speech, a CAUCUS speech, a REBUTTAL, a RESPONSE or a CLOSING speech.
It only DRAFTS text. It never submits it: the delegate (or a client) sends the draft through the normal speech
endpoint, where the backend still checks the phase, the floor and the seat. `meta` says deterministically whether the
draft could be submitted right now (`submittable_now`) so a client does not have to guess.

Which speech types fit which phase is checked before Gemini is called (a wrong combination is a caller error, 409):

    OPENING   only in OPENING_SPEECHES
    CAUCUS    only in MODERATED_CAUCUS
    REBUTTAL / RESPONSE   any phase that permits speeches; they need a `target` country (whose position is answered)
    CLOSING   any phase from MODERATED_CAUCUS on, up to and including RESULTS (a draft: submitting is still gated)
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.mun import MAX_SPEECH_CHARS, PHASE_ORDER, ActionType, ConferencePhase, ConferenceStatus
from ai.country_agent import ResponseError
from ai.mun_context import MunContext, full_briefing
from ai.mun_core import COMMON_RULES, AIPreconditionError, AIResult, MunAgent, parse_json_object, require_text, validate_model
from ai.mun_opponent import build_opponent_dossier, dossier_text

MAX_WORDS_ADVICE = 220
MAX_ADDRESSED = 5


class SpeechType(str, Enum):
    OPENING = "OPENING"
    CAUCUS = "CAUCUS"
    REBUTTAL = "REBUTTAL"
    RESPONSE = "RESPONSE"
    CLOSING = "CLOSING"


NEEDS_TARGET = frozenset({SpeechType.REBUTTAL, SpeechType.RESPONSE})
_CLOSING_FROM = PHASE_ORDER.index(ConferencePhase.MODERATED_CAUCUS)


class SpeechDraft(BaseModel):
    """A validated DRAFT. Exactly these three keys."""

    model_config = ConfigDict(extra="forbid")

    country: str
    speech_type: SpeechType
    text: str = Field(min_length=1, max_length=MAX_SPEECH_CHARS)
    addressed_countries: list[str] = Field(max_length=MAX_ADDRESSED)

    @field_validator("country", "text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return require_text(v, "text field")


SYSTEM_PROMPT = """\
You are the speechwriter for {name}'s delegation in a Model UN committee. Write ONE {kind} speech in {name}'s voice.
Stay true to {name}'s goals and red lines, and to the committee agenda. Be diplomatic, concrete and persuasive,
speak in the first person plural ("{name} believes..."), and keep it under {words} words.
{guidance}

{rules}

Return exactly this JSON object:
{{"country":"{name}","speech_type":"{kind}","text":"the speech","addressed_countries":["exact country names the speech directly addresses, at most {max_addr}"]}}
"""

GUIDANCE = {
    SpeechType.OPENING: "An opening speech states {name}'s position on the agenda, its priorities, and the outcome it will work toward.",
    SpeechType.CAUCUS: "A caucus speech advances {name}'s case on the current debate, builds on what has been said, and may invite partners.",
    SpeechType.REBUTTAL: "A rebuttal answers {target}'s recorded position respectfully and precisely, using only what {target} actually said or did, and offers a counter-argument.",
    SpeechType.RESPONSE: "A response replies to {target}'s recent speech, offer or vote: acknowledge it, then state {name}'s position or conditions.",
    SpeechType.CLOSING: "A closing speech summarises {name}'s contribution, acknowledges partners and the drafting and voting record so far, and states its final position.",
}


def check_speech_phase(ctx: MunContext, speech_type: SpeechType) -> None:
    """Raise AIPreconditionError if this kind of speech does not fit the conference's phase (before any Gemini call)."""
    ctx.require_started()
    if speech_type is SpeechType.CLOSING:
        if ctx.status not in (ConferenceStatus.ACTIVE, ConferenceStatus.COMPLETED):
            raise AIPreconditionError(f"A closing speech needs a running or completed conference (status is {ctx.status.value})")
        if PHASE_ORDER.index(ctx.phase) < _CLOSING_FROM:
            raise AIPreconditionError(f"A closing speech cannot be drafted yet: the conference is in {ctx.phase.value}")
        return
    ctx.require_active(f"draft a {speech_type.value.lower()} speech")
    if speech_type is SpeechType.OPENING and ctx.phase is not ConferencePhase.OPENING_SPEECHES:
        raise AIPreconditionError(f"An opening speech belongs to OPENING_SPEECHES, not {ctx.phase.value}")
    if speech_type is SpeechType.CAUCUS and ctx.phase is not ConferencePhase.MODERATED_CAUCUS:
        raise AIPreconditionError(f"A caucus speech belongs to MODERATED_CAUCUS, not {ctx.phase.value}")
    if speech_type in NEEDS_TARGET and ActionType.SPEECH not in ctx.allowed_actions:
        raise AIPreconditionError(f"{ctx.phase.value} does not permit speeches, so a {speech_type.value.lower()} cannot be given now")


class SpeechAgent(MunAgent):
    role = "speech-agent"

    def draft(self, ctx: MunContext, speech_type: str, target_code: Optional[str] = None, brief: Optional[str] = None) -> AIResult:
        me = ctx.require_me()
        try:
            kind = SpeechType(speech_type)
        except ValueError:
            raise AIPreconditionError(f"Invalid speech type '{speech_type}'. Valid: {', '.join(t.value for t in SpeechType)}") from None
        check_speech_phase(ctx, kind)

        target = None
        if kind in NEEDS_TARGET:
            if not target_code:
                raise AIPreconditionError(f"A {kind.value.lower()} needs a target_code (the country being answered)")
            target = ctx.delegate_by_code(target_code)
            if target is None:
                raise AIPreconditionError(f"Country '{target_code}' holds no seat in conference '{ctx.conference_id}'")
            if target.code == me.code:
                raise AIPreconditionError("A country cannot rebut or respond to itself")
        elif target_code:
            raise AIPreconditionError(f"A {kind.value.lower()} speech takes no target_code")

        system = SYSTEM_PROMPT.format(
            name=me.country_name, kind=kind.value, words=MAX_WORDS_ADVICE, max_addr=MAX_ADDRESSED, rules=COMMON_RULES,
            guidance=GUIDANCE[kind].format(name=me.country_name, target=target.country_name if target else ""),
        )
        parts = [full_briefing(ctx)]
        if target is not None:
            parts.append(dossier_text(build_opponent_dossier(ctx, target.code)))
        if brief and brief.strip():
            parts.append(f"=== DELEGATE'S BRIEF ===\n{brief.strip()}")
        parts.append(f"Write the {kind.value} speech for {me.country_name}. JSON object only.")

        holds_floor = bool(ctx.speakers.current_speaker and ctx.speakers.current_speaker.participant_id == me.participant_id)
        meta = {
            "phase": ctx.phase.value,
            "speech_type": kind.value,
            "submittable_now": ctx.active and ActionType.SPEECH in ctx.allowed_actions and holds_floor,
            "holds_the_floor": holds_floor,
            "max_chars": MAX_SPEECH_CHARS,
        }

        def parse(raw) -> SpeechDraft:
            out = validate_model(SpeechDraft, parse_json_object(raw), "speech")
            if out.country != me.country_name:
                raise ResponseError(f"Response is for '{out.country}', expected '{me.country_name}'")
            if out.speech_type is not kind:
                raise ResponseError(f"Response is a {out.speech_type.value} speech, expected {kind.value}")
            seen = set()
            for name in out.addressed_countries:
                addressed = ctx.delegate_by_name(name)
                if addressed is None:
                    raise ResponseError(f"Unknown addressed country '{name}': it holds no seat in this conference")
                if addressed.code == me.code:
                    raise ResponseError("A speech cannot address its own country")
                if addressed.code in seen:
                    raise ResponseError(f"Addressed country '{name}' is listed twice")
                seen.add(addressed.code)
            if target is not None and target.code not in seen:
                raise ResponseError(f"A {kind.value.lower()} must address {target.country_name}")
            return out

        return self._run(system, "\n\n".join(parts), parse, label=f"{me.country_name}/speech", meta=meta)