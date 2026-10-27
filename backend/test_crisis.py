"""Phase 7: the crisis engine - models, effect tables, deterministic rules, endpoints, authorization, phases, expiry,
events and world-state isolation. No AI and no network: every outcome here comes from the backend's fixed tables."""
import inspect
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import backend.crisis_routes as crisis_routes_module
import backend.crisis_rules as crisis_rules_module
import backend.crisis_schemas as crisis_schemas_module
import backend.crisis_service as crisis_service_module
import backend.mun.crisis as crisis_module
from backend.conference_service import conference_service
from backend.crisis_rules import apply_effects, project_effects
from backend.main import app
from backend.mun import ConferencePhase, ConferenceStatus, MUNWorldMetrics
from backend.mun.crisis import (
    ACTION_PROFILES,
    CRISIS_TEMPLATES,
    CRISIS_TTL_SECONDS,
    MAX_ACTIVE_CRISES,
    MAX_EFFECT_DELTA,
    METRIC_NAMES,
    SEVERITY_MULTIPLIER,
    Crisis,
    CrisisActionType,
    CrisisEndReason,
    CrisisOption,
    CrisisOutcome,
    CrisisSeverity,
    CrisisStateError,
    CrisisStatus,
    UnknownCrisisTemplateError,
    build_options,
    close_crisis,
    expiry_reason,
    get_template,
    outcome_for,
    scaled_effects,
)
from backend.simulation import create_initial_world, simulation

client = TestClient(app)
safe_client = TestClient(app, raise_server_exceptions=False)  # lets a deliberate 500 come back as a response

FLOW = [
    "LOBBY", "ROLL_CALL", "OPENING_SPEECHES", "MODERATED_CAUCUS", "UNMODERATED_CAUCUS",
    "CRISIS", "DRAFTING", "VOTING", "RESULTS",
]
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
DEFAULTS = {
    "world_stability": 75.0, "diplomatic_tension": 30.0, "humanitarian_impact": 20.0,
    "international_trust": 60.0, "cybersecurity_level": 50.0, "economic_risk": 25.0,
}
ALL_TYPES = [t.value for t in CrisisActionType]
FINAL_KEYS = ("id", "status", "outcome", "end_reason")


# --- helpers ----------------------------------------------------------------------------------
def make_conference(delegates=3, extra_roles=("JURY",), committee="UNSC"):
    cid = client.post("/conference/create", json={"name": "Crisis", "committee": committee, "topic": "Peace"}).json()["id"]
    for i in range(delegates):
        assert client.post(f"/conference/{cid}/join", json={"name": f"D{i}", "role": "PARTICIPANT"}).status_code == 201
    for i, role in enumerate(extra_roles):
        assert client.post(f"/conference/{cid}/join", json={"name": f"X{i}", "role": role}).status_code == 201
    return cid


def people(cid):
    return {p["name"]: p for p in client.get(f"/conference/{cid}").json()["participants"]}


def snapshot(cid):
    return client.get(f"/conference/{cid}").json()


def go_to(cid, phase):
    for _ in range(len(FLOW) + 1):
        if snapshot(cid)["current_phase"] == phase:
            return
        assert client.post(f"/conference/{cid}/advance").status_code == 200
    raise AssertionError(f"never reached {phase}")


def crisis_conference(delegates=3, extra_roles=("JURY",)):
    """A started conference in its CRISIS phase. Returns (conference id, participants by name); the JURY member is X0."""
    cid = make_conference(delegates, extra_roles)
    assert client.post(f"/conference/{cid}/start").status_code == 200
    go_to(cid, "CRISIS")
    return cid, people(cid)


def start_crisis(cid, jury, template="cyber_attack", **body):
    payload = {"conference_id": cid, "participant_id": jury["id"], **body}
    if template is not None:
        payload["template_id"] = template
    return client.post("/crisis", json=payload)


def custom(cid, jury, severity="MEDIUM", types=("DIPLOMACY", "SANCTIONS", "NO_ACTION"), **body):
    response = start_crisis(
        cid, jury, template=None, title="Custom crisis", description="Something happened.", severity=severity,
        option_types=list(types), **body,
    )
    assert response.status_code == 201, response.text
    return response.json()


def open_template(cid, jury, template="cyber_attack", **body):
    response = start_crisis(cid, jury, template=template, **body)
    assert response.status_code == 201, response.text
    return response.json()


def option(crisis, action_type):
    return next(o for o in crisis["options"] if o["action_type"] == action_type)


def respond(crisis, who, opt, **overrides):
    opt_id = opt["id"] if isinstance(opt, dict) else opt
    body = {"participant_id": who["id"], "country_code": who["country_code"], "option_id": opt_id, **overrides}
    return client.post(f"/crisis/{crisis['id']}/respond", json=body)


def ok_respond(crisis, who, action_type):
    response = respond(crisis, who, option(crisis, action_type))
    assert response.status_code == 201, response.text
    return response.json()


def resolve(crisis, who):
    return client.post(f"/crisis/{crisis['id']}/resolve", json={"participant_id": who["id"]})


def get_crisis(crisis_id):
    return client.get(f"/crisis/{crisis_id}")


def metrics_of(cid):
    return snapshot(cid)["world"]["mun_metrics"]


def events_of(cid, *types):
    events = snapshot(cid)["world"]["events"]
    return [e for e in events if not types or e["type"] in types]


def state(cid):
    """Everything a rejected request must leave untouched."""
    return snapshot(cid)["world"], client.get(f"/conference/{cid}/crises").json()


def record(cid):
    return conference_service._records[cid]


@pytest.fixture
def clock(monkeypatch):
    """A movable clock for the conference service (crises use it): `clock.now`, `clock.advance(seconds=...)`."""

    class Clock:
        def __init__(self):
            self.now = datetime.now(timezone.utc)

        def advance(self, seconds):
            self.now = self.now + timedelta(seconds=seconds)

    fake = Clock()
    monkeypatch.setattr(conference_service, "_clock", lambda: fake.now)
    return fake


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def make_crisis(**over):
    values = dict(
        conference_id="conf-1", title="A crisis", description="Something happened.", severity="HIGH",
        started_at=NOW, expires_at=NOW + timedelta(minutes=5), created_by="part-j",
    )
    values.update(over)
    return Crisis(**values)


# --- enums and models -------------------------------------------------------------------------
def test_enum_values_are_uppercase_names():
    assert {s.value for s in CrisisSeverity} == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert {s.value for s in CrisisStatus} == {"ACTIVE", "RESOLVED", "EXPIRED"}
    assert {o.value for o in CrisisOutcome} == {"UNADDRESSED", "PARTIALLY_ADDRESSED", "FULLY_ADDRESSED"}
    for enum in (CrisisSeverity, CrisisStatus, CrisisActionType, CrisisEndReason):
        assert all(member.value == member.name for member in enum)


def test_crisis_has_the_required_fields():
    assert {"id", "conference_id", "title", "description", "severity", "status", "started_at", "expires_at"} <= set(
        Crisis.model_fields
    )
    c = make_crisis()
    assert c.id.startswith("crisis-") and c.status is CrisisStatus.ACTIVE
    assert c.ended_at is None and c.end_reason is None and c.outcome is None


def test_crisis_option_has_the_required_fields():
    assert {"id", "crisis_id", "title", "description", "action_type", "effects"} <= set(CrisisOption.model_fields)
    o = CrisisOption(crisis_id="c", title="T", description="D", action_type="DIPLOMACY", effects={"world_stability": 2})
    assert o.id.startswith("opt-") and o.effects == {"world_stability": 2}


@pytest.mark.parametrize(
    "over",
    [
        {"started_at": datetime(2026, 1, 1, 12, 0)},  # naive datetime
        {"expires_at": NOW},  # not after the start
        {"expires_at": NOW - timedelta(seconds=1)},
        {"title": ""},
        {"title": "x" * 121},
        {"description": " "},
        {"severity": "EXTREME"},
        {"severity": "high"},  # exact match only
        {"status": "OPEN"},
        {"colour": "red"},  # unknown field
        {"conference_id": ""},
        {"created_by": ""},
    ],
)
def test_invalid_crisis_is_rejected(over):
    with pytest.raises(ValidationError):
        make_crisis(**over)


@pytest.mark.parametrize(
    "over",
    [
        {"ended_at": NOW + timedelta(seconds=1)},  # ACTIVE cannot have ended
        {"end_reason": "TIME_EXPIRED"},
        {"outcome": "UNADDRESSED"},
        {"status": "RESOLVED"},  # needs ended_at, reason and outcome
        {"status": "RESOLVED", "ended_at": NOW, "end_reason": "TIME_EXPIRED", "outcome": "UNADDRESSED"},
        {"status": "RESOLVED", "ended_at": NOW, "end_reason": "RESOLVED"},  # no outcome
        {"status": "EXPIRED", "ended_at": NOW, "end_reason": "RESOLVED"},
        {"status": "EXPIRED", "ended_at": NOW, "end_reason": "TIME_EXPIRED", "outcome": "UNADDRESSED"},
        {"status": "EXPIRED", "end_reason": "TIME_EXPIRED"},  # no ended_at
        {"status": "EXPIRED", "ended_at": NOW - timedelta(seconds=1), "end_reason": "TIME_EXPIRED"},
    ],
)
def test_inconsistent_crisis_state_is_rejected(over):
    with pytest.raises(ValidationError):
        make_crisis(**over)


@pytest.mark.parametrize(
    "effects",
    [
        {"gdp": 3},  # not a MUN metric
        {"world_stability": 1.5},
        {"world_stability": 2.0},  # a float is not an integer delta
        {"world_stability": True},
        {"world_stability": "3"},
        {"world_stability": MAX_EFFECT_DELTA + 1},
        {"world_stability": -(MAX_EFFECT_DELTA + 1)},
    ],
)
def test_option_effects_must_be_known_metrics_with_bounded_integer_deltas(effects):
    with pytest.raises(ValidationError):
        CrisisOption(crisis_id="c", title="T", description="D", action_type="DIPLOMACY", effects=effects)


def test_options_are_immutable_and_reject_unknown_fields():
    o = CrisisOption(crisis_id="c", title="T", description="D", action_type="DIPLOMACY")
    with pytest.raises(ValidationError):
        o.title = "other"
    with pytest.raises(ValidationError):
        CrisisOption(crisis_id="c", title="T", description="D", action_type="DIPLOMACY", cost=3)
    with pytest.raises(ValidationError):
        CrisisOption(crisis_id="c", title="T", description="D", action_type="BOMB")


# --- effect tables ----------------------------------------------------------------------------
def test_every_action_type_has_a_profile_and_all_profiles_differ():
    assert set(ACTION_PROFILES) == set(CrisisActionType)
    profiles = [tuple(sorted(p.items())) for p in ACTION_PROFILES.values()]
    assert len(set(profiles)) == len(profiles)


def test_the_six_world_metrics_are_all_supported_and_nothing_else():
    assert set(METRIC_NAMES) == set(DEFAULTS)
    used = {metric for profile in ACTION_PROFILES.values() for metric in profile}
    assert used == set(METRIC_NAMES)  # every metric can be moved by some response, and no profile invents one


@pytest.mark.parametrize("severity", list(CrisisSeverity))
@pytest.mark.parametrize("action", list(CrisisActionType))
def test_effects_are_the_profile_times_the_severity_multiplier(action, severity):
    expected = {m: d * SEVERITY_MULTIPLIER[severity] for m, d in ACTION_PROFILES[action].items()}
    assert scaled_effects(action, severity) == expected
    assert max(abs(v) for v in expected.values()) <= MAX_EFFECT_DELTA


def test_severity_multipliers_grow_with_severity():
    values = [SEVERITY_MULTIPLIER[s] for s in (CrisisSeverity.LOW, CrisisSeverity.MEDIUM, CrisisSeverity.HIGH, CrisisSeverity.CRITICAL)]
    assert values == sorted(values) and len(set(values)) == 4


def test_build_options_is_deterministic_apart_from_ids():
    a = build_options("c1", "HIGH", ["DIPLOMACY", "SANCTIONS"])
    b = build_options("c1", "HIGH", ["DIPLOMACY", "SANCTIONS"])
    assert [(o.action_type, o.effects, o.title) for o in a] == [(o.action_type, o.effects, o.title) for o in b]
    assert all(o.crisis_id == "c1" for o in a) and len({o.id for o in a + b}) == 4


@pytest.mark.parametrize(
    "types",
    [[], ["DIPLOMACY"], ["DIPLOMACY", "DIPLOMACY"], ALL_TYPES + ["DIPLOMACY"], ["DIPLOMACY", "NUKE"]],
)
def test_build_options_rejects_bad_option_sets(types):
    with pytest.raises(ValueError):
        build_options("c1", "HIGH", types)


def test_templates_are_valid_and_build_options():
    assert len(CRISIS_TEMPLATES) >= 4
    for template_id, template in CRISIS_TEMPLATES.items():
        assert template.id == template_id
        options = build_options("c", template.severity, template.option_types)
        assert [o.action_type for o in options] == list(template.option_types)
    with pytest.raises(UnknownCrisisTemplateError):
        get_template("alien_invasion")


# --- pure state rules -------------------------------------------------------------------------
def test_close_crisis_resolves_or_expires_without_mutating_the_original():
    c = make_crisis()
    done = close_crisis(c, CrisisEndReason.RESOLVED, NOW + timedelta(seconds=30), CrisisOutcome.UNADDRESSED)
    assert done.status is CrisisStatus.RESOLVED and done.outcome is CrisisOutcome.UNADDRESSED
    assert done.end_reason is CrisisEndReason.RESOLVED and done.ended_at == NOW + timedelta(seconds=30)
    gone = close_crisis(c, CrisisEndReason.TIME_EXPIRED, NOW + timedelta(minutes=5))
    assert gone.status is CrisisStatus.EXPIRED and gone.outcome is None
    assert c.status is CrisisStatus.ACTIVE  # the original is untouched


def test_a_final_crisis_can_never_change_again():
    done = close_crisis(make_crisis(), CrisisEndReason.PHASE_CLOSED, NOW)
    for reason in CrisisEndReason:
        with pytest.raises(CrisisStateError):
            close_crisis(done, reason, NOW, CrisisOutcome.UNADDRESSED)


def test_expiry_reason_rules():
    c = make_crisis()
    P, S = ConferencePhase, ConferenceStatus
    assert expiry_reason(c, NOW, P.CRISIS, S.ACTIVE) is None
    assert expiry_reason(c, c.expires_at - timedelta(seconds=1), P.CRISIS, S.ACTIVE) is None
    assert expiry_reason(c, c.expires_at, P.CRISIS, S.ACTIVE) is CrisisEndReason.TIME_EXPIRED
    for phase in P:
        if phase is not P.CRISIS:
            assert expiry_reason(c, NOW, phase, S.ACTIVE) is CrisisEndReason.PHASE_CLOSED
    for status in (S.COMPLETED, S.CANCELLED):
        assert expiry_reason(c, NOW, P.CRISIS, status) is CrisisEndReason.PHASE_CLOSED
    # the phase wins over the clock
    assert expiry_reason(c, c.expires_at, P.DRAFTING, S.ACTIVE) is CrisisEndReason.PHASE_CLOSED
    # a final crisis is never expired again
    assert expiry_reason(close_crisis(c, CrisisEndReason.TIME_EXPIRED, NOW), NOW, P.DRAFTING, S.ACTIVE) is None


@pytest.mark.parametrize(
    "responses, delegates, expected",
    [(0, 3, "UNADDRESSED"), (1, 3, "PARTIALLY_ADDRESSED"), (2, 3, "PARTIALLY_ADDRESSED"), (3, 3, "FULLY_ADDRESSED"), (0, 0, "UNADDRESSED")],
)
def test_outcome_is_decided_by_head_count_alone(responses, delegates, expected):
    assert outcome_for(responses, delegates).value == expected


# --- deterministic metric rules ---------------------------------------------------------------
def test_project_effects_is_pure():
    metrics = MUNWorldMetrics()
    change = project_effects(metrics, {"world_stability": 5, "diplomatic_tension": -4})
    assert metrics.model_dump() == DEFAULTS  # untouched
    assert change.before == DEFAULTS
    assert change.after["world_stability"] == 80.0 and change.after["diplomatic_tension"] == 26.0
    assert change.applied == {"world_stability": 5.0, "diplomatic_tension": -4.0} and change.changed


def test_effects_are_clamped_to_the_metric_range_and_applied_reports_what_really_moved():
    world = create_initial_world()
    world.mun_metrics.humanitarian_impact = 3
    world.mun_metrics.world_stability = 98
    change = apply_effects(world, {"humanitarian_impact": -10, "world_stability": 5, "economic_risk": 0})
    assert world.mun_metrics.humanitarian_impact == 0 and world.mun_metrics.world_stability == 100
    assert change.applied == {"humanitarian_impact": -3.0, "world_stability": 2.0}  # economic_risk did not move
    assert all(0 <= v <= 100 for v in world.mun_metrics.model_dump().values())


def test_a_change_that_moves_nothing_is_not_a_change():
    world = create_initial_world()
    change = apply_effects(world, {})
    assert not change.changed and change.applied == {} and world.mun_metrics.model_dump() == DEFAULTS


def test_apply_effects_is_deterministic():
    w1, w2 = create_initial_world(), create_initial_world()
    effects = scaled_effects("SANCTIONS", "HIGH")
    c1, c2 = apply_effects(w1, effects), apply_effects(w2, effects)
    assert c1 == c2 and w1.mun_metrics == w2.mun_metrics


def test_an_unknown_metric_is_rejected_and_nothing_changes():
    world = create_initial_world()
    with pytest.raises(ValueError):
        apply_effects(world, {"world_stability": 5, "gdp": 9})
    assert world.mun_metrics.model_dump() == DEFAULTS


def test_effects_touch_only_the_mun_metrics_of_the_world_they_are_given():
    world = create_initial_world()
    before = world.model_dump()
    apply_effects(world, scaled_effects("MILITARY_DEPLOYMENT", "CRITICAL"))
    after = world.model_dump()
    assert world.mun_metrics.diplomatic_tension == 46.0
    assert {k: v for k, v in before.items() if k != "mun_metrics"} == {k: v for k, v in after.items() if k != "mun_metrics"}


# --- no AI, no randomness, no wall clock in the crisis modules --------------------------------
@pytest.mark.parametrize(
    "module", [crisis_module, crisis_rules_module, crisis_schemas_module, crisis_service_module, crisis_routes_module]
)
def test_crisis_modules_never_touch_an_ai_randomness_or_the_wall_clock(module):
    source = inspect.getsource(module).lower()
    for forbidden in ("gemini", "import ai", "from ai", "anthropic", "random", "datetime.now", "time.time"):
        assert forbidden not in source


def test_only_three_crisis_routes_change_anything_and_none_accepts_effects():
    spec = app.openapi()
    mutating = {
        path for path, methods in spec["paths"].items()
        if path.startswith("/crisis") and set(methods) & {"post", "put", "patch", "delete"}
    }
    assert mutating == {"/crisis", "/crisis/{crisis_id}/respond", "/crisis/{crisis_id}/resolve"}
    schemas = spec["components"]["schemas"]
    for name in ("CrisisCreateRequest", "CrisisRespondRequest", "CrisisResolveRequest"):
        assert not {"effects", "status", "id", "expires_at", "outcome", "metrics"} & set(schemas[name]["properties"])


# --- templates endpoint -----------------------------------------------------------------------
def test_templates_endpoint_lists_the_catalogue():
    response = client.get("/crisis-templates")
    assert response.status_code == 200
    templates = response.json()
    assert {t["id"] for t in templates} == set(CRISIS_TEMPLATES)
    assert all(t["severity"] in {s.value for s in CrisisSeverity} and len(t["option_types"]) >= 2 for t in templates)


# --- starting a crisis ------------------------------------------------------------------------
def test_jury_starts_a_crisis_from_a_template():
    cid, p = crisis_conference()
    response = start_crisis(cid, p["X0"])
    assert response.status_code == 201
    crisis = response.json()
    template = CRISIS_TEMPLATES["cyber_attack"]
    assert crisis["id"].startswith("crisis-") and crisis["conference_id"] == cid
    assert crisis["title"] == template.title and crisis["description"] == template.description
    assert crisis["severity"] == "HIGH" and crisis["status"] == "ACTIVE" and crisis["created_by"] == p["X0"]["id"]
    assert crisis["ended_at"] is None and crisis["end_reason"] is None and crisis["outcome"] is None
    assert crisis["responses"] == []
    assert [o["action_type"] for o in crisis["options"]] == [t.value for t in template.option_types]
    for o in crisis["options"]:
        assert o["crisis_id"] == crisis["id"] and o["title"] and o["description"]
        assert o["effects"] == scaled_effects(o["action_type"], "HIGH")  # worked out by the backend


def test_a_custom_crisis_needs_no_template():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"], severity="LOW", types=("CYBER_DEFENSE", "NO_ACTION"))
    assert crisis["title"] == "Custom crisis" and crisis["severity"] == "LOW"
    assert [o["action_type"] for o in crisis["options"]] == ["CYBER_DEFENSE", "NO_ACTION"]


def test_a_custom_crisis_without_option_types_gets_the_default_options():
    cid, p = crisis_conference()
    response = start_crisis(cid, p["X0"], template=None, title="T", description="D", severity="MEDIUM")
    assert response.status_code == 201
    assert [o["action_type"] for o in response.json()["options"]] == ["DIPLOMACY", "HUMANITARIAN_AID", "SANCTIONS", "NO_ACTION"]


def test_explicit_fields_override_the_template():
    cid, p = crisis_conference()
    crisis = open_template(cid, p["X0"], title="Our own title", severity="CRITICAL", option_types=["DIPLOMACY", "NO_ACTION"])
    assert crisis["title"] == "Our own title" and crisis["severity"] == "CRITICAL"
    assert crisis["description"] == CRISIS_TEMPLATES["cyber_attack"].description
    assert option(crisis, "DIPLOMACY")["effects"] == {k: v * 4 for k, v in ACTION_PROFILES[CrisisActionType.DIPLOMACY].items()}


@pytest.mark.parametrize("template_id", sorted(CRISIS_TEMPLATES))
def test_every_template_can_be_started(template_id):
    cid, p = crisis_conference()
    crisis = open_template(cid, p["X0"], template=template_id)
    assert len(crisis["options"]) == len(CRISIS_TEMPLATES[template_id].option_types)


def test_a_crisis_lasts_the_default_time_and_never_outlives_the_crisis_phase(clock):
    cid, p = crisis_conference()
    snap = snapshot(cid)
    clock.now = parse(snap["phase_started_at"])
    crisis = open_template(cid, p["X0"])
    assert parse(crisis["started_at"]) == clock.now
    assert parse(crisis["expires_at"]) == clock.now + timedelta(seconds=CRISIS_TTL_SECONDS)
    clock.advance(9 * 60)  # the phase has one minute left
    later = open_template(cid, p["X0"])
    assert parse(later["expires_at"]) == parse(snap["phase_ends_at"])  # capped at the phase's own deadline
    assert parse(later["expires_at"]) > parse(later["started_at"])


def test_a_crisis_cannot_start_once_the_crisis_phase_time_is_up(clock):
    cid, p = crisis_conference()
    clock.now = parse(snapshot(cid)["phase_started_at"]) + timedelta(minutes=11)
    before = state(cid)
    response = start_crisis(cid, p["X0"])
    assert response.status_code == 409 and "time" in response.json()["detail"].lower()
    assert state(cid) == before


def test_starting_a_crisis_emits_a_crisis_created_event():
    cid, p = crisis_conference()
    crisis = open_template(cid, p["X0"])
    (event,) = events_of(cid, "crisis_created")
    assert event["actor"] == cid and event["target"] is None
    fx = event["effects"]
    assert fx["conference_id"] == cid and fx["crisis_id"] == crisis["id"] and fx["severity"] == "HIGH"
    assert fx["status"] == "ACTIVE" and fx["phase"] == "CRISIS" and fx["created_by"] == p["X0"]["id"]
    assert [o["id"] for o in fx["options"]] == [o["id"] for o in crisis["options"]]
    assert metrics_of(cid) == DEFAULTS  # starting a crisis moves no metric


def test_at_most_three_crises_can_be_open_at_once():
    cid, p = crisis_conference()
    opened = [open_template(cid, p["X0"], template="market_crash") for _ in range(MAX_ACTIVE_CRISES)]
    response = start_crisis(cid, p["X0"], template="market_crash")
    assert response.status_code == 409 and "open crises" in response.json()["detail"]
    assert resolve(opened[0], p["X0"]).status_code == 200  # room again
    assert start_crisis(cid, p["X0"], template="market_crash").status_code == 201


# --- starting a crisis: invalid and unauthorized ----------------------------------------------
def test_start_rejects_non_jury_roles_and_strangers():
    cid, p = crisis_conference(extra_roles=("JURY", "GUEST"))
    other, op = crisis_conference()
    before = state(cid)
    assert start_crisis(cid, p["D0"]).status_code == 403  # a delegate
    assert start_crisis(cid, p["X1"]).status_code == 403  # a guest
    assert start_crisis(cid, {"id": "part-nobody"}).status_code == 403  # not a participant at all
    assert start_crisis(cid, op["X0"]).status_code == 403  # a JURY member of ANOTHER conference
    assert state(cid) == before
    assert events_of(cid, "crisis_created") == []


def test_start_in_an_unknown_conference_is_404():
    cid, p = crisis_conference()
    response = client.post("/crisis", json={"conference_id": "conf-nope", "participant_id": p["X0"]["id"], "template_id": "cyber_attack"})
    assert response.status_code == 404


@pytest.mark.parametrize("phase", [p for p in FLOW if p not in ("CRISIS",)][1:])
def test_start_is_refused_outside_the_crisis_phase(phase):
    cid = make_conference()
    assert client.post(f"/conference/{cid}/start").status_code == 200
    jury = people(cid)["X0"]
    go_to(cid, phase)
    before = state(cid)
    response = start_crisis(cid, jury)
    assert response.status_code == 409 and "CRISIS_RESPONSE" in response.json()["detail"]
    assert state(cid) == before


def test_start_before_the_conference_has_started_is_409():
    cid = make_conference()
    jury = people(cid)["X0"]
    assert start_crisis(cid, jury).status_code == 409


def test_start_after_the_conference_completed_is_409():
    cid, p = crisis_conference()
    for _ in range(4):  # DRAFTING, VOTING, RESULTS, COMPLETED
        assert client.post(f"/conference/{cid}/advance").status_code == 200
    assert snapshot(cid)["status"] == "COMPLETED"
    assert start_crisis(cid, p["X0"]).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"template_id": "alien_invasion"},  # unknown template -> 422 from the service
        {"template_id": "Cyber Attack"},  # bad shape
        {},  # neither a template nor a custom crisis
        {"title": "T", "description": "D"},  # custom without severity
        {"title": "T", "severity": "HIGH"},  # custom without description
        {"template_id": "cyber_attack", "severity": "EXTREME"},
        {"template_id": "cyber_attack", "severity": "high"},
        {"template_id": "cyber_attack", "title": ""},
        {"template_id": "cyber_attack", "title": "x" * 121},
        {"template_id": "cyber_attack", "option_types": ["DIPLOMACY"]},  # too few
        {"template_id": "cyber_attack", "option_types": ["DIPLOMACY", "DIPLOMACY"]},  # repeated
        {"template_id": "cyber_attack", "option_types": ["DIPLOMACY", "NUKE"]},
        {"template_id": "cyber_attack", "option_types": ALL_TYPES + ["DIPLOMACY"]},  # too many
        # a client can never set what only the backend decides
        {"template_id": "cyber_attack", "effects": {"world_stability": 50}},
        {"template_id": "cyber_attack", "status": "RESOLVED"},
        {"template_id": "cyber_attack", "id": "crisis-mine"},
        {"template_id": "cyber_attack", "expires_at": "2030-01-01T00:00:00Z"},
        {"template_id": "cyber_attack", "options": [{"title": "x", "effects": {"world_stability": 50}}]},
    ],
)
def test_start_rejects_invalid_requests_and_changes_nothing(body):
    cid, p = crisis_conference()
    before = state(cid)
    response = client.post("/crisis", json={"conference_id": cid, "participant_id": p["X0"]["id"], **body})
    assert response.status_code == 422
    assert state(cid) == before


# --- viewing ----------------------------------------------------------------------------------
def test_a_crisis_can_be_viewed_by_id():
    cid, p = crisis_conference()
    crisis = open_template(cid, p["X0"])
    response = get_crisis(crisis["id"])
    assert response.status_code == 200 and response.json() == crisis


def test_viewing_an_unknown_crisis_is_404():
    assert get_crisis("crisis-nope").status_code == 404
    assert client.get("/crisis/crisis-nope/options/opt-x/preview").status_code == 404
    assert client.post("/crisis/crisis-nope/resolve", json={"participant_id": "p"}).status_code == 404
    assert client.post("/crisis/crisis-nope/respond", json={"participant_id": "p", "country_code": "IN", "option_id": "o"}).status_code == 404


def test_crises_of_a_conference_are_listed_oldest_first_and_filterable():
    cid, p = crisis_conference()
    a = open_template(cid, p["X0"], template="cyber_attack")
    b = open_template(cid, p["X0"], template="market_crash")
    assert resolve(a, p["X0"]).status_code == 200
    listed = client.get(f"/conference/{cid}/crises").json()
    assert [c["id"] for c in listed] == [a["id"], b["id"]]
    assert [c["id"] for c in client.get(f"/conference/{cid}/crises", params={"status": "ACTIVE"}).json()] == [b["id"]]
    assert [c["id"] for c in client.get(f"/conference/{cid}/crises", params={"status": "RESOLVED"}).json()] == [a["id"]]
    assert client.get(f"/conference/{cid}/crises", params={"status": "EXPIRED"}).json() == []
    assert client.get(f"/conference/{cid}/crises", params={"status": "open"}).status_code == 422
    assert client.get("/conference/conf-nope/crises").status_code == 404


def test_crises_belong_to_their_own_conference():
    a, pa = crisis_conference()
    b, pb = crisis_conference()
    crisis = open_template(a, pa["X0"])
    assert client.get(f"/conference/{b}/crises").json() == []
    assert [c["id"] for c in client.get(f"/conference/{a}/crises").json()] == [crisis["id"]]


# --- responding -------------------------------------------------------------------------------
def test_a_delegate_responds_and_the_option_effects_change_the_conference_metrics():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"], severity="MEDIUM")
    response = respond(crisis, p["D0"], option(crisis, "DIPLOMACY"))
    assert response.status_code == 201
    body = response.json()
    r = body["response"]
    assert r["id"].startswith("cresp-") and r["crisis_id"] == crisis["id"] and r["conference_id"] == cid
    assert r["participant_id"] == p["D0"]["id"] and r["country_code"] == p["D0"]["country_code"]
    assert r["option_id"] == option(crisis, "DIPLOMACY")["id"] and r["action_type"] == "DIPLOMACY"
    assert r["applied"] == {"world_stability": 4.0, "diplomatic_tension": -6.0, "international_trust": 4.0}
    expected = {**DEFAULTS, "world_stability": 79.0, "diplomatic_tension": 24.0, "international_trust": 64.0}
    assert body["mun_metrics"] == expected
    assert metrics_of(cid) == expected  # the conference's own world holds the change
    assert body["crisis"]["status"] == "ACTIVE" and [x["id"] for x in body["crisis"]["responses"]] == [r["id"]]
    assert get_crisis(crisis["id"]).json()["responses"][0]["applied"] == r["applied"]


def test_the_country_code_is_normalised():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    response = respond(crisis, p["D0"], option(crisis, "DIPLOMACY"), country_code=p["D0"]["country_code"].lower())
    assert response.status_code == 201


def test_different_options_produce_different_deterministic_outcomes():
    outcomes = {}
    for action in ALL_TYPES:
        cid, p = crisis_conference(delegates=1)
        crisis = custom(cid, p["X0"], types=ALL_TYPES)
        ok_respond(crisis, p["D0"], action)
        outcomes[action] = metrics_of(cid)
    assert all(m != DEFAULTS for m in outcomes.values())
    assert len({tuple(sorted(m.items())) for m in outcomes.values()}) == len(ALL_TYPES)  # all different
    # ... and each is repeatable: the same choice in a fresh conference gives the very same world
    for action in ("DIPLOMACY", "SANCTIONS", "NO_ACTION"):
        cid, p = crisis_conference(delegates=1)
        crisis = custom(cid, p["X0"], types=ALL_TYPES)
        ok_respond(crisis, p["D0"], action)
        assert metrics_of(cid) == outcomes[action]


@pytest.mark.parametrize(
    "metric, action, direction",
    [
        ("world_stability", "DIPLOMACY", 1),
        ("diplomatic_tension", "MILITARY_DEPLOYMENT", 1),
        ("diplomatic_tension", "DIPLOMACY", -1),
        ("humanitarian_impact", "HUMANITARIAN_AID", -1),
        ("humanitarian_impact", "NO_ACTION", 1),
        ("international_trust", "DIPLOMACY", 1),
        ("cybersecurity_level", "CYBER_DEFENSE", 1),
        ("economic_risk", "ECONOMIC_STABILIZATION", -1),
        ("economic_risk", "SANCTIONS", 1),
    ],
)
def test_each_of_the_six_metrics_can_change(metric, action, direction):
    cid, p = crisis_conference(delegates=1)
    crisis = custom(cid, p["X0"], types=ALL_TYPES)
    ok_respond(crisis, p["D0"], action)
    delta = metrics_of(cid)[metric] - DEFAULTS[metric]
    assert delta * direction > 0
    untouched = set(DEFAULTS) - set(option(crisis, action)["effects"])
    assert all(metrics_of(cid)[m] == DEFAULTS[m] for m in untouched)  # only what the option lists moves


def test_severity_scales_the_consequences():
    deltas = {}
    for severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
        cid, p = crisis_conference(delegates=1)
        crisis = custom(cid, p["X0"], severity=severity)
        ok_respond(crisis, p["D0"], "DIPLOMACY")
        deltas[severity] = metrics_of(cid)["diplomatic_tension"] - DEFAULTS["diplomatic_tension"]
    assert deltas == {"LOW": -3.0, "MEDIUM": -6.0, "HIGH": -9.0, "CRITICAL": -12.0}


def test_responses_from_different_countries_accumulate():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"], severity="MEDIUM")
    ok_respond(crisis, p["D0"], "DIPLOMACY")
    ok_respond(crisis, p["D1"], "SANCTIONS")
    assert metrics_of(cid) == {
        **DEFAULTS, "world_stability": 77.0, "diplomatic_tension": 30.0, "international_trust": 60.0, "economic_risk": 29.0,
    }
    assert len(get_crisis(crisis["id"]).json()["responses"]) == 2


def test_consequences_are_clamped_at_the_ends_of_the_scale():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"], severity="CRITICAL", types=("HUMANITARIAN_AID", "NO_ACTION"))
    first = ok_respond(crisis, p["D0"], "HUMANITARIAN_AID")
    second = ok_respond(crisis, p["D1"], "HUMANITARIAN_AID")
    assert first["response"]["applied"]["humanitarian_impact"] == -16.0
    assert second["response"]["applied"]["humanitarian_impact"] == -4.0  # only 4 points were left above zero
    assert metrics_of(cid)["humanitarian_impact"] == 0.0
    assert all(0 <= v <= 100 for v in metrics_of(cid).values())


def test_a_response_that_moves_no_metric_emits_no_world_state_event():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"], types=("DIPLOMACY", "NO_ACTION"))
    m = record(cid).world.mun_metrics  # put the three metrics DIPLOMACY pushes already at their limits
    m.world_stability, m.diplomatic_tension, m.international_trust = 100, 0, 100
    body = ok_respond(crisis, p["D0"], "DIPLOMACY")
    assert body["response"]["applied"] == {}
    assert len(events_of(cid, "crisis_response")) == 1 and events_of(cid, "world_state_changed") == []


# --- responding: invalid and unauthorized -----------------------------------------------------
def test_respond_rejects_strangers_and_non_delegates_and_changes_nothing():
    cid, p = crisis_conference(extra_roles=("JURY", "GUEST"))
    other, op = crisis_conference()
    crisis = custom(cid, p["X0"])
    opt = option(crisis, "DIPLOMACY")
    before = state(cid)
    assert respond(crisis, p["X0"], opt, country_code="IN").status_code == 403  # JURY
    assert respond(crisis, p["X1"], opt, country_code="IN").status_code == 403  # GUEST
    assert respond(crisis, {"id": "part-nobody", "country_code": "IN"}, opt).status_code == 403
    assert respond(crisis, op["D0"], opt).status_code == 403  # a delegate of ANOTHER conference
    assert state(cid) == before


def test_respond_requires_your_own_country():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    before = state(cid)
    response = respond(crisis, p["D0"], option(crisis, "DIPLOMACY"), country_code=p["D1"]["country_code"])
    assert response.status_code == 403 and "mismatch" in response.json()["detail"].lower()
    assert state(cid) == before


def test_respond_rejects_an_option_that_is_not_this_crisis():
    cid, p = crisis_conference()
    one = custom(cid, p["X0"])
    two = custom(cid, p["X0"])
    before = state(cid)
    assert respond(one, p["D0"], "opt-does-not-exist").status_code == 422
    foreign = option(two, "DIPLOMACY")  # a real option, but of another crisis
    assert respond(one, p["D0"], foreign).status_code == 422
    assert state(cid) == before


def test_a_country_cannot_respond_twice():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    ok_respond(crisis, p["D0"], "DIPLOMACY")
    before = state(cid)
    again = respond(crisis, p["D0"], option(crisis, "SANCTIONS"))
    assert again.status_code == 409 and "already responded" in again.json()["detail"]
    assert state(cid) == before
    # ... but the same delegate may answer a different crisis
    other = custom(cid, p["X0"])
    assert respond(other, p["D0"], option(other, "SANCTIONS")).status_code == 201


@pytest.mark.parametrize(
    "extra",
    [
        {"effects": {"world_stability": 99}},
        {"status": "RESOLVED"},
        {"applied": {"world_stability": 99}},
        {"world_stability": 99},
        {"crisis_id": "crisis-other"},
    ],
)
def test_a_client_cannot_send_its_own_consequences(extra):
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    before = state(cid)
    assert respond(crisis, p["D0"], option(crisis, "DIPLOMACY"), **extra).status_code == 422
    assert state(cid) == before


@pytest.mark.parametrize("over", [{"country_code": "USA"}, {"country_code": "1"}, {"country_code": ""}, {"option_id": ""}, {"participant_id": ""}])
def test_respond_rejects_malformed_requests(over):
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    before = state(cid)
    assert respond(crisis, p["D0"], option(crisis, "DIPLOMACY"), **over).status_code == 422
    assert state(cid) == before


def test_respond_is_refused_once_the_conference_left_the_crisis_phase():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    assert client.post(f"/conference/{cid}/advance").status_code == 200  # CRISIS -> DRAFTING
    before_metrics = metrics_of(cid)
    response = respond(crisis, p["D0"], option(crisis, "DIPLOMACY"))
    assert response.status_code == 409 and "EXPIRED" in response.json()["detail"]
    assert metrics_of(cid) == before_metrics == DEFAULTS


def test_respond_is_refused_once_the_crisis_is_resolved():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    assert resolve(crisis, p["X0"]).status_code == 200
    before = state(cid)
    response = respond(crisis, p["D0"], option(crisis, "DIPLOMACY"))
    assert response.status_code == 409 and "RESOLVED" in response.json()["detail"]
    assert state(cid) == before


def test_respond_is_refused_after_the_crisis_timed_out(clock):
    cid, p = crisis_conference()
    clock.now = parse(snapshot(cid)["phase_started_at"])
    crisis = custom(cid, p["X0"])
    clock.advance(CRISIS_TTL_SECONDS - 1)
    assert respond(crisis, p["D0"], option(crisis, "DIPLOMACY")).status_code == 201  # still open, just
    clock.advance(2)
    response = respond(crisis, p["D1"], option(crisis, "SANCTIONS"))
    assert response.status_code == 409 and "EXPIRED" in response.json()["detail"]
    assert metrics_of(cid)["economic_risk"] == DEFAULTS["economic_risk"]  # the late SANCTIONS did nothing


def test_a_rule_failure_never_corrupts_the_world(monkeypatch):
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    before = state(cid)
    monkeypatch.setattr(crisis_service_module, "validate_world", lambda world: ["boom"])
    response = safe_client.post(
        f"/crisis/{crisis['id']}/respond",
        json={"participant_id": p["D0"]["id"], "country_code": p["D0"]["country_code"], "option_id": option(crisis, "DIPLOMACY")["id"]},
    )
    assert response.status_code == 500
    monkeypatch.undo()
    assert state(cid) == before and metrics_of(cid) == DEFAULTS


# --- resolving --------------------------------------------------------------------------------
@pytest.mark.parametrize("responders, outcome", [(0, "UNADDRESSED"), (1, "PARTIALLY_ADDRESSED"), (3, "FULLY_ADDRESSED")])
def test_jury_resolves_a_crisis_with_an_outcome_from_the_head_count(responders, outcome):
    cid, p = crisis_conference(delegates=3)
    crisis = custom(cid, p["X0"])
    for name in ("D0", "D1", "D2")[:responders]:
        ok_respond(crisis, p[name], "DIPLOMACY")
    metrics_before = metrics_of(cid)
    response = resolve(crisis, p["X0"])
    assert response.status_code == 200
    done = response.json()
    assert done["status"] == "RESOLVED" and done["outcome"] == outcome and done["end_reason"] == "RESOLVED"
    assert done["ended_at"] is not None and len(done["responses"]) == responders
    assert metrics_of(cid) == metrics_before  # resolving moves no metric: consequences came with the responses
    assert get_crisis(crisis["id"]).json() == done


def test_resolving_emits_a_crisis_resolved_event_with_the_net_effects():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"], severity="MEDIUM")
    ok_respond(crisis, p["D0"], "DIPLOMACY")
    ok_respond(crisis, p["D1"], "SANCTIONS")
    resolve(crisis, p["X0"])
    (event,) = events_of(cid, "crisis_resolved")
    fx = event["effects"]
    assert event["actor"] == cid
    assert fx["crisis_id"] == crisis["id"] and fx["status"] == "RESOLVED" and fx["outcome"] == "PARTIALLY_ADDRESSED"
    assert fx["responses"] == 2 and fx["delegates"] == 3 and fx["participant_id"] == p["X0"]["id"]
    assert fx["actions_chosen"] == {"DIPLOMACY": 1, "SANCTIONS": 1}
    assert fx["net_effects"] == {
        "world_stability": 2.0, "diplomatic_tension": 0.0, "international_trust": 0.0, "economic_risk": 4.0,
    }


def test_resolve_rejects_non_jury_and_strangers():
    cid, p = crisis_conference(extra_roles=("JURY", "GUEST"))
    other, op = crisis_conference()
    crisis = custom(cid, p["X0"])
    before = state(cid)
    for who in (p["D0"], p["X1"], {"id": "part-nobody"}, op["X0"]):
        assert resolve(crisis, who).status_code == 403
    assert state(cid) == before
    assert get_crisis(crisis["id"]).json()["status"] == "ACTIVE"


def test_a_crisis_can_only_be_resolved_once():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    assert resolve(crisis, p["X0"]).status_code == 200
    before = state(cid)
    again = resolve(crisis, p["X0"])
    assert again.status_code == 409 and "RESOLVED" in again.json()["detail"]
    assert state(cid) == before
    assert len(events_of(cid, "crisis_resolved")) == 1


def test_resolve_rejects_unknown_fields():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    response = client.post(f"/crisis/{crisis['id']}/resolve", json={"participant_id": p["X0"]["id"], "outcome": "FULLY_ADDRESSED"})
    assert response.status_code == 422
    assert get_crisis(crisis["id"]).json()["status"] == "ACTIVE"


def test_resolve_is_refused_once_the_crisis_phase_is_over():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    assert client.post(f"/conference/{cid}/advance").status_code == 200
    response = resolve(crisis, p["X0"])
    assert response.status_code == 409 and "EXPIRED" in response.json()["detail"]
    assert get_crisis(crisis["id"]).json()["status"] == "EXPIRED"


# --- expiry and the CRISIS phase --------------------------------------------------------------
def test_a_crisis_expires_by_time_without_changing_any_metric(clock):
    cid, p = crisis_conference()
    clock.now = parse(snapshot(cid)["phase_started_at"])
    crisis = custom(cid, p["X0"])
    assert get_crisis(crisis["id"]).json()["status"] == "ACTIVE"
    clock.advance(CRISIS_TTL_SECONDS)  # exactly at expires_at
    expired = get_crisis(crisis["id"]).json()
    assert expired["status"] == "EXPIRED" and expired["end_reason"] == "TIME_EXPIRED"
    assert expired["outcome"] is None and expired["ended_at"] is not None
    assert metrics_of(cid) == DEFAULTS  # silence is not a decision
    (event,) = events_of(cid, "crisis_expired")
    assert event["actor"] == cid and event["effects"]["crisis_id"] == crisis["id"]
    assert event["effects"]["reason"] == "TIME_EXPIRED" and event["effects"]["metrics_changed"] is False


def test_expiry_is_recorded_once_however_often_it_is_read(clock):
    cid, p = crisis_conference()
    clock.now = parse(snapshot(cid)["phase_started_at"])
    crisis = custom(cid, p["X0"])
    clock.advance(CRISIS_TTL_SECONDS + 5)
    for _ in range(3):
        assert get_crisis(crisis["id"]).json()["status"] == "EXPIRED"
        assert client.get(f"/conference/{cid}/crises").status_code == 200
    assert len(events_of(cid, "crisis_expired")) == 1


def test_leaving_the_crisis_phase_expires_open_crises_and_keeps_the_metrics():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    ok_respond(crisis, p["D0"], "DIPLOMACY")
    metrics = metrics_of(cid)
    assert client.post(f"/conference/{cid}/advance").status_code == 200  # CRISIS -> DRAFTING
    expired = get_crisis(crisis["id"]).json()
    assert expired["status"] == "EXPIRED" and expired["end_reason"] == "PHASE_CLOSED"
    assert len(expired["responses"]) == 1  # history is kept
    assert metrics_of(cid) == metrics  # what the response did stays
    (event,) = events_of(cid, "crisis_expired")
    assert event["effects"]["reason"] == "PHASE_CLOSED" and event["effects"]["responses"] == 1


def test_a_resolved_crisis_is_not_expired_later():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    assert resolve(crisis, p["X0"]).status_code == 200
    assert client.post(f"/conference/{cid}/advance").status_code == 200
    assert get_crisis(crisis["id"]).json()["status"] == "RESOLVED"
    assert events_of(cid, "crisis_expired") == []


def test_completing_the_conference_closes_every_open_crisis():
    cid, p = crisis_conference()
    a, b = custom(cid, p["X0"]), custom(cid, p["X0"])
    resolve(b, p["X0"])
    for _ in range(4):
        assert client.post(f"/conference/{cid}/advance").status_code == 200
    assert snapshot(cid)["status"] == "COMPLETED"
    assert get_crisis(a["id"]).json()["status"] == "EXPIRED"
    assert get_crisis(b["id"]).json()["status"] == "RESOLVED"
    assert respond(a, p["D0"], option(a, "DIPLOMACY")).status_code == 409


def test_crises_stay_readable_after_the_conference_completed():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    ok_respond(crisis, p["D0"], "DIPLOMACY")
    for _ in range(4):
        client.post(f"/conference/{cid}/advance")
    assert get_crisis(crisis["id"]).status_code == 200
    assert len(client.get(f"/conference/{cid}/crises").json()) == 1


# --- events -----------------------------------------------------------------------------------
def test_the_full_lifecycle_generates_the_expected_events_in_order():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    ok_respond(crisis, p["D0"], "DIPLOMACY")
    ok_respond(crisis, p["D1"], "NO_ACTION")
    resolve(crisis, p["X0"])
    crisis_events = [e["type"] for e in events_of(cid) if e["type"].startswith(("crisis_", "world_state"))]
    assert crisis_events == [
        "crisis_created",
        "crisis_response", "world_state_changed",
        "crisis_response", "world_state_changed",
        "crisis_resolved",
    ]
    ids = [e["id"] for e in events_of(cid)]
    assert ids == list(range(1, len(ids) + 1))  # sequential, no gaps or repeats
    for e in events_of(cid):
        if e["type"].startswith(("crisis_", "world_state")):
            assert e["effects"]["conference_id"] == cid and e["effects"]["crisis_id"] == crisis["id"]


def test_response_events_name_the_responding_country_and_world_changes_show_before_and_after():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"], severity="MEDIUM")
    ok_respond(crisis, p["D0"], "DIPLOMACY")
    country_id = next(a["country_id"] for a in snapshot(cid)["assigned_countries"] if a["country_code"] == p["D0"]["country_code"])
    (response_event,) = events_of(cid, "crisis_response")
    assert response_event["actor"] == country_id
    assert response_event["effects"]["action_type"] == "DIPLOMACY"
    assert response_event["effects"]["country_code"] == p["D0"]["country_code"]
    (change,) = events_of(cid, "world_state_changed")
    assert change["actor"] == country_id
    fx = change["effects"]
    assert fx["source"] == "crisis_response" and fx["before"] == DEFAULTS
    assert fx["after"]["diplomatic_tension"] == 24.0 and fx["applied"]["diplomatic_tension"] == -6.0
    assert fx["response_id"] == response_event["effects"]["response_id"]


def test_rejected_requests_emit_no_events():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    count = len(events_of(cid))
    respond(crisis, p["X0"], option(crisis, "DIPLOMACY"), country_code="IN")  # 403
    respond(crisis, p["D0"], "opt-nope")  # 422
    resolve(crisis, p["D0"])  # 403
    start_crisis(cid, p["D0"])  # 403
    assert len(events_of(cid)) == count


def test_crisis_events_appear_in_the_conference_report_and_metrics_match():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"], severity="MEDIUM")
    ok_respond(crisis, p["D0"], "DIPLOMACY")
    report = client.get(f"/conference/{cid}/report")
    assert report.status_code == 200
    body = report.json()
    assert body["mun_metrics"] == metrics_of(cid)
    assert {"crisis_created", "crisis_response", "world_state_changed"} <= {e["type"] for e in body["diplomatic_events"]}


# --- read-only preview ------------------------------------------------------------------------
def test_preview_shows_what_an_option_would_do_and_changes_nothing():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"], severity="MEDIUM")
    before = state(cid)
    opt = option(crisis, "SANCTIONS")
    response = client.get(f"/crisis/{crisis['id']}/options/{opt['id']}/preview")
    assert response.status_code == 200
    body = response.json()
    assert body["action_type"] == "SANCTIONS" and body["effects"] == opt["effects"]
    assert body["current"] == DEFAULTS and body["projected"]["diplomatic_tension"] == 36.0
    assert body["applied"] == {"diplomatic_tension": 6.0, "economic_risk": 4.0, "international_trust": -4.0, "world_stability": -2.0}
    assert state(cid) == before  # no metric moved, no event, no response
    assert metrics_of(cid) == DEFAULTS
    # ... and it is exactly what the real response then does
    real = ok_respond(crisis, p["D0"], "SANCTIONS")
    assert real["mun_metrics"] == body["projected"] and real["response"]["applied"] == body["applied"]


def test_preview_rejects_an_option_of_another_crisis():
    cid, p = crisis_conference()
    one, two = custom(cid, p["X0"]), custom(cid, p["X0"])
    assert client.get(f"/crisis/{one['id']}/options/{option(two, 'DIPLOMACY')['id']}/preview").status_code == 422
    assert client.get(f"/crisis/{one['id']}/options/opt-nope/preview").status_code == 422


# --- world-state isolation --------------------------------------------------------------------
def test_crisis_effects_change_only_their_own_conference():
    a, pa = crisis_conference()
    b, pb = crisis_conference()
    crisis_a = custom(a, pa["X0"], severity="CRITICAL", types=ALL_TYPES)
    crisis_b = custom(b, pb["X0"])
    world_b = snapshot(b)["world"]
    ok_respond(crisis_a, pa["D0"], "MILITARY_DEPLOYMENT")
    assert metrics_of(a)["diplomatic_tension"] == 46.0
    assert metrics_of(b) == DEFAULTS and snapshot(b)["world"] == world_b  # the other conference is untouched
    assert events_of(b, "crisis_response", "world_state_changed") == []
    assert get_crisis(crisis_b["id"]).json()["responses"] == []


def test_crisis_effects_never_touch_the_shared_simulation():
    cid, p = crisis_conference()
    sandbox_before = client.get("/world").json()
    metrics_before = simulation.world.mun_metrics.model_dump()
    events_before = len(simulation.world.events)
    crisis = custom(cid, p["X0"], severity="CRITICAL", types=ALL_TYPES)
    for name, action in zip(("D0", "D1", "D2"), ("MILITARY_DEPLOYMENT", "SANCTIONS", "HUMANITARIAN_AID")):
        ok_respond(crisis, p[name], action)
    resolve(crisis, p["X0"])
    assert metrics_of(cid) != DEFAULTS
    assert simulation.world.mun_metrics.model_dump() == metrics_before == DEFAULTS
    assert len(simulation.world.events) == events_before
    assert client.get("/world").json() == sandbox_before
    assert client.get("/events").json() == []


def test_the_conference_world_keeps_everything_a_crisis_does_not_own():
    cid, p = crisis_conference()
    before = snapshot(cid)["world"]
    crisis = custom(cid, p["X0"], severity="HIGH", types=ALL_TYPES)
    for name, action in zip(("D0", "D1", "D2"), ("SANCTIONS", "DIPLOMACY", "CYBER_DEFENSE")):
        ok_respond(crisis, p[name], action)
    after = snapshot(cid)["world"]
    for key in ("turn", "countries", "trade_routes"):
        assert after[key] == before[key]  # countries, relationships, sanctions, alliances, trade: all intact
    assert after["events"][: len(before["events"])] == before["events"]  # history is only ever added to
    assert after["mun_metrics"] != before["mun_metrics"]
    assert snapshot(cid)["status"] == "ACTIVE" and snapshot(cid)["current_phase"] == "CRISIS"


def test_crises_work_alongside_negotiations_in_the_same_phase():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    neg = client.post(
        "/negotiation/propose",
        json={"conference_id": cid, "participant_id": p["D0"]["id"], "receiver": p["D1"]["country_code"], "proposal": "A deal."},
    )
    assert neg.status_code == 201
    assert respond(crisis, p["D0"], option(crisis, "DIPLOMACY")).status_code == 201
    accept = client.post(f"/negotiation/{neg.json()['id']}/respond", json={"participant_id": p["D1"]["id"], "action": "ACCEPT"})
    assert accept.status_code == 200
    types = {e["type"] for e in events_of(cid)}
    assert {"negotiation_proposed", "negotiation_accepted", "crisis_response"} <= types


def test_clearing_the_conference_service_forgets_its_crises():
    cid, p = crisis_conference()
    crisis = custom(cid, p["X0"])
    assert get_crisis(crisis["id"]).status_code == 200
    conference_service.clear()
    assert get_crisis(crisis["id"]).status_code == 404
    assert client.get(f"/conference/{cid}/crises").status_code == 404


def test_crisis_ids_and_data_are_unique_per_crisis():
    cid, p = crisis_conference()
    a, b = custom(cid, p["X0"]), custom(cid, p["X0"])
    assert a["id"] != b["id"]
    assert not {o["id"] for o in a["options"]} & {o["id"] for o in b["options"]}
    ok_respond(a, p["D0"], "DIPLOMACY")
    assert get_crisis(b["id"]).json()["responses"] == []  # a response belongs to one crisis only


def test_the_global_cybersecurity_committee_runs_crises_too():
    cid = make_conference(committee="GLOBAL_CYBERSECURITY", delegates=2)
    assert client.post(f"/conference/{cid}/start").status_code == 200
    go_to(cid, "CRISIS")
    p = people(cid)
    crisis = open_template(cid, p["X0"])
    assert respond(crisis, p["D0"], option(crisis, "CYBER_DEFENSE")).status_code == 201
    assert metrics_of(cid)["cybersecurity_level"] == 62.0