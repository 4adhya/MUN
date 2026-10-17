// Display helpers only: they reshape what the backend already returned (sums, lists, labels).
// No simulation rules live here; the backend decides every outcome.

// Where each fictional country's marker sits on the illustrative map (percent of the map box).
// This is purely visual placement; the backend has no coordinates.
export const MAP_LAYOUT = {
  aurelia: { x: 14, y: 30 },
  brevania: { x: 31, y: 17 },
  helvaris: { x: 48, y: 25 },
  dravenia: { x: 65, y: 17 },
  jorvania: { x: 83, y: 28 },
  caldoria: { x: 34, y: 50 },
  eldoria: { x: 53, y: 54 },
  garvonia: { x: 72, y: 51 },
  istoria: { x: 20, y: 70 },
  fyrnia: { x: 86, y: 66 },
};

export const countryNames = (world) => Object.fromEntries(world.countries.map((c) => [c.id, c.name]));

export function tradeVolumeByCountry(world) {
  const totals = Object.fromEntries(world.countries.map((c) => [c.id, 0]));
  for (const route of world.trade_routes) {
    if (!route.active) continue;
    totals[route.exporter] = (totals[route.exporter] ?? 0) + route.volume;
    totals[route.importer] = (totals[route.importer] ?? 0) + route.volume;
  }
  return totals;
}

export function worldTotals(world) {
  const count = world.countries.length || 1;
  const sanctions = world.countries.flatMap((c) => c.sanctions.map((actor) => ({ actor, target: c.id })));
  return {
    totalGdp: world.countries.reduce((sum, c) => sum + c.gdp, 0),
    averageStability: world.countries.reduce((sum, c) => sum + c.stability, 0) / count,
    activeTradeVolume: world.trade_routes.filter((r) => r.active).reduce((sum, r) => sum + r.volume, 0),
    activeRoutes: world.trade_routes.filter((r) => r.active).length,
    totalRoutes: world.trade_routes.length,
    sanctions,
    cutRoutes: world.trade_routes.filter((r) => !r.active),
  };
}

// One line per pair of countries (the backend has a route in each direction for most pairs).
export function routePairs(world) {
  const pairs = new Map();
  for (const route of world.trade_routes) {
    const key = [route.exporter, route.importer].sort().join("|");
    const entry = pairs.get(key) ?? { a: route.exporter, b: route.importer, anyActive: false };
    entry.anyActive = entry.anyActive || route.active;
    pairs.set(key, entry);
  }
  return [...pairs.values()];
}

export const stabilityLevel = (value) => (value >= 70 ? "high" : value >= 50 ? "medium" : "low");
export const stabilityLabel = (value) => (value >= 70 ? "High" : value >= 50 ? "Medium" : "Low");
export const formatGdp = (value) => `${Number(value).toLocaleString("en-US", { maximumFractionDigits: 1 })}B`;
export const titleCase = (text) => text.charAt(0).toUpperCase() + text.slice(1);

export function timeAgo(timestamp) {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(timestamp).getTime()) / 1000));
  if (Number.isNaN(seconds)) return "";
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}