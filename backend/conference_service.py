"""Phase 2: in-memory conference service (create, join, view, start).

Each conference owns its participants and, once started, its OWN copy of the geopolitical world
(built with the existing `create_initial_world()`), so conferences never interfere with each other
or with the sandbox world behind `/world` and `/actions/*`. Country seats come from that world's
existing country data; there is no second country list.

Nothing here handles speeches, voting, phase transitions or persistence (later phases).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Optional

from .conference_schemas import (
    AssignedCountry,
    CommitteeConfigView,
    ConferenceSnapshot,
    ConferenceWorldView,
    ParticipantView,
)
from .models import Country, DiplomacyEvent, WorldState
from .mun import (
    Committee,
    CommitteeConfig,
    Conference,
    ConferencePhase,
    ConferenceStatus,
    MUNWorldMetrics,
    Participant,
    ParticipantRole,
    UnknownCommitteeError,
    get_committee_config,
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
    def _snapshot(record: ConferenceRecord) -> ConferenceSnapshot:
        conference, world = record.conference, record.world
        countries = {c.country_code: c for c in world.countries if c.country_code} if world else {}

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
            return self._snapshot(record)

    def join(self, conference_id: str, name: str, role: str) -> Participant:
        with self._lock:
            record = self._get(conference_id)
            self._require_waiting(record, "join")

            try:
                role_enum = ParticipantRole(role)
            except ValueError:
                valid = ", ".join(r.value for r in ParticipantRole)
                raise InvalidRequestError(f"Invalid role '{role}'. Valid roles: {valid}") from None

            limit = record.config.max_delegates
            is_delegate = role_enum is ParticipantRole.PARTICIPANT
            same_kind = sum(1 for p in record.participants if (p.role is ParticipantRole.PARTICIPANT) == is_delegate)
            if same_kind >= limit:
                kind = "delegate" if is_delegate else "guest/jury"
                raise ConflictError(
                    f"Participant limit reached: {record.conference.committee.value} allows at most {limit} {kind}s"
                )

            participant = Participant(name=name, role=role_enum, conference_id=conference_id)
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

            conference = Conference.model_validate(
                {
                    **record.conference.model_dump(),
                    "status": ConferenceStatus.ACTIVE,
                    "current_phase": ConferencePhase.ROLL_CALL,
                    "phase_started_at": now,
                    "phase_ends_at": None,  # phase durations belong to Phase 3
                }
            )

            record.participants = seated
            record.world = world
            record.conference = conference
            return self._snapshot(record)

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