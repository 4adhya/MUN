
import { useState } from "react";
import NameEntry from "./components/NameEntry";
import "./App.css";

const initialProfile = () => {
  try {
    return JSON.parse(localStorage.getItem("munProfile")) || null;
  } catch {
    return null;
  }
};

const scenarios = [
  {
    emoji: "🌐",
    title: "Global Cyberattack",
    committee: "UN Security Council",
    level: "Intermediate",
    description:
      "Countries must cooperate to respond to a worldwide cyberattack.",
  },
  {
    emoji: "🌱",
    title: "Climate Emergency",
    committee: "UN Environment Programme",
    level: "Beginner",
    description:
      "Negotiate an international agreement to address climate change.",
  },
  {
    emoji: "🕊️",
    title: "International Peace",
    committee: "UN Security Council",
    level: "Advanced",
    description:
      "Prevent an escalating international conflict through diplomacy.",
  },
];

function Dashboard({ profile, onChangeProfile }) {
  const [page, setPage] = useState("home");
  const [selectedScenario, setSelectedScenario] = useState(scenarios[0]);
  const [joinCode, setJoinCode] = useState("");
  const [message, setMessage] = useState("");
  const [speech, setSpeech] = useState("");
  const [votes, setVotes] = useState(null);

  function startSimulation(scenario) {
    setSelectedScenario(scenario);
    setMessage("");
    setSpeech("");
    setVotes(null);
    setPage("simulation");
  }

  function joinConference(event) {
    event.preventDefault();

    if (!joinCode.trim()) {
      setMessage("Please enter a conference code.");
      return;
    }

    setMessage(
      `Demo mode: conference ${joinCode.trim()} is ready to connect.`
    );
  }

  function submitSpeech(event) {
    event.preventDefault();

    if (!speech.trim()) {
      setMessage("Write your speech before submitting.");
      return;
    }

    setMessage(
      "Your speech has been recorded in this demo. Connect the AI backend to receive a delegate response and speech feedback."
    );
  }

  const navigation = [
    { id: "home", emoji: "🏠", label: "Home" },
    { id: "explore", emoji: "🌍", label: "Explore Crises" },
    { id: "join", emoji: "🔑", label: "Join Conference" },
    { id: "practice", emoji: "🤖", label: "AI Practice" },
    { id: "results", emoji: "🏆", label: "My Results" },
  ];

  return (
    <div className="mun-app">
      <header className="mun-navbar">
        <button
          className="mun-brand"
          onClick={() => setPage("home")}
          aria-label="Go to home"
        >
          <span className="mun-brand-icon">🌐</span>
          <span>
            <strong>MUNVERSE</strong>
            <small>DIPLOMACY IN ACTION</small>
          </span>
        </button>

        <div className="mun-user">
          <span className="mun-user-avatar">{profile.avatar}</span>
          <span className="mun-user-name">{profile.name}</span>
          <button
            className="mun-change-profile"
            onClick={onChangeProfile}
            title="Change your name or avatar"
          >
            Change
          </button>
        </div>
      </header>

      <div className="mun-layout">
        <aside className="mun-sidebar">
          <p className="mun-sidebar-label">YOUR COMMAND CENTRE</p>

          {navigation.map((item) => (
            <button
              key={item.id}
              className={`mun-nav-item ${
                page === item.id ? "active" : ""
              }`}
              onClick={() => {
                setMessage("");
                setPage(item.id);
              }}
            >
              <span>{item.emoji}</span>
              {item.label}
            </button>
          ))}

          <div className="mun-sidebar-bottom">
            <span>✨</span>
            <p>Your decisions shape the world.</p>
          </div>
        </aside>

        <main className="mun-main">
          {page === "home" && (
            <>
              <section className="mun-hero">
                <div className="mun-hero-content">
                  <span className="mun-eyebrow">
                    YOUR DIPLOMATIC JOURNEY STARTS HERE
                  </span>

                  <h1>
                    The world is in
                    <br />
                    <span>your hands.</span>
                  </h1>

                  <p>
                    Welcome, {profile.name}! Step into international
                    diplomacy, negotiate with AI delegates, and discover
                    how your decisions change the world.
                  </p>

                  <button
                    className="mun-primary-button"
                    onClick={() => setPage("explore")}
                  >
                    Start a Simulation <span>→</span>
                  </button>
                </div>

                <div className="mun-globe-art" aria-hidden="true">
                  <span className="mun-orbit orbit-one" />
                  <span className="mun-orbit orbit-two" />
                  <span className="mun-big-globe">🌍</span>
                  <span className="mun-floating-emoji">🤝</span>
                  <span className="mun-floating-star">✦</span>
                </div>
              </section>

              <section className="mun-section">
                <div className="mun-section-heading">
                  <div>
                    <span className="mun-eyebrow">YOUR NEXT MOVE</span>
                    <h2>Where will you begin?</h2>
                  </div>
                </div>

                <div className="mun-action-grid">
                  <button
                    className="mun-action-card"
                    onClick={() => setPage("explore")}
                  >
                    <span className="mun-action-icon">🌍</span>
                    <strong>Start Simulation</strong>
                    <span>Choose a global crisis and represent a country.</span>
                    <span className="mun-card-arrow">Explore →</span>
                  </button>

                  <button
                    className="mun-action-card"
                    onClick={() => setPage("join")}
                  >
                    <span className="mun-action-icon">🔑</span>
                    <strong>Join Conference</strong>
                    <span>Enter a room code to join your conference.</span>
                    <span className="mun-card-arrow">Join →</span>
                  </button>

                  <button
                    className="mun-action-card"
                    onClick={() => setPage("practice")}
                  >
                    <span className="mun-action-icon">🤖</span>
                    <strong>Practice with AI</strong>
                    <span>Prepare speeches and practise diplomacy.</span>
                    <span className="mun-card-arrow">Practise →</span>
                  </button>

                  <button
                    className="mun-action-card"
                    onClick={() => setPage("results")}
                  >
                    <span className="mun-action-icon">🏆</span>
                    <strong>My Results</strong>
                    <span>Review your diplomatic journey and progress.</span>
                    <span className="mun-card-arrow">View results →</span>
                  </button>
                </div>
              </section>

              <section className="mun-section">
                <div className="mun-section-heading">
                  <div>
                    <span className="mun-eyebrow">THE WORLD NEEDS YOU</span>
                    <h2>Explore global crises</h2>
                  </div>

                  <button
                    className="mun-text-button"
                    onClick={() => setPage("explore")}
                  >
                    View all →
                  </button>
                </div>

                <div className="mun-scenario-grid">
                  {scenarios.slice(0, 2).map((scenario) => (
                    <ScenarioCard
                      key={scenario.title}
                      scenario={scenario}
                      onClick={() => startSimulation(scenario)}
                    />
                  ))}
                </div>
              </section>
            </>
          )}

          {page === "explore" && (
            <section className="mun-section">
              <span className="mun-eyebrow">CHOOSE YOUR MISSION</span>
              <h1 className="mun-page-title">Explore global crises</h1>
              <p className="mun-page-description">
                Every crisis has a different challenge. Choose one to begin
                your diplomatic journey.
              </p>

              <div className="mun-scenario-grid">
                {scenarios.map((scenario) => (
                  <ScenarioCard
                    key={scenario.title}
                    scenario={scenario}
                    onClick={() => startSimulation(scenario)}
                  />
                ))}
              </div>
            </section>
          )}

          {page === "join" && (
            <section className="mun-centered-page">
              <div className="mun-feature-icon">🔑</div>
              <span className="mun-eyebrow">YOUR CONFERENCE AWAITS</span>
              <h1>Join a conference</h1>
              <p>
                Ask your conference organiser for the room code.
              </p>

              <form className="mun-join-form" onSubmit={joinConference}>
                <label htmlFor="conference-code">Conference code</label>
                <input
                  id="conference-code"
                  value={joinCode}
                  onChange={(event) => setJoinCode(event.target.value)}
                  placeholder="Enter your room code"
                  maxLength={40}
                />
                <button className="mun-primary-button" type="submit">
                  Join Conference →
                </button>
              </form>

              {message && <p className="mun-notice">{message}</p>}
            </section>
          )}

          {page === "practice" && (
            <section className="mun-centered-page">
              <div className="mun-feature-icon">🤖</div>
              <span className="mun-eyebrow">YOUR PERSONAL DIPLOMATIC COACH</span>
              <h1>Practise with AI</h1>
              <p>
                Choose a crisis to practise your arguments and prepare for
                international negotiations.
              </p>

              <div className="mun-practice-box">
                <label htmlFor="practice-scenario">Choose a scenario</label>
                <select
                  id="practice-scenario"
                  value={selectedScenario.title}
                  onChange={(event) => {
                    const scenario = scenarios.find(
                      (item) => item.title === event.target.value
                    );
                    setSelectedScenario(scenario);
                  }}
                >
                  {scenarios.map((scenario) => (
                    <option key={scenario.title} value={scenario.title}>
                      {scenario.title}
                    </option>
                  ))}
                </select>

                <button
                  className="mun-primary-button"
                  onClick={() => startSimulation(selectedScenario)}
                >
                  Begin AI Practice →
                </button>
              </div>
            </section>
          )}

          {page === "simulation" && (
            <section className="mun-section">
              <button
                className="mun-text-button"
                onClick={() => setPage("explore")}
              >
                ← Back to crises
              </button>

              <div className="mun-simulation-header">
                <span className="mun-feature-icon">
                  {selectedScenario.emoji}
                </span>
                <span className="mun-eyebrow">SIMULATION IN PROGRESS</span>
                <h1>{selectedScenario.title}</h1>
                <p>{selectedScenario.committee}</p>
                <p className="mun-page-description">
                  {selectedScenario.description}
                </p>
              </div>

              <div className="mun-info-grid">
                <div className="mun-info-card">
                  <span>👤</span>
                  <p>Your delegate</p>
                  <strong>
                    {profile.avatar} {profile.name}
                  </strong>
                </div>

                <div className="mun-info-card">
                  <span>🤖</span>
                  <p>AI delegates</p>
                  <strong>Ready to negotiate</strong>
                </div>
              </div>

              <div className="mun-panel">
                <h2>Make your opening statement</h2>
                <p>
                  Explain your proposed solution to the crisis. Your speech
                  will be ready for the next stage of the simulation.
                </p>

                <form onSubmit={submitSpeech}>
                  <textarea
                    value={speech}
                    onChange={(event) => setSpeech(event.target.value)}
                    placeholder="Honourable delegates, my country believes..."
                    rows={5}
                  />

                  <button className="mun-primary-button" type="submit">
                    Submit Speech →
                  </button>
                </form>

                {message && <p className="mun-notice">{message}</p>}
              </div>

              <div className="mun-panel">
                <h2>Resolution and voting</h2>
                <p>
                  In a full conference, delegates draft clauses, negotiate
                  amendments, and vote according to committee rules.
                </p>

                <button
                  className="mun-secondary-button"
                  onClick={() => {
                    setVotes(null);
                    setPage("results");
                  }}
                >
                  View Demo Outcome →
                </button>
              </div>
            </section>
          )}

          {page === "results" && (
            <section className="mun-centered-page">
              <div className="mun-feature-icon">🏆</div>
              <span className="mun-eyebrow">YOUR DIPLOMATIC JOURNEY</span>
              <h1>My Results</h1>
              <p>
                Your conference reports and performance feedback will appear
                here as you complete simulations.
              </p>

              <div className="mun-results-card">
                <span className="mun-result-emoji">🌍</span>
                <h2>Ready to make history?</h2>
                <p>
                  Complete a simulation to build your diplomatic portfolio.
                </p>

                <button
                  className="mun-primary-button"
                  onClick={() => setPage("explore")}
                >
                  Start a Simulation →
                </button>
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

function ScenarioCard({ scenario, onClick }) {
  return (
    <button className="mun-scenario-card" onClick={onClick}>
      <span className="mun-scenario-emoji">{scenario.emoji}</span>
      <span className="mun-scenario-level">{scenario.level}</span>
      <h3>{scenario.title}</h3>
      <p>{scenario.description}</p>
      <span className="mun-scenario-committee">{scenario.committee}</span>
      <span className="mun-card-arrow">Enter crisis →</span>
    </button>
  );
}

export default function App() {
  const [profile, setProfile] = useState(initialProfile);

  function handleEnter(newProfile) {
    localStorage.setItem("munProfile", JSON.stringify(newProfile));
    setProfile(newProfile);
  }

  function handleChangeProfile() {
    localStorage.removeItem("munProfile");
    setProfile(null);
  }

  if (!profile) {
    return <NameEntry onEnter={handleEnter} />;
  }

  return (
    <Dashboard
      profile={profile}
      onChangeProfile={handleChangeProfile}
    />
  );
}
