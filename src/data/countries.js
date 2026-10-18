
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

// Country profiles are loaded locally; no API request is needed.
const allProfiles = countriesData
  .filter((country) => country.cca2 && country.name?.common)
  .map(normalizeCountry)
  .sort((a, b) => a.name.localeCompare(b.name));

export async function getAllCountryProfiles() {
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
