"""Record a REPLAY snapshot: run real LIVE queries through a recording transport.

Every upstream response (Open-Meteo, NOAA ERDDAP, GDACS, GEBCO, ...) is saved
verbatim with its retrieval timestamp under data/replay/<snapshot-id>/. In
REPLAY mode ORCA's clock is fixed to the recording time and the same
questions reproduce the same agent behaviour on real (recorded) data.

Run:  .venv/Scripts/python scripts/record_replay.py [snapshot-id]
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from orca import orchestrator  # noqa: E402
from orca.connectors.transport import Recorder  # noqa: E402
from orca.core.schemas import DataMode, QueryRequest  # noqa: E402
from orca.runtime import Runtime  # noqa: E402
from orca.services import fields  # noqa: E402

QUERIES = [
    "Is it safe for a fishing boat to leave Kochi tomorrow at 5 AM?",
    "Is it safe to fish 25 km off Chennai tomorrow morning?",
    "Calculate a lower-risk route from Mumbai to Goa tomorrow morning",
    "Show potential fishing zones near Mangaluru",
    "Show cyclone risk across the Odisha coast for the next 24 hours",
    "Why did chlorophyll concentration decline off Kochi over the past 14 days?",
]


async def main(snapshot: str) -> None:
    out = ROOT / "data" / "replay" / snapshot
    rec = Recorder(out, description="Real public-endpoint responses recorded for REPLAY mode")
    rt = Runtime.get()
    orig = rt.context

    def ctx(mode, **kw):  # route every LIVE context of this process through the recorder
        if mode == DataMode.LIVE:
            kw["recorder"] = rec
        return orig(mode, **kw)

    rt.context = ctx  # type: ignore[assignment]
    done = []
    for q in QUERIES:
        bb = await orchestrator.run_query(QueryRequest(text=q), DataMode.LIVE)
        fa = bb.final_assessment
        print(f"{bb.trace_id}  {fa.decision.value if fa else '-':18}  {q}")
        done.append({"text": q, "trace_id": bb.trace_id, "decision": fa.decision.value if fa else None})
    lctx = ctx(DataMode.LIVE)
    for layer in ("waves", "wind", "currents"):
        f = await fields.field(lctx, layer)
        print(f"field {layer}: {len(f['points'])} points")
    m = json.loads((out / "manifest.json").read_text("utf-8"))
    m.update(queries=done, finished_at=datetime.now(timezone.utc).isoformat(), requests=len(rec.index))
    (out / "manifest.json").write_text(json.dumps(m, indent=2), "utf-8")
    print(f"snapshot {snapshot}: {len(rec.index)} recorded requests")
    await rt.aclose()


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).strftime("snap-%Y%m%dT%H%MZ")
    asyncio.run(main(sid))
