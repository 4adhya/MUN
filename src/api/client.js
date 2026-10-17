// Thin wrapper around the FastAPI backend. No simulation logic lives here: it only sends requests and
// turns failures into short, user-friendly messages (never stack traces or raw server output).
import { API_BASE_URL } from "./config.js";

export class ApiError extends Error {
  constructor(message, status = null) {
    super(message);
    this.name = "ApiError";
    this.status = status; // null = the backend could not be reached
  }
}

const UNREACHABLE = "Can't reach the simulation server. Make sure the backend is running and try again.";

function friendlyMessage(status, body) {
  const detail = body && body.detail;
  if (status === 422) {
    const first = Array.isArray(detail) && detail[0] ? detail[0] : null;
    const field = first && Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : null;
    return field ? `Invalid request: please check the "${field}" value.` : "Invalid request: please check your input.";
  }
  if (typeof detail === "string" && detail.trim() && status < 500) return detail; // backend's own readable reason (400/404/409)
  if (status >= 500) return "The simulation server hit a problem. Please try again.";
  return "The request could not be completed.";
}

async function request(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(UNREACHABLE);
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    // non-JSON body: fall through with data = null
  }
  if (!response.ok) throw new ApiError(friendlyMessage(response.status, data), response.status);
  if (data === null) throw new ApiError("The simulation server sent an unexpected response.", response.status);
  return data;
}

export const getHealth = () => request("/health");
export const getWorld = () => request("/world");
export const getCountry = (id) => request(`/countries/${encodeURIComponent(id)}`);
export const getEvents = (limit = 100) => request(`/events?limit=${limit}`); // newest first
export const sanction = (actor, target) => request("/actions/sanction", { method: "POST", body: { actor, target } });
export const alliance = (actor, target) => request("/actions/alliance", { method: "POST", body: { actor, target } });
export const aid = (actor, target, amount) => request("/actions/aid", { method: "POST", body: { actor, target, amount } });
export const resetSimulation = () => request("/simulation/reset", { method: "POST" });