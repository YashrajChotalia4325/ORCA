"""Deterministic geodesy and geometry helpers.

All metric computations use either WGS84 geodesics (pyproj.Geod) or a local
azimuthal-equidistant projection centred on the point of interest, so
distances are accurate to well under 1 % across the Indian EEZ. No LLM is
involved in any geometric result.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Iterable, Sequence

import numpy as np
import shapely
from pyproj import Geod, Transformer
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from .schemas.common import GeoPoint

GEOD = Geod(ellps="WGS84")


def distance_km(a: GeoPoint, b: GeoPoint) -> float:
    _, _, d = GEOD.inv(a.lon, a.lat, b.lon, b.lat)
    return d / 1000.0


def bearing_deg(a: GeoPoint, b: GeoPoint) -> float:
    az, _, _ = GEOD.inv(a.lon, a.lat, b.lon, b.lat)
    return az % 360.0


def destination(p: GeoPoint, bearing: float, km: float) -> GeoPoint:
    lon, lat, _ = GEOD.fwd(p.lon, p.lat, bearing, km * 1000.0)
    return GeoPoint(lat=lat, lon=((lon + 180) % 360) - 180)


def compass(bearing: float | None) -> str:
    if bearing is None:
        return ""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((bearing % 360) / 22.5 + 0.5) % 16]


@lru_cache(maxsize=512)
def _aeqd(lat: float, lon: float) -> tuple[Transformer, Transformer]:
    crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs"
    fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return fwd, inv


def local_projection(center: GeoPoint):
    """Return (to_metres, to_lonlat) callables for shapely.ops.transform."""
    fwd, inv = _aeqd(round(center.lat, 3), round(center.lon, 3))
    return fwd.transform, inv.transform


def distance_to_geometry_km(p: GeoPoint, geom: BaseGeometry, window_deg: float = 4.0
                            ) -> tuple[float, GeoPoint | None, bool]:
    """Distance from p to geom (km), nearest point on geom, and whether p is inside.

    The geometry is clipped to a window around p before projection; the window
    grows until something is found (up to the full geometry).
    """
    if geom is None or geom.is_empty:
        return math.inf, None, False
    inside = bool(geom.geom_type in ("Polygon", "MultiPolygon") and shapely.contains_xy(geom, p.lon, p.lat))
    if inside:
        return 0.0, p, True
    w = window_deg
    part = None
    while w <= 64:
        part = geom.intersection(box(p.lon - w, p.lat - w, p.lon + w, p.lat + w))
        if not part.is_empty:
            break
        w *= 2
    if part is None or part.is_empty:
        part = geom
    to_m, to_ll = local_projection(p)
    gp = transform(to_m, part)
    origin = Point(0, 0)
    target = gp.boundary if gp.geom_type in ("Polygon", "MultiPolygon") else gp
    d = origin.distance(target)
    nearest = shapely.ops.nearest_points(origin, target)[1]
    lon, lat = to_ll(nearest.x, nearest.y)
    return d / 1000.0, GeoPoint(lat=lat, lon=lon), False


def densify_route(coords: Sequence[Sequence[float]], step_km: float = 0.5
                  ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Resample a [[lon, lat], ...] polyline along geodesics.

    Returns (lons, lats, cumulative_km) arrays.
    """
    lons, lats, cum = [coords[0][0]], [coords[0][1]], [0.0]
    total = 0.0
    for (lo1, la1), (lo2, la2) in zip(coords[:-1], coords[1:]):
        _, _, seg_m = GEOD.inv(lo1, la1, lo2, la2)
        seg_km = seg_m / 1000.0
        n = max(1, int(math.ceil(seg_km / step_km)))
        if n > 1:
            pts = GEOD.npts(lo1, la1, lo2, la2, n - 1)
            prev = (lo1, la1)
            for lo, la in pts:
                _, _, dm = GEOD.inv(prev[0], prev[1], lo, la)
                total += dm / 1000.0
                lons.append(lo); lats.append(la); cum.append(total)
                prev = (lo, la)
            _, _, dm = GEOD.inv(prev[0], prev[1], lo2, la2)
            total += dm / 1000.0
        else:
            total += seg_km
        lons.append(lo2); lats.append(la2); cum.append(total)
    return np.asarray(lons), np.asarray(lats), np.asarray(cum)


def route_length_km(coords: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for (lo1, la1), (lo2, la2) in zip(coords[:-1], coords[1:]):
        total += GEOD.inv(lo1, la1, lo2, la2)[2]
    return total / 1000.0


def first_entry_along(lons: np.ndarray, lats: np.ndarray, cum_km: np.ndarray, polygon: BaseGeometry
                      ) -> tuple[float | None, int | None]:
    """Distance along the route (km) at which it first enters polygon, or None."""
    inside = shapely.contains_xy(polygon, lons, lats)
    idx = np.flatnonzero(inside)
    if idx.size == 0:
        return None, None
    i = int(idx[0])
    return float(cum_km[i]), i


def min_distance_route_km(lons: np.ndarray, lats: np.ndarray, geom: BaseGeometry
                          ) -> tuple[float, int]:
    """Minimum distance from the sampled route to geom (km) and index of the closest sample."""
    mid = GeoPoint(lat=float(np.mean(lats)), lon=float(np.mean(lons)))
    to_m, _ = local_projection(mid)
    xs, ys = to_m(lons, lats)
    bb = box(float(lons.min()) - 3, float(lats.min()) - 3, float(lons.max()) + 3, float(lats.max()) + 3)
    part = geom.intersection(bb)
    if part.is_empty:
        return math.inf, 0
    gp = transform(to_m, part)
    target = gp.boundary if gp.geom_type in ("Polygon", "MultiPolygon") else gp
    pts = shapely.points(np.asarray(xs), np.asarray(ys))
    d = shapely.distance(pts, target)
    i = int(np.argmin(d))
    return float(d[i]) / 1000.0, i


def line_crosses(coords: Iterable[Sequence[float]], geom: BaseGeometry) -> bool:
    return LineString(list(coords)).intersects(geom)
