"""FastAPI entry point.

Run from the backend/ folder:
    uvicorn main:app --reload
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import Country, WorldState
from simulation import simulation

app = FastAPI(title="MUN Simulation API", version="0.1.0")

# Allow the Vite/React dev server to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/world", response_model=WorldState)
def get_world() -> WorldState:
    return simulation.world


@app.get("/countries/{country_id}", response_model=Country)
def get_country(country_id: str) -> Country:
    country = simulation.get_country(country_id.lower())
    if country is None:
        raise HTTPException(status_code=404, detail=f"Country '{country_id}' not found")
    return country
