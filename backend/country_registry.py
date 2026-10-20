"""Country identifier resolution backed by the `world-countries` dataset.

Why this exists
---------------
The UI lets the player pick any country from the `world-countries` npm package
(the same dataset `src/data/countries.js` uses), but the simulation world only
simulates a handful of them. Lookups used to be an exact, lowercase slug match
against the simulated countries, so anything else (e.g. "afghanistan") failed
with "Country 'afghanistan' not found" and codes such as "IND" or "AFG" were
never understood.

This module resolves any identifier a client may send -- display name, official
name, slug, ISO alpha-2 / alpha-3 code, numeric ISO code -- to ONE dataset
record, and links it to a simulated country through the ISO alpha-2
`country_code` that `Country` already carries. The dataset is read, never copied
or re-typed: there is no hand-maintained country list here.

Where the dataset is read from (first match wins):
  1. the file named by the WORLD_COUNTRIES_PATH environment variable
  2. <repo root>/node_modules/world-countries/countries.json (installed by `npm install`)
If neither exists, resolution degrades to the simulated countries only, and a
warning is logged once.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger("worldevent.countries")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_PATH = REPO_ROOT / "node_modules" / "world-countries" / "countries.json"


@dataclass(frozen=True)
class CountryRecord:
    """One country of the dataset, reduced to what the backend needs."""

    slug: str  # e.g. "afghanistan", "united-states"
    name: str  # common name, e.g. "Afghanistan"
    official_name: str
    cca2: str  # ISO alpha-2, e.g. "AF"
    cca3: str  # ISO alpha-3, e.g. "AFG"
    ccn3: str  # ISO numeric, e.g. "004" ("" if the dataset has none)
    region: str
    subregion: str
    capital: tuple[str, ...]
    independent: Optional[bool]
    un_member: Optional[bool]


def normalize_identifier(value: Any) -> str:
    """Canonical comparison form: 'United-States', 'united_states', ' UNITED  states ' -> 'united states'."""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("_", " ").replace("-", " ")
    text = re.sub(r"[^\w\s]", "", text)  # apostrophes, dots, commas ("Cote d'Ivoire", "U.S.A.")
    return re.sub(r"\s+", " ", text).strip()


def slugify(name: str) -> str:
    return normalize_identifier(name).replace(" ", "-")


def _numeric_key(value: str) -> Optional[str]:
    """'004', '4' and ' 4 ' are the same ISO numeric code."""
    value = value.strip()
    return str(int(value)) if value.isdigit() else None


def _dataset_path() -> Path:
    override = os.getenv("WORLD_COUNTRIES_PATH", "").strip()
    return Path(override) if override else DEFAULT_DATASET_PATH


def _to_record(raw: dict) -> Optional[CountryRecord]:
    name = (raw.get("name") or {}).get("common")
    cca2 = raw.get("cca2")
    if not name or not cca2:
        return None
    return CountryRecord(
        slug=slugify(name),
        name=name,
        official_name=(raw.get("name") or {}).get("official") or name,
        cca2=cca2.upper(),
        cca3=(raw.get("cca3") or "").upper(),
        ccn3=raw.get("ccn3") or "",
        region=raw.get("region") or "",
        subregion=raw.get("subregion") or "",
        capital=tuple(raw.get("capital") or ()),
        independent=raw.get("independent"),
        un_member=raw.get("unMember"),
    )


class CountryRegistry:
    """Index over dataset records. Tiers are tried in order; a tier must match exactly one country."""

    def __init__(self, raw_countries: Iterable[dict]) -> None:
        self.records: list[CountryRecord] = []
        raw_by_cca2: dict[str, dict] = {}
        for raw in raw_countries:
            record = _to_record(raw)
            if record is not None:
                self.records.append(record)
                raw_by_cca2[record.cca2] = raw

        # tier 1: exact codes / slug / common name; tier 2: official name; tier 3: alternate spellings.
        self._tiers: list[dict[str, set[str]]] = [{}, {}, {}]
        for record in self.records:
            for key in (record.cca2, record.cca3, record.slug, record.name):
                self._add(0, normalize_identifier(key), record.cca2)
            numeric = _numeric_key(record.ccn3)
            if numeric is not None:
                self._add(0, f"#{numeric}", record.cca2)
            self._add(1, normalize_identifier(record.official_name), record.cca2)
            for alt in raw_by_cca2[record.cca2].get("altSpellings") or ():
                self._add(2, normalize_identifier(alt), record.cca2)
        self._by_cca2 = {record.cca2: record for record in self.records}

    def _add(self, tier: int, key: str, cca2: str) -> None:
        if key:
            self._tiers[tier].setdefault(key, set()).add(cca2)

    def __len__(self) -> int:
        return len(self.records)

    def resolve(self, identifier: Any) -> Optional[CountryRecord]:
        if identifier is None:
            return None
        text = str(identifier)
        keys = [normalize_identifier(text)]
        numeric = _numeric_key(text)
        if numeric is not None:
            keys.insert(0, f"#{numeric}")
        for tier in self._tiers:
            for key in keys:
                matches = tier.get(key)
                if matches and len(matches) == 1:
                    return self._by_cca2[next(iter(matches))]
        return None


@lru_cache(maxsize=1)
def get_registry() -> CountryRegistry:
    path = _dataset_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        registry = CountryRegistry(raw)
        if len(registry) == 0:
            raise ValueError("dataset contains no countries")
        return registry
    except (OSError, ValueError) as exc:
        logger.warning(
            "world-countries dataset unavailable at %s (%s); only simulated countries can be resolved. "
            "Run `npm install` or set WORLD_COUNTRIES_PATH.",
            path,
            exc,
        )
        return CountryRegistry([])


def resolve_country(identifier: Any) -> Optional[CountryRecord]:
    """Dataset record for 'India' / 'india' / 'IND' / 'IN' / '356' ..., or None if it is not a country."""
    return get_registry().resolve(identifier)


def find_world_country(world: Any, identifier: Any):
    """The simulated country (an entry of world.countries) that `identifier` refers to, or None.

    Dataset first (so 'IND', 'usa', 'Russian Federation' work); the ISO alpha-2 `country_code`
    links the dataset record to the simulated country. Direct id / name / code matching on the
    simulated countries is the fallback, so lookups still work when the dataset file is missing.
    """
    countries = list(world.countries)
    record = resolve_country(identifier)
    if record is not None:
        for country in countries:
            if country.country_code and country.country_code.upper() == record.cca2:
                return country
        for country in countries:
            if country.id == record.slug:
                return country

    key = normalize_identifier(identifier)
    if not key:
        return None
    for country in countries:
        candidates = {normalize_identifier(country.id), normalize_identifier(country.name)}
        if country.country_code:
            candidates.add(normalize_identifier(country.country_code))
        if key in candidates:
            return country
    return None