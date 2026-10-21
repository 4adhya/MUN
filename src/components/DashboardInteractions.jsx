
import { useEffect, useState } from "react";
import {
  ArrowRight,
  Handshake,
  ShieldAlert,
  HeartHandshake,
  MessageSquare,
  Globe2,
  LoaderCircle,
  X,
} from "lucide-react";
import "./DashboardInteractions.css";

const ACTIONS = [
  {
    id: "sanctions",
    title: "Propose sanctions",
    description: "Apply economic or diplomatic pressure.",
    icon: ShieldAlert,
  },
  {
    id: "alliance",
    title: "Form alliance",
    description: "Build relationships and cooperation.",
    icon: Handshake,
  },
  {
    id: "aid",
    title: "Send aid",
    description: "Offer humanitarian or economic support.",
    icon: HeartHandshake,
  },
  {
    id: "negotiations",
    title: "Open negotiations",
    description: "Seek a diplomatic solution.",
    icon: MessageSquare,
  },
];

const COUNTRIES = [
  "Afghanistan",
  "Argentina",
  "Australia",
  "Austria",
  "Brazil",
  "Canada",
  "China",
  "Egypt",
  "France",
  "Germany",
  "India",
  "Italy",
  "Japan",
  "Mexico",
  "Nepal",
  "Pakistan",
  "Russia",
  "Saudi Arabia",
  "South Africa",
  "South Korea",
  "Turkey",
  "Ukraine",
  "United Arab Emirates",
  "United Kingdom",
  "United States",
];

const API_COUNTRIES = "https://restcountries.com/v3.1/name/";

function formatNumber(value) {
  if (value == null || !Number.isFinite(Number(value))) {
    return "Not available";
  }

  return new Intl.NumberFormat("en-US").format(Number(value));
}

function formatMoney(value) {
  if (value == null || !Number.isFinite(Number(value))) {
    return "Not available";
  }

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function makeLocalCountry(profile, countryName) {
  if (!profile) return null;
  const name = profile.name || countryName;
  return {
    name: {
      common: name,
      official: profile.officialName || name,
    },
    cca2: profile.code || "",
    cca3: profile.iso3 || "",
    capital: profile.capital ? [profile.capital] : [],
    region: profile.region || "",
    subregion: profile.subregion || "",
    population: profile.populationValue ?? null,
    area: profile.areaValue ?? null,
    areaLabel: profile.area || profile.areaLabel || "",
    currencies: profile.currencies || {},
    currencyLabel: profile.currency || profile.currencyLabel || "",
    languages: profile.languages && typeof profile.languages === "object"
      ? profile.languages
      : {},
    languageLabel: profile.languages && typeof profile.languages === "string"
      ? profile.languages
      : profile.languageLabel || "",
    flags: profile.flagImage ? { svg: profile.flagImage } : {},
    timezones: [],
    continents: [],
    idd: {},
    tld: [],
    unMember: null,
    independent: null,
    landlocked: null,
    borders: [],
    latlng: [],
    coatOfArms: {},
    maps: {},
    car: {},
    startOfWeek: "",
  };
}

function CountryInformation({ countryName, countryProfile }) {
  const [country, setCountry] = useState(null);
  const [gdp, setGdp] = useState(null);
  const [militarySpending, setMilitarySpending] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!countryName) {
      setCountry(null);
      setLoading(false);
      return;
    }

    const controller = new AbortController();

    async function loadCountry() {
      setLoading(true);
      setError("");
      setCountry(makeLocalCountry(countryProfile, countryName));
      setGdp(null);
      setMilitarySpending(null);

      try {
        const fields =
          "name,cca2,cca3,capital,region,subregion,population,area,currencies,languages,timezones,continents,idd,tld,unMember,independent,landlocked,borders,latlng,flags,coatOfArms,maps,car,startOfWeek";

        let results = [];

        // First try the specific country endpoint.
        try {
          const response = await fetch(
            `${API_COUNTRIES}${encodeURIComponent(countryName)}?fields=${fields}`,
            { signal: controller.signal }
          );

          if (response.ok) {
            const data = await response.json();
            if (Array.isArray(data)) results = data;
          }
        } catch (requestError) {
          if (requestError.name === "AbortError") throw requestError;
          // Continue to the all-countries fallback below.
        }

        // Fallback helps with country-name variations and endpoint lookup failures.
        if (!results.length) {
          const fallbackResponse = await fetch(
            `https://restcountries.com/v3.1/all?fields=${fields}`,
            { signal: controller.signal }
          );

          if (!fallbackResponse.ok) {
            throw new Error(
              "Country data service is unavailable. Check your internet connection and try again."
            );
          }

          const allCountries = await fallbackResponse.json();
          const normalizedName = countryName.trim().toLowerCase();

          results = (Array.isArray(allCountries) ? allCountries : []).filter(
            (item) =>
              item.name?.common?.toLowerCase() === normalizedName ||
              item.name?.official?.toLowerCase() === normalizedName
          );
        }

        const normalizedName = countryName.trim().toLowerCase();
        const selected =
          results.find(
            (item) =>
              item.name?.common?.toLowerCase() === normalizedName ||
              item.name?.official?.toLowerCase() === normalizedName
          ) || results[0];

        if (!selected) {
          throw new Error(
            `No country record was found for "${countryName}".`
          );
        }

        setCountry(selected);

        if (selected.cca3) {
          const indicators = [
            {
              key: "gdp",
              url: `https://api.worldbank.org/v2/country/${selected.cca3}/indicator/NY.GDP.MKTP.CD?format=json&per_page=20`,
            },
            {
              key: "military",
              url: `https://api.worldbank.org/v2/country/${selected.cca3}/indicator/MS.MIL.XPND.GD.ZS?format=json&per_page=20`,
            },
          ];

          const responses = await Promise.allSettled(
            indicators.map((indicator) =>
              fetch(indicator.url, { signal: controller.signal })
            )
          );

          for (let index = 0; index < responses.length; index += 1) {
            const result = responses[index];

            if (result.status !== "fulfilled" || !result.value.ok) {
              continue;
            }

            try {
              const json = await result.value.json();
              const observation = json?.[1]?.find(
                (item) => item.value != null
              );

              if (!observation) continue;

              const value = {
                value: observation.value,
                year: observation.date,
              };

              if (indicators[index].key === "gdp") {
                setGdp(value);
              } else {
                setMilitarySpending(value);
              }
            } catch {
              // Keep unavailable if no usable observation is returned.
            }
          }
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          // Keep the dashboard useful if the external country API is offline.
          const localCountry = makeLocalCountry(countryProfile, countryName);
          if (localCountry) {
            setCountry(localCountry);
            setError("");
          } else {
            setError(err.message || "Unable to load country information.");
          }
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    loadCountry();

    return () => controller.abort();
  }, [countryName, countryProfile]);

  if (loading && !country) {
    return (
      <div className="di-message">
        <LoaderCircle className="di-spin" size={20} />
        Loading country information…
      </div>
    );
  }

  if (error && !country) {
    return <p className="di-message di-error">{error}</p>;
  }

  if (!country) return null;

  const currencies = Object.values(country.currencies || {})
    .map((item) => typeof item === "string"
      ? item
      : `${item.name || ""}${item.symbol ? ` (${item.symbol})` : ""}`)
    .filter(Boolean)
    .join(", ") || country.currencyLabel || "";

  const languages = Object.values(country.languages || {}).join(", ") || country.languageLabel || "";

  const details = [
    ["Official name", country.name?.official],
    ["Capital", country.capital?.join(", ")],
    ["Region", country.region],
    ["Subregion", country.subregion],
    ["Population", formatNumber(country.population)],
    [
      "Area",
      country.area != null
        ? `${formatNumber(country.area)} km²`
        : country.areaLabel || null,
    ],
    ["Currency", currencies],
    ["Languages", languages],
    ["Time zones", country.timezones?.join(", ")],
    ["Continents", country.continents?.join(", ")],
    [
      "Calling code",
      country.idd?.root
        ? `${country.idd.root}${country.idd.suffixes?.[0] || ""}`
        : null,
    ],
    ["Internet domains", country.tld?.join(", ")],
    ["ISO alpha-2", country.cca2],
    ["ISO alpha-3", country.cca3],
    [
      "UN member",
      country.unMember == null
        ? null
        : country.unMember
          ? "Yes"
          : "No",
    ],
    [
      "Independent",
      country.independent == null
        ? null
        : country.independent
          ? "Yes"
          : "No",
    ],
    [
      "Coastline",
      country.landlocked == null
        ? null
        : country.landlocked
          ? "Landlocked"
          : "Has coastline",
    ],
    ["Driving side", country.car?.side],
    ["Start of week", country.startOfWeek],
    ["Bordering countries (ISO codes)", country.borders?.join(", ")],
    ["Coordinates", country.latlng?.join(", ")],
    [
      "GDP (current US$)",
      gdp
        ? `${formatMoney(gdp.value)} · ${gdp.year}`
        : null,
    ],
    [
      "Military spending (% of GDP)",
      militarySpending
        ? `${militarySpending.value}% · ${militarySpending.year}`
        : null,
    ],
  ].filter(([, value]) => {
    if (value == null || value === "") return false;
    if (typeof value === "string" && value.trim().toLowerCase() === "not available") return false;
    return true;
  });

  return (
    <div className="di-country">
      <div className="di-country-heading">
        {country.flags?.svg && (
          <img
            src={country.flags.svg}
            alt={country.flags.alt || `${country.name.common} flag`}
          />
        )}

        <div>
          <span className="di-eyebrow">COUNTRY INTELLIGENCE</span>
          <h3>{country.name.common}</h3>
          <p>{country.name.official}</p>
        </div>
      </div>

      {country.coatOfArms?.svg && (
        <div className="di-coat-of-arms">
          <img
            src={country.coatOfArms.svg}
            alt={`${country.name.common} coat of arms`}
          />
        </div>
      )}

      <div className="di-country-grid">
        {details.map(([label, value]) => (
          <div className="di-detail" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>

      {country.maps?.googleMaps && (
        <a
          className="di-map-link"
          href={country.maps.googleMaps}
          target="_blank"
          rel="noreferrer"
        >
          Open country map <ArrowRight size={15} />
        </a>
      )}

      {error && <p className="di-message di-error">{error}</p>}

      <p className="di-source">
        Sources: REST Countries and World Bank. GDP and military-spending
        observations may not be from the current year. Military spending
        does not measure military capability. Current alliances, sanctions,
        diplomatic relationships, and simulation scores require simulation data.
      </p>
    </div>
  );
}

export default function DashboardInteractions({
  countryName = "India",
  countryProfile = null,
  onSubmitAction,
}) {
  const [activeAction, setActiveAction] = useState(null);
  const [target, setTarget] = useState("");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const availableCountries = COUNTRIES.filter(
    (name) =>
      name.toLowerCase() !== countryName.trim().toLowerCase()
  ).sort();

  function openAction(actionId) {
    setMessage("");

    if (activeAction === actionId) {
      setActiveAction(null);
      return;
    }

    setActiveAction(actionId);
    setTarget("");
    setDetails("");
  }

  async function submitAction(event) {
    event.preventDefault();
    setMessage("");

    if (!target) {
      setMessage("Please select a target country.");
      return;
    }

    if (
      target.toLowerCase() === countryName.trim().toLowerCase()
    ) {
      setMessage("Choose a country other than your own delegation.");
      return;
    }

    if (typeof onSubmitAction !== "function") {
      setMessage(
        "The form is ready, but the backend action handler is not connected yet."
      );
      return;
    }

    setBusy(true);

    try {
      const result = await onSubmitAction({
        action: activeAction,
        actor: countryName,
        target,
        details: details.trim(),
      });

      setMessage(result?.message || "Proposal submitted successfully.");
      setTarget("");
      setDetails("");
    } catch (err) {
      setMessage(err.message || "Action failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="di-layout">
      <section className="di-panel">
        <div className="di-heading">
          <div>
            <span className="di-eyebrow">DIPLOMATIC TOOLKIT</span>
            <h2>Available diplomatic actions</h2>
            <p>
              Choose an action. Its form opens above the action cards.
            </p>
          </div>
          <Globe2 size={22} />
        </div>

        {/* The form is rendered before the cards */}
        {activeAction && (
          <form className="di-action-form" onSubmit={submitAction}>
            <div className="di-form-heading">
              <div>
                <span className="di-eyebrow">NEW DIPLOMATIC ACTION</span>
                <h3>
                  {ACTIONS.find((item) => item.id === activeAction)?.title}
                </h3>
              </div>

              <button
                type="button"
                className="di-close"
                onClick={() => setActiveAction(null)}
                aria-label="Close action form"
              >
                <X size={18} />
              </button>
            </div>

            <p className="di-form-note">
              Acting delegation: <strong>{countryName}</strong>
            </p>

            <label htmlFor="di-target">
              Select target country or delegation
            </label>

            <select
              id="di-target"
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              required
              disabled={busy}
            >
              <option value="">Choose a country</option>
              {availableCountries.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>

            <label htmlFor="di-details">Proposal details</label>

            <textarea
              id="di-details"
              value={details}
              onChange={(event) => setDetails(event.target.value)}
              placeholder="Explain the proposal, purpose, or terms…"
              rows={3}
              disabled={busy}
            />

            {message && (
              <p className="di-feedback" role="status">
                {message}
              </p>
            )}

            <button className="di-submit" type="submit" disabled={busy}>
              {busy ? "Submitting…" : "Submit proposal"}
              {busy ? (
                <LoaderCircle className="di-spin" size={16} />
              ) : (
                <ArrowRight size={16} />
              )}
            </button>
          </form>
        )}

        <div className="di-action-grid">
          {ACTIONS.map(({ id, title, description, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={`di-action-card ${
                activeAction === id ? "is-active" : ""
              }`}
              onClick={() => openAction(id)}
              aria-expanded={activeAction === id}
            >
              <span className="di-action-icon">
                <Icon size={21} />
              </span>

              <strong>{title}</strong>
              <span>{description}</span>

              <span className="di-action-link">
                {activeAction === id ? "Close form" : "Configure action"}
                <ArrowRight size={15} />
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="di-panel">
        <div className="di-heading">
          <div>
            <span className="di-eyebrow">NATIONAL INTELLIGENCE</span>
            <h2>Country information</h2>
            <p>Facts for the currently selected country.</p>
          </div>
          <Globe2 size={22} />
        </div>

        <CountryInformation countryName={countryName} countryProfile={countryProfile} />
      </section>
    </div>
  );
}
