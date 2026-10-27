
import React, { useState } from "react";

const initialCrises = [
  {
    id: 1,
    category: "Cybersecurity",
    severity: "High",
    title: "Global Cyberattack",
    description:
      "Multiple national infrastructure networks report a coordinated cyberattack. Delegates must coordinate cyber defence while avoiding escalation based on unverified attribution.",
    status: "Active",
    responses: [],
  },
  {
    id: 2,
    category: "Economic",
    severity: "Moderate",
    title: "Strategic Trade Dispute",
    description:
      "A major trade dispute threatens global supply chains. Delegates must negotiate trade protections and prevent further economic instability.",
    status: "Active",
    responses: [],
  },
  {
    id: 3,
    category: "Humanitarian",
    severity: "High",
    title: "Regional Humanitarian Emergency",
    description:
      "A regional emergency has displaced civilians and disrupted essential services. Delegates must coordinate aid and protect vulnerable populations.",
    status: "Active",
    responses: [],
  },
];

const countries = [
  "Afghanistan",
  "India",
  "China",
  "United States",
  "France",
  "United Kingdom",
  "Russia",
  "Japan",
  "Brazil",
];

const buttonStyle = {
  padding: "12px 18px",
  borderRadius: 10,
  border: "1px solid #2385aa",
  background: "#104466",
  color: "#e1f2ff",
  cursor: "pointer",
  fontSize: 15,
};

const inputStyle = {
  width: "100%",
  boxSizing: "border-box",
  padding: 12,
  borderRadius: 8,
  border: "1px solid #294d67",
  background: "#08182a",
  color: "#e1efff",
  marginTop: 7,
};

const panelStyle = {
  background: "rgba(5, 20, 37, 0.94)",
  border: "1px solid #234762",
  borderRadius: 18,
  padding: 24,
  marginBottom: 24,
};

export default function CrisisCenter({
  view = "crisis",
  country: initialCountry = { name: "Afghanistan", flag: "🇦🇫" },
  onResolutionPassed,
}) {
  const [crises, setCrises] = useState(() =>
    initialCrises.map((crisis) => ({ ...crisis, responses: [] }))
  );
  const [selectedId, setSelectedId] = useState(1);
  const [country, setCountry] = useState(() =>
    typeof initialCountry === "string"
      ? initialCountry
      : initialCountry?.name || "Afghanistan"
  );
  const [selectedResolution, setSelectedResolution] = useState("cyber-cooperation");
  const [userVote, setUserVote] = useState("");
  const [voteCounts, setVoteCounts] = useState({ For: 8, Against: 2, Abstain: 1 });
  const [resolutionPassed, setResolutionPassed] = useState(false);
  const [showCountryPicker, setShowCountryPicker] = useState(false);
  const [practiceMode, setPracticeMode] = useState(true);
  const [turn, setTurn] = useState(1);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [showMessages, setShowMessages] = useState(false);
  const [messages, setMessages] = useState([
    "Welcome to the Crisis Center. Review active crises and select your response.",
  ]);
  const [responseText, setResponseText] = useState("");
  const [notice, setNotice] = useState("");

  const [newTitle, setNewTitle] = useState("");
  const [newCategory, setNewCategory] = useState("Cybersecurity");
  const [newSeverity, setNewSeverity] = useState("High");
  const [newDescription, setNewDescription] = useState("");

  const selectedCrisis =
    crises.find((crisis) => crisis.id === selectedId) || crises[0];

  function resetDemo() {
    setCrises(initialCrises.map((crisis) => ({ ...crisis, responses: [] })));
    setSelectedId(1);
    setTurn(1);
    setCountry("Afghanistan");
    setPracticeMode(true);
    setShowCountryPicker(false);
    setShowCreateForm(false);
    setResponseText("");
    setMessages([
      "Demo reset. The initial crisis briefings have been restored.",
    ]);
    setNotice("Demo reset successfully.");
  }

  function advanceTurn() {
    setTurn((current) => current + 1);
    setNotice(`Advanced to Turn ${String(turn + 1).padStart(2, "0")}.`);
    setMessages((current) => [
      ...current,
      `Turn ${String(turn + 1).padStart(2, "0")} started.`,
    ]);
  }

  function createCrisis(event) {
    event.preventDefault();

    if (!newTitle.trim() || !newDescription.trim()) {
      setNotice("Enter a crisis title and description.");
      return;
    }

    const crisis = {
      id: Date.now(),
      title: newTitle.trim(),
      category: newCategory,
      severity: newSeverity,
      description: newDescription.trim(),
      status: "Active",
      responses: [],
    };

    setCrises((current) => [...current, crisis]);
    setSelectedId(crisis.id);
    setNewTitle("");
    setNewDescription("");
    setNewCategory("Cybersecurity");
    setNewSeverity("High");
    setShowCreateForm(false);
    setNotice("Crisis added to the local demo.");
    setMessages((current) => [
      ...current,
      `New crisis created: ${crisis.title}.`,
    ]);
  }

  function submitResponse(event) {
    event.preventDefault();

    if (!responseText.trim()) {
      setNotice("Write a response before submitting.");
      return;
    }

    const response = {
      country,
      turn,
      text: responseText.trim(),
      timestamp: new Date().toLocaleTimeString(),
    };

    setCrises((current) =>
      current.map((crisis) =>
        crisis.id === selectedId
          ? { ...crisis, responses: [...crisis.responses, response] }
          : crisis
      )
    );

    setMessages((current) => [
      ...current,
      `${country} submitted a response to ${selectedCrisis.title}: ${response.text}`,
    ]);

    setResponseText("");
    setNotice("Response saved in the local demo.");
  }

  function resolveCrisis() {
    if (!selectedCrisis || selectedCrisis.status === "Resolved") return;

    setCrises((current) =>
      current.map((crisis) =>
        crisis.id === selectedId
          ? { ...crisis, status: "Resolved" }
          : crisis
      )
    );

    setNotice(`${selectedCrisis.title} marked as resolved in the demo.`);
    setMessages((current) => [
      ...current,
      `${selectedCrisis.title} was marked as resolved.`,
    ]);
  }

  const resolutionOptions = [
    { id: "cyber-cooperation", title: "International Cybersecurity Cooperation", category: "Security", sponsor: "France, Japan", description: "Establish a shared incident-reporting network and coordinate technical assistance for critical infrastructure.", clauses: ["Create a voluntary cyber incident exchange", "Provide technical assistance to affected states", "Review implementation at the next conference turn"] },
    { id: "humanitarian-corridor", title: "Humanitarian Access and Safe Corridors", category: "Humanitarian", sponsor: "India, Brazil", description: "Coordinate safe access for relief agencies and protect civilians affected by regional emergencies.", clauses: ["Support impartial humanitarian access", "Coordinate emergency supplies with local authorities", "Publish a voluntary progress report"] },
    { id: "trade-stability", title: "Global Trade and Supply-Chain Stability", category: "Economy", sponsor: "Germany, Singapore", description: "Reduce supply-chain disruption through dialogue, transparent notices and temporary cooperation measures.", clauses: ["Open a diplomatic consultation channel", "Share non-sensitive supply-chain risk notices", "Avoid unilateral escalation during negotiations"] },
  ];
  const activeResolution = resolutionOptions.find((item) => item.id === selectedResolution) || resolutionOptions[0];

  function castVote(choice) {
    if (userVote) {
      setNotice(`Your delegation has already voted ${userVote}. Reset the demo to vote again.`);
      return;
    }
    setUserVote(choice);
    setVoteCounts((current) => ({ ...current, [choice]: current[choice] + 1 }));
    setNotice(`${country} voted ${choice} on “${activeResolution.title}”.`);
    setMessages((current) => [...current, `${country} voted ${choice} on ${activeResolution.title}.`]);
  }

  function submitResolutionResult() {
    const passed = voteCounts.For > voteCounts.Against;
    setResolutionPassed(passed);
    const result = { title: activeResolution.title, passed, votes: { ...voteCounts }, turn };
    onResolutionPassed?.(result);
    setNotice(passed ? `Resolution passed in this practice vote (${voteCounts.For} for, ${voteCounts.Against} against).` : `Resolution did not pass (${voteCounts.For} for, ${voteCounts.Against} against).`);
  }

  const sharedPageStyle = {
    minHeight: "100vh", background: "radial-gradient(ellipse at 65% 35%, #102c49 0%, #07182b 55%, #061322 100%)",
    color: "#dfedff", padding: "32px clamp(16px, 3vw, 42px)", fontFamily: "Inter, system-ui, sans-serif", boxSizing: "border-box",
  };
  const sectionStyle = { ...panelStyle, background: "rgba(5, 20, 37, 0.94)", borderColor: "#234762" };
  const pageTitle = view === "resolutions" ? "Resolutions & Voting" : view === "impact" ? "Living World" : "Crisis Center";

  if (view === "resolutions") {
    return (
      <main style={sharedPageStyle}>
        <header style={{ marginBottom: 28 }}>
          <div style={{ color: "#43c8ff", letterSpacing: 3, fontSize: 12, fontWeight: 700 }}>GLOBAL AFFAIRS / SIMULATION</div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap", marginTop: 12 }}>
            <div><h1 style={{ margin: 0, fontSize: 36 }}>{pageTitle}</h1><p style={{ color: "#8da9c3", marginBottom: 0 }}>Review proposals, cast your delegation’s vote and see the outcome.</p></div>
            <span style={buttonStyle}>◷ Turn {String(turn).padStart(2, "0")}</span>
          </div>
        </header>
        {notice && <div role="status" style={{ ...sectionStyle, padding: 14, color: "#68d5ff" }}>{notice}</div>}
        <section style={sectionStyle}>
          <div style={{ color: "#36caff", letterSpacing: 3, fontSize: 13, fontWeight: 700 }}>PHASE 6 / RESOLUTION & VOTING</div>
          <h2 style={{ fontSize: 30, marginBottom: 8 }}>Resolution agenda</h2>
          <p style={{ color: "#9cb5ca", lineHeight: 1.7 }}>Select a proposal to inspect its clauses and vote. Each delegation can cast one vote per demo round.</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 245px), 1fr))", gap: 14, marginTop: 20 }}>
            {resolutionOptions.map((item) => <button key={item.id} onClick={() => { setSelectedResolution(item.id); setUserVote(""); setResolutionPassed(false); setNotice(""); }} style={{ textAlign: "left", padding: 18, borderRadius: 12, border: `1px solid ${selectedResolution === item.id ? "#16c7ff" : "#294b65"}`, background: selectedResolution === item.id ? "#123750" : "#09192a", color: "#e0efff", cursor: "pointer" }}><small style={{ color: "#40caff" }}>{item.category} · Draft proposal</small><h3 style={{ margin: "10px 0" }}>{item.title}</h3><p style={{ color: "#8caac2", marginBottom: 0 }}>Sponsors: {item.sponsor}</p></button>)}
          </div>
        </section>
        <section style={sectionStyle}>
          <div style={{ color: "#36caff", letterSpacing: 2, fontSize: 12, fontWeight: 700 }}>SELECTED PROPOSAL</div>
          <h2>{activeResolution.title}</h2><p style={{ color: "#9cb5ca", lineHeight: 1.7 }}>{activeResolution.description}</p>
          <h3>Draft clauses</h3><ol style={{ lineHeight: 2 }}>{activeResolution.clauses.map((clause, index) => <li key={clause}>{clause}</li>)}</ol>
          <p style={{ color: "#9cb5ca" }}>Your delegation: <strong>{country}</strong></p>
          <h3>Cast your vote</h3>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>{["For", "Against", "Abstain"].map((choice) => <button key={choice} disabled={Boolean(userVote)} onClick={() => castVote(choice)} style={{ ...buttonStyle, opacity: userVote && userVote !== choice ? 0.55 : 1, borderColor: userVote === choice ? "#48d6a2" : "#2385aa", background: userVote === choice ? "#12513f" : buttonStyle.background }}>{userVote === choice ? "✓ " : ""}{choice}</button>)}</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12, marginTop: 22 }}>{["For", "Against", "Abstain"].map((choice) => <div key={choice} style={{ background: "#09192a", border: "1px solid #294b65", borderRadius: 10, padding: 16 }}><div style={{ color: "#8caac2" }}>{choice}</div><strong style={{ display: "block", fontSize: 28, marginTop: 8 }}>{voteCounts[choice]}</strong><div style={{ color: "#8caac2", fontSize: 12 }}>recorded votes</div></div>)}</div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 20 }}><button style={buttonStyle} onClick={submitResolutionResult}>Calculate outcome</button><button style={buttonStyle} onClick={() => { setUserVote(""); setVoteCounts({ For: 8, Against: 2, Abstain: 1 }); setResolutionPassed(false); setNotice("Voting round reset."); }}>Reset voting round</button></div>
          {resolutionPassed && <div style={{ marginTop: 18, padding: 16, borderRadius: 10, background: "#103a31", border: "1px solid #2d9279" }}><h3 style={{ marginTop: 0, color: "#7ce8bd" }}>Resolution passed</h3><p style={{ marginBottom: 0 }}>The practice vote shows more votes For than Against. The outcome is illustrative and does not represent a real UN vote.</p></div>}
          {resolutionPassed === false && notice.includes("did not pass") && <div style={{ marginTop: 18, padding: 16, borderRadius: 10, background: "#3a2029", border: "1px solid #9b485a" }}><h3 style={{ marginTop: 0 }}>Resolution not passed</h3><p style={{ marginBottom: 0 }}>There were not more votes For than Against in this practice vote.</p></div>}
        </section>
      </main>
    );
  }

  if (view === "impact") {
    const responseTotal = crises.reduce((sum, item) => sum + item.responses.length, 0);
    const resolvedTotal = crises.filter((item) => item.status === "Resolved").length;
    const stability = Math.max(20, Math.min(95, 72 + resolvedTotal * 6 - crises.filter((item) => item.status === "Active" && item.severity === "High").length * 4));
    const tension = Math.max(10, Math.min(95, 42 + crises.filter((item) => item.status === "Active").length * 7 - resolvedTotal * 8));
    const indicators = [["Global stability", stability, "Higher is better"], ["Diplomatic tension", tension, "Lower is better"], ["Active crises", crises.filter((item) => item.status === "Active").length, "Requires coordinated action"], ["National responses", responseTotal, "Submitted by delegations"]];
    return (
      <main style={sharedPageStyle}>
        <header style={{ marginBottom: 28 }}><div style={{ color: "#43c8ff", letterSpacing: 3, fontSize: 12, fontWeight: 700 }}>GLOBAL AFFAIRS / SIMULATION</div><h1 style={{ margin: "12px 0 6px", fontSize: 36 }}>{pageTitle}</h1><p style={{ color: "#8da9c3" }}>Track how diplomatic actions and crisis outcomes change the simulated world.</p></header>
        <section style={sectionStyle}><div style={{ color: "#36caff", letterSpacing: 3, fontSize: 13, fontWeight: 700 }}>PHASE 8 / WORLD IMPACT</div><h2 style={{ fontSize: 30 }}>Global situation overview</h2><p style={{ color: "#9cb5ca", lineHeight: 1.7 }}>These indicators are calculated from the current local demo state, not live geopolitical data.</p><div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 14, marginTop: 22 }}>{indicators.map(([label, value, description]) => <div key={label} style={{ background: "#09192a", border: "1px solid #294b65", borderRadius: 12, padding: 18 }}><div style={{ color: "#8caac2" }}>{label}</div><strong style={{ display: "block", fontSize: 32, margin: "10px 0" }}>{value}{label.includes("stability") || label.includes("tension") ? "/100" : ""}</strong><div style={{ color: "#8caac2", fontSize: 12 }}>{description}</div>{(label.includes("stability") || label.includes("tension")) && <div style={{ height: 6, background: "#1a3044", borderRadius: 8, marginTop: 12, overflow: "hidden" }}><div style={{ width: `${value}%`, height: "100%", background: label.includes("stability") ? "#34d399" : "#fb7185" }} /></div>}</div>)}</div></section>
        <section style={sectionStyle}><h2>Country-level effects</h2><p style={{ color: "#9cb5ca" }}>Delegation currently selected: <strong>{country}</strong></p><div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 14 }}>{crises.map((crisis) => <article key={crisis.id} style={{ background: "#09192a", border: "1px solid #294b65", borderRadius: 12, padding: 18 }}><small style={{ color: "#40caff" }}>{crisis.category} · {crisis.severity}</small><h3>{crisis.title}</h3><p style={{ color: "#9cb5ca" }}>{crisis.status === "Resolved" ? "Resolved: simulated pressure reduced." : "Active: continued diplomatic coordination is needed."}</p><div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}><span>Status</span><strong>{crisis.status}</strong></div><div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginTop: 8 }}><span>Responses logged</span><strong>{crisis.responses.length}</strong></div></article>)}</div></section>
        <section style={sectionStyle}><h2>Recent simulation activity</h2>{messages.slice(-6).reverse().map((message, index) => <div key={`${message}-${index}`} style={{ padding: "12px 0", borderBottom: "1px solid #203e56", color: "#b8d4e8" }}>{message}</div>)}<button style={{ ...buttonStyle, marginTop: 18 }} onClick={advanceTurn}>Advance simulation turn</button></section>
      </main>
    );
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        background:
          "radial-gradient(ellipse at 65% 35%, #102c49 0%, #07182b 55%, #061322 100%)",
        color: "#dfedff",
        padding: "32px clamp(16px, 3vw, 42px)",
        fontFamily: "Inter, system-ui, sans-serif",
        boxSizing: "border-box",
      }}
    >
      <header style={{ marginBottom: 32 }}>
        <div
          style={{
            color: "#43c8ff",
            letterSpacing: 3,
            fontSize: 12,
            fontWeight: 700,
          }}
        >
          GLOBAL AFFAIRS / SIMULATION
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 16,
            flexWrap: "wrap",
            marginTop: 12,
          }}
        >
          <div>
            <h1 style={{ margin: 0, fontSize: 36 }}>
              {view === "resolutions"
                ? "Resolutions & Voting"
                : view === "impact"
                  ? "Living World"
                  : "Crisis Center"}
            </h1>
            <p style={{ color: "#8da9c3", marginBottom: 0 }}>
              {view === "resolutions"
                ? "Review proposals, cast your delegation's vote and see the outcome."
                : view === "impact"
                  ? "Track how diplomatic decisions affect global stability."
                  : "Monitor the world. Understand your position. Choose your next move."}
            </p>
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            <button style={buttonStyle} onClick={advanceTurn}>
              ◷ Turn {String(turn).padStart(2, "0")}
            </button>
            {view === "crisis" && (
              <button
                style={buttonStyle}
                onClick={() => setShowMessages((current) => !current)}
                aria-expanded={showMessages}
                aria-label="Toggle messages"
              >
                ▢ Messages ({messages.length})
              </button>
            )}
          </div>
        </div>
      </header>

      {notice && (
        <div
          role="status"
          style={{
            ...panelStyle,
            padding: 14,
            color: "#68d5ff",
            marginBottom: 18,
          }}
        >
          {notice}
          <button
            onClick={() => setNotice("")}
            style={{
              ...buttonStyle,
              float: "right",
              padding: "3px 9px",
            }}
            aria-label="Dismiss notification"
          >
            ×
          </button>
        </div>
      )}

      <section style={panelStyle}>
        <div
          style={{
            color: "#36caff",
            letterSpacing: 3,
            fontSize: 13,
            fontWeight: 700,
          }}
        >
          {view === "resolutions"
            ? "PHASE 6 / RESOLUTION & VOTING"
            : view === "impact"
              ? "PHASE 8 / LIVING WORLD"
              : "PHASE 7 / CRISIS ENGINE"}
        </div>

        <h2 style={{ fontSize: 30 }}>
          {view === "resolutions"
            ? "Resolutions & Voting"
            : view === "impact"
              ? "Living World"
              : "Crisis Center"}
        </h2>
        <p style={{ color: "#9cb5ca", lineHeight: 1.7 }}>
          {view === "resolutions"
            ? "Evaluate proposed measures, cast a vote and review the simulated result."
            : view === "impact"
              ? "Explore illustrative changes to trust, security, tension and economic risk."
              : "Review briefings, submit national responses and track crisis developments."}
        </p>

        <div
          style={{
            display: "flex",
            gap: 12,
            flexWrap: "wrap",
            marginTop: 24,
          }}
        >
          <button style={buttonStyle} onClick={resetDemo}>
            ↺ Reset demo
          </button>

          <button
            style={buttonStyle}
            onClick={advanceTurn}
            title="Advance the local demo turn"
          >
            ϟ Turn {String(turn).padStart(2, "0")}
          </button>

          <button
            style={buttonStyle}
            onClick={() => setShowCountryPicker((current) => !current)}
            aria-expanded={showCountryPicker}
          >
            🌐 {country} ▾
          </button>

          <button
            style={{
              ...buttonStyle,
              background: practiceMode ? "#12516a" : "#252f40",
            }}
            onClick={() => {
              setPracticeMode((current) => !current);
              setNotice(
                practiceMode
                  ? "Practice mode turned off in the local UI."
                  : "Practice mode turned on."
              );
            }}
            aria-pressed={practiceMode}
          >
            {practiceMode ? "✓ Practice mode: ON" : "Practice mode: OFF"}
          </button>
        </div>

        {view === "crisis" && showCountryPicker && (
          <div style={{ marginTop: 18, maxWidth: 350 }}>
            <label htmlFor="country-select">Select your delegation</label>
            <select
              id="country-select"
              value={country}
              onChange={(event) => {
                setCountry(event.target.value);
                setShowCountryPicker(false);
                setNotice(`Selected delegation: ${event.target.value}.`);
              }}
              style={inputStyle}
            >
              {countries.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
        )}
      </section>

      {view === "crisis" && showMessages && (
        <section style={panelStyle}>
          <h2>Conference Messages</h2>
          <div
            style={{
              maxHeight: 240,
              overflowY: "auto",
              display: "grid",
              gap: 12,
            }}
          >
            {messages.map((message, index) => (
              <div
                key={`${index}-${message}`}
                style={{
                  padding: 12,
                  borderRadius: 8,
                  background: "#0b2034",
                  color: "#b8d4e8",
                }}
              >
                {message}
              </div>
            ))}
          </div>
        </section>
      )}

      {view === "crisis" && (
      <section style={panelStyle}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "center",
            flexWrap: "wrap",
            marginBottom: 22,
          }}
        >
          <h2 style={{ margin: 0 }}>⚠ Active crisis briefing</h2>
          <button
            style={buttonStyle}
            onClick={() => setShowCreateForm((current) => !current)}
            aria-expanded={showCreateForm}
          >
            {showCreateForm ? "Cancel" : "+ Create crisis"}
          </button>
        </div>

        {showCreateForm && (
          <form
            onSubmit={createCrisis}
            style={{
              ...panelStyle,
              background: "#09192b",
              marginBottom: 24,
            }}
          >
            <h3>Create a crisis</h3>

            <label htmlFor="crisis-title">Title</label>
            <input
              id="crisis-title"
              value={newTitle}
              onChange={(event) => setNewTitle(event.target.value)}
              style={inputStyle}
              maxLength={120}
              required
              placeholder="Enter crisis title"
            />

            <label htmlFor="crisis-category" style={{ display: "block", marginTop: 14 }}>
              Category
            </label>
            <select
              id="crisis-category"
              value={newCategory}
              onChange={(event) => setNewCategory(event.target.value)}
              style={inputStyle}
            >
              <option>Cybersecurity</option>
              <option>Economic</option>
              <option>Humanitarian</option>
              <option>Diplomatic</option>
              <option>Environmental</option>
            </select>

            <label htmlFor="crisis-severity" style={{ display: "block", marginTop: 14 }}>
              Severity
            </label>
            <select
              id="crisis-severity"
              value={newSeverity}
              onChange={(event) => setNewSeverity(event.target.value)}
              style={inputStyle}
            >
              <option>Low</option>
              <option>Moderate</option>
              <option>High</option>
              <option>Critical</option>
            </select>

            <label htmlFor="crisis-description" style={{ display: "block", marginTop: 14 }}>
              Description
            </label>
            <textarea
              id="crisis-description"
              value={newDescription}
              onChange={(event) => setNewDescription(event.target.value)}
              style={{ ...inputStyle, minHeight: 110, resize: "vertical" }}
              maxLength={2000}
              required
              placeholder="Describe the crisis and its impact"
            />

            <button type="submit" style={{ ...buttonStyle, marginTop: 16 }}>
              Create crisis
            </button>
          </form>
        )}

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 230px), 1fr))",
            gap: 14,
          }}
        >
          {crises.map((crisis) => {
            const selected = crisis.id === selectedId;

            return (
              <button
                key={crisis.id}
                onClick={() => {
                  setSelectedId(crisis.id);
                  setNotice(`Selected crisis: ${crisis.title}.`);
                }}
                aria-pressed={selected}
                style={{
                  textAlign: "left",
                  padding: 20,
                  minHeight: 125,
                  borderRadius: 14,
                  border: selected
                    ? "1px solid #16c7ff"
                    : "1px solid #294b65",
                  background: selected ? "#123750" : "#09192a",
                  color: "#e0efff",
                  cursor: "pointer",
                }}
              >
                <div style={{ color: "#40caff", marginBottom: 12 }}>
                  {crisis.category} · {crisis.severity}
                </div>
                <strong style={{ fontSize: 18, lineHeight: 1.5 }}>
                  {crisis.title}
                </strong>
                <div style={{ color: "#8caac2", marginTop: 10, fontSize: 13 }}>
                  {crisis.status} · {crisis.responses.length} responses
                </div>
              </button>
            );
          })}
        </div>

        {selectedCrisis && (
          <article
            style={{
              ...panelStyle,
              marginTop: 24,
              marginBottom: 0,
              background: "#09192a",
            }}
          >
            <div
              style={{
                color: "#39c9ff",
                letterSpacing: 3,
                fontSize: 12,
                fontWeight: 700,
              }}
            >
              SITUATION REPORT
            </div>

            <h2>{selectedCrisis.title}</h2>
            <p style={{ color: "#a1b9ce", lineHeight: 1.8 }}>
              {selectedCrisis.description}
            </p>

            <p>
              Status:{" "}
              <strong
                style={{
                  color:
                    selectedCrisis.status === "Resolved"
                      ? "#5ee0a0"
                      : "#ffc86a",
                }}
              >
                {selectedCrisis.status}
              </strong>
            </p>

            <h3>Delegation response</h3>
            <form onSubmit={submitResponse}>
              <label htmlFor="response">Your country's proposed response</label>
              <textarea
                id="response"
                value={responseText}
                onChange={(event) => setResponseText(event.target.value)}
                placeholder={`What should ${country} do about this crisis?`}
                style={{ ...inputStyle, minHeight: 100, resize: "vertical" }}
                maxLength={2000}
                disabled={selectedCrisis.status === "Resolved"}
              />
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  flexWrap: "wrap",
                  marginTop: 14,
                }}
              >
                <button
                  type="submit"
                  style={buttonStyle}
                  disabled={selectedCrisis.status === "Resolved"}
                >
                  Submit response
                </button>

                <button
                  type="button"
                  style={buttonStyle}
                  onClick={resolveCrisis}
                  disabled={selectedCrisis.status === "Resolved"}
                >
                  Mark resolved
                </button>
              </div>
            </form>

            {selectedCrisis.responses.length > 0 && (
              <div style={{ marginTop: 24 }}>
                <h3>Response history</h3>
                {selectedCrisis.responses.map((response, index) => (
                  <div
                    key={`${response.country}-${index}`}
                    style={{
                      borderTop: "1px solid #294b65",
                      padding: "14px 0",
                    }}
                  >
                    <strong>{response.country}</strong>
                    <span style={{ color: "#8caac2" }}>
                      {" "}· Turn {String(response.turn).padStart(2, "0")} ·{" "}
                      {response.timestamp}
                    </span>
                    <p style={{ color: "#b3c9dd", lineHeight: 1.7 }}>
                      {response.text}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </article>
        )}
      </section>
      )}

      {view === "resolutions" && (
        <section style={panelStyle}>
          <h2 style={{ marginTop: 0 }}>Active resolution</h2>
          <p style={{ color: "#9cb5ca", lineHeight: 1.7 }}>
            Choose a proposal, review its purpose and cast one vote for {country}.
            This is a local demonstration; votes are not sent to a backend.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))", gap: 12 }}>
            {[
              { id: "cyber-cooperation", title: "International Cybersecurity Cooperation", category: "Security", detail: "Create a voluntary channel for sharing verified cyber-threat intelligence and coordinating infrastructure protection." },
              { id: "humanitarian-aid", title: "Emergency Humanitarian Assistance", category: "Humanitarian", detail: "Coordinate emergency supplies, medical support and safe access for displaced civilians." },
              { id: "trade-dialogue", title: "Strategic Trade Dialogue", category: "Economy", detail: "Open negotiations to reduce supply-chain disruption and prevent unnecessary escalation." },
            ].map((resolution) => (
              <button key={resolution.id} type="button" onClick={() => { setSelectedResolution(resolution.id); setResolutionPassed(false); setUserVote(""); }} style={{ textAlign: "left", padding: 18, borderRadius: 12, border: selectedResolution === resolution.id ? "1px solid #16c7ff" : "1px solid #294b65", background: selectedResolution === resolution.id ? "#123750" : "#09192a", color: "#e0efff", cursor: "pointer" }}>
                <small style={{ color: "#40caff" }}>{resolution.category}</small>
                <h3 style={{ margin: "10px 0" }}>{resolution.title}</h3>
                <p style={{ color: "#9cb5ca", lineHeight: 1.6, marginBottom: 0 }}>{resolution.detail}</p>
              </button>
            ))}
          </div>
          <h3 style={{ marginTop: 24 }}>Cast your vote</h3>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {["For", "Against", "Abstain"].map((vote) => (
              <button key={vote} type="button" aria-pressed={userVote === vote} onClick={() => setUserVote(vote)} style={{ ...buttonStyle, background: userVote === vote ? "#087da2" : buttonStyle.background, borderColor: userVote === vote ? "#38d5ff" : buttonStyle.border }}>
                {userVote === vote ? "✓ " : ""}{vote}
              </button>
            ))}
            <button type="button" style={{ ...buttonStyle, opacity: userVote ? 1 : 0.55 }} disabled={!userVote || resolutionPassed} onClick={() => {
              const nextCounts = { ...voteCounts, [userVote]: voteCounts[userVote] + 1 };
              setVoteCounts(nextCounts);
              setResolutionPassed(true);
              const result = { title: selectedResolution === "humanitarian-aid" ? "Emergency Humanitarian Assistance" : selectedResolution === "trade-dialogue" ? "Strategic Trade Dialogue" : "International Cybersecurity Cooperation", vote: userVote, votes: nextCounts, turn };
              setNotice(`${country}'s vote (${userVote}) was recorded in the demo.`);
              setMessages((current) => [...current, `${country} voted ${userVote} on ${result.title}.`]);
              onResolutionPassed?.(result);
            }}>Submit vote</button>
          </div>
          {resolutionPassed && <p role="status" style={{ color: "#68d5ff", marginTop: 16 }}>Your vote has been recorded for this demo.</p>}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12, marginTop: 22 }}>
            {Object.entries(voteCounts).map(([label, count]) => <div key={label} style={{ ...panelStyle, marginBottom: 0, padding: 16, background: "#09192a" }}><span style={{ color: "#9cb5ca" }}>{label}</span><h2 style={{ marginBottom: 0 }}>{count}</h2></div>)}
          </div>
        </section>
      )}

      {view === "impact" && (
        <section style={panelStyle}>
          <h2 style={{ marginTop: 0 }}>Global stability indicators</h2>
          <p style={{ color: "#9cb5ca", lineHeight: 1.7 }}>Illustrative simulation metrics. These values demonstrate how decisions could influence the world state; they are not live real-world measurements.</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 14 }}>
            {[
              { label: "International trust", value: resolutionPassed ? 72 : 64, color: "#34d399", description: "Higher is better" },
              { label: "Cybersecurity readiness", value: resolutionPassed && selectedResolution === "cyber-cooperation" ? 81 : 58, color: "#38bdf8", description: "Higher is better" },
              { label: "Diplomatic tension", value: resolutionPassed && userVote === "For" ? 36 : 57, color: "#fb7185", description: "Lower is better" },
              { label: "Economic risk", value: resolutionPassed && selectedResolution === "trade-dialogue" ? 32 : 49, color: "#fbbf24", description: "Lower is better" },
            ].map((metric) => (
              <div key={metric.label} style={{ ...panelStyle, marginBottom: 0, padding: 18, background: "#09192a" }}>
                <span style={{ color: "#9cb5ca", fontSize: 13 }}>{metric.label}</span>
                <h2 style={{ color: metric.color, fontSize: 30, margin: "12px 0" }}>{metric.value}/100</h2>
                <div style={{ height: 6, borderRadius: 99, background: "#1a3044", overflow: "hidden" }}><div style={{ width: `${metric.value}%`, height: "100%", background: metric.color, borderRadius: 99 }} /></div>
                <small style={{ display: "block", marginTop: 9, color: "#819ab0" }}>{metric.description}</small>
              </div>
            ))}
          </div>
          <div style={{ ...panelStyle, marginTop: 18, marginBottom: 0, background: "#09192a" }}>
            <h3 style={{ marginTop: 0 }}>Latest simulation update</h3>
            <p style={{ color: "#b8d4e8", lineHeight: 1.7 }}>{resolutionPassed ? `Turn ${String(turn).padStart(2, "0")}: ${country} voted ${userVote} on the selected resolution. The indicators above show illustrative effects.` : "No resolution has been submitted during this session. Visit Resolutions & Voting to cast a practice vote and demonstrate possible world-state changes."}</p>
          </div>
        </section>
      )}

      <p style={{ color: "#7994ad", fontSize: 12, textAlign: "center" }}>
        Practice demo · Changes are stored in component state and reset on page
        reload. No backend actions or real world consequences are performed.
      </p>
    </main>
  );
}
