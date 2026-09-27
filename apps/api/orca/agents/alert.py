"""Agent 13 — Alert agent.

Turns verified findings into alerts: EVENT → VERIFY → GENERATE → DELIVER.
Used both inside a query (situational alerts for the asked place/route) and
by the background monitor (proactive scanning of coastal sectors, cyclones,
geofence watches). An alert is marked *verified* only when backed by an
official advisory, or by at least two independent source lineages, with
claim confidence ≥ 0.5. Unverified signals are still shown, labelled.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from typing import Optional

from ..core.clock import fmt_ist
from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import AgentStatus, GeoPoint, RiskLevel
from ..core.schemas.geo import Alert
from .base import Agent, AgentOutcome, RunState

CATEGORY = {"wave_height": "waves", "wind_speed": "wind", "wind_gusts": "wind", "cape": "lightning",
            "precipitation": "rain", "cyclone_distance": "cyclone", "boundary_distance": "boundary",
            "official_advisory": "official", "current_speed": "current", "visibility": "visibility"}


class AlertBus:
    """In-process fan-out of new alerts to SSE subscribers."""
    subscribers: list[asyncio.Queue] = []

    @classmethod
    def publish(cls, alert: Alert) -> None:
        for q in list(cls.subscribers):
            q.put_nowait(alert)


def _id(key: str) -> str:
    return "ALR-" + hashlib.sha1(key.encode()).hexdigest()[:10].upper()


def build_alerts(st: RunState, region: str) -> list[Alert]:
    bb = st.bb
    risk = bb.risk
    alerts: list[Alert] = []
    if risk is None:
        return alerts
    claims = {c.factor_id: c for c in bb.claims if c.factor_id}
    day = risk.window_start.strftime("%Y%m%d")
    for f in risk.factors:
        if f.level not in (RiskLevel.CAUTION, RiskLevel.DANGER) or not f.available:
            continue
        cat = CATEGORY.get(f.id, f.id)
        c = claims.get(f.id)
        conf = c.confidence.value if c and c.confidence else 0.0
        lineages = c.n_sources if c else 0
        official = f.id == "official_advisory"
        verified = official or (lineages >= 2 and conf >= 0.5 and (c.n_supporting >= 2 if c else False))
        verification = ("official advisory" if official else
                        f"{c.n_supporting if c else 0}/{(c.n_supporting + c.n_contradicting) if c else 0} sources agree, "
                        f"{lineages} independent lineage(s), confidence {conf * 100:.0f}%")
        sev = "severe" if f.level == RiskLevel.DANGER else "warning"
        key = f"{st.ctx.mode.value}:{cat}:{region}:{day}:{f.level.value}"
        when = f" from {fmt_ist(f.onset)}" if f.onset else ""
        alerts.append(Alert(
            id=_id(key + bb.query_id), created_at=st.now, severity=sev, category=cat,
            title=f"{f.label} {f.level.value} — {region}",
            message=f"{f.label} {'up to ' if f.threshold and f.threshold.direction == 'above' else ''}"
                    f"{f.value:g} {f.units}{when} ({risk.vessel_class.replace('_', ' ')} thresholds). {f.explanation}"
                    if f.value is not None else f.explanation,
            region=region, location=f.location, valid_from=f.onset or risk.window_start, valid_to=risk.window_end,
            level=f.level, evidence=[{"source": m.source, "value": m.value, "units": m.units, "at": m.at.isoformat() if m.at else None,
                                      "level": m.level.value} for m in f.per_source],
            verified=verified, verification=verification, mode=st.ctx.mode.value, trace_id=bb.trace_id, dedup_key=key))
    rt = st.typed.get("route")
    if rt and rt.route:
        rec = next(o for o in rt.route.options if o.id == rt.route.recommended_id)
        for w in rec.warnings:
            if w.startswith("WARNING"):
                key = f"{st.ctx.mode.value}:geofence:{rt.route.origin_name}-{rt.route.destination_name}:{w[:60]}"
                alerts.append(Alert(id=_id(key + bb.query_id), created_at=st.now, severity="warning", category="geofence",
                                    title=f"Route geofence — {rt.route.origin_name} → {rt.route.destination_name}",
                                    message=w, region=region, level=RiskLevel.CAUTION, verified=True,
                                    verification="deterministic geometry (route ∩ zone polygon)",
                                    mode=st.ctx.mode.value, trace_id=bb.trace_id, dedup_key=key,
                                    valid_from=rec.departure, valid_to=rec.arrival))
    return alerts


class AlertAgent(Agent):
    name = "alert"
    title = "Alert & Monitoring Agent"
    responsibility = "EVENT → VERIFY → GENERATE → DELIVER for threshold crossings, cyclones, geofences and boundaries"
    tools = ["alerts.verify", "alerts.generate", "alerts.deliver(sse)", "store.alerts"]
    consumes = ["evidence", "hazard", "route"]
    output_model = None

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        from ..store.db import Store
        u = st.bb.understanding
        region = (u.region.name if u.region else (u.places[0].name if u.places else "query area"))
        alerts = build_alerts(st, region)
        store = Store.get()
        delivered = 0
        for a in alerts:
            since = (st.now - timedelta(hours=6)).isoformat()
            if not store.alert_exists(a.dedup_key, since):
                store.save_alert(a)
                AlertBus.publish(a)
                delivered += 1
        st.bb.alerts = alerts
        for a in alerts:
            st.emit("alert", a.title, agent=self.name, severity=a.severity, verified=a.verified)
        return AgentOutcome(status=AgentStatus.SUCCEEDED,
                            summary=f"{len(alerts)} alert(s) generated, {sum(a.verified for a in alerts)} verified, {delivered} newly delivered",
                            tools=self.tools)
