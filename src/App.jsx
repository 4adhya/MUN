import ScrollReveal from "./components/ScrollReveal";
import { useEffect, useRef, useState } from "react";
import Globe from "react-globe.gl";
import {
  Globe2, ArrowRight, Shield, Users, Handshake, Activity,
  TrendingUp, Landmark, Map, BarChart3, Search, Check,
  AlertTriangle, Bell, MessageSquare, Crosshair, HeartHandshake,
  Clock3, X, ChevronDown, Send, Target
} from "lucide-react";
import "./App.css";
import "./PoliticaRedesign.css";
import WorldMap from "./components/WorldMap";
import ConferenceRoom from "./components/ConferenceRoom";
import { getAllCountryProfiles } from "./data/countries.js";
import { askAdvisor } from "./api/client.js";

const featuredCountries = []; // Country profiles are loaded dynamically from countries.js.

const initialEvents = [
  { type: "alert", title: "Trade tensions rising", detail: "Major economies are reviewing trade restrictions.", time: "2 min ago" },
  { type: "deal", title: "Diplomatic talks proposed", detail: "A proposal for emergency talks is circulating.", time: "8 min ago" },
  { type: "info", title: "Security briefing updated", detail: "New information is available to delegates.", time: "14 min ago" },
];

const tabs = [
  ["conference", "Conference", Landmark],
  ["dashboard", "Dashboard", Activity],
  ["map", "World Map", Globe2],
  ["countries", "Countries", Users],
  ["events", "Events", Bell],
  ["analytics", "World", BarChart3],
];

function WorldGraphic({ selected, onSelect, large = false }) {
  const [hovered, setHovered] = useState("");

  const land = [
    "M62 74 L91 51 140 42 167 58 199 62 220 88 199 110 181 126 171 158 149 179 131 161 114 143 94 128 72 116 55 94Z",
    "M180 177 L205 186 223 211 216 241 201 268 197 304 180 343 165 326 158 291 147 263 154 229 164 204Z",
    "M312 76 L342 59 378 62 398 78 431 72 457 59 488 64 516 48 555 59 586 73 619 76 645 96 675 108 690 133 669 151 639 146 614 158 588 145 569 164 542 151 522 173 494 159 471 170 454 147 430 139 407 156 389 137 368 139 348 122 322 116Z",
    "M356 149 L381 151 407 175 410 203 394 233 377 264 361 292 343 270 331 240 329 211 338 185Z",
    "M496 182 L524 167 558 174 579 193 604 199 628 223 620 251 590 261 573 248 555 268 536 251 514 238 504 214Z",
    "M626 276 L653 266 682 276 699 296 687 317 659 325 636 309Z",
    "M708 157 L726 148 741 162 733 180 716 181Z",
    "M248 95 L267 83 286 92 279 110 259 117Z",
  ];

  return (
    <div className={`world-graphic ${large ? "world-graphic-large" : ""}`}>
      <svg viewBox="0 0 800 410" className="continent-art" role="img" aria-label="Illustrated interactive world map">
        <defs>
          <pattern id="mapGrid" width="32" height="32" patternUnits="userSpaceOnUse">
            <path d="M32 0H0V32" fill="none" stroke="#1a4160" strokeWidth=".8" />
          </pattern>
          <linearGradient id="landGlow" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#247b99" />
            <stop offset="100%" stopColor="#164566" />
          </linearGradient>
        </defs>
        <rect width="800" height="410" fill="#071b30" />
        <rect width="800" height="410" fill="url(#mapGrid)" />
        <g fill="url(#landGlow)" stroke="#4387a7" strokeWidth="1.5">
          {land.map((d, i) => <path key={i} d={d} />)}
        </g>

        {featuredCountries.map((c) => {
          const active = selected === c.name;
          const showLabel = large || active || hovered === c.name;
          const x = c.x * 8;
          const y = c.y * 4.1;
          const labelWidth = Math.max(62, c.name.length * 6.3 + 13);
          const labelX = x + labelWidth + 9 > 795 ? x - labelWidth - 9 : x + 9;

          return (
            <g
              key={c.name}
              className="map-country-point"
              onMouseEnter={() => setHovered(c.name)}
              onMouseLeave={() => setHovered("")}
              onClick={() => onSelect?.(c.name)}
              onKeyDown={(e) => {
                if (onSelect && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  onSelect(c.name);
                }
              }}
              tabIndex={onSelect ? 0 : undefined}
              role={onSelect ? "button" : undefined}
              aria-label={`Select ${c.name}`}
            >
              {active && <circle cx={x} cy={y} r="17" fill={c.color} opacity=".17" />}
              <circle cx={x} cy={y} r={active ? 6 : 4.5} fill={c.color} />
              <circle cx={x} cy={y} r={active ? 12 : 9} fill="none" stroke={c.color} opacity=".65" />
              {showLabel && (
                <g className="country-map-label">
                  <rect
                    x={labelX}
                    y={y - 24}
                    width={labelWidth}
                    height="22"
                    rx="5"
                    fill={active ? "#0c3960" : "#081b2e"}
                    stroke={active ? "#48c8ff" : "#315774"}
                  />
                  <text x={labelX + 7} y={y - 10} fill="#f0f8ff" fontSize="10.5" fontWeight={active ? "700" : "500"}>
                    {c.name}
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
      <div className="map-legend">
        <span><i className="legend-dot friendly" /> Diplomatic partner</span>
        <span><i className="legend-dot neutral" /> Neutral</span>
        <span><i className="legend-dot hostile" /> Tension</span>
      </div>
    </div>
  );
}

function RotatingEarth() {
  const globeRef = useRef(null);
  const containerRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 560, height: 460 });

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const observer = new ResizeObserver(([entry]) => {
      const width = Math.floor(entry.contentRect.width);
      setDimensions({
        width,
        height: Math.min(510, Math.max(310, Math.floor(width * 0.82))),
      });
    });

    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const globe = globeRef.current;
    if (!globe) return;

    const controls = globe.controls();
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.38;
    controls.enableZoom = false;
    controls.enablePan = false;
    globe.pointOfView({ lat: 22, lng: 75, altitude: 2.15 }, 0);
  }, []);

  const arcs = [
    { startLat: 28.6, startLng: 77.2, endLat: 38.9, endLng: -77.0 },
    { startLat: 28.6, startLng: 77.2, endLat: 39.9, endLng: 116.4 },
    { startLat: 48.8, startLng: 2.3, endLat: 35.7, endLng: 139.7 },
    { startLat: 40.7, startLng: -74, endLat: 51.5, endLng: -.1 },
    { startLat: 39.9, startLng: 116.4, endLat: 35.7, endLng: 139.7 },
  ];

  return (
    <div className="rotating-earth" ref={containerRef}>
      <Globe
        ref={globeRef}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor="rgba(0,0,0,0)"
        globeImageUrl="https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg"
        bumpImageUrl="https://unpkg.com/three-globe/example/img/earth-topology.png"
        showAtmosphere
        atmosphereColor="#1687ff"
        atmosphereAltitude={0.13}
        arcsData={arcs}
        arcColor={() => ["#42c7f5", "#1687ff"]}
        arcStroke={0.55}
        arcDashLength={0.35}
        arcDashGap={0.2}
        arcDashAnimateTime={2400}
        pointsData={featuredCountries.map((c) => ({
          lat: ({ India: 28.6, "United States": 38.9, China: 39.9, France: 48.8, "United Kingdom": 51.5, Russia: 55.8, Japan: 35.7, Brazil: -15.8 })[c.name],
          lng: ({ India: 77.2, "United States": -77, China: 116.4, France: 2.3, "United Kingdom": -.1, Russia: 37.6, Japan: 139.7, Brazil: -47.9 })[c.name],
          name: c.name,
          color: c.color,
        }))}
        pointLat="lat"
        pointLng="lng"
        pointColor="color"
        pointAltitude={0.025}
        pointRadius={0.35}
        pointLabel="name"
        ringsData={[
          { lat: 28.6, lng: 77.2 },
          { lat: 38.9, lng: -77 },
          { lat: 39.9, lng: 116.4 },
          { lat: 48.8, lng: 2.3 },
        ]}
        ringLat="lat"
        ringLng="lng"
        ringColor={() => "#46bfff"}
        ringMaxRadius={2.5}
        ringPropagationSpeed={1.5}
        ringRepeatPeriod={1300}
      />
      <div className="earth-caption">
        <span className="live-indicator" /> GLOBAL CONNECTIONS
        <span className="earth-caption-divider" /> DIPLOMATIC NETWORK
      </div>
    </div>
  );
}

function Metric({ icon: Icon, label, value, sub, color = "blue" }) {
  return (
    <div className="metric-card">
      <div className={`metric-icon ${color}`}><Icon size={17} /></div>
      <div className="metric-copy">
        <span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}
      </div>
    </div>
  );
}

function MiniBars({ value, color = "blue" }) {
  return <div className="mini-track"><span className={color} style={{ width: `${value}%` }} /></div>;
}


const COUNTRY_COLORS = ["#60a5fa", "#34d399", "#f59e0b", "#a78bfa", "#fb7185", "#38bdf8"];

function flagEmojiFromCode(code = "") {
  if (!/^[A-Z]{2}$/.test(code)) return "🌐";
  return [...code].map((letter) => String.fromCodePoint(127397 + letter.charCodeAt(0))).join("");
}

function canonicalCountryName(name = "") {
  const aliases = {
    "United States of America": "United States",
    "Russian Federation": "Russia",
    "Türkiye": "Turkey",
    "Republic of Korea": "South Korea",
    "Korea, Republic of": "South Korea",
    "Democratic People's Republic of Korea": "North Korea",
    "Czechia": "Czechia",
  };
  return aliases[name] || name;
}

function buildCountryList(profiles) {
  const featuredByName = new globalThis.Map(featuredCountries.map((country) => [country.name, country]));

  return profiles.map((profile, index) => {
    const name = canonicalCountryName(profile.name);
    const featured = featuredByName.get(name);
    return {
      ...featured,
      id: profile.id,
      code: profile.code,
      iso3: profile.iso3,
      name,
      officialName: profile.officialName,
      flag: flagEmojiFromCode(profile.code),
      flagImage: profile.flag,
      capital: profile.capital,
      population: profile.populationLabel,
      populationValue: profile.population,
      region: profile.region,
      subregion: profile.subregion,
      area: profile.areaLabel,
      currency: profile.currencyLabel,
      languages: profile.languageLabel,
      economy: featured?.economy || "Not rated",
      military: featured?.military || "Not rated",
      stability: featured?.stability ?? 50,
      color: featured?.color || COUNTRY_COLORS[index % COUNTRY_COLORS.length],
      gdp: featured?.gdp || "Not available",
      role: featured?.role || profile.subregion || profile.region || "Country profile",
      x: featured?.x ?? 50,
      y: featured?.y ?? 50,
    };
  });
}

export default function App() {
  const [screen, setScreen] = useState("landing");
  const [countryName, setCountryName] = useState("India");
  const [tab, setTab] = useState("dashboard");
  const [modal, setModal] = useState("");
  const [target, setTarget] = useState("China");
  const [reason, setReason] = useState("Economic");
  const [events, setEvents] = useState(initialEvents);
  const [actionResult, setActionResult] = useState(null);
  const [query, setQuery] = useState("");
  const [advisorQuestion, setAdvisorQuestion] = useState("");
  const [advisorMessages, setAdvisorMessages] = useState([]);
  const [advisorLoading, setAdvisorLoading] = useState(false);
  const [advisorError, setAdvisorError] = useState("");
  const advisorEndRef = useRef(null);
  const [showAdvisor, setShowAdvisor] = useState(false);
  const [notice, setNotice] = useState("");
  const [turn, setTurn] = useState(1);
  const [countryList, setCountryList] = useState([]);
  const [countryDataLoading, setCountryDataLoading] = useState(true);
  const [countryDataError, setCountryDataError] = useState("");

  useEffect(() => {
    let cancelled = false;
    getAllCountryProfiles()
      .then((profiles) => {
        if (!cancelled) {
          setCountryList(buildCountryList(profiles));
          setCountryDataError("");
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setCountryDataError(error?.message || "Country data could not be loaded.");
          setCountryList([]);
        }
      })
      .finally(() => {
        if (!cancelled) setCountryDataLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const handleCountrySelect = (name) => {
    const normalized = canonicalCountryName(name);
    const match = countryList.find((item) => item.name === normalized);
    setCountryName(match?.name || normalized);
  };

  // If the country API is unavailable or a map feature is not in its response,
  // still show the country that was clicked instead of silently reverting to India.
  const country = countryList.find((c) => c.name === countryName) || {
    name: countryName,
    officialName: countryName,
    flag: "🌐",
    flagImage: "",
    capital: "Not available",
    population: "Not available",
    region: "Not available",
    subregion: "Not available",
    area: "Not available",
    currency: "Not available",
    languages: "Not available",
    economy: "Not rated",
    military: "Not rated",
    stability: 50,
    color: "#38bdf8",
    gdp: "Not available",
    role: "Country profile",
  };
  const targetCountry = countryList.find((c) => c.name === target) || countryList.find((c) => c.name !== country.name) || countryList[0] || country;
  const filteredCountries = countryList.filter((c) => c.name.toLowerCase().includes(query.toLowerCase()) || c.officialName?.toLowerCase().includes(query.toLowerCase()));
  useEffect(() => {
    if (countryList.length && !countryList.some((c) => c.name === target)) {
      setTarget(countryList.find((c) => c.name !== country.name)?.name || countryList[0].name);
    }
  }, [countryList, target, country.name]);

  function openGame() {
    setScreen("select");
    setNotice("");
  }

  useEffect(() => {
    advisorEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [advisorMessages, advisorLoading, advisorError]);

  async function sendAdvisorQuestion(event) {
    event.preventDefault();
    const text = advisorQuestion.trim();
    if (!text || advisorLoading) return;

    const history = advisorMessages.slice(-16);
    setAdvisorMessages([...advisorMessages, { role: "user", text }]);
    setAdvisorQuestion("");
    setAdvisorError("");
    setAdvisorLoading(true);

    try {
      const result = await askAdvisor(countryName.trim().toLowerCase().replace(/\s+/g, "-"), text, history);
      setAdvisorMessages((previous) => [...previous, { role: "advisor", text: result.reply }]);
    } catch (error) {
      // No advice was produced: take the question back out of the thread so the delegate can simply retry.
      setAdvisorMessages((previous) => previous.slice(0, -1));
      setAdvisorQuestion(text);
      setAdvisorError(error?.message || "The advisor could not respond. Please retry.");
    } finally {
      setAdvisorLoading(false);
    }
  }

  function enterGame() {
  setScreen("game");
  setTab("conference");
  setTurn(1);
  setActionResult(null);
  setShowAdvisor(false);
  setAdvisorMessages([]);
  setAdvisorError("");
  setEvents([
    {
      type: "alert",
      title: "Opening sanctions announced",
      detail: "The opposing delegation has opened the conference with sanctions.",
      time: "Opening move",
    },
    ...initialEvents.slice(1),
  ]);
}

  function submitAction(kind) {
    const names = {
      sanctions: "Sanctions proposal submitted",
      alliance: "Alliance proposal",
      aid: "Humanitarian aid proposal",
      negotiation: "Negotiation proposal",
    };
    const descriptions = {
      sanctions: `A simulated ${reason.toLowerCase()} sanctions proposal targeting ${target} has been submitted by ${country.name}.`,
      alliance: `${country.name} has proposed a diplomatic partnership with ${target}.`,
      aid: `${country.name} has proposed humanitarian and economic assistance involving ${target}.`,
      negotiation: `${country.name} has requested diplomatic negotiations with ${target}.`,
    };

    setActionResult({ title: names[kind], description: descriptions[kind], target, reason: kind === "sanctions" ? reason : kind });
    setEvents((old) => [
      { type: kind === "sanctions" ? "alert" : "deal", title: names[kind], detail: descriptions[kind], time: "Just now" },
      ...old,
    ]);
    setModal("");
    setScreen("result");
    setTurn((t) => t + 1);
  }

  return (
    <div className="politica-app">
      {/* Persistent animated Earth background shared by every app screen */}
      <div className="global-earth-background" aria-hidden="true">
        <RotatingEarth />
      </div>

      <header className="topbar">
        <button className="brand" onClick={() => setScreen("landing")}>
          <span className="brand-symbol"><Globe2 size={22} /></span>
          <span>POLITICA<small>DIPLOMACY IN ACTION</small></span>
        </button>
        <nav className="top-links">
          {screen === "landing" ? (
            <>
              <a href="#how">How it works</a>
              <a href="#features">Features</a>
              <a href="#about">About</a>
              <button className="button button-small" onClick={openGame}>Enter</button>
            </>
          ) : (
            <>
              <span className="live-indicator" /> SIMULATION LAB
              <button className="button button-small" onClick={() => setScreen("landing")}>Exit</button>
            </>
          )}
        </nav>
      </header>

      {screen === "landing" && (
        <main className="landing">
          <section className="landing-hero">
            <div className="hero-copy">
              <span className="eyebrow"><span className="live-indicator" /> INTERACTIVE DIPLOMACY SIMULATOR</span>
              <h1>Make decisions.<br />Shape <span>relationships.</span><br />See the consequences.</h1>
              <p>Step into the role of a nation and experience the high-stakes world of global diplomacy, trade, and alliances.</p>
              <button className="button button-large" onClick={openGame}>Start simulation <ArrowRight size={17} /></button>
              <div className="hero-stats">
                <div><Users /><span><b>Global nations</b><small>Represent a country</small></span></div>
                <div><Handshake /><span><b>Dynamic relations</b><small>Diplomacy and trade</small></span></div>
                <div><Activity /><span><b>Every choice matters</b><small>Explore consequences</small></span></div>
              </div>
            </div>
            <div className="hero-map-wrap">
              <div className="hero-glow" />
              <div className="floating-label label-one"><span className="live-indicator" /> DIPLOMATIC TENSION <b>RISING</b></div>
              <div className="floating-label label-two"><Globe2 size={14} /> GLOBAL OUTLOOK <b>LIVE SIMULATION</b></div>
            </div>
          </section>

          <section className="explore-world-section" id="explore-world">
            <div className="explore-world-heading">
              <div>
                <span className="eyebrow">EXPLORE THE WORLD</span>
                <h2>Every nation has <span>a story.</span></h2>
                <p>Explore global powers and discover the countries shaping international relations.</p>
              </div>
              <button className="button" onClick={openGame}>Choose your country <ArrowRight size={16} /></button>
            </div>
            <div className="explore-world-layout">
              <div className="explore-map">
                <WorldMap
  selectedCountry={countryName}
  onCountrySelect={handleCountrySelect}
  height={480}
/>
                <div className="explore-map-hint"><span className="live-indicator" /> HOVER OVER A COUNTRY · CLICK TO EXPLORE</div>
              </div>
              <div className="explore-country-panel">
                <span className="eyebrow">COUNTRY SPOTLIGHT</span>
                {countryDataError && <p className="panel-note">Country database could not load. Clicked country is shown, but full facts need an internet connection. {countryDataError}</p>}
                {countryDataLoading && <p className="panel-note">Loading country profiles…</p>}
                <div className="explore-flag">{country.flag}</div>
                <h3>{country.name}</h3>
                <p>{country.role}</p>
                <div className="explore-stat"><span>Capital</span><b>{country.capital || "Not available"}</b></div>
                <div className="explore-stat"><span>Population</span><b>{country.population || "Not available"}</b></div>
                <div className="explore-stat"><span>Region</span><b>{country.subregion || country.region || "Not available"}</b></div>
                <div className="explore-stat"><span>Currency</span><b>{country.currency || "Not available"}</b></div>
                <div className="explore-stat"><span>Languages</span><b>{country.languages || "Not available"}</b></div>
                <div className="explore-stat"><span>Area</span><b>{country.area || "Not available"}</b></div>
                <div className="explore-stat"><span>Economic position</span><b>{country.economy}</b></div>
                <div className="explore-stat"><span>Stability index</span><b>{country.stability}/100</b></div>
                <MiniBars value={country.stability} color="green" />
                <button className="button explore-select-button" onClick={openGame}>Represent {country.name} <ArrowRight size={16} /></button>
              </div>
            </div>
          </section>

          <section id="how" className="how-section">
            <div className="section-heading"><span className="eyebrow">THE PROCESS</span><h2>One world. <span>Infinite outcomes.</span></h2><p>Your diplomatic journey unfolds in three stages.</p></div>
            <div className="steps-grid">
              <div className="step-card"><span className="step-number">01</span><div className="step-icon"><Globe2 /></div><h3>Choose a country</h3><p>Understand your nation's strengths, interests, and international position.</p></div>
              <div className="step-card"><span className="step-number">02</span><div className="step-icon"><Landmark /></div><h3>Make decisions</h3><p>Negotiate, build alliances, propose sanctions, or offer support.</p></div>
              <div className="step-card"><span className="step-number">03</span><div className="step-icon"><TrendingUp /></div><h3>See the impact</h3><p>Track how diplomatic choices change your relationships and the world.</p></div>
            </div>
          </section>

          <section id="features" className="feature-strip">
            <div><Shield /><b>Strategic decisions</b><span>Weigh risks and rewards.</span></div>
            <div><Map /><b>A living world map</b><span>See relationships at a glance.</span></div>
            <div><BarChart3 /><b>Global analytics</b><span>Understand the bigger picture.</span></div>
            <div><MessageSquare /><b>Diplomatic dialogue</b><span>Practice negotiation and policy.</span></div>
          </section>
          <footer id="about" className="site-footer"><span>POLITICA © 2026</span><span>A learning simulation. Not a real-world policy tool.</span><span>OBSERVE · NEGOTIATE · DECIDE</span></footer>
        </main>
      )}

      {screen === "select" && (
        <main className="select-screen">
          <div className="page-heading"><div><span className="eyebrow">STEP 01 / DELEGATION</span><h1>Choose your country</h1><p>Select a nation to begin your diplomatic journey.</p></div><span className="step-pill">01 <span>/ 04</span></span></div>
          <div className="selection-layout">
            <section className="panel country-picker">
              <div className="panel-heading"><div><h2>Available delegations</h2><p>Choose the country you will represent.</p></div><span className="count-pill">{countryList.length} COUNTRIES</span></div>
              <label className="search-box"><Search size={17} /><input placeholder="Search countries..." value={query} onChange={(e) => setQuery(e.target.value)} /></label>
              {countryDataLoading && <p className="panel-note">Loading country profiles…</p>}
              {countryDataError && <p className="panel-note">Could not load the full country dataset. Showing available fallback profiles. {countryDataError}</p>}
              <div className="country-list">
                {filteredCountries.map((c) => (
                  <button key={c.name} className={`country-option ${countryName === c.name ? "selected" : ""}`} onClick={() => handleCountrySelect(c.name)}>
                    <span className="flag">{c.flag}</span><span className="country-option-copy"><b>{c.name}</b><small>{c.role}</small></span><span className="country-status"><i style={{ background: c.color }} />{countryName === c.name ? "Selected" : "Available"}</span>{countryName === c.name && <Check size={16} />}
                  </button>
                ))}
              </div>
              <div className="picker-footer"><Shield size={15} /> Country profiles use public country facts; simulation ratings are illustrative.</div>
            </section>
            <section className="panel map-selection">
              <div className="panel-heading"><div><h2>Explore the world</h2><p>Select a highlighted country or use the list.</p></div><span className="map-live"><i /> MAP VIEW</span></div>
              <WorldMap
  selectedCountry={countryName}
  onCountrySelect={handleCountrySelect}
  height={520}
/>
              <div className="selected-country-card"><span className="flag flag-large">{country.flag}</span><div><small>YOUR DELEGATION</small><h3>{country.name}</h3><p>{country.capital} · {country.role}</p></div><button className="button" onClick={enterGame}>Enter simulation <ArrowRight size={16} /></button></div>
            </section>
          </div>
          <div className="page-footnote"><span>POLITICA / DELEGATION SELECTION</span><span>Choose carefully. Every nation has different interests.</span></div>
        </main>
      )}

      {screen === "game" && (
        <div className="simulation-layout">
          <aside className="sidebar">
            <div className="sidebar-country"><span className="flag">{country.flag}</span><div><b>{country.name}</b><small>YOUR DELEGATION</small></div></div>
            <span className="sidebar-label">COMMAND CENTRE</span>
            {tabs.map(([id, label, Icon]) => <button key={id} className={`side-link ${tab === id ? "active" : ""}`} onClick={() => setTab(id)}><Icon size={17} />{label}{id === "events" && <span className="side-count">{events.length}</span>}</button>)}
            <div className="sidebar-bottom"><span className="live-indicator" /><span><b>Simulation active</b><small>Turn {String(turn).padStart(2, "0")} · Practice mode</small></span></div>
          </aside>
          <main className="game-main">
            <div className="game-topline"><div><span className="eyebrow">GLOBAL AFFAIRS / SIMULATION</span><h1>{tabs.find((t) => t[0] === tab)?.[1]}</h1><p>Monitor the world. Understand your position. Choose your next move.</p></div><div className="topline-actions"><span className="turn-badge"><Clock3 size={14} /> TURN {String(turn).padStart(2, "0")}</span><button className="icon-button" onClick={() => setShowAdvisor(!showAdvisor)} title="Toggle advisor"><MessageSquare size={17} /></button></div></div>
            {tab === "conference" && (
  <ConferenceRoom
    country={country}
    onExit={() => {
      setScreen("select");
      setShowAdvisor(false);
    }}
    onAdvisor={() => setShowAdvisor(true)}
  />
)}
            {tab === "dashboard" && <>
              <div className="metrics-grid"><Metric icon={Activity} label="Global stability" value="72/100" sub="Illustrative" color="green" /><Metric icon={ZapIcon} label="Global tension" value="41/100" sub="Moderate" color="red" /><Metric icon={Handshake} label="Active alliances" value="03" sub="Across the world" color="purple" /><Metric icon={Target} label="Your influence" value="68/100" sub="Regional standing" color="gold" /></div>
              <div className="dashboard-grid">
                <section className="panel map-panel"><div className="panel-heading"><div><h2>Geopolitical overview</h2><p>Country positions and regional activity</p></div><button className="text-link" onClick={() => setTab("map")}>Full map <ArrowRight size={14} /></button></div><WorldMap
  selectedCountry={countryName}
  onCountrySelect={handleCountrySelect}
  height={350}
/><div className="map-summary"><span><i className="legend-dot friendly" /> Partners</span><span><i className="legend-dot neutral" /> Neutral</span><span><i className="legend-dot hostile" /> Tensions</span></div></section>
                <section className="panel status-panel"><div className="panel-heading"><div><h2>National status</h2><p>{country.flag} {country.name}</p></div><button className="icon-button" onClick={() => setTab("countries")}><ArrowRight size={15} /></button></div><div className="status-line"><span>Economic strength</span><b>{country.economy}</b></div><MiniBars value={78} /><div className="status-line"><span>Military capability</span><b>{country.military}</b></div><MiniBars value={72} color="purple" /><div className="status-line"><span>Domestic stability</span><b>{country.stability}/100</b></div><MiniBars value={country.stability} color="green" /><div className="status-divider" /><div className="status-line"><span>Population</span><b>{country.population}</b></div><div className="status-line"><span>GDP (approx.)</span><b>{country.gdp}</b></div></section>
                <section className="panel event-panel"><div className="panel-heading"><div><h2>Diplomatic timeline</h2><p>Recent developments</p></div><button className="text-link" onClick={() => setTab("events")}>All events <ArrowRight size={14} /></button></div><div className="event-list">{events.slice(0, 3).map((e, i) => <div className="event-row" key={`${e.title}-${i}`}><span className={`event-icon ${e.type}`}>{e.type === "alert" ? <AlertTriangle size={15} /> : e.type === "deal" ? <Handshake size={15} /> : <Globe2 size={15} />}</span><div><b>{e.title}</b><p>{e.detail}</p><small>{e.time}</small></div></div>)}</div></section>
                <section className="panel actions-panel"><div className="panel-heading"><div><h2>Available diplomatic actions</h2><p>Choose a direction for your next move.</p></div></div><div className="action-grid">
                  <button className="diplomatic-action" onClick={() => setModal("sanctions")}><span className="action-symbol red"><Crosshair /></span><b>Propose sanctions</b><small>Apply economic or diplomatic pressure.</small><span className="action-cta">Configure action <ArrowRight size={14} /></span></button>
                  <button className="diplomatic-action" onClick={() => setModal("alliance")}><span className="action-symbol purple"><Handshake /></span><b>Form alliance</b><small>Build relationships and cooperation.</small><span className="action-cta">Explore partnership <ArrowRight size={14} /></span></button>
                  <button className="diplomatic-action" onClick={() => setModal("aid")}><span className="action-symbol green"><HeartHandshake /></span><b>Send aid</b><small>Offer humanitarian or economic support.</small><span className="action-cta">Prepare assistance <ArrowRight size={14} /></span></button>
                  <button className="diplomatic-action" onClick={() => setModal("negotiation")}><span className="action-symbol blue"><MessageSquare /></span><b>Open negotiations</b><small>Seek a diplomatic solution.</small><span className="action-cta">Start dialogue <ArrowRight size={14} /></span></button>
                </div></section>
              </div>
            </>}

            {tab === "map" && <section className="panel full-map-panel"><div className="panel-heading"><div><h2>World map</h2><p>Hover or select a highlighted country.</p></div></div><WorldMap
  selectedCountry={countryName}
  onCountrySelect={handleCountrySelect}
  height={520}
/><div className="country-chips">{countryList.map((c) => <button key={c.name} className={countryName === c.name ? "active" : ""} onClick={() => handleCountrySelect(c.name)}>{c.flag} {c.name}</button>)}</div></section>}

            {tab === "countries" && <section className="panel"><div className="panel-heading"><div><h2>Country intelligence</h2><p>Explore national profiles and strategic positions.</p></div><label className="search-box compact"><Search size={16} /><input placeholder="Search..." value={query} onChange={(e) => setQuery(e.target.value)} /></label></div><div className="country-table">{filteredCountries.map((c) => <button key={c.name} className="country-table-row" onClick={() => handleCountrySelect(c.name)}><span className="flag">{c.flag}</span><span><b>{c.name}</b><small>{c.role}</small></span><span><small>ECONOMY</small><b>{c.economy}</b></span><span><small>STABILITY</small><MiniBars value={c.stability} /></span><span className="table-arrow"><ArrowRight size={16} /></span></button>)}</div><div className="profile-detail"><span className="flag flag-large">{country.flag}</span><div><span className="eyebrow">SELECTED PROFILE</span><h2>{country.name}</h2><p>{country.capital} · {country.population} people · GDP {country.gdp}</p></div><span className="status-chip">{country.role}</span></div></section>}

            {tab === "events" && <section className="panel"><div className="panel-heading"><div><h2>Diplomatic events</h2><p>A timeline of activity in your simulation.</p></div><span className="count-pill">{events.length} EVENTS</span></div><div className="event-list event-list-large">{events.map((e, i) => <div className="event-row" key={`${e.title}-${i}`}><span className={`event-icon ${e.type}`}>{e.type === "alert" ? <AlertTriangle size={17} /> : <Handshake size={17} />}</span><div><b>{e.title}</b><p>{e.detail}</p><small>{e.time} · Practice simulation</small></div></div>)}</div></section>}

            {tab === "analytics" && <>
              <div className="metrics-grid"><Metric icon={Activity} label="Global stability" value="72/100" color="green" /><Metric icon={TrendingUp} label="Global tension" value="41/100" color="red" /><Metric icon={Handshake} label="Active alliances" value="03" color="purple" /><Metric icon={Target} label="Recorded actions" value={String(turn - 1).padStart(2, "0")} color="gold" /></div>
              <div className="analytics-grid"><section className="panel"><div className="panel-heading"><div><h2>Stability trend</h2><p>Illustrative values across recent turns</p></div></div><div className="chart"><div className="chart-y"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div><svg viewBox="0 0 500 220" preserveAspectRatio="none"><g className="chart-grid">{[25,65,105,145,185].map((y) => <line key={y} x1="0" y1={y} x2="500" y2={y} />)}</g><path d="M0 70 L55 90 L110 78 L165 115 L220 88 L275 95 L330 60 L385 80 L440 70 L500 100 L500 200 L0 200Z" fill="rgba(56,189,248,.08)" /><polyline points="0,70 55,90 110,78 165,115 220,88 275,95 330,60 385,80 440,70 500,100" fill="none" stroke="#38bdf8" strokeWidth="3" /></svg></div><div className="chart-x"><span>Turn 1</span><span>Turn 3</span><span>Turn 5</span><span>Turn 7</span><span>Turn 10</span></div></section><section className="panel"><div className="panel-heading"><div><h2>National indicators</h2><p>{country.name}</p></div></div>{[["Stability",country.stability],["Economic strength",78],["Military capability",72],["Diplomatic influence",68]].map(([label,value]) => <div className="indicator-row" key={label}><div className="status-line"><span>{label}</span><b>{value}/100</b></div><MiniBars value={value} /></div>)}</section></div>
            </>}
          </main>
        </div>
      )}

      {screen === "result" && <main className="result-screen"><div className="result-card"><div className="result-check"><Check size={28} /></div><span className="eyebrow">ACTION RECORDED / PRACTICE MODE</span><h1>{actionResult?.title || "Action recorded"}</h1><p>{actionResult?.description}</p><div className="result-impact"><div><span>TARGET</span><b>{countryList.find((c) => c.name === actionResult?.target)?.flag} {actionResult?.target}</b></div><div><span>ACTION TYPE</span><b>{actionResult?.reason}</b></div><div><span>SIMULATION TURN</span><b>{String(turn).padStart(2, "0")}</b></div></div><div className="notice-box"><AlertTriangle size={17} /><p>This is a frontend demonstration. It does not apply real sanctions or change real-world events.</p></div><div className="result-actions"><button className="button button-secondary" onClick={() => { setScreen("game"); setTab("dashboard"); }}>Return to dashboard</button><button className="button" onClick={() => { setScreen("game"); setTab("map"); }}>View world map <ArrowRight size={16} /></button></div></div></main>}

      {showAdvisor && screen === "game" && (
        <aside className="advisor-drawer">
          <div className="advisor-header">
            <div className="advisor-avatar"><MessageSquare size={18} /></div>
            <div><b>Diplomatic advisor</b><small>{countryName} delegation · advice only</small></div>
            <button className="icon-button" onClick={() => setShowAdvisor(false)}><X size={17} /></button>
          </div>
          <div className="advisor-chat">
            {advisorMessages.length === 0 && (
              <>
                <div className="advisor-message"><span className="eyebrow">STRATEGIC NOTE</span><p>Ask about your options, the likely reaction of other countries, or the cost of escalation. I advise from the live simulation state; you decide what to do.</p></div>
                <div className="advisor-suggestion"><b>Try asking</b><ul>{["What outcome matters most to us right now?", "How might the target country respond?", "Could negotiation achieve the same goal?"].map((q) => <li key={q}><button type="button" className="advisor-chip" onClick={() => setAdvisorQuestion(q)}>{q}</button></li>)}</ul></div>
              </>
            )}
            {advisorMessages.map((m, i) => <div key={i} className={`advisor-bubble ${m.role}`}>{m.text}</div>)}
            {advisorLoading && <div className="advisor-bubble advisor advisor-typing">Advisor is thinking…</div>}
            {advisorError && <p className="advisor-error" role="alert">{advisorError}</p>}
            <div ref={advisorEndRef} />
          </div>
          <form className="advisor-form" onSubmit={sendAdvisorQuestion}>
            <input placeholder="Ask your advisor..." value={advisorQuestion} maxLength={1000} disabled={advisorLoading} onChange={(e) => setAdvisorQuestion(e.target.value)} />
            <button className="button button-icon" aria-label="Send question" disabled={advisorLoading || !advisorQuestion.trim()}><Send size={16} /></button>
          </form>
        </aside>
      )}

      {modal && <div className="modal-backdrop" onClick={() => setModal("")}><section className="action-modal" onClick={(e) => e.stopPropagation()}><div className="modal-heading"><div><span className="eyebrow">DIPLOMATIC ACTION / CONFIGURATION</span><h2>{modal === "sanctions" ? "Propose sanctions" : modal === "alliance" ? "Form an alliance" : modal === "aid" ? "Send assistance" : "Open negotiations"}</h2></div><button className="icon-button" onClick={() => setModal("")}><X size={18} /></button></div><p className="modal-description">Configure your proposal. This demo records your selection locally.</p><label className="form-label">Target country</label><div className="select-wrap"><span className="flag">{targetCountry.flag}</span><select value={target} onChange={(e) => setTarget(e.target.value)}>{countryList.filter((c) => c.name !== country.name).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select><ChevronDown size={16} /></div><label className="form-label">Policy objective</label><div className="reason-options">{["Economic","Diplomatic","Security"].map((r) => <button key={r} className={reason === r ? "active" : ""} onClick={() => setReason(r)}>{r}</button>)}</div><div className="consequence-preview"><span className="eyebrow">CONSIDER BEFORE ACTING</span><p>{modal === "sanctions" ? "Sanctions can increase pressure but may also damage trade and diplomatic relations." : modal === "alliance" ? "An alliance can strengthen cooperation but may create new commitments." : modal === "aid" ? "Assistance can build trust and support stability but requires resources." : "Negotiations can reduce tensions but may require compromise."}</p></div><div className="modal-actions"><button className="button button-secondary" onClick={() => setModal("")}>Cancel</button><button className="button" onClick={() => submitAction(modal)}>{modal === "sanctions" ? "Submit proposal" : modal === "alliance" ? "Propose alliance" : modal === "aid" ? "Send proposal" : "Request talks"} <ArrowRight size={16} /></button></div></section></div>}
      {notice && <div className="toast">{notice}<button onClick={() => setNotice("")}><X size={14} /></button></div>}
    </div>
  );
}

function ZapIcon(props) {
  return <Activity {...props} />;
}