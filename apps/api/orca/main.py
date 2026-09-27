"""ORCA API application."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import probe_all, router
from .config import get_settings
from .geo.reference import ReferenceStore
from .monitor import MONITOR
from .runtime import Runtime
from .store.db import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("orca")


async def _probe_loop() -> None:
    while True:
        try:
            await probe_all()
        except Exception:  # pragma: no cover
            log.exception("source probe failed")
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    ref = ReferenceStore.get()
    for g in Store.get().geofences():
        ref.add_geofence(g["id"], g["name"], g["ring"], g["props"])
    tasks = [asyncio.create_task(_probe_loop())]
    if s.monitor_enabled:
        MONITOR.start(s.monitor_interval_s)
    log.info("ORCA ready — default mode %s, LLM %s", s.default_mode, "on" if s.llm_available else "off (templates only)")
    yield
    for t in tasks:
        t.cancel()
    await MONITOR.stop()
    await Runtime.get().aclose()


app = FastAPI(title="ORCA — Ocean & Marine Reasoning with Collaborative Agents",
              version="0.1.0", lifespan=lifespan,
              description="Agentic marine decision-support API (SIH26176). Decision support only — not an official authority.")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = uuid.uuid4().hex[:10]
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    # never log query strings (they can carry coordinates)
    log.info("%s %s %s %.0fms", request.method, request.url.path, response.status_code, (time.perf_counter() - t0) * 1000)
    return response


app.include_router(router)


@app.get("/")
async def root():
    return {"name": "ORCA API", "docs": "/docs", "health": "/api/system/health"}
