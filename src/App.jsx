import { useEffect, useRef, useState } from "react";
import { useSimulation } from "./hooks/useSimulation.js";
import WorldMap from "./components/WorldMap.jsx";
import CountryPanel from "./components/CountryPanel.jsx";
import {
  countryNames, formatGdp, stabilityLabel, stabilityLevel, timeAgo, tradeVolumeByCountry, worldTotals, titleCase,
} from "./lib/worldView.js";
import {
  Globe2, Eye, Users, Gavel, ArrowRight, ArrowLeft,
  LayoutDashboard, CalendarDays, MessageCircle, FileText,
  Network, AlertTriangle, ChartNoAxesColumn,
  Search, Bell, ShieldCheck, Activity, RotateCcw, Handshake, Ban,
  Menu, X
} from "lucide-react";

const roles = [
  {
    id: "guest",
    title: "Guest",
    subtitle: "Observe the world",
    description: "Explore global events, crises and diplomatic developments.",
    icon: Eye,
    color: "guest",
    detail: "Read-only access",
  },
  {
    id: "participant",
    title: "Participant",
    subtitle: "Shape the outcome",
    description: "Represent a country, negotiate alliances and propose resolutions.",
    icon: Users,
    color: "participant",
    detail: "Delegate access",
  },
  {
    id: "jury",
    title: "Jury Member",
    subtitle: "Guide the proceedings",
    description: "Observe debate, review delegates and oversee the committee.",
    icon: Gavel,
    color: "jury",
    detail: "Executive board access",
  },
];

const navItems = [
  { label: "World Overview", icon: LayoutDashboard },
  { label: "Agenda", icon: CalendarDays },
  { label: "Debate Hall", icon: MessageCircle },
  { label: "Resolutions", icon: FileText },
  { label: "Countries", icon: Globe2 },
  { label: "Trade & Economy", icon: Network },
  { label: "Crisis Center", icon: AlertTriangle },
  { label: "Analytics", icon: ChartNoAxesColumn },
];

function Brand({ compact = false }) {
  return (
    <div className={`brand ${compact ? "brand-compact" : ""}`}>
      <div className="brand-emblem">
        <Globe2 size={compact ? 21 : 31} strokeWidth={1.35} />
      </div>
      <div>
        <div className="brand-name">MUN SIMULATOR</div>
        <div className="brand-caption">DIPLOMACY IN ACTION</div>
      </div>
    </div>
  );
}

function RoleSelection({ onSelect }) {
  return (
    <main className="profile-page">
      <header className="profile-topbar">
        <Brand />
        <div className="profile-top-right">
          <span className="status-pill"><span className="live-dot" /> SIMULATION ONLINE</span>
          <span className="edition-label">GLOBAL EDITION · 2026</span>
        </div>
      </header>

      <section className="profile-intro">
        <div className="intro-eyebrow">
          <span className="intro-line" />
          YOUR WORLD. YOUR PERSPECTIVE.
          <span className="intro-line" />
        </div>
        <h1>Who's entering the <em>simulation?</em></h1>
        <p>
          Choose your profile to enter a world where every decision
          changes the course of diplomacy.
        </p>
      </section>

      <section className="profile-grid" aria-label="Choose your role">
        {roles.map((role, index) => {
          const Icon = role.icon;
          return (
            <button
              className={`profile-card profile-${role.color}`}
              key={role.id}
              onClick={() => onSelect(role)}
              style={{ "--profile-index": index }}
            >
              <div className="profile-card-top">
                <span className="profile-number">0{index + 1}</span>
                <span className="profile-access">{role.detail}</span>
              </div>

              <div className="profile-art">
                <div className="art-orbit orbit-one" />
                <div className="art-orbit orbit-two" />
                <div className="art-glow" />
                <div className="profile-avatar">
                  <Icon size={48} strokeWidth={1.15} />
                </div>
                <span className="art-star star-one">✳</span>
                <span className="art-star star-two">✧</span>
                <span className="art-dot dot-one" />
                <span className="art-dot dot-two" />
              </div>

              <div className="profile-card-copy">
                <div className="profile-subtitle">{role.subtitle}</div>
                <h2>{role.title}</h2>
                <p>{role.description}</p>
              </div>

              <div className="profile-card-bottom">
                <span>Enter as {role.title.toLowerCase()}</span>
                <span className="profile-arrow"><ArrowRight size={18} /></span>
              </div>
            </button>
          );
        })}
      </section>

      <div className="profile-footnote">
        <ShieldCheck size={15} />
        <span>Your experience and available actions depend on your selected role.</span>
      </div>

      <footer className="profile-footer">
        <Brand compact />
        <span>A LIVING GEOPOLITICAL WORLD</span>
        <span>Observe · Negotiate · Decide</span>
      </footer>
    </main>
  );
}

function CrisisThumbnail({ type }) {
  return (
    <div className={`crisis-thumbnail thumbnail-${type}`}>
      {type === "sea" && <Globe2 size={25} />}
      {type === "energy" && <Activity size={25} />}
      {type === "human" && <Users size={25} />}
    </div>
  );
}

function StatusBanners({ sim }) {
  return (
    <>
      {sim.status === "ready" && sim.error && (
        <div className="sim-banner sim-banner-error" role="alert">
          <span>{sim.error}</span>
          <button onClick={sim.retry}>Retry</button>
        </div>
      )}
      {sim.notice && (
        <div className={`sim-banner sim-banner-${sim.notice.kind}`} role={sim.notice.kind === "error" ? "alert" : "status"}>
          <span>{sim.notice.text}</span>
          <button onClick={sim.dismissNotice} aria-label="Dismiss message"><X size={13} /></button>
        </div>
      )}
    </>
  );
}

function Dashboard({ role, onChangeProfile, sim }) {
  const { world, events } = sim;
  const [activePage, setActivePage] = useState("World Overview");
  const [selectedId, setSelectedId] = useState("");
  const [actorId, setActorId] = useState("aurelia");
  const [search, setSearch] = useState("");
  const [resourceTab, setResourceTab] = useState("");
  const [showNotifications, setShowNotifications] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);

  const isGuest = role.id === "guest";
  const isJury = role.id === "jury";
  const term = search.trim().toLowerCase();

  const names = world ? countryNames(world) : {};
  const totals = world ? worldTotals(world) : null;
  const tradeVolume = world ? tradeVolumeByCountry(world) : {};
  const allianceNames = world ? [...new Set(world.countries.flatMap((c) => c.alliances))] : [];
  const resources = world ? [...new Set(world.trade_routes.map((r) => r.resource))].sort() : [];
  const activeResource = resources.includes(resourceTab) ? resourceTab : resources[0];

  const crises = totals
    ? totals.sanctions.map(({ actor, target }) => ({
        key: `${actor}-${target}`,
        title: `${names[actor]} sanctions ${names[target]}`,
        description: `${names[target]} lost GDP and stability; direct trade is cut off.`,
        target,
      }))
    : [];
  const visibleCrises = crises.filter((c) => `${c.title} ${c.description}`.toLowerCase().includes(term));
  const visibleCountries = world ? [...world.countries].filter((c) => c.name.toLowerCase().includes(term)).sort((a, b) => b.gdp - a.gdp) : [];
  const countryPanelRef = useRef(null);

    useEffect(() => {
      if (!selectedId || !countryPanelRef.current) return;

      countryPanelRef.current.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, [selectedId]);
  const selectCountry = (id) => setSelectedId(id);

  function handleReset() {
    if (window.confirm("Reset the simulation to its starting state? All events will be cleared.")) {
      setSelectedId("");
      sim.reset();
    }
  }

  const loadingOrError = sim.status !== "ready" || !world;
  const actorName = names[actorId] ?? "Aurelia";

  return (
    <main className="dashboard-page">
      <aside className={`dashboard-sidebar ${mobileNav ? "mobile-nav-open" : ""}`}>
        <div className="sidebar-brand">
          <Brand />
          <button className="mobile-close" onClick={() => setMobileNav(false)} aria-label="Close navigation"><X size={19} /></button>
        </div>

        <nav className="main-navigation">
          {navItems.map(({ label, icon: Icon }) => (
            <button
              key={label}
              className={`nav-item ${activePage === label ? "nav-active" : ""}`}
              onClick={() => { setActivePage(label); setMobileNav(false); }}
            >
              <Icon size={17} strokeWidth={1.7} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-session">
          <div className="session-label">CURRENT SESSION</div>
          <div className="session-name"><span className="session-emblem">🌐</span><div><strong>UNSC</strong><small>Global Security &amp;<br />Maritime Stability</small></div></div>
          <div className="session-progress"><span /></div>
          <div className="session-meta"><span>Turn {world ? world.turn : "–"}</span><strong>{world ? `${events.length} ${events.length === 1 ? "event" : "events"}` : "…"}</strong></div>
        </div>

        <button className="change-profile" onClick={onChangeProfile}>
          <ArrowLeft size={16} />
          <span>Change profile</span>
        </button>
        <div className="sidebar-decor">
          <div className="decor-lines" />
          <span>“Dialogue is the beginning of diplomacy.”</span>
        </div>
      </aside>

      <section className="dashboard-main">
        <header className="dashboard-toolbar">
          <button className="mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <label className="dashboard-search">
            <Search size={15} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search country or crisis..." />
          </label>
          <div className="toolbar-spacer" />
          <span className={`live-status ${sim.status === "error" ? "live-status-offline" : ""}`}><i /> {sim.status === "error" ? "Backend offline" : sim.status === "loading" ? "Connecting…" : "Live Simulation"}</span>
          <span className="round-label">Turn {world ? world.turn : "–"}</span>
          {!isGuest && (
            <button className="reset-button" onClick={handleReset} disabled={sim.busy || loadingOrError} title="Reset the simulation to its starting state">
              <RotateCcw size={13} /> Reset
            </button>
          )}
          <div className="notification-wrap">
            <button className="icon-button" onClick={() => setShowNotifications(!showNotifications)} aria-label="Notifications">
              <Bell size={17} />{events.length > 0 && <i />}
            </button>
            {showNotifications && (
              <div className="notification-popover">
                <strong>Latest events</strong>
                {events.length === 0 ? <p>No events yet.</p> : events.slice(0, 3).map((e) => <p key={e.id}>{e.message}</p>)}
              </div>
            )}
          </div>
          <button className="profile-mini" onClick={onChangeProfile} title="Change profile">
            <span>{role.title === "Guest" ? "G" : role.title === "Jury Member" ? "J" : "P"}</span>
            <div><strong>{role.title}</strong><small>{isGuest ? "Observer" : isJury ? "Executive Board" : actorName}</small></div>
          </button>
        </header>

        <div className="dashboard-body">
          <StatusBanners sim={sim} />

          {loadingOrError ? (
            <div className="sim-state" role={sim.status === "error" ? "alert" : "status"}>
              {sim.status === "error" ? (
                <>
                  <strong>The simulation is unavailable</strong>
                  <p>{sim.error}</p>
                  <button onClick={sim.retry}>Try again</button>
                </>
              ) : (
                <><strong>Loading the simulation…</strong><p>Fetching the current world state.</p></>
              )}
            </div>
          ) : (
            <>
              <section className="dashboard-hero">
                <div className="dashboard-hero-copy">
                  <div className="eyebrow">GLOBAL SIMULATION</div>
                  <h1>{activePage === "World Overview" ? <>Shaping a More<br />Stable World</> : activePage}</h1>
                  <p>{activePage === "World Overview" ? "Debate. Decide. See the real-world impact." : `Explore ${activePage.toLowerCase()} across the simulation.`}</p>
                </div>
                <div className="quote-block">
                  <span className="quote-mark">“</span>
                  <p>Diplomacy is the art<br />of turning complex realities<br />into shared possibilities.</p>
                  <small>— UNITED NATIONS</small>
                </div>
                <div className="stability-block">
                  <div className="stability-globe"><Globe2 size={52} strokeWidth={.8} /></div>
                  <strong>{totals.averageStability.toFixed(1)}</strong>
                  <span>Global Stability Index</span>
                  <small>Average of {world.countries.length} countries</small>
                </div>
              </section>

              <section className="map-section">
                <WorldMap world={world} selectedId={selectedId} onSelect={selectCountry} search={search} />
              </section>

              {selectedId && (
             <div ref={countryPanelRef} className="country-panel-scroll-target">
              <CountryPanel
                world={world}
                countryId={selectedId}
                canAct={!isGuest}
                actorId={actorId}
                onActorChange={setActorId}
                sim={sim}
                onClose={() => setSelectedId("")}
              />
              </div>
              )}

              <section className="stat-grid">
                <div className="stat-card"><div className="stat-icon"><Globe2 size={19} /></div><div className="stat-content"><span>Global GDP</span><strong>{formatGdp(totals.totalGdp)}</strong><small>{world.countries.length} countries</small></div></div>
                <div className="stat-card"><div className="stat-icon"><ChartNoAxesColumn size={19} /></div><div className="stat-content"><span>Trade Volume</span><strong>{totals.activeTradeVolume}</strong><small>{totals.activeRoutes} of {totals.totalRoutes} routes active</small></div></div>
                <div className="stat-card"><div className="stat-icon"><Ban size={19} /></div><div className="stat-content"><span>Active Sanctions</span><strong className={totals.sanctions.length ? "stat-tension" : ""}>{totals.sanctions.length}</strong><small>{totals.cutRoutes.length} {totals.cutRoutes.length === 1 ? "route" : "routes"} cut off</small></div></div>
                <div className="stat-card"><div className="stat-icon"><Handshake size={19} /></div><div className="stat-content"><span>Alliances</span><strong>{allianceNames.length}</strong><small>{events.length} {events.length === 1 ? "event" : "events"} recorded</small></div></div>
              </section>

              <section className="lower-grid">
                <div className="data-panel affected-panel">
                  <div className="panel-title"><div><h2>Countries</h2><span>GDP, trade and stability</span></div><button onClick={() => setActivePage("Countries")}>View all <ArrowRight size={13} /></button></div>
                  <div className="country-table">
                    <div className="table-row table-header"><span>Country</span><span>GDP</span><span>Trade volume</span><span>Stability</span></div>
                    {visibleCountries.map((c) => (
                      <button className="table-row country-row" key={c.id} onClick={() => selectCountry(c.id)}>
                        <span className="country-name"><b>{c.name[0]}</b>{c.name}</span><span>{formatGdp(c.gdp)}</span><span>{tradeVolume[c.id]}</span><span><i className={`stability-tag tag-${stabilityLevel(c.stability)}`}>{c.stability} · {stabilityLabel(c.stability)}</i></span>
                      </button>
                    ))}
                    {visibleCountries.length === 0 && <p className="empty-search">No matching countries.</p>}
                  </div>
                </div>

                <div className="data-panel trade-panel">
                  <div className="panel-title"><div><h2>Trade &amp; Resource Flow</h2><span>Routes by resource</span></div><button onClick={() => setActivePage("Trade & Economy")}>View all <ArrowRight size={13} /></button></div>
                  <div className="resource-tabs">
                    {resources.map((r) => <button key={r} className={r === activeResource ? "resource-active" : ""} onClick={() => setResourceTab(r)}>{titleCase(r)}</button>)}
                  </div>
                  <div className="trade-list">
                    {world.trade_routes.filter((r) => r.resource === activeResource).map((r) => (
                      <div key={r.id} className={`trade-row ${r.active ? "" : "trade-row-cut"}`}>
                        <span>{names[r.exporter]} → {names[r.importer]}</span>
                        <strong>{r.active ? `${r.volume} (${r.efficiency}%)` : "Cut off"}</strong>
                      </div>
                    ))}
                  </div>
                  <div className="trade-legend"><span><i className="legend-blue" /> Active route</span><span><i className="legend-orange" /> Cut off</span></div>
                </div>
              </section>
            </>
          )}
        </div>
      </section>

      <aside className="dashboard-right">
        <section className="right-panel crisis-panel">
          <div className="right-panel-heading"><h2>Ongoing Crises</h2><button onClick={() => setActivePage("Crisis Center")}>View all</button></div>
          {visibleCrises.map((crisis) => (
            <button className="crisis-row" key={crisis.key} onClick={() => { setSelectedId(crisis.target); setActivePage("Crisis Center"); }}>
              <CrisisThumbnail type="sea" />
              <span className="crisis-copy"><strong>{crisis.title}</strong><small>{crisis.description}</small></span>
              <span className="crisis-tag crisis-red">Sanction</span>
            </button>
          ))}
          {visibleCrises.length === 0 && <p className="empty-search">{world ? "No active crises." : "Waiting for the simulation…"}</p>}
        </section>

        <section className="right-panel timeline-panel">
          <div className="right-panel-heading"><h2>Live Session Timeline</h2><button onClick={() => setActivePage("Agenda")}>View all</button></div>
          <div className="timeline-list">
            {events.slice(0, 8).map((e, i) => <div className="timeline-entry" key={e.id}><time>{timeAgo(e.timestamp)}</time><span className={`timeline-node timeline-node-${i === 0 ? 0 : 1}`} /><p>{e.message}</p></div>)}
            {events.length === 0 && <p className="empty-search">{world ? "No events yet. Take an action to see it here." : "Waiting for the simulation…"}</p>}
          </div>
        </section>

        <section className="right-panel responses-panel">
          <div className="right-panel-heading"><h2>Alliances</h2><button onClick={() => setActivePage("Countries")}>View all</button></div>
          {world && allianceNames.map((name) => {
            const members = world.countries.filter((c) => c.alliances.includes(name));
            return (
              <button className="response-row" key={name} onClick={() => setSelectedId(members[0].id)}>
                <span className="response-flag"><Handshake size={16} /></span>
                <span><strong>{name}</strong><small>{members.map((m) => m.name).join(", ")}</small></span>
              </button>
            );
          })}
          {world && allianceNames.length === 0 && <p className="empty-search">No alliances.</p>}
        </section>

        <button className="change-profile-right" onClick={onChangeProfile}><ArrowLeft size={15} /> Change profile</button>
      </aside>
    </main>
  );
}

export default function App() {
  const [role, setRole] = useState(null);
  const sim = useSimulation();

  function changeProfile() {
    setRole(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <div className="app-root">
      {role ? (
        <Dashboard key={role.id} role={role} onChangeProfile={changeProfile} sim={sim} />
      ) : (
        <RoleSelection onSelect={setRole} />
      )}
    </div>
  );
}