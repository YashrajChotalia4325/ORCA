"""ORCA orchestrator: creates a run (blackboard + data-mode context), invokes
the LangGraph agent graph (`orca.graph`) on it, and persists the full trace.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
import uuid
from typing import Optional

from .agents.base import RunState
from .core.clock import utcnow
from .core.schemas.blackboard import Blackboard, QueryRequest
from .core.schemas.common import DataMode
from .graph import AGENTS, GRAPH, PLANNER, RECURSION_LIMIT, OrcaContext, graph_description  # noqa: F401
from .reasoning.nlu import ConversationContext
from .runtime import Runtime
from .store.db import Store

log = logging.getLogger("orca.orchestrator")

ACTIVE: dict[str, RunState] = {}           # query_id -> live state (for SSE)
CONVERSATIONS: dict[str, ConversationContext] = {}


def agent_catalog() -> list[dict]:
    planner = {"name": PLANNER.name, "title": PLANNER.title, "responsibility": PLANNER.responsibility,
               "tools": PLANNER.tools, "consumes": ["request", "conversation memory"], "deterministic": False,
               "output_schema": ExecutionPlanSchema()}
    return [planner] + [a.describe() for a in AGENTS.values()]


def ExecutionPlanSchema():  # noqa: N802
    from .core.schemas.blackboard import ExecutionPlan
    return ExecutionPlan.model_json_schema()


def new_trace_id(now) -> str:
    return f"ORCA-{now:%Y-%m-%d}-{secrets.token_hex(3).upper()[:5]}"


def _conversation_context(conv_id: str) -> tuple[Optional[ConversationContext], Optional[Blackboard]]:
    ctx = CONVERSATIONS.get(conv_id)
    prev_bb = None
    if ctx and ctx.last_query_id:
        blob = Store.get().load_blackboard(ctx.last_query_id)
        if blob:
            prev_bb = Blackboard.model_validate_json(blob)
    elif conv_id:
        blob = Store.get().last_in_conversation(conv_id)
        if blob:
            prev_bb = Blackboard.model_validate_json(blob)
            ctx = ConversationContext(prev_bb.query_id, prev_bb.understanding)
    return ctx, prev_bb


def create_run(req: QueryRequest, mode: DataMode, scenario_id: Optional[str] = None,
               snapshot: Optional[str] = None) -> RunState:
    rt = Runtime.get()
    ectx = rt.context(mode, scenario_id=scenario_id, snapshot=snapshot)
    now = ectx.clock.now()
    conv = req.conversation_id or uuid.uuid4().hex[:12]
    bb = Blackboard(query_id=uuid.uuid4().hex[:16], trace_id=new_trace_id(now), conversation_id=conv,
                    created_at=utcnow(), virtual_now=now, mode=mode, request=req)
    ctx, prev = _conversation_context(conv)
    st = RunState(bb, ectx, previous=prev)
    st._conv_ctx = ctx  # type: ignore[attr-defined]
    ACTIVE[bb.query_id] = st
    return st


async def run(st: RunState) -> Blackboard:
    bb = st.bb
    t0 = time.perf_counter()
    try:
        st.emit("start", f"{bb.trace_id} · mode {bb.mode.value}" + (f" · scenario {st.ctx.scenario_id}" if st.ctx.scenario_id else ""),
                mode=bb.mode.value, scenario=st.ctx.scenario_id, virtual_now=bb.virtual_now.isoformat(),
                engine="langgraph")
        await GRAPH.ainvoke({}, config={"recursion_limit": RECURSION_LIMIT, "run_name": bb.trace_id},
                            context=OrcaContext(run=st))
        bb.status = "complete"
    except Exception as e:  # pragma: no cover - last-resort guard
        log.exception("query failed")
        bb.status = "failed"
        st.emit("error", f"{type(e).__name__}: {e}")
    finally:
        bb.completed_at = utcnow()
        bb.timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        if bb.understanding and bb.status == "complete":
            CONVERSATIONS[bb.conversation_id] = ConversationContext(bb.query_id, bb.understanding)
        try:
            Store.get().save_query(bb)
        except Exception:  # pragma: no cover
            log.exception("persist failed")
        st.emit("done", f"completed in {bb.timings['total_ms'] / 1000:.1f} s", status=bb.status,
                decision=bb.final_assessment.decision.value if bb.final_assessment else None)
        asyncio.get_running_loop().call_later(600, ACTIVE.pop, bb.query_id, None)
    return bb


async def run_query(req: QueryRequest, mode: DataMode, scenario_id: Optional[str] = None,
                    snapshot: Optional[str] = None) -> Blackboard:
    st = create_run(req, mode, scenario_id, snapshot)
    return await run(st)
