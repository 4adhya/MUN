"""Phase 1: MUN metrics on WorldState, Country compatibility, backward compatibility."""
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.countries import build_countries, build_trade_routes
from backend.main import app
from backend.models import Country, WorldState
from backend.mun import MUNWorldMetrics
from backend.simulation import simulation

client = TestClient(app)
METRICS = ["world_stability", "diplomatic_tension", "humanitarian_impact",
           "international_trust", "cybersecurity_level", "economic_risk"]


# --- MUN metrics -------------------------------------------------------------
def test_metrics_defaults_are_in_range():
    m = MUNWorldMetrics()
    for name in METRICS:
        assert 0 <= getattr(m, name) <= 100


@pytest.mark.parametrize("name", METRICS)
@pytest.mark.parametrize("bad", [-0.1, 100.1, 1000, float("nan"), float("inf")])
def test_out_of_range_metric_rejected(name, bad):
    with pytest.raises(ValidationError):
        MUNWorldMetrics(**{name: bad})


@pytest.mark.parametrize("name", METRICS)
def test_boundaries_accepted(name):
    assert getattr(MUNWorldMetrics(**{name: 0}), name) == 0
    assert getattr(MUNWorldMetrics(**{name: 100}), name) == 100


def test_assignment_is_validated():
    m = MUNWorldMetrics()
    m.economic_risk = 80
    with pytest.raises(ValidationError):
        m.economic_risk = 101
    assert m.economic_risk == 80


def test_unknown_metric_rejected():
    with pytest.raises(ValidationError):
        MUNWorldMetrics(world_stabilty=50)


# --- WorldState ----------------------------------------------------------------
def test_valid_world_state_with_metrics():
    w = WorldState(countries=build_countries(), trade_routes=build_trade_routes(),
                   mun_metrics={"world_stability": 40, "economic_risk": 90})
    assert w.mun_metrics.world_stability == 40 and w.mun_metrics.economic_risk == 90
    assert w.mun_metrics.international_trust == 60  # untouched default


def test_world_state_without_metrics_still_valid():
    w = WorldState(countries=build_countries(), trade_routes=build_trade_routes())
    assert isinstance(w.mun_metrics, MUNWorldMetrics)


def test_world_state_rejects_out_of_range_metric():
    with pytest.raises(ValidationError):
        WorldState(countries=[], trade_routes=[], mun_metrics={"world_stability": 150})


def test_existing_world_fields_still_work():
    w = simulation.world
    assert w.turn == 0 and w.events == []
    # Every registered country is seeded now, so there are many more than the 8 featured ones.
    assert len(w.countries) >= 8 and len(w.trade_routes) == 16
    c = next(c for c in w.countries if c.id == "india")
    assert c.gdp > 0 and 0 <= c.stability <= 100 and c.resources and c.trade_partners
    assert c.alliances == [] and c.sanctions == [] and c.relationships


def test_metrics_are_separate_state_per_world():
    a = WorldState(countries=[], trade_routes=[])
    b = WorldState(countries=[], trade_routes=[])
    a.mun_metrics.economic_risk = 99
    assert b.mun_metrics.economic_risk == 25


# --- Country compatibility ----------------------------------------------------------
def test_country_without_mun_fields_still_valid():
    c = Country(id="x", name="X", gdp=1, stability=50)
    assert c.country_code is None and c.flag is None


def test_country_code_validated():
    assert Country(id="x", name="X", gdp=1, stability=50, country_code="IN").country_code == "IN"
    with pytest.raises(ValidationError):
        Country(id="x", name="X", gdp=1, stability=50, country_code="india")


def test_real_countries_have_unique_codes_and_flags():
    countries = build_countries()
    codes = [c.country_code for c in countries]
    assert all(codes) and len(set(codes)) == len(codes)
    assert all(c.flag for c in countries)
    by_id = {c.id: c for c in countries}
    assert by_id["india"].country_code == "IN" and by_id["united-kingdom"].country_code == "GB"
    assert by_id["india"].flag == "\U0001F1EE\U0001F1F3"


# --- Backward compatibility ------------------------------------------------------------
def test_world_endpoint_shape_unchanged():
    r = client.get("/world")
    assert r.status_code == 200
    body = r.json()
    json.dumps(body)
    assert set(body) == {"turn", "countries", "trade_routes", "events"}  # metrics are not on the wire (yet)
    assert {"country_code", "flag"} <= set(body["countries"][0])  # additive Country fields


def test_country_endpoint_still_works():
    r = client.get("/countries/india")
    assert r.status_code == 200 and r.json()["country_code"] == "IN"


def test_actions_still_work_and_preserve_metrics():
    simulation.world.mun_metrics.diplomatic_tension = 55
    r = client.post("/actions/sanction", json={"actor": "india", "target": "china"})
    assert r.status_code == 200 and r.json()["event"]["type"] == "sanction"
    assert simulation.world.mun_metrics.diplomatic_tension == 55  # deep-copied world keeps MUN state
    assert client.post("/actions/alliance", json={"actor": "france", "target": "united-kingdom"}).status_code == 200
    assert client.post("/actions/aid", json={"actor": "japan", "target": "brazil", "amount": 5}).status_code == 200
    assert client.post("/actions/sanction", json={"actor": "india", "target": "nowhere"}).status_code == 404


def test_reset_restores_default_metrics():
    simulation.world.mun_metrics.world_stability = 10
    r = client.post("/simulation/reset")
    assert r.status_code == 200
    assert simulation.world.mun_metrics.world_stability == 75


def test_mun_layer_does_not_import_the_geopolitical_layer():
    """Dependency points one way: backend.models -> backend.mun, never the reverse."""
    import ast
    import pathlib

    import backend.mun as mun

    forbidden = {"simulation", "rules", "countries", "models", "main"}
    for path in pathlib.Path(mun.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                parts = (node.module or "").split(".")
                if node.level >= 2:  # `from ..x import y` reaches into backend/
                    assert parts[0] not in forbidden, f"{path.name} imports backend.{node.module}"
                if node.level == 0 and parts[0] == "backend" and len(parts) > 1 and parts[1] != "mun":
                    raise AssertionError(f"{path.name} imports {node.module}")