"""MUN domain layer: conferences, participants, committees and MUN world metrics.

Sits on top of the geopolitical simulation (backend.models / rules / simulation)
and never replaces it. Nothing in this package imports the simulation.
"""
from .committees import COMMITTEE_CONFIGS, CommitteeConfig, UnknownCommitteeError, get_committee_config
from .enums import Committee, ConferencePhase, ConferenceStatus, ParticipantRole
from .metrics import MUNWorldMetrics
from .models import Conference, Participant
from .negotiations import (
    ACTION_OUTCOME,
    FINAL_STATUSES,
    MAX_PROPOSAL_CHARS,
    NEGOTIATION_TTL_SECONDS,
    Negotiation,
    NegotiationAction,
    NegotiationStateError,
    NegotiationStatus,
    apply_response,
    default_expiry,
    expire,
    expire_reason,
    is_finalized,
    should_expire,
)
from .phases import (
    COMPLETED_STEP,
    PHASE_ACTIONS,
    PHASE_DURATION_SECONDS,
    PHASE_ORDER,
    REQUIRED_PHASES,
    ActionType,
    InvalidTransitionError,
    allowed_actions,
    check_transition,
    is_action_allowed,
    next_phase,
    phase_deadline,
)
from .speeches import MAX_SPEECH_CHARS, NoSpeakersRemainingError, SpeakerState, Speech, open_floor, pass_floor

__all__ = [
    "ACTION_OUTCOME",
    "COMMITTEE_CONFIGS",
    "COMPLETED_STEP",
    "FINAL_STATUSES",
    "MAX_PROPOSAL_CHARS",
    "MAX_SPEECH_CHARS",
    "NEGOTIATION_TTL_SECONDS",
    "PHASE_ACTIONS",
    "PHASE_DURATION_SECONDS",
    "PHASE_ORDER",
    "REQUIRED_PHASES",
    "ActionType",
    "InvalidTransitionError",
    "Committee",
    "CommitteeConfig",
    "Conference",
    "ConferencePhase",
    "ConferenceStatus",
    "MUNWorldMetrics",
    "Negotiation",
    "NegotiationAction",
    "NegotiationStateError",
    "NegotiationStatus",
    "NoSpeakersRemainingError",
    "Participant",
    "ParticipantRole",
    "SpeakerState",
    "Speech",
    "UnknownCommitteeError",
    "allowed_actions",
    "apply_response",
    "check_transition",
    "default_expiry",
    "expire",
    "expire_reason",
    "get_committee_config",
    "is_action_allowed",
    "is_finalized",
    "next_phase",
    "open_floor",
    "pass_floor",
    "phase_deadline",
    "should_expire",
]