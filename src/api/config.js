// The ONE place that knows where the backend lives. Set VITE_API_BASE_URL in .env (see .env.example).
const raw = import.meta.env.VITE_API_BASE_URL;

export const API_BASE_URL = (raw && raw.trim() ? raw.trim() : "http://127.0.0.1:8000").replace(/\/+$/, "");