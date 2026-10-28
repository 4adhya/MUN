import { API_BASE_URL } from "./config.js";

export class ApiError extends Error {
  constructor(message, status = null, { failureType = null, reason = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    // Set only for AI failures (see AI_FAILURE_LABELS): which kind of failure it was.
    this.failureType = failureType;
    this.reason = reason;
  }
}

// Stable failure types sent by the backend when an AI request does not produce a usable answer.
// An AI failure is never a decision: it must be shown as a failure, never as "No action needed".
export const AI_FAILURE_LABELS = {
  AI_REQUEST_FAILED: "AI request failed",
  TIMEOUT: "AI request timed out",
  QUOTA_ERROR: "AI quota or rate limit reached",
  SERVER_ERROR: "AI service error",
  MODEL_UNAVAILABLE: "AI model unavailable",
  MALFORMED_RESPONSE: "AI returned a malformed response",
  INVALID_OUTPUT: "AI output was rejected as invalid",
};

export const aiFailureLabel = (failureType) =>
  AI_FAILURE_LABELS[failureType] || AI_FAILURE_LABELS.AI_REQUEST_FAILED;

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
      throw new ApiError("The AI took too long to respond. Please retry.", null, {
        failureType: "TIMEOUT",
        reason: "CLIENT_TIMEOUT",
      });
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
    // AI failures carry failure_type at the top level (/ai/propose, /ai/advisor, /ai/mun/*) or inside a dict `detail`.
    const failureType = data?.failure_type || (detail && typeof detail === "object" ? detail.failure_type : null) || null;
    const reason = data?.reason || (detail && typeof detail === "object" ? detail.reason : null) || null;
    const detailText =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && typeof detail.error === "string"
          ? detail.error
          : null;
    const message =
      detailText ||
      (response.status >= 500
        ? "The AI service encountered an error. Please retry."
        : "The request could not be completed.");

    throw new ApiError(message, response.status, { failureType, reason });
  }

  if (data === null) {
    throw new ApiError("The server sent an unexpected response.", response.status);
  }

  // Defence in depth: a failure body must never be treated as a successful answer, whatever its HTTP status.
  if (data && data.status === "AI_REQUEST_FAILED") {
    throw new ApiError(
      typeof data.detail === "string" ? data.detail : "The AI request failed. No decision was made.",
      response.status,
      { failureType: data.failure_type || "AI_REQUEST_FAILED", reason: data.reason || null }
    );
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

// The backend allows Gemma up to ~55 s in total; wait a bit longer so its real error reaches the UI.
export const proposeAI = (countryId, situation, { timeoutMs = 70000 } = {}) =>
  request("/ai/propose", {
    method: "POST",
    body: {
      country_id: countryId,
      situation,
    },
    timeoutMs,
  });

export const askAdvisor = (countryId, message, history = [], { timeoutMs = 70000 } = {}) =>
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

// ---------------------------------------------------------------------------
// Phase 11: the MUN conference API (the backend is the single source of truth
// for phase, status, world metrics, speeches, negotiations, resolutions,
// voting and crises). These simply mirror the FastAPI routes in backend/.
// ---------------------------------------------------------------------------

// --- Conference lifecycle --------------------------------------------------
export const createConference = (name, committee, topic) =>
  request("/conference/create", {
    method: "POST",
    body: { name, committee, topic },
  });

export const joinConference = (conferenceId, { name, role, country } = {}) =>
  request(`/conference/${encodeURIComponent(conferenceId)}/join`, {
    method: "POST",
    body: country ? { name, role, country } : { name, role },
  });

export const getConference = (conferenceId) =>
  request(`/conference/${encodeURIComponent(conferenceId)}`);

export const startConference = (conferenceId) =>
  request(`/conference/${encodeURIComponent(conferenceId)}/start`, {
    method: "POST",
  });

// The backend always decides the next phase; `toPhase` is only an optional stale-screen guard.
export const advanceConference = (conferenceId, toPhase) =>
  request(`/conference/${encodeURIComponent(conferenceId)}/advance`, {
    method: "POST",
    body: toPhase ? { to_phase: toPhase } : undefined,
  });

export const checkConferenceAction = (conferenceId, action) =>
  request(`/conference/${encodeURIComponent(conferenceId)}/actions/check`, {
    method: "POST",
    body: { action },
  });

export const getConferenceReport = (conferenceId) =>
  request(`/conference/${encodeURIComponent(conferenceId)}/report`);

// --- Speeches and the speaker queue ----------------------------------------
export const submitSpeech = (conferenceId, participantId, countryCode, text) =>
  request(`/conference/${encodeURIComponent(conferenceId)}/speech`, {
    method: "POST",
    body: { participant_id: participantId, country_code: countryCode, text },
  });

export const listSpeeches = (conferenceId, { phase, countryCode } = {}) => {
  const params = new URLSearchParams();
  if (phase) params.set("phase", phase);
  if (countryCode) params.set("country_code", countryCode);
  const query = params.toString();
  return request(`/conference/${encodeURIComponent(conferenceId)}/speeches${query ? `?${query}` : ""}`);
};

export const getSpeakers = (conferenceId) =>
  request(`/conference/${encodeURIComponent(conferenceId)}/speakers`);

export const nextSpeaker = (conferenceId) =>
  request(`/conference/${encodeURIComponent(conferenceId)}/speaker/next`, {
    method: "POST",
  });

// --- Negotiations ----------------------------------------------------------
export const proposeNegotiation = (conferenceId, participantId, receiver, proposal) =>
  request("/negotiation/propose", {
    method: "POST",
    body: { conference_id: conferenceId, participant_id: participantId, receiver, proposal },
  });

export const respondToNegotiation = (negotiationId, participantId, action, counterOffer) =>
  request(`/negotiation/${encodeURIComponent(negotiationId)}/respond`, {
    method: "POST",
    body: counterOffer
      ? { participant_id: participantId, action, counter_offer: counterOffer }
      : { participant_id: participantId, action },
  });

export const listNegotiations = (conferenceId, { status, countryCode } = {}) => {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (countryCode) params.set("country_code", countryCode);
  const query = params.toString();
  return request(`/conference/${encodeURIComponent(conferenceId)}/negotiations${query ? `?${query}` : ""}`);
};

// --- Resolutions and voting ------------------------------------------------
export const createResolution = (conferenceId, participantId, title, sponsors = []) =>
  request("/resolution", {
    method: "POST",
    body: { conference_id: conferenceId, participant_id: participantId, title, sponsors },
  });

export const getResolution = (resolutionId) =>
  request(`/resolution/${encodeURIComponent(resolutionId)}`);

export const addClause = (resolutionId, participantId, type, text) =>
  request(`/resolution/${encodeURIComponent(resolutionId)}/clause`, {
    method: "POST",
    body: { participant_id: participantId, type, text },
  });

export const submitResolution = (resolutionId, participantId) =>
  request(`/resolution/${encodeURIComponent(resolutionId)}/submit`, {
    method: "POST",
    body: { participant_id: participantId },
  });

export const reviewResolution = (resolutionId) =>
  request(`/resolution/${encodeURIComponent(resolutionId)}/review`, {
    method: "POST",
  });

export const voteOnResolution = (resolutionId, participantId, countryCode, vote) =>
  request(`/resolution/${encodeURIComponent(resolutionId)}/vote`, {
    method: "POST",
    body: { participant_id: participantId, country_code: countryCode, vote },
  });

export const listResolutions = (conferenceId, { status } = {}) => {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  const query = params.toString();
  return request(`/conference/${encodeURIComponent(conferenceId)}/resolutions${query ? `?${query}` : ""}`);
};

// --- Crises ----------------------------------------------------------------
export const listCrisisTemplates = () => request("/crisis-templates");

export const createCrisis = (conferenceId, participantId, { templateId, title, description, severity, optionTypes } = {}) => {
  const body = { conference_id: conferenceId, participant_id: participantId };
  if (templateId) body.template_id = templateId;
  if (title) body.title = title;
  if (description) body.description = description;
  if (severity) body.severity = severity;
  if (optionTypes) body.option_types = optionTypes;
  return request("/crisis", { method: "POST", body });
};

export const getCrisis = (crisisId) =>
  request(`/crisis/${encodeURIComponent(crisisId)}`);

export const respondToCrisis = (crisisId, participantId, countryCode, optionId) =>
  request(`/crisis/${encodeURIComponent(crisisId)}/respond`, {
    method: "POST",
    body: { participant_id: participantId, country_code: countryCode, option_id: optionId },
  });

export const resolveCrisis = (crisisId, participantId) =>
  request(`/crisis/${encodeURIComponent(crisisId)}/resolve`, {
    method: "POST",
    body: { participant_id: participantId },
  });

export const listCrises = (conferenceId, { status } = {}) => {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  const query = params.toString();
  return request(`/conference/${encodeURIComponent(conferenceId)}/crises${query ? `?${query}` : ""}`);
};

// --- Conference AI roles (advisory / proposal-only) ------------------------
// Each returns { status, advisory, executed, output, ... } on success, or throws
// an ApiError carrying failureType on an AI failure. An AI failure is never a decision.
export const aiStrategy = (conferenceId, countryCode, focus, opts = {}) =>
  request("/ai/mun/strategy", {
    method: "POST",
    body: focus ? { conference_id: conferenceId, country_code: countryCode, focus } : { conference_id: conferenceId, country_code: countryCode },
    timeoutMs: opts.timeoutMs ?? 70000,
  });

export const aiSpeech = (conferenceId, countryCode, speechType, { targetCode, brief } = {}, opts = {}) => {
  const body = { conference_id: conferenceId, country_code: countryCode, speech_type: speechType };
  if (targetCode) body.target_code = targetCode;
  if (brief) body.brief = brief;
  return request("/ai/mun/speech", { method: "POST", body, timeoutMs: opts.timeoutMs ?? 70000 });
};

export const aiCrisis = (conferenceId, countryCode, crisis, opts = {}) =>
  request("/ai/mun/crisis", {
    method: "POST",
    body: { conference_id: conferenceId, country_code: countryCode, crisis },
    timeoutMs: opts.timeoutMs ?? 70000,
  });

export const aiResolutionClauses = (conferenceId, countryCode, resolutionId, focus, opts = {}) => {
  const body = { conference_id: conferenceId, country_code: countryCode, resolution_id: resolutionId };
  if (focus) body.focus = focus;
  return request("/ai/mun/resolution/clauses", { method: "POST", body, timeoutMs: opts.timeoutMs ?? 70000 });
};

export const aiChair = (conferenceId, question, opts = {}) =>
  request("/ai/mun/chair", {
    method: "POST",
    body: question ? { conference_id: conferenceId, question } : { conference_id: conferenceId },
    timeoutMs: opts.timeoutMs ?? 70000,
  });

export const aiJudge = (conferenceId, opts = {}) =>
  request("/ai/mun/judge", {
    method: "POST",
    body: { conference_id: conferenceId },
    timeoutMs: opts.timeoutMs ?? 70000,
  });
