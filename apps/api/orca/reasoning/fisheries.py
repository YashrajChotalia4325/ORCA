"""ORCA productivity indicator (candidate fishing zones) — deterministic.

This is an ORCA-DERIVED indicator, not an INCOIS Potential Fishing Zone
advisory. It encodes the same physical rationale INCOIS PFZ uses (thermal
fronts in satellite SST co-located with elevated chlorophyll), but it is a
probabilistic habitat indicator: it never states that fish are present.

score = 0.45·f_front + 0.40·f_chl + 0.15·f_sst
    f_front = clamp(|∇SST| / (2·G0)),         G0 = max(0.02 °C/km, P90(|∇SST|))
    f_chl   = clamp(log10(chl/0.1) / log10(30))  (0.1 mg/m³ → 0, 3 mg/m³ → 1)
    f_sst   = 1 inside 25–30 °C, linear decay to 0 at ±3 °C outside
Candidate cells: score ≥ 0.55, at sea, inside the Indian EEZ; 8-connected
clusters become zones, ranked by score × sqrt(area).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import shapely
from scipy import ndimage
from shapely.geometry import box
from shapely.ops import unary_union

from ..core import spatial
from ..core.schemas.common import GeoPoint
from ..core.schemas.geo import CandidateZone
from ..core.schemas.provenance import GridField

G0_MIN = 0.02
SCORE_MIN = 0.55


@dataclass
class FrontAnalysis:
    zones: list[CandidateZone]
    g0: float
    n_cells: int
    n_candidate: int
    grad_p90: float
    chl_median: Optional[float]
    sst_mean: Optional[float]
    front_cells: int
    method: str


def _arr(g: GridField) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in g.values[0]], dtype=float)


def gradient_c_per_km(sst: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    dy_km = np.gradient(lats) * 110.57
    dx_km = np.gradient(lons)[None, :] * 111.32 * np.cos(np.radians(lats))[:, None]
    gy = np.gradient(sst, axis=0) / dy_km[:, None]
    gx = np.gradient(sst, axis=1) / dx_km
    return np.hypot(gx, gy)


def _resample_nearest(src: GridField, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    a = _arr(src)
    sl, so = np.array(src.lats), np.array(src.lons)
    ii = np.clip(np.searchsorted(sl, lats), 0, len(sl) - 1)
    jj = np.clip(np.searchsorted(so, lons), 0, len(so) - 1)
    ii = np.where((ii > 0) & (np.abs(sl[np.maximum(ii - 1, 0)] - lats) < np.abs(sl[ii] - lats)), ii - 1, ii)
    jj = np.where((jj > 0) & (np.abs(so[np.maximum(jj - 1, 0)] - lons) < np.abs(so[jj] - lons)), jj - 1, jj)
    return a[np.ix_(ii, jj)]


def analyse(sst: GridField, chl: Optional[GridField], origin: GeoPoint, sea_and_eez_mask) -> FrontAnalysis:
    lats, lons = np.array(sst.lats), np.array(sst.lons)
    S = _arr(sst)
    grad = gradient_c_per_km(S, lats, lons)
    valid = ~np.isnan(grad)
    p90 = float(np.nanpercentile(grad, 90)) if valid.any() else 0.0
    g0 = max(G0_MIN, p90)
    f_front = np.clip(grad / (2 * g0), 0, 1)
    if chl is not None:
        C = _resample_nearest(chl, lats, lons)
        f_chl = np.clip(np.log10(np.maximum(C, 1e-3) / 0.1) / math.log10(30), 0, 1)
        f_chl = np.where(np.isnan(C), np.nan, f_chl)
    else:
        C = np.full_like(S, np.nan)
        f_chl = np.full_like(S, np.nan)
    dev = np.maximum(0, np.maximum(25 - S, S - 30))
    f_sst = np.clip(1 - dev / 3, 0, 1)
    if chl is not None:
        score = 0.45 * f_front + 0.40 * np.nan_to_num(f_chl, nan=0.0) + 0.15 * f_sst
        method = "SST front + chlorophyll + SST preference"
    else:
        score = (0.45 * f_front + 0.15 * f_sst) / 0.60 * 0.85  # renormalised, capped lower without chlorophyll
        method = "SST front + SST preference only (chlorophyll unavailable — reduced confidence)"
    LO, LA = np.meshgrid(lons, lats)
    ok = sea_and_eez_mask(LO.ravel(), LA.ravel()).reshape(LA.shape) & ~np.isnan(S) & valid
    cand = (score >= SCORE_MIN) & ok
    labels, n = ndimage.label(cand, structure=np.ones((3, 3)))
    dlat = float(np.median(np.diff(lats))) if len(lats) > 1 else 0.05
    dlon = float(np.median(np.diff(lons))) if len(lons) > 1 else 0.05
    zones: list[CandidateZone] = []
    for k in range(1, n + 1):
        m = labels == k
        if m.sum() < 3:
            continue
        cells = [box(lons[j] - dlon / 2, lats[i] - dlat / 2, lons[j] + dlon / 2, lats[i] + dlat / 2)
                 for i, j in zip(*np.nonzero(m))]
        poly = unary_union(cells).simplify(dlat / 3)
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        c = poly.centroid
        cpt = GeoPoint(lat=c.y, lon=c.x)
        area = m.sum() * (dlat * 110.57) * (dlon * 111.32 * math.cos(math.radians(c.y)))
        zs = float(np.nanmean(score[m]))
        d_km = spatial.distance_km(origin, cpt)
        brg = spatial.bearing_deg(origin, cpt)
        mean_chl = float(np.nanmean(C[m])) if np.isfinite(C[m]).any() else None
        rationale = [f"SST front: max |∇SST| {np.nanmax(grad[m]):.3f} °C/km (threshold G0 {g0:.3f} °C/km)",
                     f"mean SST {np.nanmean(S[m]):.2f} °C"]
        if mean_chl is not None:
            rationale.append(f"mean chlorophyll-a {mean_chl:.2f} mg/m³")
        rationale.append(f"{d_km:.0f} km {spatial.compass(brg)} of {origin.lat:.2f}°N {origin.lon:.2f}°E")
        zones.append(CandidateZone(
            id=f"zone_{k}", centroid=cpt, polygon=[list(xy) for xy in poly.exterior.coords], area_km2=round(area, 1),
            score=round(zs, 3), mean_sst_c=round(float(np.nanmean(S[m])), 2),
            max_front_gradient_c_per_km=round(float(np.nanmax(grad[m])), 4),
            mean_chl_mg_m3=round(mean_chl, 3) if mean_chl is not None else None,
            distance_from_origin_km=round(d_km, 1), bearing_from_origin_deg=round(brg, 0),
            rationale=rationale, official=False))
    zones.sort(key=lambda z: -(z.score * math.sqrt(max(z.area_km2, 1))))
    zones = zones[:5]
    for i, z in enumerate(zones, 1):
        z.id = f"ORCA-Z{i}"
    return FrontAnalysis(zones=zones, g0=round(g0, 4), n_cells=int(ok.sum()), n_candidate=int(cand.sum()),
                         grad_p90=round(p90, 4), chl_median=None if chl is None else float(np.nanmedian(C)),
                         sst_mean=float(np.nanmean(S)) if (~np.isnan(S)).any() else None,
                         front_cells=int(((grad >= g0) & ok).sum()), method=method)
