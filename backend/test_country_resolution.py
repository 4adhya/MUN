"""Country identifier resolution (the 'Country afghanistan not found' bug).

The AI advisor used to work only for the 8 simulated countries because lookups were an exact
lowercase slug match. These tests use the real `world-countries` dataset (skipped if it has not
been installed with `npm install` and WORLD_COUNTRIES_PATH is not set) and a fake LLM, so no
network or Gemini key is needed.
"""
import json

import pytest
from fastapi.testclient import TestClient

from ai.country_agent import CountryAgent
from backend import main
from backend.country_registry import (
    DEFAULT_DATASET_PATH,
    _dataset_path,
    find_world_country,
    get_registry,
    normalize_identifier,
    resolve_country,
)
from backend.simulation import simulation

needs_dataset = pytest.mark.skipif(
    not _dataset_path().exists(),
    reason=f"world-countries dataset not found ({DEFAULT_DATASET_PATH}); run `npm install`",
)

client = TestClient(main.app)

SIMULATED = ["india", "united-states", "china", "france", "united-kingdom", "russia", "japan", "brazil"]


@pytest.fixture(autouse=True)
def fresh_registry():
    get_registry.cache_clear()
    yield
    get_registry.cache_clear()


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace Gemini with a fake that answers NO_ACTION for whichever country is advising."""
    seen = {}

    def factory(profile):
        def llm(system_prompt, user_prompt):
            seen.update(profile=profile, system=system_prompt, user=user_prompt)
            return json.dumps(
                {
                    "country": profile.name,
                    "situation": "A crisis.",
                    "decision": "NO_ACTION",
                    "target": None,
                    "reason": "Wait and see.",
                }
            )

        return CountryAgent(profile, llm=llm)

    monkeypatch.setattr(main, "CountryAgent", factory)
    return seen


def propose(country_id):
    return client.post("/ai/propose", json={"country_id": country_id, "situation": "A trade crisis."})


def test_normalize_identifier():
    assert normalize_identifier("United-States") == normalize_identifier("united_states ") == "united states"
    assert normalize_identifier("Côte d'Ivoire") == "cote divoire"


@needs_dataset
@pytest.mark.parametrize(
    "identifier, slug",
    [
        ("India", "india"), ("india", "india"), ("IND", "india"), ("ind", "india"), ("IN", "india"), ("356", "india"),
        ("Afghanistan", "afghanistan"), ("afghanistan", "afghanistan"), ("AFG", "afghanistan"), ("AF", "afghanistan"),
        ("004", "afghanistan"), ("4", "afghanistan"),
        ("Pakistan", "pakistan"), ("PAK", "pakistan"),
        ("USA", "united-states"), ("US", "united-states"), ("united-states", "united-states"),
        ("United States of America", "united-states"), ("Russia", "russia"), ("RUS", "russia"),
        ("Russian Federation", "russia"),
        ("France", "france"), ("FRA", "france"), ("Japan", "japan"), ("JPN", "japan"),
        ("  Côte d'Ivoire ", "ivory-coast"), ("UK", "united-kingdom"),
    ],
)
def test_identifiers_resolve_to_one_country(identifier, slug):
    assert resolve_country(identifier).slug == slug


@needs_dataset
@pytest.mark.parametrize("identifier", ["atlantis", "", "   ", "ZZZ", "99999", "wakanda"])
def test_invalid_identifiers_do_not_resolve(identifier):
    assert resolve_country(identifier) is None


@needs_dataset
@pytest.mark.parametrize("alias", ["India", "india", "IND", "IN", " INDIA "])
def test_world_lookup_links_dataset_to_simulated_country(alias):
    assert find_world_country(simulation.world, alias).id == "india"


@needs_dataset
def test_simulated_countries_are_not_in_the_dataset_only_by_name():
    # Every simulated country is reachable through its alpha-2 code, alpha-3 code and slug.
    for country in simulation.world.countries:
        record = resolve_country(country.country_code)
        assert find_world_country(simulation.world, record.cca3).id == country.id
        assert find_world_country(simulation.world, country.id).id == country.id


@needs_dataset
@pytest.mark.parametrize(
    "identifier, name",
    [
        ("india", "India"), ("India", "India"), ("IND", "India"),
        ("afghanistan", "Afghanistan"), ("Afghanistan", "Afghanistan"), ("AFG", "Afghanistan"),
        ("pakistan", "Pakistan"), ("united-states", "United States"), ("USA", "United States"),
        ("russia", "Russia"), ("france", "France"), ("japan", "Japan"),
    ],
)
def test_ai_propose_works_for_every_country(fake_llm, identifier, name):
    response = propose(identifier)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"]["country"] == name
    assert body["used_fallback"] is False
    assert fake_llm["profile"].name == name


@needs_dataset
def test_simulated_country_keeps_its_hand_written_profile_and_live_state(fake_llm):
    for identifier in ("india", "IND"):
        assert propose(identifier).status_code == 200
        assert fake_llm["profile"].country_id == "india"
        assert fake_llm["profile"].background == ""
        assert "=== CURRENT STATE OF INDIA ===" in fake_llm["user"]


@needs_dataset
def test_non_simulated_country_gets_dataset_facts_and_no_invented_numbers(fake_llm):
    assert propose("afghanistan").status_code == 200
    assert fake_llm["profile"].country_id == "afghanistan"
    user = fake_llm["user"]
    assert "AFGHANISTAN: NOT A SIMULATED PARTICIPANT" in user
    assert "Capital: Kabul" in user
    assert "CURRENT STATE OF" not in user
    assert "- India: GDP" in user  # simulated countries remain valid targets


@needs_dataset
def test_non_simulated_country_can_target_a_simulated_country(monkeypatch):
    def factory(profile):
        reply = json.dumps(
            {"country": profile.name, "situation": "s", "decision": "ALLIANCE", "target": "India", "reason": "r"}
        )
        return CountryAgent(profile, llm=lambda _system, _user: reply)

    monkeypatch.setattr(main, "CountryAgent", factory)
    body = propose("PAK").json()
    assert body["decision"]["decision"] == "ALLIANCE"
    assert body["decision"]["target"] == "India"
    assert body["used_fallback"] is False


@needs_dataset
@pytest.mark.parametrize("identifier", ["atlantis", "wakanda", "ZZZ"])
def test_invalid_country_is_still_404(fake_llm, identifier):
    response = propose(identifier)
    assert response.status_code == 404
    assert response.json() == {"detail": f"Country '{identifier}' not found"}
    assert "profile" not in fake_llm  # the agent was never built


@needs_dataset
@pytest.mark.parametrize("identifier", ["india", "India", "IND"])
def test_get_country_accepts_aliases_for_simulated_countries(identifier):
    response = client.get(f"/countries/{identifier}")
    assert response.status_code == 200
    assert response.json()["id"] == "india"


def test_get_country_unknown_is_404():
    assert client.get("/countries/atlantis").status_code == 404


def test_simulated_countries_work_without_the_dataset(monkeypatch, fake_llm):
    monkeypatch.setenv("WORLD_COUNTRIES_PATH", "/nonexistent/countries.json")
    get_registry.cache_clear()
    for identifier in SIMULATED + ["India", "IN"]:
        assert propose(identifier).status_code == 200, identifier
    assert client.get("/countries/india").status_code == 200
    assert propose("afghanistan").status_code == 404  # needs the dataset; fails cleanly, not with a 500