"""Quick smoke test. Run from backend/:  python test_smoke.py"""
from fastapi.testclient import TestClient

from main import app
from rules import validate_world
from simulation import create_initial_world

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_world():
    w = client.get("/world").json()
    assert w["turn"] == 0
    assert w["events"] == []
    assert len(w["countries"]) == 10
    assert len(w["trade_routes"]) > 0
    required = {"id", "name", "gdp", "stability", "resources",
                "trade_partners", "alliances", "sanctions", "relationships"}
    for c in w["countries"]:
        assert required <= set(c), c["id"]
        assert len(c["relationships"]) == 9


def test_country():
    r = client.get("/countries/aurelia")
    assert r.status_code == 200 and r.json()["id"] == "aurelia"
    assert client.get("/countries/AURELIA").status_code == 200
    assert client.get("/countries/atlantis").status_code == 404


def test_world_is_consistent_and_deterministic():
    assert validate_world(create_initial_world()) == []
    assert create_initial_world() == create_initial_world()


def test_cors():
    r = client.options("/world", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    })
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
