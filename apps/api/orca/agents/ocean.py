"""Agent 3 — Oceanography agent.

Significant wave height / direction / period, wind-sea and swell, surface
currents and model SST from three independent wave models (Météo-France
MFWAM, ECMWF WAM, NOAA GFS-Wave) plus SMOC currents. Point mode samples the
geospatial agent's sampling design over the time window; field mode returns
gridded hourly fields for the router. On replanning it can add an
additional independent wave model (DWD GWAM) as tie-breaker.
"""
from __future__ import annotations

from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import AgentStatus, BBox
from ._sampling import RetrievalOutput, fetch_field, fetch_points, field_summary, summarize_points
from .base import Agent, AgentOutcome, RunState

WAVE_VARS = ["wave_height", "wave_direction", "wave_period", "swell_height", "swell_period", "wind_wave_height"]
CURRENT_VARS = ["current_speed", "current_direction", "sst_model"]


class OceanAgent(Agent):
    name = "ocean"
    title = "Oceanography Agent"
    responsibility = "Waves, swell, currents and model SST from multiple independent ocean models, aligned to the query's space-time"
    tools = ["om_mfwam.points", "om_ecmwf_wam.points", "om_gfs_wave.points", "om_smoc.points",
             "om_dwd_gwam.points (tie-breaker)", "openmeteo.run_info"]
    consumes = ["geospatial"]
    output_model = RetrievalOutput

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        reg = st.ctx.registry
        u = st.bb.understanding
        geo = st.typed.get("geospatial")
        tiebreak = task.params.get("tiebreaker", False)
        wave_models = reg.tiebreaker("marine") if tiebreak else reg.wave_models()
        cur_models = [] if tiebreak else reg.current_models()
        mode = task.params.get("mode", "point")
        failures = []
        st.stage("RETRIEVAL", "Retrieving ocean model data")
        if mode == "field":
            bbox: BBox = geo.bbox
            res = task.params.get("res_deg", 0.5)
            fd, f1 = await fetch_field(wave_models, bbox, res, st, self.name, ["wave_height", "wave_direction"])
            fc, f2 = await fetch_field(cur_models, bbox, res, st, self.name, ["current_speed", "current_direction"]) if cur_models else (None, [])
            failures = f1 + f2
            if fd and fc:
                fd.by_model.update(fc.by_model)
                fd.models.update(fc.models)
                fd.provenance.update(fc.provenance)
            out = RetrievalOutput(mode="field", models_used=list(fd.by_model) if fd else [],
                                  models_failed=sorted({f.source_id for f in failures}), field_grid=field_summary(fd))
            prior = st.typed.get(self.name + ":field")
            if prior and fd and tiebreak:
                prior.by_model.update(fd.by_model); prior.models.update(fd.models); prior.provenance.update(fd.provenance)
                fd = prior
            st.typed[self.name + ":field"] = fd
            ok = fd is not None and any("wave_height" in v for v in fd.by_model.values())
            status = AgentStatus.SUCCEEDED if ok and not failures else AgentStatus.PARTIAL if ok else AgentStatus.FAILED
            return AgentOutcome(status=status, summary=f"gridded fields from {len(out.models_used)} model(s)",
                                output=out, typed=fd, sources=out.models_used, tools=[f"{m}.points" for m in out.models_used],
                                failures=failures, confidence=None)

        samples = geo.samples
        ids, pts = [s.id for s in samples], [s.point for s in samples]
        wd, f1 = await fetch_points(wave_models, ids, pts, st, self.name, WAVE_VARS)
        failures += f1
        if cur_models:
            cd, f2 = await fetch_points(cur_models, ids, pts, st, self.name, CURRENT_VARS)
            failures += f2
            wd.by_model.update(cd.by_model)
            wd.models.update(cd.models)
        st.stage("NORMALIZATION", "Normalising units (m, s, km/h, °C) and UTC timestamps")
        window = (u.time_window.start, u.time_window.end)
        out = summarize_points(wd, window, WAVE_VARS + CURRENT_VARS)
        out.models_failed = sorted({f.source_id for f in failures})
        prior = st.typed.get(self.name)
        if prior is not None and tiebreak:
            prior.by_model.update(wd.by_model)
            prior.models.update(wd.models)
            wd = prior
            merged = summarize_points(wd, window, WAVE_VARS + CURRENT_VARS)
            merged.models_failed = out.models_failed
            out = merged
        st.typed[self.name] = wd
        waves = [s for s in out.summaries if s.variable == "wave_height" and s.worst is not None]
        if waves:
            spread = max(s.worst for s in waves) - min(s.worst for s in waves)
            summ = (f"Hs worst {max(s.worst for s in waves):.2f} m across {len(waves)} model(s)"
                    + (f" (spread {spread:.2f} m)" if len(waves) > 1 else ""))
        else:
            summ = "no wave data available"
        status = (AgentStatus.SUCCEEDED if waves and not failures else AgentStatus.PARTIAL if waves else AgentStatus.FAILED)
        return AgentOutcome(status=status, summary=summ, output=out, typed=wd, sources=out.models_used,
                            tools=[f"{m}.points" for m in out.models_used], failures=failures,
                            confidence=None, warnings=[f.reason for f in failures][:4])
