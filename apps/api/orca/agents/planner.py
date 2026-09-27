"""Agent 1 — Orchestrator / Planner agent.

Understands the request (deterministic NLU, LLM fallback only when
confidence is low), resolves location and time, selects agents, builds a
dependency graph of tasks, and after each execution round reviews the
blackboard and re-plans when:

  RP1  a critical retrieval produced no data           → query an alternative model
  RP2  sources disagree on a critical variable          → add an independent tie-breaker model, re-verify
  RP3  an active tropical cyclone is within 1500 km     → extend the assessment horizon by 24 h
  RP4  the recommended route enters a protected area    → re-route with the zone as a hard constraint
"""
from __future__ import annotations

from typing import Optional

from ..core import temporal
from ..core.schemas.blackboard import ExecutionPlan, PlanTask, Understanding
from ..core.schemas.common import AgentStatus, Intent, Place, RiskLevel, UserRole, VesselClass
from ..reasoning import nlu
from .base import RunState

SAFETY_LIKE = (Intent.SAFETY_CHECK, Intent.CONDITIONS, Intent.HAZARD_SCAN)


class Planner:
    name = "planner"
    title = "Orchestrator / Planner Agent"
    responsibility = "Intent understanding, location/time resolution, task decomposition, agent selection, re-planning"
    tools = ["nlu.parse (deterministic)", "temporal.resolve", "gazetteer.match", "llm.interpret (fallback, optional)",
             "plan.build_dag", "plan.review"]

    # ------------------------------------------------------------------ understanding
    async def understand(self, st: RunState, ctx: Optional[nlu.ConversationContext]) -> Understanding:
        st.stage("INTENT", "Understanding the question")
        u = nlu.parse(st.bb.request, st.now, st.ctx.ref, ctx)
        st.emit("tool", f"rule-based NLU: intent {u.intent.value}, language {u.language}, confidence {u.parse_confidence:.2f}",
                agent=self.name, tool="nlu.parse")
        if u.parse_confidence < 0.5 and st.ctx.llm.available:
            st.emit("tool", f"low parse confidence — asking LLM for a structured interpretation ({st.ctx.llm.model})",
                    agent=self.name, tool="llm.interpret")
            res = await st.ctx.llm.interpret(st.bb.request.text, st.ctx.ref.places, st.ctx.ref.regions)
            st.bb.llm_usage["input_tokens"] = st.bb.llm_usage.get("input_tokens", 0) + res.input_tokens
            st.bb.llm_usage["output_tokens"] = st.bb.llm_usage.get("output_tokens", 0) + res.output_tokens
            if res.data:
                u2 = self._from_llm(res.data, st, u)
                if u2:
                    u = u2
                    st.emit("tool", "LLM interpretation validated against gazetteer and schema", agent=self.name, tool="llm.interpret")
            else:
                st.emit("tool", f"LLM interpretation unavailable ({res.error}); keeping rule-based result",
                        agent=self.name, tool="llm.interpret")
        st.stage("LOCATION_TIME", "Resolving location and time window")
        if u.time_window:
            st.emit("tool", f"time window {u.time_window.label} → {u.time_window.start:%Y-%m-%d %H:%MZ}–"
                            f"{u.time_window.end:%Y-%m-%d %H:%MZ} ({u.time_window.rule})", agent=self.name, tool="temporal.resolve")
        return u

    def _from_llm(self, d: dict, st: RunState, base: Understanding) -> Optional[Understanding]:
        ref = st.ctx.ref
        try:
            intent = Intent(d["intent"])
        except ValueError:
            return None
        ids = [i for i in d.get("place_ids", []) if i in ref.place_by_id]
        places = [ref.place(i) for i in ids]
        region = ref.region_place(d["region_id"]) if d.get("region_id") in {r["id"] for r in ref.regions} else None
        origin = ref.place(d["origin_id"]) if d.get("origin_id") in ref.place_by_id else None
        dest = ref.place(d["destination_id"]) if d.get("destination_id") in ref.place_by_id else None
        tr = temporal.resolve(d.get("time_expression_en") or "", st.now)
        u = base.model_copy(deep=True)
        u.intent, u.places, u.region, u.origin, u.destination = intent, places or base.places, region or base.region, origin, dest
        if tr.explicit:
            u.time_window = tr.window
            u.comparison_window = tr.comparison or u.comparison_window
        off = d.get("offshore_km")
        if isinstance(off, (int, float)) and 0 < off < 400:
            u.offshore_km = float(off)
        if d.get("vessel_class") in [v.value for v in VesselClass]:
            u.vessel_class = VesselClass(d["vessel_class"])
        if st.bb.request.role is None and d.get("role") in [r.value for r in UserRole]:
            u.role = UserRole(d["role"])
        u.parse_method = "llm (validated)"
        u.parse_confidence = max(base.parse_confidence, 0.7)
        u.clarification_needed = None
        if intent == Intent.ROUTE_PLAN and not (origin and dest):
            u.clarification_needed = "Please give both the departure and destination ports."
        elif intent in SAFETY_LIKE + (Intent.FISHING_ZONES,) and not (u.places or u.region):
            u.clarification_needed = "Which location? Name a coastal town or harbour, or click the map."
        u.assumptions.append("interpretation produced by LLM and validated against the ORCA gazetteer")
        return u

    # ------------------------------------------------------------------ planning
    def plan(self, st: RunState) -> ExecutionPlan:
        u = st.bb.understanding
        st.stage("PLANNING", "Decomposing the question into tasks")
        p = ExecutionPlan()
        T = lambda tid, agent, deps=(), reason="", critical=False, **params: p.tasks.append(  # noqa: E731
            PlanTask(id=tid, agent=agent, depends_on=list(deps), reason=reason, critical=critical, params=params))
        intent = u.intent
        if Intent.ROUTE_PLAN in u.secondary_intents and u.origin and u.destination:
            intent = Intent.ROUTE_PLAN
        place = (u.places[0] if u.places else None)
        if intent in (Intent.EXPLAIN, Intent.SOURCES, Intent.CONFLICTS):
            T("evidence", "evidence", reason="re-use verified evidence from the previous answer", reuse_previous=True)
            T("communication", "communication", ["evidence"], "render explanation")
            p.rationale.append("follow-up about a previous answer: no new data retrieval needed")
        elif intent == Intent.ROUTE_PLAN:
            span = max(abs(u.origin.point.lat - u.destination.point.lat), abs(u.origin.point.lon - u.destination.point.lon))
            res = 0.25 if span < 3 else 0.5
            T("geospatial", "geospatial", reason="snap end-points to navigable water, build routing box", critical=True,
              mode="route", origin=u.origin.model_dump(), destination=u.destination.model_dump())
            T("ocean", "ocean", ["geospatial"], f"gridded wave & current forecasts ({res}°) for the cost surface", True,
              mode="field", res_deg=res)
            T("weather", "weather", ["geospatial"], f"gridded wind & rain forecasts ({res}°)", True, mode="field", res_deg=res)
            T("advisory", "advisory", ["geospatial"], "cyclone and official warnings near the route")
            T("route", "route", ["geospatial", "ocean", "weather"], "time-dependent A* over the risk surface", True)
            T("hazard", "hazard", ["route", "advisory"], "evaluate risk along the route at ETA", True)
            T("evidence", "evidence", ["hazard"], "verify claims, detect conflicts, compute confidence")
            T("alert", "alert", ["evidence"], "raise route / geofence alerts")
            T("communication", "communication", ["evidence"], "render answer")
            p.rationale.append("route question → the route must be evaluated segment by segment at ETA, not only at the end-points")
        elif intent == Intent.REGIONAL_RISK:
            T("geospatial", "geospatial", reason="derive offshore stations along the coast", critical=True,
              mode="region", region=u.region.model_dump(), offshore_km=25)
            T("ocean", "ocean", ["geospatial"], "waves / currents at every station", True)
            T("weather", "weather", ["geospatial"], "wind / rain / convection at every station", True)
            T("advisory", "advisory", ["geospatial"], "cyclones and official warnings for the region")
            T("hazard", "hazard", ["ocean", "weather", "advisory"], "per-station and regional risk", True)
            T("evidence", "evidence", ["hazard"], "verify and score")
            T("alert", "alert", ["evidence"], "regional alerts")
            T("communication", "communication", ["evidence"], "authority-grade situation report")
            p.rationale.append("regional question → multiple coastal stations are assessed individually")
        elif intent == Intent.FISHING_ZONES:
            T("geospatial", "geospatial", reason="analysis box offshore of the harbour", critical=True, mode="area",
              place=(place or u.region).model_dump(), offshore_km=40, half_deg=1.2)
            T("fisheries", "fisheries", ["geospatial"], "SST-front / chlorophyll productivity indicator + INCOIS PFZ", True)
            T("satellite", "satellite", ["geospatial"], "satellite context at analysis centre")
            T("ocean", "ocean", ["geospatial"], "sea state in the analysis area")
            T("weather", "weather", ["geospatial"], "winds in the analysis area")
            T("advisory", "advisory", ["geospatial"], "cyclone / official warnings")
            T("hazard", "hazard", ["ocean", "weather", "advisory"], "is it safe to go there?")
            T("evidence", "evidence", ["hazard", "fisheries", "satellite"], "verify and score")
            T("communication", "communication", ["evidence"], "render answer")
            p.rationale.append("fishing-zone question → productivity evidence plus a safety check of the same area")
        elif intent in (Intent.RESEARCH_TREND, Intent.COMPARE_PERIODS):
            days = int(round((u.time_window.end - (u.comparison_window.start if u.comparison_window else u.time_window.start)).total_seconds() / 86400))
            T("geospatial", "geospatial", reason="define the study region", critical=True, mode="area",
              place=(place or u.region).model_dump(), offshore_km=40, half_deg=0.75)
            T("satellite", "satellite", ["geospatial"], "daily area-mean SST, SST anomaly and chlorophyll series", True, mode="series")
            T("weather", "weather", ["geospatial"], f"{days}-day wind history", mode="history", past_days=days)
            T("research", "research", ["satellite", "weather"], "statistics, correlation, hypothesis evaluation", True)
            T("evidence", "evidence", ["research"], "label observation / correlation / hypothesis / conclusion")
            T("communication", "communication", ["evidence"], "researcher-grade analysis")
            p.rationale.append("research question → compare periods, correlate variables, evaluate hypotheses; never infer causation")
        elif intent == Intent.GEOFENCE_CHECK:
            T("geospatial", "geospatial", reason="zone, boundary and geofence analysis", critical=True, mode="point",
              place=place.model_dump(), offshore_km=u.offshore_km)
            T("evidence", "evidence", ["geospatial"], "verify geometry claims")
            T("communication", "communication", ["evidence"], "render answer")
        else:  # SAFETY_CHECK, CONDITIONS, HAZARD_SCAN
            mode = "ring" if intent == Intent.HAZARD_SCAN else "point"
            T("geospatial", "geospatial", reason="assessment point, trip transect, zone & boundary context", critical=True,
              mode=mode, place=place.model_dump(), offshore_km=u.offshore_km, radius_km=u.radius_km)
            T("ocean", "ocean", ["geospatial"], "waves, swell, currents from 3 wave models + SMOC", True)
            T("weather", "weather", ["geospatial"], "wind, gusts, rain, lightning potential from 3 NWP models", True)
            T("satellite", "satellite", ["geospatial"], "satellite SST / anomaly / chlorophyll (context & cross-check)")
            T("advisory", "advisory", ["geospatial"], "cyclones (GDACS), IMD & INCOIS warnings")
            deps = ["satellite"]
            if u.activity == "fishing" and intent == Intent.SAFETY_CHECK:
                T("fisheries", "fisheries", ["geospatial"], "nearby productivity indicator (secondary)")
                deps.append("fisheries")
            T("hazard", "hazard", ["ocean", "weather", "advisory", "geospatial"], "deterministic risk decision", True)
            T("evidence", "evidence", ["hazard", *deps], "verify claims, detect conflicts, compute confidence")
            T("alert", "alert", ["evidence"], "situational alerts")
            T("communication", "communication", ["evidence"], "render answer")
            p.rationale.append("safety question → conservative multi-source assessment over the whole trip window")
        st.stage("AGENT_SELECTION", f"{len({t.agent for t in p.tasks})} agents selected",
                 agents=sorted({t.agent for t in p.tasks}))
        return p

    # ------------------------------------------------------------------ replanning
    def review(self, st: RunState, round_no: int) -> list[PlanTask]:
        bb = st.bb
        new: list[PlanTask] = []
        done_flags = {r.get("rule") for r in bb.plan.replans}

        def record(rule: str, detail: str) -> None:
            bb.plan.replans.append({"rule": rule, "round": round_no + 1, "detail": detail})
            st.emit("replan", detail, agent=self.name, rule=rule)

        recs = {r.agent: r for r in bb.agents.values()}
        oc, wx = recs.get("ocean"), recs.get("weather")
        field_mode = any(t.agent == "ocean" and t.params.get("mode") == "field" for t in bb.plan.tasks)
        # RP1 — missing critical data
        if oc and oc.status == AgentStatus.FAILED and "RP1-ocean" not in done_flags:
            new.append(PlanTask(id=f"ocean_alt#{round_no + 1}", agent="ocean", round=round_no + 1, critical=True,
                                reason="primary wave models returned no data — querying alternative model (DWD GWAM)",
                                params={**next(t.params for t in bb.plan.tasks if t.agent == "ocean"), "tiebreaker": True}))
            record("RP1-ocean", "No wave data from primary models → re-planning with an alternative wave model (DWD GWAM)")
        if wx and wx.status == AgentStatus.FAILED and "RP1-weather" not in done_flags:
            new.append(PlanTask(id=f"weather_alt#{round_no + 1}", agent="weather", round=round_no + 1, critical=True,
                                reason="primary NWP models returned no data — querying alternative model (UK Met Office)",
                                params={**next(t.params for t in bb.plan.tasks if t.agent == "weather"), "tiebreaker": True}))
            record("RP1-weather", "No wind data from primary models → re-planning with an alternative NWP model (UK Met Office)")
        # RP2 — decision-relevant conflict on a critical variable
        for c in bb.conflicts:
            if not c.decision_relevant or c.variable not in ("wave_height", "wind_speed"):
                continue
            fam = "ocean" if c.variable == "wave_height" else "weather"
            rule = f"RP2-{fam}"
            if rule in done_flags or any(t.agent == fam and t.params.get("tiebreaker") for t in new):
                continue
            base = next((t.params for t in bb.plan.tasks if t.agent == fam), {})
            new.append(PlanTask(id=f"{fam}_tiebreak#{round_no + 1}", agent=fam, round=round_no + 1,
                                reason=f"sources disagree on {c.variable} — adding an independent tie-breaker model",
                                params={**base, "tiebreaker": True}))
            record(rule, f"Conflict on {c.variable} ({c.description[:90]}…) → requesting an independent tie-breaker model")
            done_flags.add(rule)
        # RP3 — cyclone nearby → extended horizon
        adv = st.typed.get("advisory")
        if adv and adv.nearest_active_km is not None and adv.nearest_active_km < 1500 and "RP3" not in done_flags \
                and any(t.agent == "hazard" for t in bb.plan.tasks):
            new.append(PlanTask(id=f"hazard_ext#{round_no + 1}", agent="hazard", round=round_no + 1,
                                reason="active cyclone within 1500 km — assessing the following 24 h as well",
                                params={"extend_h": 24, "tag": "extended"}))
            record("RP3", f"Active cyclone {adv.nearest_active_km:.0f} km away → extending assessment horizon by 24 h")
        # RP4 — route enters protected area
        rt = st.typed.get("route")
        if rt and rt.route and "RP4" not in done_flags:
            rec = next(o for o in rt.route.options if o.id == rt.route.recommended_id)
            if any(z.kind == "mpa" for z in rec.zone_violations):
                new.append(PlanTask(id=f"route_block#{round_no + 1}", agent="route", round=round_no + 1,
                                    reason="recommended route enters a protected area — re-routing with the zone as a hard constraint",
                                    params={"block_protected": True}))
                record("RP4", "Recommended route crosses a protected area → re-routing with protected areas blocked")
        if not new:
            return []
        needs_rerun = any(t.agent in ("ocean", "weather", "route") for t in new)
        if needs_rerun:
            head = [t.id for t in new]
            chain = []
            order = (["route"] if field_mode and not any(t.agent == "route" for t in new) else []) + \
                    ["hazard", "evidence", "alert", "communication"]
            existing = {t.agent for t in bb.plan.tasks}
            prev_ids = head
            for a in order:
                if a not in existing:
                    continue
                tid = f"{a}#{round_no + 1}"
                params = next((t.params for t in bb.plan.tasks if t.agent == a and not t.params.get("tag")), {})
                chain.append(PlanTask(id=tid, agent=a, depends_on=prev_ids, round=round_no + 1, params=params,
                                      reason="re-evaluate with the additional evidence"))
                prev_ids = [tid]
            # route re-run must follow its own new task if present
            new += chain
        else:
            # extended hazard only: refresh evidence & communication afterwards so the answer mentions it
            prev = [t.id for t in new]
            for a in ("evidence", "communication"):
                tid = f"{a}#{round_no + 1}"
                params = next((t.params for t in bb.plan.tasks if t.agent == a), {})
                new.append(PlanTask(id=tid, agent=a, depends_on=prev, round=round_no + 1, params=params,
                                    reason="incorporate extended-horizon assessment"))
                prev = [tid]
        return new
