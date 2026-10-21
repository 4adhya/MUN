import { API_BASE_URL } from "./config.js";

export class ApiError extends Error {
  constructor(message, status = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const UNREACHABLE =
  "Can't reach the simulation server. Make sure the backend is running and try again.";


async function request(path, { method = "GET", body, timeoutMs = 90000 } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  let response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new ApiError("The AI took too long to respond. Please retry.");
    }
    throw new ApiError(UNREACHABLE);
  } finally {
    clearTimeout(timeout);
  }

  let data = null;

  try {
    data = await response.json();
  } catch {
    // Handle a non-JSON response below.
  }

  if (!response.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : response.status >= 500
          ? "The AI service encountered an error. Please retry."
          : "The request could not be completed.";

    throw new ApiError(message, response.status);
  }

  if (data === null) {
    throw new ApiError("The server sent an unexpected response.", response.status);
  }

  return data;
}


export const getHealth = () => request("/health");

export const getWorld = () => request("/world");

export const getCountry = (id) =>
  request(`/countries/${encodeURIComponent(id)}`);

export const getEvents = (limit = 100) =>
  request(`/events?limit=${limit}`);

// Read-only: summarises the recorded simulation. Safe to call repeatedly.
export const getReport = () => request("/simulation/report");


export const proposeAI = (countryId, situation, { timeoutMs = 60000 } = {}) =>
  request("/ai/propose", {
    method: "POST",
    body: {
      country_id: countryId,
      situation,
    },
    timeoutMs,
  });


export const askAdvisor = (countryId, message, history = [], { timeoutMs = 60000 } = {}) =>
  request("/ai/advisor", {
    method: "POST",
    body: { country_id: countryId, message, history },
    timeoutMs,
  });


export const sanction = (actor, target) =>
  request("/actions/sanction", {
    method: "POST",
    body: { actor, target },
  });

export const alliance = (actor, target) =>
  request("/actions/alliance", {
    method: "POST",
    body: { actor, target },
  });

export const aid = (actor, target, amount) =>
  request("/actions/aid", {
    method: "POST",
    body: { actor, target, amount },
  });

export const resetSimulation = () =>
  request("/simulation/reset", {
    method: "POST",
  });