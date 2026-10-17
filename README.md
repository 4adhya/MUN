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