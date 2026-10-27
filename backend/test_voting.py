"""Phase 6: the voting rules and the deterministic tally (pure functions, no API)."""
import inspect
import random
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import backend.mun.voting as voting_module
from backend.mun import (
    COMMITTEE_CONFIGS,
    UNSC_PERMANENT_MEMBERS,
    AbstentionBehavior,
    Committee,
    CommitteeConfig,
    MajorityType,
    VoteChoice,
    VotingError,
    VotingRules,
    required_yes,
    tally,
)

P5 = ["CN", "FR", "GB", "RU", "US"]
OTHERS = ["BR", "DE", "IN", "JP", "KE", "MX", "NG", "PL", "ZA", "EG"]  # ten non-permanent seats (15 with P5)
UNSC15 = P5 + OTHERS

SIMPLE = VotingRules()
SIMPLE_COUNTING_ABSTENTIONS = VotingRules(abstention=AbstentionBehavior.COUNTS_AGAINST)
TWO_THIRDS = VotingRules(majority=MajorityType.QUALIFIED, threshold=2 / 3)
UNSC_RULES = COMMITTEE_CONFIGS[Committee.UNSC].voting_rules


def votes(**by_choice):
    """votes(YES=["US"], NO=["RU"], ABSTAIN=[...]) -> list of vote-like objects."""
    return [SimpleNamespace(country_code=c, choice=VoteChoice(choice)) for choice, codes in by_choice.items() for c in codes]


# --- simple majority -------------------------------------------------------------------------
def test_simple_majority_needs_strictly_more_than_half():
    codes = ["A1", "A2", "A3", "A4"]
    tie = tally(votes(YES=codes[:2], NO=codes[2:]), codes, SIMPLE)
    assert (tie.passed, tie.required_yes) == (False, 3)
    win = tally(votes(YES=codes[:3], NO=codes[3:]), codes, SIMPLE)
    assert (win.passed, win.required_yes, win.counted) == (True, 3, 4)


def test_abstentions_ignored_by_default():
    codes = [f"A{i}" for i in "ABCDEFGH"]
    result = tally(votes(YES=codes[:2], NO=codes[2:3], ABSTAIN=codes[3:]), codes, SIMPLE)
    assert (result.yes, result.no, result.abstain, result.counted, result.passed) == (2, 1, 5, 3, True)


def test_abstentions_count_against_when_configured():
    codes = [f"A{i}" for i in "ABCDEFGH"]
    result = tally(votes(YES=codes[:2], NO=codes[2:3], ABSTAIN=codes[3:]), codes, SIMPLE_COUNTING_ABSTENTIONS)
    assert (result.counted, result.required_yes, result.passed) == (8, 5, False)


def test_absent_delegates_are_ignored_unless_configured():
    codes = ["AA", "BB", "CC", "DD", "EE"]
    ignored = tally(votes(YES=["AA", "BB"]), codes, SIMPLE)
    assert (ignored.absent, ignored.counted, ignored.passed) == (3, 2, True)
    counted = tally(votes(YES=["AA", "BB"]), codes, VotingRules(absent_counts_against=True))
    assert (counted.counted, counted.required_yes, counted.passed) == (5, 3, False)


def test_no_yes_votes_never_passes():
    result = tally(votes(ABSTAIN=["AA"]), ["AA", "BB"], SIMPLE)
    assert result.passed is False and "no YES" in result.reason
    empty = tally([], ["AA", "BB"], SIMPLE)
    assert (empty.passed, empty.counted, empty.required_yes, empty.absent) == (False, 0, 1, 2)


# --- qualified majority ----------------------------------------------------------------------
@pytest.mark.parametrize("counted,expected", [(1, 1), (3, 2), (6, 4), (9, 6), (10, 7), (15, 10)])
def test_two_thirds_required_yes_is_an_exact_ceiling(counted, expected):
    assert required_yes(counted, TWO_THIRDS) == expected  # 0.6666... never rounds the wrong way


def test_qualified_threshold_is_inclusive():
    codes = [f"A{i}" for i in "ABCDEF"]
    assert tally(votes(YES=codes[:4], NO=codes[4:]), codes, TWO_THIRDS).passed is True  # exactly 4 of 6
    assert tally(votes(YES=codes[:3], NO=codes[3:]), codes, TWO_THIRDS).passed is False


def test_unanimity_is_a_valid_qualified_rule():
    unanimous = VotingRules(majority=MajorityType.QUALIFIED, threshold=1.0)
    codes = ["AA", "BB", "CC"]
    assert tally(votes(YES=codes), codes, unanimous).passed is True
    assert tally(votes(YES=codes[:2], NO=codes[2:]), codes, unanimous).passed is False


# --- UNSC and the veto -----------------------------------------------------------------------
def test_unsc_rules_are_nine_of_fifteen_with_a_p5_veto():
    assert UNSC_RULES.majority is MajorityType.QUALIFIED and UNSC_RULES.threshold == 0.6
    assert UNSC_RULES.abstention is AbstentionBehavior.COUNTS_AGAINST and UNSC_RULES.absent_counts_against
    assert UNSC_RULES.veto_enabled and list(UNSC_RULES.veto_members) == P5 == list(UNSC_PERMANENT_MEMBERS)


def test_unsc_nine_votes_pass_and_eight_fail():
    nine = tally(votes(YES=UNSC15[:9], ABSTAIN=UNSC15[9:]), UNSC15, UNSC_RULES)
    assert (nine.passed, nine.required_yes, nine.counted) == (True, 9, 15)
    eight = tally(votes(YES=UNSC15[:8], ABSTAIN=UNSC15[8:]), UNSC15, UNSC_RULES)
    assert (eight.passed, eight.required_yes) == (False, 9)


def test_unsc_abstentions_cannot_help_reach_nine():
    result = tally(votes(YES=UNSC15[:5], ABSTAIN=UNSC15[5:]), UNSC15, UNSC_RULES)
    assert result.passed is False and result.counted == 15


@pytest.mark.parametrize("holder", P5)
def test_a_no_from_any_permanent_member_is_a_veto(holder):
    rest = [c for c in UNSC15 if c != holder]
    result = tally(votes(YES=rest, NO=[holder]), UNSC15, UNSC_RULES)
    assert result.yes == 14 and result.passed is False
    assert result.vetoed_by == (holder,) and "Vetoed" in result.reason


def test_several_vetoes_are_all_reported_in_order():
    rest = [c for c in UNSC15 if c not in ("US", "CN")]
    result = tally(votes(YES=rest, NO=["US", "CN"]), UNSC15, UNSC_RULES)
    assert result.vetoed_by == ("CN", "US") and result.passed is False


def test_a_permanent_member_abstaining_is_not_a_veto():
    rest = [c for c in UNSC15 if c != "RU"]
    result = tally(votes(YES=rest, ABSTAIN=["RU"]), UNSC15, UNSC_RULES)
    assert result.passed is True and result.vetoed_by == ()


def test_a_permanent_member_being_absent_is_not_a_veto():
    rest = [c for c in UNSC15 if c != "RU"]
    result = tally(votes(YES=rest), UNSC15, UNSC_RULES)
    assert (result.passed, result.vetoed_by, result.absent) == (True, (), 1)


def test_a_no_from_a_non_permanent_member_is_not_a_veto():
    rest = [c for c in UNSC15 if c != "BR"]
    result = tally(votes(YES=rest, NO=["BR"]), UNSC15, UNSC_RULES)
    assert result.passed is True and result.vetoed_by == ()


def test_veto_applies_even_when_the_count_would_fail_anyway_and_is_still_reported():
    result = tally(votes(YES=["US"], NO=["RU"]), ["RU", "US"], UNSC_RULES)
    assert result.passed is False and result.vetoed_by == ("RU",)


def test_veto_only_applies_to_a_member_that_is_entitled_to_vote():
    # Russia is not seated: nobody can cast its NO, so there is nothing to veto with.
    seated = ["CN", "FR", "GB", "IN", "US"]
    result = tally(votes(YES=seated), seated, UNSC_RULES)
    assert result.passed is True and result.vetoed_by == ()


def test_no_veto_without_veto_enabled():
    result = tally(votes(YES=["BR", "JP"], NO=["US"]), ["BR", "JP", "US"], SIMPLE)
    assert result.passed is True and result.vetoed_by == ()


# --- determinism and safety ------------------------------------------------------------------
def test_result_does_not_depend_on_vote_order():
    cast = votes(YES=UNSC15[:9], NO=UNSC15[9:11], ABSTAIN=UNSC15[11:13])
    first = tally(cast, UNSC15, UNSC_RULES)
    for seed in range(10):
        shuffled = cast[:]
        random.Random(seed).shuffle(shuffled)
        assert tally(shuffled, list(reversed(UNSC15)), UNSC_RULES) == first


def test_result_lists_countries_sorted_and_carries_the_rules():
    result = tally(votes(YES=["US", "BR"], NO=["IN"]), ["US", "BR", "IN", "JP"], SIMPLE)
    assert result.yes_countries == ("BR", "US") and result.no_countries == ("IN",)
    assert result.absent_countries == ("JP",) and result.rules == SIMPLE


def test_duplicate_and_ineligible_votes_are_refused():
    with pytest.raises(VotingError):
        tally(votes(YES=["AA"], NO=["AA"]), ["AA"], SIMPLE)
    with pytest.raises(VotingError):
        tally(votes(YES=["ZZ"]), ["AA"], SIMPLE)


def test_a_result_is_immutable():
    result = tally(votes(YES=["AA"]), ["AA"], SIMPLE)
    with pytest.raises(ValidationError):
        result.passed = False


def test_voting_module_never_touches_an_ai_or_the_clock():
    source = inspect.getsource(voting_module).lower()
    for forbidden in ("gemini", "import ai", "from ai", "anthropic", "random", "datetime.now", "time.time"):
        assert forbidden not in source


# --- rule validation -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs",
    [
        {"majority": "QUALIFIED"},  # needs a threshold
        {"majority": "SIMPLE", "threshold": 0.6},  # a simple majority takes none
        {"majority": "QUALIFIED", "threshold": 0.5},  # not above a simple majority
        {"majority": "QUALIFIED", "threshold": 1.2},
        {"majority": "QUALIFIED", "threshold": float("nan")},
        {"veto_enabled": True},  # needs members
        {"veto_members": ["US"]},  # members need the flag
        {"veto_enabled": True, "veto_members": ["US", "US"]},
        {"veto_enabled": True, "veto_members": ["USA"]},
        {"abstention": "ignore"},
        {"colour": "red"},
    ],
)
def test_invalid_rules_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        VotingRules(**kwargs)


def test_veto_members_are_normalised():
    rules = VotingRules(veto_enabled=True, veto_members=["us", " ru "])
    assert rules.veto_members == ("RU", "US")


def test_committee_registry_defines_rules_for_every_committee():
    gc = COMMITTEE_CONFIGS[Committee.GLOBAL_CYBERSECURITY].voting_rules
    assert gc.majority is MajorityType.SIMPLE and gc.abstention is AbstentionBehavior.IGNORED and not gc.veto_enabled
    for config in COMMITTEE_CONFIGS.values():
        assert isinstance(config.voting_rules, VotingRules)


def test_a_qualified_committee_rule_must_match_the_committee_threshold():
    base = {"committee": "UNSC", "topic": "T", "max_delegates": 15, "allowed_phases": ["VOTING"]}
    CommitteeConfig(**base, voting_threshold=0.75, voting_rules=VotingRules(majority="QUALIFIED", threshold=0.75))
    with pytest.raises(ValidationError):
        CommitteeConfig(**base, voting_threshold=0.6, voting_rules=VotingRules(majority="QUALIFIED", threshold=0.75))


def test_a_config_without_voting_rules_defaults_to_a_simple_majority():
    cfg = CommitteeConfig(committee="UNSC", topic="T", max_delegates=5, voting_threshold=0.5, allowed_phases=["VOTING"])
    assert cfg.voting_rules == VotingRules()