"""SQLite persistence (default). A PostGIS schema for production lives in infra/postgis/schema.sql.

Location privacy: unless ORCA_STORE_PRECISE_LOCATION=true, stored query
locations are rounded to 0.1° (~11 km) and the free-text query is kept only
in the full trace blob, which can be disabled per deployment.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
  query_id TEXT PRIMARY KEY, trace_id TEXT UNIQUE, conversation_id TEXT, created_at TEXT, completed_at TEXT,
  mode TEXT, intent TEXT, role TEXT, language TEXT, decision TEXT, confidence REAL, status TEXT,
  lat_coarse REAL, lon_coarse REAL, duration_ms REAL, n_agents INTEGER, n_sources INTEGER, n_conflicts INTEGER,
  llm_input_tokens INTEGER, llm_output_tokens INTEGER, blackboard TEXT
);
CREATE INDEX IF NOT EXISTS ix_queries_conv ON queries(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS agent_runs (
  query_id TEXT, task_id TEXT, agent TEXT, status TEXT, duration_ms REAL, round INTEGER, n_failures INTEGER,
  PRIMARY KEY (query_id, task_id)
);
CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY, created_at TEXT, severity TEXT, category TEXT, title TEXT, region TEXT, status TEXT,
  mode TEXT, dedup_key TEXT, verified INTEGER, valid_to TEXT, body TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_dedup ON alerts(dedup_key, created_at);
CREATE TABLE IF NOT EXISTS geofences (
  id TEXT PRIMARY KEY, name TEXT, created_at TEXT, ring TEXT, props TEXT
);
CREATE TABLE IF NOT EXISTS watches (
  id TEXT PRIMARY KEY, name TEXT, created_at TEXT, kind TEXT, spec TEXT, active INTEGER
);
CREATE TABLE IF NOT EXISTS eval_runs (
  id TEXT PRIMARY KEY, created_at TEXT, summary TEXT, results TEXT
);
"""


class Store:
    _inst: Optional["Store"] = None

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    @classmethod
    def get(cls) -> "Store":
        if cls._inst is None:
            cls._inst = Store(get_settings().db_path)
        return cls._inst

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    # ------------------------------------------------------------------ queries
    def save_query(self, bb) -> None:
        s = get_settings()
        u = bb.understanding
        pt = None
        if u and u.places:
            pt = u.places[0].point
        elif u and u.region:
            pt = u.region.point
        nd = 4 if s.store_precise_location else 1
        blob = bb.model_dump_json()
        fa = bb.final_assessment
        dur = (bb.completed_at - bb.created_at).total_seconds() * 1000 if bb.completed_at else None
        srcs = {x for r in bb.agents.values() for x in r.sources_used}
        self._exec("""INSERT OR REPLACE INTO queries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            bb.query_id, bb.trace_id, bb.conversation_id, bb.created_at.isoformat(),
            bb.completed_at.isoformat() if bb.completed_at else None, bb.mode.value,
            u.intent.value if u else None, u.role.value if u else None, u.language if u else None,
            fa.decision.value if fa else None, fa.confidence if fa else None, bb.status,
            round(pt.lat, nd) if pt else None, round(pt.lon, nd) if pt else None, dur, len(bb.agents), len(srcs),
            len(bb.conflicts), bb.llm_usage.get("input_tokens", 0), bb.llm_usage.get("output_tokens", 0), blob))
        for r in bb.agents.values():
            self._exec("INSERT OR REPLACE INTO agent_runs VALUES (?,?,?,?,?,?,?)",
                       (bb.query_id, r.task_id, r.agent, r.status.value, r.duration_ms, r.round, len(r.failures)))

    def load_blackboard(self, query_id: str) -> Optional[str]:
        rows = self._all("SELECT blackboard FROM queries WHERE query_id=? OR trace_id=?", (query_id, query_id))
        return rows[0]["blackboard"] if rows else None

    def last_in_conversation(self, conversation_id: str) -> Optional[str]:
        rows = self._all("SELECT blackboard FROM queries WHERE conversation_id=? AND status='complete' "
                         "ORDER BY created_at DESC LIMIT 1", (conversation_id,))
        return rows[0]["blackboard"] if rows else None

    def recent_queries(self, limit: int = 50) -> list[dict]:
        return self._all("SELECT query_id, trace_id, conversation_id, created_at, completed_at, mode, intent, role, language, "
                         "decision, confidence, status, duration_ms, n_agents, n_sources, n_conflicts, llm_input_tokens, "
                         "llm_output_tokens FROM queries ORDER BY created_at DESC LIMIT ?", (limit,))

    def agent_stats(self) -> list[dict]:
        return self._all("SELECT agent, COUNT(*) AS runs, AVG(duration_ms) AS avg_ms, "
                         "SUM(CASE WHEN status IN ('SUCCEEDED','PARTIAL') THEN 1 ELSE 0 END) AS ok, "
                         "SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) AS failed FROM agent_runs GROUP BY agent")

    def query_stats(self) -> dict:
        r = self._all("SELECT COUNT(*) n, AVG(duration_ms) avg_ms, SUM(llm_input_tokens) tin, SUM(llm_output_tokens) tout "
                      "FROM queries")[0]
        return r

    # ------------------------------------------------------------------ alerts
    def save_alert(self, a) -> None:
        self._exec("INSERT OR REPLACE INTO alerts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            a.id, a.created_at.isoformat(), a.severity, a.category, a.title, a.region, a.status, a.mode, a.dedup_key,
            int(a.verified), a.valid_to.isoformat() if a.valid_to else None, a.model_dump_json()))

    def alert_exists(self, dedup_key: str, since_iso: str) -> bool:
        return bool(self._all("SELECT 1 FROM alerts WHERE dedup_key=? AND created_at>=? LIMIT 1", (dedup_key, since_iso)))

    def alerts(self, mode: Optional[str] = None, limit: int = 100, status: Optional[str] = None) -> list[dict]:
        q, args = "SELECT body FROM alerts WHERE 1=1", []
        if mode:
            q += " AND mode=?"; args.append(mode)
        if status:
            q += " AND status=?"; args.append(status)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        return [json.loads(r["body"]) for r in self._all(q, tuple(args))]

    def set_alert_status(self, aid: str, status: str) -> bool:
        rows = self._all("SELECT body FROM alerts WHERE id=?", (aid,))
        if not rows:
            return False
        body = json.loads(rows[0]["body"])
        body["status"] = status
        self._exec("UPDATE alerts SET status=?, body=? WHERE id=?", (status, json.dumps(body), aid))
        return True

    # ------------------------------------------------------------------ geofences / watches
    def save_geofence(self, gid: str, name: str, ring: list, props: dict) -> None:
        self._exec("INSERT OR REPLACE INTO geofences VALUES (?,?,?,?,?)",
                   (gid, name, datetime.utcnow().isoformat(), json.dumps(ring), json.dumps(props)))

    def geofences(self) -> list[dict]:
        return [{**r, "ring": json.loads(r["ring"]), "props": json.loads(r["props"])} for r in self._all("SELECT * FROM geofences")]

    def delete_geofence(self, gid: str) -> None:
        self._exec("DELETE FROM geofences WHERE id=?", (gid,))

    def save_watch(self, wid: str, name: str, kind: str, spec: dict, active: bool = True) -> None:
        self._exec("INSERT OR REPLACE INTO watches VALUES (?,?,?,?,?,?)",
                   (wid, name, datetime.utcnow().isoformat(), kind, json.dumps(spec, default=str), int(active)))

    def watches(self) -> list[dict]:
        return [{**r, "spec": json.loads(r["spec"])} for r in self._all("SELECT * FROM watches WHERE active=1")]

    # ------------------------------------------------------------------ eval
    def save_eval(self, rid: str, summary: dict, results: list) -> None:
        self._exec("INSERT OR REPLACE INTO eval_runs VALUES (?,?,?,?)",
                   (rid, datetime.utcnow().isoformat(), json.dumps(summary, default=str), json.dumps(results, default=str)))

    def latest_eval(self) -> Optional[dict]:
        rows = self._all("SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT 1")
        if not rows:
            return None
        r = rows[0]
        return {"id": r["id"], "created_at": r["created_at"], "summary": json.loads(r["summary"]), "results": json.loads(r["results"])}
