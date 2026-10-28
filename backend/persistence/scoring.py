"""Deterministic delegate scoring, derived only from the recorded event/action history.

Scoring is a PURE function of what actually happened in a conference: the world's event log plus the
seated participants. It never looks at AI output, never mutates state, and always returns the same
score for the same history (so a reload reproduces the same numbers). This mirrors how
``report_service`` already derives per-country activity from the event log, keeping ONE source of
truth for "what happened".

The weights below are simple, explainable points for recorded diplomatic activity. They reward
constructive engagement (speeches, alliances, aid, accepted negotiations) and lightly penalise
inactivity; they are intentionally modest and bounded so the feature stays a scoreboard, not a new
game mechanic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..models import DiplomacyEvent, WorldState
from ..mun import Participant, ParticipantRole

# Event types the scorer understands (all already emitted by the existing services).
SPEECH_EVENT = "speech_submitted"
NEGOTIATION_PROPOSED = "negotiation_proposed"
NEGOTIATION_ACCEPTED = "negotiation_accepted"
NEGOTIATION_REJECTED = "negotiation_rejected"
NEGOTIATION_COUNTERED = "negotiation_countered"
CRISIS_RESPONSE = "crisis_response"
RESOLUTION_PASSED = "resolution_passed"
ACTION_SANCTION = "sanction"
ACTION_ALLIANCE = "alliance"
ACTION_AID = "aid"

# Points per recorded contribution. Deterministic and explainable.
POINTS = {
    "speech": 3.0,
    "negotiation_proposed": 2.0,
    "negotiation_accepted": 4.0,  # credited to the responder who accepted
    "negotiation_rejected": 1.0,  # still engaged
    "negotiation_countered": 2.0,
    "crisis_response": 4.0,
    "alliance": 3.0,
    "aid": 3.0,
    "sanction": 1.0,
    "resolution_passed": 5.0,  # shared by the delegate whose action carried it, if attributable
}


@dataclass
class ScoreBreakdown:
    participant_id: str
    country_code: Optional[str]
    name: str
    score: float = 0.0
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, points: float) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.score = round(self.score + points, 2)


def _actor_country_id(event: DiplomacyEvent) -> Optional[str]:
    """Country id that initiated the event, from the event itself (actor) or its effects."""
    if event.actor:
        return event.actor
    return None


def score_participants(
    participants: Iterable[Participant],
    world: Optional[WorldState],
) -> list[ScoreBreakdown]:
    """Deterministic scores for every PARTICIPANT delegate, from the world's event log.

    Guests/jury are not scored (they do not represent a country). Returns one ScoreBreakdown per
    seated delegate, ordered by descending score then country code for stable, reproducible output.
    """
    delegates = [
        p for p in participants
        if p.role is ParticipantRole.PARTICIPANT and p.country_code
    ]
    # Map a country id (e.g. "india") -> the delegate representing it. The event log uses country
    # ids; participants carry the ISO alpha-2 code, so we bridge through the world's countries.
    code_by_id: dict[str, str] = {}
    if world is not None:
        for c in world.countries:
            if c.country_code:
                code_by_id[c.id] = c.country_code

    by_code: dict[str, ScoreBreakdown] = {
        p.country_code: ScoreBreakdown(
            participant_id=p.id, country_code=p.country_code, name=p.name
        )
        for p in delegates
    }

    def breakdown_for_country_id(country_id: Optional[str]) -> Optional[ScoreBreakdown]:
        if not country_id:
            return None
        code = code_by_id.get(country_id)
        return by_code.get(code) if code else None

    events = list(world.events) if world is not None else []
    for event in events:
        fx = event.effects or {}
        actor = breakdown_for_country_id(_actor_country_id(event))

        if event.type == SPEECH_EVENT:
            # Speech effects carry the acting country_code directly.
            code = fx.get("country_code")
            bd = by_code.get(code) if code else actor
            if bd:
                bd.add("speech", POINTS["speech"])
        elif event.type == NEGOTIATION_PROPOSED:
            bd = by_code.get(fx.get("proposer")) or actor
            if bd:
                bd.add("negotiation_proposed", POINTS["negotiation_proposed"])
        elif event.type == NEGOTIATION_ACCEPTED:
            # The responder (receiver) accepted; credit them.
            bd = by_code.get(fx.get("receiver")) or actor
            if bd:
                bd.add("negotiation_accepted", POINTS["negotiation_accepted"])
        elif event.type == NEGOTIATION_REJECTED:
            bd = by_code.get(fx.get("receiver")) or actor
            if bd:
                bd.add("negotiation_rejected", POINTS["negotiation_rejected"])
        elif event.type == NEGOTIATION_COUNTERED:
            bd = by_code.get(fx.get("receiver")) or actor
            if bd:
                bd.add("negotiation_countered", POINTS["negotiation_countered"])
        elif event.type == CRISIS_RESPONSE:
            code = fx.get("country_code")
            bd = by_code.get(code) if code else actor
            if bd:
                bd.add("crisis_response", POINTS["crisis_response"])
        elif event.type == ACTION_ALLIANCE and actor:
            actor.add("alliance", POINTS["alliance"])
        elif event.type == ACTION_AID and actor:
            actor.add("aid", POINTS["aid"])
        elif event.type == ACTION_SANCTION and actor:
            actor.add("sanction", POINTS["sanction"])
        elif event.type == RESOLUTION_PASSED:
            # Credit the sponsor(s) if the effect records them; otherwise it is a committee-wide pass.
            sponsors = fx.get("sponsors") or []
            for code in sponsors:
                bd = by_code.get(code)
                if bd:
                    bd.add("resolution_passed", POINTS["resolution_passed"])

    results = list(by_code.values())
    results.sort(key=lambda b: (-b.score, b.country_code or ""))
    return results
