"""Builds the end-of-session report from existing simulation data only.

Sources, and nothing else:
  * the world's event log (`world.events`) - every action that actually happened,
  * the current world versus the initial world (`create_initial_world()`) - what actually changed,
  * for a conference: its record and participants.

The builder is a pure function: it never mutates the world it is given and never invents events,
countries or outcomes. Anything missing from an event's `effects` becomes None.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from .models import DiplomacyEvent, WorldState
from .mun import Conference, ConferenceStatus, Participant, ParticipantRole
from .report_schemas import (
    ReportAid,
    ReportAlliance,
    ReportConference,
    ReportCountry,
    ReportCountryChange,
    ReportEvent,
    ReportOutcome,
    ReportParticipant,
    ReportSanction,
    ReportTotals,
    ReportTradeChange,
    ReportType,
    SimulationReport,
)

ACTION_SANCTION = "sanction"
ACTION_ALLIANCE = "alliance"
ACTION_AID = "aid"
ACTION_TYPES = (ACTION_SANCTION, ACTION_ALLIANCE, ACTION_AID)


def _pair(effects: dict[str, Any], key: str) -> tuple[Any, Any]:
    """(before, after) from an effects entry shaped {"before": x, "after": y}; (None, None) if absent."""
    value = effects.get(key)
    if isinstance(value, dict):
        return value.get("before"), value.get("after")
    return None, None


def _plural(count: int, word: str, plural: Optional[str] = None) -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


def _join(parts: list[str]) -> str:
    if len(parts) <= 2:
        return " and ".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _signed(value: float) -> str:
    return f"{value:+g}"


def _country_changes(world: WorldState, baseline: WorldState) -> list[ReportCountryChange]:
    start = {c.id: c for c in baseline.countries}
    names = {c.id: c.name for c in world.countries}
    changes: list[ReportCountryChange] = []
    for country in world.countries:
        before = start.get(country.id)
        if before is None:
            continue
        alliances_added = [a for a in country.alliances if a not in before.alliances]
        new_sanctioners = [names.get(s, s) for s in country.sanctions if s not in before.sanctions]
        if (
            country.gdp == before.gdp
            and country.stability == before.stability
            and not alliances_added
            and not new_sanctioners
        ):
            continue
        changes.append(
            ReportCountryChange(
                id=country.id,
                name=country.name,
                gdp_before=before.gdp,
                gdp_after=country.gdp,
                stability_before=before.stability,
                stability_after=country.stability,
                alliances_added=alliances_added,
                sanctions_received_from=new_sanctioners,
            )
        )
    return changes


def _trade_changes(world: WorldState, baseline: WorldState) -> list[ReportTradeChange]:
    start = {r.id: r for r in baseline.trade_routes}
    changes: list[ReportTradeChange] = []
    for route in world.trade_routes:
        before = start.get(route.id)
        if before is None:
            continue
        if (before.active, before.efficiency, before.volume) == (route.active, route.efficiency, route.volume):
            continue
        changes.append(
            ReportTradeChange(
                route_id=route.id,
                exporter=route.exporter,
                importer=route.importer,
                resource=route.resource,
                active_before=before.active,
                active_after=route.active,
                volume_before=before.volume,
                volume_after=route.volume,
                efficiency_before=before.efficiency,
                efficiency_after=route.efficiency,
            )
        )
    return changes


def _highlights(changes: list[ReportCountryChange], trade: list[ReportTradeChange]) -> list[str]:
    """Extremes taken straight from the recorded before/after values."""
    lines: list[str] = []

    def extreme(delta, pick, label, fmt):
        scored = [(delta(c), c) for c in changes if delta(c) != 0]
        scored = [(d, c) for d, c in scored if pick(d)]
        if scored:
            d, c = max(scored, key=lambda x: abs(x[0]))
            lines.append(f"{label}: {c.name} ({fmt(d)})")

    extreme(lambda c: round(c.gdp_after - c.gdp_before, 2), lambda d: d > 0, "Largest GDP gain", _signed)
    extreme(lambda c: round(c.gdp_after - c.gdp_before, 2), lambda d: d < 0, "Largest GDP loss", _signed)
    extreme(lambda c: c.stability_after - c.stability_before, lambda d: d > 0, "Largest stability gain", _signed)
    extreme(lambda c: c.stability_after - c.stability_before, lambda d: d < 0, "Largest stability loss", _signed)

    suspended = sum(1 for t in trade if t.active_before and not t.active_after)
    if suspended:
        lines.append(f"Trade routes suspended: {suspended}")
    return lines


def _outcome(
    events: list[DiplomacyEvent],
    sanctions: list[ReportSanction],
    alliances: list[ReportAlliance],
    aid: list[ReportAid],
    changes: list[ReportCountryChange],
    trade: list[ReportTradeChange],
) -> ReportOutcome:
    actions = sum(1 for e in events if e.type in ACTION_TYPES)
    total_aid = round(sum(a.amount for a in aid if a.amount is not None), 2)
    totals = ReportTotals(
        actions=actions,
        sanctions=len(sanctions),
        alliances=len(alliances),
        aid_transfers=len(aid),
        total_aid_amount=total_aid,
        trade_routes_changed=len(trade),
        countries_changed=len(changes),
    )
    if actions == 0:
        return ReportOutcome(
            summary="No diplomatic actions were recorded in this session, so the world remains in its starting state.",
            highlights=[],
            totals=totals,
        )

    kinds = []
    if sanctions:
        kinds.append(_plural(len(sanctions), "sanction"))
    if alliances:
        kinds.append(_plural(len(alliances), "alliance"))
    if aid:
        kinds.append(_plural(len(aid), "aid transfer"))
    summary = f"{_plural(actions, 'diplomatic action')} {'was' if actions == 1 else 'were'} recorded: {_join(kinds)}."
    if aid and total_aid:
        summary += f" Total aid sent: {total_aid:g} (billions of illustrative simulation dollars)."
    if trade:
        summary += f" {_plural(len(trade), 'trade route')} ended up different from the starting state."
    summary += f" {_plural(len(changes), 'country', 'countries')} ended with a changed GDP, stability, alliance or sanction status."
    return ReportOutcome(summary=summary, highlights=_highlights(changes, trade), totals=totals)


def build_report(
    world: WorldState,
    baseline: WorldState,
    *,
    conference: Optional[Conference] = None,
    participants: Sequence[Participant] = (),
    generated_at: Optional[datetime] = None,
) -> SimulationReport:
    """Report on `world` (compared with `baseline`). Pass `conference` for a conference-scoped report."""
    names = {c.id: c.name for c in world.countries}
    by_code = {c.country_code: c for c in world.countries if c.country_code}

    def name_of(country_id: Optional[str]) -> str:
        return names.get(country_id, country_id) if country_id else ""

    events = list(world.events)

    # --- per-action sections -------------------------------------------------------------------
    sanctions: list[ReportSanction] = []
    alliances: list[ReportAlliance] = []
    aid: list[ReportAid] = []
    for e in events:
        fx = e.effects or {}
        if e.type == ACTION_SANCTION and e.target:
            gdp_b, gdp_a = _pair(fx, "target_gdp")
            stab_b, stab_a = _pair(fx, "target_stability")
            sanctions.append(
                ReportSanction(
                    event_id=e.id, turn=e.turn,
                    imposed_by=e.actor, imposed_by_name=name_of(e.actor),
                    target=e.target, target_name=name_of(e.target),
                    target_gdp_before=gdp_b, target_gdp_after=gdp_a,
                    target_stability_before=stab_b, target_stability_after=stab_a,
                    trade_routes_suspended=list(fx.get("trade_routes_deactivated") or []),
                )
            )
        elif e.type == ACTION_ALLIANCE and e.target:
            members = [e.actor, e.target]
            alliances.append(
                ReportAlliance(
                    event_id=e.id, turn=e.turn, name=fx.get("alliance"),
                    members=members, member_names=[name_of(m) for m in members],
                )
            )
        elif e.type == ACTION_AID and e.target:
            donor_b, donor_a = _pair(fx, "actor_gdp")
            rec_b, rec_a = _pair(fx, "target_gdp")
            aid.append(
                ReportAid(
                    event_id=e.id, turn=e.turn,
                    donor=e.actor, donor_name=name_of(e.actor),
                    recipient=e.target, recipient_name=name_of(e.target),
                    amount=fx.get("amount"),
                    donor_gdp_before=donor_b, donor_gdp_after=donor_a,
                    recipient_gdp_before=rec_b, recipient_gdp_after=rec_a,
                )
            )

    # --- participating countries -------------------------------------------------------------
    initiated: dict[str, int] = {}
    received: dict[str, int] = {}
    for e in events:
        if e.type not in ACTION_TYPES:
            continue
        if e.actor in names:
            initiated[e.actor] = initiated.get(e.actor, 0) + 1
        if e.target in names:
            received[e.target] = received.get(e.target, 0) + 1

    delegate_by_country: dict[str, str] = {}
    for p in participants:
        seat = by_code.get(p.country_code) if p.country_code else None
        if seat is not None and p.role is ParticipantRole.PARTICIPANT:
            delegate_by_country[seat.id] = p.name

    involved = set(initiated) | set(received) | set(delegate_by_country)
    countries = [
        ReportCountry(
            id=c.id, name=c.name, flag=c.flag,
            delegate=delegate_by_country.get(c.id),
            actions_initiated=initiated.get(c.id, 0),
            actions_received=received.get(c.id, 0),
        )
        for c in world.countries
        if c.id in involved
    ]

    # --- state changes ---------------------------------------------------------------------------
    changes = _country_changes(world, baseline)
    trade = _trade_changes(world, baseline)

    # --- conference scope ----------------------------------------------------------------------
    report_type: ReportType = "SIMULATION_SNAPSHOT"
    conference_view = None
    metrics = None
    if conference is not None:
        report_type = "CONFERENCE_FINAL" if conference.status is ConferenceStatus.COMPLETED else "CONFERENCE_INTERIM"
        conference_view = ReportConference(
            id=conference.id,
            name=conference.name,
            committee=conference.committee.value,
            topic=conference.topic,
            status=conference.status,
            current_phase=conference.current_phase,
            participants=[
                ReportParticipant(
                    name=p.name,
                    role=p.role,
                    country_name=(by_code[p.country_code].name if p.country_code in by_code else None),
                )
                for p in participants
            ],
        )
        metrics = world.mun_metrics.model_copy(deep=True)

    return SimulationReport(
        report_type=report_type,
        generated_at=generated_at or datetime.now(timezone.utc),
        turn=world.turn,
        event_count=len(events),
        activity_recorded=any(e.type in ACTION_TYPES for e in events),
        conference=conference_view,
        participating_countries=countries,
        alliances=alliances,
        sanctions=sanctions,
        aid=aid,
        trade_changes=trade,
        diplomatic_events=[
            ReportEvent(
                id=e.id, turn=e.turn, type=e.type,
                actor=e.actor, actor_name=name_of(e.actor),
                target=e.target, target_name=name_of(e.target) if e.target else None,
                message=e.message, timestamp=e.timestamp,
            )
            for e in events
        ],
        world_changes=changes,
        mun_metrics=metrics,
        outcome=_outcome(events, sanctions, alliances, aid, changes, trade),
    )