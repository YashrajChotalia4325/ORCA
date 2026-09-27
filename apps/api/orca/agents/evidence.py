"""Agent 9 — Evidence & Verification agent.

For every important conclusion: which sources support it, when they were
retrieved, whether they are independent, whether they agree, what kind of
data they are (observed / analysis / forecast / advisory / reference), how
confident ORCA can be (documented formula) and what the weakest link is.
Detects and explains conflicts, lists excluded sources, and assembles the
final decision package with recommendations and caveats.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from ..core import confidence as cf
from ..core import spatial
from ..core.clock import fmt_ist, parse_utc
from ..core.risk import FACTOR_META, THRESHOLDS, level_for
from ..core.schemas.assessment import (Claim, ConfidenceBreakdown, EvidenceItem, FinalAssessment, Recommendation,
                                       RiskFactor)
from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import (AgentStatus, AuthorityTier, DataKind, DataMode, Decision, FreshnessStatus, GeoPoint,
                                   Intent, RiskLevel)
from ..core.schemas.provenance import Freshness, Provenance
from ..reasoning import conflicts as cx
from .base import Agent, AgentOutcome, RunState

HEADLINES = {
    Decision.GO: "GO — conditions within configured limits",
    Decision.CAUTION: "CAUTION — hazardous conditions possible",
    Decision.DONT_GO: "DON'T GO — dangerous conditions expected",
    Decision.INSUFFICIENT_DATA: "NO RELIABLE ASSESSMENT — critical data unavailable",
    Decision.NOT_APPLICABLE: "Analysis complete",
}
COMPLETENESS_WEIGHTS = {"wind_speed": 2, "wave_height": 2, "wind_gusts": 1, "current_speed": 1, "precipitation": 1,
                        "cape": 1, "cyclone_distance": 1, "official_advisory": 1, "visibility": 0.5}


def _stub_prov(source: str, source_id: str, kind: DataKind, st: RunState, tier=AuthorityTier.SCIENTIFIC_COMPILATION,
               dataset: str = "", note: str = "") -> Provenance:
    return Provenance(source=source, source_id=source_id, organization=source, authority_tier=tier, dataset=dataset,
                      variable="", kind=kind, retrieval_timestamp=st.now, mode=st.ctx.mode,
                      freshness=Freshness(status=FreshnessStatus.STATIC, label="static reference", factor=0.9),
                      confidence=0.85, notes=[note] if note else [])


class EvidenceAgent(Agent):
    name = "evidence"
    title = "Evidence & Verification Agent"
    responsibility = ("Claim extraction, per-source evidence with provenance, independence & agreement analysis, conflict "
                      "detection, documented confidence, final decision package")
    tools = ["evidence.build_claims", "confidence.claim", "confidence.assessment", "conflicts.detect", "provenance.verify"]
    consumes = ["hazard", "ocean", "weather", "satellite", "advisory", "fisheries", "geospatial", "route", "research"]
    output_model = None

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        bb = st.bb
        u = bb.understanding
        if task.params.get("reuse_previous") and st.previous is not None:
            p = st.previous
            bb.claims, bb.evidence, bb.conflicts = p.claims, p.evidence, p.conflicts
            bb.final_assessment, bb.risk, bb.route, bb.failures = p.final_assessment, p.risk, p.route, p.failures
            bb.map = p.map
            st.stage("VERIFICATION", f"Re-using verified evidence from {p.query_id}")
            return AgentOutcome(status=AgentStatus.SUCCEEDED,
                                summary=f"re-used {len(p.claims)} claim(s), {len(p.conflicts)} conflict(s) from {p.query_id}",
                                confidence=p.final_assessment.confidence if p.final_assessment else None,
                                tools=["memory.previous_blackboard"])

        reg = st.ctx.registry
        auth = reg.authority_map()
        auth.update({"marine_regions": 0.85, "orca_curated": 0.5, "orca_derived": 0.7})
        items: list[EvidenceItem] = []
        claims: list[Claim] = []
        n = [0]

        def add_item(claim_id: str, **kw) -> EvidenceItem:
            n[0] += 1
            it = EvidenceItem(id=f"E{n[0]}", claim_id=claim_id, **kw)
            it.weight = cf.item_weight(it.authority, it.freshness, it.spatial, it.temporal)
            items.append(it)
            return it

        st.stage("VERIFICATION", "Verifying claims against source evidence")
        hz = st.typed.get("hazard")
        assessment = hz["assessment"] if hz else None
        inputs = hz["inputs"] if hz else {}
        fields = {**(getattr(st.typed.get("ocean:field"), "provenance", None) or {}),
                  **(getattr(st.typed.get("weather:field"), "provenance", None) or {})}

        # ------------------------------------------------------------------ risk factor claims
        if assessment:
            vessel = assessment.vessel_class
            for f in assessment.factors:
                if not f.available:
                    continue
                cid = f"C_{f.id}"
                claim = Claim(id=cid, text=self._factor_text(f, vessel), category="risk", factor_id=f.id, level=f.level,
                              epistemic="FORECAST" if f.id not in ("boundary_distance", "official_advisory", "cyclone_distance") else "OBSERVATION",
                              map_focus=f.location, time_focus=f.at)
                fi = inputs.get(f.id)
                th = THRESHOLDS[vessel].get(f.id)
                if fi and th:
                    for src in fi.sources:
                        vals = [s for s in src.samples if s.value is not None]
                        if not vals:
                            continue
                        w = (max(vals, key=lambda s: s.value) if th.direction == "above" else min(vals, key=lambda s: s.value))
                        prov: Optional[Provenance] = src.meta.get("provenance") or fields.get(src.source_id, {}).get(
                            {"wind_speed": "wind_speed"}.get(f.id, f.id))
                        if prov is None:
                            prov = _stub_prov(src.source, src.source_id, src.kind, st)
                        lvl = level_for(w.value, th)
                        lead_h = ((w.time - prov.issued_at).total_seconds() / 3600) if (w.time and prov.issued_at) else None
                        age_h = ((st.now - prov.timestamp).total_seconds() / 3600) if prov.timestamp else 0.0
                        it = add_item(cid, source=src.source, source_id=src.source_id, kind=src.kind, variable=f.id,
                                      value=round(w.value, 2), units=th.units, valid_time=w.time, location=w.location,
                                      provenance=prov, supports=(lvl == f.level),
                                      authority=auth.get(src.source_id, 0.8), freshness=prov.freshness.factor or 0.9,
                                      spatial=cf.spatial_factor(src.meta.get("grid_distance_km"), prov.spatial_resolution),
                                      temporal=cf.temporal_factor(src.kind, lead_h=lead_h, age_h=age_h),
                                      lineage=src.meta.get("lineage", src.source_id))
                        claim.evidence_ids.append(it.id)
                elif f.id == "cyclone_distance":
                    adv = st.typed.get("advisory")
                    if adv and adv.gdacs_provenance:
                        it = add_item(cid, source="GDACS", source_id="gdacs", kind=DataKind.ADVISORY, variable="cyclone",
                                      value_text=f.explanation, provenance=adv.gdacs_provenance, supports=True,
                                      authority=auth.get("gdacs", 0.9), freshness=adv.gdacs_provenance.freshness.factor,
                                      spatial=1.0, temporal=1.0, lineage="gdacs")
                        claim.evidence_ids.append(it.id)
                elif f.id == "official_advisory":
                    adv = st.typed.get("advisory")
                    for o in (adv.official if adv else []):
                        prov = o.provenance or _stub_prov(o.source, o.source.lower(), DataKind.ADVISORY, st, AuthorityTier.NATIONAL_OFFICIAL)
                        it = add_item(cid, source=o.source, source_id=o.source.lower(), kind=DataKind.ADVISORY,
                                      variable="official_advisory", value_text=f"{o.title}: {o.text}"[:240], provenance=prov,
                                      supports=True, authority=0.95, freshness=prov.freshness.factor or 1.0, spatial=1.0,
                                      temporal=1.0, lineage=o.source.lower())
                        claim.evidence_ids.append(it.id)
                claims.append(claim)

        # ------------------------------------------------------------------ geospatial claims
        geo = st.typed.get("geospatial")
        if geo and geo.primary:
            pc = geo.primary
            cid = "C_location"
            txt = f"Assessment point {pc.point.lat:.3f}°N {pc.point.lon:.3f}°E ({pc.resolved_from}) lies " + \
                  (f"inside the {pc.eez}" if pc.eez else "outside the modelled EEZ polygons") + \
                  (f", {pc.distance_to_coast_km:.1f} km from the coast" if pc.distance_to_coast_km is not None else "") + \
                  (f", water depth {abs(pc.depth_m):.0f} m (GEBCO)" if pc.depth_m is not None and pc.depth_m < 0 else "") + "."
            claim = Claim(id=cid, text=txt, category="geospatial", epistemic="OBSERVATION", map_focus=pc.point)
            it = add_item(cid, source="Marine Regions EEZ v12 + Natural Earth coastline", source_id="marine_regions",
                          kind=DataKind.REFERENCE, variable="eez", value_text=pc.eez or "none",
                          provenance=_stub_prov("Marine Regions (VLIZ)", "marine_regions", DataKind.REFERENCE, st,
                                                dataset="eez_v12", note="compiled boundaries; not legal delimitation"),
                          supports=True, authority=0.85, freshness=0.9, spatial=1.0, temporal=1.0, lineage="marine_regions")
            claim.evidence_ids.append(it.id)
            claims.append(claim)
            for z in pc.zones[:6]:
                if z.kind not in ("mpa", "restricted", "maritime_boundary", "geofence"):
                    continue
                cid = f"C_zone_{z.zone_id}"
                txt = (f"Point is INSIDE {z.name}." if z.inside else
                       f"{z.name} is {z.distance_km:.1f} km ({z.distance_nm:.1f} nm) away" +
                       (f", bearing {z.bearing_deg:.0f}° {spatial.compass(z.bearing_deg)}" if z.bearing_deg is not None else "") + ".")
                if z.approximate:
                    txt += " (approximate outline)"
                claim = Claim(id=cid, text=txt, category="geospatial", epistemic="OBSERVATION",
                              map_focus=z.nearest_point or pc.point)
                sid = "orca_curated" if z.approximate else "marine_regions"
                it = add_item(cid, source=z.source or sid, source_id=sid, kind=DataKind.REFERENCE, variable=z.kind,
                              value=z.distance_km, units="km",
                              provenance=_stub_prov(z.source or sid, sid, DataKind.REFERENCE, st,
                                                    AuthorityTier.ORCA_CURATED if z.approximate else AuthorityTier.SCIENTIFIC_COMPILATION),
                              supports=True, authority=auth.get(sid, 0.7), freshness=0.9, spatial=1.0, temporal=1.0, lineage=sid)
                claim.evidence_ids.append(it.id)
                claims.append(claim)

        # ------------------------------------------------------------------ satellite context
        sat = st.typed.get("satellite")
        if sat and getattr(sat, "point_values", None):
            for pv in sat.point_values:
                cid = f"C_sat_{pv.variable}"
                label = {"sst": "Satellite SST", "sst_anomaly": "SST anomaly", "chlorophyll": "Chlorophyll-a"}[pv.variable]
                age_h = (st.now - pv.valid_time).total_seconds() / 3600 if pv.valid_time else None
                claim = Claim(id=cid, category="environment", epistemic="OBSERVATION", map_focus=pv.grid_location,
                              time_focus=pv.valid_time,
                              text=f"{label} {pv.value:+.2f} {pv.units}" if pv.variable == "sst_anomaly" else
                              f"{label} {pv.value:.2f} {pv.units} near the assessment point (product of {pv.valid_time:%d %b %Y}, "
                              f"~{age_h:.0f} h old — daily satellite analysis, not a real-time observation)")
                it = add_item(cid, source=pv.provenance.source, source_id="noaa_coastwatch", kind=DataKind.ANALYSIS,
                              variable=pv.variable, value=round(pv.value, 3), units=pv.units, valid_time=pv.valid_time,
                              location=pv.grid_location, provenance=pv.provenance, supports=True,
                              authority=auth.get("noaa_coastwatch", 0.88), freshness=pv.provenance.freshness.factor,
                              spatial=cf.spatial_factor(spatial.distance_km(pv.location, pv.grid_location) if pv.grid_location else 0,
                                                        pv.provenance.spatial_resolution),
                              temporal=cf.temporal_factor(DataKind.ANALYSIS, age_h=age_h, validity_h=48), lineage="noaa_nesdis")
                claim.evidence_ids.append(it.id)
                claims.append(claim)

        # ------------------------------------------------------------------ fisheries
        fish = st.typed.get("fisheries")
        if fish:
            for z in fish.zones[:3]:
                cid = f"C_{z.id}"
                claim = Claim(id=cid, category="fisheries", epistemic="HYPOTHESIS", map_focus=z.centroid,
                              text=(f"{z.id}: oceanographic conditions often associated with fish aggregation "
                                    f"(score {z.score:.2f}) {z.distance_from_origin_km:.0f} km "
                                    f"{spatial.compass(z.bearing_from_origin_deg)} — " + "; ".join(z.rationale[:3])
                                    + ". Probabilistic indicator; presence of fish is not implied."))
                for key, prov in (("sst", fish.sst_provenance), ("chlorophyll", fish.chl_provenance)):
                    if prov is None:
                        continue
                    age_h = (st.now - prov.timestamp).total_seconds() / 3600 if prov.timestamp else None
                    it = add_item(cid, source=prov.source, source_id="noaa_coastwatch", kind=DataKind.ANALYSIS,
                                  variable=key, value=z.max_front_gradient_c_per_km if key == "sst" else z.mean_chl_mg_m3,
                                  units="°C/km" if key == "sst" else "mg/m³", valid_time=prov.timestamp, location=z.centroid,
                                  provenance=prov, supports=True, authority=0.7, freshness=prov.freshness.factor,
                                  spatial=cf.spatial_factor(0, prov.spatial_resolution),
                                  temporal=cf.temporal_factor(DataKind.ANALYSIS, age_h=age_h, validity_h=48),
                                  lineage=f"noaa_{key}")
                    claim.evidence_ids.append(it.id)
                claims.append(claim)
            if fish.official_available:
                for i, f in enumerate(fish.official_pfz[:3]):
                    cid = f"C_pfz_{i}"
                    props = f.get("properties", {})
                    claim = Claim(id=cid, category="fisheries", epistemic="OBSERVATION",
                                  text=f"INCOIS PFZ advisory: {props.get('description') or props.get('name') or 'PFZ sector'}")
                    prov = fish.pfz_provenance or _stub_prov("INCOIS", "incois", DataKind.ADVISORY, st, AuthorityTier.NATIONAL_OFFICIAL)
                    it = add_item(cid, source="INCOIS", source_id="incois", kind=DataKind.ADVISORY, variable="pfz",
                                  value_text=str(props)[:200], provenance=prov, supports=True, authority=0.95,
                                  freshness=prov.freshness.factor or 1.0, spatial=1.0, temporal=1.0, lineage="incois")
                    claim.evidence_ids.append(it.id)
                    claims.append(claim)

        # ------------------------------------------------------------------ route
        rt = st.typed.get("route")
        if rt and rt.route:
            r = rt.route
            rec = next(o for o in r.options if o.id == r.recommended_id)
            short = next((o for o in r.options if o.id == "shortest"), None)
            txt = (f"Recommended route {r.origin_name} → {r.destination_name}: {rec.distance_km:.0f} km "
                   f"({rec.distance_nm:.0f} nm), {rec.duration_h:.1f} h at {r.speed_kn:g} kn, max segment risk {rec.max_risk:.2f}")
            if short and short.id != rec.id:
                txt += f" vs shortest {short.distance_km:.0f} km with max risk {short.max_risk:.2f}"
            claims.append(Claim(id="C_route", text=txt + ".", category="route", epistemic="FORECAST",
                                map_focus=r.origin, evidence_ids=[i.id for i in items if i.claim_id in ("C_wave_height", "C_wind_speed")]))
            for opt in r.options:
                for z in opt.zone_violations:
                    claims.append(Claim(id=f"C_route_zone_{opt.id}_{z.zone_id}", category="geospatial", epistemic="OBSERVATION",
                                        text=f"{opt.label} route enters {z.name}: {z.note}", map_focus=z.nearest_point))

        # ------------------------------------------------------------------ research
        res = st.typed.get("research")
        if res:
            ser_prov = (st.typed.get("satellite") and getattr(st.typed.get("satellite"), "series_provenance", {})) or {}
            for i, fnd in enumerate(res.findings):
                cid = f"C_research_{i}"
                claim = Claim(id=cid, text=fnd.text, category="research", epistemic=fnd.epistemic)
                if fnd.epistemic == "OBSERVATION" and fnd.variable in ser_prov:
                    prov = ser_prov[fnd.variable]
                    it = add_item(cid, source=prov.source, source_id="noaa_coastwatch", kind=DataKind.HISTORICAL,
                                  variable=fnd.variable, value=fnd.stats.get("delta"), units=fnd.stats.get("units", ""),
                                  valid_time=prov.timestamp, provenance=prov, supports=True, authority=0.88,
                                  freshness=prov.freshness.factor, spatial=cf.spatial_factor(0, prov.spatial_resolution),
                                  temporal=1.0, lineage=f"noaa_{fnd.variable}")
                    claim.evidence_ids.append(it.id)
                claims.append(claim)

        # ------------------------------------------------------------------ conflicts
        st.stage("CONFLICTS", "Detecting disagreement between sources")
        conflicts = []
        if assessment:
            crit = {f.id for f in assessment.factors if f.critical}
            conflicts += cx.factor_conflicts(assessment.factors, auth, crit)
            adv = st.typed.get("advisory")
            if adv and adv.official_available and adv.official:
                model_lvls = [f.level for f in assessment.factors if f.id in ("wave_height", "wind_speed", "wind_gusts") and f.available]
                ml = (RiskLevel.DANGER if RiskLevel.DANGER in model_lvls else RiskLevel.CAUTION if RiskLevel.CAUTION in model_lvls
                      else RiskLevel.NOMINAL)
                c = cx.advisory_vs_models(adv.official_level, "/".join(sorted({o.source for o in adv.official})), ml,
                                          "; ".join(o.title for o in adv.official))
                if c:
                    conflicts.append(c)
        sst_sat = next((pv for pv in (sat.point_values if sat and getattr(sat, "point_values", None) else []) if pv.variable == "sst"), None)
        ocean = st.typed.get("ocean")
        if sst_sat and ocean and getattr(ocean, "by_model", None) and "om_smoc" in ocean.by_model:
            ts = ocean.by_model["om_smoc"][0].get("sst_model")
            if ts:
                mv = ts.at(sst_sat.valid_time) if sst_sat.valid_time else None
                if mv is None:
                    mv = next((v for v in ts.values if v is not None), None)
                c = cx.sst_satellite_vs_model(sst_sat.value, "NOAA blended SST (satellite)", mv, "SMOC model SST",
                                              sst_sat.valid_time, None)
                if c:
                    conflicts.append(c)
        for c in conflicts:
            st.emit("conflict", c.description, agent=self.name, severity=c.severity, variable=c.variable)

        # ------------------------------------------------------------------ confidence
        st.stage("CONFIDENCE", "Computing evidence-based confidence")
        by_claim: dict[str, list[EvidenceItem]] = {}
        for it in items:
            by_claim.setdefault(it.claim_id, []).append(it)
        for c in claims:
            ev = by_claim.get(c.id, [])
            c.n_sources = len({e.lineage for e in ev})
            c.n_supporting = sum(1 for e in ev if e.supports is not False)
            c.n_contradicting = sum(1 for e in ev if e.supports is False)
            if ev:
                c.confidence = cf.claim_confidence(ev, c.level.value if c.level else None)
        completeness = 1.0
        notes = []
        if assessment:
            expected = {k: v for k, v in COMPLETENESS_WEIGHTS.items() if k in {f.id for f in assessment.factors}}
            got = sum(w for k, w in expected.items() if any(f.id == k and f.available for f in assessment.factors))
            completeness = round(got / sum(expected.values()), 3) if expected else 1.0
            missing = [FACTOR_META[k][0] for k in expected if not any(f.id == k and f.available for f in assessment.factors)]
            if missing:
                notes.append("missing: " + ", ".join(missing))
        drivers = set(assessment.drivers) if assessment else set()
        scored = [(c.confidence, (c.factor_id in drivers)) for c in claims if c.confidence and c.category in ("risk", "route")] or \
                 [(c.confidence, False) for c in claims if c.confidence]
        coverage = 1.0
        if assessment:
            covs = []
            for fid, fam in (("wave_height", "ocean"), ("wind_speed", "weather")):
                used = len(next((f.per_source for f in assessment.factors if f.id == fid), []))
                expected = 3 + (1 if any(t.agent == fam and t.params.get("tiebreaker") for t in bb.plan.tasks) else 0)
                covs.append(min(1.0, used / expected))
            coverage = sum(covs) / len(covs)
            if coverage < 1.0:
                notes.append(f"only {coverage * 100:.0f}% of queried critical sources responded")
        overall = cf.assessment_confidence(scored, completeness, notes, coverage=coverage)
        if assessment and assessment.decision == Decision.INSUFFICIENT_DATA:
            overall.value = 0.0
            overall.notes.append("no decision issued (INSUFFICIENT DATA) — confidence reported as 0")
        dr = [c for c in conflicts if c.decision_relevant]
        if dr:
            overall.notes.append(f"{len(dr)} decision-relevant conflict(s) — reflected via agreement term")

        # ------------------------------------------------------------------ final assessment
        st.stage("DECISION", "Assembling decision package")
        decision = assessment.decision if assessment else Decision.NOT_APPLICABLE
        fa = FinalAssessment(decision=decision, headline=HEADLINES[decision], reasons=[], confidence=round(overall.value, 3),
                             confidence_breakdown=overall)
        if assessment:
            for fid in assessment.drivers:
                f = next((x for x in assessment.factors if x.id == fid), None)
                if f:
                    fa.reasons.append(f"{f.label}: {f.explanation}")
            fa.reasons += [r for r in assessment.rules_fired] + assessment.conservative_adjustments
            if decision == Decision.INSUFFICIENT_DATA:
                miss = ", ".join(FACTOR_META[m][0].lower() for m in assessment.missing_critical)
                fa.refusal_reason = (f"Unable to provide a reliable safety assessment because current {miss} data is unavailable. "
                                     "ORCA will not infer safety from partial information.")
        for c in dr:
            fa.reasons.append(f"Sources disagree — {c.description}. {c.resolution}")
        fa.recommendations = self._recommendations(st, assessment, conflicts)
        fa.excluded_sources = [f"{f.source} — {f.status}: {f.reason}" + (f" → {f.impact}" if f.impact else "") for f in bb.failures]
        fa.caveats = self._caveats(st, assessment)
        fa.metrics = {"claims": len(claims), "evidence_items": len(items), "conflicts": len(conflicts),
                      "decision_relevant_conflicts": len(dr), "independent_lineages": len({i.lineage for i in items}),
                      "completeness": completeness, "risk_index": assessment.risk_index if assessment else None}
        if u.intent in (Intent.FISHING_ZONES,) and fish:
            fa.headline = (f"{len(fish.zones)} candidate productive zone(s) identified" if fish.zones else
                           "No candidate productive zones met the indicator threshold")
            if assessment:
                fa.headline += f" · sea state {decision.value.replace('_', ' ')}"
        if u.intent in (Intent.RESEARCH_TREND, Intent.COMPARE_PERIODS) and res:
            concl = next((f.text for f in res.findings if f.epistemic == "CONCLUSION"), "")
            fa.headline = "Research analysis: " + (concl.split(". ")[0].rstrip(".") if concl else "complete")
            fa.decision = Decision.NOT_APPLICABLE
        bb.claims, bb.evidence, bb.conflicts, bb.final_assessment = claims, items, conflicts, fa
        st.typed[self.name] = fa
        for c in claims[:12]:
            st.emit("evidence", c.text[:160], agent=self.name, claim_id=c.id,
                    confidence=c.confidence.value if c.confidence else None, sources=c.n_sources)
        summ = (f"{len(claims)} claims · {len(items)} evidence items · {len(conflicts)} conflict(s) · "
                f"confidence {overall.value * 100:.0f}%")
        return AgentOutcome(status=AgentStatus.SUCCEEDED, summary=summ, confidence=overall.value, tools=self.tools)

    # ------------------------------------------------------------------ text helpers
    @staticmethod
    def _factor_text(f: RiskFactor, vessel: str) -> str:
        vc = vessel.replace("_", " ")
        when = f" around {fmt_ist(f.at)}" if f.at else ""
        if f.id == "cyclone_distance":
            if f.value is None:
                return f.explanation
            if f.value == 0:
                return f"The assessment area lies INSIDE an active tropical cyclone's wind field ({f.level.value})."
            return f"Nearest active tropical cyclone {f.value:.0f} km away ({f.level.value})."
        if f.id == "official_advisory":
            return f"Official warnings: {f.explanation} ({f.level.value})."
        if f.id == "boundary_distance":
            return f"International maritime boundary {f.value:.1f} km away ({f.level.value} for {vc})."
        if f.value is None:
            return f"{f.label}: no data."
        ext = "minimum" if f.threshold and f.threshold.direction == "below" else "up to"
        return (f"{f.label} {ext} {f.value:g} {f.units}{when} — {f.level.value} for {vc}"
                + (f" (sources spread {f.spread:g} {f.units})" if f.spread else "") + ".")

    @staticmethod
    def _recommendations(st: RunState, a, conflicts) -> list[Recommendation]:
        recs: list[Recommendation] = []
        u = st.bb.understanding

        def add(p: int, t: str, basis: list[str] | None = None):
            recs.append(Recommendation(priority=p, text=t, basis=basis or []))

        if a is None:
            return recs
        fac = {f.id: f for f in a.factors}
        if a.decision == Decision.INSUFFICIENT_DATA:
            add(1, "Do not rely on ORCA for this decision — consult IMD / INCOIS bulletins and the harbour authority directly.",
                a.missing_critical)
        if a.decision == Decision.DONT_GO:
            add(1, f"Do not put to sea during {u.time_window.label}.", a.drivers)
        onsets = [f.onset for f in a.factors if f.onset and f.level in (RiskLevel.CAUTION, RiskLevel.DANGER)]
        if onsets and a.decision == Decision.CAUTION:
            first = min(onsets)
            if st.typed.get("route") is not None and getattr(st.typed.get("route"), "route", None):
                add(1, f"Caution-level conditions are expected on the route from about {fmt_ist(first)} — see the "
                       "segment table and consider adjusting departure time or speed.", a.drivers)
            elif first > a.window_start + timedelta(minutes=45):
                add(1, f"Conditions reach caution level from about {fmt_ist(first)} — plan to be back in harbour before then.",
                    [f.id for f in a.factors if f.onset == first])
            else:
                add(1, "Caution-level conditions are expected from the start of the window — postpone if possible, or stay "
                       "close to shore with a clear return plan.", a.drivers)
        wv = fac.get("wave_height")
        if wv and wv.level in (RiskLevel.CAUTION, RiskLevel.DANGER):
            add(2, f"Expect significant waves up to {wv.value:g} m; avoid beam seas, reduce speed and secure deck gear.", ["wave_height"])
        g = fac.get("wind_gusts")
        if g and g.level in (RiskLevel.CAUTION, RiskLevel.DANGER):
            add(2, f"Gusts up to {g.value:.0f} km/h forecast — keep the boat trimmed and avoid sail/spread gear.", ["wind_gusts"])
        cp = fac.get("cape")
        if cp and cp.level in (RiskLevel.CAUTION, RiskLevel.DANGER):
            add(2, "High convective potential (model CAPE): thunderstorms and lightning are possible — watch the sky and "
                   "return at the first sign of squalls.", ["cape"])
        cy = fac.get("cyclone_distance")
        if cy and cy.value is not None and cy.level != RiskLevel.NOMINAL:
            where = "inside the wind field of an active tropical cyclone" if cy.value == 0 else f"{cy.value:.0f} km from an active tropical cyclone"
            add(1, f"The area is {where} — follow IMD cyclone bulletins and harbour instructions.",
                ["cyclone_distance"])
        bd = fac.get("boundary_distance")
        if bd and bd.value is not None and bd.level != RiskLevel.NOMINAL:
            add(1, f"The international maritime boundary is only {bd.value:.1f} km away — stay well inside Indian waters.",
                ["boundary_distance"])
        oa = fac.get("official_advisory")
        if oa and not oa.available:
            add(3, "Check the latest IMD fishermen warning and INCOIS ocean-state bulletin before departure — they are not "
                   "machine-accessible to ORCA.", ["official_advisory"])
        if any(c.decision_relevant for c in conflicts):
            add(2, "Forecast models disagree on key conditions — treat the more severe forecast as plausible.",
                [c.variable for c in conflicts if c.decision_relevant])
        rt = st.typed.get("route")
        if rt and rt.route:
            r = rt.route
            rec = next(o for o in r.options if o.id == r.recommended_id)
            short = next((o for o in r.options if o.id == "shortest"), None)
            if short and short.id != rec.id and short.max_risk > rec.max_risk + 0.05:
                add(1, f"Follow the recommended route ({rec.distance_km:.0f} km, {rec.duration_h:.1f} h): it lowers peak segment "
                       f"risk from {short.max_risk:.2f} to {rec.max_risk:.2f} for {rec.distance_km - short.distance_km:+.0f} km.", ["route"])
            for w in rec.warnings[:3]:
                add(1, w, ["route"])
        ext = st.typed.get("hazard:extended")
        if ext:
            ea = ext["assessment"]
            add(1, f"Extended check (cyclone nearby): through {fmt_ist(ea.window_end)} the assessment is "
                   f"{ea.decision.value.replace('_', ' ')}" + (f" — driven by {', '.join(ea.drivers)}" if ea.drivers else "") + ".",
                ["cyclone_distance"])
        if u.vessel_class.value == "small_craft" and a.decision != Decision.DONT_GO:
            add(4, "Carry life jackets, a charged phone / VHF and a Distress Alert Transmitter; tell someone ashore your plan.")
        recs.sort(key=lambda r: r.priority)
        return recs

    @staticmethod
    def _caveats(st: RunState, a) -> list[str]:
        cav = ["ORCA is a decision-support system, not an official authority. Official IMD / INCOIS warnings always take precedence."]
        if st.ctx.mode == DataMode.DEMO:
            cav.insert(0, f"DEMO MODE — scenario '{st.ctx.scenario_id}': all environmental data in this answer is SIMULATED.")
        elif st.ctx.mode == DataMode.REPLAY:
            cav.insert(0, f"REPLAY MODE — recorded real data from snapshot {st.ctx.replay_snapshot}; timestamps are those of the recording.")
        if a is not None:
            cav.append(f"Risk thresholds are ORCA defaults for {a.vessel_class.replace('_', ' ')} (model {a.model_version}) and "
                       "have not been validated by a marine authority.")
            cav.append("For safety decisions ORCA uses the worst case across forecast models and sample points; no averaging.")
        geo = st.typed.get("geospatial")
        if geo and geo.primary and any(z.approximate for z in geo.primary.zones):
            cav.append("Protected / restricted-area outlines are approximate (not legal boundaries).")
        return cav
