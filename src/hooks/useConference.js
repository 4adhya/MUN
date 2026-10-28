import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api/client.js";

// The backend owns the whole MUN conference: phase, status, the world/metrics, speeches,
// negotiations, resolutions, votes and crises. This hook never advances the conference on its
// own and never fabricates phase/opponent/world state — it bootstraps one conference on the
// backend, then keeps a fresh snapshot of what the backend reports.
//
// Bootstrap sequence (all real backend calls):
//   1. POST /conference/create         -> a WAITING conference in LOBBY
//   2. POST /conference/{id}/join      -> the human delegate, seated on the chosen country
//   3. POST /conference/{id}/join      -> a JURY member (needed to run/resolve crises)
//   4. POST /conference/{id}/start     -> seats countries, builds the world, enters ROLL_CALL
//
// `advance()` calls POST /conference/{id}/advance and lets the BACKEND decide the next phase.

const DEFAULT_COMMITTEE = "UNSC";
const DEFAULT_TOPIC =
  "International response to escalating geopolitical tensions and their impact on global stability.";

export function useConference(countryName, { committee = DEFAULT_COMMITTEE, topic = DEFAULT_TOPIC } = {}) {
  const [snapshot, setSnapshot] = useState(null); // the ConferenceSnapshot (phase, status, world, ...)
  const [delegate, setDelegate] = useState(null); // our Participant { id, country_code, ... }
  const [jury, setJury] = useState(null); // the jury Participant (so the UI can run crises)
  const [events, setEvents] = useState([]); // conference world events, newest-first for display
  const [status, setStatus] = useState("loading"); // "loading" | "ready" | "error"
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false); // an advance/action is in flight
  const [notice, setNotice] = useState(null); // { kind: "success" | "error", text }
  const mounted = useRef(true);
  const bootstrapped = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const applySnapshot = useCallback((snap) => {
    if (!mounted.current || !snap) return;
    setSnapshot(snap);
    const worldEvents = snap.world?.events || [];
    setEvents([...worldEvents].reverse()); // newest first for the live record
  }, []);

  const refresh = useCallback(async () => {
    const id = snapshot?.id;
    if (!id) return null;
    try {
      const snap = await api.getConference(id);
      applySnapshot(snap);
      if (mounted.current) setError("");
      return snap;
    } catch (err) {
      if (mounted.current) setError(err.message);
      return null;
    }
  }, [snapshot?.id, applySnapshot]);

  const bootstrap = useCallback(async () => {
    if (!mounted.current) return;
    setStatus("loading");
    setError("");
    try {
      const created = await api.createConference(
        `${countryName || "Delegation"} — Live Session`,
        committee,
        topic
      );
      const del = await api.joinConference(created.id, {
        name: `${countryName || "Delegate"} delegation`,
        role: "PARTICIPANT",
        country: countryName,
      });
      // A jury member lets the conference run crises (JURY starts/resolves them).
      const jur = await api.joinConference(created.id, {
        name: "Conference Jury",
        role: "JURY",
      });
      const started = await api.startConference(created.id);

      if (!mounted.current) return;
      setDelegate(del);
      setJury(jur);
      applySnapshot(started);
      setStatus("ready");
    } catch (err) {
      if (!mounted.current) return;
      setError(err.message || "Could not start the conference on the backend.");
      setStatus("error");
    }
  }, [countryName, committee, topic, applySnapshot]);

  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    bootstrap();
  }, [bootstrap]);

  const retry = useCallback(() => {
    bootstrapped.current = true;
    return bootstrap();
  }, [bootstrap]);

  // Advance exactly one phase. The backend picks the next phase; we only refresh to what it reports.
  const advance = useCallback(async () => {
    const id = snapshot?.id;
    if (!id) return false;
    setBusy(true);
    setNotice(null);
    try {
      const snap = await api.advanceConference(id);
      applySnapshot(snap);
      if (mounted.current) {
        const label =
          snap.status === "COMPLETED"
            ? "Conference completed. Final results are in."
            : `Advanced to ${phaseLabel(snap.current_phase)}.`;
        setNotice({ kind: "success", text: label });
      }
      return true;
    } catch (err) {
      if (mounted.current) setNotice({ kind: "error", text: err.message });
      return false;
    } finally {
      if (mounted.current) setBusy(false);
    }
  }, [snapshot?.id, applySnapshot]);

  // Run a backend action (speech, negotiation, crisis, vote, ...) then refresh to the new snapshot.
  const runAction = useCallback(
    async (call, successText) => {
      setBusy(true);
      setNotice(null);
      try {
        const result = await call();
        await refresh();
        if (mounted.current && successText) {
          setNotice({ kind: "success", text: typeof successText === "function" ? successText(result) : successText });
        }
        return result;
      } catch (err) {
        if (mounted.current) setNotice({ kind: "error", text: err.message });
        throw err;
      } finally {
        if (mounted.current) setBusy(false);
      }
    },
    [refresh]
  );

  const conferenceId = snapshot?.id || null;
  const phase = snapshot?.current_phase || null;
  const conferenceStatus = snapshot?.status || null;
  const nextPhase = snapshot?.next_phase || null;
  const allowedActions = snapshot?.allowed_actions || [];
  const metrics = snapshot?.world?.mun_metrics || null;
  const countries = snapshot?.world?.countries || [];
  const assigned = snapshot?.assigned_countries || [];
  const myCountryCode = delegate?.country_code || null;
  const myCountry = assigned.find((a) => a.country_code === myCountryCode) || null;

  return {
    // identity
    conferenceId,
    delegate,
    jury,
    myCountryCode,
    myCountry,
    // backend-authoritative state
    snapshot,
    phase,
    conferenceStatus,
    nextPhase,
    allowedActions,
    metrics,
    countries,
    assigned,
    events,
    // lifecycle
    status,
    error,
    busy,
    notice,
    dismissNotice: () => setNotice(null),
    advance,
    refresh,
    runAction,
    retry,
  };
}

// Human-readable phase names used across the conference UI.
const PHASE_LABELS = {
  LOBBY: "Lobby",
  ROLL_CALL: "Roll Call",
  OPENING_SPEECHES: "Opening Speeches",
  MODERATED_CAUCUS: "Moderated Caucus",
  UNMODERATED_CAUCUS: "Unmoderated Caucus",
  CRISIS: "Crisis",
  DRAFTING: "Drafting",
  VOTING: "Voting",
  RESULTS: "Results",
  COMPLETED: "Completed",
};

export function phaseLabel(phase) {
  return PHASE_LABELS[phase] || phase || "—";
}

export const PHASE_SEQUENCE = [
  "ROLL_CALL",
  "OPENING_SPEECHES",
  "MODERATED_CAUCUS",
  "UNMODERATED_CAUCUS",
  "CRISIS",
  "DRAFTING",
  "VOTING",
  "RESULTS",
];
