"""Agent 4 — Weather / Atmospheric agent.

Wind, gusts, rainfall rate, pressure, convective (lightning) potential and
visibility from ECMWF IFS, NOAA GFS and DWD ICON; forecasts are labelled
FORECAST, recent history HISTORICAL, and IMD warnings (ADVISORY) are handled
by the Advisory agent — the kinds are never mixed. History mode supports
research questions; tie-breaker mode adds the UK Met Office global model.
"""
from __future__ import annotations

from datetime import timedelta

from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import AgentStatus, BBox, DataKind
from ._sampling import RetrievalOutput, fetch_field, fetch_points, field_summary, summarize_points
from .base import Agent, AgentOutcome, RunState

WX_VARS = ["wind_speed", "wind_direction", "wind_gusts", "precipitation", "pressure", "cape", "visibility", "weather_code"]


class WeatherAgent(Agent):
    name = "weather"
    title = "Weather & Atmospheric Agent"
    responsibility = "Wind, gusts, rain, pressure, lightning potential and visibility from multiple NWP models"
    tools = ["om_ecmwf_ifs.points", "om_gfs.points", "om_icon.points", "om_ukmo.points (tie-breaker)", "openmeteo.run_info"]
    consumes = ["geospatial"]
    output_model = RetrievalOutput

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        reg = st.ctx.registry
        u = st.bb.understanding
        geo = st.typed.get("geospatial")
        tiebreak = task.params.get("tiebreaker", False)
        models = reg.tiebreaker("weather") if tiebreak else reg.weather_models()
        mode = task.params.get("mode", "point")
        st.stage("RETRIEVAL", "Retrieving numerical weather prediction data")
        if mode == "field":
            bbox: BBox = geo.bbox
            fd, failures = await fetch_field(models, bbox, task.params.get("res_deg", 0.5), st, self.name,
                                             ["wind_speed", "wind_gusts", "precipitation", "cape"])
            prior = st.typed.get(self.name + ":field")
            if prior and fd and tiebreak:
                prior.by_model.update(fd.by_model); prior.models.update(fd.models); prior.provenance.update(fd.provenance)
                fd = prior
            st.typed[self.name + ":field"] = fd
            out = RetrievalOutput(mode="field", models_used=list(fd.by_model) if fd else [],
                                  models_failed=sorted({f.source_id for f in failures}), field_grid=field_summary(fd))
            ok = fd is not None and bool(fd.by_model)
            return AgentOutcome(status=AgentStatus.SUCCEEDED if ok and not failures else AgentStatus.PARTIAL if ok else AgentStatus.FAILED,
                                summary=f"gridded wind/rain fields from {len(out.models_used)} model(s)", output=out, typed=fd,
                                sources=out.models_used, tools=[f"{m}.points" for m in out.models_used], failures=failures)

        samples = geo.samples
        ids, pts = [s.id for s in samples], [s.point for s in samples]
        if mode == "history":
            days = int(task.params.get("past_days", 28))
            wd, failures = await fetch_points(models[:1], ids[:1], pts[:1], st, self.name,
                                              ["wind_speed", "wind_direction"], past_days=min(92, days), forecast_days=1)
            for per_pt in wd.by_model.values():
                for d in per_pt:
                    for ts in d.values():
                        ts.provenance.kind = DataKind.HISTORICAL
                        ts.provenance.notes.append("past model analyses/short-range forecasts (Open-Meteo past_days), used as historical context")
            st.typed[self.name + ":history"] = wd
            out = summarize_points(wd, (st.now - timedelta(days=days), st.now), ["wind_speed"])
            out.mode = "history"
            return AgentOutcome(status=AgentStatus.SUCCEEDED if wd.by_model else AgentStatus.FAILED,
                                summary=f"{days}-day wind history from {', '.join(wd.by_model) or 'no model'}",
                                output=out, typed=wd, sources=list(wd.by_model), tools=[f"{m}.points" for m in wd.by_model],
                                failures=failures)

        wd, failures = await fetch_points(models, ids, pts, st, self.name, WX_VARS)
        st.stage("NORMALIZATION", "Normalising wind to km/h (knots shown), visibility to km, rain to mm/h")
        window = (u.time_window.start, u.time_window.end)
        prior = st.typed.get(self.name)
        if prior is not None and tiebreak:
            prior.by_model.update(wd.by_model)
            prior.models.update(wd.models)
            wd = prior
        out = summarize_points(wd, window, WX_VARS, worst_is_max={"visibility": False, "pressure": False})
        out.models_failed = sorted({f.source_id for f in failures})
        st.typed[self.name] = wd
        winds = [s for s in out.summaries if s.variable == "wind_speed" and s.worst is not None]
        summ = (f"wind worst {max(s.worst for s in winds):.0f} km/h across {len(winds)} model(s)" if winds
                else "no wind data available")
        status = AgentStatus.SUCCEEDED if winds and not failures else AgentStatus.PARTIAL if winds else AgentStatus.FAILED
        return AgentOutcome(status=status, summary=summ, output=out, typed=wd, sources=out.models_used,
                            tools=[f"{m}.points" for m in out.models_used], failures=failures,
                            warnings=[f.reason for f in failures][:4])
