"""Deterministic marine route optimisation.

Algorithm: time-dependent A* on an 8-connected lat/lon grid.

    edge_cost = d_km × (1 + α·r(x, t)) × zone_multiplier + danger_penalty
      d_km  geodesic edge length
      r     point risk in [0,1] from the forecast risk field at the cell,
            evaluated at the vessel's ETA (departure + distance / speed)
      α     risk aversion (0 = shortest, 3 = recommended, 8 = safest)

Heuristic: great-circle distance to goal (admissible since cost ≥ distance).
Land cells are impassable; diagonal moves may not cut land corners.
Restricted areas are impassable; protected areas get a ×6 cost multiplier
(×1 for 'shortest'); for fishing craft, cells outside the Indian EEZ are
impassable (no IMBL crossing).

After search the path is simplified by line-of-sight string-pulling, only
where the straight segment stays at sea, outside blocked zones, and does not
raise the maximum risk of the section it replaces.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

import numpy as np
import shapely

from . import spatial
from .schemas.common import GeoPoint

KMH_PER_KN = 1.852


@dataclass
class RiskField:
    """Hourly gridded fields (NaN = no data) used by the router and route evaluator."""
    lats: np.ndarray                    # ascending
    lons: np.ndarray                    # ascending
    times: list[datetime]
    fields: dict[str, np.ndarray]       # var -> [t, i, j]
    sources: dict[str, list[str]] = field(default_factory=dict)  # var -> contributing source names

    def _tidx(self, t: datetime) -> tuple[int, int, float]:
        if not self.times:
            return 0, 0, 0.0
        if t <= self.times[0]:
            return 0, 0, 0.0
        if t >= self.times[-1]:
            n = len(self.times) - 1
            return n, n, 0.0
        secs = [(x - self.times[0]).total_seconds() for x in self.times]
        ts = (t - self.times[0]).total_seconds()
        k = int(np.searchsorted(secs, ts)) - 1
        w = (ts - secs[k]) / (secs[k + 1] - secs[k])
        return k, k + 1, w

    def value(self, var: str, lat: float, lon: float, t: datetime) -> Optional[float]:
        arr = self.fields.get(var)
        if arr is None or len(self.lats) < 1:
            return None
        k0, k1, w = self._tidx(t)
        v0 = _bilinear(arr[k0], self.lats, self.lons, lat, lon)
        v1 = _bilinear(arr[k1], self.lats, self.lons, lat, lon)
        if v0 is None:
            return v1
        if v1 is None:
            return v0
        return v0 + (v1 - v0) * w


def _bilinear(a: np.ndarray, lats: np.ndarray, lons: np.ndarray, lat: float, lon: float) -> Optional[float]:
    if len(lats) == 1 or len(lons) == 1:
        v = a.flat[0]
        return None if np.isnan(v) else float(v)
    i = int(np.clip(np.searchsorted(lats, lat) - 1, 0, len(lats) - 2))
    j = int(np.clip(np.searchsorted(lons, lon) - 1, 0, len(lons) - 2))
    y = (lat - lats[i]) / (lats[i + 1] - lats[i])
    x = (lon - lons[j]) / (lons[j + 1] - lons[j])
    y, x = min(max(y, 0.0), 1.0), min(max(x, 0.0), 1.0)
    q = np.array([[a[i, j], a[i, j + 1]], [a[i + 1, j], a[i + 1, j + 1]]], dtype=float)
    wts = np.array([[(1 - y) * (1 - x), (1 - y) * x], [y * (1 - x), y * x]])
    m = ~np.isnan(q)
    if not m.any():
        # fall back to nearest valid cell within 2 cells (coastal gaps in marine models)
        best = None
        for di in range(-2, 4):
            for dj in range(-2, 4):
                ii, jj = i + di, j + dj
                if 0 <= ii < len(lats) and 0 <= jj < len(lons) and not np.isnan(a[ii, jj]):
                    d = (lats[ii] - lat) ** 2 + (lons[jj] - lon) ** 2
                    if best is None or d < best[0]:
                        best = (d, float(a[ii, jj]))
        return None if best is None else best[1]
    return float((q[m] * wts[m]).sum() / wts[m].sum())


@dataclass
class Grid:
    lats: np.ndarray
    lons: np.ndarray
    passable: np.ndarray          # [i, j] bool
    zone_mult: np.ndarray         # [i, j] float multiplier (protected areas)
    res_deg: float


def build_grid(bbox: tuple[float, float, float, float], res_deg: float,
               sea_mask_fn: Callable[[np.ndarray, np.ndarray], np.ndarray],
               blocked_geoms: list, protected_geoms: list, allowed_geom=None, protected_mult: float = 6.0) -> Grid:
    lon0, lat0, lon1, lat1 = bbox
    lats = np.arange(lat0, lat1 + 1e-9, res_deg)
    lons = np.arange(lon0, lon1 + 1e-9, res_deg)
    LO, LA = np.meshgrid(lons, lats)
    sea = sea_mask_fn(LO.ravel(), LA.ravel()).reshape(LA.shape)
    passable = sea.copy()
    for g in blocked_geoms:
        passable &= ~shapely.contains_xy(g, LO, LA)
    if allowed_geom is not None:
        passable &= shapely.contains_xy(allowed_geom, LO, LA)
    zm = np.ones_like(LA, dtype=float)
    for g in protected_geoms:
        zm[shapely.contains_xy(g, LO, LA)] = protected_mult
    return Grid(lats, lons, passable, zm, res_deg)


def nearest_passable(grid: Grid, p: GeoPoint) -> tuple[int, int]:
    i = int(np.clip(round((p.lat - grid.lats[0]) / grid.res_deg), 0, len(grid.lats) - 1))
    j = int(np.clip(round((p.lon - grid.lons[0]) / grid.res_deg), 0, len(grid.lons) - 1))
    if grid.passable[i, j]:
        return i, j
    best = None
    for r in range(1, 40):
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                if max(abs(di), abs(dj)) != r:
                    continue
                ii, jj = i + di, j + dj
                if 0 <= ii < len(grid.lats) and 0 <= jj < len(grid.lons) and grid.passable[ii, jj]:
                    d = di * di + dj * dj
                    if best is None or d < best[0]:
                        best = (d, ii, jj)
        if best:
            return best[1], best[2]
    raise ValueError("no navigable water near the requested point")


@dataclass
class SearchResult:
    cells: list[tuple[int, int]]
    coords: list[list[float]]
    nodes_expanded: int
    cost: float


NEIGHBOURS = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]


def astar(grid: Grid, start: tuple[int, int], goal: tuple[int, int], *, alpha: float, speed_kn: float,
          departure: datetime, risk_at: Callable[[float, float, datetime], float],
          use_zone_mult: bool = True, max_expansions: int = 400_000) -> SearchResult:
    lats, lons = grid.lats, grid.lons
    speed_kmh = speed_kn * KMH_PER_KN
    goal_pt = GeoPoint(lat=float(lats[goal[0]]), lon=float(lons[goal[1]]))

    def h(c: tuple[int, int]) -> float:
        return spatial.distance_km(GeoPoint(lat=float(lats[c[0]]), lon=float(lons[c[1]])), goal_pt)

    # per-row edge lengths (km) for the 8 directions — lat-dependent
    dlat_km = grid.res_deg * 111.2
    g = {start: 0.0}
    dist = {start: 0.0}
    came: dict[tuple[int, int], tuple[int, int]] = {}
    openh = [(h(start), 0.0, start)]
    closed = set()
    expanded = 0
    ni, nj = grid.passable.shape
    while openh:
        f, gc, cur = heapq.heappop(openh)
        if cur in closed:
            continue
        if cur == goal:
            break
        closed.add(cur)
        expanded += 1
        if expanded > max_expansions:
            raise RuntimeError("route search exceeded expansion budget")
        ci, cj = cur
        dlon_km = grid.res_deg * 111.2 * math.cos(math.radians(float(lats[ci])))
        for di, dj in NEIGHBOURS:
            ii, jj = ci + di, cj + dj
            if not (0 <= ii < ni and 0 <= jj < nj) or not grid.passable[ii, jj]:
                continue
            if di and dj and not (grid.passable[ci + di, cj] and grid.passable[ci, cj + dj]):
                continue  # no land corner-cutting
            step = math.hypot(di * dlat_km, dj * dlon_km)
            d_new = dist[cur] + step
            if alpha > 0:
                eta = departure + timedelta(hours=d_new / speed_kmh)
                r = risk_at(float(lats[ii]), float(lons[jj]), eta)
            else:
                r = 0.0
            zm = grid.zone_mult[ii, jj] if use_zone_mult else 1.0
            danger_pen = step * 20.0 if (alpha > 0 and r >= 0.999) else 0.0
            cost = step * (1.0 + alpha * r) * zm + danger_pen
            ng = g[cur] + cost
            nb = (ii, jj)
            if ng < g.get(nb, math.inf):
                g[nb] = ng
                dist[nb] = d_new
                came[nb] = cur
                heapq.heappush(openh, (ng + h(nb), ng, nb))
    if goal not in came and goal != start:
        raise ValueError("no sea route found between the requested points")
    path = [goal]
    while path[-1] != start:
        path.append(came[path[-1]])
    path.reverse()
    coords = [[float(lons[j]), float(lats[i])] for i, j in path]
    return SearchResult(path, coords, expanded, g.get(goal, 0.0))


def smooth(coords: list[list[float]], ok_segment: Callable[[list[float], list[float]], bool]) -> list[list[float]]:
    """Greedy line-of-sight simplification."""
    if len(coords) <= 2:
        return coords
    out = [coords[0]]
    i = 0
    n = len(coords)
    while i < n - 1:
        j = n - 1
        while j > i + 1 and not ok_segment(coords[i], coords[j]):
            j -= 1
        out.append(coords[j])
        i = j
    return out
