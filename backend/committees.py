"""Committee configuration.

Committee behaviour is data, not code: add a committee by adding an enum value
and an entry in `COMMITTEE_CONFIGS`, not by branching elsewhere in the app.
Committee-specific voting *logic* (vetoes, abstentions) is Phase 5.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import Committee, ConferencePhase


class UnknownCommitteeError(ValueError):
    """Raised when a committee name is not a known Committee."""


class CommitteeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    committee: Committee
    topic: str = Field(min_length=1, max_length=300)
    max_delegates: int = Field(ge=1, le=200, description="Maximum delegates (country seats) in the committee")
    voting_threshold: float = Field(
        gt=0,
        le=1,
        allow_inf_nan=False,
        description="Minimum fraction of votes cast in favour for a motion to pass (inclusive). Refined in Phase 5.",
    )
    allowed_phases: list[ConferencePhase] = Field(
        min_length=1,
        description="Phases this committee may use; transition order is decided in Phase 3",
    )

    @field_validator("allowed_phases")
    @classmethod
    def _unique_phases(cls, phases: list[ConferencePhase]) -> list[ConferencePhase]:
        if len(set(phases)) != len(phases):
            raise ValueError("allowed_phases must not contain duplicates")
        return phases


_ALL_PHASES = list(ConferencePhase)

COMMITTEE_CONFIGS: dict[Committee, CommitteeConfig] = {
    Committee.UNSC: CommitteeConfig(
        committee=Committee.UNSC,
        topic="Threats to International Peace and Security",
        max_delegates=15,
        voting_threshold=0.6,  # 9 of 15
        allowed_phases=_ALL_PHASES,
    ),
    Committee.GLOBAL_CYBERSECURITY: CommitteeConfig(
        committee=Committee.GLOBAL_CYBERSECURITY,
        topic="Global Cybersecurity Crisis",
        max_delegates=30,
        voting_threshold=0.5,
        allowed_phases=_ALL_PHASES,
    ),
}


def get_committee_config(committee: Committee | str) -> CommitteeConfig:
    """Return a copy of the config for `committee`; raise UnknownCommitteeError if unknown."""
    try:
        key = Committee(committee)
    except ValueError:
        raise UnknownCommitteeError(f"Unknown committee: {committee!r}") from None
    return COMMITTEE_CONFIGS[key].model_copy(deep=True)  # copy so callers cannot mutate the registry