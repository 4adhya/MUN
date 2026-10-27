import { useState } from "react";
import {
  AlertTriangle,
  Shield,
  Users,
  Vote,
  CheckCircle2,
  Activity,
  Globe2,
  MessageSquare,
  FileText,
  RotateCcw,
} from "lucide-react";

const INITIAL_METRICS = {
  cybersecurity: 60,
  trust: 50,
  tension: 40,
  economicRisk: 35,
};

const CRISIS_OPTIONS = [
  {
    id: "cyberattack",
    title: "Global Cyberattack",
    type: "Cybersecurity",
    severity: "High",
    description:
      "Multiple national infrastructure networks report a coordinated cyberattack. Delegates must coordinate cyber defence while avoiding an escalation based on unverified attribution.",
    affected: ["India", "United States", "China", "Algeria", "France"],
  },
  {
    id: "trade",
    title: "Strategic Trade Dispute",
    type: "Economic",
    severity: "Moderate",
    description:
      "A dispute over strategic goods has disrupted supply chains. Delegates must decide whether to negotiate, provide assistance, or impose restrictions.",
    affected: ["Algeria", "China", "United States", "India"],
  },
  {
    id: "humanitarian",
    title: "Regional Humanitarian Emergency",
    type: "Humanitarian",
    severity: "High",
    description:
      "A sudden emergency has displaced civilians and strained essential services. Delegates are asked to coordinate relief and protect critical supplies.",
    affected: ["Affected region", "Neighbouring states", "Aid partners"],
  },
];

const RESOLUTIONS = [
  {
    id: "cooperation",
    title: "International Cybersecurity Cooperation Pact",
    summary:
      "Create a shared incident-response framework, exchange verified threat information, and fund cyber resilience support.",
    effects: { cybersecurity: 15, trust: 8, tension: -10, economicRisk: -5 },
  },
  {
    id: "sanctions",
    title: "Coordinated Restrictive Measures",
    summary:
      "Apply targeted restrictions while requesting an independent investigation and maintaining diplomatic communication channels.",
    effects: { cybersecurity: 5, trust: -3, tension: 10, economicRisk: 8 },
  },
  {
    id: "relief",
    title: "Joint Assistance and De-escalation Plan",
    summary:
      "Coordinate assistance, establish a crisis hotline, and create a monitoring group to reduce the risk of further escalation.",
    effects: { cybersecurity: 4, trust: 12, tension: -12, economicRisk: -8 },
  },
];

const DEMO_DELEGATIONS = [
  { name: "United States", vote: "For" },
  { name: "France", vote: "For" },
  { name: "Japan", vote: "For" },
  { name: "China", vote: "Abstain" },
  { name: "Russia", vote: "Against" },
];

const styles = {
  page: { display: "grid", gap: 18, paddingBottom: 32 },
  panel: {
    background: "rgba(5, 20, 36, 0.94)",
    border: "1px solid #21445e",
    borderRadius: 14,
    padding: 20,
    color: "#e5f2ff",
    minWidth: 0,
  },
  muted: { color: "#9bb4c9", lineHeight: 1.65 },
  button: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    background: "#0b4266",
    border: "1px solid #287aa6",
    color: "#e5f6ff",
    borderRadius: 9,
    padding: "10px 14px",
    cursor: "pointer",
    font: "inherit",
  },
  input: {
    width: "100%",
    boxSizing: "border-box",
    background: "#081727",
    color: "#e5f2ff",
    border: "1px solid #21445e",
    borderRadius: 9,
    padding: 12,
    font: "inherit",
  },
  eyebrow: {
    color: "#38bdf8",
    letterSpacing: 2,
    fontSize: 11,
    fontWeight: 800,
  },
};

function MetricCard({ label, value, color, description }) {
  return (
    <div style={{ background: "#081727", border: "1px solid #21445e", borderRadius: 10, padding: 16 }}>
      <small style={{ color: "#9bb4c9" }}>{label}</small>
      <h2 style={{ color, margin: "10px 0" }}>{value}/100</h2>
      <div style={{ height: 5, background: "#1a3044", borderRadius: 9, overflow: "hidden" }}>
        <div style={{ width: `${value}%`, height: "100%", borderRadius: 9, background: color, transition: "width .35s ease" }} />
      </div>
      {description && <small style={{ color: "#819ab0", display: "block", marginTop: 8 }}>{description}</small>}
    </div>
  );
}

export default function CrisisCenter({ view = "crisis", country = { name: "India", flag: "🇮🇳" }, onResolutionPassed }) {
  const [crises, setCrises] = useState(CRISIS_OPTIONS);
  const [activeCrisisId, setActiveCrisisId] = useState("cyberattack");
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newSeverity, setNewSeverity] = useState("Moderate");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [response, setResponse] = useState("");
  const [statement, setStatement] = useState("");
  const [submittedResponses, setSubmittedResponses] = useState([]);
  const [selectedResolutionId, setSelectedResolutionId] = useState("cooperation");
  const [userVote, setUserVote] = useState("");
  const [votes, setVotes] = useState({});
  const [metrics, setMetrics] = useState(INITIAL_METRICS);
  const [appliedResolution, setAppliedResolution] = useState(null);
  const [message, setMessage] = useState("");
  const [turn, setTurn] = useState(1);

  const activeCrisis = crises.find((item) => item.id === activeCrisisId) || crises[0];
  const selectedResolution = RESOLUTIONS.find((item) => item.id === selectedResolutionId) || RESOLUTIONS[0];
  const alreadyApplied = Boolean(appliedResolution);

  function createCrisis(event) {
    event.preventDefault();
    const title = newTitle.trim();
    const description = newDescription.trim();
    if (!title || !description) {
      setMessage("Enter both a crisis title and a briefing.");
      return;
    }
    const crisis = {
      id: `custom-${Date.now()}`,
      title,
      type: "Custom crisis",
      severity: newSeverity,
      description,
      affected: [country.name, "Other participating delegations"],
    };
    setCrises((previous) => [crisis, ...previous]);
    setActiveCrisisId(crisis.id);
    setNewTitle("");
    setNewDescription("");
    setShowCreateForm(false);
    setMessage("Crisis created in this browser session.");
  }

  function submitResponse(event) {
    event.preventDefault();
    if (!response) {
      setMessage("Choose a response before submitting.");
      return;
    }
    const entry = {
      id: `${Date.now()}-${Math.random()}`,
      country: country.name,
      flag: country.flag || "🌐",
      response,
      statement: statement.trim(),
      crisis: activeCrisis.title,
      turn,
    };
    setSubmittedResponses((previous) => [entry, ...previous]);
    setStatement("");
    setMessage(`${country.name}'s response was recorded in the frontend demo.`);
  }

  function castVote(vote) {
    if (alreadyApplied) {
      setMessage("This demo resolution has already been applied. Reset the demo to try again.");
      return;
    }
    setUserVote(vote);
    setVotes((previous) => ({ ...previous, [country.name]: vote }));
    setMessage(`Your vote (${vote}) has been recorded for this demo.`);
  }

  function passResolution() {
    if (alreadyApplied) return;
    const demoVotes = { ...votes, [country.name]: userVote || "For" };
    const simulatedVotes = DEMO_DELEGATIONS.reduce((all, item) => {
      all[item.name] = item.vote;
      return all;
    }, {});
    const allVotes = { ...simulatedVotes, ...demoVotes };
    const voteValues = Object.values(allVotes);
    const forCount = voteValues.filter((vote) => vote === "For").length;
    const againstCount = voteValues.filter((vote) => vote === "Against").length;
    const passes = forCount > againstCount;

    if (!passes) {
      setMessage(`Resolution did not pass in the demo vote (${forCount} for, ${againstCount} against).`);
      return;
    }

    const nextMetrics = Object.fromEntries(
      Object.entries(metrics).map(([key, value]) => [
        key,
        Math.max(0, Math.min(100, value + (selectedResolution.effects[key] || 0))),
      ])
    );

    const result = {
      title: selectedResolution.title,
      effects: selectedResolution.effects,
      metrics: nextMetrics,
      votes: { for: forCount, against: againstCount, abstain: voteValues.filter((vote) => vote === "Abstain").length },
      crisis: activeCrisis.title,
      turn,
    };

    setMetrics(nextMetrics);
    setAppliedResolution(result);
    setTurn((previous) => previous + 1);
    setMessage(`Resolution passed (${forCount} for, ${againstCount} against). Illustrative world-state effects applied.`);
    onResolutionPassed?.(result);
  }

  function resetDemo() {
    setMetrics(INITIAL_METRICS);
    setAppliedResolution(null);
    setVotes({});
    setUserVote("");
    setSubmittedResponses([]);
    setTurn(1);
    setMessage("The Phase 7 demo has been reset.");
  }

  const metricCards = [
    ["Cybersecurity", metrics.cybersecurity, "#38bdf8", "Higher is better"],
    ["International Trust", metrics.trust, "#34d399", "Higher is better"],
    ["Diplomatic Tension", metrics.tension, "#fb7185", "Lower is better"],
    ["Economic Risk", metrics.economicRisk, "#fbbf24", "Lower is better"],
  ];

  const heading = view === "resolutions"
    ? "Resolutions & Voting"
    : view === "impact"
      ? "Living World"
      : "Crisis Center";

  return (
    <div style={styles.page}>
      <section style={styles.panel}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 14 }}>
          <div>
            <span style={styles.eyebrow}>PHASE 7 / CRISIS ENGINE</span>
            <h2 style={{ margin: "8px 0" }}>{heading}</h2>
            <p style={styles.muted}>A frontend prototype for crisis briefings, country responses, resolution voting and deterministic world-state changes.</p>
          </div>
          <button type="button" style={styles.button} onClick={resetDemo}><RotateCcw size={15} /> Reset demo</button>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
          <span style={{ ...styles.button, cursor: "default" }}><Activity size={14} /> Turn {String(turn).padStart(2, "0")}</span>
          <span style={{ ...styles.button, cursor: "default" }}><Globe2 size={14} /> {country.flag || "🌐"} {country.name}</span>
          <span style={{ ...styles.button, cursor: "default" }}>{alreadyApplied ? "Resolution applied" : "Practice mode"}</span>
        </div>
      </section>

      {view === "crisis" && (
        <>
          <section style={styles.panel}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
              <h3 style={{ margin: 0 }}><AlertTriangle size={18} style={{ verticalAlign: "middle", color: "#fbbf24" }} /> Active crisis briefing</h3>
              <button type="button" style={styles.button} onClick={() => setShowCreateForm((show) => !show)}>
                {showCreateForm ? "Cancel" : "＋ Create crisis"}
              </button>
            </div>

            {showCreateForm && (
              <form onSubmit={createCrisis} style={{ display: "grid", gap: 12, marginTop: 16 }}>
                <input style={styles.input} value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="Crisis title" maxLength={100} />
                <textarea style={{ ...styles.input, resize: "vertical" }} rows={3} value={newDescription} onChange={(event) => setNewDescription(event.target.value)} placeholder="Write the crisis briefing..." maxLength={1000} />
                <select style={styles.input} value={newSeverity} onChange={(event) => setNewSeverity(event.target.value)}>
                  <option>Low</option><option>Moderate</option><option>High</option><option>Critical</option>
                </select>
                <button type="submit" style={styles.button}>Create briefing</button>
              </form>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, marginTop: 16 }}>
              {crises.map((crisis) => (
                <button key={crisis.id} type="button" onClick={() => setActiveCrisisId(crisis.id)} style={{
                  textAlign: "left", padding: 14, borderRadius: 10, cursor: "pointer", color: "#e5f2ff",
                  background: activeCrisisId === crisis.id ? "#10344d" : "#081727",
                  border: `1px solid ${activeCrisisId === crisis.id ? "#38bdf8" : "#21445e"}`,
                }}>
                  <small style={{ color: "#38bdf8" }}>{crisis.type} · {crisis.severity}</small>
                  <strong style={{ display: "block", marginTop: 8 }}>{crisis.title}</strong>
                </button>
              ))}
            </div>

            {activeCrisis && (
              <div style={{ marginTop: 18, padding: 18, background: "#081727", border: "1px solid #21445e", borderRadius: 10 }}>
                <span style={styles.eyebrow}>SITUATION REPORT</span>
                <h3>{activeCrisis.title}</h3>
                <p style={styles.muted}>{activeCrisis.description}</p>
                <p><strong>Severity:</strong> {activeCrisis.severity}</p>
                <p><strong>Affected parties:</strong> {activeCrisis.affected.join(" · ")}</p>
              </div>
            )}
          </section>

          <section style={styles.panel}>
            <h3><Shield size={18} style={{ verticalAlign: "middle" }} /> Submit your country's response</h3>
            <p style={styles.muted}>Choose a policy response and submit a short statement as your delegation.</p>
            <form onSubmit={submitResponse} style={{ display: "grid", gap: 12 }}>
              <select style={styles.input} value={response} onChange={(event) => setResponse(event.target.value)}>
                <option value="">Choose a response</option>
                <option value="International cooperation">International cooperation</option>
                <option value="Emergency negotiations">Request emergency negotiations</option>
                <option value="Targeted sanctions">Propose targeted sanctions</option>
                <option value="Defensive measures">Strengthen defensive measures</option>
                <option value="Humanitarian assistance">Offer humanitarian assistance</option>
              </select>
              <textarea style={{ ...styles.input, resize: "vertical" }} rows={3} value={statement} onChange={(event) => setStatement(event.target.value)} placeholder={`Write ${country.name}'s diplomatic statement...`} maxLength={1200} />
              <div><button type="submit" style={styles.button}>Submit country response</button></div>
            </form>
            {submittedResponses.length > 0 && (
              <div style={{ marginTop: 18 }}>
                <h4>Recorded responses</h4>
                {submittedResponses.map((item) => (
                  <div key={item.id} style={{ borderTop: "1px solid #21445e", padding: "12px 0" }}>
                    <strong>{item.flag} {item.country}</strong> · {item.response}
                    <p style={styles.muted}>{item.statement || "No additional statement provided."}</p>
                    <small style={{ color: "#819ab0" }}>{item.crisis} · Turn {item.turn}</small>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {view === "resolutions" && (
        <>
          <section style={styles.panel}>
            <h3><FileText size={18} style={{ verticalAlign: "middle" }} /> Draft resolution</h3>
            <p style={styles.muted}>Choose a proposal. Its predefined rules determine the illustrative world-state changes if it passes.</p>
            {RESOLUTIONS.map((resolution) => (
              <label key={resolution.id} style={{
                display: "flex", gap: 12, alignItems: "flex-start", padding: 15, marginTop: 10, borderRadius: 10,
                border: `1px solid ${selectedResolutionId === resolution.id ? "#38bdf8" : "#21445e"}`,
                background: selectedResolutionId === resolution.id ? "#10344d" : "#081727", cursor: "pointer",
              }}>
                <input type="radio" name="phase7-resolution" checked={selectedResolutionId === resolution.id} onChange={() => setSelectedResolutionId(resolution.id)} disabled={alreadyApplied} />
                <span><strong>{resolution.title}</strong><p style={styles.muted}>{resolution.summary}</p></span>
              </label>
            ))}
          </section>

          <section style={styles.panel}>
            <h3><Vote size={18} style={{ verticalAlign: "middle" }} /> Vote on the resolution</h3>
            <p style={styles.muted}>Your vote is recorded under your selected delegation. Other displayed votes are sample votes for the frontend demonstration.</p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {["For", "Against", "Abstain"].map((vote) => (
                <button key={vote} type="button" disabled={alreadyApplied} onClick={() => { setUserVote(vote); setVotes((previous) => ({ ...previous, [country.name]: vote })); setMessage(`Your vote (${vote}) has been recorded.`); }} style={{ ...styles.button, borderColor: userVote === vote ? "#38bdf8" : "#287aa6", opacity: alreadyApplied ? 0.6 : 1 }}>
                  {vote}
                </button>
              ))}
            </div>
            <div style={{ marginTop: 16, display: "grid", gap: 8 }}>
              {DEMO_DELEGATIONS.map((delegate) => (
                <div key={delegate.name} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: 10, background: "#081727", borderRadius: 8 }}>
                  <span>{delegate.name}</span><strong>{delegate.vote}</strong>
                </div>
              ))}
              {userVote && <div style={{ display: "flex", justifyContent: "space-between", padding: 10, border: "1px solid #287aa6", borderRadius: 8 }}><span>{country.name} (your delegation)</span><strong>{userVote}</strong></div>}
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 16 }}>
              <button type="button" style={{ ...styles.button, opacity: alreadyApplied ? 0.6 : 1 }} disabled={alreadyApplied} onClick={passResolution}>Calculate vote & apply resolution</button>
            </div>
            {appliedResolution && (
              <p style={{ color: "#34d399" }}><CheckCircle2 size={16} style={{ verticalAlign: "middle" }} /> Passed: {appliedResolution.title}</p>
            )}
          </section>
        </>
      )}

      {view === "impact" && (
        <section style={styles.panel}>
          <h3><Globe2 size={18} style={{ verticalAlign: "middle" }} /> Living world state</h3>
          <p style={styles.muted}>These values update in this component after a demo resolution passes. They are illustrative simulation scores, not real-world measurements.</p>
          {appliedResolution && (
            <div style={{ padding: 14, border: "1px solid #27644f", background: "#0b2927", borderRadius: 10, margin: "16px 0" }}>
              <strong><CheckCircle2 size={16} style={{ verticalAlign: "middle" }} /> Latest change: {appliedResolution.title}</strong>
              <p style={styles.muted}>Vote tally: {appliedResolution.votes.for} for · {appliedResolution.votes.against} against · {appliedResolution.votes.abstain} abstained.</p>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 8 }}>
                {Object.entries(appliedResolution.effects).map(([key, value]) => (
                  <div key={key} style={{ background: "#081727", borderRadius: 8, padding: 10 }}>
                    <small style={{ color: "#9bb4c9" }}>{key.replace(/([A-Z])/g, " $1")}</small>
                    <strong style={{ display: "block", marginTop: 6, color: value >= 0 ? "#34d399" : "#fb7185" }}>{value > 0 ? "+" : ""}{value}</strong>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginTop: 16 }}>
            {metricCards.map(([label, value, color, description]) => <MetricCard key={label} label={label} value={value} color={color} description={description} />)}
          </div>
          {!appliedResolution && <p style={styles.muted}>No resolution has been applied in this demo yet. Open Resolutions & Voting and calculate a passing vote to see the changes.</p>}
        </section>
      )}

      {message && (
        <div role="status" style={{ ...styles.panel, borderColor: "#287aa6" }}>
          <MessageSquare size={17} style={{ verticalAlign: "middle", color: "#38bdf8" }} /> {message}
        </div>
      )}
      <p style={{ ...styles.muted, fontSize: 12 }}>
        Demo limitation: crises, votes and scores are stored in React state and reset when this component is fully unmounted or the page is refreshed. Sample delegate votes are fictional. A backend is required for persistent shared sessions and authoritative voting.
      </p>
    </div>
  );
}
