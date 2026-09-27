"""ORCA's agent graph, built with LangGraph.

Topology (compiled once at import, reused for every query):

    START → understand ─┬─(clarification needed)→ clarify ───────────────┐
                        └─(understood)──────────→ plan                     │
    plan ──dispatch──→ Send(<agent>, task) × N   (one parallel superstep)  │
    <agent> ─────────→ join                                                │
    join ──dispatch──→ Send(<agent>, task) × N   while tasks remain        │
                    └→ review                    when the plan is exhausted│
    review ──(re-plan rules RP1–RP4 added tasks)→ Send(<agent>, task) × N  │
            └(nothing to add / round cap)──────→ visualize ←───────────────┘
    visualize → END

Every specialised agent is its own graph node. The plan is dynamic (it
depends on the intent), so the planner does not hard-wire agent→agent edges;
instead the `dispatch` router reads the plan's dependency DAG and fans out
every task whose dependencies are satisfied with LangGraph's `Send` API.
All tasks sent in one superstep run concurrently and LangGraph waits for all
of them before `join` runs — that barrier is exactly a wave of the DAG.

Two kinds of state:
* `OrcaState` (LangGraph channels) — the scheduling state: completed task ids
  (merged from parallel branches by an `operator.add` reducer), the re-plan
  round and the superstep counter. Small and serialisable.
* `OrcaContext.run` (LangGraph runtime context) — the per-query `RunState`:
  the typed Blackboard, the data-mode execution context (LIVE / REPLAY /
  DEMO transport, clock) and the event bus that streams to the UI. Agents
  read upstream typed outputs from it and write their own typed outputs back.
"""
from __future__ import annotations

import asyncio
import logging
import operator
import time
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from .agents.advisory import AdvisoryAgent
from .agents.alert import AlertAgent
from .agents.base import Agent, AgentOutcome, RunState
from .agents.communication import CommunicationAgent
from .agents.evidence import EvidenceAgent
from .agents.fisheries import FisheriesAgent
from .agents.geospatial import GeospatialAgent
from .agents.hazard import HazardAgent
from .agents.ocean import OceanAgent
from .agents.planner import Planner
from .agents.research import ResearchAgent
from .agents.route import RouteAgent
from .agents.satellite import SatelliteAgent
from .agents.weather import WeatherAgent
from .core.clock import utcnow
from .core.schemas.assessment import FinalAssessment
from .core.schemas.blackboard import AgentRecord, LocalizedResponse, MapDirective, PlanTask
from .core.schemas.common import AgentStatus, Decision, GeoPoint

log = logging.getLogger("orca.graph")

AGENTS: dict[str, Agent] = {a.name: a for a in [
    GeospatialAgent(), OceanAgent(), WeatherAgent(), SatelliteAgent(), AdvisoryAgent(), FisheriesAgent(),
    HazardAgent(), RouteAgent(), ResearchAgent(), EvidenceAgent(), CommunicationAgent(), AlertAgent()]}
PLANNER = Planner()
MAX_ROUNDS = 3          # initial plan + at most two re-planning rounds
RECURSION_LIMIT = 200   # supersteps; a route query with two re-plans uses ~25


# ------------------------------------------------------------------ state
class OrcaState(TypedDict, total=False):
    completed: Annotated[list[str], operator.add]   # task ids, merged across parallel branches
    round: int                                      # re-plan reviews performed
    superstep: int                                  # waves dispatched so far
    clarify: bool


class TaskInput(TypedDict):
    """Payload of a `Send` to an agent node."""
    task_id: str
    wave: int


@dataclass
class OrcaContext:
    run: RunState


# ------------------------------------------------------------------ helpers
def _ready(st: RunState, completed: set[str]) -> list[PlanTask]:
    """Tasks of the plan whose dependencies are all satisfied."""
    ids = {t.id for t in st.bb.plan.tasks}
    pending = [t for t in st.bb.plan.tasks if t.id not in completed]
    ready = [t for t in pending if all(d in completed or d not in ids for d in t.depends_on)]
    if pending and not ready:  # dependency cycle / unknown dependency — run everything left
        ready = pending
    return ready


def _register(st: RunState, tasks: list[PlanTask]) -> None:
    for t in tasks:
        st.bb.agents[t.id] = AgentRecord(task_id=t.id, agent=t.agent, title=AGENTS[t.agent].title, round=t.round)


def _sends(st: RunState, state: OrcaState) -> list[Send]:
    ready = _ready(st, set(state.get("completed", [])))
    wave = state.get("superstep", 0) + 1
    st.bb.supersteps.append({"wave": wave, "round": state.get("round", 0),
                             "tasks": [t.id for t in ready], "agents": sorted({t.agent for t in ready})})
    st.emit("dispatch", f"superstep {wave}: " + ", ".join(t.id for t in ready), wave=wave,
            tasks=[t.id for t in ready], parallel=len(ready))
    return [Send(t.agent, {"task_id": t.id, "wave": wave}) for t in ready]


async def execute_task(task: PlanTask, st: RunState, wave: int = 0) -> None:
    """Run one agent task with a timeout and failure isolation; record the outcome on the blackboard."""
    agent = AGENTS[task.agent]
    rec = st.bb.agents[task.id]
    rec.status = AgentStatus.RUNNING
    rec.started_at = utcnow()
    st.emit("agent_start", task.reason or agent.title, agent=agent.name, task_id=task.id, round=task.round, wave=wave)
    t0 = time.perf_counter()
    try:
        outcome: AgentOutcome = await asyncio.wait_for(agent.run(task, st), timeout=agent.timeout_s)
    except asyncio.TimeoutError:
        outcome = AgentOutcome(status=AgentStatus.FAILED, summary=f"timed out after {agent.timeout_s:.0f}s")
        rec.error = "timeout"
    except Exception as e:  # an agent failure must never crash the graph
        log.exception("agent %s failed", agent.name)
        outcome = AgentOutcome(status=AgentStatus.FAILED, summary=f"{type(e).__name__}: {e}"[:300])
        rec.error = f"{type(e).__name__}: {e}"[:500]
    rec.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
    rec.ended_at = utcnow()
    rec.status = outcome.status
    rec.summary = outcome.summary
    rec.confidence = outcome.confidence
    rec.tools_used = outcome.tools
    rec.sources_used = outcome.sources
    rec.failures = outcome.failures
    rec.warnings = outcome.warnings
    if outcome.output is not None:
        try:
            rec.output = outcome.output.model_dump(mode="json")
            st.bb.outputs[agent.name if not task.params.get("tag") else f"{agent.name}:{task.params['tag']}"] = rec.output
        except Exception:  # pragma: no cover
            rec.output = None
    seen = {(f.source_id, f.status) for f in st.bb.failures}
    for f in outcome.failures:
        if (f.source_id, f.status) not in seen:
            st.bb.failures.append(f)
            seen.add((f.source_id, f.status))
    st.emit("agent_end", outcome.summary, agent=agent.name, task_id=task.id, status=outcome.status.value,
            duration_ms=rec.duration_ms, sources=outcome.sources, failures=len(outcome.failures), round=task.round)


# ------------------------------------------------------------------ nodes
async def understand(state: OrcaState, runtime: Runtime[OrcaContext]) -> OrcaState:
    st = runtime.context.run
    rec = AgentRecord(task_id="planner", agent="planner", title=PLANNER.title, status=AgentStatus.RUNNING,
                      started_at=utcnow())
    st.bb.agents["planner"] = rec
    st.emit("agent_start", "understanding request and planning", agent="planner", task_id="planner")
    u = await PLANNER.understand(st, getattr(st, "_conv_ctx", None))
    st.bb.understanding = u
    if u.intent.value in ("EXPLAIN", "SOURCES", "CONFLICTS") and st.previous is None:
        u.clarification_needed = "There is no previous answer in this conversation to explain yet — ask a question first."
    return {"clarify": bool(u.clarification_needed), "completed": [], "round": 0, "superstep": 0}


async def clarify(state: OrcaState, runtime: Runtime[OrcaContext]) -> OrcaState:
    st = runtime.context.run
    u, rec = st.bb.understanding, st.bb.agents["planner"]
    rec.status, rec.summary = AgentStatus.PARTIAL, f"clarification needed: {u.clarification_needed}"
    rec.ended_at = utcnow()
    st.emit("agent_end", rec.summary, agent="planner", task_id="planner", status=rec.status.value)
    st.bb.final_assessment = FinalAssessment(decision=Decision.NOT_APPLICABLE, headline="Clarification needed",
                                             reasons=[u.clarification_needed], confidence=0.0)
    st.bb.response = LocalizedResponse(language=u.output_language, role=u.role, headline="Clarification needed",
                                       summary=u.clarification_needed,
                                       sections=[{"id": "understanding", "title": "Understood as",
                                                  "items": [u.intent.value], "assumptions": u.assumptions}])
    return {}


async def plan(state: OrcaState, runtime: Runtime[OrcaContext]) -> OrcaState:
    st = runtime.context.run
    bb, u, rec = st.bb, st.bb.understanding, st.bb.agents["planner"]
    bb.plan = PLANNER.plan(st)
    _register(st, bb.plan.tasks)
    rec.status = AgentStatus.SUCCEEDED
    rec.summary = (f"intent {u.intent.value} ({u.parse_method}, conf {u.parse_confidence:.2f}); "
                   f"{len(bb.plan.tasks)} tasks, {len({t.agent for t in bb.plan.tasks})} agents")
    rec.output = bb.plan.model_dump(mode="json")
    rec.ended_at = utcnow()
    rec.duration_ms = round((rec.ended_at - rec.started_at).total_seconds() * 1000, 1)
    rec.tools_used = ["nlu.parse", "temporal.resolve", "plan.build_dag"]
    st.emit("plan", rec.summary, agent="planner", tasks=[t.model_dump() for t in bb.plan.tasks],
            rationale=bb.plan.rationale)
    st.emit("agent_end", rec.summary, agent="planner", task_id="planner", status="SUCCEEDED",
            duration_ms=rec.duration_ms)
    return {}


def make_agent_node(name: str):
    async def node(payload: TaskInput, runtime: Runtime[OrcaContext]) -> OrcaState:
        st = runtime.context.run
        task = next(t for t in st.bb.plan.tasks if t.id == payload["task_id"])
        await execute_task(task, st, payload.get("wave", 0))
        return {"completed": [task.id]}
    node.__name__ = f"{name}_node"
    return node


async def join(state: OrcaState, runtime: Runtime[OrcaContext]) -> OrcaState:
    """Barrier after a parallel superstep; counts the wave."""
    return {"superstep": state.get("superstep", 0) + 1}


async def review(state: OrcaState, runtime: Runtime[OrcaContext]) -> OrcaState:
    """Planner reflection: apply re-planning rules RP1–RP4 to what the agents found."""
    st = runtime.context.run
    rnd = state.get("round", 0) + 1
    if rnd < MAX_ROUNDS:
        extra = PLANNER.review(st, rnd - 1)
        if extra:
            st.bb.plan.tasks += extra
            _register(st, extra)
            st.emit("plan", f"re-plan round {rnd}: +{len(extra)} task(s)", agent="planner",
                    tasks=[t.model_dump() for t in extra], round=rnd)
    return {"round": rnd}


async def visualize(state: OrcaState, runtime: Runtime[OrcaContext]) -> OrcaState:
    st = runtime.context.run
    st.stage("VISUALIZATION", "Preparing map layers and evidence markers")
    st.bb.map = map_directive(st)
    return {}


# ------------------------------------------------------------------ routers (conditional edges)
def after_understand(state: OrcaState) -> str:
    return "clarify" if state.get("clarify") else "plan"


def dispatch(state: OrcaState, runtime: Runtime[OrcaContext]):
    """Fan out every ready task in parallel, or hand over to the planner's review when the plan is done."""
    st = runtime.context.run
    if not _ready(st, set(state.get("completed", []))):
        return "review"
    return _sends(st, state)


def after_review(state: OrcaState, runtime: Runtime[OrcaContext]):
    st = runtime.context.run
    if state.get("round", 0) >= MAX_ROUNDS or not _ready(st, set(state.get("completed", []))):
        return "visualize"
    return _sends(st, state)


# ------------------------------------------------------------------ build
def build_graph():
    g = StateGraph(OrcaState, context_schema=OrcaContext)
    g.add_node("understand", understand)
    g.add_node("clarify", clarify)
    g.add_node("plan", plan)
    for name in AGENTS:
        g.add_node(name, make_agent_node(name), input_schema=TaskInput)
        g.add_edge(name, "join")
    g.add_node("join", join)
    g.add_node("review", review)
    g.add_node("visualize", visualize)

    g.add_edge(START, "understand")
    g.add_conditional_edges("understand", after_understand, ["clarify", "plan"])
    g.add_edge("clarify", "visualize")
    agents = list(AGENTS)
    g.add_conditional_edges("plan", dispatch, agents + ["review"])
    g.add_conditional_edges("join", dispatch, agents + ["review"])
    g.add_conditional_edges("review", after_review, agents + ["visualize"])
    g.add_edge("visualize", END)
    return g.compile(name="orca")


GRAPH = build_graph()


def graph_description() -> dict:
    """Topology of the compiled graph (for the API / docs)."""
    dg = GRAPH.get_graph()
    return {"engine": "langgraph",
            "nodes": [{"id": n.id, "kind": "agent" if n.id in AGENTS else "control"} for n in dg.nodes.values()],
            "edges": [{"source": e.source, "target": e.target, "conditional": e.conditional} for e in dg.edges],
            "mermaid": dg.draw_mermaid()}


# ------------------------------------------------------------------ map directive
def map_directive(st: RunState) -> MapDirective:
    md = MapDirective()
    geo = st.typed.get("geospatial")
    feats = {}
    if geo:
        feats["samples"] = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": s.id, "label": s.label, "role": s.role},
             "geometry": {"type": "Point", "coordinates": [s.point.lon, s.point.lat]}} for s in geo.samples]}
        if geo.bbox:
            b = geo.bbox
            md.center = GeoPoint(lat=(b.lat_min + b.lat_max) / 2, lon=(b.lon_min + b.lon_max) / 2)
            span = max(b.lon_max - b.lon_min, b.lat_max - b.lat_min)
            md.zoom = 8.2 if span <= 1.3 else 7 if span <= 3 else 6 if span <= 6 else 5
        if geo.primary and geo.mode in ("point", "ring"):
            md.center = geo.primary.point
    rt = st.typed.get("route")
    if rt and rt.geojson:
        feats["route"] = rt.geojson
    fish = st.typed.get("fisheries")
    if fish and fish.geojson:
        feats["fishing_zones"] = fish.geojson
    adv = st.typed.get("advisory")
    if adv:
        cf = [f for c in adv.cyclones if c.geojson for f in c.geojson["features"]]
        if cf:
            feats["cyclones"] = {"type": "FeatureCollection", "features": cf}
    hz = st.typed.get("hazard")
    if hz and hz["output"].stations:
        feats["stations"] = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"label": s.label, "decision": s.decision, "risk_index": s.risk_index},
             "geometry": {"type": "Point", "coordinates": [s.point.lon, s.point.lat]}} for s in hz["output"].stations]}
    ev = [{"type": "Feature", "properties": {"claim_id": c.id, "text": c.text[:140], "category": c.category,
                                             "confidence": c.confidence.value if c.confidence else None},
           "geometry": {"type": "Point", "coordinates": [c.map_focus.lon, c.map_focus.lat]}}
          for c in st.bb.claims if c.map_focus]
    if ev:
        feats["evidence"] = {"type": "FeatureCollection", "features": ev}
    md.features = feats
    u = st.bb.understanding
    layers = ["zones", "boundaries", "samples"]
    if u:
        md.time = u.time_window.start if u.time_window else None
        if "route" in feats:
            layers += ["route", "waves"]
        if "fishing_zones" in feats:
            layers += ["fishing_zones", "gibs_chlorophyll"]
        if "cyclones" in feats:
            layers += ["cyclones"]
        if u.intent.value in ("SAFETY_CHECK", "CONDITIONS", "HAZARD_SCAN", "REGIONAL_RISK"):
            layers += ["waves", "wind"]
        if u.intent.value in ("RESEARCH_TREND", "COMPARE_PERIODS"):
            layers += ["gibs_sst_anomaly", "gibs_chlorophyll"]
    md.layers = list(dict.fromkeys(layers))
    return md
