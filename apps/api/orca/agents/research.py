"""Agent 12 — Research / Analyst agent.

Defines comparison periods, computes changes (with Welch t-tests), linear
trends, lagged SST–chlorophyll correlation, and evaluates physically
motivated hypotheses against the evidence. Output is labelled
OBSERVATION / CORRELATION / HYPOTHESIS / CONCLUSION; correlation is never
reported as causation.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import AgentStatus
from ..core.schemas.provenance import TimeSeries
from ..reasoning import research as rs
from .base import Agent, AgentOutcome, RunState


class Finding(BaseModel):
    epistemic: str               # OBSERVATION | CORRELATION | HYPOTHESIS | CONCLUSION
    text: str
    variable: Optional[str] = None
    stats: dict = Field(default_factory=dict)
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)
    status: Optional[str] = None


class ResearchOutput(BaseModel):
    region: str
    current_period: str
    previous_period: str
    target_variable: str
    findings: list[Finding] = Field(default_factory=list)
    period_stats: dict[str, dict] = Field(default_factory=dict)
    correlation: Optional[dict] = None
    data_gaps: list[str] = Field(default_factory=list)


class ResearchAgent(Agent):
    name = "research"
    title = "Research & Analytics Agent"
    responsibility = "Period comparison, trends, correlation and hypothesis evaluation with explicit epistemic labels"
    tools = ["stats.welch_ttest", "stats.linear_trend", "stats.lagged_pearson", "hypothesis.evaluate_rules"]
    consumes = ["satellite:series", "weather:history", "geospatial"]
    output_model = ResearchOutput

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        u = st.bb.understanding
        geo = st.typed.get("geospatial")
        series: dict[str, TimeSeries] = dict(st.typed.get("satellite:series") or {})
        hist = st.typed.get("weather:history")
        if hist and hist.by_model:
            sid, per_pt = next(iter(hist.by_model.items()))
            ws = per_pt[0].get("wind_speed")
            if ws:
                # hourly → daily means
                acc: dict = {}
                for t, v in zip(ws.times, ws.values):
                    if v is not None:
                        acc.setdefault(t.replace(hour=12, minute=0, second=0, microsecond=0), []).append(v)
                days = sorted(acc)
                series["wind_speed"] = TimeSeries(variable="wind_speed", units="km/h", location=ws.location, times=days,
                                                  values=[sum(acc[d]) / len(acc[d]) for d in days], provenance=ws.provenance)
        cur = (u.time_window.start, u.time_window.end)
        prev = (u.comparison_window.start, u.comparison_window.end) if u.comparison_window else (cur[0] - (cur[1] - cur[0]), cur[0])
        target = "chlorophyll" if ("chlorophyll" in u.variables or "productivity" in st.bb.request.text.lower()
                                   or "fish" in st.bb.request.text.lower()) else ("sst" if "sst" in u.variables else "chlorophyll")
        region = geo.origin_place.name if geo and geo.origin_place else "region"
        out = ResearchOutput(region=region, current_period=f"{cur[0]:%d %b}–{cur[1]:%d %b %Y}",
                             previous_period=f"{prev[0]:%d %b}–{prev[1]:%d %b %Y}", target_variable=target)
        st.stage("CORRELATION", "Computing period statistics, trends and correlations")
        stats = {}
        for var in ("chlorophyll", "sst", "sst_anomaly", "wind_speed"):
            s = rs.period_stats(series.get(var), cur, prev)
            stats[var] = s
            if s is None:
                out.data_gaps.append(f"{var}: no data")
                continue
            out.period_stats[var] = {k: getattr(s, k) for k in ("current_mean", "previous_mean", "delta", "pct_change",
                                                                "p_value", "slope_per_day", "n_current", "n_previous", "significant", "units", "source")}
            if s.delta is not None:
                out.findings.append(Finding(epistemic="OBSERVATION", variable=var, text=rs.summarize_change(s),
                                            stats=out.period_stats[var]))
                st.tool(self.name, "stats.welch_ttest", rs.summarize_change(s)[:140])
        corr = rs.correlate(series.get("sst"), series.get("chlorophyll"))
        if corr and corr.r is not None:
            out.correlation = corr.__dict__
            strength = "weak" if abs(corr.r) < 0.3 else "moderate" if abs(corr.r) < 0.6 else "strong"
            out.findings.append(Finding(
                epistemic="CORRELATION", variable="sst~chlorophyll",
                text=(f"Daily SST and chlorophyll-a show a {strength} {'negative' if corr.r < 0 else 'positive'} association "
                      f"(Pearson r = {corr.r:.2f}, p = {rs.fmt_p(corr.p_value)}, n = {corr.n} days; strongest at lag "
                      f"{corr.best_lag_days} d, r = {corr.best_lag_r:.2f}). Association does not establish causation."),
                stats=out.correlation))
            st.tool(self.name, "stats.lagged_pearson", f"r={corr.r:.2f}, best lag {corr.best_lag_days} d")
        elif corr:
            out.data_gaps.append(f"SST–chlorophyll correlation not computed (only {corr.n} overlapping days)")
        month = cur[1].month
        west = bool(geo and geo.primary and geo.primary.point.lon < 77.5)
        if stats.get(target) is None or stats[target].delta is None:
            hyps = []
            out.data_gaps.append(f"hypotheses not evaluated: no {target} observations for the comparison periods")
        else:
            hyps = rs.hypotheses(target, stats, corr, month, west, chl_gapfilled=True)
        st.tool(self.name, "hypothesis.evaluate_rules", f"{len(hyps)} hypotheses evaluated")
        for h in hyps:
            out.findings.append(Finding(epistemic="HYPOTHESIS", text=f"{h.id}: {h.statement}", supporting=h.supporting,
                                        contradicting=h.contradicting, status=h.status))
        tstat = stats.get(target)
        best = next((h for h in hyps if h.status in ("consistent", "partially consistent")), None)
        concl = []
        q = st.bb.request.text.lower()
        asked_down = any(w in q for w in ("decline", "declin", "decrease", "drop", "lower", "fell", "reduc", "कमी", "घट"))
        asked_up = any(w in q for w in ("increase", "rise", "rose", "higher", "grew", "warm"))
        if tstat and tstat.delta is not None and ((asked_down and tstat.delta > 0) or (asked_up and tstat.delta < 0)):
            concl.append(f"The premise of the question is not supported by the data: {target} "
                         f"{'increased' if tstat.delta > 0 else 'decreased'} rather than "
                         f"{'declined' if asked_down else 'increased'}.")
            out.findings.append(Finding(epistemic="OBSERVATION", variable=target,
                                        text=f"Premise check: the observed change in {target} is opposite to the one assumed in the question."))
        if tstat and tstat.delta is not None:
            concl.append(f"{target} {'declined' if tstat.delta < 0 else 'increased'} by {abs(tstat.pct_change or 0):.1f} % between "
                         f"the two periods ({'significant' if tstat.significant else 'not significant'} at α = 0.05).")
        else:
            concl.append(f"Insufficient {target} data to establish a change.")
        if best:
            concl.append(f"The evidence is most consistent with {best.id} ({best.status}); this is a hypothesis, not a demonstrated cause.")
        else:
            concl.append("No hypothesis is clearly supported by the available evidence.")
        concl.append("Establishing causation would require in-situ profiles (mixed-layer depth, nutrients) and longer records.")
        out.findings.append(Finding(epistemic="CONCLUSION", text=" ".join(concl)))
        st.typed[self.name] = out
        n_obs = sum(1 for f in out.findings if f.epistemic == "OBSERVATION")
        status = AgentStatus.SUCCEEDED if n_obs >= 2 else AgentStatus.PARTIAL if n_obs else AgentStatus.FAILED
        return AgentOutcome(status=status, summary=concl[0], output=out, typed=out, tools=self.tools,
                            sources=sorted({s.source for s in stats.values() if s}))
