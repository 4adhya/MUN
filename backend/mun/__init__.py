"""MUN domain layer: conferences, participants, committees and MUN world metrics.

Sits on top of the geopolitical simulation (backend.models / rules / simulation)
and never replaces it. Nothing in this package imports the simulation.
"""
from .committees import COMMITTEE_CONFIGS, CommitteeConfig, UnknownCommitteeError, get_committee_config
from .enums import Committee, ConferencePhase, ConferenceStatus, ParticipantRole
from .metrics import MUNWorldMetrics
from .models import Conference, Participant
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
    "COMMITTEE_CONFIGS",
    "COMPLETED_STEP",
    "MAX_SPEECH_CHARS",
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
    "NoSpeakersRemainingError",
    "Participant",
    "ParticipantRole",
    "SpeakerState",
    "Speech",
    "UnknownCommitteeError",
    "allowed_actions",
    "check_transition",
    "get_committee_config",
    "is_action_allowed",
    "next_phase",
    "open_floor",
    "pass_floor",
    "phase_deadline",
]