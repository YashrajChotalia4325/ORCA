"""Agent 10 — Communication & Localisation agent.

Renders the *same* verified result for different audiences (fisherman,
authority, researcher, operator) and languages. The scientific content is
fixed upstream; this agent only chooses presentation. Template rendering
is deterministic; optional LLM narration must pass the numeric grounding
check or it is discarded.
"""
from __future__ import annotations

from ..core.clock import fmt_ist, fmt_utc
from ..core.schemas.blackboard import LocalizedResponse, PlanTask
from ..core.schemas.common import AgentStatus, DataMode, Decision, Intent, RiskLevel, UserRole
from ..core.units import fmt, kmh_to_kn
from ..reasoning.i18n import T, t
from .base import Agent, AgentOutcome, RunState


def _val(f) -> str:
    if f.value is None:
        return f.explanation
    if f.units == "km/h":
        return f"{f.value:.0f} km/h ({kmh_to_kn(f.value):.0f} kn)"
    if f.units == "km":
        return f"{f.value:.1f} km"
    return f"{f.value:g} {f.units}"


class CommunicationAgent(Agent):
    name = "communication"
    title = "Communication & Localisation Agent"
    responsibility = "Role- and language-specific rendering of the verified result (8 Indian languages + English)"
    tools = ["i18n.templates", "llm.narrate (optional, grounding-checked)"]
    consumes = ["evidence", "hazard", "route", "fisheries", "research"]
    output_model = LocalizedResponse
    deterministic = False

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        bb = st.bb
        u = bb.understanding
        fa = bb.final_assessment
        lang = u.output_language if u.output_language in T else "en"
        role = u.role
        st.stage("EXPLANATION", f"Rendering for {role.value} in {lang}")
        risk = bb.risk
        decision = fa.decision if fa else Decision.NOT_APPLICABLE
        sections: list[dict] = []
        mode_banner = t(lang, "simulated") if st.ctx.mode == DataMode.DEMO else t(lang, "replay") if st.ctx.mode == DataMode.REPLAY else None

        # understanding
        und = [f"{u.intent.value.replace('_', ' ').title()}"]
        if u.places:
            und.append(", ".join(p.name for p in u.places[:3]))
        if u.region:
            und.append(u.region.name)
        if u.offshore_km:
            und.append(f"{u.offshore_km:g} km offshore")
        if u.time_window:
            und.append(u.time_window.label)
        und.append(u.vessel_class.value.replace("_", " "))
        sections.append({"id": "understanding", "title": t(lang, "understanding"), "items": und, "assumptions": u.assumptions})

        headline = t(lang, f"h.{decision.value}")
        summary_bits = []
        if fa:
            if u.intent in (Intent.FISHING_ZONES, Intent.RESEARCH_TREND, Intent.COMPARE_PERIODS) or decision == Decision.NOT_APPLICABLE:
                headline = fa.headline if lang == "en" else f"{t(lang, 'NOT_APPLICABLE')}: {fa.headline}"
            summary_bits.append(f"{t(lang, decision.value)} · {t(lang, 'confidence')} {fa.confidence * 100:.0f}%")
            if u.time_window:
                summary_bits.append(f"{t(lang, 'time')}: {u.time_window.label}")
        if risk:
            drivers = [f for f in risk.factors if f.id in risk.drivers]
            why = [f"{t(lang, 'f.' + f.id)}: {t(lang, 'up_to') if f.value is not None and f.threshold and f.threshold.direction == 'above' else ''} "
                   f"{_val(f)} — {t(lang, 'lvl.' + f.level.value)}".replace("  ", " ") for f in drivers]
            if decision == Decision.INSUFFICIENT_DATA and fa and fa.refusal_reason:
                why.insert(0, fa.refusal_reason)
            sections.append({"id": "why", "title": t(lang, "why"), "items": why or [t(lang, f"h.{decision.value}")],
                             "detail": fa.reasons if fa else []})
            cond = [{"factor": f.id, "label": t(lang, "f." + f.id), "value": _val(f) if f.available else "—",
                     "level": f.level.value, "level_label": t(lang, "lvl." + f.level.value),
                     "at": fmt_ist(f.at) if f.at else None, "spread": f.spread, "sources": len(f.per_source),
                     "available": f.available}
                    for f in risk.factors]
            sections.append({"id": "conditions", "title": t(lang, "conditions"), "table": cond})
        if fa:
            recs = [r.text for r in fa.recommendations]
            if lang != "en":
                loc = []
                onset = next((f.onset for f in (risk.factors if risk else []) if f.onset and f.level != RiskLevel.NOMINAL), None)
                if decision == Decision.DONT_GO:
                    loc.append(t(lang, "h.DONT_GO"))
                elif onset and decision == Decision.CAUTION:
                    loc.append(t(lang, "return_before", time=fmt_ist(onset, with_date=False)))
                loc.append(t(lang, "official_check"))
                loc.append(t(lang, "not_authority"))
                sections.append({"id": "recommendations", "title": t(lang, "recommendations"), "items": loc, "detail": recs})
            else:
                sections.append({"id": "recommendations", "title": t(lang, "recommendations"), "items": recs})
        rt = st.typed.get("route")
        if rt and rt.route:
            r = rt.route
            sections.append({"id": "route", "title": t(lang, "route"), "table": [
                {"id": o.id, "label": o.label, "distance": fmt(o.distance_km, "km"), "duration_h": o.duration_h,
                 "arrival": fmt_ist(o.arrival), "max_risk": o.max_risk, "level": o.level.value,
                 "zones": [z.name for z in o.zone_violations], "recommended": o.id == r.recommended_id} for o in r.options],
                "notes": r.notes, "algorithm": r.algorithm})
        fish = st.typed.get("fisheries")
        if fish:
            sections.append({"id": "zones", "title": t(lang, "zones"), "table": [
                {"id": z.id, "score": z.score, "distance_km": z.distance_from_origin_km, "bearing": z.bearing_from_origin_deg,
                 "sst": z.mean_sst_c, "chl": z.mean_chl_mg_m3, "front": z.max_front_gradient_c_per_km, "depth": z.depth_m,
                 "rationale": z.rationale} for z in fish.zones],
                "disclaimer": fish.disclaimer, "official": fish.official_status})
        hz = st.typed.get("hazard")
        if hz and hz["output"].stations:
            sections.append({"id": "stations", "title": t(lang, "stations"),
                             "table": [s.model_dump(mode="json") for s in hz["output"].stations]})
        res = st.typed.get("research")
        if res:
            sections.append({"id": "research", "title": t(lang, "research"),
                             "findings": [f.model_dump() for f in res.findings], "gaps": res.data_gaps})
        if fa and fa.excluded_sources:
            sections.append({"id": "gaps", "title": t(lang, "gaps"), "items": fa.excluded_sources})
        if fa:
            sections.append({"id": "caveats", "title": t(lang, "caveats"), "items": fa.caveats})

        # role-specific summary text (deterministic)
        if role == UserRole.FISHERMAN:
            summary = " · ".join(summary_bits)
        elif role == UserRole.AUTHORITY:
            summary = (f"Situation report generated {fmt_utc(st.now)} ({fmt_ist(st.now)}). " + " · ".join(summary_bits)
                       + (f". Evidence: {fa.metrics.get('evidence_items')} items from {fa.metrics.get('independent_lineages')} "
                          f"independent lineages; {fa.metrics.get('conflicts')} conflict(s)." if fa else ""))
        elif role == UserRole.RESEARCHER:
            summary = " · ".join(summary_bits) + (f". Confidence = {fa.confidence_breakdown.formula}; completeness "
                                                  f"{fa.confidence_breakdown.completeness:.2f}; weakest link: "
                                                  f"{fa.confidence_breakdown.weakest_link}." if fa and fa.confidence_breakdown else "")
        else:
            summary = " · ".join(summary_bits)
        if mode_banner:
            summary = f"[{mode_banner}] " + summary

        resp = LocalizedResponse(language=lang, role=role, headline=headline, summary=summary, sections=sections)
        # optional LLM narration (never alters sections / numbers)
        if st.ctx.llm.available and fa and u.intent not in (Intent.SOURCES, Intent.CONFLICTS):
            facts = {"decision": decision.value, "headline": fa.headline, "confidence_pct": round(fa.confidence * 100),
                     "time_window": u.time_window.label if u.time_window else None,
                     "reasons": fa.reasons[:6], "recommendations": [r.text for r in fa.recommendations[:5]],
                     "excluded_sources": fa.excluded_sources[:5], "mode": st.ctx.mode.value}
            st.tool(self.name, "llm.narrate", f"requesting narration ({st.ctx.llm.model})")
            nr = await st.ctx.llm.narrate(facts, role.value, lang)
            bb.llm_usage["input_tokens"] = bb.llm_usage.get("input_tokens", 0) + nr.input_tokens
            bb.llm_usage["output_tokens"] = bb.llm_usage.get("output_tokens", 0) + nr.output_tokens
            if nr.data:
                resp.headline = f"{t(lang, decision.value)} — {nr.data['headline']}" if decision != Decision.NOT_APPLICABLE else nr.data["headline"]
                resp.summary = (f"[{mode_banner}] " if mode_banner else "") + nr.data["summary"]
                resp.sections.insert(1, {"id": "narrative", "title": "", "items": nr.data.get("bullets", [])})
                resp.renderer = f"llm({nr.model}) + templates"
            resp.grounding_check = {"attempted": True, "passed": bool(nr.data), "error": nr.error, "notes": nr.notes}
            st.tool(self.name, "llm.narrate", "narration accepted (grounding passed)" if nr.data else f"narration rejected: {nr.error}")
        bb.response = resp
        st.stage("RESPONSE", "Response ready")
        return AgentOutcome(status=AgentStatus.SUCCEEDED, summary=f"{role.value} / {lang} via {resp.renderer}",
                            output=resp, typed=resp, tools=["i18n.templates"] + (["llm.narrate"] if resp.grounding_check else []))
