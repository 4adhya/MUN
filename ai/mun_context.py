"""Phase 8: what the conference AI roles get to know, read from the backend and never from the AI.

`build_context(conference_id, country_code)` reads ONE consistent view of a conference through the services' public
read methods (snapshot, speeches, negotiations, resolutions with their roll call, speaker queue) and the committee's
voting rules. Nothing is written back. The result is a `MunContext`: plain data plus helpers that every role uses to
check an AI reply against the real conference (is that country seated? is that resolution open for a vote? does the
phase permit this?) and to render prompt text.

The prompt text reuses the existing `country_agent.build_briefing` for the country's world view (GDP, stability,
alliances, sanctions, trade, relationships, recent events) and adds the conference layer: committee, agenda, phase,
time left, voting rules, delegates, and a bounded recent history.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from backend.conference_schemas import ConferenceSnapshot, ConferenceWorldView
from backend.conference_service import conference_service as shared_conferences
from backend.resolution_schemas import ResolutionView
from backend.resolution_service import resolution_service as shared_resolutions
from backend.speech_schemas import SpeakerQueueView
from backend.mun import (
    ActionType,
    ConferencePhase,
    ConferenceStatus,
    Negotiation,
    ResolutionStatus,
    Speech,
    VoteChoice,
    VotingRules,
    get_committee_config,
)
from ai.country_agent import AgentProfile, build_briefing
from ai.mun_core import AIPreconditionError
from ai.mun_profiles import MunProfile, agent_profile_for, mun_profile_for

RECENT_SPEECHES = 8
RECENT_NEGOTIATIONS = 8
SPEECH_EXCERPT_CHARS = 300
NEGOTIATION_EXCERPT_CHARS = 200
CLAUSE_EXCERPT_CHARS = 500


@dataclass(frozen=True)
class Delegate:
    code: str  # ISO alpha-2
    country_id: str
    country_name: str
    participant_id: str
    participant_name: str


@dataclass
class MunContext:
    snapshot: ConferenceSnapshot
    now: datetime
    rules: VotingRules
    delegates: list[Delegate]
    speeches: list[Speech]
    negotiations: list[Negotiation]
    resolutions: list[ResolutionView]
    speakers: SpeakerQueueView
    me: Optional[Delegate] = None
    extra: dict = field(default_factory=dict)

    # --- plain facts ---------------------------------------------------------------------------
    @property
    def conference_id(self) -> str:
        return self.snapshot.id

    @property
    def phase(self) -> ConferencePhase:
        return self.snapshot.current_phase

    @property
    def status(self) -> ConferenceStatus:
        return self.snapshot.status

    @property
    def world(self) -> Optional[ConferenceWorldView]:
        return self.snapshot.world

    @property
    def active(self) -> bool:
        return self.status is ConferenceStatus.ACTIVE

    @property
    def allowed_actions(self) -> set[ActionType]:
        """What the current phase permits right now (empty unless the conference is ACTIVE), from the backend."""
        return {ActionType(a) for a in self.snapshot.allowed_actions}

    @property
    def remaining_seconds(self) -> Optional[int]:
        end = self.snapshot.phase_ends_at
        if end is None or not self.active:
            return None
        return max(0, int((end - self.now).total_seconds()))

    # --- lookups the validators use ------------------------------------------------------------
    def delegate_by_code(self, code: str) -> Optional[Delegate]:
        key = code.strip().upper() if isinstance(code, str) else ""
        return next((d for d in self.delegates if d.code == key), None)

    def delegate_by_name(self, name: str) -> Optional[Delegate]:
        """Exact (case-sensitive) display-name match, like the existing country agent."""
        return next((d for d in self.delegates if d.country_name == name), None)

    def resolution(self, resolution_id: str) -> Optional[ResolutionView]:
        return next((r for r in self.resolutions if r.id == resolution_id), None)

    def negotiation(self, negotiation_id: str) -> Optional[Negotiation]:
        return next((n for n in self.negotiations if n.id == negotiation_id), None)

    def country_name(self, code: str) -> str:
        d = self.delegate_by_code(code)
        return d.country_name if d else code

    def require_started(self) -> ConferenceWorldView:
        if self.world is None:
            raise AIPreconditionError(f"Conference '{self.conference_id}' has not started; there is no world to reason about")
        return self.world

    def require_active(self, doing: str) -> None:
        if not self.active:
            raise AIPreconditionError(
                f"Conference '{self.conference_id}' is {self.status.value}; the AI cannot help {doing} unless it is ACTIVE"
            )

    def require_me(self) -> Delegate:
        if self.me is None:
            raise AIPreconditionError("This request needs a country_code")
        return self.me

    def profile(self, delegate: Optional[Delegate] = None) -> AgentProfile:
        d = delegate or self.require_me()
        profile = agent_profile_for(d.country_id)
        if profile is None:
            raise AIPreconditionError(f"No AI profile is configured for {d.country_name}")
        return profile

    def mun_profile(self, delegate: Optional[Delegate] = None) -> MunProfile:
        return mun_profile_for((delegate or self.require_me()).country_id)

    def open_resolutions_for_me(self) -> list[ResolutionView]:
        """Resolutions in VOTING on which this country has not voted yet."""
        me = self.require_me()
        return [
            r for r in self.resolutions
            if r.status is ResolutionStatus.VOTING and all(v.country_code != me.code for v in r.votes)
        ]


def build_context(
    conference_id: str,
    country_code: Optional[str] = None,
    *,
    conferences=None,
    resolutions=None,
    now: Optional[datetime] = None,
) -> MunContext:
    """Read a conference (404 NotFoundError if unknown). With `country_code`, that country must hold a seat in it."""
    conferences = conferences or shared_conferences
    resolutions = resolutions or shared_resolutions
    snapshot = conferences.get(conference_id)
    delegates = [
        Delegate(a.country_code, a.country_id, a.country_name, a.participant_id, a.participant_name)
        for a in snapshot.assigned_countries
    ]
    me = None
    if country_code is not None:
        me = next((d for d in delegates if d.code == str(country_code).strip().upper()), None)
        if me is None:
            raise AIPreconditionError(f"Country '{country_code}' holds no seat in conference '{conference_id}'")
    return MunContext(
        snapshot=snapshot,
        now=now or datetime.now(timezone.utc),
        rules=get_committee_config(snapshot.committee).voting_rules,
        delegates=delegates,
        speeches=conferences.get_speeches(conference_id),
        negotiations=conferences.get_negotiations(conference_id),
        resolutions=resolutions.list_resolutions(conference_id),
        speakers=conferences.get_speakers(conference_id),
        me=me,
    )


# --- prompt text -----------------------------------------------------------------------------------
def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _rules_text(rules: VotingRules) -> str:
    parts = [f"{rules.majority.value.lower()} majority" + (f" ({rules.threshold:g})" if rules.threshold else "")]
    parts.append(f"abstentions {rules.abstention.value.lower().replace('_', ' ')}")
    if rules.absent_counts_against:
        parts.append("absent delegates count against")
    if rules.veto_enabled:
        parts.append("veto held by " + ", ".join(rules.veto_members))
    return "; ".join(parts)


def conference_brief(ctx: MunContext) -> str:
    snap = ctx.snapshot
    remaining = ctx.remaining_seconds
    lines = [
        "=== CONFERENCE ===",
        f"Committee: {snap.committee} | Agenda: {snap.topic}",
        f"Status: {snap.status.value} | Phase: {snap.current_phase.value} | Next step: {snap.next_phase or 'none'}",
        "Time left in phase: " + (f"{remaining // 60} min {remaining % 60} s" if remaining is not None else "untimed or not running"),
        "Actions the phase permits: " + (", ".join(sorted(a.value for a in ctx.allowed_actions)) or "none"),
        f"Voting rules: {_rules_text(ctx.rules)}",
        "Seated delegates: " + (", ".join(f"{d.country_name} ({d.code})" for d in ctx.delegates) or "none"),
    ]
    if ctx.world is not None:
        m = ctx.world.mun_metrics
        lines.append(
            f"World metrics (0-100): stability {m.world_stability:g}, tension {m.diplomatic_tension:g}, "
            f"humanitarian impact {m.humanitarian_impact:g}, trust {m.international_trust:g}, "
            f"cybersecurity {m.cybersecurity_level:g}, economic risk {m.economic_risk:g}"
        )
    return "\n".join(lines)


def country_brief(ctx: MunContext, delegate: Optional[Delegate] = None) -> str:
    """Profile, goals, red lines and the live world view of one seated country."""
    d = delegate or ctx.require_me()
    world = ctx.require_started()
    profile, mun = ctx.profile(d), ctx.mun_profile(d)
    lines = [
        f"=== YOUR COUNTRY: {d.country_name} ({d.code}) ===",
        f"Personality: {profile.personality}",
        "Goals: " + " | ".join(profile.goals),
        "Committee priorities: " + (" | ".join(mun.priorities) or "none recorded"),
        "RED LINES (never accept): " + (" | ".join(mun.red_lines) or "none recorded"),
        "",
        build_briefing(world, profile),
    ]
    return "\n".join(lines)


def render_resolution(r: ResolutionView, full: bool = True) -> str:
    head = (
        f"- [{r.id}] \"{r.title}\" status {r.status.value}; sponsors {', '.join(r.sponsors)}; "
        f"signatories {', '.join(r.signatories) or 'none'}; {len(r.clauses)} clauses, {len(r.amendments)} amendments"
    )
    lines = [head]
    if full:
        lines += [f"    clause {c.number} [{c.id}] {c.type.value}: {_clip(c.text, CLAUSE_EXCERPT_CHARS)}" for c in r.clauses]
    if r.votes:
        lines.append("    votes: " + ", ".join(f"{v.country_code} {v.choice.value}" for v in r.votes))
    if r.result is not None:
        lines.append(f"    OFFICIAL RESULT: {'PASSED' if r.result.passed else 'FAILED'} - {r.result.reason}")
    return "\n".join(lines)


def history_brief(ctx: MunContext, full_resolutions: bool = True) -> str:
    lines = ["=== RECENT SPEECHES ==="]
    for s in ctx.speeches[-RECENT_SPEECHES:]:
        lines.append(f"- {ctx.country_name(s.country_code)} ({s.phase.value}): {_clip(s.text, SPEECH_EXCERPT_CHARS)}")
    if len(lines) == 1:
        lines.append("- none yet")
    lines.append("=== RECENT NEGOTIATIONS ===")
    n_start = len(lines)
    for n in ctx.negotiations[-RECENT_NEGOTIATIONS:]:
        row = (
            f"- [{n.id}] {ctx.country_name(n.proposer)} -> {ctx.country_name(n.receiver)} {n.status.value}: "
            f"{_clip(n.proposal, NEGOTIATION_EXCERPT_CHARS)}"
        )
        if n.counter_offer:
            row += f" | counter: {_clip(n.counter_offer, NEGOTIATION_EXCERPT_CHARS)}"
        lines.append(row)
    if len(lines) == n_start:
        lines.append("- none yet")
    lines.append("=== RESOLUTIONS ===")
    if ctx.resolutions:
        lines += [render_resolution(r, full_resolutions) for r in ctx.resolutions]
    else:
        lines.append("- none yet")
    return "\n".join(lines)


def full_briefing(ctx: MunContext, with_country: bool = True) -> str:
    parts = [conference_brief(ctx)]
    if with_country:
        parts.append(country_brief(ctx))
    parts.append(history_brief(ctx))
    return "\n\n".join(parts)


VOTE_VALUES = tuple(v.value for v in VoteChoice)