"""Prove that EVERY registered country is playable, not just the featured few.

The country registry (the world-countries dataset) is the single source of truth for which
countries exist. build_countries() must seed every one of them into the world with safe
defaults, and every action (sanction / alliance / aid), trade recalculation, diplomacy and the
AI proposal path must work for a newly added, non-featured country such as American Samoa.
"""
from fastapi.testclient import TestClient

from backend.country_registry import get_registry, resolve_country
from backend.main import app
from backend.rules import find_country, validate_world
from backend.simulation import create_initial_world

client = TestClient(app)

# A non-featured country that previously could not be selected or acted on.
NEW_COUNTRY = "american-samoa"
NEW_COUNTRY_CODE = "AS"


def world() -> dict:
    return client.get("/world").json()


def act(kind: str, actor: str, target: str, **extra):
    return client.post(f"/actions/{kind}", json={"actor": actor, "target": target, **extra})


# --- The world contains every registered country -----------------------------------------------
def test_world_contains_every_registered_country():
    w = create_initial_world()
    registry = get_registry()
    assert len(registry) > 0, "registry/dataset must be available for this test"

    ids = {c.id for c in w.countries}
    # Every registry record is seeded (by its slug).
    for record in registry.records:
        assert record.slug in ids, f"{record.name} ({record.slug}) is missing from the world"

    # And the world is internally consistent despite the large country set.
    assert validate_world(w) == []


def test_world_is_one_registry_sized_source_of_truth():
    w = create_initial_world()
    # No country beyond the registry sneaks in, and the counts line up.
    registry_slugs = {r.slug for r in get_registry().records}
    world_ids = {c.id for c in w.countries}
    # Featured ids are all registry slugs too (india, united-states, ...), so the world is exactly the registry.
    assert world_ids == registry_slugs


def test_featured_country_data_is_preserved():
    """Adding every country must not break the hand-tuned featured data or relationships."""
    w = create_initial_world()
    india = find_country(w, "india")
    assert india is not None
    assert india.gdp == 3900.0
    assert india.stability == 74
    assert india.resources == {"food": 75, "tech": 60, "minerals": 55, "energy": 45}
    # A curated relationship still exists and is symmetric.
    usa = find_country(w, "united-states")
    assert india.relationships.get("united-states") == usa.relationships.get("india")
    assert india.relationships.get("united-states", 0) != 0
    # Curated trade partners survived.
    assert "united-states" in india.trade_partners


def test_new_country_has_safe_defaults():
    w = create_initial_world()
    asam = find_country(w, NEW_COUNTRY)
    assert asam is not None
    assert asam.name == "American Samoa"
    assert asam.country_code == NEW_COUNTRY_CODE
    assert asam.gdp > 0
    assert 0 <= asam.stability <= 100
    assert asam.resources and all(0 <= v <= 100 for v in asam.resources.values())
    # Starts neutral: no alliances, no sanctions, no forced relationships.
    assert asam.alliances == []
    assert asam.sanctions == []
    assert asam.relationships == {}


# --- Lookup / selection ------------------------------------------------------------------------
def test_new_country_is_selectable_by_slug_and_code():
    assert client.get(f"/countries/{NEW_COUNTRY}").status_code == 200
    assert client.get(f"/countries/{NEW_COUNTRY_CODE}").status_code == 200
    # And it is present in the authoritative /world list the selector reads.
    ids = {c["id"] for c in world()["countries"]}
    assert NEW_COUNTRY in ids


# --- Actions work for a newly added country ----------------------------------------------------
def test_sanction_works_for_new_country():
    r = act("sanction", "india", NEW_COUNTRY)
    assert r.status_code == 200, r.text
    asam = next(c for c in world()["countries"] if c["id"] == NEW_COUNTRY)
    assert "india" in asam["sanctions"]


def test_alliance_works_for_new_country():
    r = act("alliance", "india", NEW_COUNTRY)
    assert r.status_code == 200, r.text
    asam = next(c for c in world()["countries"] if c["id"] == NEW_COUNTRY)
    assert asam["alliances"], "an alliance should have been formed"
    # Relationship became positive and symmetric.
    india = next(c for c in world()["countries"] if c["id"] == "india")
    assert india["relationships"].get(NEW_COUNTRY) == asam["relationships"].get("india")
    assert asam["relationships"].get("india", 0) > 0


def test_aid_works_for_new_country():
    r = act("aid", "india", NEW_COUNTRY, amount=50)
    assert r.status_code == 200, r.text
    asam = next(c for c in world()["countries"] if c["id"] == NEW_COUNTRY)
    assert asam["gdp"] > 100.0  # default GDP rose after receiving aid


def test_new_country_can_be_the_actor():
    """A newly added country can also initiate actions, not only receive them."""
    r = act("aid", NEW_COUNTRY, "india", amount=5)
    assert r.status_code == 200, r.text


def test_two_new_countries_interact():
    r = act("alliance", "tuvalu", "nauru")
    assert r.status_code == 200, r.text
    w = world()
    tuvalu = next(c for c in w["countries"] if c["id"] == "tuvalu")
    assert tuvalu["alliances"]


# --- Trade / diplomacy stays consistent after acting on a new country --------------------------
def test_trade_and_world_stay_consistent_after_new_country_action():
    assert act("sanction", "china", NEW_COUNTRY).status_code == 200
    # The live world served by the API is still internally consistent.
    from backend.models import WorldState

    w = WorldState.model_validate(world())
    assert validate_world(w) == []


# --- AI proposal path accepts every registered country -----------------------------------------
def test_ai_propose_accepts_new_country_without_profile_rejection():
    """A newly added country must not be rejected for 'no AI profile'.

    Gemma itself is unchanged, so without an API key the request fails upstream (502/503). The point
    is that it reaches the AI path instead of a 400/404 'country/profile not available' rejection.
    """
    r = client.post(
        "/ai/propose",
        json={"country_id": NEW_COUNTRY, "situation": "A regional trade disruption affects the territory."},
    )
    assert r.status_code not in (400, 404), r.text
    assert r.status_code in (200, 502, 503)


def test_ai_propose_still_rejects_a_non_country():
    r = client.post("/ai/propose", json={"country_id": "not-a-real-country-xyz", "situation": "test"})
    assert r.status_code == 404


def test_registry_resolves_new_country_identifiers():
    assert resolve_country(NEW_COUNTRY).cca2 == NEW_COUNTRY_CODE
    assert resolve_country(NEW_COUNTRY_CODE).slug == NEW_COUNTRY
    assert resolve_country("American Samoa").slug == NEW_COUNTRY
