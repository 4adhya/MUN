import { useCallback, useEffect, useState } from "react";
import { FileText, RefreshCw, X } from "lucide-react";
import { getReport } from "../api/client.js";
import "./ReportModal.css";

const fmt = (value) => (value === null || value === undefined ? "—" : value);
const delta = (before, after) =>
  before === null || before === undefined || after === null || after === undefined
    ? "—"
    : `${before} → ${after}`;

function Section({ title, count, children }) {
  return (
    <section className="rpt-section">
      <h3>{title}{count !== undefined && <span className="rpt-count">{count}</span>}</h3>
      {children}
    </section>
  );
}

const Empty = ({ children }) => <p className="rpt-empty">{children}</p>;

// Renders the backend's report exactly as returned. Nothing is computed or invented here.
export default function ReportModal({ onClose }) {
  const [state, setState] = useState({ status: "loading", report: null, error: "" });

  const [attempt, setAttempt] = useState(0);
  const load = useCallback(() => {
    setState((prev) => ({ ...prev, status: "loading", error: "" }));
    setAttempt((n) => n + 1);
  }, []);

  // The initial state is already "loading", so the first fetch needs no state reset.
  useEffect(() => {
    let cancelled = false;
    getReport()
      .then((report) => !cancelled && setState({ status: "ready", report, error: "" }))
      .catch((err) => !cancelled && setState((prev) => ({ ...prev, status: "error", error: err.message || "The report could not be generated." })));
    return () => { cancelled = true; };
  }, [attempt]);

  useEffect(() => {
    const onKey = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const { status, report, error } = state;

  return (
    <div className="cr-modal-backdrop" onClick={onClose}>
      <div className="rpt-modal" role="dialog" aria-modal="true" aria-label="Simulation report" onClick={(event) => event.stopPropagation()}>
        <div className="cr-modal-heading">
          <div>
            <span className="cr-eyebrow">SIMULATION REPORT</span>
            <h2>Session report</h2>
          </div>
          <div className="rpt-head-actions">
            <button type="button" className="cr-modal-close" onClick={load} disabled={status === "loading"} aria-label="Regenerate report"><RefreshCw size={15} /></button>
            <button type="button" className="cr-modal-close" onClick={onClose} aria-label="Close"><X size={18} /></button>
          </div>
        </div>

        {status === "loading" && !report && <p className="rpt-state" role="status">Generating report…</p>}

        {status === "error" && (
          <div className="rpt-state rpt-error" role="alert">
            <p>{error}</p>
            <button type="button" className="cr-secondary-button" onClick={load}>Try again</button>
          </div>
        )}

        {report && (
          <div className="rpt-body">
            <p className="rpt-meta">
              <FileText size={13} /> Generated {new Date(report.generated_at).toLocaleString()} · {report.event_count} recorded event{report.event_count === 1 ? "" : "s"}
            </p>

            <Section title="Overall outcome">
              <p className="rpt-summary">{report.outcome.summary}</p>
              {report.outcome.highlights.length > 0 && (
                <ul>{report.outcome.highlights.map((line) => <li key={line}>{line}</li>)}</ul>
              )}
            </Section>

            {!report.activity_recorded && (
              <Empty>No diplomatic actions have been taken yet. Propose an alliance or sanctions, then generate the report again.</Empty>
            )}

            <Section title="Participating countries" count={report.participating_countries.length}>
              {report.participating_countries.length === 0 ? <Empty>None yet.</Empty> : (
                <ul>{report.participating_countries.map((c) => (
                  <li key={c.id}>{c.flag} <b>{c.name}</b> — {c.actions_initiated} initiated, {c.actions_received} received{c.delegate ? ` (delegate: ${c.delegate})` : ""}</li>
                ))}</ul>
              )}
            </Section>

            <Section title="Alliances" count={report.alliances.length}>
              {report.alliances.length === 0 ? <Empty>No alliances formed.</Empty> : (
                <ul>{report.alliances.map((a) => <li key={a.event_id}>{a.name || a.member_names.join(" & ")} <small>(event #{a.event_id})</small></li>)}</ul>
              )}
            </Section>

            <Section title="Sanctions" count={report.sanctions.length}>
              {report.sanctions.length === 0 ? <Empty>No sanctions imposed.</Empty> : (
                <ul>{report.sanctions.map((s) => (
                  <li key={s.event_id}>
                    <b>{s.imposed_by_name}</b> sanctioned <b>{s.target_name}</b> — GDP {delta(s.target_gdp_before, s.target_gdp_after)}, stability {delta(s.target_stability_before, s.target_stability_after)}
                    {s.trade_routes_suspended.length > 0 && `, ${s.trade_routes_suspended.length} trade route(s) suspended`}
                  </li>
                ))}</ul>
              )}
            </Section>

            <Section title="Aid" count={report.aid.length}>
              {report.aid.length === 0 ? <Empty>No aid sent.</Empty> : (
                <ul>{report.aid.map((a) => (
                  <li key={a.event_id}><b>{a.donor_name}</b> sent {fmt(a.amount)} to <b>{a.recipient_name}</b> — recipient GDP {delta(a.recipient_gdp_before, a.recipient_gdp_after)}</li>
                ))}</ul>
              )}
            </Section>

            <Section title="Trade changes" count={report.trade_changes.length}>
              {report.trade_changes.length === 0 ? <Empty>No trade routes changed.</Empty> : (
                <ul>{report.trade_changes.map((t) => (
                  <li key={t.route_id}>{t.exporter} → {t.importer} ({t.resource}): volume {t.volume_before} → {t.volume_after}{t.active_before && !t.active_after ? " · suspended" : ""}</li>
                ))}</ul>
              )}
            </Section>

            <Section title="Diplomatic events" count={report.diplomatic_events.length}>
              {report.diplomatic_events.length === 0 ? <Empty>No events recorded.</Empty> : (
                <ol>{report.diplomatic_events.map((e) => <li key={e.id}><small>Turn {e.turn} · {e.type}</small> {e.message}</li>)}</ol>
              )}
            </Section>

            <Section title="World-state changes" count={report.world_changes.length}>
              {report.world_changes.length === 0 ? <Empty>The world is unchanged from its starting state.</Empty> : (
                <ul>{report.world_changes.map((c) => (
                  <li key={c.id}>
                    <b>{c.name}</b> — GDP {delta(c.gdp_before, c.gdp_after)}, stability {delta(c.stability_before, c.stability_after)}
                    {c.alliances_added.length > 0 && `, joined ${c.alliances_added.join(", ")}`}
                    {c.sanctions_received_from.length > 0 && `, sanctioned by ${c.sanctions_received_from.join(", ")}`}
                  </li>
                ))}</ul>
              )}
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}