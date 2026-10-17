
import { useState } from "react";
import {
  Globe2, Eye, Users, Gavel, ArrowRight, ArrowLeft,
  LayoutDashboard, CalendarDays, MessageCircle, FileText,
  MapPin, Network, AlertTriangle, ChartNoAxesColumn,
  Search, Bell, Clock3, Sparkles, ShieldCheck, Activity,
  TrendingUp, Leaf, Layers, ChevronRight, Menu, X
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

const crises = [
  {
    title: "Maritime Tensions",
    description: "Disputed waters in the South China Sea",
    tag: "Escalating",
    color: "red",
    image: "sea",
  },
  {
    title: "Energy Supply Disruption",
    description: "Reduced exports from Norland",
    tag: "Developing",
    color: "amber",
    image: "energy",
  },
  {
    title: "Humanitarian Crisis",
    description: "Food shortages in the East Bloc region",
    tag: "Monitoring",
    color: "blue",
    image: "human",
  },
];

const timeline = [
  ["2m ago", "Trade sanctions proposal submitted"],
  ["12m ago", "Alliance meeting: East Bloc"],
  ["25m ago", "New trade route agreement signed"],
  ["40m ago", "Humanitarian aid proposal submitted"],
];

const diplomaticResponses = [
  ["🇺🇸", "United States", "We support increased maritime security..."],
  ["🇳🇴", "Norland", "These allegations are unfounded..."],
  ["🇨🇳", "China", "We call for restraint and oppose unilateral..."],
  ["🇪🇺", "European Union", "The situation requires immediate dialogue..."],
];

const countries = [
  ["🇳🇴", "Norland", "−12.3%", "−26%", "Low", "low"],
  ["🌐", "East Bloc", "−8.6%", "−15%", "Medium", "medium"],
  ["🇮🇳", "India", "−3.1%", "−5%", "Medium", "medium"],
  ["🇺🇸", "United States", "−2.4%", "−5%", "High", "high"],
  ["🇪🇺", "European Union", "−1.9%", "−4%", "High", "high"],
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

function WorldMap({ onCountrySelect }) {
  return (
    <div className="world-map">
      <div className="map-ocean-label atlantic-label">Atlantic Ocean</div>
      <div className="map-ocean-label arctic-label">Arctic Ocean</div>
      <div className="map-ocean-label indian-label">Indian Ocean</div>
      <div className="map-graticule" />

      <svg
        className="map-art"
        viewBox="0 0 850 440"
        preserveAspectRatio="xMidYMid slice"
        role="img"
        aria-label="Illustrative geopolitical world map with trade routes"
      >
        <defs>
          <pattern id="mapDots" width="7" height="7" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r=".8" fill="#ffffff" opacity=".35" />
          </pattern>
          <linearGradient id="mapLand" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#d7d0c1" />
            <stop offset="100%" stopColor="#b4c4b7" />
          </linearGradient>
          <filter id="mapShadow">
            <feDropShadow dx="0" dy="2" stdDeviation="2" floodOpacity=".1" />
          </filter>
        </defs>

        <g className="landmass" filter="url(#mapShadow)">
          <path fill="#637f96" d="M30 80 L66 55 110 58 135 38 175 50 192 80 228 87 244 115 222 138 197 141 183 165 156 174 145 208 119 219 103 192 80 177 75 151 49 133 25 113Z" />
          <path fill="#71899a" d="M155 207 L181 221 193 244 182 266 165 291 150 319 132 333 121 310 124 279 111 255 124 233Z" />
          <path fill="#829a9a" d="M237 295 L273 284 300 299 321 323 309 355 295 382 280 414 263 391 252 358 232 337Z" />
          <path fill="#b6a58e" d="M350 81 L374 62 404 66 427 83 447 78 470 89 482 111 464 129 442 124 432 143 410 143 399 159 374 150 359 125 340 115Z" />
          <path fill="#a4b4a5" d="M365 157 L399 150 430 167 443 197 431 229 414 254 393 271 377 247 362 219 348 192Z" />
          <path fill="#819c9c" d="M421 65 L461 49 507 56 540 48 577 61 615 55 654 77 689 72 730 96 759 115 745 137 706 141 685 161 658 163 638 184 611 174 591 155 563 155 548 137 515 137 493 117 464 120 449 96Z" />
          <path fill="#bc9c8c" d="M638 183 L667 174 696 187 709 212 697 236 674 245 655 231 639 208Z" />
          <path fill="#9bafa0" d="M531 170 L560 166 585 186 595 211 583 235 566 248 547 229 535 207Z" />
          <path fill="#b7c1aa" d="M708 271 L743 260 775 274 794 300 775 322 750 313 735 292Z" />
          <path fill="#b8a78e" d="M775 340 L800 331 821 344 813 363 790 371Z" />
          <path fill="#c6b9a7" d="M297 65 L321 54 336 68 325 85 308 87Z" />
        </g>

        <g className="country-lines">
          <path d="M60 90 L99 121 91 156 136 168 176 140 212 116" />
          <path d="M138 68 L145 113 176 140 164 175" />
          <path d="M151 229 L180 251 150 278 164 310" />
          <path d="M261 307 L289 329 279 362 297 386" />
          <path d="M374 83 L389 108 424 104 451 92" />
          <path d="M376 168 L402 194 394 222 416 240" />
          <path d="M453 80 L475 101 501 92 524 124 551 106" />
          <path d="M530 169 L551 192 575 188 589 216" />
          <path d="M588 76 L605 107 644 103 670 126 703 113" />
          <path d="M644 187 L668 208 690 200" />
        </g>

        <g className="trade-routes">
          <path className="route route-blue" d="M132 153 Q245 61 386 124 T580 194" />
          <path className="route route-orange" d="M388 125 Q436 240 547 211 T738 293" />
          <path className="route route-red" d="M425 109 Q518 72 605 115 T675 204" />
          <path className="route route-blue" d="M264 336 Q380 255 432 196 T644 184" />
          <path className="route route-orange" d="M177 148 Q264 220 396 181 T562 224" />
        </g>

        <g className="map-node node-blue">
          <circle cx="132" cy="153" r="5" /><circle cx="386" cy="124" r="5" />
          <circle cx="580" cy="194" r="5" /><circle cx="644" cy="184" r="5" />
        </g>
        <g className="map-node node-orange">
          <circle cx="388" cy="125" r="5" /><circle cx="547" cy="211" r="5" />
          <circle cx="738" cy="293" r="5" /><circle cx="396" cy="181" r="5" />
        </g>
        <g className="map-node node-red">
          <circle cx="605" cy="115" r="6" /><circle cx="675" cy="204" r="6" />
        </g>
      </svg>

      <button className="map-control map-zoom-plus" onClick={() => onCountrySelect("World overview")} aria-label="Zoom in">+</button>
      <button className="map-control map-zoom-minus" onClick={() => onCountrySelect("World overview")} aria-label="Zoom out">−</button>
      <button className="map-control map-layers" onClick={() => onCountrySelect("Map layers")} aria-label="View map layers"><Layers size={17} /></button>

      <button className="country-marker marker-us" onClick={() => onCountrySelect("United States")}>
        <span>🇺🇸</span><span><strong>United States</strong><small>Stable · Trade +2.1%</small></span>
      </button>
      <button className="country-marker marker-eu" onClick={() => onCountrySelect("European Union")}>
        <span>🇪🇺</span><span><strong>European Union</strong><small>Mediating</small></span>
      </button>
      <button className="country-marker marker-ru" onClick={() => onCountrySelect("Russia")}>
        <span>🇷🇺</span><span><strong>Russia</strong><small>Under sanctions</small></span>
      </button>
      <button className="country-marker marker-cn" onClick={() => onCountrySelect("China")}>
        <span>🇨🇳</span><span><strong>China</strong><small>Watching</small></span>
      </button>
      <button className="country-marker marker-in" onClick={() => onCountrySelect("India")}>
        <span>🇮🇳</span><span><strong>India</strong><small>Active · Trade +3.4%</small></span>
      </button>

      <div className="map-legend">
        <span><i className="legend-blue" /> Alliance</span>
        <span><i className="legend-dashed" /> Trade route</span>
        <span><i className="legend-red" /> Conflict</span>
        <span><i className="legend-orange" /> Crisis</span>
      </div>
    </div>
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

function Dashboard({ role, onChangeProfile }) {
  const [activePage, setActivePage] = useState("World Overview");
  const [selectedCountry, setSelectedCountry] = useState("");
  const [search, setSearch] = useState("");
  const [showNotifications, setShowNotifications] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);

  const isGuest = role.id === "guest";
  const isJury = role.id === "jury";

  const visibleCrises = crises.filter((crisis) =>
    `${crisis.title} ${crisis.description}`.toLowerCase().includes(search.toLowerCase())
  );

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
          <div className="session-meta"><span>Round 2</span><strong>01:24:15</strong></div>
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
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search country, resolution, crisis..." />
            <kbd>⌘ K</kbd>
          </label>
          <div className="toolbar-spacer" />
          <span className="live-status"><i /> Live Simulation</span>
          <span className="round-label">Round 2</span>
          <span className="toolbar-clock"><Clock3 size={14} /> 01:24:15</span>
          <div className="notification-wrap">
            <button className="icon-button" onClick={() => setShowNotifications(!showNotifications)} aria-label="Notifications">
              <Bell size={17} /><i />
            </button>
            {showNotifications && <div className="notification-popover"><strong>Notifications</strong><p>Three crises are currently being monitored.</p><p>A new resolution is awaiting debate.</p></div>}
          </div>
          <button className="profile-mini" onClick={onChangeProfile} title="Change profile">
            <span>{role.title === "Guest" ? "G" : role.title === "Jury Member" ? "J" : "P"}</span>
            <div><strong>{role.title}</strong><small>{isGuest ? "Observer" : isJury ? "Executive Board" : "India"}</small></div>
          </button>
        </header>

        <div className="dashboard-body">
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
              <strong>62.1</strong>
              <span>Global Stability Index</span>
              <small>↗ +4.3%</small>
              <svg viewBox="0 0 95 30" preserveAspectRatio="none" aria-label="Stability trend">
                <path d="M0 25 L12 22 L22 25 L35 13 L46 17 L58 9 L67 13 L79 3 L95 5" />
              </svg>
            </div>
          </section>

          <section className="map-section">
            <WorldMap onCountrySelect={setSelectedCountry} />
          </section>

          {selectedCountry && (
            <div className="country-detail">
              <div><MapPin size={16} /><strong>{selectedCountry}</strong><span>Selected on the world map</span></div>
              <button onClick={() => setSelectedCountry("")}>Close</button>
            </div>
          )}

          <section className="stat-grid">
            <div className="stat-card"><div className="stat-icon"><Globe2 size={19} /></div><div className="stat-content"><span>Global GDP</span><strong className="stat-negative">−2.4% <small>▼</small></strong><small>vs last round</small></div><div className="sparkline spark-pink"><svg viewBox="0 0 100 30"><path d="M0 25 L12 21 L22 23 L34 14 L44 19 L58 9 L69 13 L81 3 L100 10" /></svg></div></div>
            <div className="stat-card"><div className="stat-icon"><ChartNoAxesColumn size={19} /></div><div className="stat-content"><span>Trade Volume</span><strong className="stat-negative">−1.8% <small>▼</small></strong><small>vs last round</small></div><div className="mini-bars">{[8,12,10,17,20,25,29].map((height, i) => <i key={i} style={{ height }} />)}</div></div>
            <div className="stat-card"><div className="stat-icon"><Users size={19} /></div><div className="stat-content"><span>Diplomatic Tension</span><strong className="stat-tension">High</strong><small>Elevated this round</small></div><div className="sparkline spark-red"><svg viewBox="0 0 100 30"><path d="M0 23 L12 18 L24 21 L36 9 L48 12 L59 6 L72 13 L84 3 L100 7" /></svg></div></div>
            <div className="stat-card"><div className="stat-icon"><Leaf size={19} /></div><div className="stat-content"><span>Active Crises</span><strong>3</strong><small>Across 5 regions</small></div><div className="mini-bars bars-orange">{[9,14,19,24,20,29,24].map((height, i) => <i key={i} style={{ height }} />)}</div></div>
          </section>

          <section className="lower-grid">
            <div className="data-panel affected-panel">
              <div className="panel-title"><div><h2>Top Affected Countries</h2><span>Economic impact this round</span></div><button onClick={() => setActivePage("Countries")}>View all <ArrowRight size={13} /></button></div>
              <div className="country-table">
                <div className="table-row table-header"><span>Country</span><span>GDP Change</span><span>Trade Impact</span><span>Stability</span></div>
                {countries.map(([flag, name, gdp, trade, stability, level]) => (
                  <button className="table-row country-row" key={name} onClick={() => setSelectedCountry(name)}>
                    <span className="country-name"><b>{flag}</b>{name}</span><span className="change-negative">{gdp}</span><span>{trade}</span><span><i className={`stability-tag tag-${level}`}>{stability}</i></span>
                  </button>
                ))}
              </div>
            </div>

            <div className="data-panel trade-panel">
              <div className="panel-title"><div><h2>Trade &amp; Resource Flow</h2><span>Global movement by sector</span></div><button onClick={() => setActivePage("Trade & Economy")}>View all <ArrowRight size={13} /></button></div>
              <div className="resource-tabs"><button className="resource-active">Oil</button><button onClick={() => setSelectedCountry("Natural Gas flows")}>Natural Gas</button><button onClick={() => setSelectedCountry("Food flows")}>Food</button><button onClick={() => setSelectedCountry("Technology flows")}>Technology</button></div>
              <div className="trade-map">
                <svg viewBox="0 0 450 160" preserveAspectRatio="xMidYMid meet">
                  <path className="trade-land" d="M30 37 L65 20 98 32 111 53 91 67 72 62 55 78 39 61Z M85 82 L108 92 101 119 89 141 77 117Z M174 28 L193 20 212 30 230 27 251 42 241 53 215 48 205 62 187 51Z M195 62 L217 58 231 80 219 103 208 122 197 96Z M230 28 L270 19 312 30 333 24 359 42 385 46 396 61 371 71 346 64 331 80 306 69 284 73 265 55Z M351 91 L370 83 388 95 380 113 363 108Z" />
                  <path className="trade-route route-oil" d="M72 51 Q150 5 208 46 T360 57" />
                  <path className="trade-route route-gas" d="M105 107 Q174 58 214 81 T365 99" />
                  <path className="trade-route route-food" d="M211 45 Q270 111 301 77 T376 100" />
                  <path className="trade-route route-tech" d="M72 51 Q164 128 226 79 T362 57" />
                  {[[72,51],[208,46],[360,57],[105,107],[214,81],[365,99],[301,77]].map(([x,y], i) => <circle className={`trade-node node-${i % 3}`} key={i} cx={x} cy={y} r="4" />)}
                </svg>
              </div>
              <div className="trade-legend"><span><i className="legend-blue" /> Major trade route</span><span><i className="legend-orange" /> Disrupted route</span><span><i className="legend-navy" /> Resource hub</span></div>
            </div>
          </section>
        </div>
      </section>

      <aside className="dashboard-right">
        <section className="right-panel crisis-panel">
          <div className="right-panel-heading"><h2>Ongoing Crises</h2><button onClick={() => setActivePage("Crisis Center")}>View all</button></div>
          {visibleCrises.map((crisis) => (
            <button className="crisis-row" key={crisis.title} onClick={() => { setSelectedCountry(crisis.title); setActivePage("Crisis Center"); }}>
              <CrisisThumbnail type={crisis.image} />
              <span className="crisis-copy"><strong>{crisis.title}</strong><small>{crisis.description}</small></span>
              <span className={`crisis-tag crisis-${crisis.color}`}>{crisis.tag}</span>
            </button>
          ))}
          {visibleCrises.length === 0 && <p className="empty-search">No matching crises.</p>}
        </section>

        <section className="right-panel timeline-panel">
          <div className="right-panel-heading"><h2>Live Session Timeline</h2><button onClick={() => setActivePage("Agenda")}>View all</button></div>
          <div className="timeline-list">
            {timeline.map(([time, text], i) => <div className="timeline-entry" key={text}><time>{time}</time><span className={`timeline-node timeline-node-${i}`} /><p>{text}</p></div>)}
          </div>
        </section>

        <section className="right-panel responses-panel">
          <div className="right-panel-heading"><h2>AI Diplomatic Responses</h2><button onClick={() => setActivePage("Debate Hall")}>View all</button></div>
          {diplomaticResponses.map(([flag, name, text]) => <button className="response-row" key={name} onClick={() => setSelectedCountry(`${name} diplomatic response`)}><span className="response-flag">{flag}</span><span><strong>{name}</strong><small>{text}</small></span></button>)}
        </section>

        <section className="ai-insight-panel">
          <div className="insight-heading"><Sparkles size={16} /><h2>AI Insight</h2><span>BETA</span></div>
          <div className="insight-content"><span className="insight-sun">☼</span><p>Norland is likely to strengthen its alliances if the current sanctions persist.</p></div>
          <small className="illustrative-note">Illustrative insight · Not a live prediction</small>
        </section>

        <button className="change-profile-right" onClick={onChangeProfile}><ArrowLeft size={15} /> Change profile</button>
      </aside>
    </main>
  );
}

export default function App() {
  const [role, setRole] = useState(null);

  function changeProfile() {
    setRole(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <div className="app-root">
      {role ? (
        <Dashboard key={role.id} role={role} onChangeProfile={changeProfile} />
      ) : (
        <RoleSelection onSelect={setRole} />
      )}
    </div>
  );
}
