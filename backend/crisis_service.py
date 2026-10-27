"""Phase 7: the crisis engine (in-memory, on top of `ConferenceService`).

A crisis is something that happens to the conference's world while the committee is in its CRISIS phase: a JURY member
starts one, the seated delegates each answer it with one of its response options, and a JURY member resolves it.
Crises, their options and the responses are kept here, per conference, next to (never inside) the conference record.
This module never re-implements a gate: membership comes from `ConferenceService._member`, and the phase gate is the
same `check_action` every other phase-restricted action passes through (`ActionType.CRISIS_RESPONSE`, which
`mun.phases` allows only in CRISIS). Data belongs to the conference RECORD it was created for, so
`ConferenceService.clear()` forgets it with everything else.

What each action needs (checked in this order; a rejected request stores nothing, emits nothing and changes no metric):

  start .... 404 unknown conference        403 not in the conference, or not a JURY member
             409 conference not ACTIVE / phase is not CRISIS / the CRISIS phase's time is up
             422 unknown template or invalid content       409 too many open crises (MAX_ACTIVE_CRISES)
  respond .. 404 unknown crisis            403 not in the conference, or not a PARTICIPANT delegate
             409 crisis not ACTIVE (resolved or expired)   409 conference not ACTIVE / phase is not CRISIS
             403 `country_code` is not the participant's own seat
             422 the option is not one of this crisis's    409 this country already responded
  resolve .. 404 unknown crisis            403 not in the conference, or not a JURY member
             409 crisis not ACTIVE         409 conference not ACTIVE / phase is not CRISIS

Consequences are deterministic and backend-owned. A response applies its option's `effects` (integer metric deltas
fixed when the crisis was created, from the action type and the severity - see `mun.crisis`) to the conference's OWN
world through `crisis_rules.apply_effects`, on a scratch copy that is committed only after `validate_world` passes. The
shared sandbox simulation is never touched. Nothing in this module reads free text to decide an effect, and nothing
here can be called by an AI to change the world: an advisor can only READ crises and `preview_option`, which changes
nothing.

Expiry is lazy and safe, like negotiations: every read or write first brings the conference's crises up to date. A
crisis expires when its `expires_at` passes (never later than the CRISIS phase's own deadline) or when the conference
leaves CRISIS or ends, so an expired crisis can never be answered. Expiry is silence, not a decision: it records an
event and changes no metric. Events are appended to the conference's world and never removed:

    crisis_created, crisis_response, world_state_changed (only when a metric really moved),
    crisis_resolved, crisis_expired
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import ValidationError

from .conference_service import (
    ConferenceRecord,
    ConferenceService,
    ForbiddenError,
    InvalidRequestError,
    conference_service,
)
from .crisis_rules import apply_effects, project_effects
from .crisis_schemas import CrisisPreview, CrisisRespondResult, CrisisView
from .models import DiplomacyEvent, WorldState
from .mun import ActionType, ParticipantRole
from .mun.crisis import (
    CRISIS_TEMPLATES,
    CRISIS_TTL_SECONDS,
    DEFAULT_OPTION_TYPES,
    MAX_ACTIVE_CRISES,
    Crisis,
    CrisisActionType,
    CrisisEndReason,
    CrisisOption,
    CrisisResponse,
    CrisisSeverity,
    CrisisStatus,
    CrisisTemplate,
    UnknownCrisisTemplateError,
    build_options,
    close_crisis,
    expiry_reason,
    get_template,
    outcome_for,
)
from .rules import ConflictError, NotFoundError, validate_world

CRISIS_CREATED_EVENT = "crisis_created"
CRISIS_RESPONSE_EVENT = "crisis_response"
CRISIS_RESOLVED_EVENT = "crisis_resolved"
CRISIS_EXPIRED_EVENT = "crisis_expired"
WORLD_STATE_CHANGED_EVENT = "world_state_changed"

# Who may start and resolve crises. The conference has no chair role, so the JURY (the game masters) does it; change
# this one set to widen or narrow that.
CRISIS_ADMIN_ROLES = frozenset({ParticipantRole.JURY})


def _problems(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())


def _signed(changes: dict[str, float]) -> str:
    return ", ".join(f"{name} {delta:+g}" for name, delta in changes.items())


@dataclass
class _Book:
    """Everything the crisis engine keeps for ONE conference record."""

    record: ConferenceRecord  # the record this book belongs to; a different record (after clear()) means a stale book
    crises: list[Crisis] = field(default_factory=list)  # append-only history; entries only change status
    options: list[CrisisOption] = field(default_factory=list)  # fixed when the crisis is created, never edited
    responses: list[CrisisResponse] = field(default_factory=list)  # append-only


class CrisisService:
    def __init__(self, conferences: ConferenceService) -> None:
        self._c = conferences
        self._books: dict[str, _Book] = {}

    # --- helpers -------------------------------------------------------------------------------
    def _prune(self) -> None:
        """Forget books of conferences that no longer exist (e.g. after `ConferenceService.clear()`)."""
        for conference_id in [cid for cid, b in self._books.items() if self._c._records.get(cid) is not b.record]:
            del self._books[conference_id]

    def _book(self, record: ConferenceRecord) -> _Book:
        self._prune()
        book = self._books.get(record.conference.id)
        if book is None:
            book = self._books[record.conference.id] = _Book(record=record)
        return book

    def _find(self, crisis_id: str) -> tuple[ConferenceRecord, _Book, int]:
        self._prune()
        for book in self._books.values():
            for index, crisis in enumerate(book.crises):
                if crisis.id == crisis_id:
                    return book.record, book, index
        raise NotFoundError(f"Crisis '{crisis_id}' not found")

    @staticmethod
    def _options_of(book: _Book, crisis_id: str) -> list[CrisisOption]:
        return [o for o in book.options if o.crisis_id == crisis_id]

    @staticmethod
    def _responses_of(book: _Book, crisis_id: str) -> list[CrisisResponse]:
        return [r for r in book.responses if r.crisis_id == crisis_id]

    def _view(self, book: _Book, crisis: Crisis) -> CrisisView:
        return CrisisView(
            **crisis.model_dump(),
            options=[o.model_copy(deep=True) for o in self._options_of(book, crisis.id)],
            responses=[r.model_copy(deep=True) for r in self._responses_of(book, crisis.id)],
        )

    @staticmethod
    def _event(
        world: WorldState,
        pending: list[DiplomacyEvent],
        now: datetime,
        type_: str,
        actor: str,
        target: Optional[str],
        message: str,
        effects: dict[str, Any],
    ) -> None:
        """Build an event and queue it in `pending`; the caller appends the queue to the world when it commits.

        The actor is the acting country, or the conference itself for events the backend raises on its own
        (a crisis starting, resolving or expiring), as `conference_start` does.
        """
        pending.append(
            DiplomacyEvent(
                id=len(world.events) + len(pending) + 1,
                turn=world.turn,
                type=type_,
                actor=actor,
                target=target,
                message=message,
                timestamp=now,
                effects=effects,
            )
        )

    def _sync(self, record: ConferenceRecord, now: datetime) -> None:
        """Expire every ACTIVE crisis whose time is up or whose phase (or conference) is over.

        Records one `crisis_expired` event each. Idempotent (an EXPIRED crisis is final and never expired twice) and
        it cannot fail half-way: every event is built before anything is stored. Changes no metric.
        """
        world = record.world
        book = self._book(record)
        if world is None or not book.crises:
            return
        conference = record.conference
        pending: list[DiplomacyEvent] = []
        changes: list[tuple[int, Crisis]] = []
        for index, crisis in enumerate(book.crises):
            reason = expiry_reason(crisis, now, conference.current_phase, conference.status)
            if reason is None:
                continue
            closed = close_crisis(crisis, reason, now)
            self._event(
                world,
                pending,
                now,
                CRISIS_EXPIRED_EVENT,
                conference.id,
                None,
                f"Crisis '{crisis.title}' expired unresolved "
                f"({'the conference left the crisis phase' if reason is CrisisEndReason.PHASE_CLOSED else 'time ran out'}).",
                {
                    "conference_id": conference.id,
                    "crisis_id": crisis.id,
                    "status": CrisisStatus.EXPIRED.value,
                    "reason": reason.value,
                    "phase": conference.current_phase.value,
                    "responses": len(self._responses_of(book, crisis.id)),
                    "metrics_changed": False,
                },
            )
            changes.append((index, closed))
        for index, closed in changes:  # nothing above can fail: commit together
            book.crises[index] = closed
        world.events.extend(pending)

    def _admin(self, record: ConferenceRecord, participant_id: str, doing: str):
        participant = self._c._member(record, participant_id)
        if participant.role not in CRISIS_ADMIN_ROLES:
            allowed = ", ".join(sorted(r.value for r in CRISIS_ADMIN_ROLES))
            raise ForbiddenError(f"{participant.role.value} participants cannot {doing}; only {allowed} members can")
        return participant

    @staticmethod
    def _require_active(crisis: Crisis, doing: str) -> None:
        if crisis.status is not CrisisStatus.ACTIVE:
            raise ConflictError(f"Crisis '{crisis.id}' is already {crisis.status.value} and can no longer be {doing}")

    # --- operations ----------------------------------------------------------------------------
    def create_crisis(
        self,
        conference_id: str,
        participant_id: str,
        *,
        template_id: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        severity: Optional[CrisisSeverity] = None,
        option_types: Optional[list[CrisisActionType]] = None,
    ) -> CrisisView:
        """A JURY member starts a crisis (status ACTIVE at once), and a `crisis_created` event is emitted.

        With `template_id` the template supplies the title, description, severity and option types; any of the four
        given explicitly overrides it. Without one, title, description and severity are required and the option types
        default to DEFAULT_OPTION_TYPES. The crisis starts now and expires after CRISIS_TTL_SECONDS, but never later
        than the end of the CRISIS phase. Each option's effects are worked out by the backend; clients cannot send them.
        """
        with self._c._lock:
            record = self._c._get(conference_id)
            self._admin(record, participant_id, "start crises")

            now = self._c._clock()
            self._sync(record, now)
            self._c.check_action(conference_id, ActionType.CRISIS_RESPONSE.value)  # ACTIVE + the phase permits it
            phase_ends = record.conference.phase_ends_at
            if phase_ends is not None and phase_ends <= now:
                raise ConflictError(
                    "The time for the CRISIS phase is up; advance the conference instead of starting a new crisis"
                )

            template: Optional[CrisisTemplate] = None
            if template_id is not None:
                try:
                    template = get_template(template_id)
                except UnknownCrisisTemplateError as exc:
                    raise InvalidRequestError(str(exc)) from None
            crisis_title = title if title is not None else (template.title if template else None)
            crisis_description = description if description is not None else (template.description if template else None)
            crisis_severity = severity if severity is not None else (template.severity if template else None)
            types = option_types if option_types is not None else (
                list(template.option_types) if template else list(DEFAULT_OPTION_TYPES)
            )
            if crisis_title is None or crisis_description is None or crisis_severity is None:
                raise InvalidRequestError("title, description and severity are required when no template_id is given")

            book = self._book(record)
            open_crises = sum(1 for c in book.crises if c.status is CrisisStatus.ACTIVE)
            if open_crises >= MAX_ACTIVE_CRISES:
                raise ConflictError(
                    f"Too many open crises: at most {MAX_ACTIVE_CRISES} can be active at once; resolve one first"
                )

            expires_at = now + timedelta(seconds=CRISIS_TTL_SECONDS)
            if phase_ends is not None:
                expires_at = min(expires_at, phase_ends)  # a crisis never outlives the CRISIS phase's deadline
            try:
                crisis = Crisis(
                    conference_id=conference_id,
                    title=crisis_title,
                    description=crisis_description,
                    severity=crisis_severity,
                    started_at=now,
                    expires_at=expires_at,
                    created_by=participant_id,
                )
                options = build_options(crisis.id, crisis.severity, types)
            except ValidationError as exc:
                raise InvalidRequestError(f"Invalid crisis: {_problems(exc)}") from None
            except ValueError as exc:
                raise InvalidRequestError(str(exc)) from None

            world = record.world
            pending: list[DiplomacyEvent] = []
            self._event(
                world,
                pending,
                now,
                CRISIS_CREATED_EVENT,
                conference_id,
                None,
                f"Crisis started: {crisis.title} ({crisis.severity.value}).",
                {
                    "conference_id": conference_id,
                    "crisis_id": crisis.id,
                    "title": crisis.title,
                    "severity": crisis.severity.value,
                    "status": crisis.status.value,
                    "phase": record.conference.current_phase.value,
                    "created_by": participant_id,
                    "expires_at": crisis.expires_at.isoformat(),
                    "options": [{"id": o.id, "action_type": o.action_type.value} for o in options],
                },
            )

            book.crises.append(crisis)  # nothing below can fail: all commits happen together
            book.options.extend(options)
            world.events.extend(pending)
            return self._view(book, crisis)

    def respond(self, crisis_id: str, participant_id: str, country_code: str, option_id: str) -> CrisisRespondResult:
        """A delegate answers an ACTIVE crisis for their own country; the option's effects change the world's metrics.

        Emits `crisis_response`, and `world_state_changed` when at least one metric really moved. The world is updated
        on a scratch copy and only committed, together with the response, once it validates. Each country may answer a
        crisis once.
        """
        with self._c._lock:
            record, book, index = self._find(crisis_id)
            conference_id = record.conference.id
            participant = self._c._member(record, participant_id)
            if participant.role is not ParticipantRole.PARTICIPANT:
                raise ForbiddenError(
                    f"{participant.role.value} participants cannot respond to crises; only PARTICIPANT delegates can"
                )

            now = self._c._clock()
            self._sync(record, now)
            crisis = book.crises[index]  # may just have expired
            self._require_active(crisis, "responded to")
            self._c.check_action(conference_id, ActionType.CRISIS_RESPONSE.value)  # ACTIVE + the phase permits it

            code = country_code.strip().upper()
            if participant.country_code != code:
                raise ForbiddenError(
                    f"Country mismatch: participant '{participant.id}' represents {participant.country_code}, not {code}"
                )
            option = next((o for o in self._options_of(book, crisis.id) if o.id == option_id), None)
            if option is None:
                raise InvalidRequestError(f"Option '{option_id}' is not an option of crisis '{crisis.id}'")
            if any(r.country_code == code for r in self._responses_of(book, crisis.id)):
                raise ConflictError(f"{code} has already responded to crisis '{crisis.id}'")

            draft = record.world.model_copy(deep=True)
            country = self._c._country_by_code(draft, code)
            if country is None:  # a seated delegate's country always exists in the world; guard anyway
                raise ConflictError(f"Country {code} is not part of this conference's world")
            change = apply_effects(draft, option.effects)
            problems = validate_world(draft)
            if problems:  # a rule bug must never corrupt the conference's world
                raise RuntimeError("Crisis response would corrupt the world: " + "; ".join(problems))

            response = CrisisResponse(
                crisis_id=crisis.id,
                conference_id=conference_id,
                participant_id=participant.id,
                country_code=code,
                option_id=option.id,
                action_type=option.action_type,
                applied=change.applied,
                created_at=now,
            )
            phase = record.conference.current_phase.value
            pending: list[DiplomacyEvent] = []
            self._event(
                draft,
                pending,
                now,
                CRISIS_RESPONSE_EVENT,
                country.id,
                None,
                f"{country.name} ({participant.name}) responded to '{crisis.title}': {option.title}.",
                {
                    "conference_id": conference_id,
                    "crisis_id": crisis.id,
                    "response_id": response.id,
                    "option_id": option.id,
                    "action_type": option.action_type.value,
                    "participant_id": participant.id,
                    "country_code": code,
                    "phase": phase,
                },
            )
            if change.changed:
                self._event(
                    draft,
                    pending,
                    now,
                    WORLD_STATE_CHANGED_EVENT,
                    country.id,
                    None,
                    f"World metrics changed after {country.name}'s response to '{crisis.title}': "
                    f"{_signed(change.applied)}.",
                    {
                        "conference_id": conference_id,
                        "crisis_id": crisis.id,
                        "response_id": response.id,
                        "source": CRISIS_RESPONSE_EVENT,
                        "before": change.before,
                        "after": change.after,
                        "applied": change.applied,
                    },
                )
            draft.events.extend(pending)

            record.world = draft  # commit: world and response together
            book.responses.append(response)
            return CrisisRespondResult(
                response=response.model_copy(deep=True),
                crisis=self._view(book, crisis),
                mun_metrics=draft.mun_metrics.model_copy(deep=True),
            )

    def resolve(self, crisis_id: str, participant_id: str) -> CrisisView:
        """A JURY member closes an ACTIVE crisis (RESOLVED) and a `crisis_resolved` event is emitted.

        The outcome is worked out from the head-count of responses alone. Resolving changes no metric itself: the
        consequences were already applied, response by response.
        """
        with self._c._lock:
            record, book, index = self._find(crisis_id)
            conference_id = record.conference.id
            self._admin(record, participant_id, "resolve crises")

            now = self._c._clock()
            self._sync(record, now)
            crisis = book.crises[index]
            self._require_active(crisis, "resolved")
            self._c.check_action(conference_id, ActionType.CRISIS_RESPONSE.value)  # ACTIVE + the phase permits it

            responses = self._responses_of(book, crisis.id)
            delegates = sum(1 for p in record.participants if p.role is ParticipantRole.PARTICIPANT and p.country_code)
            outcome = outcome_for(len(responses), delegates)
            net: dict[str, float] = {}
            for r in responses:
                for name, delta in r.applied.items():
                    net[name] = round(net.get(name, 0.0) + delta, 6)
            chosen: dict[str, int] = {}
            for r in responses:
                chosen[r.action_type.value] = chosen.get(r.action_type.value, 0) + 1

            closed = close_crisis(crisis, CrisisEndReason.RESOLVED, now, outcome)
            world = record.world
            pending: list[DiplomacyEvent] = []
            self._event(
                world,
                pending,
                now,
                CRISIS_RESOLVED_EVENT,
                conference_id,
                None,
                f"Crisis '{crisis.title}' resolved: {outcome.value.replace('_', ' ').lower()} "
                f"({len(responses)} of {delegates} delegates responded).",
                {
                    "conference_id": conference_id,
                    "crisis_id": crisis.id,
                    "status": closed.status.value,
                    "outcome": outcome.value,
                    "participant_id": participant_id,
                    "responses": len(responses),
                    "delegates": delegates,
                    "actions_chosen": chosen,
                    "net_effects": net,
                    "phase": record.conference.current_phase.value,
                },
            )

            book.crises[index] = closed  # nothing above can fail: both commits happen together
            world.events.extend(pending)
            return self._view(book, closed)

    # --- reads ---------------------------------------------------------------------------------
    def get(self, crisis_id: str) -> CrisisView:
        """A crisis with its options and responses. Readable in any conference state, including COMPLETED."""
        with self._c._lock:
            record, book, index = self._find(crisis_id)
            self._sync(record, self._c._clock())
            return self._view(book, book.crises[index])

    def list_crises(self, conference_id: str, status: Optional[CrisisStatus] = None) -> list[CrisisView]:
        """The conference's crises, oldest first, optionally filtered by status."""
        with self._c._lock:
            record = self._c._get(conference_id)
            self._sync(record, self._c._clock())
            book = self._book(record)
            return [self._view(book, c) for c in book.crises if status is None or c.status is status]

    def preview_option(self, crisis_id: str, option_id: str) -> CrisisPreview:
        """What an option would do to the conference's metrics right now, WITHOUT doing it.

        Read-only: the world, the crisis and the event log are untouched. This is what a later advisor can use to
        recommend a response; it has no way to apply one.
        """
        with self._c._lock:
            record, book, _ = self._find(crisis_id)
            self._sync(record, self._c._clock())
            option = next((o for o in self._options_of(book, crisis_id) if o.id == option_id), None)
            if option is None:
                raise InvalidRequestError(f"Option '{option_id}' is not an option of crisis '{crisis_id}'")
            change = project_effects(record.world.mun_metrics, option.effects)
            return CrisisPreview(
                crisis_id=crisis_id,
                option_id=option.id,
                action_type=option.action_type,
                effects=dict(option.effects),
                current=change.before,
                projected=change.after,
                applied=change.applied,
            )

    @staticmethod
    def templates() -> list[CrisisTemplate]:
        """The ready-made crises the backend knows."""
        return [t.model_copy(deep=True) for t in CRISIS_TEMPLATES.values()]

    def clear(self) -> None:
        """Forget every crisis (used by tests; `ConferenceService.clear()` also invalidates them by itself)."""
        with self._c._lock:
            self._books.clear()


# Single shared instance used by the API; it works on the shared conference service's records.
crisis_service = CrisisService(conference_service)