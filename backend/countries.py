"""Fictional starting data: 10 countries, trade routes and relationships.

Everything here is hard-coded and deterministic. Trade partners and initial
relationship scores are *derived* from the raw data below so they can never
disagree with each other.
"""
from __future__ import annotations

from itertools import combinations

from models import Country, TradeRoute
from rules import (
    SHARED_ALLIANCE_BONUS,
    TRADE_ROUTE_BONUS_PER_10_VOLUME,
    clamp_relationship,
)

# --- Raw country data ---------------------------------------------------------
# gdp is in billions of fictional dollars. resources are stockpile indexes (0-100).
_RAW_COUNTRIES: list[dict] = [
    {"id": "aurelia",  "name": "Aurelia",  "gdp": 1800.0, "stability": 82,
     "resources": {"tech": 85, "minerals": 30, "oil": 15}},
    {"id": "brevania", "name": "Brevania", "gdp": 950.0,  "stability": 75,
     "resources": {"food": 80, "tech": 45, "energy": 40}},
    {"id": "caldoria", "name": "Caldoria", "gdp": 1200.0, "stability": 60,
     "resources": {"oil": 90, "minerals": 40, "food": 25}},
    {"id": "dravenia", "name": "Dravenia", "gdp": 700.0,  "stability": 55,
     "resources": {"minerals": 85, "energy": 50, "food": 35}},
    {"id": "eldoria",  "name": "Eldoria",  "gdp": 520.0,  "stability": 68,
     "resources": {"food": 70, "oil": 35, "tech": 30}},
    {"id": "fyrnia",   "name": "Fyrnia",   "gdp": 400.0,  "stability": 48,
     "resources": {"food": 75, "energy": 30, "minerals": 20}},
    {"id": "garvonia", "name": "Garvonia", "gdp": 880.0,  "stability": 52,
     "resources": {"minerals": 80, "oil": 45, "tech": 25}},
    {"id": "helvaris", "name": "Helvaris", "gdp": 1450.0, "stability": 90,
     "resources": {"tech": 90, "energy": 55, "food": 30}},
    {"id": "istoria",  "name": "Istoria",  "gdp": 310.0,  "stability": 40,
     "resources": {"minerals": 55, "food": 45, "energy": 20}},
    {"id": "jorvania", "name": "Jorvania", "gdp": 640.0,  "stability": 63,
     "resources": {"energy": 88, "oil": 50, "minerals": 35}},
]

# Alliance name -> member ids
ALLIANCES: dict[str, list[str]] = {
    "Northern Accord": ["aurelia", "brevania", "dravenia", "helvaris"],
    "Meridian Pact": ["caldoria", "eldoria", "garvonia"],
    "Sunward Union": ["fyrnia", "jorvania"],
}

# (exporter, importer, resource, volume)
_RAW_TRADE_ROUTES: list[tuple[str, str, str, int]] = [
    ("aurelia",  "brevania", "tech",     40),
    ("brevania", "aurelia",  "food",     30),
    ("caldoria", "aurelia",  "oil",      50),
    ("caldoria", "eldoria",  "oil",      35),
    ("eldoria",  "caldoria", "food",     25),
    ("dravenia", "helvaris", "minerals", 40),
    ("helvaris", "dravenia", "tech",     30),
    ("fyrnia",   "garvonia", "food",     30),
    ("garvonia", "fyrnia",   "minerals", 25),
    ("istoria",  "aurelia",  "minerals", 20),
    ("jorvania", "istoria",  "energy",   30),
    ("jorvania", "fyrnia",   "energy",   35),
    ("garvonia", "caldoria", "minerals", 30),
    ("dravenia", "jorvania", "minerals", 20),
    ("helvaris", "eldoria",  "tech",     25),
    ("brevania", "istoria",  "food",     20),
]

# Hand-tuned historical grudges (negative) and friendships (positive).
# Keys are unordered pairs; the value is added on top of alliance/trade effects.
_RELATIONSHIP_ADJUSTMENTS: dict[frozenset[str], int] = {
    frozenset({"aurelia", "garvonia"}): -45,
    frozenset({"helvaris", "garvonia"}): -35,
    frozenset({"caldoria", "dravenia"}): -30,
    frozenset({"dravenia", "jorvania"}): -30,
    frozenset({"eldoria", "istoria"}): -25,
    frozenset({"brevania", "fyrnia"}): -20,
    frozenset({"aurelia", "jorvania"}): -15,
    frozenset({"istoria", "fyrnia"}): 15,
}


# --- Builders -------------------------------------------------------------------
def build_trade_routes() -> list[TradeRoute]:
    return [
        TradeRoute(
            id=f"route-{i:02d}",
            exporter=exporter,
            importer=importer,
            resource=resource,
            volume=volume,
        )
        for i, (exporter, importer, resource, volume) in enumerate(_RAW_TRADE_ROUTES, start=1)
    ]


def _initial_relationships() -> dict[str, dict[str, int]]:
    ids = [c["id"] for c in _RAW_COUNTRIES]
    scores: dict[str, dict[str, int]] = {i: {} for i in ids}

    for a, b in combinations(ids, 2):
        score = 0
        # +25 for every alliance both countries belong to
        score += SHARED_ALLIANCE_BONUS * sum(
            1 for members in ALLIANCES.values() if a in members and b in members
        )
        # +3 per 10 units of trade volume between the two (either direction)
        volume = sum(
            v for (e, i, _r, v) in _RAW_TRADE_ROUTES if {e, i} == {a, b}
        )
        score += (volume // 10) * TRADE_ROUTE_BONUS_PER_10_VOLUME
        # hand-tuned grudges / friendships
        score += _RELATIONSHIP_ADJUSTMENTS.get(frozenset({a, b}), 0)

        score = clamp_relationship(score)
        scores[a][b] = score
        scores[b][a] = score  # relationships are symmetric at the start
    return scores


def build_countries() -> list[Country]:
    relationships = _initial_relationships()

    partners: dict[str, list[str]] = {c["id"]: [] for c in _RAW_COUNTRIES}
    for exporter, importer, _resource, _volume in _RAW_TRADE_ROUTES:
        if importer not in partners[exporter]:
            partners[exporter].append(importer)
        if exporter not in partners[importer]:
            partners[importer].append(exporter)

    countries: list[Country] = []
    for raw in _RAW_COUNTRIES:
        cid = raw["id"]
        countries.append(
            Country(
                **raw,
                trade_partners=sorted(partners[cid]),
                alliances=[name for name, members in ALLIANCES.items() if cid in members],
                sanctions=[],
                relationships=relationships[cid],
            )
        )
    return countries
