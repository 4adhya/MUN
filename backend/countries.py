"""Starting data for the real-country MUN simulation.

Country names and IDs correspond to real countries. GDP, stability, resources,
relationships, and trade-route values are illustrative simulation values, not
live economic data or claims about current diplomatic relations.

Every country known to the backend country registry (``country_registry``,
backed by the ``world-countries`` dataset) is seeded into the world so that it
is playable: it can be selected, proposed for by the AI, sanctioned, allied,
aided and traded with. A small set of "featured" countries carry hand-tuned
economic, resource and relationship data; every other registered country is
initialised with safe, neutral defaults. The registry is therefore the ONE
source of truth for which countries exist.
"""
from __future__ import annotations

from itertools import combinations

from .country_registry import get_registry
from .models import Country, TradeRoute
from .rules import (
    RESOURCE_MAX,
    RESOURCE_MIN,
    SHARED_ALLIANCE_BONUS,
    STABILITY_MAX,
    STABILITY_MIN,
    TRADE_ROUTE_BONUS_PER_10_VOLUME,
    clamp,
    clamp_relationship,
)

def flag_emoji(country_code: str) -> str:
    """ISO alpha-2 code -> flag emoji (regional-indicator letters), e.g. 'IN' -> flag of India."""
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in country_code)


# GDP is represented in billions of illustrative simulation dollars.
# Resource values are indexes from 0 to 100.
_RAW_COUNTRIES: list[dict] = [
    {
        "id": "india",
        "country_code": "IN",
        "name": "India",
        "gdp": 3900.0,
        "stability": 74,
        "resources": {"food": 75, "tech": 60, "minerals": 55, "energy": 45},
    },
    {
        "id": "united-states",
        "country_code": "US",
        "name": "United States",
        "gdp": 28800.0,
        "stability": 82,
        "resources": {"tech": 95, "energy": 85, "food": 90, "minerals": 75},
    },
    {
        "id": "china",
        "country_code": "CN",
        "name": "China",
        "gdp": 18700.0,
        "stability": 77,
        "resources": {"tech": 85, "minerals": 90, "energy": 65, "food": 80},
    },
    {
        "id": "france",
        "country_code": "FR",
        "name": "France",
        "gdp": 3200.0,
        "stability": 79,
        "resources": {"tech": 75, "food": 80, "energy": 70, "minerals": 45},
    },
    {
        "id": "united-kingdom",
        "country_code": "GB",
        "name": "United Kingdom",
        "gdp": 3600.0,
        "stability": 78,
        "resources": {"tech": 80, "energy": 55, "food": 65, "minerals": 40},
    },
    {
        "id": "russia",
        "country_code": "RU",
        "name": "Russia",
        "gdp": 2200.0,
        "stability": 61,
        "resources": {"energy": 95, "minerals": 90, "food": 65, "tech": 55},
    },
    {
        "id": "japan",
        "country_code": "JP",
        "name": "Japan",
        "gdp": 4000.0,
        "stability": 85,
        "resources": {"tech": 95, "minerals": 30, "energy": 25, "food": 45},
    },
    {
        "id": "brazil",
        "country_code": "BR",
        "name": "Brazil",
        "gdp": 2200.0,
        "stability": 68,
        "resources": {"food": 95, "minerals": 75, "energy": 65, "tech": 50},
    },
]

# No pre-existing alliances are assumed. AI agents can propose alliances
# through the simulation's normal validated action system.
ALLIANCES: dict[str, list[str]] = {}

# (exporter, importer, resource, base trade volume).
# These are illustrative game routes, not measured real-world trade flows.
_RAW_TRADE_ROUTES: list[tuple[str, str, str, int]] = [
    ("india", "united-states", "tech", 30),
    ("united-states", "india", "energy", 25),
    ("india", "china", "minerals", 20),
    ("china", "japan", "tech", 35),
    ("japan", "united-states", "tech", 35),
    ("united-states", "france", "food", 20),
    ("france", "united-kingdom", "food", 20),
    ("united-kingdom", "japan", "tech", 15),
    ("russia", "china", "energy", 40),
    ("russia", "india", "energy", 25),
    ("brazil", "china", "food", 35),
    ("brazil", "india", "food", 25),
    ("brazil", "france", "minerals", 20),
    ("united-states", "brazil", "tech", 15),
    ("france", "india", "tech", 15),
    ("china", "united-states", "minerals", 20),
]

# Initial diplomatic scores are game assumptions, not statements of current
# real-world relationships. Keys are unordered country pairs.
_RELATIONSHIP_ADJUSTMENTS: dict[frozenset[str], int] = {
    frozenset({"india", "united-states"}): 15,
    frozenset({"india", "russia"}): 12,
    frozenset({"india", "china"}): -20,
    frozenset({"united-states", "china"}): -25,
    frozenset({"united-states", "russia"}): -30,
    frozenset({"france", "russia"}): -20,
    frozenset({"united-kingdom", "russia"}): -20,
    frozenset({"china", "japan"}): -12,
    frozenset({"brazil", "china"}): 8,
    frozenset({"brazil", "united-states"}): 5,
}


def build_trade_routes() -> list[TradeRoute]:
    """Build the initial illustrative trade routes."""
    return [
        TradeRoute(
            id=f"route-{i:02d}",
            exporter=exporter,
            importer=importer,
            resource=resource,
            volume=volume,
            base_volume=volume,
        )
        for i, (exporter, importer, resource, volume)
        in enumerate(_RAW_TRADE_ROUTES, start=1)
    ]


def _initial_relationships() -> dict[str, dict[str, int]]:
    ids = [country["id"] for country in _RAW_COUNTRIES]
    scores: dict[str, dict[str, int]] = {country_id: {} for country_id in ids}

    for a, b in combinations(ids, 2):
        score = SHARED_ALLIANCE_BONUS * sum(
            1
            for members in ALLIANCES.values()
            if a in members and b in members
        )

        volume = sum(
            amount
            for exporter, importer, _resource, amount in _RAW_TRADE_ROUTES
            if {exporter, importer} == {a, b}
        )
        score += (
            volume // 10
        ) * TRADE_ROUTE_BONUS_PER_10_VOLUME

        score += _RELATIONSHIP_ADJUSTMENTS.get(frozenset({a, b}), 0)
        score = clamp_relationship(score)

        # The initial relationship matrix is symmetric.
        scores[a][b] = score
        scores[b][a] = score

    return scores


# Safe, neutral defaults for a registered country that has no hand-tuned entry
# in _RAW_COUNTRIES. These are deliberately middle-of-the-road illustrative
# values so that every country is immediately playable (can be sanctioned,
# allied, aided and traded with) without privileging it over the featured set.
DEFAULT_GDP = 100.0  # billions of illustrative simulation dollars
DEFAULT_STABILITY = 60
DEFAULT_RESOURCES: dict[str, int] = {"food": 50, "tech": 50, "minerals": 50, "energy": 50}


def _default_resources() -> dict[str, int]:
    return {
        resource: clamp(value, RESOURCE_MIN, RESOURCE_MAX)
        for resource, value in DEFAULT_RESOURCES.items()
    }


def _featured_countries() -> list[Country]:
    """The hand-tuned countries with their curated relationships, trade and alliances."""
    relationships = _initial_relationships()
    partners: dict[str, list[str]] = {
        country["id"]: [] for country in _RAW_COUNTRIES
    }

    for exporter, importer, _resource, _volume in _RAW_TRADE_ROUTES:
        if importer not in partners[exporter]:
            partners[exporter].append(importer)
        if exporter not in partners[importer]:
            partners[importer].append(exporter)

    countries: list[Country] = []

    for raw in _RAW_COUNTRIES:
        country_id = raw["id"]
        countries.append(
            Country(
                **raw,
                flag=flag_emoji(raw["country_code"]),
                trade_partners=sorted(partners[country_id]),
                alliances=[
                    alliance
                    for alliance, members in ALLIANCES.items()
                    if country_id in members
                ],
                sanctions=[],
                relationships=relationships[country_id],
            )
        )

    return countries


def _default_country_from_record(record) -> Country:
    """A registered (non-featured) country, seeded with safe neutral defaults.

    It starts with no trade routes, no alliances, no sanctions and an empty
    (all-zero) relationship map, so it is consistent on its own and every
    action (sanction/alliance/aid) and the AI proposal path work for it.
    """
    return Country(
        id=record.slug,
        country_code=record.cca2 if len(record.cca2) == 2 else None,
        name=record.name,
        flag=flag_emoji(record.cca2) if len(record.cca2) == 2 else None,
        gdp=DEFAULT_GDP,
        stability=clamp(DEFAULT_STABILITY, STABILITY_MIN, STABILITY_MAX),
        resources=_default_resources(),
        trade_partners=[],
        alliances=[],
        sanctions=[],
        relationships={},
    )


def build_countries() -> list[Country]:
    """Create every registered country, derive featured trade-partner lists.

    The featured countries keep their hand-tuned data; every other country the
    registry knows (the ``world-countries`` dataset) is appended with safe
    defaults so that the whole world is playable. The registry is the single
    source of truth; if it is unavailable only the featured set is built.
    """
    countries: list[Country] = _featured_countries()

    taken_ids = {country.id for country in countries}
    taken_codes = {country.country_code for country in countries if country.country_code}

    registry = get_registry()
    # Deterministic order (by slug) so the world is stable across runs.
    for record in sorted(registry.records, key=lambda r: r.slug):
        if record.slug in taken_ids:
            continue  # a featured country already occupies this slug (e.g. india)
        if record.cca2 in taken_codes:
            continue  # or this ISO code (defensive: codes are unique in the dataset)
        country = _default_country_from_record(record)
        countries.append(country)
        taken_ids.add(country.id)
        if country.country_code:
            taken_codes.add(country.country_code)

    return countries