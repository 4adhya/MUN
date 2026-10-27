"""Phase 6: resolutions, clauses, amendments and voting (in-memory, on top of `ConferenceService`).

Resolutions and votes are stored on the conference record (`record.resolutions`, `record.votes`), so they share its
lock, its clock and its lifetime, and `ConferenceService.clear()` forgets them with everything else. This module never
re-implements a gate: membership comes from `ConferenceService._member`, and the phase gate is the same
`check_action` every other phase-restricted action passes through.

What each action needs (checked in this order; a rejected request stores nothing and emits nothing):

    404 unknown resolution / conference          403 not in the conference, or not a PARTICIPANT delegate
    409 conference not ACTIVE, or the phase does not permit the action (RESOLUTION_EDIT, AMENDMENT or VOTE)
    403 not a sponsor (edit, amend, submit) / wrong country (vote)
    409 the resolution is in the wrong status          422 the content is invalid

    create / sign / submit / clause edits ... RESOLUTION_EDIT  (UNMODERATED_CAUCUS, DRAFTING)
    amend ................................... AMENDMENT        (DRAFTING)
    vote .................................... VOTE             (VOTING)

Status flow (see `mun.resolutions`): DRAFT -> SUBMITTED -> [UNDER_REVIEW] -> VOTING -> PASSED | FAILED.

The vote is run by the backend, never by an AI:

  * Voting OPENS by itself: the first time anything touches a SUBMITTED or UNDER_REVIEW resolution while the
    conference is in its VOTING phase (or later), it becomes VOTING. DRAFT resolutions are never put to a vote.
  * It CLOSES when every seated delegate has voted, or when the conference leaves the VOTING phase (any delegate who
    never voted is then "absent"). A submitted resolution that was never voted on fails with an empty tally.
  * The result is `mun.voting.tally(votes, eligible countries, the committee's voting_rules)`: integer arithmetic on
    the recorded votes and the committee's configured rules, nothing else. Free text is never read.

Like negotiations, these transitions are applied lazily: every read or write of a resolution first brings it up to
date with the conference's phase, so nothing depends on a background job. Events are appended to the conference's
world (`resolution_*` and `vote_cast`) and are never removed.

Out of scope here (later phases): crisis logic, scoring, persistence, AI agents. A passed resolution records its
result and emits its event; it does not change the world.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import ValidationError

from .conference_service import (
    ConferenceRecord,
    ConferenceService,
    ForbiddenError,
    InvalidRequestError,
    conference_service,
)
from .models import Country, DiplomacyEvent
from .mun import (
    AMENDABLE_STATUSES,
    EDITABLE_STATUSES,
    PHASE_ORDER,
    ActionType,
    Amendment,
    AmendmentAction,
    ClauseType,
    ConferencePhase,
    ConferenceStatus,
    Participant,
    ParticipantRole,
    Resolution,
    ResolutionStateError,
    ResolutionStatus,
    Vote,
    VoteChoice,
    operative_count,
    tally,
)
from .mun.models import new_id
from .mun.resolutions import (
    find_clause,
    with_amendment,
    with_clause_added,
    with_clause_changed,
    with_clause_removed,
    with_signatory,
    with_status,
)
from .resolution_schemas import ResolutionView, VoteResponse
from .rules import ConflictError, NotFoundError

RESOLUTION_CREATED_EVENT = "resolution_created"
CLAUSE_ADDED_EVENT = "resolution_clause_added"
CLAUSE_UPDATED_EVENT = "resolution_clause_updated"
CLAUSE_REMOVED_EVENT = "resolution_clause_removed"
AMENDED_EVENT = "resolution_amended"
SIGNED_EVENT = "resolution_signed"
SUBMITTED_EVENT = "resolution_submitted"
UNDER_REVIEW_EVENT = "resolution_under_review"
VOTING_OPENED_EVENT = "resolution_voting_opened"
VOTE_CAST_EVENT = "vote_cast"
RESULT_EVENT = "resolution_result"

_VOTING_INDEX = PHASE_ORDER.index(ConferencePhase.VOTING)


def _problems(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())


class ResolutionService:
    def __init__(self, conferences: ConferenceService) -> None:
        self._c = conferences

    # --- helpers -------------------------------------------------------------------------------
    def _find(self, resolution_id: str) -> tuple[ConferenceRecord, int]:
        for record in self._c._records.values():
            for index, resolution in enumerate(record.resolutions):
                if resolution.id == resolution_id:
                    return record, index
        raise NotFoundError(f"Resolution '{resolution_id}' not found")

    @staticmethod
    def _delegate_codes(record: ConferenceRecord) -> list[str]:
        """The countries entitled to vote: every seated PARTICIPANT delegate."""
        return sorted(
            p.country_code for p in record.participants if p.role is ParticipantRole.PARTICIPANT and p.country_code
        )

    @staticmethod
    def _votes_for(record: ConferenceRecord, resolution_id: str) -> list[Vote]:
        return [v for v in record.votes if v.resolution_id == resolution_id]

    @staticmethod
    def _event(
        record: ConferenceRecord,
        pending: list[DiplomacyEvent],
        now: datetime,
        type_: str,
        message: str,
        effects: dict[str, Any],
        actor: Optional[Country] = None,
    ) -> None:
        """Build an event and queue it in `pending`; the caller appends the queue to the world when it commits.

        The actor is the acting country, or the conference itself for events the backend raises on its own
        (voting opened, final result), as `conference_start` does.
        """
        world = record.world
        pending.append(
            DiplomacyEvent(
                id=len(world.events) + len(pending) + 1,
                turn=world.turn,
                type=type_,
                actor=actor.id if actor is not None else record.conference.id,
                target=None,
                message=message,
                timestamp=now,
                effects={
                    "conference_id": record.conference.id,
                    "phase": record.conference.current_phase.value,
                    **effects,
                },
            )
        )

    def _view(self, record: ConferenceRecord, resolution: Resolution) -> ResolutionView:
        votes = [v.model_dump() for v in self._votes_for(record, resolution.id)]
        return ResolutionView.model_validate({**resolution.model_dump(), "votes": votes})

    # --- lazy transitions: opening and closing the vote ----------------------------------------
    def _decide(
        self, record: ConferenceRecord, resolution: Resolution, votes: list[Vote], now: datetime, pending: list[DiplomacyEvent]
    ) -> Resolution:
        """The VOTING resolution after the official tally: PASSED or FAILED, with its result. Queues the result event."""
        result = tally(votes, self._delegate_codes(record), record.config.voting_rules)
        status = ResolutionStatus.PASSED if result.passed else ResolutionStatus.FAILED
        decided = with_status(resolution, status, now, result=result)
        self._event(
            record,
            pending,
            now,
            RESULT_EVENT,
            f"Resolution '{resolution.title}' {status.value}: {result.reason}",
            {
                "resolution_id": resolution.id,
                "status": status.value,
                "passed": result.passed,
                "yes": result.yes,
                "no": result.no,
                "abstain": result.abstain,
                "absent": result.absent,
                "eligible": result.eligible,
                "counted": result.counted,
                "required_yes": result.required_yes,
                "vetoed_by": list(result.vetoed_by),
                "reason": result.reason,
            },
        )
        return decided

    def _sync(self, record: ConferenceRecord, now: datetime) -> None:
        """Bring every resolution up to date with the conference's phase (open the vote, close the vote)."""
        if record.world is None or not record.resolutions:
            return
        conference = record.conference
        closed = conference.status is ConferenceStatus.COMPLETED or PHASE_ORDER.index(conference.current_phase) > _VOTING_INDEX
        open_now = conference.status is ConferenceStatus.ACTIVE and conference.current_phase is ConferencePhase.VOTING
        if not (open_now or closed):
            return
        pending: list[DiplomacyEvent] = []
        updated = list(record.resolutions)
        for index, resolution in enumerate(updated):
            if resolution.status in AMENDABLE_STATUSES:
                resolution = with_status(resolution, ResolutionStatus.VOTING, now)
                self._event(
                    record,
                    pending,
                    now,
                    VOTING_OPENED_EVENT,
                    f"Voting opened on resolution '{resolution.title}'.",
                    {"resolution_id": resolution.id, "status": ResolutionStatus.VOTING.value},
                )
            if closed and resolution.status is ResolutionStatus.VOTING:
                resolution = self._decide(record, resolution, self._votes_for(record, resolution.id), now, pending)
            updated[index] = resolution
        if pending:  # nothing above can fail half-way: commit together
            record.resolutions = updated
            record.world.events.extend(pending)

    # --- shared preamble of the participant actions --------------------------------------------
    def _begin(
        self, resolution_id: str, participant_id: str, action: ActionType, *, sponsors_only: bool
    ) -> tuple[ConferenceRecord, int, Resolution, Participant, Country, datetime]:
        record, index = self._find(resolution_id)
        now = self._c._clock()
        self._sync(record, now)
        participant = self._delegate(record, participant_id, action)
        resolution = record.resolutions[index]
        country = self._c._country_by_code(record.world, participant.country_code)
        if country is None:  # a started conference seats every delegate; guard anyway
            raise ConflictError(f"Participant '{participant.id}' has no country in this conference")
        if sponsors_only and participant.country_code not in resolution.sponsors:
            raise ForbiddenError(
                f"Only a sponsor can do this: {participant.country_code} does not sponsor resolution '{resolution.id}'"
            )
        return record, index, resolution, participant, country, now

    def _delegate(self, record: ConferenceRecord, participant_id: str, action: ActionType) -> Participant:
        """403 unless the participant is a delegate of this conference; 409 unless the phase permits `action`."""
        participant = self._c._member(record, participant_id)
        if participant.role is not ParticipantRole.PARTICIPANT:
            raise ForbiddenError(f"{participant.role.value} participants cannot do this; only PARTICIPANT delegates can")
        self._c.check_action(record.conference.id, action.value)  # ACTIVE + the phase permits `action`
        return participant

    @staticmethod
    def _require_status(resolution: Resolution, allowed: frozenset[ResolutionStatus], doing: str, hint: str = "") -> None:
        if resolution.status not in allowed:
            wanted = " or ".join(sorted(s.value for s in allowed))
            raise ConflictError(
                f"Cannot {doing}: resolution '{resolution.id}' is {resolution.status.value}, not {wanted}. {hint}".strip()
            )

    # --- create, clauses -----------------------------------------------------------------------
    def create_resolution(
        self, conference_id: str, participant_id: str, title: str, sponsors: list[str]
    ) -> ResolutionView:
        """A delegate drafts a new resolution (status DRAFT). The creator's own country is always its first sponsor."""
        with self._c._lock:
            record = self._c._get(conference_id)
            now = self._c._clock()
            self._sync(record, now)
            participant = self._delegate(record, participant_id, ActionType.RESOLUTION_EDIT)
            country = self._c._country_by_code(record.world, participant.country_code)
            if country is None:
                raise ConflictError(f"Participant '{participant.id}' has no country in this conference")

            seated = set(self._delegate_codes(record))
            codes = list(dict.fromkeys([participant.country_code, *(c.strip().upper() for c in sponsors)]))
            unseated = [c for c in codes if c not in seated]
            if unseated:
                raise InvalidRequestError(
                    f"Sponsor(s) {', '.join(unseated)} are not represented by a delegate in this conference"
                )
            try:
                resolution = Resolution(
                    conference_id=conference_id,
                    title=title,
                    created_by=participant.id,
                    sponsors=codes,
                    created_at=now,
                    updated_at=now,
                )
            except ValidationError as exc:
                raise InvalidRequestError(f"Invalid resolution: {_problems(exc)}") from None

            pending: list[DiplomacyEvent] = []
            self._event(
                record,
                pending,
                now,
                RESOLUTION_CREATED_EVENT,
                f"{country.name} ({participant.name}) started drafting resolution '{resolution.title}'.",
                {"resolution_id": resolution.id, "status": resolution.status.value, "sponsors": codes},
                actor=country,
            )
            record.resolutions.append(resolution)
            record.world.events.extend(pending)
            return self._view(record, resolution)

    def add_clause(self, resolution_id: str, participant_id: str, clause_type: ClauseType, text: str) -> ResolutionView:
        with self._c._lock:
            record, index, resolution, participant, country, now = self._begin(
                resolution_id, participant_id, ActionType.RESOLUTION_EDIT, sponsors_only=True
            )
            self._require_status(resolution, EDITABLE_STATUSES, "add a clause", "A submitted resolution changes only by amendment.")
            try:
                updated, clause = with_clause_added(resolution, ClauseType(clause_type), text, participant.id, now)
            except ValidationError as exc:
                raise InvalidRequestError(f"Invalid clause: {_problems(exc)}") from None
            pending: list[DiplomacyEvent] = []
            self._event(
                record,
                pending,
                now,
                CLAUSE_ADDED_EVENT,
                f"{country.name} added {clause.type.value.lower()} clause {clause.number} to '{resolution.title}'.",
                {
                    "resolution_id": resolution.id,
                    "clause_id": clause.id,
                    "number": clause.number,
                    "clause_type": clause.type.value,
                    "participant_id": participant.id,
                    "characters": len(clause.text),
                },
                actor=country,
            )
            record.resolutions[index] = updated
            record.world.events.extend(pending)
            return self._view(record, updated)

    def update_clause(
        self,
        resolution_id: str,
        clause_id: str,
        participant_id: str,
        text: Optional[str] = None,
        clause_type: Optional[ClauseType] = None,
    ) -> ResolutionView:
        with self._c._lock:
            record, index, resolution, participant, country, now = self._begin(
                resolution_id, participant_id, ActionType.RESOLUTION_EDIT, sponsors_only=True
            )
            self._require_status(resolution, EDITABLE_STATUSES, "edit a clause", "A submitted resolution changes only by amendment.")
            if find_clause(resolution, clause_id) is None:
                raise NotFoundError(f"Clause '{clause_id}' not found in resolution '{resolution_id}'")
            if text is None and clause_type is None:
                raise InvalidRequestError("Give a new text, a new type or both")
            try:
                updated, clause = with_clause_changed(
                    resolution, clause_id, text, ClauseType(clause_type) if clause_type is not None else None, now
                )
            except ValidationError as exc:
                raise InvalidRequestError(f"Invalid clause: {_problems(exc)}") from None
            pending: list[DiplomacyEvent] = []
            self._event(
                record,
                pending,
                now,
                CLAUSE_UPDATED_EVENT,
                f"{country.name} changed clause {clause.number} of '{resolution.title}'.",
                {
                    "resolution_id": resolution.id,
                    "clause_id": clause.id,
                    "number": clause.number,
                    "clause_type": clause.type.value,
                    "participant_id": participant.id,
                    "characters": len(clause.text),
                },
                actor=country,
            )
            record.resolutions[index] = updated
            record.world.events.extend(pending)
            return self._view(record, updated)

    def remove_clause(self, resolution_id: str, clause_id: str, participant_id: str) -> ResolutionView:
        with self._c._lock:
            record, index, resolution, participant, country, now = self._begin(
                resolution_id, participant_id, ActionType.RESOLUTION_EDIT, sponsors_only=True
            )
            self._require_status(resolution, EDITABLE_STATUSES, "remove a clause", "A submitted resolution changes only by amendment.")
            if find_clause(resolution, clause_id) is None:
                raise NotFoundError(f"Clause '{clause_id}' not found in resolution '{resolution_id}'")
            updated, removed = with_clause_removed(resolution, clause_id, now)
            pending: list[DiplomacyEvent] = []
            self._event(
                record,
                pending,
                now,
                CLAUSE_REMOVED_EVENT,
                f"{country.name} removed {removed.type.value.lower()} clause {removed.number} from '{resolution.title}'.",
                {
                    "resolution_id": resolution.id,
                    "clause_id": removed.id,
                    "number": removed.number,
                    "clause_type": removed.type.value,
                    "participant_id": participant.id,
                },
                actor=country,
            )
            record.resolutions[index] = updated
            record.world.events.extend(pending)
            return self._view(record, updated)

    # --- amend, sign, submit, review -----------------------------------------------------------
    def amend(
        self,
        resolution_id: str,
        participant_id: str,
        action: AmendmentAction,
        clause_id: Optional[str] = None,
        clause_type: Optional[ClauseType] = None,
        text: Optional[str] = None,
    ) -> ResolutionView:
        """A sponsor amends a SUBMITTED or UNDER_REVIEW resolution during DRAFTING.

        The amendment is a "friendly amendment": applied at once and kept in `amendments` with the text it replaced.
        An amendment may never leave the resolution without an operative clause.
        """
        with self._c._lock:
            record, index, resolution, participant, country, now = self._begin(
                resolution_id, participant_id, ActionType.AMENDMENT, sponsors_only=True
            )
            action = AmendmentAction(action)
            self._require_status(
                resolution,
                AMENDABLE_STATUSES,
                "amend",
                "A DRAFT is edited through its clauses; a resolution that is voting or decided can no longer change.",
            )
            try:
                if action is AmendmentAction.ADD:
                    if clause_type is None or text is None:
                        raise InvalidRequestError("An ADD amendment needs a type and a text")
                    amendment = Amendment(
                        resolution_id=resolution.id,
                        proposed_by=participant.id,
                        country_code=participant.country_code,
                        action=action,
                        clause_id=new_id("clause"),
                        clause_type=ClauseType(clause_type),
                        text=text,
                        created_at=now,
                    )
                else:
                    clause = find_clause(resolution, clause_id or "")
                    if clause is None:
                        raise NotFoundError(f"Clause '{clause_id}' not found in resolution '{resolution_id}'")
                    if action is AmendmentAction.MODIFY:
                        new_text = text if text is not None else clause.text
                        new_type = ClauseType(clause_type) if clause_type is not None else clause.type
                        if new_text.strip() == clause.text and new_type is clause.type:
                            raise InvalidRequestError("The amendment changes nothing")
                        if new_type is not clause.type and clause.type is ClauseType.OPERATIVE and operative_count(resolution) == 1:
                            raise InvalidRequestError("An amendment cannot leave the resolution without an operative clause")
                    else:
                        new_text, new_type = None, clause.type
                        if clause.type is ClauseType.OPERATIVE and operative_count(resolution) == 1:
                            raise InvalidRequestError("An amendment cannot remove the last operative clause")
                    amendment = Amendment(
                        resolution_id=resolution.id,
                        proposed_by=participant.id,
                        country_code=participant.country_code,
                        action=action,
                        clause_id=clause.id,
                        clause_type=new_type,
                        text=new_text,
                        previous_text=clause.text,
                        created_at=now,
                    )
                updated = with_amendment(resolution, amendment, now)
            except ValidationError as exc:
                raise InvalidRequestError(f"Invalid amendment: {_problems(exc)}") from None

            pending: list[DiplomacyEvent] = []
            self._event(
                record,
                pending,
                now,
                AMENDED_EVENT,
                f"{country.name} amended '{resolution.title}' ({action.value} clause).",
                {
                    "resolution_id": resolution.id,
                    "amendment_id": amendment.id,
                    "action": action.value,
                    "clause_id": amendment.clause_id,
                    "clause_type": amendment.clause_type.value,
                    "participant_id": participant.id,
                    "country_code": participant.country_code,
                    "status": updated.status.value,
                },
                actor=country,
            )
            record.resolutions[index] = updated
            record.world.events.extend(pending)
            return self._view(record, updated)

    def sign(self, resolution_id: str, participant_id: str) -> ResolutionView:
        """A delegate who is not a sponsor signs in support. Signing does not grant the right to edit."""
        with self._c._lock:
            record, index, resolution, participant, country, now = self._begin(
                resolution_id, participant_id, ActionType.RESOLUTION_EDIT, sponsors_only=False
            )
            self._require_status(
                resolution,
                frozenset({ResolutionStatus.DRAFT, ResolutionStatus.SUBMITTED, ResolutionStatus.UNDER_REVIEW}),
                "sign",
            )
            code = participant.country_code
            if code in resolution.sponsors:
                raise ConflictError(f"{code} already sponsors resolution '{resolution.id}'")
            if code in resolution.signatories:
                raise ConflictError(f"{code} has already signed resolution '{resolution.id}'")
            updated = with_signatory(resolution, code, now)
            pending: list[DiplomacyEvent] = []
            self._event(
                record,
                pending,
                now,
                SIGNED_EVENT,
                f"{country.name} signed resolution '{resolution.title}'.",
                {"resolution_id": resolution.id, "participant_id": participant.id, "country_code": code},
                actor=country,
            )
            record.resolutions[index] = updated
            record.world.events.extend(pending)
            return self._view(record, updated)

    def submit(self, resolution_id: str, participant_id: str) -> ResolutionView:
        """A sponsor submits a DRAFT. It needs at least one operative clause; its text is frozen from then on."""
        with self._c._lock:
            record, index, resolution, participant, country, now = self._begin(
                resolution_id, participant_id, ActionType.RESOLUTION_EDIT, sponsors_only=True
            )
            self._require_status(resolution, EDITABLE_STATUSES, "submit")
            if operative_count(resolution) == 0:
                raise InvalidRequestError("A resolution needs at least one operative clause before it can be submitted")
            updated = with_status(resolution, ResolutionStatus.SUBMITTED, now)
            pending: list[DiplomacyEvent] = []
            self._event(
                record,
                pending,
                now,
                SUBMITTED_EVENT,
                f"{country.name} submitted resolution '{resolution.title}' with {len(resolution.clauses)} clause(s).",
                {
                    "resolution_id": resolution.id,
                    "status": updated.status.value,
                    "participant_id": participant.id,
                    "clauses": len(resolution.clauses),
                    "sponsors": list(resolution.sponsors),
                    "signatories": list(resolution.signatories),
                },
                actor=country,
            )
            record.resolutions[index] = updated
            record.world.events.extend(pending)
            return self._view(record, updated)

    def review(self, resolution_id: str) -> ResolutionView:
        """The chair takes a SUBMITTED resolution under review (like advancing the phase, no participant is named)."""
        with self._c._lock:
            record, index = self._find(resolution_id)
            now = self._c._clock()
            self._sync(record, now)
            self._c._require_active(record, "review a resolution")
            resolution = record.resolutions[index]
            self._require_status(resolution, frozenset({ResolutionStatus.SUBMITTED}), "review")
            try:
                updated = with_status(resolution, ResolutionStatus.UNDER_REVIEW, now)
            except ResolutionStateError as exc:
                raise ConflictError(str(exc)) from None
            pending: list[DiplomacyEvent] = []
            self._event(
                record,
                pending,
                now,
                UNDER_REVIEW_EVENT,
                f"Resolution '{resolution.title}' is under review.",
                {"resolution_id": resolution.id, "status": updated.status.value},
            )
            record.resolutions[index] = updated
            record.world.events.extend(pending)
            return self._view(record, updated)

    # --- voting --------------------------------------------------------------------------------
    def vote(self, resolution_id: str, participant_id: str, country_code: str, choice: VoteChoice) -> VoteResponse:
        """A delegate votes YES, NO or ABSTAIN for their own country. A vote is final: it cannot be changed.

        Checked in this order: 404 resolution; 403 participant not in the resolution's conference or not a delegate;
        409 conference not ACTIVE / phase is not VOTING; 403 country is not the participant's seat; 409 the resolution
        is not open for voting; 409 the country already voted. When the last delegate votes, the vote closes at once
        and the response carries the official result.
        """
        with self._c._lock:
            record, index = self._find(resolution_id)
            now = self._c._clock()
            self._sync(record, now)
            participant = self._delegate(record, participant_id, ActionType.VOTE)
            code = country_code.strip().upper()
            if participant.country_code != code:
                raise ForbiddenError(
                    f"Country mismatch: participant '{participant.id}' represents {participant.country_code}, not {code}"
                )
            resolution = record.resolutions[index]
            if resolution.status is not ResolutionStatus.VOTING:
                raise ConflictError(
                    f"Resolution '{resolution.id}' is {resolution.status.value}, not open for voting. "
                    "Only a VOTING resolution can be voted on."
                )
            if any(v.resolution_id == resolution.id and v.country_code == code for v in record.votes):
                raise ConflictError(f"{code} has already voted on resolution '{resolution.id}'; a vote cannot be changed")
            country = self._c._country_by_code(record.world, code)
            if country is None:
                raise ConflictError(f"Country {code} is not part of this conference's world")

            try:
                vote = Vote(
                    resolution_id=resolution.id,
                    conference_id=record.conference.id,
                    participant_id=participant.id,
                    country_code=code,
                    choice=choice,
                    phase=record.conference.current_phase,
                    cast_at=now,
                )
            except ValidationError as exc:
                raise InvalidRequestError(f"Invalid vote: {_problems(exc)}") from None

            pending: list[DiplomacyEvent] = []
            self._event(
                record,
                pending,
                now,
                VOTE_CAST_EVENT,
                f"{country.name} ({participant.name}) voted {vote.choice.value} on resolution '{resolution.title}'.",
                {
                    "resolution_id": resolution.id,
                    "vote_id": vote.id,
                    "participant_id": participant.id,
                    "country_code": code,
                    "vote": vote.choice.value,
                },
                actor=country,
            )
            votes = [*self._votes_for(record, resolution.id), vote]
            updated = resolution
            if {v.country_code for v in votes} >= set(self._delegate_codes(record)):  # everyone has voted: close
                updated = self._decide(record, resolution, votes, now, pending)

            record.votes.append(vote)  # nothing above can fail: all commits happen together
            record.resolutions[index] = updated
            record.world.events.extend(pending)
            return VoteResponse(
                vote=vote.model_copy(deep=True), resolution_status=updated.status, result=updated.result
            )

    # --- reads ---------------------------------------------------------------------------------
    def get(self, resolution_id: str) -> ResolutionView:
        """The resolution, its roll call and (once decided) its official result. Readable in any conference state."""
        with self._c._lock:
            record, index = self._find(resolution_id)
            self._sync(record, self._c._clock())
            return self._view(record, record.resolutions[index])

    def list_resolutions(self, conference_id: str, status: Optional[ResolutionStatus] = None) -> list[ResolutionView]:
        """The conference's resolutions, oldest first, optionally filtered by status."""
        with self._c._lock:
            record = self._c._get(conference_id)
            self._sync(record, self._c._clock())
            return [self._view(record, r) for r in record.resolutions if status is None or r.status is status]


# Single shared instance used by the API; it works on the shared conference service's records.
resolution_service = ResolutionService(conference_service)