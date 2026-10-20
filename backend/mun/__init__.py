"""MUN domain layer: conferences, participants, committees and MUN world metrics.

Sits on top of the geopolitical simulation (backend.models / rules / simulation)
and never replaces it. Nothing in this package imports the simulation.
"""
from .committees import COMMITTEE_CONFIGS, CommitteeConfig, UnknownCommitteeError, get_committee_config
from .enums import Committee, ConferencePhase, ConferenceStatus, ParticipantRole
from .metrics import MUNWorldMetrics
from .models import Conference, Participant

__all__ = [
    "COMMITTEE_CONFIGS",
    "Committee",
    "CommitteeConfig",
    "Conference",
    "ConferencePhase",
    "ConferenceStatus",
    "MUNWorldMetrics",
    "Participant",
    "ParticipantRole",
    "UnknownCommitteeError",
    "get_committee_config",
]