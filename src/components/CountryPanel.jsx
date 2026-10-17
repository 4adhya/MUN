import { useEffect, useState } from "react";
import { MapPin } from "lucide-react";
import { getCountry } from "../api/client.js";
import { countryNames, formatGdp, titleCase } from "../lib/worldView.js";

const ACTIONS = [
  { type: "sanction", label: "Sanction" },
  { type: "alliance", label: "Form alliance" },
  { type: "aid", label: "Send aid" },
];

// Details for the selected country (fetched from GET /countries/{id}) plus the action controls.
export default function CountryPanel({ world, countryId, canAct, actorId, onActorChange, sim, onClose }) {
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState("");
  const [amount, setAmount] = useState("10");
  const names = countryNames(world);
  const fromWorld = world.countries.find((c) => c.id === countryId);

  // Refetch the country whenever the world changes (e.g. after an action) so the panel never shows stale data.
  useEffect(() => {
    let cancelled = false;
    getCountry(countryId)
      .then((c) => { if (!cancelled) { setDetail(c); setDetailError(""); } })
      .catch((err) => { if (!cancelled) setDetailError(err.message); });
    return () => { cancelled = true; };
  }, [countryId, world]);

  const country = detail && detail.id === countryId ? detail : fromWorld;
  if (!country) return null;

  const routes = world.trade_routes.filter((r) => r.exporter === country.id || r.importer === country.id);
  const relationships = Object.entries(country.relationships).sort((a, b) => b[1] - a[1]);
  const actingOnSelf = actorId === country.id;
  const latestAction =
    sim.lastAction?.event?.target === country.id
     ? sim.lastAction
     : null;

  const event = latestAction?.event;
  const effects = event?.effects ?? {};

  const showGDP = (change) =>
    change
     ? `${Number(change.before).toFixed(2)}B → ${Number(change.after).toFixed(2)}B`
     : "—";
  const amountNumber = Number(amount);
  const amountValid = amount.trim() !== "" && Number.isFinite(amountNumber) && amountNumber > 0;

  const run = (type) => sim.act(type, actorId, country.id, amountNumber);

  return (
    <section className="country-panel" aria-label={`${country.name} details`}>
      <div className="country-panel-head">
        <div><MapPin size={16} /><strong>{country.name}</strong><span>Live data from the simulation</span></div>
        <button onClick={onClose}>Close</button>
      </div>
      {detailError && <p className="panel-note">Showing the last loaded data. {detailError}</p>}

      <div className="country-facts">
        <div><small>GDP</small><strong>{formatGdp(country.gdp)}</strong></div>
        <div><small>Stability</small><strong>{country.stability}/100</strong></div>
        <div><small>Trade partners</small><strong>{country.trade_partners.map((id) => names[id]).join(", ") || "None"}</strong></div>
        <div><small>Alliances</small><strong>{country.alliances.join(", ") || "None"}</strong></div>
        <div><small>Sanctioned by</small><strong>{country.sanctions.map((id) => names[id]).join(", ") || "None"}</strong></div>
        <div><small>Resources</small><strong>{Object.entries(country.resources).map(([k, v]) => `${titleCase(k)} ${v}`).join(" · ") || "None"}</strong></div>
      </div>

      <div className="country-lists">
        <div>
          <h3>Trade routes</h3>
          {routes.length === 0 && <p>No trade routes.</p>}
          {routes.map((r) => (
            <p key={r.id} className={r.active ? "" : "route-cut"}>
              {names[r.exporter]} → {names[r.importer]} · {r.resource} · {r.active ? `volume ${r.volume} (${r.efficiency}%)` : "cut off"}
            </p>
          ))}
        </div>
        <div>
          <h3>Relationships</h3>
          {relationships.map(([id, score]) => (
            <p key={id}>{names[id] ?? id}: <b className={score < 0 ? "change-negative" : ""}>{score > 0 ? `+${score}` : score}</b></p>
          ))}
        </div>
      </div>

      {canAct ? (
        <div className="action-bar">
          <label>
            <small>Acting as</small>
            <select value={actorId} onChange={(e) => onActorChange(e.target.value)} disabled={sim.busy}>
              {world.countries.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label>
            <small>Aid amount (B)</small>
            <input type="number" min="1" step="1" value={amount} onChange={(e) => setAmount(e.target.value)} disabled={sim.busy} />
          </label>
          <div className="action-buttons">
            {ACTIONS.map(({ type, label }) => (
              <button
                key={type}
                disabled={sim.busy || actingOnSelf || (type === "aid" && !amountValid)}
                onClick={() => run(type)}
                title={actingOnSelf ? "Choose a different acting country or target" : `${label}: ${names[actorId]} → ${country.name}`}
              >
                {label}
              </button>
            ))}
          </div>
          {actingOnSelf && <p className="panel-note">Pick a target other than {country.name}, or change who is acting.</p>}
        </div>
      ) : (
        <p className="panel-note">Guests can observe only. Choose the Participant or Jury role to take actions.</p>
      )}
            {event && (
        <div className="action-impact" role="status">
          <h3>Action Impact</h3>
          <p className="impact-message">{event.message}</p>

          {event.type === "aid" && (
            <>
              <p>
                <b>Aid transferred:</b> {effects.amount}B
              </p>
              <p>
                <b>{latestAction.actor.name} GDP:</b>{" "}
                {showGDP(effects.actor_gdp)}
              </p>
              <p>
                <b>{latestAction.target.name} GDP:</b>{" "}
                {showGDP(effects.target_gdp)}
              </p>
              <p>
                <b>Target stability:</b>{" "}
                {effects.target_stability.before} →{" "}
                {effects.target_stability.after} / 100
              </p>
              <p>
                <b>Relationship score:</b> {effects.relationship} / 100
              </p>
            </>
          )}

          {event.type === "sanction" && (
            <>
              <p>
                <b>Target GDP:</b> {showGDP(effects.target_gdp)}
              </p>
              <p>
                <b>Target stability:</b>{" "}
                {effects.target_stability.before} →{" "}
                {effects.target_stability.after} / 100
              </p>
              <p>
                <b>Relationship score:</b> {effects.relationship} / 100
              </p>
              <p>
                <b>Trade routes cut:</b>{" "}
                {effects.trade_routes_deactivated?.length ?? 0}
              </p>
            </>
          )}

          {event.type === "alliance" && (
            <>
              <p>
                <b>Alliance:</b> {effects.alliance}
              </p>
              <p>
                <b>{latestAction.actor.name} stability:</b>{" "}
                {effects.stability?.[latestAction.actor.id]?.before} →{" "}
                {effects.stability?.[latestAction.actor.id]?.after} / 100
              </p>
              <p>
                <b>{latestAction.target.name} stability:</b>{" "}
                {effects.stability?.[latestAction.target.id]?.before} →{" "}
                {effects.stability?.[latestAction.target.id]?.after} / 100
              </p>
              <p>
                <b>Relationship score:</b> {effects.relationship} / 100
              </p>
              <p>
                <b>Trade routes affected:</b>{" "}
                {Object.keys(effects.trade_routes_boosted ?? {}).length}
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}