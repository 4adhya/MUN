"""Phase 2: in-memory conference service (create, join, view, start).

Each conference owns its participants and, once started, its OWN copy of the geopolitical world
(built with the existing `create_initial_world()`), so conferences never interfere with each other
or with the sandbox world behind `/world` and `/actions/*`. Country seats come from that world's
existing country data; there is no second country list.

Country seats are validated against the existing country registry (`country_registry`): a delegate may ask
for a seat by name, slug or ISO code, which must resolve to a country of the simulation and must not already
be held by another participant. Delegates who ask for nothing are seated automatically when the conference starts.

The phase flow, per-phase action permissions and deadlines live in `mun.phases`; the service only applies them.
The backend owns the authoritative phase: it advances one valid step at a time, never to a phase a client names.

Phase 4 adds speeches and the speaker queue. Every conference record keeps its speeches (an append-only history that
later AI agents can read) and a `SpeakerState`. The queue is rebuilt by the service whenever the conference enters a
phase, so it can never disagree with the authoritative phase. A speech passes through the `check_action` gate like
any other phase-restricted action, and emits a `speech_submitted` event into the conference's world.

Phase 5 adds negotiations between delegates. Every conference record keeps its negotiations (an append-only history
that later AI agents can read). Proposing and answering both pass the same `check_action(NEGOTIATION)` gate, so they
work only in the phases `mun.phases` permits (UNMODERATED_CAUCUS and CRISIS). Each important step (proposed, accepted,
rejected, countered, expired) is recorded as an event in the conference's world. An answer changes the diplomatic
relationship between the two countries only through the deterministic rules in `negotiation_rules.py`, never from the
proposal text. A PENDING negotiation expires lazily: whenever the service touches negotiations (and when the phase
advances) it first expires every one whose time is up or whose phase no longer permits negotiating.

Phase 6 adds resolutions and voting. Their data lives on the conference record too (`resolutions` and `votes`, both
append-only histories), but ALL of their rules live in `resolution_service.py`, which works on these records through
this service's helpers (`_get`, `_member`, `check_action`) so that it never duplicates a gate.

Nothing here handles crisis logic, scoring or persistence (later phases).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Optional

from pydantic import ValidationError

from .conference_schemas import (
    ActionCheckResponse,
    AssignedCountry,
    CommitteeConfigView,
    ConferenceSnapshot,
    ConferenceWorldView,
    ParticipantView,
)
from .country_registry import find_world_country, resolve_country
from .models import Country, DiplomacyEvent, WorldState
from .mun import (
    COMPLETED_STEP,
    ActionType,
    Committee,
    CommitteeConfig,
    Conference,
    ConferencePhase,
    ConferenceStatus,
    MUNWorldMetrics,
    Participant,
    ParticipantRole,
    UnknownCommitteeError,
    allowed_actions,
    check_transition,
    get_committee_config,
    InvalidTransitionError,
    is_action_allowed,
    next_phase,
    phase_deadline,
    NoSpeakersRemainingError,
    SpeakerState,
    Speech,
    open_floor,
    pass_floor,
    Negotiation,
    NegotiationAction,
    NegotiationStateError,
    NegotiationStatus,
    Resolution,
    Vote,
    apply_response,
    default_expiry,
    expire,
    expire_reason,
    is_finalized,
)
from .negotiation_rules import apply_negotiation_outcome
from .persistence.service import NullPersistenceService, compute_scores as persistence_compute_scores
from .report_schemas import SimulationReport
from .report_service import build_report
from .rules import ActionError, ConflictError, NotFoundError, validate_world
from .simulation import create_initial_world
from .speech_schemas import SpeakerEntry, SpeakerQueueView

CONFERENCE_START_EVENT = "conference_start"
SPEECH_EVENT = "speech_submitted"
NEGOTIATION_PROPOSED_EVENT = "negotiation_proposed"
NEGOTIATION_EXPIRED_EVENT = "negotiation_expired"


class InvalidRequestError(ActionError):
    """The request is well-formed but its content is not acceptable (HTTP 422)."""

    status_code = 422


class ForbiddenError(ActionError):
    """The participant is not allowed to do this in this conference (HTTP 403)."""

    status_code = 403


@dataclass
class ConferenceRecord:
    conference: Conference
    config: CommitteeConfig
    participants: list[Participant] = field(default_factory=list)
    world: Optional[WorldState] = None
    speeches: list[Speech] = field(default_factory=list)  # append-only history; never cleared by phase changes
    speakers: SpeakerState = field(default_factory=SpeakerState)  # rebuilt on every phase change
    negotiations: list[Negotiation] = field(default_factory=list)  # append-only history; entries only change status
    resolutions: list[Resolution] = field(default_factory=list)  # Phase 6; managed only by resolution_service
    votes: list[Vote] = field(default_factory=list)  # Phase 6; append-only, never edited or withdrawn


def resolve_seat(identifier: str) -> Country:
    """The simulated country a delegate asked for, resolved through the country registry.

    Accepts any identifier the registry understands (name, slug, ISO alpha-2/alpha-3/numeric code, any case).
    Raises InvalidRequestError (422) if it is not a country at all, or a real country this simulation does not seat.
    """
    seat_world = create_initial_world()
    country = find_world_country(seat_world, identifier)
    if country is not None and country.country_code:
        return country
    if resolve_country(identifier) is not None:
        available = ", ".join(c.name for c in seat_world.countries if c.country_code)
        raise InvalidRequestError(
            f"Country '{identifier}' is not available in this simulation. Available countries: {available}"
        )
    raise InvalidRequestError(f"Unknown country '{identifier}': it is not a recognised country")


def assign_countries(participants: list[Participant], countries: list[Country]) -> list[Participant]:
    """Seat every PARTICIPANT without a country, deterministically.

    Delegates are seated in the order given (join order) on the countries in the order given (the
    world's country order). A country is never given twice. Returns new Participant objects;
    the inputs are not modified.
    """
    seats = [c for c in countries if c.country_code]
    held = [p.country_code for p in participants if p.country_code]
    if len(held) != len(set(held)):
        raise ConflictError("Duplicate country assignment: two participants already hold the same country")
    seat_codes = {c.country_code for c in seats}
    invalid = sorted(code for code in held if code not in seat_codes)
    if invalid:  # a held seat must be a country of this world; never start with an unknown one
        raise InvalidRequestError(
            f"Invalid country assignment: {', '.join(invalid)} is not a country of this simulation"
        )

    free = [c for c in seats if c.country_code not in set(held)]
    needing = [p for p in participants if p.role is ParticipantRole.PARTICIPANT and not p.country_code]
    if len(needing) > len(free):
        raise InvalidRequestError(
            f"No available country: {len(needing)} delegate(s) need a seat but only {len(free)} "
            f"of the {len(seats)} configured countries are available"
        )

    seat_iter = iter(free)
    seated: list[Participant] = []
    for participant in participants:
        if participant in needing:
            seated.append(participant.model_copy(update={"country_code": next(seat_iter).country_code}))
        else:
            seated.append(participant.model_copy())
    return seated


class ConferenceService:
    def __init__(self, clock: Optional[Callable[[], datetime]] = None) -> None:
        self._records: dict[str, ConferenceRecord] = {}
        self._lock = RLock()  # FastAPI runs sync routes in a thread pool
        # The clock negotiations use for creation, answers and expiry (tests replace it to move time).
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(timezone.utc))
        # Phase 10 persistence collaborator. Defaults to a no-op so the in-memory behaviour is
        # unchanged until persistence is explicitly attached (set_persistence). This service remains
        # the single state machine; persistence only mirrors the records it already owns.
        self._persistence = NullPersistenceService()

    # --- persistence (Phase 10) ---------------------------------------------------------------
    def set_persistence(self, persistence) -> None:
        """Attach a persistence collaborator (PersistenceService) or detach with NullPersistenceService."""
        self._persistence = persistence or NullPersistenceService()

    @property
    def persistence(self):
        return self._persistence

    def _persist(self, record: "ConferenceRecord") -> None:
        """Mirror a record to durable storage. Never raises: a storage error must not break a live op."""
        self._persistence.persist(record)

    def persist_conference(self, conference_id: str) -> None:
        """Persist a conference by id. Used by the resolution/crisis services after they commit changes
        to a shared record, so persistence stays in one place and those services need no storage code."""
        with self._lock:
            record = self._records.get(conference_id)
            if record is not None:
                self._persist(record)

    def load_persisted(self) -> int:
        """Rehydrate every persisted conference into memory (used at startup / after a restart).

        Records already in memory win (the live state machine is authoritative); only conferences
        that are not currently loaded are restored. Returns how many were restored.
        """
        with self._lock:
            restored = 0
            for record in self._persistence.restore_records():
                cid = record.conference.id
                if cid not in self._records:
                    self._records[cid] = record
                    restored += 1
            return restored

    def get_scores(self, conference_id: str) -> list[dict]:
        """Deterministic delegate scores for a conference, derived from its recorded event history."""
        with self._lock:
            record = self._get(conference_id)
            return persistence_compute_scores(record)

    # --- helpers -------------------------------------------------------------------------------
    def _get(self, conference_id: str) -> ConferenceRecord:
        record = self._records.get(conference_id)
        if record is None:
            raise NotFoundError(f"Conference '{conference_id}' not found")
        return record

    @staticmethod
    def _require_waiting(record: ConferenceRecord, action: str) -> None:
        status = record.conference.status
        if status is ConferenceStatus.WAITING:
            return
        if status is ConferenceStatus.COMPLETED:
            raise ConflictError(f"Conference '{record.conference.id}' is already completed; cannot {action}")
        if status in (ConferenceStatus.ACTIVE, ConferenceStatus.PAUSED):
            raise ConflictError(f"Conference '{record.conference.id}' has already started; cannot {action}")
        raise ConflictError(f"Conference '{record.conference.id}' is {status.value}; cannot {action}")

    @staticmethod
    def _require_active(record: ConferenceRecord, action: str) -> None:
        """Phases only move, and phase actions only run, while the conference STATUS is ACTIVE."""
        status = record.conference.status
        if status is ConferenceStatus.ACTIVE:
            return
        conference_id = record.conference.id
        if status is ConferenceStatus.WAITING:
            raise ConflictError(f"Conference '{conference_id}' has not started; start it before you {action}")
        if status is ConferenceStatus.COMPLETED:
            raise ConflictError(f"Conference '{conference_id}' is already completed; cannot {action}")
        raise ConflictError(f"Conference '{conference_id}' is {status.value}; cannot {action}")

    @staticmethod
    def _snapshot(record: ConferenceRecord) -> ConferenceSnapshot:
        conference, world = record.conference, record.world
        if world is not None:
            seat_countries = world.countries
        elif any(p.country_code for p in record.participants):
            seat_countries = create_initial_world().countries  # seats already requested, before the world exists
        else:
            seat_countries = []
        countries = {c.country_code: c for c in seat_countries if c.country_code}

        participants = []
        assigned = []
        for p in record.participants:
            country = countries.get(p.country_code) if p.country_code else None
            participants.append(
                ParticipantView(
                    id=p.id,
                    name=p.name,
                    role=p.role,
                    country_code=p.country_code,
                    country_name=country.name if country else None,
                    score=p.score,
                    joined_at=p.joined_at,
                )
            )
            if country is not None:
                assigned.append(
                    AssignedCountry(
                        country_code=country.country_code,
                        country_id=country.id,
                        country_name=country.name,
                        flag=country.flag,
                        participant_id=p.id,
                        participant_name=p.name,
                    )
                )

        world_view = None
        if world is not None:
            world_view = ConferenceWorldView(
                turn=world.turn,
                countries=world.countries,
                trade_routes=world.trade_routes,
                events=world.events,
                mun_metrics=world.mun_metrics,
            ).model_copy(deep=True)

        return ConferenceSnapshot(
            id=conference.id,
            name=conference.name,
            committee=conference.committee.value,
            topic=conference.topic,
            status=conference.status,
            current_phase=conference.current_phase,
            created_at=conference.created_at,
            phase_started_at=conference.phase_started_at,
            phase_ends_at=conference.phase_ends_at,
            config=CommitteeConfigView(
                max_delegates=record.config.max_delegates,
                voting_threshold=record.config.voting_threshold,
                allowed_phases=record.config.allowed_phases,
            ),
            participant_count=len(record.participants),
            participants=participants,
            assigned_countries=assigned,
            world=world_view,
            next_phase=ConferenceService._next_step(record),
            allowed_actions=(
                [a.value for a in ActionType if a in allowed_actions(conference.current_phase)]
                if conference.status is ConferenceStatus.ACTIVE
                else []
            ),
        )

    @staticmethod
    def _next_step(record: ConferenceRecord) -> Optional[str]:
        """The next valid step (phase name or COMPLETED) while ACTIVE, else None."""
        if record.conference.status is not ConferenceStatus.ACTIVE:
            return None
        following = next_phase(record.conference.current_phase, record.config.allowed_phases)
        return following.value if following is not None else COMPLETED_STEP

    @staticmethod
    def _open_floor(participants: list[Participant], phase: ConferencePhase) -> SpeakerState:
        """The speaker state for `phase`: every seated delegate, in join order (empty if the phase has no speeches)."""
        delegates = [p.id for p in participants if p.role is ParticipantRole.PARTICIPANT and p.country_code]
        return open_floor(phase, delegates)

    @staticmethod
    def _speaker_entry(record: ConferenceRecord, participant_id: str) -> SpeakerEntry:
        participant = next(p for p in record.participants if p.id == participant_id)
        country = None
        if record.world is not None and participant.country_code:
            country = next((c for c in record.world.countries if c.country_code == participant.country_code), None)
        return SpeakerEntry(
            participant_id=participant.id,
            participant_name=participant.name,
            country_code=participant.country_code,
            country_name=country.name if country else None,
        )

    @staticmethod
    def _speaker_view(record: ConferenceRecord) -> SpeakerQueueView:
        conference, state = record.conference, record.speakers
        phase_permits = is_action_allowed(conference.current_phase, ActionType.SPEECH)
        return SpeakerQueueView(
            conference_id=conference.id,
            status=conference.status,
            phase=conference.current_phase,
            speaking_open=conference.status is ConferenceStatus.ACTIVE and phase_permits,
            current_speaker=(
                ConferenceService._speaker_entry(record, state.current) if state.current is not None else None
            ),
            queue=[ConferenceService._speaker_entry(record, pid) for pid in state.queue],
            completed=[ConferenceService._speaker_entry(record, pid) for pid in state.completed],
        )

    # --- operations ----------------------------------------------------------------------------
    def create(self, name: str, committee: str, topic: str) -> ConferenceSnapshot:
        try:
            config = get_committee_config(committee)
        except UnknownCommitteeError:
            valid = ", ".join(c.value for c in Committee)
            raise InvalidRequestError(f"Invalid committee '{committee}'. Valid committees: {valid}") from None

        conference = Conference(name=name, committee=config.committee, topic=topic)
        record = ConferenceRecord(conference=conference, config=config)
        with self._lock:
            self._records[conference.id] = record
            self._persist(record)
            return self._snapshot(record)

    def join(self, conference_id: str, name: str, role: str, country: Optional[str] = None) -> Participant:
        with self._lock:
            record = self._get(conference_id)
            self._require_waiting(record, "join")

            try:
                role_enum = ParticipantRole(role)
            except ValueError:
                valid = ", ".join(r.value for r in ParticipantRole)
                raise InvalidRequestError(f"Invalid role '{role}'. Valid roles: {valid}") from None

            seat: Optional[Country] = None
            if country is not None:
                if role_enum is not ParticipantRole.PARTICIPANT:
                    raise InvalidRequestError(
                        f"Only PARTICIPANT delegates can request a country; {role_enum.value} has no seat"
                    )
                seat = resolve_seat(country)
                if any(p.country_code == seat.country_code for p in record.participants):
                    raise ConflictError(f"{seat.name} is already assigned to another participant in this conference")

            limit = record.config.max_delegates
            is_delegate = role_enum is ParticipantRole.PARTICIPANT
            same_kind = sum(1 for p in record.participants if (p.role is ParticipantRole.PARTICIPANT) == is_delegate)
            if same_kind >= limit:
                kind = "delegate" if is_delegate else "guest/jury"
                raise ConflictError(
                    f"Participant limit reached: {record.conference.committee.value} allows at most {limit} {kind}s"
                )

            participant = Participant(
                name=name,
                role=role_enum,
                conference_id=conference_id,
                country_code=seat.country_code if seat else None,
            )
            record.participants.append(participant)
            self._persist(record)
            return participant.model_copy(deep=True)

    def get(self, conference_id: str) -> ConferenceSnapshot:
        with self._lock:
            return self._snapshot(self._get(conference_id))

    def start(self, conference_id: str) -> ConferenceSnapshot:
        with self._lock:
            record = self._get(conference_id)
            self._require_waiting(record, "start")

            if not any(p.role is ParticipantRole.PARTICIPANT for p in record.participants):
                raise ConflictError("Cannot start conference: at least one PARTICIPANT (delegate) must join first")

            # Everything is built on local copies and committed last, so a failure changes nothing.
            world = create_initial_world()  # the existing geopolitical world, private to this conference
            seated = assign_countries(record.participants, world.countries)
            world.mun_metrics = MUNWorldMetrics()  # initial MUN metrics (the defaults)

            now = datetime.now(timezone.utc)
            delegates = [p for p in seated if p.country_code]
            world.events.append(
                DiplomacyEvent(
                    id=len(world.events) + 1,
                    turn=world.turn,
                    type=CONFERENCE_START_EVENT,
                    actor=record.conference.id,
                    target=None,
                    message=(
                        f"Conference '{record.conference.name}' ({record.conference.committee.value}) started "
                        f"with {len(delegates)} delegate(s) seated."
                    ),
                    timestamp=now,
                    effects={
                        "committee": record.conference.committee.value,
                        "assigned_countries": [p.country_code for p in delegates],
                    },
                )
            )
            problems = validate_world(world)
            if problems:
                raise RuntimeError("Conference world is inconsistent: " + "; ".join(problems))

            first_phase = next_phase(record.conference.current_phase, record.config.allowed_phases)  # LOBBY -> ROLL_CALL
            conference = Conference.model_validate(
                {
                    **record.conference.model_dump(),
                    "status": ConferenceStatus.ACTIVE,
                    "current_phase": first_phase,
                    "phase_started_at": now,
                    "phase_ends_at": phase_deadline(first_phase, now),
                }
            )

            speakers = self._open_floor(seated, conference.current_phase)

            record.participants = seated
            record.world = world
            record.conference = conference
            record.speakers = speakers
            self._persist(record)
            return self._snapshot(record)

    def advance(self, conference_id: str, to_phase: Optional[str] = None) -> ConferenceSnapshot:
        """Move the conference ONE valid step forward. The backend picks the step; `to_phase` can only confirm it.

        After RESULTS the next step is completion: the STATUS becomes COMPLETED and the phase stays RESULTS.
        A rejected request changes nothing.
        """
        with self._lock:
            record = self._get(conference_id)
            self._require_active(record, "advance its phase")
            current = record.conference.current_phase
            allowed = record.config.allowed_phases

            target = next_phase(current, allowed)
            if to_phase is not None:  # a client's claim is verified against the state machine, never obeyed
                if to_phase == COMPLETED_STEP:
                    requested: Optional[ConferencePhase] = None
                else:
                    try:
                        requested = ConferencePhase(to_phase)
                    except ValueError:
                        valid = ", ".join([p.value for p in ConferencePhase] + [COMPLETED_STEP])
                        raise InvalidRequestError(f"Invalid phase '{to_phase}'. Valid values: {valid}") from None
                try:
                    check_transition(current, requested, allowed)
                except InvalidTransitionError as exc:
                    raise ConflictError(str(exc)) from None

            payload = record.conference.model_dump()
            if target is None:  # RESULTS is done: complete the conference (status), keep the phase
                payload.update({"status": ConferenceStatus.COMPLETED, "phase_ends_at": None})
            else:
                now = datetime.now(timezone.utc)
                payload.update(
                    {"current_phase": target, "phase_started_at": now, "phase_ends_at": phase_deadline(target, now)}
                )
            conference = Conference.model_validate(payload)  # validated before it replaces the old one
            # The speaker queue follows the phase: rebuilt on entering a speaking phase, emptied otherwise
            # (including on completion). Computed before anything is committed.
            speakers = (
                self._open_floor(record.participants, conference.current_phase)
                if target is not None
                else SpeakerState()
            )
            record.conference = conference
            record.speakers = speakers
            self._expire_stale_negotiations(record, self._clock())  # offers the new phase no longer permits
            self._persist(record)
            return self._snapshot(record)

    def check_action(self, conference_id: str, action: str) -> ActionCheckResponse:
        """The gate every phase-restricted action will pass through. Allows or refuses; performs nothing.

        404 unknown conference, 422 unknown action type, 409 if the conference is not ACTIVE or the current
        phase does not permit the action.
        """
        with self._lock:
            record = self._get(conference_id)
            try:
                action_type = ActionType(action)
            except ValueError:
                valid = ", ".join(a.value for a in ActionType)
                raise InvalidRequestError(f"Invalid action '{action}'. Valid actions: {valid}") from None

            self._require_active(record, f"perform {action_type.value}")
            phase = record.conference.current_phase
            if not is_action_allowed(phase, action_type):
                permitted = ", ".join(a.value for a in ActionType if a in allowed_actions(phase)) or "none"
                raise ConflictError(
                    f"{action_type.value} is not allowed during {phase.value}. Allowed in this phase: {permitted}"
                )
            return ActionCheckResponse(conference_id=conference_id, action=action_type.value, phase=phase)

    # --- Phase 4: speeches and the speaker queue -----------------------------------------------
    def submit_speech(self, conference_id: str, participant_id: str, country_code: str, text: str) -> Speech:
        """Record a speech by the delegate holding the floor, and emit a `speech_submitted` event.

        Checked in this order; a rejected request stores nothing and emits nothing:
          404 unknown conference
          403 the participant is not in this conference, or is not a PARTICIPANT delegate (GUEST/JURY cannot speak)
          409 the conference is not ACTIVE, or the current phase does not permit SPEECH (the Phase 3 gate)
          403 `country_code` is not the country the participant was assigned
          409 the participant does not hold the floor
          422 the speech itself is invalid (blank, too long)
        The phase stored on the speech is always the conference's own current phase; clients cannot choose it.
        """
        with self._lock:
            record = self._get(conference_id)
            participant = next((p for p in record.participants if p.id == participant_id), None)
            if participant is None or participant.conference_id != conference_id:
                raise ForbiddenError(f"Participant '{participant_id}' does not belong to conference '{conference_id}'")
            if participant.role is not ParticipantRole.PARTICIPANT:
                raise ForbiddenError(
                    f"{participant.role.value} participants cannot give speeches; only PARTICIPANT delegates can"
                )

            self.check_action(conference_id, ActionType.SPEECH.value)  # ACTIVE + the phase permits SPEECH

            code = country_code.strip().upper()
            if participant.country_code != code:
                raise ForbiddenError(
                    f"Country mismatch: participant '{participant.id}' represents {participant.country_code}, "
                    f"not {code}"
                )
            if record.speakers.current != participant.id:
                holder = (
                    self._speaker_entry(record, record.speakers.current) if record.speakers.current is not None else None
                )
                floor = f"{holder.country_name or holder.country_code} ({holder.participant_name})" if holder else "nobody"
                raise ConflictError(f"It is not your turn to speak: the floor is held by {floor}")

            world = record.world
            country = next((c for c in world.countries if c.country_code == code), None)
            if country is None:  # a seated delegate's country always exists in the world; guard anyway
                raise ConflictError(f"Country {code} is not part of this conference's world")

            now = datetime.now(timezone.utc)
            phase = record.conference.current_phase
            try:
                speech = Speech(
                    conference_id=conference_id,
                    participant_id=participant.id,
                    country_code=code,
                    text=text,
                    phase=phase,
                    created_at=now,
                )
            except ValidationError as exc:
                problems = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
                raise InvalidRequestError(f"Invalid speech: {problems}") from None

            event = DiplomacyEvent(
                id=len(world.events) + 1,
                turn=world.turn,
                type=SPEECH_EVENT,
                actor=country.id,
                target=None,
                message=f"{country.name} ({participant.name}) delivered a speech during {phase.value}.",
                timestamp=now,
                effects={
                    "conference_id": conference_id,
                    "speech_id": speech.id,
                    "participant_id": participant.id,
                    "country_code": code,
                    "phase": phase.value,
                    "characters": len(speech.text),
                },
            )

            record.speeches.append(speech)  # nothing below can fail: both commits happen together
            world.events.append(event)
            self._persistence.append_event(conference_id, event)
            self._persist(record)
            return speech.model_copy(deep=True)

    def get_speeches(
        self,
        conference_id: str,
        phase: Optional[ConferencePhase] = None,
        country_code: Optional[str] = None,
    ) -> list[Speech]:
        """The conference's speech history, oldest first, optionally filtered by phase and/or country.

        Returns copies, so callers (the API, later AI agents) can never alter the stored history. Readable in any
        conference state, including COMPLETED.
        """
        with self._lock:
            record = self._get(conference_id)
            code = country_code.strip().upper() if country_code else None
            return [
                s.model_copy(deep=True)
                for s in record.speeches
                if (phase is None or s.phase is phase) and (code is None or s.country_code == code)
            ]

    def get_speakers(self, conference_id: str) -> SpeakerQueueView:
        """Who holds the floor and who is waiting. Always readable; empty when no speaking phase is open."""
        with self._lock:
            return self._speaker_view(self._get(conference_id))

    def next_speaker(self, conference_id: str) -> SpeakerQueueView:
        """End the current speaker's turn and give the floor to the next delegate (the chair's "next speaker").

        404 unknown conference; 409 if the conference is not ACTIVE, the phase has no speaker queue, or every
        delegate has already had a turn. A rejected request changes nothing.
        """
        with self._lock:
            record = self._get(conference_id)
            self._require_active(record, "move to the next speaker")
            phase = record.conference.current_phase
            if not is_action_allowed(phase, ActionType.SPEECH):
                raise ConflictError(f"There is no speaker queue during {phase.value}: speeches are not allowed in it")
            try:
                new_state = pass_floor(record.speakers)
            except NoSpeakersRemainingError as exc:
                raise ConflictError(str(exc)) from None
            record.speakers = new_state
            return self._speaker_view(record)

    # --- Phase 5: negotiations -----------------------------------------------------------------
    @staticmethod
    def _country_by_code(world: WorldState, code: str) -> Optional[Country]:
        return next((c for c in world.countries if c.country_code == code), None)

    def _expire_stale_negotiations(self, record: ConferenceRecord, now: datetime) -> None:
        """Expire every PENDING negotiation whose time is up or whose phase no longer permits negotiating.

        Records one `negotiation_expired` event each. Idempotent (an EXPIRED negotiation is final and is never
        expired twice) and it cannot fail half-way: every event is built before anything is stored.
        """
        world = record.world
        if world is None or not record.negotiations:
            return
        phase = record.conference.current_phase
        changes: list[tuple[int, Negotiation, DiplomacyEvent]] = []
        for index, negotiation in enumerate(record.negotiations):
            reason = expire_reason(negotiation, now, phase)
            if reason is None:
                continue
            proposer = self._country_by_code(world, negotiation.proposer)
            receiver = self._country_by_code(world, negotiation.receiver)
            proposer_name = proposer.name if proposer else negotiation.proposer
            receiver_name = receiver.name if receiver else negotiation.receiver
            event = DiplomacyEvent(
                id=len(world.events) + len(changes) + 1,
                turn=world.turn,
                type=NEGOTIATION_EXPIRED_EVENT,
                actor=proposer.id if proposer else negotiation.proposer,
                target=receiver.id if receiver else negotiation.receiver,
                message=(
                    f"{proposer_name}'s proposal to {receiver_name} expired unanswered "
                    f"({'the phase no longer permits negotiation' if reason == 'phase_closed' else 'time ran out'})."
                ),
                timestamp=now,
                effects={
                    "conference_id": record.conference.id,
                    "negotiation_id": negotiation.id,
                    "proposer": negotiation.proposer,
                    "receiver": negotiation.receiver,
                    "status": NegotiationStatus.EXPIRED.value,
                    "reason": reason,
                    "phase": phase.value,
                    "relationship_changed": False,
                },
            )
            changes.append((index, expire(negotiation), event))
        for index, expired, event in changes:  # nothing above can fail: commit together
            record.negotiations[index] = expired
            world.events.append(event)

    def _find_negotiation(self, negotiation_id: str) -> tuple[ConferenceRecord, int]:
        for record in self._records.values():
            for index, negotiation in enumerate(record.negotiations):
                if negotiation.id == negotiation_id:
                    return record, index
        raise NotFoundError(f"Negotiation '{negotiation_id}' not found")

    @staticmethod
    def _member(record: ConferenceRecord, participant_id: str) -> Participant:
        participant = next((p for p in record.participants if p.id == participant_id), None)
        if participant is None or participant.conference_id != record.conference.id:
            raise ForbiddenError(
                f"Participant '{participant_id}' does not belong to conference '{record.conference.id}'"
            )
        return participant

    def propose_negotiation(
        self, conference_id: str, participant_id: str, receiver: str, proposal: str
    ) -> Negotiation:
        """A delegate proposes something to another delegate's country, and a `negotiation_proposed` event is emitted.

        Checked in this order; a rejected request stores nothing and emits nothing:
          404 unknown conference
          403 the participant is not in this conference, or is not a PARTICIPANT delegate (GUEST/JURY cannot negotiate)
          409 the conference is not ACTIVE, or the current phase does not permit NEGOTIATION (the Phase 3 gate)
          422 the receiver is the proposer's own country, or is not seated with a delegate in this conference
          422 the proposal itself is invalid (blank, too long)
        The proposer is always the participant's own country and the phase is always the conference's current phase;
        clients cannot choose either. The negotiation starts PENDING and expires after NEGOTIATION_TTL_SECONDS.
        """
        with self._lock:
            record = self._get(conference_id)
            participant = self._member(record, participant_id)
            if participant.role is not ParticipantRole.PARTICIPANT:
                raise ForbiddenError(
                    f"{participant.role.value} participants cannot negotiate; only PARTICIPANT delegates can"
                )

            now = self._clock()
            self._expire_stale_negotiations(record, now)
            self.check_action(conference_id, ActionType.NEGOTIATION.value)  # ACTIVE + the phase permits NEGOTIATION

            world = record.world
            code = receiver.strip().upper()
            proposer_country = self._country_by_code(world, participant.country_code) if participant.country_code else None
            if proposer_country is None:  # a started conference seats every delegate; guard anyway
                raise ConflictError(f"Participant '{participant.id}' has no country in this conference")
            if code == participant.country_code:
                raise InvalidRequestError("A country cannot negotiate with itself")
            holder = next(
                (p for p in record.participants if p.role is ParticipantRole.PARTICIPANT and p.country_code == code),
                None,
            )
            receiver_country = self._country_by_code(world, code)
            if holder is None or receiver_country is None:
                raise InvalidRequestError(
                    f"Country {code} is not represented by a delegate in this conference, so it cannot receive proposals"
                )

            phase = record.conference.current_phase
            try:
                negotiation = Negotiation(
                    conference_id=conference_id,
                    proposer=participant.country_code,
                    receiver=code,
                    proposal=proposal,
                    created_at=now,
                    expires_at=default_expiry(now),
                    proposer_participant_id=participant.id,
                    receiver_participant_id=holder.id,
                    phase=phase,
                )
            except ValidationError as exc:
                problems = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
                raise InvalidRequestError(f"Invalid negotiation: {problems}") from None

            event = DiplomacyEvent(
                id=len(world.events) + 1,
                turn=world.turn,
                type=NEGOTIATION_PROPOSED_EVENT,
                actor=proposer_country.id,
                target=receiver_country.id,
                message=(
                    f"{proposer_country.name} ({participant.name}) proposed a negotiation to "
                    f"{receiver_country.name} during {phase.value}."
                ),
                timestamp=now,
                effects={
                    "conference_id": conference_id,
                    "negotiation_id": negotiation.id,
                    "proposer": negotiation.proposer,
                    "receiver": negotiation.receiver,
                    "status": NegotiationStatus.PENDING.value,
                    "phase": phase.value,
                    "expires_at": negotiation.expires_at.isoformat(),
                    "characters": len(negotiation.proposal),
                },
            )

            record.negotiations.append(negotiation)  # nothing below can fail: both commits happen together
            world.events.append(event)
            self._persistence.append_event(conference_id, event)
            self._persist(record)
            return negotiation.model_copy(deep=True)

    def respond_negotiation(
        self,
        negotiation_id: str,
        participant_id: str,
        action: NegotiationAction,
        counter_offer: Optional[str] = None,
    ) -> Negotiation:
        """The receiving delegate accepts, rejects or counters a PENDING negotiation.

        Checked in this order; a rejected request changes nothing (except that stale negotiations are expired first,
        which is just time having passed):
          404 unknown negotiation
          403 the participant is not in the negotiation's conference, or is not the delegate it was addressed to
              (this includes the proposer answering their own proposal)
          409 the negotiation is already final (answered, countered or expired)
          409 the conference is not ACTIVE, or the current phase does not permit NEGOTIATION (the Phase 3 gate)
          422 COUNTER without a counter-offer, or an ACCEPT/REJECT carrying one
        ACCEPT / REJECT / COUNTER finalize the negotiation, record an event and move the two countries' (symmetric)
        relationship by the fixed amount `negotiation_rules` defines for that outcome. The proposal text is never
        interpreted. The world is updated on a scratch copy and only committed once it validates.
        """
        with self._lock:
            record, index = self._find_negotiation(negotiation_id)
            conference_id = record.conference.id
            participant = self._member(record, participant_id)
            negotiation = record.negotiations[index]
            if participant.role is not ParticipantRole.PARTICIPANT or participant.id != negotiation.receiver_participant_id:
                if participant.id == negotiation.proposer_participant_id:
                    raise ForbiddenError(
                        f"You cannot answer your own proposal; only the delegate for {negotiation.receiver} can"
                    )
                raise ForbiddenError(
                    f"Only the delegate representing {negotiation.receiver} can answer negotiation '{negotiation.id}'"
                )

            now = self._clock()
            self._expire_stale_negotiations(record, now)
            negotiation = record.negotiations[index]  # may just have expired
            if is_finalized(negotiation):
                raise ConflictError(
                    f"Negotiation '{negotiation.id}' is already {negotiation.status.value} "
                    "and can no longer be answered"
                )
            self.check_action(conference_id, ActionType.NEGOTIATION.value)  # ACTIVE + the phase permits NEGOTIATION

            try:
                updated = apply_response(negotiation, action, counter_offer, now)
            except NegotiationStateError as exc:
                raise ConflictError(str(exc)) from None
            except ValueError as exc:
                raise InvalidRequestError(str(exc)) from None

            draft = record.world.model_copy(deep=True)
            proposer_country = self._country_by_code(draft, negotiation.proposer)
            receiver_country = self._country_by_code(draft, negotiation.receiver)
            if proposer_country is None or receiver_country is None:
                raise ConflictError("A country of this negotiation is not part of the conference's world")
            result = apply_negotiation_outcome(
                draft, proposer_country.id, receiver_country.id, updated.status, negotiation.id
            )
            problems = validate_world(draft)
            if problems:  # a rule bug must never corrupt the conference's world
                raise RuntimeError("Negotiation would corrupt the world: " + "; ".join(problems))

            draft.events.append(
                DiplomacyEvent(
                    id=len(draft.events) + 1,
                    turn=draft.turn,
                    type=result.type,
                    actor=receiver_country.id,  # the answering country acts; the proposer is the target
                    target=proposer_country.id,
                    message=result.message,
                    timestamp=now,
                    effects={
                        **result.effects,
                        "conference_id": conference_id,
                        "proposer": negotiation.proposer,
                        "receiver": negotiation.receiver,
                        "status": updated.status.value,
                        "phase": record.conference.current_phase.value,
                        "characters": len(updated.counter_offer or ""),
                    },
                )
            )

            record.world = draft  # commit: world and negotiation together
            record.negotiations[index] = updated
            self._persist(record)
            return updated.model_copy(deep=True)

    def get_negotiations(
        self,
        conference_id: str,
        status: Optional[NegotiationStatus] = None,
        country_code: Optional[str] = None,
    ) -> list[Negotiation]:
        """The conference's negotiation history, oldest first, optionally filtered by status and/or country.

        `country_code` matches negotiations the country took part in, as proposer or receiver. Stale negotiations
        are expired first so the statuses returned are current. Returns copies, so callers (the API, later AI
        agents) can never alter the stored history. Readable in any conference state, including COMPLETED.
        """
        with self._lock:
            record = self._get(conference_id)
            self._expire_stale_negotiations(record, self._clock())
            code = country_code.strip().upper() if country_code else None
            return [
                n.model_copy(deep=True)
                for n in record.negotiations
                if (status is None or n.status is status) and (code is None or code in (n.proposer, n.receiver))
            ]

    def report(self, conference_id: str) -> SimulationReport:
        """Report on a started conference's own world. Read-only; 409 until the conference has started."""
        with self._lock:
            record = self._get(conference_id)
            if record.world is None:
                raise ConflictError(
                    f"Conference '{conference_id}' has not started; there is no simulation data to report on"
                )
            return build_report(
                record.world.model_copy(deep=True),
                create_initial_world(),
                conference=record.conference.model_copy(deep=True),
                participants=[p.model_copy(deep=True) for p in record.participants],
            )

    def clear(self) -> None:
        """Forget every conference IN MEMORY (used by tests). Does not touch durable storage."""
        with self._lock:
            self._records.clear()


def stored_to_record(stored) -> ConferenceRecord:
    """Rebuild a live ConferenceRecord from a persisted StoredConference (Phase 10 rehydration).

    Reconstructs the MUN pydantic objects from their stored JSON, re-derives the committee config
    from the conference's committee, and rebuilds the speaker queue for the current phase so the
    restored record behaves exactly like one created in memory. Pure data in, record out.
    """
    conference = Conference.model_validate(stored.conference)
    config = get_committee_config(conference.committee.value)
    participants = [Participant.model_validate(p) for p in stored.participants]
    world = WorldState.model_validate(stored.world) if stored.world is not None else None
    speeches = [Speech.model_validate(s) for s in stored.speeches]
    negotiations = [Negotiation.model_validate(n) for n in stored.negotiations]
    resolutions = [Resolution.model_validate(r) for r in stored.resolutions]
    votes = [Vote.model_validate(v) for v in stored.votes]

    # The speaker queue is derived state: rebuild it for the current phase from the seated delegates,
    # exactly as start()/advance() do, so it can never disagree with the restored phase.
    if conference.status is ConferenceStatus.ACTIVE:
        speakers = ConferenceService._open_floor(participants, conference.current_phase)
    else:
        speakers = SpeakerState()

    return ConferenceRecord(
        conference=conference,
        config=config,
        participants=participants,
        world=world,
        speeches=speeches,
        speakers=speakers,
        negotiations=negotiations,
        resolutions=resolutions,
        votes=votes,
    )


# Single shared instance used by the API.
conference_service = ConferenceService()