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
  MessageSquare,
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

    // Gemini returns the canonical country name, not its ID.
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
  return (
    <main className="conference-page">
      <header className="conference-heading">
        <div>
          <div className="conference-eyebrow">
            <span className="conference-live-dot" />
            DIPLOMATIC CONFERENCE
            <span className="conference-mode">FICTIONAL SCENARIO</span>
          </div>
          <h1>The sanctions crisis</h1>
          <p>
            You represent {country.name}. Your decisions will shape the
            diplomatic response to the opening move.
          </p>
        </div>

        <button className="conference-exit" onClick={onExit}>
          <X size={15} /> Exit conference
        </button>
      </header>

      <section className="conference-statusbar">
        <div>
          <span>YOUR DELEGATION</span>
          <strong>{country.flag} {country.name}</strong>
        </div>
        <div>
          <span>CONFERENCE TURN</span>
          <strong><Clock3 size={14} /> {String(turn).padStart(2, "0")}</strong>
        </div>
        <div>
          <span>GLOBAL TENSION</span>
          <strong className={tension >= 60 ? "tension-high" : ""}>
            {tension}/100
          </strong>
        </div>
        <div>
          <span>DIPLOMATIC INFLUENCE</span>
          <strong>{influence}/100</strong>
        </div>
      </section>

      <div className="conference-layout">
        <section className="conference-main-column">
          {showOpening && (
            <article className="opening-crisis">
              <div className="opening-crisis-top">
                <div className="opening-icon">
                  <AlertTriangle size={21} />
                </div>
                <div>
                  <span className="conference-section-label">
                    OPENING MOVE · AI DELEGATION
                  </span>
                  <h2>{opening.opponent} imposes sanctions</h2>
                </div>
                <span className="crisis-badge">ESCALATION</span>
                <button
                  className="conference-icon-button"
                  aria-label="Dismiss opening summary"
                  onClick={() => setShowOpening(false)}
                >
                  <X size={15} />
                </button>
              </div>

              <div className="opening-parties">
                <div className="opening-party">
                  <span>{opening.flag}</span>
                  <div>
                    <small>INITIATING DELEGATION</small>
                    <strong>{opening.opponent}</strong>
                  </div>
                </div>
                <ArrowDownRight className="opening-arrow" size={23} />
                <div className="opening-party target-party">
                  <span>{country.flag}</span>
                  <div>
                    <small>TARGET DELEGATION</small>
                    <strong>{country.name}</strong>
                  </div>
                </div>
              </div>

              <div className="opening-reason">
                <span>DISPUTE</span>
                <strong>{opening.issue}</strong>
                <p>{opening.reason}</p>
              </div>

              <div className="opening-demand">
                <span>THEIR STATED DEMAND</span>
                <p>“{opening.demand}”</p>
              </div>

              <div className="fictional-notice">
                <Shield size={15} />
                This is a fictional training scenario, not a report of real
                sanctions or current government policy.
              </div>
            </article>
          )}

          <section className="response-section">
            <div className="response-heading">
              <div>
                <span className="conference-section-label">
                  YOUR TURN · TURN {String(turn).padStart(2, "0")}
                </span>
                <h2>How will you respond?</h2>
                <p>
                  Review your advisor’s assessment, then choose your
                  delegation’s next move.
                </p>
              </div>
              <span className={`turn-state ${phase === "player" ? "your-turn" : ""}`}>
                {phase === "player" ? (
                  <><span className="conference-live-dot" /> YOUR DECISION</>
                ) : (
                  <><Bot size={14} /> OPPONENT THINKING</>
                )}
              </span>
            </div>

            <div className="advisor-brief">
              <div className="advisor-brief-icon"><Bot size={20} /></div>
              <div className="advisor-brief-copy">
                <div>
                  <strong>Diplomatic advisor</strong>
                  <span>STRATEGIC BRIEFING · DEMO</span>
                </div>
                <p>
                  Avoid reacting before weighing the costs. Negotiation may
                  reduce immediate tension; coalition-building can increase
                  leverage. Counter-sanctions may demonstrate resolve but
                  risk further escalation.
                </p>
                <button className="advisor-open-link" onClick={onAdvisor}>
                  Ask your advisor <ArrowRight size={14} />
                </button>
              </div>
              <section className="ai-proposal-panel">
  <div className="ai-proposal-heading">
    <div>
      <span className="conference-section-label">
        LIVE GEMINI AGENT
      </span>

      <h2>AI diplomatic advisor</h2>

      <p>
        Generate a recommendation for {country.name} using the
        current simulation state.
      </p>
    </div>

    <span className="ai-status">
      {aiLoading ? "ANALYZING" : "READY"}
    </span>
  </div>

  <button
    className="ai-proposal-button"
    onClick={requestAIProposal}
    disabled={aiLoading || actionLoading}
  >
    <Bot size={17} />
    {aiLoading
  ? "Waiting for Gemma..."
  : aiError
    ? "Retry AI proposal"
    : "Generate AI proposal"}
    <ArrowRight size={15} />
  </button>

  {aiError && (
    <p className="ai-error" role="alert">
      {aiError}
    </p>
  )}

  {aiProposal && (
    <div className="ai-proposal-result">
      <div className="ai-proposal-meta">
        <span>
          {aiProposal.used_fallback
            ? "SAFE FALLBACK"
            : "GEMINI GENERATED"}
        </span>

        <strong>
          {aiProposal.decision.decision.replaceAll("_", " ")}
        </strong>
      </div>

      <p className="ai-proposal-reason">
        {aiProposal.decision.reason}
      </p>

      <p>
        <strong>Country:</strong>{" "}
        {aiProposal.decision.country}
      </p>

      <p>
        <strong>Target:</strong>{" "}
        {aiProposal.decision.target || "No target"}
      </p>

      {aiProposal.used_fallback && (
        <p className="ai-error">
          This is a fallback response, not a Gemini-generated
          recommendation.
          {aiProposal.error ? ` ${aiProposal.error}` : ""}
        </p>
      )}

      {!aiProposal.used_fallback &&
        aiProposal.decision.decision !== "NO_ACTION" && (
          <button
            className="ai-approve-button"
            onClick={approveAIProposal}
            disabled={actionLoading}
          >
            <Check size={16} />
            {actionLoading
              ? "Executing..."
              : "Approve & execute"}
          </button>
        )}

      {!aiProposal.used_fallback &&
        aiProposal.decision.decision === "NO_ACTION" && (
          <p className="ai-no-action">
            The AI recommends no action. The world state will
            remain unchanged.
          </p>
        )}

      {actionMessage && (
        <p className="ai-action-message" role="status">
          {actionMessage}
        </p>
      )}
    </div>
  )}
</section>
            </div>

            <div className="response-grid">
              {RESPONSE_OPTIONS.map((option, index) => {
                const Icon = option.icon;
                return (
                  <button
                    key={option.id}
                    className={`response-card ${option.tone} ${
                      selectedResponse === option.id ? "response-selected" : ""
                    }`}
                    disabled={phase !== "player"}
                    onClick={() => respond(option)}
                  >
                    <span className="response-number">0{index + 1}</span>
                    <span className="response-icon"><Icon size={20} /></span>
                    <strong>{option.title}</strong>
                    <small>{option.subtitle}</small>
                    <span className="response-choose">
                      {phase === "opponent" && selectedResponse === option.id
                        ? "Decision submitted"
                        : "Choose response"}
                      <ArrowRight size={14} />
                    </span>
                  </button>
                );
              })}
            </div>

            {phase === "opponent" && (
              <div className="opponent-thinking">
                <span className="thinking-orbit"><Bot size={17} /></span>
                <div>
                  <strong>Opponent delegations are responding</strong>
                  <p>Your decision has been recorded. The opposing delegation is preparing its next move…</p>
                </div>
              </div>
            )}

            {lastResponse && phase === "player" && (
              <div className="last-decision">
                <Check size={17} />
                <div>
                  <strong>Previous decision: {lastResponse.title}</strong>
                  <p>{lastResponse.result}</p>
                </div>
              </div>
            )}
          </section>

          <section className="conference-timeline">
            <div className="conference-panel-heading">
              <div>
                <span className="conference-section-label">LIVE RECORD</span>
                <h2>Conference proceedings</h2>
              </div>
              <span>{timeline.length} EVENTS</span>
            </div>

            <div className="proceedings-list">
              {timeline.map((event) => (
                <article className="proceeding" key={event.id}>
                  <div className={`proceeding-avatar ${event.type}`}>
                    {event.type === "opponent" ? event.flag : country.flag}
                  </div>
                  <div className="proceeding-content">
                    <div className="proceeding-meta">
                      <strong>{event.actor}</strong>
                      <span>{event.time}</span>
                    </div>
                    <h3>{event.title}</h3>
                    <p>{event.detail}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </section>

        <aside className="conference-side-column">
          <section className="conference-map-panel">
            <div className="conference-panel-heading">
              <div>
                <span className="conference-section-label">WORLD MONITOR</span>
                <h2>Diplomatic landscape</h2>
              </div>
              <TrendingUp size={17} />
            </div>
            <WorldMap
              selectedCountry={country.name}
              onCountrySelect={() => {}}
              height={300}
            />
            <div className="conference-map-caption">
              <span><i className="conference-dot blue-dot" /> Your delegation</span>
              <span><i className="conference-dot red-dot" /> Sanctions dispute</span>
            </div>
          </section>

          <section className="conference-objectives">
            <span className="conference-section-label">YOUR OBJECTIVES</span>
            <h2>Protect your national interests</h2>
            <p>Use diplomacy to pursue your goals while managing escalation risks.</p>
            {[
              ["Protect trade", "Limit economic damage"],
              ["Preserve stability", "Avoid unnecessary escalation"],
              ["Build influence", "Secure diplomatic support"],
            ].map(([title, detail], index) => (
              <div className="objective-row" key={title}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{title}</strong><small>{detail}</small></div>
              </div>
            ))}
          </section>

          <section className="conference-rules">
            <div className="conference-rules-icon"><Handshake size={17} /></div>
            <div>
              <strong>Diplomacy is a sequence</strong>
              <p>Your move changes the situation. Opponents react. You decide again.</p>
            </div>
          </section>
        </aside>
      </div>
      <OpponentCouncil country={country} />
    </main>
  );
}
