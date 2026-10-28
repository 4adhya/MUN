import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  listCrisisTemplates,
  createCrisis as apiCreateCrisis,
  respondToCrisis,
  resolveCrisis as apiResolveCrisis,
  listCrises,
  createResolution,
  addClause,
  submitResolution,
  reviewResolution,
  voteOnResolution,
  listResolutions,
} from "../api/client.js";
import { useConference, phaseLabel } from "../hooks/useConference.js";

// Phase 11: the Crisis Center, Resolutions & Voting and Living World views are now driven by the real
// backend conference (crisis engine, resolution service and voting rules). No crisis, vote tally or
// pass/fail is fabricated on the client — every value shown comes from a backend response.

const buttonStyle = {
  padding: "12px 18px",
  borderRadius: 10,
  border: "1px solid #2385aa",
  background: "#104466",
  color: "#e1f2ff",
  cursor: "pointer",
  fontSize: 15,
};

const disabledButtonStyle = { ...buttonStyle, opacity: 0.55, cursor: "not-allowed" };

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

const sharedPageStyle = {
  minHeight: "100vh",
  background: "radial-gradient(ellipse at 65% 35%, #102c49 0%, #07182b 55%, #061322 100%)",
  color: "#dfedff",
  padding: "32px clamp(16px, 3vw, 42px)",
  fontFamily: "Inter, system-ui, sans-serif",
  boxSizing: "border-box",
};

export default function CrisisCenter({ view = "crisis", country: initialCountry, onResolutionPassed }) {
  const countryName =
    typeof initialCountry === "string" ? initialCountry : initialCountry?.name || "India";
  const conf = useConference(countryName);

  const pageTitle =
    view === "resolutions" ? "Resolutions & Voting" : view === "impact" ? "Living World" : "Crisis Center";

  if (conf.status === "loading") {
    return (
      <main style={sharedPageStyle}>
        <Header title={pageTitle} phase={conf.phase} />
        <section style={panelStyle}>
          <p style={{ color: "#9cb5ca" }}>Starting a live conference on the backend…</p>
        </section>
      </main>
    );
  }

  if (conf.status === "error") {
    return (
      <main style={sharedPageStyle}>
        <Header title={pageTitle} phase={conf.phase} />
        <section style={panelStyle}>
          <p style={{ color: "#ffb1a9" }}>
            Could not reach the simulation backend: {conf.error || "unknown error"}.
          </p>
          <button style={buttonStyle} onClick={conf.retry}>Retry</button>
        </section>
      </main>
    );
  }

  if (view === "resolutions") {
    return <ResolutionsView conf={conf} countryName={countryName} onResolutionPassed={onResolutionPassed} />;
  }
  if (view === "impact") {
    return <ImpactView conf={conf} countryName={countryName} />;
  }
  return <CrisisView conf={conf} countryName={countryName} />;
}

function Header({ title, phase, right }) {
  return (
    <header style={{ marginBottom: 28 }}>
      <div style={{ color: "#43c8ff", letterSpacing: 3, fontSize: 12, fontWeight: 700 }}>
        GLOBAL AFFAIRS / SIMULATION
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap", marginTop: 12 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 36 }}>{title}</h1>
          <p style={{ color: "#8da9c3", marginBottom: 0 }}>Backend-authoritative conference state.</p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span style={buttonStyle}>Phase: {phaseLabel(phase)}</span>
          {right}
        </div>
      </div>
    </header>
  );
}

function Notice({ notice, onDismiss }) {
  if (!notice) return null;
  return (
    <div role="status" style={{ ...panelStyle, padding: 14, color: notice.kind === "error" ? "#ffb1a9" : "#68d5ff", marginBottom: 18 }}>
      {notice.text}
      <button onClick={onDismiss} style={{ ...buttonStyle, float: "right", padding: "3px 9px" }} aria-label="Dismiss notification">×</button>
    </div>
  );
}

// A control to move the backend conference toward the phase this view needs.
function PhaseControl({ conf, targetPhase }) {
  if (!targetPhase || conf.phase === targetPhase) return null;
  const completed = conf.conferenceStatus === "COMPLETED";
  return (
    <section style={{ ...panelStyle, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
      <div style={{ flex: 1, minWidth: 220 }}>
        <strong style={{ color: "#ffd27a" }}>This view needs the {phaseLabel(targetPhase)} phase.</strong>
        <p style={{ color: "#9cb5ca", margin: "6px 0 0" }}>
          The conference is in {phaseLabel(conf.phase)}. The backend advances one phase at a time.
        </p>
      </div>
      {!completed && (
        <button style={conf.busy ? disabledButtonStyle : buttonStyle} onClick={conf.advance} disabled={conf.busy}>
          {conf.busy ? "Advancing…" : `Advance to ${phaseLabel(conf.nextPhase)}`}
        </button>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Crisis view — real crisis engine (JURY starts/resolves, the delegate responds)
// ---------------------------------------------------------------------------
function CrisisView({ conf, countryName }) {
  const [templates, setTemplates] = useState([]);
  const [crises, setCrises] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState(null);
  const [acting, setActing] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState("");

  const canRunCrisis = conf.phase === "CRISIS" && conf.conferenceStatus === "ACTIVE";

  const loadCrises = useCallback(async () => {
    if (!conf.conferenceId) return;
    try {
      const list = await listCrises(conf.conferenceId);
      setCrises(list);
      if (list.length && selectedId == null) setSelectedId(list[list.length - 1].id);
    } catch (err) {
      setNotice({ kind: "error", text: err.message });
    }
  }, [conf.conferenceId, selectedId]);

  useEffect(() => {
    let cancelled = false;
    listCrisisTemplates()
      .then((t) => {
        if (cancelled) return;
        setTemplates(t);
        if (t.length) setSelectedTemplate(t[0].id);
      })
      .catch((err) => !cancelled && setNotice({ kind: "error", text: err.message }))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  useEffect(() => { loadCrises(); }, [loadCrises]);

  const selectedCrisis = useMemo(
    () => crises.find((x) => x.id === selectedId) || null,
    [crises, selectedId]
  );

  async function startCrisis() {
    if (!canRunCrisis || !conf.jury) return;
    setActing(true);
    setNotice(null);
    try {
      const crisis = await apiCreateCrisis(conf.conferenceId, conf.jury.id, { templateId: selectedTemplate });
      await loadCrises();
      await conf.refresh();
      setSelectedId(crisis.id);
      setNotice({ kind: "success", text: `Crisis started: ${crisis.title}.` });
    } catch (err) {
      setNotice({ kind: "error", text: err.message });
    } finally {
      setActing(false);
    }
  }

  async function respond(optionId) {
    if (!selectedCrisis || !conf.delegate || !conf.myCountryCode) return;
    setActing(true);
    setNotice(null);
    try {
      const result = await respondToCrisis(selectedCrisis.id, conf.delegate.id, conf.myCountryCode, optionId);
      await loadCrises();
      await conf.refresh();
      setNotice({
        kind: "success",
        text: `${countryName} responded. World stability is now ${Math.round(result.mun_metrics.world_stability)}/100.`,
      });
    } catch (err) {
      setNotice({ kind: "error", text: err.message });
    } finally {
      setActing(false);
    }
  }

  async function resolve() {
    if (!selectedCrisis || !conf.jury) return;
    setActing(true);
    setNotice(null);
    try {
      await apiResolveCrisis(selectedCrisis.id, conf.jury.id);
      await loadCrises();
      await conf.refresh();
      setNotice({ kind: "success", text: `${selectedCrisis.title} resolved.` });
    } catch (err) {
      setNotice({ kind: "error", text: err.message });
    } finally {
      setActing(false);
    }
  }

  const myResponded = selectedCrisis?.responses?.some((r) => r.country_code === conf.myCountryCode);

  return (
    <main style={sharedPageStyle}>
      <Header title="Crisis Center" phase={conf.phase} />
      <Notice notice={notice} onDismiss={() => setNotice(null)} />
      <PhaseControl conf={conf} targetPhase="CRISIS" />

      <section style={panelStyle}>
        <div style={{ color: "#36caff", letterSpacing: 3, fontSize: 13, fontWeight: 700 }}>CRISIS ENGINE</div>
        <h2 style={{ fontSize: 30 }}>Active crisis briefing</h2>
        <p style={{ color: "#9cb5ca", lineHeight: 1.7 }}>
          Your delegation: <strong>{countryName}</strong> ({conf.myCountryCode || "…"}). The jury starts a crisis;
          your delegation responds with one of the backend's fixed options, whose effects change the world metrics.
        </p>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 20, alignItems: "center" }}>
          <select
            value={selectedTemplate}
            onChange={(e) => setSelectedTemplate(e.target.value)}
            style={{ ...inputStyle, width: "auto", marginTop: 0, minWidth: 260 }}
            disabled={loading || !canRunCrisis}
          >
            {templates.map((t) => (
              <option key={t.id} value={t.id}>{t.title} ({t.severity})</option>
            ))}
          </select>
          <button
            style={canRunCrisis && !acting ? buttonStyle : disabledButtonStyle}
            onClick={startCrisis}
            disabled={!canRunCrisis || acting || !selectedTemplate}
            title={canRunCrisis ? "Start this crisis" : "Advance to the Crisis phase first"}
          >
            {acting ? "Working…" : "Start crisis"}
          </button>
        </div>
      </section>

      {crises.length === 0 ? (
        <section style={panelStyle}>
          <p style={{ color: "#9cb5ca" }}>
            {canRunCrisis ? "No crisis has been started yet. Pick a template and start one." : "No crises recorded. Reach the Crisis phase to begin."}
          </p>
        </section>
      ) : (
        <section style={panelStyle}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 230px), 1fr))", gap: 14 }}>
            {crises.map((crisis) => {
              const selected = crisis.id === selectedId;
              return (
                <button
                  key={crisis.id}
                  onClick={() => setSelectedId(crisis.id)}
                  aria-pressed={selected}
                  style={{ textAlign: "left", padding: 20, minHeight: 120, borderRadius: 14, border: selected ? "1px solid #16c7ff" : "1px solid #294b65", background: selected ? "#123750" : "#09192a", color: "#e0efff", cursor: "pointer" }}
                >
                  <div style={{ color: "#40caff", marginBottom: 12 }}>{crisis.severity}</div>
                  <strong style={{ fontSize: 17, lineHeight: 1.5 }}>{crisis.title}</strong>
                  <div style={{ color: "#8caac2", marginTop: 10, fontSize: 13 }}>
                    {crisis.status} · {crisis.responses?.length || 0} responses
                  </div>
                </button>
              );
            })}
          </div>

          {selectedCrisis && (
            <article style={{ ...panelStyle, marginTop: 24, marginBottom: 0, background: "#09192a" }}>
              <div style={{ color: "#39c9ff", letterSpacing: 3, fontSize: 12, fontWeight: 700 }}>SITUATION REPORT</div>
              <h2>{selectedCrisis.title}</h2>
              <p style={{ color: "#a1b9ce", lineHeight: 1.8 }}>{selectedCrisis.description}</p>
              <p>
                Status:{" "}
                <strong style={{ color: selectedCrisis.status === "RESOLVED" ? "#5ee0a0" : "#ffc86a" }}>
                  {selectedCrisis.status}
                </strong>
              </p>

              <h3>Your delegation's response</h3>
              {selectedCrisis.status !== "ACTIVE" ? (
                <p style={{ color: "#8caac2" }}>This crisis is {selectedCrisis.status.toLowerCase()} — no further responses.</p>
              ) : myResponded ? (
                <p style={{ color: "#8caac2" }}>{countryName} has already responded to this crisis.</p>
              ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))", gap: 12 }}>
                  {(selectedCrisis.options || []).map((option) => (
                    <button
                      key={option.id}
                      style={acting || !canRunCrisis ? disabledButtonStyle : { ...buttonStyle, textAlign: "left" }}
                      onClick={() => respond(option.id)}
                      disabled={acting || !canRunCrisis}
                    >
                      <strong>{option.title}</strong>
                      {option.description && <div style={{ color: "#bcd4e8", fontSize: 13, marginTop: 6 }}>{option.description}</div>}
                    </button>
                  ))}
                </div>
              )}

              {selectedCrisis.status === "ACTIVE" && conf.jury && (
                <button style={{ ...buttonStyle, marginTop: 16 }} onClick={resolve} disabled={acting}>
                  {acting ? "Working…" : "Resolve crisis (jury)"}
                </button>
              )}

              {selectedCrisis.responses?.length > 0 && (
                <div style={{ marginTop: 24 }}>
                  <h3>Responses</h3>
                  {selectedCrisis.responses.map((r, index) => (
                    <div key={`${r.country_code}-${index}`} style={{ borderTop: "1px solid #294b65", padding: "12px 0" }}>
                      <strong>{r.country_code}</strong>
                      <span style={{ color: "#8caac2" }}> chose {String(r.action_type).replace(/_/g, " ")}</span>
                    </div>
                  ))}
                </div>
              )}
            </article>
          )}
        </section>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Resolutions & Voting — real resolution service + voting rules
// ---------------------------------------------------------------------------
function ResolutionsView({ conf, countryName, onResolutionPassed }) {
  const [resolutions, setResolutions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [notice, setNotice] = useState(null);
  const [acting, setActing] = useState(false);
  const [title, setTitle] = useState("Resolution on global stability and cooperation");
  const [clause, setClause] = useState("Calls upon all member states to cooperate on de-escalation and share threat information.");

  const canVote = conf.phase === "VOTING" && conf.conferenceStatus === "ACTIVE";
  const canDraft = conf.phase === "DRAFTING" && conf.conferenceStatus === "ACTIVE";

  const loadResolutions = useCallback(async () => {
    if (!conf.conferenceId) return;
    try {
      const list = await listResolutions(conf.conferenceId);
      setResolutions(list);
      if (list.length && selectedId == null) setSelectedId(list[list.length - 1].id);
    } catch (err) {
      setNotice({ kind: "error", text: err.message });
    }
  }, [conf.conferenceId, selectedId]);

  useEffect(() => { loadResolutions(); }, [loadResolutions]);

  const selected = useMemo(
    () => resolutions.find((r) => r.id === selectedId) || null,
    [resolutions, selectedId]
  );
  const myVote = selected?.votes?.find((v) => v.country_code === conf.myCountryCode);

  // Draft a complete, submittable resolution in one click (create → add operative clause → submit → review).
  async function draftResolution() {
    if (!canDraft || !conf.delegate) return;
    setActing(true);
    setNotice(null);
    try {
      const created = await createResolution(conf.conferenceId, conf.delegate.id, title.trim());
      await addClause(created.id, conf.delegate.id, "OPERATIVE", clause.trim());
      await submitResolution(created.id, conf.delegate.id);
      await reviewResolution(created.id);
      await loadResolutions();
      setSelectedId(created.id);
      setNotice({ kind: "success", text: "Resolution drafted, submitted and taken under review." });
    } catch (err) {
      setNotice({ kind: "error", text: err.message });
    } finally {
      setActing(false);
    }
  }

  async function castVote(choice) {
    if (!selected || !conf.delegate || !conf.myCountryCode) return;
    setActing(true);
    setNotice(null);
    try {
      const result = await voteOnResolution(selected.id, conf.delegate.id, conf.myCountryCode, choice);
      await loadResolutions();
      await conf.refresh();
      if (result.result) {
        const passed = result.result.passed;
        setNotice({ kind: "success", text: `Voting complete: the resolution ${passed ? "PASSED" : "did not pass"}. ${result.result.reason}` });
        if (passed && onResolutionPassed) onResolutionPassed({ title: selected.title, passed, result: result.result });
      } else {
        setNotice({ kind: "success", text: `${countryName} voted ${choice}.` });
      }
    } catch (err) {
      setNotice({ kind: "error", text: err.message });
    } finally {
      setActing(false);
    }
  }

  const tally = selected?.result;

  return (
    <main style={sharedPageStyle}>
      <Header title="Resolutions & Voting" phase={conf.phase} />
      <Notice notice={notice} onDismiss={() => setNotice(null)} />
      <PhaseControl conf={conf} targetPhase="VOTING" />

      {canDraft && (
        <section style={panelStyle}>
          <div style={{ color: "#36caff", letterSpacing: 3, fontSize: 13, fontWeight: 700 }}>DRAFTING</div>
          <h2 style={{ fontSize: 26 }}>Draft a resolution</h2>
          <label htmlFor="res-title">Title</label>
          <input id="res-title" value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle} maxLength={120} />
          <label htmlFor="res-clause" style={{ display: "block", marginTop: 14 }}>Operative clause</label>
          <textarea id="res-clause" value={clause} onChange={(e) => setClause(e.target.value)} style={{ ...inputStyle, minHeight: 90 }} maxLength={500} />
          <button style={acting ? disabledButtonStyle : { ...buttonStyle, marginTop: 16 }} onClick={draftResolution} disabled={acting || !title.trim() || !clause.trim()}>
            {acting ? "Working…" : "Draft, submit & review"}
          </button>
        </section>
      )}

      <section style={panelStyle}>
        <div style={{ color: "#36caff", letterSpacing: 3, fontSize: 13, fontWeight: 700 }}>RESOLUTION & VOTING</div>
        <h2 style={{ fontSize: 28 }}>Resolution agenda</h2>
        {resolutions.length === 0 ? (
          <p style={{ color: "#9cb5ca", lineHeight: 1.7 }}>
            No resolutions yet. {canDraft ? "Draft one above." : "Resolutions are drafted in the Drafting phase and voted in the Voting phase."}
          </p>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 245px), 1fr))", gap: 14, marginTop: 16 }}>
            {resolutions.map((item) => (
              <button key={item.id} onClick={() => setSelectedId(item.id)} style={{ textAlign: "left", padding: 18, borderRadius: 12, border: selectedId === item.id ? "1px solid #16c7ff" : "1px solid #294b65", background: selectedId === item.id ? "#123750" : "#09192a", color: "#e0efff", cursor: "pointer" }}>
                <small style={{ color: "#40caff" }}>{item.status}</small>
                <h3 style={{ margin: "10px 0" }}>{item.title}</h3>
                <p style={{ color: "#8caac2", marginBottom: 0 }}>Sponsors: {(item.sponsors || []).join(", ") || "—"}</p>
              </button>
            ))}
          </div>
        )}
      </section>

      {selected && (
        <section style={panelStyle}>
          <div style={{ color: "#36caff", letterSpacing: 2, fontSize: 12, fontWeight: 700 }}>SELECTED RESOLUTION</div>
          <h2>{selected.title}</h2>
          <p style={{ color: "#9cb5ca" }}>Status: <strong>{selected.status}</strong></p>
          {(selected.clauses || []).length > 0 && (
            <>
              <h3>Clauses</h3>
              <ol style={{ lineHeight: 2 }}>
                {selected.clauses.map((cl) => <li key={cl.id}>{cl.text}</li>)}
              </ol>
            </>
          )}

          <h3>Cast your vote ({countryName})</h3>
          {myVote ? (
            <p style={{ color: "#68d5ff" }}>Your delegation voted <strong>{myVote.vote}</strong>. One final vote per country.</p>
          ) : (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {["YES", "NO", "ABSTAIN"].map((choice) => (
                <button
                  key={choice}
                  disabled={!canVote || acting}
                  onClick={() => castVote(choice)}
                  style={!canVote || acting ? disabledButtonStyle : buttonStyle}
                  title={canVote ? `Vote ${choice}` : "Advance to the Voting phase first"}
                >
                  {choice}
                </button>
              ))}
            </div>
          )}

          {tally && (
            <div style={{ marginTop: 20 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 12 }}>
                {[["YES", tally.yes], ["NO", tally.no], ["ABSTAIN", tally.abstain]].map(([label, count]) => (
                  <div key={label} style={{ background: "#09192a", border: "1px solid #294b65", borderRadius: 10, padding: 16 }}>
                    <div style={{ color: "#8caac2" }}>{label}</div>
                    <strong style={{ display: "block", fontSize: 28, marginTop: 8 }}>{count}</strong>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 18, padding: 16, borderRadius: 10, background: tally.passed ? "#103a31" : "#3a2029", border: `1px solid ${tally.passed ? "#2d9279" : "#9b485a"}` }}>
                <h3 style={{ marginTop: 0, color: tally.passed ? "#7ce8bd" : "#ffb1a9" }}>
                  {tally.passed ? "Resolution passed" : "Resolution did not pass"}
                </h3>
                <p style={{ marginBottom: 0, color: "#cfe3f3" }}>{tally.reason}</p>
              </div>
            </div>
          )}
        </section>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Living World — real MUN world metrics from the backend snapshot
// ---------------------------------------------------------------------------
function ImpactView({ conf, countryName }) {
  const metrics = conf.metrics;
  const indicators = metrics
    ? [
        { label: "World stability", value: metrics.world_stability, color: "#34d399", description: "Higher is better" },
        { label: "International trust", value: metrics.international_trust, color: "#38bdf8", description: "Higher is better" },
        { label: "Cybersecurity level", value: metrics.cybersecurity_level, color: "#60a5fa", description: "Higher is better" },
        { label: "Diplomatic tension", value: metrics.diplomatic_tension, color: "#fb7185", description: "Lower is better" },
        { label: "Humanitarian impact", value: metrics.humanitarian_impact, color: "#fbbf24", description: "Lower is better" },
        { label: "Economic risk", value: metrics.economic_risk, color: "#f59e0b", description: "Lower is better" },
      ]
    : [];

  const events = conf.events;

  return (
    <main style={sharedPageStyle}>
      <Header title="Living World" phase={conf.phase} />
      <section style={panelStyle}>
        <div style={{ color: "#36caff", letterSpacing: 3, fontSize: 13, fontWeight: 700 }}>WORLD IMPACT</div>
        <h2 style={{ fontSize: 30 }}>Global situation overview</h2>
        <p style={{ color: "#9cb5ca", lineHeight: 1.7 }}>
          These are the conference's live MUN world metrics from the backend. They change as crises are answered
          and resolutions pass. Delegation: <strong>{countryName}</strong>.
        </p>
        {indicators.length === 0 ? (
          <p style={{ color: "#9cb5ca" }}>World metrics are not available yet.</p>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 14, marginTop: 22 }}>
            {indicators.map(({ label, value, color, description }) => (
              <div key={label} style={{ background: "#09192a", border: "1px solid #294b65", borderRadius: 12, padding: 18 }}>
                <div style={{ color: "#8caac2" }}>{label}</div>
                <strong style={{ display: "block", fontSize: 30, margin: "10px 0", color }}>{Math.round(value)}/100</strong>
                <div style={{ height: 6, background: "#1a3044", borderRadius: 8, overflow: "hidden" }}>
                  <div style={{ width: `${value}%`, height: "100%", background: color }} />
                </div>
                <small style={{ display: "block", marginTop: 9, color: "#819ab0" }}>{description}</small>
              </div>
            ))}
          </div>
        )}
      </section>

      <section style={panelStyle}>
        <h2>Recent conference activity</h2>
        {events.length === 0 ? (
          <p style={{ color: "#9cb5ca" }}>No events recorded yet.</p>
        ) : (
          events.slice(0, 8).map((event, index) => (
            <div key={event.id ?? index} style={{ padding: "12px 0", borderBottom: "1px solid #203e56", color: "#b8d4e8" }}>
              {event.message}
            </div>
          ))
        )}
      </section>
    </main>
  );
}
