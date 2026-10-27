
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

export default function CrisisCenter() {
  const [crises, setCrises] = useState(() =>
    initialCrises.map((crisis) => ({ ...crisis, responses: [] }))
  );
  const [selectedId, setSelectedId] = useState(1);
  const [country, setCountry] = useState("Afghanistan");
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
            <h1 style={{ margin: 0, fontSize: 36 }}>Crisis Center</h1>
            <p style={{ color: "#8da9c3", marginBottom: 0 }}>
              Monitor the world. Understand your position. Choose your next move.
            </p>
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            <button style={buttonStyle} onClick={advanceTurn}>
              ◷ Turn {String(turn).padStart(2, "0")}
            </button>
            <button
              style={buttonStyle}
              onClick={() => setShowMessages((current) => !current)}
              aria-expanded={showMessages}
              aria-label="Toggle messages"
            >
              ▢ Messages ({messages.length})
            </button>
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
          PHASE 7 / CRISIS ENGINE
        </div>

        <h2 style={{ fontSize: 30 }}>Crisis Center</h2>
        <p style={{ color: "#9cb5ca", lineHeight: 1.7 }}>
          Review briefings, submit national responses and track crisis
          developments.
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

        {showCountryPicker && (
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

      {showMessages && (
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

      <p style={{ color: "#7994ad", fontSize: 12, textAlign: "center" }}>
        Practice demo · Changes are stored in component state and reset on page
        reload. No backend actions or real world consequences are performed.
      </p>
    </main>
  );
}
