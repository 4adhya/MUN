"""Phase 8: MUN-specific interests and red lines for the country agents.

`country_agent.COUNTRY_PROFILES` already holds each country's personality and goals (used by the world-simulation
agent). Conference diplomacy needs two more things: what a delegation is NOT prepared to accept (red lines) and what
it wants out of a committee (priorities). They live here, next to the existing profiles, instead of changing the
frozen `AgentProfile`. A country without an entry here simply has no recorded red lines; nothing is invented.

These are fictional simulation positions written for game play, not statements of real government policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ai.country_agent import COUNTRY_PROFILES, AgentProfile


@dataclass(frozen=True)
class MunProfile:
    country_id: str
    priorities: tuple[str, ...] = ()
    red_lines: tuple[str, ...] = ()


MUN_PROFILES: dict[str, MunProfile] = {
    "india": MunProfile(
        "india",
        priorities=("Strategic autonomy", "Energy and economic security", "Inclusive, development-first outcomes"),
        red_lines=(
            "No binding measure that dictates India's foreign or trade policy.",
            "No unilateral coercion presented as collective action.",
        ),
    ),
    "china": MunProfile(
        "china",
        priorities=("Sovereignty and non-interference", "Supply-chain resilience", "Multilateral process through the UN"),
        red_lines=(
            "No language that licenses interference in a state's internal affairs.",
            "No sanctions or trade restrictions that target China's critical supply chains.",
        ),
    ),
    "united-states": MunProfile(
        "united-states",
        priorities=("Alliance credibility", "Technology and economic security", "Enforceable commitments"),
        red_lines=(
            "No text that weakens commitments to treaty allies.",
            "No outcome that constrains US technology or export controls without reciprocity.",
        ),
    ),
    "france": MunProfile(
        "france",
        priorities=("Multilateral coordination", "European and partner alignment", "Negotiated, proportionate pressure"),
        red_lines=(
            "No text that bypasses the committee's agreed procedure.",
            "No measure that splits European partners.",
        ),
    ),
    "united-kingdom": MunProfile(
        "united-kingdom",
        priorities=("Maritime and trade security", "Partner coordination", "Credible, flexible diplomacy"),
        red_lines=(
            "No outcome that endangers key trade routes or maritime security.",
            "No text that undermines close security partners.",
        ),
    ),
    "russia": MunProfile(
        "russia",
        priorities=("Sovereignty and strategic autonomy", "Sanctions relief and trade resilience", "Preserving negotiating leverage"),
        red_lines=(
            "No resolution that authorises coercive measures against Russia.",
            "No language that isolates Russia diplomatically without negotiation.",
        ),
    ),
    "japan": MunProfile(
        "japan",
        priorities=("Rules-based order", "Critical supply chains and technology", "Calibrated, predictable responses"),
        red_lines=(
            "No text that endangers critical imports or supply chains.",
            "No escalation without clear, rule-based justification.",
        ),
    ),
    "brazil": MunProfile(
        "brazil",
        priorities=("Agricultural trade access", "Dialogue across blocs", "Development and economic sovereignty"),
        red_lines=(
            "No measure that closes agricultural export markets.",
            "No text that forces Brazil to choose one diplomatic bloc.",
        ),
    ),
}


def agent_profile_for(country_id: str) -> Optional[AgentProfile]:
    """The existing AgentProfile for a simulated country id, or None if it has none."""
    return COUNTRY_PROFILES.get(country_id) or COUNTRY_PROFILES.get(country_id.replace("_", "-"))


def mun_profile_for(country_id: str) -> MunProfile:
    """Priorities and red lines for a country; an empty profile (no red lines recorded) when there is none."""
    return MUN_PROFILES.get(country_id) or MUN_PROFILES.get(country_id.replace("_", "-")) or MunProfile(country_id)