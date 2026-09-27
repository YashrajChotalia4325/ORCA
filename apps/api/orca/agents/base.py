"""Agent contract.

Every agent declares: name, title, responsibility, tools, the blackboard keys
it consumes, and a typed output model. `run()` receives the task parameters
and the shared run state (blackboard + typed outputs of upstream agents) and
returns an `AgentOutcome`. Agents never talk to each other directly and
never exchange free text.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, ClassVar, Optional

from pydantic import BaseModel

from ..core.clock import utcnow
from ..core.schemas.blackboard import Blackboard, PlanTask, TraceEvent
from ..core.schemas.common import AgentStatus
from ..core.schemas.provenance import SourceFailure
from ..runtime import ExecContext


@dataclass
class AgentOutcome:
    status: AgentStatus
    summary: str
    output: Optional[BaseModel] = None          # serialisable typed output (goes on the blackboard)
    typed: Any = None                           # in-memory rich objects for downstream agents
    confidence: Optional[float] = None
    sources: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    failures: list[SourceFailure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class RunState:
    """Per-query shared state handed to every agent."""

    def __init__(self, bb: Blackboard, ctx: ExecContext, previous: Optional[Blackboard] = None):
        self.bb = bb
        self.ctx = ctx
        self.previous = previous
        self.typed: dict[str, Any] = {}           # agent name -> typed payload
        self._subscribers: list[asyncio.Queue] = []
        self._seq = 0

    # ---------------------------------------------------------------- events
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for e in self.bb.events:
            q.put_nowait(e)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def emit(self, type_: str, message: str = "", *, agent: str | None = None, task_id: str | None = None,
             stage: str | None = None, **data: Any) -> TraceEvent:
        self._seq += 1
        ev = TraceEvent(seq=self._seq, at=utcnow(), type=type_, agent=agent, task_id=task_id, stage=stage,
                        message=message, data=data)
        self.bb.events.append(ev)
        for q in list(self._subscribers):
            q.put_nowait(ev)
        return ev

    def stage(self, name: str, message: str = "", **data: Any) -> None:
        self.bb.stage = name
        self.emit("stage", message or name.replace("_", " ").title(), stage=name, **data)

    def tool(self, agent: str, tool: str, message: str = "", **data: Any) -> None:
        self.emit("tool", message or tool, agent=agent, tool=tool, **data)

    @property
    def now(self) -> datetime:
        return self.ctx.clock.now()


class Agent(ABC):
    name: ClassVar[str]
    title: ClassVar[str]
    responsibility: ClassVar[str]
    tools: ClassVar[list[str]]
    consumes: ClassVar[list[str]] = []
    output_model: ClassVar[Optional[type[BaseModel]]] = None
    deterministic: ClassVar[bool] = True       # False only where an LLM may participate
    timeout_s: ClassVar[float] = 90.0

    @abstractmethod
    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome: ...

    @classmethod
    def describe(cls) -> dict:
        schema = cls.output_model.model_json_schema() if cls.output_model else None
        return {"name": cls.name, "title": cls.title, "responsibility": cls.responsibility, "tools": cls.tools,
                "consumes": cls.consumes, "deterministic": cls.deterministic, "timeout_s": cls.timeout_s,
                "output_schema": schema}

    # helpers
    def upstream(self, st: RunState, name: str) -> Any:
        return st.typed.get(name)
