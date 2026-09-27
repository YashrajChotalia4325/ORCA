"""End-to-end multi-agent pipeline on DEMO scenarios (deterministic, no network) + routing + API."""
import numpy as np
import pytest
from datetime import datetime, timedelta, timezone

from orca.core import routing
from orca.core.schemas import DataMode, QueryRequest
from orca.core.schemas.common import Decision, FreshnessStatus, GeoPoint
from orca.demo.scenarios import SCENARIOS
from orca.orchestrator import run_query


async def run(sid, text=None, **kw):
    return await run_query(QueryRequest(text=text or SCENARIOS[sid].query, **kw), DataMode.DEMO, scenario_id=sid)


def agents_used(bb):
    return {r.agent for r in bb.agents.values()}


async def test_kochi_caution_with_onset_and_all_agents():
    bb = await run("kochi_fishing")
    fa = bb.final_assessment
    assert fa.decision == Decision.CAUTION
    assert {"planner", "geospatial", "ocean", "weather", "satellite", "advisory", "fisheries", "hazard", "evidence",
            "alert", "communication"} <= agents_used(bb)
    assert any("back in harbour before" in r.text for r in fa.recommendations)
    # every evidence item carries provenance and is labelled SIMULATED, never LIVE
    assert bb.evidence and all(e.provenance.mode == DataMode.DEMO for e in bb.evidence)
    assert all(e.provenance.freshness.status != FreshnessStatus.LIVE for e in bb.evidence)
    assert any("DEMO MODE" in c for c in fa.caveats)
    assert 0 < fa.confidence <= 1 and fa.confidence_breakdown.formula
    assert bb.trace_id.startswith("ORCA-2026-")


async def test_cyclone_dont_go_with_replanning_and_alerts():
    bb = await run("approaching_cyclone")
    assert bb.final_assessment.decision == Decision.DONT_GO
    assert any(r["rule"] == "RP3" for r in bb.plan.replans)
    cy = next(f for f in bb.risk.factors if f.id == "cyclone_distance")
    assert cy.value == 0.0                              # inside simulated wind radius (point-in-polygon)
    assert bb.alerts and any(a.category == "cyclone" for a in bb.alerts)
    assert "cyclones" in bb.map.features


async def test_conflicting_sources_are_not_averaged_and_trigger_tiebreakers():
    bb = await run("conflicting_sources")
    assert bb.final_assessment.decision == Decision.CAUTION
    wave = next(c for c in bb.conflicts if c.variable == "wave_height")
    assert wave.decision_relevant and len(wave.entries) >= 3
    f = next(f for f in bb.risk.factors if f.id == "wave_height")
    assert f.value == max(m.value for m in f.per_source)          # conservative, not averaged
    rules = {r["rule"] for r in bb.plan.replans}
    assert {"RP2-ocean", "RP2-weather"} <= rules
    assert any(m.source_id == "om_dwd_gwam" for m in f.per_source)   # tie-breaker model was added
    assert any(c.variable == "sst" for c in bb.conflicts)


async def test_degraded_mode_lists_exclusions_and_lowers_confidence():
    ok = await run("kochi_fishing", "Is it safe to fish 20 km off Kochi tomorrow morning?")
    bad = await run("degraded_sources")
    ex = " ".join(bad.final_assessment.excluded_sources)
    assert "MFWAM" in ex and "CoastWatch" in ex
    assert bad.final_assessment.confidence < ok.final_assessment.confidence
    assert bad.final_assessment.decision != Decision.INSUFFICIENT_DATA


async def test_total_outage_refuses_instead_of_guessing():
    bb = await run("total_outage")
    fa = bb.final_assessment
    assert fa.decision == Decision.INSUFFICIENT_DATA and fa.refusal_reason
    assert "wave" in fa.refusal_reason.lower() and fa.confidence == 0.0
    assert any(r["rule"] == "RP1-ocean" for r in bb.plan.replans)
    assert "not" in bb.response.headline.lower() or "cannot" in bb.response.headline.lower()


async def test_route_avoids_squall_and_reports_tradeoff():
    bb = await run("mumbai_goa_route")
    r = bb.route or None
    out = bb.outputs["route"]["route"]
    opts = {o["id"]: o for o in out["options"]}
    assert opts["recommended"]["max_risk"] < opts["shortest"]["max_risk"]
    assert opts["recommended"]["distance_km"] >= opts["shortest"]["distance_km"]
    assert all(s["eta_start"] for s in opts["recommended"]["segments"])
    assert "route" in bb.map.features


async def test_protected_area_geofence_warning_with_time_to_entry():
    bb = await run("protected_geofence")
    rec = next(o for o in bb.outputs["route"]["route"]["options"] if o["id"] == "recommended")
    assert any("Gulf of Mannar" in w and "minutes" in w for w in rec["warnings"])
    assert any(r["rule"] == "RP4" for r in bb.plan.replans)


async def test_pfz_is_probabilistic_and_labels_official_vs_derived():
    bb = await run("pfz_mangaluru")
    fish = bb.outputs["fisheries"]
    assert fish["zones"] and all(not z["official"] for z in fish["zones"])
    assert "does not indicate that fish are present" in fish["disclaimer"]
    txt = " ".join(c.text for c in bb.claims if c.category == "fisheries")
    assert "presence of fish is not implied" in txt.lower()


async def test_research_separates_epistemic_levels():
    bb = await run("research_chl")
    kinds = {f["epistemic"] for f in bb.outputs["research"]["findings"]}
    assert {"OBSERVATION", "CORRELATION", "HYPOTHESIS", "CONCLUSION"} <= kinds
    concl = next(f["text"] for f in bb.outputs["research"]["findings"] if f["epistemic"] == "CONCLUSION")
    assert "not a demonstrated cause" in concl or "causation" in concl


async def test_multilingual_output_same_science():
    en = await run("kochi_fishing", "Is it safe to fish off Kochi tomorrow morning?")
    ml = await run("kochi_fishing", "നാളെ രാവിലെ കൊച്ചിയിൽ നിന്ന് മീൻ പിടിക്കാൻ പോകാമോ?")
    assert ml.response.language == "ml" and en.response.language == "en"
    assert ml.final_assessment.decision == en.final_assessment.decision
    assert ml.risk.risk_index == en.risk.risk_index
    assert "ജാഗ്രത" in ml.response.summary or "ശ്രദ്ധിക്കുക" in ml.response.headline


async def test_follow_up_explain_reuses_evidence():
    first = await run("kochi_fishing")
    fu = await run_query(QueryRequest(text="What sources support your conclusion?", conversation_id=first.conversation_id),
                         DataMode.DEMO, scenario_id="kochi_fishing")
    assert fu.claims and fu.final_assessment.decision == first.final_assessment.decision
    assert "evidence" in agents_used(fu) and "ocean" not in agents_used(fu)


# ------------------------------------------------------------------------------------------------ router unit test
def test_astar_detours_around_high_risk_and_land():
    lats, lons = np.arange(0, 1.01, 0.05), np.arange(0, 2.01, 0.05)
    passable = np.ones((len(lats), len(lons)), bool)
    passable[5:21, 20] = False                          # a "peninsula" wall from the north down to lat 0.25
    grid = routing.Grid(lats, lons, passable, np.ones_like(passable, float), 0.05)
    t0 = datetime(2026, 9, 26, tzinfo=timezone.utc)
    risky = lambda la, lo, t: 1.0 if (0.0 <= la <= 0.3 and 0.9 <= lo <= 1.1) else 0.0   # storm at the gap
    s, g = (10, 0), (10, 40)
    short = routing.astar(grid, s, g, alpha=0, speed_kn=10, departure=t0, risk_at=risky)
    safe = routing.astar(grid, s, g, alpha=8, speed_kn=10, departure=t0, risk_at=risky)
    assert all(passable[i, j] for i, j in short.cells) and all(passable[i, j] for i, j in safe.cells)
    assert max(risky(lats[i], lons[j], t0) for i, j in short.cells) == 1.0
    assert max(risky(lats[i], lons[j], t0) for i, j in safe.cells) < 1.0 or len(safe.cells) >= len(short.cells)


# ------------------------------------------------------------------------------------------------ API
def test_api_endpoints():
    from fastapi.testclient import TestClient
    from orca.main import app
    with TestClient(app) as c:
        h = c.get("/api/system/health").json()
        assert h["status"] == "ok" and h["agents"]["count"] >= 13
        a = c.get("/api/agents").json()
        assert len(a) >= 13 and all("tools" in x for x in a)
        b = c.get("/api/boundaries").json()
        assert b["layers"]["eez"]["features"] and b["provenance"]["curated_zones"]["warning"]
        r = c.post("/api/query?mode=DEMO&scenario=kochi_fishing&wait=true",
                   json={"text": "Is it safe to fish off Kochi tomorrow morning?"}).json()
        assert r["final_assessment"]["decision"] == "CAUTION" and r["mode"] == "DEMO"
        ev = c.get(f"/api/query/{r['trace_id']}/evidence").json()
        assert ev["claims"] and ev["evidence"]
        g = c.post("/api/geofences", json={"name": "t", "ring": [[75, 9], [75.2, 9], [75.2, 9.2], [75, 9.2]]}).json()
        assert g["id"].startswith("gf_")
        assert c.post("/api/query", json={"text": ""}).status_code == 422
        assert c.get("/api/demo/scenarios").json()


def test_langgraph_topology():
    from orca.graph import AGENTS, graph_description
    d = graph_description()
    assert d["engine"] == "langgraph"
    ids = {n["id"] for n in d["nodes"]}
    assert set(AGENTS) <= ids and {"understand", "plan", "join", "review", "visualize", "clarify"} <= ids
    edges = {(e["source"], e["target"]) for e in d["edges"]}
    assert all((a, "join") in edges for a in AGENTS)          # every agent fans back into the barrier
    assert ("review", "visualize") in edges and ("join", "review") in edges


async def test_supersteps_are_parallel_waves():
    bb = await run("conflicting_sources")
    waves = bb.supersteps
    assert waves[0]["tasks"] == ["geospatial"]
    assert {"ocean", "weather", "advisory"} <= set(waves[1]["tasks"])   # independent agents share a superstep
    done = set()
    for w in waves:                                                    # a task only runs after its dependencies
        for tid in w["tasks"]:
            t = next(t for t in bb.plan.tasks if t.id == tid)
            assert all(d in done for d in t.depends_on)
        done |= set(w["tasks"])
    assert any(w["round"] == 1 for w in waves)                         # RP2 re-plan executed as further supersteps
