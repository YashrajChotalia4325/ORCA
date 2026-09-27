"""Process-wide runtime: transports per mode, contexts, shared services."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import Settings, get_settings
from .connectors.base import ConnectorContext
from .connectors.registry import ConnectorRegistry
from .connectors.transport import DemoTransport, LiveTransport, Recorder, ReplayTransport
from .core.clock import Clock
from .core.schemas.common import DataMode
from .geo.reference import ReferenceStore
from .reasoning.llm import LLMClient


@dataclass
class ExecContext:
    mode: DataMode
    clock: Clock
    registry: ConnectorRegistry
    ref: ReferenceStore
    llm: LLMClient
    settings: Settings
    scenario_id: Optional[str] = None
    replay_snapshot: Optional[str] = None


class Runtime:
    _instance: Optional["Runtime"] = None

    def __init__(self, settings: Settings):
        self.settings = settings
        self.live = LiveTransport(settings.user_agent, settings.http_timeout_s)
        self.llm = LLMClient(settings)
        self._replays: dict[str, ReplayTransport] = {}

    @classmethod
    def get(cls) -> "Runtime":
        if cls._instance is None:
            cls._instance = Runtime(get_settings())
        return cls._instance

    # ------------------------------------------------------------------ replay snapshots
    def replay_dir(self) -> Path:
        return self.settings.data_dir / "replay"

    def list_snapshots(self) -> list[dict]:
        out = []
        d = self.replay_dir()
        if not d.exists():
            return out
        for p in sorted(d.iterdir()):
            m = p / "manifest.json"
            if m.exists() and (p / "index.json").exists():
                meta = json.loads(m.read_text("utf-8"))
                idx = json.loads((p / "index.json").read_text("utf-8"))
                out.append({"id": p.name, "recorded_at": meta.get("recorded_at"), "description": meta.get("description"),
                            "requests": len(idx), "queries": meta.get("queries", [])})
        return out

    def _replay(self, snapshot: Optional[str]) -> ReplayTransport:
        snaps = self.list_snapshots()
        if not snaps:
            raise FileNotFoundError("no replay snapshots recorded (run scripts/record_replay.py)")
        sid = snapshot if snapshot and snapshot != "latest" else snaps[-1]["id"]
        if sid not in self._replays:
            self._replays[sid] = ReplayTransport(self.replay_dir() / sid)
        return self._replays[sid]

    # ------------------------------------------------------------------ contexts
    def context(self, mode: DataMode, *, scenario_id: Optional[str] = None,
                snapshot: Optional[str] = None, recorder: Optional[Recorder] = None) -> ExecContext:
        ref = ReferenceStore.get()
        if mode == DataMode.LIVE:
            clock = Clock()
            transport = self.live
            if recorder is not None:
                transport = LiveTransport(self.settings.user_agent, self.settings.http_timeout_s, recorder=recorder)
        elif mode == DataMode.REPLAY:
            transport = self._replay(snapshot or self.settings.replay_snapshot)
            clock = Clock(fixed=transport.recorded_at)
            snapshot = transport.dir.name
        else:
            from .demo.scenarios import get_scenario
            sc = get_scenario(scenario_id or "kochi_fishing")
            clock = Clock(fixed=sc.now)
            transport = DemoTransport(sc.respond, clock.now)
            scenario_id = sc.id
        cctx = ConnectorContext(transport=transport, now=clock.now, mode=mode, settings=self.settings)
        return ExecContext(mode=mode, clock=clock, registry=ConnectorRegistry(cctx), ref=ref, llm=self.llm,
                           settings=self.settings, scenario_id=scenario_id, replay_snapshot=snapshot)

    async def aclose(self) -> None:
        await self.live.aclose()
