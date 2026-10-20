# 🌍 POLITICA — AI-Powered MUN Simulator

**Diplomacy in Action | Powered by Google Gemma 4**

POLITICA is an interactive geopolitical and Model United Nations simulation where players represent countries, respond to international crises, and make strategic diplomatic decisions. The simulation combines a visual country-selection experience, evolving world conditions, economic relationships, and AI-assisted decision-making.

Built for the **Google Gemma Challenge**, the project integrates Gemma 4 through the Gemini API to generate structured diplomatic proposals based on the current simulation state.

## ✨ Features

- 🌐 **Interactive geopolitical world** — Explore and select countries for the simulation.
- 🏛️ **Country-based gameplay** — Represent a country with its own economic indicators, resources, alliances, sanctions, and trade relationships.
- 🤖 **AI diplomatic advisor** — Request a proposed response to a geopolitical situation.
- 🌍 **Multi-country simulation** — Includes India, China, the United States, France, the United Kingdom, Russia, Japan, and Brazil.
- 📊 **Dynamic world state** — Track GDP, stability, resources, trade routes, and diplomatic relationships.
- ⚖️ **Strategic decisions** — Choose among sanctions, alliances, aid, and no action.
- 🛡️ **Structured AI output** — Validate model-generated proposals before they can be considered by the application.
- 🔄 **Simulation-based diplomacy** — Explore the potential consequences of different policy choices.

## 🦙 Google Gemma 4 Integration

Gemma is integrated through Google's Gemini API using the `google-genai` Python SDK.

**Model:** `gemma-4-26b-a4b-it`

**Integration requirement:** A Gemini API key is used to access the Gemma model. The model identifier and API integration are configured in the backend rather than exposed to the frontend.

### How Gemma works in POLITICA

1. The simulation maintains a world state containing countries, trade routes, resources, alliances, sanctions, and recent events.
2. The user provides a geopolitical situation or crisis.
3. The backend constructs a country-specific prompt using the country's profile, strategic goals, and current world state.
4. Gemma is asked to generate a structured JSON diplomatic proposal.
5. The backend parses and validates the response using Pydantic, checking the decision type and target country.
6. A valid proposal can be presented to the user for consideration. The agent's proposal function does not execute the action itself.

### Supported diplomatic decisions

| Decision | Purpose |
|---|---|
| `SANCTION` | Propose economic or diplomatic pressure against another country. |
| `ALLIANCE` | Propose strengthening diplomatic cooperation. |
| `AID` | Propose providing assistance to another country. |
| `NO_ACTION` | Recommend taking no action in the current turn. |

The model is instructed to return the country, situation summary, decision, target, and reasoning in a structured JSON object. Invalid responses are rejected rather than silently converted into valid decisions.

## 🏗️ Architecture

```text
React + Vite Frontend
        |
        | HTTP requests
        v
FastAPI Backend
        |
        v
Country Agent
        |
        +--> Country Profile
        +--> World-State Briefing
        +--> Decision Prompt
        |
        v
Gemma 4 via Gemini API
        |
        v
JSON Response
        |
        v
Pydantic Validation
        |
        v
Diplomatic Proposal
```

### Technology stack

| Layer | Technology |
|---|---|
| Frontend | React |
| Development server | Vite |
| Backend | Python, FastAPI |
| AI model | Google Gemma 4 |
| Model access | Gemini API |
| AI SDK | `google-genai` |
| Data validation | Pydantic |
| API communication | HTTP / JSON |

## 📁 Project Structure

```text
MUN/
├── ai/
│   ├── check_gemini.py       # API connection verification
│   ├── gemini_client.py      # Gemma API client and generation config
│   ├── country_agent.py      # Country profiles, prompts and validation
│   └── fallback.py           # Handling failed AI proposals
├── backend/
│   └── main.py               # FastAPI endpoints and simulation API
├── src/
│   ├── components/           # React interface components
│   ├── pages/                # Application pages
│   └── api/                  # Frontend API client
├── .env                      # Local API configuration; do not commit
├── .gitignore
├── package.json
└── README.md
```

## 🚀 Getting Started

### Prerequisites

- Python 3.10 or later
- Node.js and npm
- A Google AI Studio API key with access to the configured Gemma model

### 1. Clone the repository

```bash
git clone https://github.com/4adhya/MUN.git
cd MUN
```

### 2. Install frontend dependencies

```bash
npm install
```

### 3. Install backend dependencies

If the repository includes `requirements.txt`, run:

```bash
python3 -m pip install -r requirements.txt
```

If dependencies are not listed there, install the packages required by the project, including FastAPI, Uvicorn, Pydantic, and Google's GenAI SDK.

```bash
python3 -m pip install fastapi "uvicorn[standard]" pydantic google-genai python-dotenv
```

### 4. Configure the Gemini API

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemma-4-26b-a4b-it
```

Replace the placeholder with your own API key.

**Security:** Never commit `.env` or expose your API key in frontend code, screenshots, logs, or the public repository.

### 5. Start the backend

From the project root:

```bash
python3 -m uvicorn backend.main:app --reload --port 8000
```

The backend should be available at:

- API: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/health`

### 6. Start the frontend

Open a second terminal in the project directory:

```bash
npm run dev
```

Open the local URL printed by Vite, usually `http://localhost:5173`.

## 🧪 Verifying the Gemma Integration

Before testing the full simulation, verify that the configured model can respond through the API.

```bash
python3 ai/check_gemini.py
```

A successful connection check confirms that the API key, configured model, and basic generation request are working.

To verify the complete integration, use the application's diplomatic advisor and check that the backend returns a valid, model-generated `CountryDecision` rather than a fallback response.

A successful short JSON response alone does not prove that the complete country-agent workflow is working; the full request must also complete and pass validation.

## ⚠️ Current Development Status

The project has verified basic generation using `gemma-4-26b-a4b-it`. During development, the full country-agent request has also encountered HTTP 500 and HTTP 504 errors.

The complete advisor workflow therefore still requires reliable end-to-end verification. If the model request times out, the application should report the failure clearly instead of presenting a fallback as a genuine AI-generated decision.

## 🔐 Responsible AI and Validation

- The AI agent proposes actions; proposals should not be treated as executed actions.
- Model output is validated before use.
- The target of an action must refer to another country in the simulation.
- `NO_ACTION` requires a null target.
- API credentials remain server-side.
- AI-generated geopolitical reasoning is simulated and should not be interpreted as authoritative real-world policy advice.

## 🎯 Project Goal

POLITICA explores how generative AI can support interactive learning about diplomacy, international relations, economic interdependence, and strategic decision-making.

By combining a simulated world state with country-specific AI agents, the project aims to make geopolitical consequences easier to explore through interactive decisions.

## 🔗 Repository

[GitHub — 4adhya/MUN](https://github.com/4adhya/MUN)

---

*Built for the Google Gemma Challenge using Gemma 4 through the Gemini API.*
