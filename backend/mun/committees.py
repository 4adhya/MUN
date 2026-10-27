"""Committee configuration.

Committee behaviour is data, not code: add a committee by adding an enum value
and an entry in `COMMITTEE_CONFIGS`, not by branching elsewhere in the app.
Phase 6 adds `voting_rules` (majority type, abstention behaviour, veto) to each config; the tally that applies
them lives in `mun.voting`.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import Committee, ConferencePhase
from .voting import AbstentionBehavior, MajorityType, VotingRules


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
        description="Minimum fraction of votes in favour for a motion to pass (inclusive). `voting_rules` is what the tally applies.",
    )
    voting_rules: VotingRules = Field(
        default_factory=VotingRules,
        description="How votes become an outcome: majority type, abstention behaviour and veto (see mun.voting)",
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

    @model_validator(mode="after")
    def _rules_match_threshold(self) -> "CommitteeConfig":
        rules = self.voting_rules
        if rules.majority is MajorityType.QUALIFIED and rules.threshold != self.voting_threshold:
            raise ValueError("a QUALIFIED voting rule must use the committee's voting_threshold")
        return self


_ALL_PHASES = list(ConferencePhase)

# The five permanent members of the UN Security Council. Only they hold a veto, and only UNSC enables it.
UNSC_PERMANENT_MEMBERS = ("CN", "FR", "GB", "RU", "US")

COMMITTEE_CONFIGS: dict[Committee, CommitteeConfig] = {
    Committee.UNSC: CommitteeConfig(
        committee=Committee.UNSC,
        topic="Threats to International Peace and Security",
        max_delegates=15,
        voting_threshold=0.6,  # 9 of 15
        # Nine affirmative votes of the members, no veto: a NO from a permanent member kills the resolution, but a
        # permanent member's ABSTENTION (or absence) does not. Abstentions and absences count toward the 15, so they
        # cannot help a resolution reach nine.
        voting_rules=VotingRules(
            majority=MajorityType.QUALIFIED,
            threshold=0.6,
            abstention=AbstentionBehavior.COUNTS_AGAINST,
            absent_counts_against=True,
            veto_enabled=True,
            veto_members=UNSC_PERMANENT_MEMBERS,
        ),
        allowed_phases=_ALL_PHASES,
    ),
    Committee.GLOBAL_CYBERSECURITY: CommitteeConfig(
        committee=Committee.GLOBAL_CYBERSECURITY,
        topic="Global Cybersecurity Crisis",
        max_delegates=30,
        voting_threshold=0.5,
        # Simple majority of the delegates present and voting: abstentions and absences are ignored, no veto.
        voting_rules=VotingRules(majority=MajorityType.SIMPLE, abstention=AbstentionBehavior.IGNORED),
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