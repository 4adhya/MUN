
import countriesData from "world-countries";

function formatPopulation(population) {
  if (typeof population !== "number") return "Not available";

  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(population);
}

function formatArea(area) {
  if (typeof area !== "number") return "Not available";

  return `${new Intl.NumberFormat("en-US").format(area)} km²`;
}

function getFlagEmoji(code = "") {
  if (!/^[A-Z]{2}$/.test(code)) return "🌐";

  return String.fromCodePoint(
    ...[...code].map((letter) => 127397 + letter.charCodeAt(0))
  );
}

function getCurrency(currencies = {}) {
  return Object.entries(currencies)
    .map(([code, currency]) =>
      `${currency.name || code} (${code})`
    )
    .join(", ") || "Not available";
}

function getLanguages(languages = {}) {
  return Object.values(languages).join(", ") || "Not available";
}

export function normalizeCountry(country) {
  const code = country.cca2 || "";

  return {
    id: country.ccn3
      ? String(Number(country.ccn3))
      : null,
    code,
    iso3: country.cca3 || "",
    name: country.name?.common || "Unknown country",
    officialName: country.name?.official || "Not available",
    flag: country.flag || getFlagEmoji(code),
    flagEmoji: country.flag || getFlagEmoji(code),
    flagImage: country.flags?.svg || country.flags?.png || "",
    capital: country.capital?.join(", ") || "Not available",
    population: country.population ?? null,
    populationLabel: formatPopulation(country.population),
    region: country.region || "Not available",
    subregion: country.subregion || "Not available",
    area: country.area ?? null,
    areaLabel: formatArea(country.area),
    currencies: country.currencies || {},
    currencyLabel: getCurrency(country.currencies),
    languages: country.languages || {},
    languageLabel: getLanguages(country.languages),
  };
}

import { getWorldCountries } from "../api/client.js";

// Rich display facts from the world-countries dataset, keyed by ISO alpha-2 code for merging
// with the backend's authoritative country list.
const allProfiles = countriesData
  .filter((country) => country.cca2 && country.name?.common)
  .map(normalizeCountry)
  .sort((a, b) => a.name.localeCompare(b.name));

const profilesByCode = new Map(
  allProfiles.map((profile) => [String(profile.code).toUpperCase(), profile])
);

// Turn a backend Country (from GET /world) into the profile shape the UI expects, enriched with
// the local dataset facts (capital, population, currency, ...) when available.
function profileFromBackendCountry(country) {
  const code = String(country.country_code || "").toUpperCase();
  const dataset = code ? profilesByCode.get(code) : null;
  if (dataset) {
    // Prefer the dataset's richer display facts; keep the backend id/name as the source of truth.
    return { ...dataset, id: country.id, name: country.name };
  }
  return {
    id: country.id,
    code,
    iso3: "",
    name: country.name,
    officialName: country.name,
    flag: country.flag || "🌐",
    flagEmoji: country.flag || "🌐",
    flagImage: "",
    capital: "Not available",
    population: null,
    populationLabel: "Not available",
    region: "Not available",
    subregion: "Not available",
    area: null,
    areaLabel: "Not available",
    currencies: {},
    currencyLabel: "Not available",
    languages: {},
    languageLabel: "Not available",
  };
}

// The selector's countries come from the BACKEND (the single source of truth for who is playable),
// enriched with local dataset facts. If the backend is unreachable, fall back to the full local
// dataset so the UI still works offline.
export async function getAllCountryProfiles() {
  try {
    const backendCountries = await getWorldCountries();
    if (Array.isArray(backendCountries) && backendCountries.length > 0) {
      return backendCountries
        .map(profileFromBackendCountry)
        .sort((a, b) => a.name.localeCompare(b.name));
    }
  } catch {
    // Backend unavailable — fall back to the full local dataset below.
  }
  return allProfiles;
}

export async function getCountryProfileById(id) {
  const numericId = String(Number(id));

  return (
    allProfiles.find((country) => country.id === numericId) || null
  );
}

export async function getCountryProfileByName(name) {
  const normalizedName = name.trim().toLowerCase();

  const aliases = {
    "united states of america": "united states",
    "russian federation": "russia",
    "republic of korea": "south korea",
    "korea, republic of": "south korea",
    "viet nam": "vietnam",
    "türkiye": "turkey",
  };

  const target = aliases[normalizedName] || normalizedName;

  return (
    allProfiles.find(
      (country) =>
        country.name.toLowerCase() === target ||
        country.officialName.toLowerCase() === normalizedName
    ) || null
  );
}
