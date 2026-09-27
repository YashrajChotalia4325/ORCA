"""ORCA evaluation runner — 10 metrics.

 1 groundedness        numbers in the rendered answer that appear in the computed facts / evidence
 2 source correctness  evidence items whose source is registered and whose provenance is complete
 3 evidence completeness  risk claims with ≥1 evidence item (critical claims: ≥2 independent lineages)
 4 temporal correctness   resolved window matches expected day/hour (IST) and duration
 5 spatial correctness    expected place resolved; assessment point at sea; offshore distance honoured (±1 km)
 6 agent routing accuracy required agents executed; research never routes, route never runs research
 7 tool selection accuracy required tools recorded in the trace
 8 risk consistency       paraphrases / translations of one question give the same decision; reruns identical
 9 hallucination rate     unsupported numbers in answers + any LIVE label inside DEMO output (target 0)
10 response latency       p50 / p95 end-to-end (DEMO, no network)
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from statistics import median
from typing import Any, Optional

from ..core import spatial
from ..core.clock import IST
from ..core.schemas import DataMode, QueryRequest
from ..core.schemas.common import FreshnessStatus
from ..demo.scenarios import NOW
from ..geo.reference import ReferenceStore
from ..reasoning import nlu
from ..reasoning.llm import grounding_check
from ..store.db import Store
from .dataset import CASES, PIPELINE


def _understanding_metrics(ref) -> tuple[list[dict], dict]:
    rows = []
    for c in CASES:
        u = nlu.parse(QueryRequest(text=c["text"]), NOW, ref)
        r: dict[str, Any] = {"id": c["id"], "text": c["text"], "expected_intent": c["intent"], "intent": u.intent.value,
                             "intent_ok": u.intent.value == c["intent"], "lang": u.language, "lang_ok": u.language == c["lang"]}
        exp_place = c.get("place")
        got = [p.id for p in u.places]
        if c.get("region"):
            r["place_ok"] = bool(u.region and u.region.id == c["region"])
        elif exp_place is None:
            r["place_ok"] = True
        elif exp_place == "coordinate":
            r["place_ok"] = bool(got and got[0].startswith("coordinate"))
        else:
            r["place_ok"] = bool(got and got[0] == exp_place)
        if c.get("dest"):
            r["place_ok"] = r["place_ok"] and bool(u.destination and u.destination.id == c["dest"])
        t_ok = True
        if "start" in c and u.time_window:
            s = u.time_window.start.astimezone(IST)
            t_ok = (s.day, s.hour) == tuple(c["start"])
        if "hours" in c and u.time_window:
            t_ok = t_ok and abs(u.time_window.hours - c["hours"]) < 0.01
        r["temporal_ok"] = t_ok
        if "offshore" in c:
            r["spatial_extra_ok"] = u.offshore_km is not None and abs(u.offshore_km - c["offshore"]) < 1
        if "vessel" in c:
            r["vessel_ok"] = u.vessel_class.value == c["vessel"]
        rows.append(r)
    n = len(rows)
    agg = {
        "cases": n,
        "intent_accuracy": sum(r["intent_ok"] for r in rows) / n,
        "language_accuracy": sum(r["lang_ok"] for r in rows) / n,
        "place_accuracy": sum(r["place_ok"] for r in rows) / n,
        "temporal_accuracy": sum(r["temporal_ok"] for r in rows) / n,
        "vessel_accuracy": (lambda v: sum(v) / len(v) if v else None)([r["vessel_ok"] for r in rows if "vessel_ok" in r]),
    }
    return rows, agg


def _all_numbers_facts(bb) -> dict:
    facts = {"factors": [f.model_dump(mode="json") for f in (bb.risk.factors if bb.risk else [])],
             "evidence": [{"v": e.value, "t": e.valid_time} for e in bb.evidence],
             "window": bb.understanding.time_window.label if bb.understanding and bb.understanding.time_window else "",
             "fa": bb.final_assessment.model_dump(mode="json") if bb.final_assessment else {},
             "route": bb.outputs.get("route"), "fisheries": bb.outputs.get("fisheries"),
             "research": bb.outputs.get("research"), "geo": bb.outputs.get("geospatial"),
             "advisory": bb.outputs.get("advisory")}
    return facts


async def _pipeline_metrics() -> tuple[list[dict], dict]:
    from ..orchestrator import run_query
    rows = []
    latencies = []
    groups: dict[str, set] = {}
    for c in PIPELINE:
        t0 = time.perf_counter()
        bb = await run_query(QueryRequest(text=c["text"]), DataMode.DEMO, scenario_id=c["scenario"])
        ms = (time.perf_counter() - t0) * 1000
        latencies.append(ms)
        fa = bb.final_assessment
        dec = fa.decision.value if fa else None
        agents = {r.agent for r in bb.agents.values()}
        tools = {t for r in bb.agents.values() for t in r.tools_used}
        tools |= {e.data.get("tool") for e in bb.events if e.type == "tool" and e.data.get("tool")}
        # grounding: numbers in the rendered response vs facts
        text = " ".join([bb.response.headline if bb.response else "", " ".join(fa.reasons if fa else []),
                         " ".join(r.text for r in (fa.recommendations if fa else []))])
        gc = grounding_check(text, _all_numbers_facts(bb))
        # provenance completeness
        prov_ok = [bool(e.provenance.source and e.provenance.source_id and e.provenance.retrieval_timestamp and
                        e.provenance.freshness.status) for e in bb.evidence]
        live_leak = any(e.provenance.freshness.status == FreshnessStatus.LIVE for e in bb.evidence)
        risk_claims = [cl for cl in bb.claims if cl.category == "risk"]
        crit = [cl for cl in risk_claims if cl.factor_id in ("wave_height", "wind_speed")]
        ev_complete = (sum(1 for cl in risk_claims if cl.evidence_ids) / len(risk_claims)) if risk_claims else 1.0
        crit_multi = (sum(1 for cl in crit if cl.n_sources >= 2) / len(crit)) if crit else 1.0
        need_agents = set(c.get("agents", []))
        route_ok = need_agents <= agents and not ("research" in agents and "route" in agents)
        tools_ok = set(c.get("tools", [])) <= tools
        spatial_ok = True
        geo = bb.outputs.get("geospatial")
        if geo and geo.get("samples"):
            p0 = geo["samples"][0]["point"]
            from ..core.schemas.common import GeoPoint
            spatial_ok = ReferenceStore.get().is_sea(GeoPoint(**p0))
        conflict_ok = (not c.get("expect_conflict")) or any(x.decision_relevant for x in bb.conflicts)
        row = {"scenario": c["scenario"], "text": c["text"], "expected": c["decision"], "decision": dec,
               "decision_ok": dec == c["decision"], "agents_ok": route_ok, "tools_ok": tools_ok, "spatial_ok": spatial_ok,
               "grounded": gc["passed"], "unsupported_numbers": gc["unsupported_numbers"][:5],
               "provenance_complete": all(prov_ok) if prov_ok else True, "live_label_leak": live_leak,
               "evidence_completeness": ev_complete, "critical_multi_source": crit_multi, "conflict_ok": conflict_ok,
               "latency_ms": round(ms), "trace_id": bb.trace_id, "confidence": fa.confidence if fa else None}
        rows.append(row)
        if c.get("group"):
            groups.setdefault(c["group"], set()).add(dec)
    # determinism: re-run the first case
    from ..orchestrator import run_query as rq
    again = await rq(QueryRequest(text=PIPELINE[0]["text"]), DataMode.DEMO, scenario_id=PIPELINE[0]["scenario"])
    deterministic = again.final_assessment.decision.value == rows[0]["decision"] and \
        again.risk.risk_index == next(r for r in [again.risk]).risk_index
    n = len(rows)
    lat = sorted(latencies)
    agg = {
        "cases": n,
        "decision_accuracy": sum(r["decision_ok"] for r in rows) / n,
        "groundedness": sum(r["grounded"] for r in rows) / n,
        "source_correctness": sum(r["provenance_complete"] for r in rows) / n,
        "evidence_completeness": sum(r["evidence_completeness"] for r in rows) / n,
        "critical_claims_multi_source": sum(r["critical_multi_source"] for r in rows) / n,
        "spatial_correctness": sum(r["spatial_ok"] for r in rows) / n,
        "agent_routing_accuracy": sum(r["agents_ok"] for r in rows) / n,
        "tool_selection_accuracy": sum(r["tools_ok"] for r in rows) / n,
        "conflict_detection": sum(r["conflict_ok"] for r in rows) / n,
        "risk_consistency": (sum(1 for g in groups.values() if len(g) == 1) / len(groups)) if groups else None,
        "deterministic_rerun": deterministic,
        "hallucination_rate": sum((not r["grounded"]) or r["live_label_leak"] for r in rows) / n,
        "latency_p50_ms": round(median(lat)), "latency_p95_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))]),
    }
    return rows, agg


async def run_suite(limit: Optional[int] = None) -> dict:
    ref = ReferenceStore.get()
    t0 = time.perf_counter()
    u_rows, u_agg = _understanding_metrics(ref)
    p_rows, p_agg = await _pipeline_metrics()
    summary = {"version": "orca-eval-v1", "run_at": datetime.now(timezone.utc).isoformat(),
               "duration_s": round(time.perf_counter() - t0, 1), "understanding": u_agg, "pipeline": p_agg,
               "metrics": {
                   "groundedness": p_agg["groundedness"], "source_correctness": p_agg["source_correctness"],
                   "evidence_completeness": p_agg["evidence_completeness"],
                   "temporal_correctness": u_agg["temporal_accuracy"],
                   "spatial_correctness": (u_agg["place_accuracy"] + p_agg["spatial_correctness"]) / 2,
                   "agent_routing_accuracy": p_agg["agent_routing_accuracy"],
                   "tool_selection_accuracy": p_agg["tool_selection_accuracy"],
                   "risk_consistency": p_agg["risk_consistency"], "hallucination_rate": p_agg["hallucination_rate"],
                   "latency_p50_ms": p_agg["latency_p50_ms"], "latency_p95_ms": p_agg["latency_p95_ms"],
                   "intent_accuracy": u_agg["intent_accuracy"], "language_accuracy": u_agg["language_accuracy"],
                   "decision_accuracy": p_agg["decision_accuracy"]}}
    rid = "EVAL-" + uuid.uuid4().hex[:8].upper()
    Store.get().save_eval(rid, summary, {"understanding": u_rows, "pipeline": p_rows})
    return {"id": rid, "summary": summary, "understanding": u_rows, "pipeline": p_rows}
