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

Nothing here handles speeches, negotiations, resolutions, voting, crisis or persistence (later phases).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Optional

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
)
from .report_schemas import SimulationReport
from .report_service import build_report
from .rules import ActionError, ConflictError, NotFoundError, validate_world
from .simulation import create_initial_world

CONFERENCE_START_EVENT = "conference_start"


class InvalidRequestError(ActionError):
    """The request is well-formed but its content is not acceptable (HTTP 422)."""

    status_code = 422


@dataclass
class ConferenceRecord:
    conference: Conference
    config: CommitteeConfig
    participants: list[Participant] = field(default_factory=list)
    world: Optional[WorldState] = None


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
    def __init__(self) -> None:
        self._records: dict[str, ConferenceRecord] = {}
        self._lock = RLock()  # FastAPI runs sync routes in a thread pool

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

            record.participants = seated
            record.world = world
            record.conference = conference
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
            record.conference = Conference.model_validate(payload)  # validated before it replaces the old one
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
        """Forget every conference (used by tests)."""
        with self._lock:
            self._records.clear()


# Single shared instance used by the API.
conference_service = ConferenceService()