import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  Globe2,
  Handshake,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Swords,
  XCircle,
} from "lucide-react";
import {
  proposeAI,
  sanction,
  alliance,
  aid,
  getWorld,
  getEvents,
  aiFailureLabel,
} from "../api/client.js";
import "./OpponentCouncil.css";

const COUNTRIES = [
  { id: "india", name: "India", flag: "🇮🇳", color: "#ff9f43" },
  { id: "china", name: "China", flag: "🇨🇳", color: "#ff5b65" },
  { id: "united-states", name: "United States", flag: "🇺🇸", color: "#65a5ff" },
  { id: "france", name: "France", flag: "🇫🇷", color: "#8c85ff" },
  { id: "united-kingdom", name: "United Kingdom", flag: "🇬🇧", color: "#65c9e8" },
  { id: "russia", name: "Russia", flag: "🇷🇺", color: "#ff7777" },
  { id: "japan", name: "Japan", flag: "🇯🇵", color: "#ff86ae" },
  { id: "brazil", name: "Brazil", flag: "🇧🇷", color: "#54d6a1" },
];

const DEFAULT_SITUATION =
  "A sudden geopolitical crisis has created uncertainty in international trade and diplomatic relations. Evaluate the current situation, your country's interests, possible consequences, and the most appropriate diplomatic response.";

const ACTION_META = {
  SANCTION: {
    label: "Impose sanctions",
    icon: ShieldAlert,
    description: "Apply diplomatic or economic pressure.",
  },
  ALLIANCE: {
    label: "Form an alliance",
    icon: Handshake,
    description: "Strengthen cooperation with another country.",
  },
  AID: {
    label: "Provide aid",
    icon: Activity,
    description: "Provide assistance to another country.",
  },
  NO_ACTION: {
    label: "Maintain position",
    icon: Clock3,
    description: "Avoid immediate intervention.",
  },
};

function normalizeCountryId(value) {
  if (!value) return "";
  const normalized = String(value)
    .toLowerCase()
    .trim()
    .replace(/_/g, "-");

  const aliases = {
    usa: "united-states",
    "united states of america": "united-states",
    us: "united-states",
    uk: "united-kingdom",
    "great britain": "united-kingdom",
  };

  if (aliases[normalized]) return aliases[normalized];

  const match = COUNTRIES.find(
    (item) =>
      item.id === normalized ||
      item.name.toLowerCase() === normalized
  );

  return match?.id || normalized;
}

function getSelectedCountryId(country) {
  if (!country) return "india";
  return normalizeCountryId(country.id || country.name || country.country_id);
}

const VALID_ACTIONS = ["SANCTION", "ALLIANCE", "AID", "NO_ACTION"];

// A decision exists only if the server sent one. A missing decision is a FAILURE, never a NO_ACTION.
function getDecision(response) {
  return response?.decision || response?.proposal || null;
}

function getDecisionType(decision) {
  const value = decision?.decision || decision?.action;
  return value ? String(value).toUpperCase() : "";
}

function getTargetId(decision) {
  return normalizeCountryId(
    decision?.target_id || decision?.target || decision?.target_country
  );
}

function getTargetName(targetId) {
  return COUNTRIES.find((item) => item.id === targetId)?.name || targetId;
}

export default function OpponentCouncil({ country, onActionComplete }) {
  const [situation, setSituation] = useState(DEFAULT_SITUATION);
  const [proposals, setProposals] = useState({});
  const [loading, setLoading] = useState(false);
  const [actingId, setActingId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [round, setRound] = useState(0);

  const selectedCountryId = getSelectedCountryId(country);

  const opponents = useMemo(() => {
  return COUNTRIES.filter((item) => item.id !== selectedCountryId);
}, [selectedCountryId]);

  async function runCouncil() {
    if (loading) return; // a council run is already in flight; never start a second concurrent batch
    if (!situation.trim()) {
      setError("Describe the crisis before starting the council.");
      return;
    }

    setLoading(true);
    setError("");
    setNotice("");
    setProposals({});
    setRound((previous) => previous + 1);

    const initial = Object.fromEntries(
      opponents.map((opponent) => [
        opponent.id,
        { status: "loading", country: opponent },
      ])
    );

    setProposals(initial);

    // Request proposals ONE country at a time: at most one /ai/propose is ever in flight, which
    // avoids the burst of simultaneous calls that was driving Gemini into HTTP 429 (quota). Each
    // card still updates as its own proposal arrives. Error handling is unchanged: a 429/503/504 or
    // a missing/invalid decision stays a genuine AI failure and is never turned into a fake NO_ACTION.
    for (const opponent of opponents) {
      try {
        const response = await proposeAI(opponent.id, situation.trim());
        const decision = getDecision(response);

        // Never show "No action needed" for an answer that is not a real decision.
        if (!decision || !VALID_ACTIONS.includes(getDecisionType(decision))) {
          const failure = new Error(
            "The server returned no usable decision. Nothing was decided for this country."
          );
          failure.failureType = response?.failure_type || "INVALID_OUTPUT";
          throw failure;
        }

        setProposals((previous) => ({
          ...previous,
          [opponent.id]: {
            status: "ready",
            country: opponent,
            response,
            decision,
            source: response?.source || "unknown",
            usedFallback: Boolean(response?.used_fallback),
          },
        }));
      } catch (err) {
        setProposals((previous) => ({
          ...previous,
          [opponent.id]: {
            status: "error",
            country: opponent,
            error: err?.message || "The country agent could not respond.",
            failureType: err?.failureType || "AI_REQUEST_FAILED",
          },
        }));
      }
    }

    setLoading(false);
  }

  async function approveProposal(opponentId) {
    const proposal = proposals[opponentId];
    if (!proposal || proposal.status !== "ready") return;

    const decision = proposal.decision;
    const action = getDecisionType(decision);
    const targetId = getTargetId(decision);

    if (action === "NO_ACTION") {
      setNotice(`${proposal.country.name} will maintain its current position.`);
      return;
    }

    if (!["SANCTION", "ALLIANCE", "AID"].includes(action)) {
      setError(`Unsupported AI action: ${action}`);
      return;
    }

    if (!targetId || targetId === opponentId) {
      setError(
        `The ${proposal.country.name} proposal has an invalid target. Generate a new proposal.`
      );
      return;
    }

    setActingId(opponentId);
    setError("");
    setNotice("");

    try {
      if (action === "SANCTION") {
        await sanction(opponentId, targetId);
      } else if (action === "ALLIANCE") {
        await alliance(opponentId, targetId);
      } else if (action === "AID") {
        await aid(opponentId, targetId, 10);
      }

      setProposals((previous) => ({
        ...previous,
        [opponentId]: {
          ...previous[opponentId],
          status: "executed",
        },
      }));

      setNotice(
        `${proposal.country.name} executed ${action.toLowerCase().replace("_", " ")} against ${getTargetName(targetId)}.`
      );

      // Refresh backend data after the action. The parent can also refresh
      // its shared simulation state using onActionComplete.
      await Promise.allSettled([getWorld(), getEvents()]);
      if (onActionComplete) await onActionComplete();
    } catch (err) {
      setError(
        err?.message ||
          "The simulation rejected this action. Check the backend response."
      );
    } finally {
      setActingId("");
    }
  }

  const readyCount = Object.values(proposals).filter(
    (proposal) =>
      proposal.status === "ready" || proposal.status === "executed"
  ).length;

  return (
    <section className="opponent-council">
      <header className="council-header">
        <div className="council-heading">
          <div className="council-icon">
            <Globe2 size={22} />
          </div>
          <div>
            <div className="council-eyebrow">
              <span className="live-dot" />
              MULTI-AGENT INTELLIGENCE
            </div>
            <h2>Opponent Council</h2>
            <p>Three countries. Three strategies. One evolving world.</p>
          </div>
        </div>

        <div className="council-count">
          <Bot size={16} />
          <span>{opponents.length} agents</span>
        </div>
      </header>

      <div className="council-situation">
        <label htmlFor="council-situation">
          <span>CRISIS BRIEFING</span>
          <span className="council-hint">Shared with every opponent</span>
        </label>

        <textarea
          id="council-situation"
          value={situation}
          onChange={(event) => setSituation(event.target.value)}
          placeholder="Describe the international crisis..."
          rows={3}
          disabled={loading}
        />

        <div className="council-controls">
          <span className="council-small-text">
            {loading
              ? "Agents are analysing the situation..."
              : "Each agent generates an independent proposal."}
          </span>

          <button
            type="button"
            className="council-run-button"
            onClick={runCouncil}
            disabled={loading}
          >
            {loading ? (
              <LoaderCircle size={17} className="council-spin" />
            ) : round > 0 ? (
              <RefreshCw size={16} />
            ) : (
              <Play size={16} />
            )}
            {loading ? "Analysing" : round > 0 ? "Run again" : "Start council"}
            {!loading && <ArrowRight size={16} />}
          </button>
        </div>
      </div>

      {error && (
        <div className="council-message council-error" role="alert">
          <AlertTriangle size={17} />
          <span>{error}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setError("")}
          >
            <XCircle size={17} />
          </button>
        </div>
      )}

      {notice && (
        <div className="council-message council-success" role="status">
          <CheckCircle2 size={17} />
          <span>{notice}</span>
          <button
            type="button"
            aria-label="Dismiss message"
            onClick={() => setNotice("")}
          >
            <XCircle size={17} />
          </button>
        </div>
      )}

      <div className="council-summary">
        <div>
          <span className="summary-label">ACTIVE OPPONENTS</span>
          <strong>{opponents.length.toString().padStart(2, "0")}</strong>
        </div>
        <div>
          <span className="summary-label">RESPONSES RECEIVED</span>
          <strong>{readyCount.toString().padStart(2, "0")}</strong>
        </div>
        <div>
          <span className="summary-label">ROUND</span>
          <strong>{round.toString().padStart(2, "0")}</strong>
        </div>
      </div>

      <div className="opponent-grid">
        {opponents.map((opponent, index) => {
          const proposal = proposals[opponent.id];
          const decision = proposal?.decision;
          const action = decision ? getDecisionType(decision) : "";
          const meta = ACTION_META[action] || ACTION_META.NO_ACTION; // only rendered when `decision` exists (validated above)
          const ActionIcon = meta.icon;
          const targetId = decision ? getTargetId(decision) : "";
          const isLoading = proposal?.status === "loading";
          const isError = proposal?.status === "error";
          const isReady = proposal?.status === "ready";
          const isExecuted = proposal?.status === "executed";
          const isFallback =
            proposal?.usedFallback ||
            proposal?.source === "fallback" ||
            proposal?.source === "safe_fallback";

          return (
            <article
              className={`opponent-card ${proposal ? `opponent-${proposal.status}` : ""}`}
              key={opponent.id}
              style={{ "--opponent-accent": opponent.color, "--card-index": index }}
            >
              <div className="opponent-card-top">
                <div className="opponent-identity">
                  <div className="opponent-flag">{opponent.flag}</div>
                  <div>
                    <h3>{opponent.name}</h3>
                    <span className="opponent-role">
                      {opponent.id === selectedCountryId
                        ? "YOUR COUNTRY"
                        : `COUNTRY AGENT · 0${index + 1}`}
                    </span>
                  </div>
                </div>
                <div className={`agent-status ${isLoading ? "status-thinking" : ""}`}>
                  <span />
                  {isLoading
                    ? "THINKING"
                    : isError
                      ? "OFFLINE"
                      : isExecuted
                        ? "EXECUTED"
                        : isReady
                          ? "READY"
                          : "STANDBY"}
                </div>
              </div>

              <div className="opponent-divider" />

              {!proposal && (
                <div className="opponent-empty">
                  <div className="opponent-orbit">
                    <Bot size={27} />
                    <span />
                  </div>
                  <strong>Awaiting briefing</strong>
                  <p>Start the council to request this agent's strategy.</p>
                </div>
              )}

              {isLoading && (
                <div className="opponent-empty">
                  <div className="opponent-orbit">
                    <LoaderCircle size={27} className="council-spin" />
                    <span />
                  </div>
                  <strong>Evaluating national interests</strong>
                  <p>Reviewing the crisis and available diplomatic actions.</p>
                </div>
              )}

              {isError && (
                <div className="opponent-empty opponent-failure">
                  <AlertTriangle size={25} />
                  <strong>{aiFailureLabel(proposal.failureType)}</strong>
                  <p>{proposal.error}</p>
                  <p>No decision was made for this country. This is not a choice to take no action.</p>
                </div>
              )}

              {decision && (
                <>
                  <div className="decision-label">
                    <Sparkles size={14} />
                    PROPOSED STRATEGY
                  </div>

                  <div className={`decision-type decision-${action.toLowerCase()}`}>
                    <div className="decision-icon">
                      <ActionIcon size={20} />
                    </div>
                    <div>
                      <strong>{meta.label}</strong>
                      <span>{meta.description}</span>
                    </div>
                  </div>

                  {targetId && (
                    <div className="opponent-target">
                      <span>TARGET</span>
                      <strong>
                        {COUNTRIES.find((item) => item.id === targetId)?.flag || "🌐"}{" "}
                        {getTargetName(targetId)}
                      </strong>
                    </div>
                  )}

                  <div className="opponent-reason">
                    <span>AGENT REASONING</span>
                    <p>
                      {decision.reason ||
                        decision.statement ||
                        "No rationale was returned by this agent."}
                    </p>
                  </div>

                  <div className="opponent-card-footer">
                    <span className={`ai-source ${isFallback ? "source-fallback" : ""}`}>
                      <span />
                      {isFallback ? "SAFE FALLBACK" : "AI RESPONSE"}
                    </span>

                    {action === "NO_ACTION" ? (
                      <span className="no-action-label">No action needed</span>
                    ) : isExecuted ? (
                      <span className="executed-label">
                        <CheckCircle2 size={14} /> Applied
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="approve-action"
                        onClick={() => approveProposal(opponent.id)}
                        disabled={!isReady || Boolean(actingId)}
                      >
                        {actingId === opponent.id ? (
                          <LoaderCircle size={15} className="council-spin" />
                        ) : (
                          <CheckCircle2 size={15} />
                        )}
                        Approve
                      </button>
                    )}
                  </div>
                </>
              )}
            </article>
          );
        })}
      </div>

      <footer className="council-footer">
        <div className="council-footer-icon">
          <Swords size={18} />
        </div>
        <p>
          <strong>Human-in-the-loop diplomacy.</strong> AI agents recommend
          actions; the simulation backend validates and applies approved
          decisions. A generated proposal is not proof that an action has
          already occurred.
        </p>
      </footer>
    </section>
  );
}