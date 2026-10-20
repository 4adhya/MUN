# React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and Oxlint's TypeScript related rules in your project.


## Running the simulation (frontend + backend)

```bash
# 1. Backend (from the repo root)
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --port 8000

# 2. Frontend (new terminal)
cp .env.example .env     # VITE_API_BASE_URL defaults to http://127.0.0.1:8000
npm install
npm run dev              # http://localhost:5173
```

The frontend reads the backend URL only from `VITE_API_BASE_URL` (see `src/api/config.js`). The backend already allows
the Vite dev origins (`localhost:5173` / `127.0.0.1:5173`); for another origin set `CORS_ORIGINS`.

## Gemma Integration

This project uses **Gemma through the Gemini API** for its AI country delegate.

- **Model:** `gemma-4-26b-a4b-it` (set in `ai/check_gemini.py` as `DEFAULT_MODEL`; override with `GEMINI_MODEL`, which must start with `gemma-`, e.g. `gemma-4-31b-it`). Any non-Gemma value is refused with an error; there is no silent switch to Gemini Flash.
- **API:** `google-genai` SDK, `client.models.generate_content(model=..., config=...)` with a system instruction and JSON output. The only call site is `generate_json_text()` in `ai/gemini_client.py`.
- **MUN feature:** in the Conference Room, **Generate AI proposal** sends the selected country's profile, the live world state and the scenario to Gemma. Gemma returns a `CountryDecision` (`SANCTION` / `ALLIANCE` / `AID` / `NO_ACTION`, target, reason).
- **Boundary:** Gemma only proposes. The response is validated with Pydantic (`ai/country_agent.py`), then the user clicks **Approve & execute**, and the backend rules engine (`/actions/*`) validates and applies it. Gemma never changes world state.
- **Failure behaviour:** if the Gemma call fails or its output is invalid, `/ai/propose` returns `source: "fallback"`, `model: null` and a `NO_ACTION`; the UI shows an error instead of presenting it as a Gemma answer. No other model is tried.

### Configure and run

```bash
cp .env.example .env          # put your real GEMINI_API_KEY in .env
pip install -r backend/requirements.txt -r ai/requirements.txt
python ai/check_gemini.py     # prints "model : gemma-4-26b-a4b-it" and a live reply
python -m uvicorn backend.main:app --reload --port 8000
npm install && npm run dev
```

### Example

```bash
curl -s localhost:8000/ai/propose -H 'content-type: application/json' \
  -d '{"country_id":"india","situation":"Brazil blocked our trade route."}'
```

```json
{"source":"ai","model":"gemma-4-26b-a4b-it","used_fallback":false,"error_code":null,"error":null,
 "decision":{"country":"India","situation":"...","decision":"SANCTION","target":"Brazil","reason":"..."}}
```

(Illustrative shape; the decision content comes from the live model.) A judge can confirm Gemma is used by checking `"model"` in this response, the `GEMMA GENERATED · <model>` label in the UI, and `python ai/check_gemini.py` output.

### Tests

`python -m pytest -q` needs no API key (Gemma is mocked). `ai/test_country_agent_live.py` calls the real Gemma API only when `GEMINI_API_KEY` is set.