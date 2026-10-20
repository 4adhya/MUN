import OpponentCouncil from "./OpponentCouncil";
import { useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  Bot,
  Check,
  Clock3,
  Handshake,
  HeartHandshake,
  Hand,
  Mic,
  MessageSquare,
  Radio,
  Send,
  ThumbsUp,
  UserRound,
  Shield,
  Swords,
  TrendingUp,
  Users,
  X,
} from "lucide-react";
import WorldMap from "./WorldMap";
import "./ConferenceRoom.css";
import {
  proposeAI,
  sanction,
  alliance,
  aid,
  getWorld,
  getEvents,
} from "../api/client.js";

const OPENING_MOVES = {
  India: {
    opponent: "China",
    flag: "🇨🇳",
    issue: "Critical mineral export dispute",
    action: "Targeted trade sanctions",
    reason:
      "The opposing delegation is applying economic pressure over a fictional dispute involving critical mineral exports and regional supply chains.",
    demand: "Suspend the disputed export restrictions",
  },
  China: {
    opponent: "United States",
    flag: "🇺🇸",
    issue: "Technology and trade restrictions",
    action: "Technology trade sanctions",
    reason:
      "The opposing delegation is applying economic pressure in a fictional dispute over technology access and strategic supply chains.",
    demand: "Reverse the proposed technology restrictions",
  },
  "United States": {
    opponent: "China",
    flag: "🇨🇳",
    issue: "Strategic technology restrictions",
    action: "Targeted technology sanctions",
    reason:
      "The opposing delegation is applying pressure in a fictional dispute over strategic technology and international trade.",
    demand: "Withdraw the proposed restrictions",
  },
  France: {
    opponent: "Russia",
    flag: "🇷🇺",
    issue: "European security dispute",
    action: "Diplomatic and trade sanctions",
    reason:
      "The opposing delegation has escalated a fictional security dispute with diplomatic and economic pressure.",
    demand: "Reverse the disputed security measures",
  },
  "United Kingdom": {
    opponent: "Russia",
    flag: "🇷🇺",
    issue: "Maritime security dispute",
    action: "Targeted trade sanctions",
    reason:
      "The opposing delegation is applying pressure in a fictional maritime security dispute.",
    demand: "Accept an emergency maritime security dialogue",
  },
  Russia: {
    opponent: "France",
    flag: "🇫🇷",
    issue: "Regional security dispute",
    action: "Diplomatic sanctions",
    reason:
      "The opposing delegation has escalated a fictional regional security disagreement.",
    demand: "Review the disputed security measures",
  },
  Japan: {
    opponent: "China",
    flag: "🇨🇳",
    issue: "Regional trade dispute",
    action: "Targeted trade sanctions",
    reason:
      "The opposing delegation is applying economic pressure in a fictional regional trade dispute.",
    demand: "Accept a new regional trade arrangement",
  },
  Brazil: {
    opponent: "United States",
    flag: "🇺🇸",
    issue: "Agricultural trade dispute",
    action: "Agricultural trade sanctions",
    reason:
      "The opposing delegation is applying economic pressure in a fictional agricultural trade dispute.",
    demand: "Review the disputed trade measures",
  },
};

const RESPONSE_OPTIONS = [
  {
    id: "negotiate",
    title: "Call emergency talks",
    subtitle: "Seek a negotiated settlement",
    icon: MessageSquare,
    tone: "blue",
    tension: -8,
    influence: 2,
    result:
      "You request emergency diplomatic talks and propose a temporary pause while both delegations negotiate.",
  },
  {
    id: "counter",
    title: "Counter-sanctions",
    subtitle: "Apply reciprocal economic pressure",
    icon: Swords,
    tone: "red",
    tension: 12,
    influence: 3,
    result:
      "Your delegation announces reciprocal measures. Pressure increases, and other countries watch for escalation.",
  },
  {
    id: "alliance",
    title: "Seek coalition support",
    subtitle: "Build a united diplomatic front",
    icon: Users,
    tone: "purple",
    tension: 1,
    influence: 6,
    result:
      "You approach other delegations to coordinate a response and increase diplomatic leverage.",
  },
  {
    id: "concede",
    title: "Offer a compromise",
    subtitle: "Trade concessions for relief",
    icon: HeartHandshake,
    tone: "green",
    tension: -5,
    influence: -1,
    result:
      "You offer a limited policy concession in exchange for a pause in sanctions and a path toward settlement.",
  },
];

export default function ConferenceRoom({ country, onExit, onAdvisor }) {
  const [aiLoading, setAiLoading] = useState(false);
  const [aiProposal, setAiProposal] = useState(null);
  const [aiError, setAiError] = useState("");
  const [actionLoading, setActionLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState("");

  const opening = OPENING_MOVES[country.name] || {
    opponent: "United States",
    flag: "🇺🇸",
    issue: "Strategic trade dispute",
    action: "Targeted trade sanctions",
    reason:
      "The opposing delegation has opened a fictional dispute over trade and strategic interests.",
    demand: "Enter emergency diplomatic talks",
  };

  const [phase, setPhase] = useState("player");
  const [selectedResponse, setSelectedResponse] = useState(null);
  const [timeline, setTimeline] = useState([
    {
      id: 1,
      type: "opponent",
      actor: opening.opponent,
      flag: opening.flag,
      title: opening.action,
      detail: opening.reason,
      time: "Opening move",
    },
  ]);
  const [tension, setTension] = useState(48);
  const [influence, setInfluence] = useState(68);
  const [turn, setTurn] = useState(1);
  const [lastResponse, setLastResponse] = useState(null);
  const [showOpening, setShowOpening] = useState(true);

  const respond = (option) => {
    if (phase !== "player") return;

    setSelectedResponse(option.id);
    setLastResponse(option);
    setPhase("opponent");

    const playerMove = {
      id: Date.now(),
      type: "player",
      actor: country.name,
      flag: country.flag,
      title: option.title,
      detail: option.result,
      time: `Turn ${turn} · Your move`,
    };

    setTimeline((items) => [playerMove, ...items]);
    setTension((value) =>
      Math.max(5, Math.min(95, value + option.tension))
    );
    setInfluence((value) =>
      Math.max(5, Math.min(95, value + option.influence))
    );

    window.setTimeout(() => {
      const reaction = {
        negotiate: {
          title: "Conditional talks proposed",
          detail:
            `${opening.opponent} acknowledges the request but demands progress on its stated concerns before sanctions can be suspended.`,
        },
        counter: {
          title: "Retaliatory measures announced",
          detail:
            `${opening.opponent} responds to the escalation with additional diplomatic pressure and calls on partners to review their position.`,
        },
        alliance: {
          title: "Coalition discussions begin",
          detail:
            `${opening.opponent} begins consulting other delegations and signals that it may consider a multilateral discussion.`,
        },
        concede: {
          title: "Limited pause offered",
          detail:
            `${opening.opponent} signals willingness to discuss a temporary pause but says a final settlement will require further negotiations.`,
        },
      }[option.id];

      setTimeline((items) => [
        {
          id: Date.now() + 1,
          type: "opponent",
          actor: opening.opponent,
          flag: opening.flag,
          title: reaction.title,
          detail: reaction.detail,
          time: `Turn ${turn} · Opponent response`,
        },
        ...items,
      ]);

      setPhase("player");
      setSelectedResponse(null);
      setTurn((value) => value + 1);
    }, 1100);
  };
const toCountryId = (name) =>
  name.trim().toLowerCase().replace(/\s+/g, "-");

const requestAIProposal = async () => {
  setAiLoading(true);
  setAiError("");
  setAiProposal(null);
  setActionMessage("");

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
      error.message || "Unable to obtain an AI proposal."
    );
  } finally {
    setAiLoading(false);
  }
};

const approveAIProposal = async () => {
  const decision = aiProposal?.decision;

  if (
    !decision ||
    decision.decision === "NO_ACTION" ||
    !decision.target
  ) {
    return;
  }

  setActionLoading(true);
  setActionMessage("");

  try {
    const actor = toCountryId(country.name);

    // Gemma returns the canonical country name, not its ID.
    // Convert it to the backend's lowercase country ID.
    const target = toCountryId(decision.target);

    let result;

    if (decision.decision === "SANCTION") {
      result = await sanction(actor, target);
    } else if (decision.decision === "ALLIANCE") {
      result = await alliance(actor, target);
    } else if (decision.decision === "AID") {
      result = await aid(actor, target, 10);
    } else {
      throw new Error("Unsupported decision type.");
    }

    setActionMessage(
      `Action executed: ${decision.decision} involving ${decision.target}.`
    );

    setTimeline((items) => [
      {
        id: Date.now(),
        type: "player",
        actor: country.name,
        flag: country.flag,
        title: `${decision.decision}: ${decision.target}`,
        detail: result.event?.message || decision.reason,
        time: "Approved AI action",
      },
      ...items,
    ]);

    // Fetch authoritative state after the action.
    // These calls confirm the backend now has the updated world/events.
    await Promise.all([getWorld(), getEvents()]);
  } catch (error) {
    setActionMessage(
      `Action was not executed: ${
        error.message || "Please try again."
      }`
    );
  } finally {
    setActionLoading(false);
  }
};


  // UI-only state for the cinematic conference-room presentation.
  const [raisedHand, setRaisedHand] = useState(false);
  const [quickNotes, setQuickNotes] = useState("");
  const [roomModal, setRoomModal] = useState("");
  const [roomTarget, setRoomTarget] = useState(opening.opponent);
  const [roomDraft, setRoomDraft] = useState("");
  const [roomToast, setRoomToast] = useState("");

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

  const addRoomEvent = (event) => {
    setTimeline((items) => [{ id: Date.now(), ...event }, ...items]);
  };

  const handleRaiseHand = () => {
    const nextRaised = !raisedHand;
    setRaisedHand(nextRaised);
    if (nextRaised) {
      addRoomEvent({
        type: "player",
        actor: country.name,
        flag: country.flag || "🌐",
        title: "Requested to speak",
        detail: `${country.name} raised a hand to request the floor.`,
        time: `Turn ${turn} · Just now`,
      });
      notifyRoom(`${country.name} requested the floor.`);
    } else {
      notifyRoom("Your raised hand was lowered.");
    }
  };

  const handleSupport = () => {
    addRoomEvent({
      type: "player",
      actor: country.name,
      flag: country.flag || "🌐",
      title: "Supported the current statement",
      detail: `${country.name} signalled support during the discussion of ${opening.issue.toLowerCase()}.`,
      time: `Turn ${turn} · Just now`,
    });
    notifyRoom(`${country.name} signalled support.`);
  };

  const submitRoomAction = async (event) => {
    event.preventDefault();
    const kind = roomModal;

    if (kind === "statement") {
      const statement = roomDraft.trim();
      if (!statement) return;
      addRoomEvent({
        type: "player",
        actor: country.name,
        flag: country.flag || "🌐",
        title: "Made a statement",
        detail: statement,
        time: `Turn ${turn} · Just now`,
      });
      setRoomDraft("");
      setRoomModal("");
      notifyRoom(`${country.name}'s statement was added to the proceedings.`);
      return;
    }

    if (!roomTarget || roomTarget === country.name) {
      notifyRoom("Choose another country for this proposal.");
      return;
    }

    setActionLoading(true);
    setActionMessage("");
    try {
      const actorId = toCountryId(country.name);
      const targetId = toCountryId(roomTarget);
      const result = kind === "alliance"
        ? await alliance(actorId, targetId)
        : await sanction(actorId, targetId);
      const title = kind === "alliance"
        ? `Alliance proposal to ${roomTarget}`
        : `Sanctions proposal targeting ${roomTarget}`;
      const detail = result?.event?.message || (kind === "alliance"
        ? `${country.name} submitted an alliance proposal to ${roomTarget}.`
        : `${country.name} submitted a sanctions proposal targeting ${roomTarget}.`);

      addRoomEvent({
        type: "player",
        actor: country.name,
        flag: country.flag || "🌐",
        title,
        detail,
        time: `Turn ${turn} · Just now`,
      });
      await Promise.all([getWorld(), getEvents()]);
      setRoomModal("");
      setRoomDraft("");
      notifyRoom(detail);
    } catch (error) {
      notifyRoom(error?.message || "The proposal could not be submitted.");
    } finally {
      setActionLoading(false);
    }
  };
  return (
    <main className="cr-photo-page">
      <header className="cr-conference-header">
        <div className="cr-heading-copy">
          <div className="cr-eyebrow"><span className="cr-live-dot" /> GLOBAL AFFAIRS / SIMULATION</div>
          <h1>Conference</h1>
          <p>Discuss. Negotiate. Build alliances. Shape the world.</p>
        </div>
        <div className="cr-header-actions">
          <span className="cr-turn-pill"><Clock3 size={15} /> TURN {String(turn).padStart(2, "0")}</span>
          <span className="cr-time-pill"><Radio size={15} /> SESSION LIVE</span>
          <button className="cr-exit-button" onClick={onExit}><X size={15} /> Exit conference</button>
        </div>
      </header>

      <section className="cr-status-strip" aria-label="Conference status">
        <div><span>YOUR DELEGATION</span><strong>{country.flag || "🌐"} {country.name}</strong></div>
        <div><span>CURRENT TOPIC</span><strong>{opening.issue}</strong></div>
        <div><span>GLOBAL TENSION</span><strong className={tension >= 60 ? "cr-tension-high" : ""}>{tension}/100</strong></div>
        <div><span>DIPLOMATIC INFLUENCE</span><strong>{influence}/100</strong></div>
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

        <div className="cr-speech-bubble" key={`${opening.opponent}-${turn}`}>
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
          <div className="cr-bottom-card-heading">YOUR ACTIONS <span>TURN {String(turn).padStart(2, "0")}</span></div>
          <div className="cr-action-buttons">
            <button className={`cr-action-button ${raisedHand ? "is-active" : ""}`} onClick={handleRaiseHand}><span><Hand size={22} /></span><strong>{raisedHand ? "Lower Hand" : "Raise Hand"}</strong></button>
            <button className="cr-action-button" onClick={handleSupport}><span><ThumbsUp size={22} /></span><strong>Support</strong></button>
            <button className="cr-action-button" onClick={() => { setRoomTarget(opening.opponent); setRoomModal("alliance"); }}><span><Handshake size={22} /></span><strong>Propose Alliance</strong></button>
            <button className="cr-action-button" onClick={() => { setRoomTarget(opening.opponent); setRoomModal("sanctions"); }}><span><Shield size={22} /></span><strong>Propose Sanctions</strong></button>
            <button className="cr-action-button" onClick={() => { setRoomDraft(""); setRoomModal("statement"); }}><span><MessageSquare size={22} /></span><strong>Make a Statement</strong></button>
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
          <button className="cr-primary-button" onClick={requestAIProposal} disabled={aiLoading || actionLoading}><Bot size={16} /> {aiLoading ? "Waiting for AI…" : aiError ? "Retry AI proposal" : "Generate AI proposal"} <ArrowRight size={15} /></button>
          {aiError && <p className="cr-inline-error" role="alert">{aiError}</p>}
          {aiProposal && (
            <div className="cr-ai-result">
              <div className="cr-ai-result-meta"><span>{aiProposal.used_fallback ? "SAFE FALLBACK" : `AI GENERATED · ${aiProposal.model || "MODEL"}`}</span><strong>{aiProposal.decision.decision.replaceAll("_", " ")}</strong></div>
              <p>{aiProposal.decision.reason}</p>
              <p><strong>Target:</strong> {aiProposal.decision.target || "No target"}</p>
              {aiProposal.used_fallback ? <p className="cr-inline-error">This is a fallback response, not an AI-generated recommendation.</p> : aiProposal.decision.decision !== "NO_ACTION" && <button className="cr-primary-button" onClick={approveAIProposal} disabled={actionLoading}><Check size={15} /> {actionLoading ? "Executing…" : "Approve & execute"}</button>}
              {actionMessage && <p className="cr-action-message" role="status">{actionMessage}</p>}
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
        <summary>More diplomatic response options <span>Existing response flow</span></summary>
        <div className="cr-response-grid">
          {RESPONSE_OPTIONS.map((option, index) => {
            const Icon = option.icon;
            return <button key={option.id} className={`cr-response-option ${option.tone} ${selectedResponse === option.id ? "selected" : ""}`} disabled={phase !== "player"} onClick={() => respond(option)}><span className="cr-response-number">0{index + 1}</span><span className="cr-response-icon"><Icon size={19} /></span><strong>{option.title}</strong><small>{option.subtitle}</small><span className="cr-response-cta">{phase === "opponent" && selectedResponse === option.id ? "Decision submitted" : "Choose response"}<ArrowRight size={13} /></span></button>;
          })}
        </div>
        {phase === "opponent" && <div className="cr-thinking-message"><Bot size={17} /><div><strong>Opponent delegations are responding</strong><p>Your decision has been recorded. The opposing delegation is preparing its next move…</p></div></div>}
        {lastResponse && phase === "player" && <div className="cr-last-decision"><Check size={16} /><div><strong>Previous decision: {lastResponse.title}</strong><p>{lastResponse.result}</p></div></div>}
      </details>

      {roomToast && <div className="cr-toast" role="status"><Check size={16} /> {roomToast}</div>}

      {roomModal && (
        <div className="cr-modal-backdrop" onClick={() => setRoomModal("")}>
          <form className="cr-action-modal" onSubmit={submitRoomAction} onClick={(event) => event.stopPropagation()}>
            <div className="cr-modal-heading"><div><span className="cr-eyebrow">DIPLOMATIC ACTION</span><h2>{roomModal === "alliance" ? "Propose an alliance" : roomModal === "sanctions" ? "Propose sanctions" : "Make a statement"}</h2></div><button type="button" className="cr-modal-close" onClick={() => setRoomModal("")} aria-label="Close"><X size={18} /></button></div>
            {roomModal === "statement" ? <label className="cr-form-label">Your statement<textarea autoFocus rows={5} value={roomDraft} onChange={(event) => setRoomDraft(event.target.value)} placeholder={`The delegation of ${country.name} states…`} required /></label> : <><label className="cr-form-label">Target delegation<select value={roomTarget} onChange={(event) => setRoomTarget(event.target.value)} required>{roomTargetCountries.map((targetCountry) => <option key={targetCountry.name} value={targetCountry.name}>{targetCountry.flag} {targetCountry.name}</option>)}</select></label><p className="cr-modal-note">This is a fictional simulation proposal. It will be sent to your configured simulation backend.</p></>}
            <div className="cr-modal-actions"><button type="button" className="cr-secondary-button" onClick={() => setRoomModal("")}>Cancel</button><button type="submit" className="cr-primary-button" disabled={actionLoading || (roomModal === "statement" && !roomDraft.trim())}>{actionLoading ? "Submitting…" : roomModal === "statement" ? <><Send size={14} /> Publish statement</> : roomModal === "alliance" ? <><Handshake size={15} /> Send proposal</> : <><Shield size={15} /> Submit proposal</>}</button></div>
          </form>
        </div>
      )}

      <OpponentCouncil country={country} />
    </main>
  );
}
