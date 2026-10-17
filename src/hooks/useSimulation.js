import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api/client.js";

// Holds the backend's world + events. The backend stays the single source of truth: after every
// action or reset we simply refetch instead of patching local copies.
export function useSimulation() {
  const [world, setWorld] = useState(null);
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState("loading"); // "loading" | "ready" | "error"
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false); // an action/reset is in flight
  const [notice, setNotice] = useState(null); // { kind: "success" | "error", text }
  const [lastAction, setLastAction] = useState(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const load = useCallback(async () => {
    try {
      const [nextWorld, nextEvents] = await Promise.all([api.getWorld(), api.getEvents(100)]);
      if (!mounted.current) return true;
      setWorld(nextWorld);
      setEvents(nextEvents);
      setError("");
      setStatus("ready");
      return true;
    } catch (err) {
      if (!mounted.current) return false;
      setError(err.message);
      setStatus((prev) => (prev === "ready" ? "ready" : "error")); // keep showing the last good data
      return false;
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const retry = useCallback(() => {
    setStatus("loading");
    return load();
  }, [load]);

  const run = useCallback(async (call, successText) => {
    setBusy(true);
    setNotice(null);
    setLastAction(null);
    try {
      const result = await call();
      await load();
      if (mounted.current) {
        setLastAction(result?.event?.effects ? result : null);
        setNotice({ kind: "success", text: successText(result) });
      }
      return true;
    } catch (err) {
      if (mounted.current) setNotice({ kind: "error", text: err.message });
      return false;
    } finally {
      if (mounted.current) setBusy(false);
    }
  }, [load]);

  const act = useCallback(
    (type, actor, target, amount) => {
      const call = () =>
        type === "sanction" ? api.sanction(actor, target)
        : type === "alliance" ? api.alliance(actor, target)
        : api.aid(actor, target, amount);
      return run(call, (res) => res.event.message);
    },
    [run]
  );

  const reset = useCallback(() => run(() => api.resetSimulation(), () => "Simulation reset to its starting state."), [run]);

  return {
    world,
    events,
    status,
    error,
    busy,
    notice,
    lastAction,
    dismissNotice: () => setNotice(null),
    act,
    reset,
    reload: load,
    retry,
  };
}