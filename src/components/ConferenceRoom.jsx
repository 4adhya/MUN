import OpponentCouncil from "./OpponentCouncil";
import ReportModal from "./ReportModal";
import { useState } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Check,
  Clock3,
  FileText,
  Handshake,
  Hand,
  Loader,
  MessageSquare,
  Radio,
  Send,
  ThumbsUp,
  UserRound,
  Shield,
  TrendingUp,
  X,
} from "lucide-react";
import WorldMap from "./WorldMap";
import "./ConferenceRoom.css";
import {
  proposeAI,
  aiFailureLabel,
  submitSpeech,
} from "../api/client.js";
import { useConference, phaseLabel, PHASE_SEQUENCE } from "../hooks/useConference.js";

const OPENING_MOVES = {
  India: {
    opponent: "China",
    flag: "🇨🇳",
    issue: "Critical minerals and resilient supply chains",
    action: "Supply-chain consultations",
    reason:
      "Delegates are discussing critical-mineral access, supply-chain resilience and the energy transition. The policy issue is real; the sanctions move and this specific dispute are simulated.",
    demand: "Begin transparent talks on critical-mineral supply chains",
  },
  China: {
    opponent: "United States",
    flag: "🇺🇸",
    issue: "Technology governance and strategic trade",
    action: "Technology-policy consultations",
    reason:
      "Delegates are examining technology access, export controls and strategic supply chains. These are real-world policy issues; the specific dispute and response in this room are simulated.",
    demand: "Open talks on technology safeguards and trade measures",
  },
  "United States": {
    opponent: "China",
    flag: "🇨🇳",
    issue: "Strategic technology and international trade",
    action: "Technology-policy consultations",
    reason:
      "Delegates are examining export controls, technology competition and international trade. These are real-world policy issues; the specific confrontation and actions in this room are simulated.",
    demand: "Open talks on technology safeguards and trade measures",
  },
  France: {
    opponent: "Russia",
    flag: "🇷🇺",
    issue: "European security and conflict prevention",
    action: "Emergency diplomatic consultations",
    reason:
      "Delegates are discussing European security, conflict prevention and diplomatic options for reducing escalation. The issue reflects real international-security debates; the specific scenario is simulated.",
    demand: "Support a monitored diplomatic de-escalation process",
  },
  "United Kingdom": {
    opponent: "Russia",
    flag: "🇷🇺",
    issue: "Maritime security and freedom of navigation",
    action: "Maritime security consultations",
    reason:
      "Delegates are considering risks to commercial shipping and freedom of navigation in strategically important waterways. The policy concern is real; this conference's dispute and actions are simulated.",
    demand: "Support a coordinated maritime de-escalation plan",
  },
  Russia: {
    opponent: "France",
    flag: "🇫🇷",
    issue: "Conflict prevention and regional security",
    action: "Emergency diplomatic consultations",
    reason:
      "Delegates are discussing conflict prevention, regional security and diplomatic options for reducing escalation. The policy area is real; the specific scenario and actions are simulated.",
    demand: "Review security concerns through a diplomatic process",
  },
  Japan: {
    opponent: "China",
    flag: "🇨🇳",
    issue: "Regional trade and economic resilience",
    action: "Trade-policy consultations",
    reason:
      "Delegates are examining trade resilience, supply-chain exposure and regional economic cooperation. These are real policy themes; the specific dispute and response are simulated.",
    demand: "Begin talks on regional trade cooperation",
  },
  Brazil: {
    opponent: "United States",
    flag: "🇺🇸",
    issue: "Food security, agriculture and climate shocks",
    action: "Food-security coordination proposal",
    reason:
      "Delegates are discussing how conflict, extreme weather and trade disruptions can affect food availability and agricultural livelihoods. The policy issue is real; this room's actions are simulated.",
    demand: "Coordinate measures to protect food supply and affordability",
  },
};

export default function ConferenceRoom({ country, onExit, onAdvisor }) {
  // The backend is the single source of truth for phase/status/world/metrics/events.
  const conf = useConference(country?.name);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiElapsed, setAiElapsed] = useState(0);
  const [aiProposal, setAiProposal] = useState(null);
  const [aiError, setAiError] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  // Real-world agenda themes are used as context; actions and dialogue remain simulated.
  // Unknown countries receive a country-dependent scenario instead of the same generic topic.
  const REAL_WORLD_SCENARIOS = [
    {
      opponent: "United Nations Security Council",
      flag: "🇺🇳",
      issue: "Conflict, food insecurity and humanitarian access",
      action: "Emergency humanitarian consultations",
      reason:
        "Delegates are examining how armed conflict disrupts food supplies, humanitarian access and civilian protection. The issue reflects topics discussed at the UN Security Council; the in-room actions are simulated.",
      demand: "Support protected humanitarian access and food supply routes",
    },
    {
      opponent: "European Union",
      flag: "🇪🇺",
      issue: "Energy security and critical supply chains",
      action: "Supply-chain risk consultations",
      reason:
        "Delegates are discussing energy security, critical materials and the effects of geopolitical tensions on international supply chains. This is a real-world policy theme; the specific dispute and responses in this room are simulated.",
      demand: "Agree to transparent supply-chain coordination",
    },
    {
      opponent: "United Kingdom",
      flag: "🇬🇧",
      issue: "Maritime security and freedom of navigation",
      action: "Maritime security consultations",
      reason:
        "Delegates are considering risks to commercial shipping and freedom of navigation in strategically important waterways. The topic reflects real maritime-security concerns; this conference's events are simulated.",
      demand: "Support a coordinated maritime de-escalation plan",
    },
    {
      opponent: "France",
      flag: "🇫🇷",
      issue: "Climate finance and resilience for vulnerable states",
      action: "Climate-finance proposal",
      reason:
        "Delegates are debating climate adaptation finance, disaster resilience and support for vulnerable countries. These are ongoing international policy issues; the proposal and negotiation in this room are simulated.",
      demand: "Commit to measurable climate-resilience support",
    },
    {
      opponent: "Japan",
      flag: "🇯🇵",
      issue: "Cybersecurity and responsible use of emerging technology",
      action: "Technology-governance consultations",
      reason:
        "Delegates are considering cybersecurity, digital infrastructure and international approaches to emerging technologies. This is a real policy area; the particular confrontation and statements are simulated.",
      demand: "Begin a multilateral dialogue on technology safeguards",
    },
    {
      opponent: "Brazil",
      flag: "🇧🇷",
      issue: "Food security, agriculture and climate shocks",
      action: "Food-security coordination proposal",
      reason:
        "Delegates are discussing how conflict, extreme weather and trade disruptions can affect food availability and agricultural livelihoods. The policy issue is real; this room's actions are simulated.",
      demand: "Coordinate measures to protect food supply and affordability",
    },
    {
      opponent: "Germany",
      flag: "🇩🇪",
      issue: "European security and diplomatic de-escalation",
      action: "Emergency diplomatic consultations",
      reason:
        "Delegates are discussing European security, conflict prevention and diplomatic options for reducing escalation. The topic reflects real international-security debates; the specific scenario is simulated.",
      demand: "Support a monitored diplomatic de-escalation process",
    },
    {
      opponent: "India",
      flag: "🇮🇳",
      issue: "Public health preparedness and equitable access to essential supplies",
      action: "Public-health coordination proposal",
      reason:
        "Delegates are considering preparedness, resilient health systems and fair access to essential medical supplies during emergencies. This is a real global policy area; the actions in this simulation are fictional.",
      demand: "Coordinate emergency supply and preparedness planning",
    },
  ];

  const countryHash = [...(country?.name || "Global")].reduce(
    (sum, character) => sum + character.charCodeAt(0),
    0
  );
  const fallbackScenario = REAL_WORLD_SCENARIOS[countryHash % REAL_WORLD_SCENARIOS.length];
  // `opening` is now used only as display framing (the scenario the delegate is briefed on).
  // It no longer drives any phase, tension or opponent state — those come from the backend.
  const opening = OPENING_MOVES[country.name] || {
    ...fallbackScenario,
    opponent: fallbackScenario.opponent === country.name ? "United Nations Security Council" : fallbackScenario.opponent,
    flag: fallbackScenario.opponent === country.name ? "🇺🇳" : fallbackScenario.flag,
  };

  // Backend-authoritative display values. Direction: higher tension is worse, higher influence (trust) is better.
  const metrics = conf.metrics;
  const tension = metrics ? Math.round(metrics.diplomatic_tension) : 0;
  const influence = metrics ? Math.round(metrics.international_trust) : 0;
  const phase = conf.phase; // the real MUN phase, decided by the backend
  const turnNumber = conf.snapshot?.world?.turn ?? 1;

  // The live record is derived from the conference's real backend events (newest first).
  const timeline = conf.events.slice(0, 8).map((event, index) => ({
    id: event.id ?? index,
    type: event.actor && conf.myCountry && event.actor === conf.myCountry.country_id ? "player" : "opponent",
    actor: event.actor || "Conference",
    flag: "🏛️",
    title: humanizeEventType(event.type),
    detail: event.message,
    time: `Turn ${String(event.turn ?? turnNumber).padStart(2, "0")}`,
  }));

const toCountryId = (name) =>
  name.trim().toLowerCase().replace(/\s+/g, "-");

const requestAIProposal = async () => {
  setAiLoading(true);
  setAiElapsed(0);
  setAiError("");
  setAiProposal(null);

  // Live seconds counter so a slow answer never looks like a frozen button.
  const startedAt = Date.now();
  const elapsedTimer = setInterval(
    () => setAiElapsed(Math.floor((Date.now() - startedAt) / 1000)),
    1000
  );

  try {
    const situation = [
      `Scenario: ${opening.issue}.`,
      opening.reason,
      `The stated demand is: ${opening.demand}.`,
      `Recommend one response that protects ${country.name}'s interests.`,
      "Use the current simulation state.",
    ].join(" ");

    const result = await proposeAI(
      toCountryId(country.name),
      situation
    );

    if (!result?.decision || !result.decision.decision) {
  setAiProposal(null);
  setAiError(
    `${aiFailureLabel(result?.failure_type)}: no decision was made. This is not a choice to take no action. Please try again.`
  );
  return;
}

    if (result.used_fallback) {
  setAiProposal(null);
  setAiError(
    `Gemma is temporarily unavailable: ${result.error || "No AI response received."} Please try again.`
  );
  return;
}

setAiProposal(result);
  } catch (error) {
    setAiError(
      error.failureType
        ? `${aiFailureLabel(error.failureType)}: ${error.message}`
        : error.message || "Unable to obtain an AI proposal."
    );
  } finally {
    clearInterval(elapsedTimer);
    setAiLoading(false);
  }
};

  // UI-only state for the cinematic conference-room presentation.
  const [raisedHand, setRaisedHand] = useState(false);
  const [quickNotes, setQuickNotes] = useState("");
  const [roomModal, setRoomModal] = useState("");
  const [roomTarget, setRoomTarget] = useState(opening.opponent);
  const [roomDraft, setRoomDraft] = useState("");
  const [roomToast, setRoomToast] = useState("");
  const [showReport, setShowReport] = useState(false);

  const notifyRoom = (message) => {
    setRoomToast(message);
    window.setTimeout(() => setRoomToast(""), 2800);
  };

  const chamberRoster = [
    { name: opening.opponent, flag: opening.flag, role: "Current speaker" },
    { name: country.name, flag: country.flag || "🌐", role: "Your delegation" },
    { name: "France", flag: "🇫🇷", role: "Delegate" },
    { name: "Germany", flag: "🇩🇪", role: "Delegate" },
    { name: "China", flag: "🇨🇳", role: "Delegate" },
    { name: "Brazil", flag: "🇧🇷", role: "Delegate" },
    { name: "India", flag: "🇮🇳", role: "Delegate" },
    { name: "Russia", flag: "🇷🇺", role: "Delegate" },
    { name: "Japan", flag: "🇯🇵", role: "Delegate" },
    { name: "Canada", flag: "🇨🇦", role: "Delegate" },
    { name: "Australia", flag: "🇦🇺", role: "Delegate" },
    { name: "Italy", flag: "🇮🇹", role: "Delegate" },
    { name: "South Africa", flag: "🇿🇦", role: "Delegate" },
    { name: "South Korea", flag: "🇰🇷", role: "Delegate" },
  ].filter((delegate, index, list) =>
    list.findIndex((item) => item.name === delegate.name) === index
  ).slice(0, 14);

  const roomTargetCountries = [
    { name: "Afghanistan", flag: "🇦🇫" },
    { name: "Argentina", flag: "🇦🇷" },
    { name: "Australia", flag: "🇦🇺" },
    { name: "Brazil", flag: "🇧🇷" },
    { name: "Canada", flag: "🇨🇦" },
    { name: "China", flag: "🇨🇳" },
    { name: "France", flag: "🇫🇷" },
    { name: "Germany", flag: "🇩🇪" },
    { name: "India", flag: "🇮🇳" },
    { name: "Japan", flag: "🇯🇵" },
    { name: "Russia", flag: "🇷🇺" },
    { name: "South Africa", flag: "🇿🇦" },
    { name: "United Kingdom", flag: "🇬🇧" },
    { name: "United States", flag: "🇺🇸" },
  ].filter((item) => item.name !== country.name);

  // Whether the current backend phase permits a given action type (drives button disabled states).
  const phaseAllows = (action) => conf.allowedActions.includes(action);

  const handleRaiseHand = () => {
    const nextRaised = !raisedHand;
    setRaisedHand(nextRaised);
    notifyRoom(nextRaised ? `${country.name} requested the floor.` : "Your raised hand was lowered.");
  };

  const handleSupport = () => {
    notifyRoom(`${country.name} signalled support.`);
  };

  // A statement is a real SPEECH submitted to the backend, only valid in a speaking phase.
  const submitRoomAction = async (event) => {
    event.preventDefault();
    const kind = roomModal;

    if (kind === "statement") {
      const statement = roomDraft.trim();
      if (!statement) return;
      if (!conf.conferenceId || !conf.delegate || !conf.myCountryCode) {
        notifyRoom("The conference is not ready yet.");
        return;
      }
      if (!phaseAllows("SPEECH")) {
        notifyRoom(`Speeches are not open during ${phaseLabel(phase)}. Advance to a speaking phase first.`);
        return;
      }
      setActionLoading(true);
      try {
        await conf.runAction(
          () => submitSpeech(conf.conferenceId, conf.delegate.id, conf.myCountryCode, statement),
          `${country.name} delivered a statement.`
        );
        setRoomDraft("");
        setRoomModal("");
        notifyRoom(`${country.name}'s statement was recorded in the conference.`);
      } catch (error) {
        notifyRoom(error?.message || "The statement could not be submitted.");
      } finally {
        setActionLoading(false);
      }
      return;
    }

    // Alliance / sanction room proposals are advisory in this single-delegate demo; the authoritative
    // diplomatic outcomes come through the conference phases, the crisis engine and voting. We surface
    // a clear notice rather than mutate the detached sandbox world and pretend it changed the conference.
    notifyRoom(
      "Use the Crisis Center, the AI advisor and the voting phase to drive real diplomatic outcomes in this session."
    );
    setRoomModal("");
  };
  const phaseDone = conf.conferenceStatus === "COMPLETED";
  const isResults = phase === "RESULTS" || phaseDone;

  return (
    <main className="cr-photo-page">
      <header className="cr-conference-header">
        <div className="cr-heading-copy">
          <div className="cr-eyebrow"><span className="cr-live-dot" /> GLOBAL AFFAIRS / SIMULATION</div>
          <h1>Conference</h1>
          <p>Discuss. Negotiate. Build alliances. Shape the world.</p>
        </div>
        <div className="cr-header-actions">
          <span className="cr-turn-pill"><Clock3 size={15} /> TURN {String(turnNumber).padStart(2, "0")}</span>
          <span className="cr-time-pill"><Radio size={15} /> {phaseDone ? "SESSION CLOSED" : "SESSION LIVE"}</span>
          <button className="cr-exit-button" onClick={() => setShowReport(true)}><FileText size={15} /> Generate Report</button>
          <button className="cr-exit-button" onClick={onExit}><X size={15} /> Exit conference</button>
        </div>
      </header>

      {/* Backend-authoritative phase banner + chair's "advance" control. The backend decides the next phase. */}
      <section className="cr-phase-bar" aria-label="Conference phase">
        {conf.status === "loading" && (
          <div className="cr-phase-loading"><Loader size={15} className="cr-spin" /> Starting the conference on the backend…</div>
        )}
        {conf.status === "error" && (
          <div className="cr-phase-error" role="alert">
            <AlertTriangle size={15} /> {conf.error || "Could not reach the conference backend."}
            <button className="cr-secondary-button" onClick={conf.retry}>Retry</button>
          </div>
        )}
        {conf.status === "ready" && (
          <>
            <ol className="cr-phase-steps">
              {PHASE_SEQUENCE.map((step) => {
                const reached = PHASE_SEQUENCE.indexOf(step) <= PHASE_SEQUENCE.indexOf(phase);
                const current = step === phase;
                return (
                  <li key={step} className={`cr-phase-step ${current ? "is-current" : reached ? "is-done" : ""}`}>
                    <span className="cr-phase-dot" />{phaseLabel(step)}
                  </li>
                );
              })}
            </ol>
            <div className="cr-phase-actions">
              <span className="cr-phase-current">Phase: <strong>{phaseLabel(phase)}</strong>{phaseDone ? " · Completed" : ""}</span>
              {!phaseDone && (
                <button className="cr-primary-button" onClick={conf.advance} disabled={conf.busy}>
                  {conf.busy ? <><Loader size={14} className="cr-spin" /> Working…</> : <>{conf.nextPhase === "COMPLETED" ? "Finish & see results" : `Advance to ${phaseLabel(conf.nextPhase)}`} <ArrowRight size={14} /></>}
                </button>
              )}
            </div>
          </>
        )}
        {conf.notice && (
          <div className={`cr-phase-notice ${conf.notice.kind}`} role="status">
            {conf.notice.text}
            <button className="cr-modal-close" onClick={conf.dismissNotice} aria-label="Dismiss"><X size={14} /></button>
          </div>
        )}
      </section>

      <section className="cr-status-strip" aria-label="Conference status">
        <div><span>YOUR DELEGATION</span><strong>{country.flag || "🌐"} {country.name}</strong></div>
        <div><span>CURRENT TOPIC</span><strong>{conf.snapshot?.topic || opening.issue}</strong></div>
        <div><span>GLOBAL TENSION</span><strong className={tension >= 60 ? "cr-tension-high" : ""}>{tension}/100</strong></div>
        <div><span>INTERNATIONAL TRUST</span><strong>{influence}/100</strong></div>
      </section>

      <section className="cr-chamber-scene" aria-label="Diplomatic conference chamber">
        <div className="cr-scene-overlay" />

        <div className="cr-wall-screen cr-topic-screen">
          <span>CURRENT TOPIC</span>
          <strong>{opening.issue}</strong>
          <div className="cr-wall-map-art" aria-hidden="true">
            <svg viewBox="0 0 260 90" role="img" aria-label="Decorative world map illustration">
              <g fill="#1b6590" stroke="#47b8ec" strokeWidth=".8" opacity=".86">
                <path d="M8 24 23 13 47 16 56 27 46 36 41 47 29 42 22 32 12 34Z" />
                <path d="M48 48 63 52 72 66 66 82 58 74 56 62Z" />
                <path d="M94 24 108 17 125 20 137 14 155 20 171 17 184 25 201 22 218 31 238 30 249 40 232 48 216 43 201 50 185 44 174 53 155 46 142 55 130 46 118 48 106 39 97 39Z" />
                <path d="M147 48 162 47 171 60 165 76 154 83 146 69Z" />
                <path d="M205 55 220 51 235 58 241 69 231 76 216 70Z" />
              </g>
              <g stroke="#4ccaff" strokeWidth=".7" fill="none" opacity=".75">
                <path d="M34 27 Q111 -3 154 28 T226 37" />
                <path d="M63 65 Q132 24 191 61" />
              </g>
            </svg>
          </div>
        </div>

        <div className="cr-wall-screen cr-tension-screen">
          <span>GLOBAL TENSION</span>
          <strong className="cr-screen-tension">{tension >= 60 ? "HIGH" : tension >= 40 ? "MODERATE" : "LOW"}</strong>
          <div className="cr-tension-chart" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /></div>
          <div className="cr-tension-legend"><span><i className="high" /> High</span><span><i className="moderate" /> Moderate</span><span><i className="low" /> Low</span></div>
        </div>

        <div className="cr-speech-bubble" key={`${opening.opponent}-${turnNumber}`}>
          <div className="cr-speech-bubble-heading"><span className="cr-flag-large">{opening.flag}</span><strong>{opening.opponent}</strong><span className="cr-speaking-dot" /></div>
          <p>{opening.reason}</p>
          <small>OPENING STATEMENT · FICTIONAL SCENARIO</small>
        </div>

        <div className="cr-delegate-rail" aria-label="Delegations in the room">
          {chamberRoster.map((delegate, index) => {
            const isSpeaker = delegate.name === opening.opponent;
            const isYou = delegate.name === country.name;
            return (
              <div className={`cr-delegate ${isSpeaker ? "is-speaker" : ""} ${isYou ? "is-you" : ""}`} key={`${delegate.name}-${index}`}>
                <span className="cr-delegate-avatar"><UserRound size={19} /></span>
                <span className="cr-delegate-flag">{delegate.flag}</span>
                <span className="cr-delegate-name">{delegate.name}</span>
                {isSpeaker && <span className="cr-delegate-status">SPEAKING</span>}
                {isYou && raisedHand && <span className="cr-hand-badge"><Hand size={13} /> HAND RAISED</span>}
              </div>
            );
          })}
        </div>

        <aside className="cr-activity-card">
          <div className="cr-activity-heading"><div><span className="cr-eyebrow">LIVE RECORD</span><h2>Conference activity</h2></div><span className="cr-activity-live"><i /> LIVE</span></div>
          <div className="cr-activity-list">
            {timeline.slice(0, 5).map((event) => (
              <article className="cr-activity-item" key={event.id}>
                <span className={`cr-activity-marker ${event.type === "player" ? "player" : "opponent"}`} />
                <div className="cr-activity-item-copy">
                  <div className="cr-activity-meta"><strong>{event.flag || "🌐"} {event.actor}</strong><time>{event.time}</time></div>
                  <b>{event.title}</b>
                  <p>{event.detail}</p>
                </div>
              </article>
            ))}
          </div>
        </aside>
      </section>

      <section className="cr-action-dock">
        <article className="cr-live-speaker-card">
          <div className="cr-bottom-card-heading"><span className="cr-live-dot" /> CURRENT SPEAKER</div>
          <div className="cr-speaker-summary"><span className="cr-speaker-flag">{opening.flag}</span><div><strong>{opening.opponent}</strong><p>{opening.action}: {opening.reason}</p></div></div>
          <div className="cr-audio-row"><div className="cr-audio-wave" aria-label="Speaker activity animation">{Array.from({ length: 32 }, (_, index) => <i key={index} style={{ "--bar-height": `${8 + ((index * 13) % 24)}px`, "--bar-delay": `${index * 22}ms` }} />)}</div><span className="cr-live-tag"><i /> LIVE</span></div>
        </article>

        <article className="cr-actions-card">
          <div className="cr-bottom-card-heading">YOUR ACTIONS <span>TURN {String(turnNumber).padStart(2, "0")}</span></div>
          <div className="cr-action-buttons">
            <button className={`cr-action-button ${raisedHand ? "is-active" : ""}`} onClick={handleRaiseHand} disabled={conf.status !== "ready"}><span><Hand size={22} /></span><strong>{raisedHand ? "Lower Hand" : "Raise Hand"}</strong></button>
            <button className="cr-action-button" onClick={handleSupport} disabled={conf.status !== "ready"}><span><ThumbsUp size={22} /></span><strong>Support</strong></button>
            <button className="cr-action-button" onClick={() => { setRoomTarget(opening.opponent); setRoomModal("alliance"); }} disabled={conf.status !== "ready"}><span><Handshake size={22} /></span><strong>Propose Alliance</strong></button>
            <button className="cr-action-button" onClick={() => { setRoomTarget(opening.opponent); setRoomModal("sanctions"); }} disabled={conf.status !== "ready"}><span><Shield size={22} /></span><strong>Propose Sanctions</strong></button>
            <button className={`cr-action-button ${phaseAllows("SPEECH") ? "" : "is-disabled"}`} onClick={() => { setRoomDraft(""); setRoomModal("statement"); }} disabled={conf.status !== "ready" || !phaseAllows("SPEECH")} title={phaseAllows("SPEECH") ? "Deliver a speech" : `Speeches open in Opening Speeches / Moderated Caucus (now: ${phaseLabel(phase)})`}><span><MessageSquare size={22} /></span><strong>Make a Statement</strong></button>
          </div>
        </article>

        <article className="cr-notes-card">
          <div className="cr-bottom-card-heading">QUICK NOTES <span><Check size={13} /> SESSION ONLY</span></div>
          <textarea value={quickNotes} onChange={(event) => setQuickNotes(event.target.value)} placeholder="Write your notes here…" aria-label="Quick notes" />
          <button className="cr-note-save" onClick={() => notifyRoom("Your notes are saved for this session.")}><Check size={14} /> Keep notes</button>
        </article>
      </section>

      <section className="cr-support-grid">
        <article className="cr-support-panel cr-ai-panel">
          <div className="cr-support-title"><div><span className="cr-eyebrow">AI DIPLOMATIC ADVISOR</span><h2>Strategic recommendation</h2><p>Generate an AI proposal using the current scenario and your delegation.</p></div><span className={`cr-ai-status ${aiLoading ? "working" : ""}`}>{aiLoading ? "ANALYZING" : "READY"}</span></div>
          <button className="cr-primary-button" onClick={requestAIProposal} disabled={aiLoading}><Bot size={16} /> {aiLoading ? `Waiting for AI… ${aiElapsed}s` : aiError ? "Retry AI proposal" : "Generate AI proposal"} <ArrowRight size={15} /></button>
          {aiError && <p className="cr-inline-error" role="alert">{aiError}</p>}
          {aiProposal && (
            <div className="cr-ai-result">
              <div className="cr-ai-result-meta"><span>{aiProposal.used_fallback ? "SAFE FALLBACK" : `AI GENERATED · ${aiProposal.model || "MODEL"}`}</span><strong>{aiProposal.decision.decision.replaceAll("_", " ")}</strong></div>
              <p>{aiProposal.decision.reason}</p>
              <p><strong>Suggested target:</strong> {aiProposal.decision.target || "No target"}</p>
              {aiProposal.used_fallback
                ? <p className="cr-inline-error">This is a fallback response, not an AI-generated recommendation.</p>
                : aiProposal.decision.decision === "NO_ACTION"
                  ? <p className="cr-action-message" role="status">The advisor recommends taking no action this turn (a deliberate choice, not a failure).</p>
                  : <p className="cr-action-message" role="status">Advisory recommendation. Use the phase controls, Crisis Center and voting to act on it within the conference.</p>}
            </div>
          )}
          <button className="cr-text-button" onClick={onAdvisor}><MessageSquare size={14} /> Open diplomatic advisor</button>
        </article>

        <article className="cr-support-panel cr-world-panel">
          <div className="cr-support-title"><div><span className="cr-eyebrow">WORLD MONITOR</span><h2>Diplomatic landscape</h2><p>Explore the map while the session continues.</p></div><TrendingUp size={18} /></div>
          <WorldMap selectedCountry={country.name} onCountrySelect={() => {}} height={220} />
          <div className="cr-map-caption"><span><i className="you" /> Your delegation</span><span><i className="tension" /> Sanctions dispute</span></div>
        </article>
      </section>

      <details className="cr-response-details">
        <summary>Phase guide & conference record <span>Backend-driven</span></summary>
        <div className="cr-phase-guide">
          <p>
            The conference is in <strong>{phaseLabel(phase)}</strong>. {isResults
              ? "Voting is closed — open the report to see the official results."
              : conf.allowedActions.length
                ? `Actions permitted now: ${conf.allowedActions.join(", ")}.`
                : "This phase has no delegate actions — the chair advances it when ready."}
          </p>
          {conf.events.length === 0 ? (
            <p className="cr-empty-note">No conference events recorded yet.</p>
          ) : (
            <ul className="cr-record-list">
              {conf.events.slice(0, 6).map((event, index) => (
                <li key={event.id ?? index}><strong>{humanizeEventType(event.type)}</strong> — {event.message}</li>
              ))}
            </ul>
          )}
        </div>
      </details>

      {roomToast && <div className="cr-toast" role="status"><Check size={16} /> {roomToast}</div>}

      {roomModal && (
        <div className="cr-modal-backdrop" onClick={() => setRoomModal("")}>
          <form className="cr-action-modal" onSubmit={submitRoomAction} onClick={(event) => event.stopPropagation()}>
            <div className="cr-modal-heading"><div><span className="cr-eyebrow">DIPLOMATIC ACTION</span><h2>{roomModal === "alliance" ? "Propose an alliance" : roomModal === "sanctions" ? "Propose sanctions" : "Make a statement"}</h2></div><button type="button" className="cr-modal-close" onClick={() => setRoomModal("")} aria-label="Close"><X size={18} /></button></div>
            {roomModal === "statement" ? <label className="cr-form-label">Your statement{!phaseAllows("SPEECH") && <span className="cr-modal-note"> Speeches open during Opening Speeches / Moderated Caucus. The conference is currently in {phaseLabel(phase)}.</span>}<textarea autoFocus rows={5} value={roomDraft} onChange={(event) => setRoomDraft(event.target.value)} placeholder={`The delegation of ${country.name} states…`} required /></label> : <><label className="cr-form-label">Target delegation<select value={roomTarget} onChange={(event) => setRoomTarget(event.target.value)} required>{roomTargetCountries.map((targetCountry) => <option key={targetCountry.name} value={targetCountry.name}>{targetCountry.flag} {targetCountry.name}</option>)}</select></label><p className="cr-modal-note">In this single-delegate session, formal diplomacy is driven through the conference phases, the Crisis Center and the voting phase. This records your intent.</p></>}
            <div className="cr-modal-actions"><button type="button" className="cr-secondary-button" onClick={() => setRoomModal("")}>Cancel</button><button type="submit" className="cr-primary-button" disabled={actionLoading || (roomModal === "statement" && !roomDraft.trim())}>{actionLoading ? "Submitting…" : roomModal === "statement" ? <><Send size={14} /> Publish statement</> : roomModal === "alliance" ? <><Handshake size={15} /> Send proposal</> : <><Shield size={15} /> Submit proposal</>}</button></div>
          </form>
        </div>
      )}

      {/* Rendered on <body>: .cr-photo-page's entrance animation leaves a transform on it, which would make
          position:fixed children position against the whole tall page instead of the visible screen. */}
      {createPortal(
        <div className="rpt-portal">
          {!showReport && (
            <button type="button" className="rpt-fab" onClick={() => setShowReport(true)} aria-label="Generate report">
              <FileText size={16} /> Generate Report
            </button>
          )}
          {showReport && <ReportModal onClose={() => setShowReport(false)} />}
        </div>,
        document.body
      )}

      <OpponentCouncil country={country} onActionComplete={conf.refresh} />
    </main>
  );
}

// Turn a backend event `type` (e.g. "speech_submitted") into a short human label for the live record.
function humanizeEventType(type) {
  if (!type) return "Conference update";
  const labels = {
    conference_start: "Conference started",
    speech_submitted: "Speech delivered",
    negotiation_proposed: "Negotiation proposed",
    negotiation_accepted: "Negotiation accepted",
    negotiation_rejected: "Negotiation rejected",
    negotiation_countered: "Negotiation countered",
    negotiation_expired: "Negotiation expired",
    crisis_started: "Crisis started",
    crisis_response: "Crisis response",
    crisis_resolved: "Crisis resolved",
    resolution_passed: "Resolution passed",
    resolution_failed: "Resolution failed",
    sanction: "Sanctions applied",
    alliance: "Alliance formed",
    aid: "Aid sent",
  };
  return labels[type] || type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
