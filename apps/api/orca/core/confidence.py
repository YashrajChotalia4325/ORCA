"""Transparent, documented confidence model (see docs/REASONING.md §Confidence).

Per evidence item i:
    w_i = A_i × F_i × S_i × T_i
      A  source authority weight (by authority tier)
      F  freshness factor (LIVE 1.0, RECENT 0.95, STALE 0.6, UNAVAILABLE 0)
      S  spatial match   = exp(−max(0, d − 0.71 r)/50 km) × (1 − min(0.3, r/150 km))
                           d: distance to the product cell used, r: native resolution (0.71 r = half-cell diagonal)
      T  temporal match  = forecast: exp(−lead_h/168)
                           analysis/observation: exp(−max(0, age_h − validity_h)/48)
                           advisory / reference: 1.0 (0.5 when outside validity)

Per claim c:
    Q  evidence quality  = Σ ι_i w_i / Σ ι_i     ι_i independence weight (1.0 first of a lineage, 0.3 repeats)
    G  agreement         = Σ ι_i [level_i == level_c] / Σ ι_i
    K  corroboration     = 1.0 if ≥ 2 independent lineages else 0.85
    conf_c = Q × (0.5 + 0.5 G) × K

Assessment:
    C  completeness      = Σ weight(available factors) / Σ weight(expected factors)   (critical factors weight 2)
    D  critical-source coverage = mean over critical factors of (sources responding / sources queried)
    conf = (Σ ω_c conf_c / Σ ω_c) × C × (0.7 + 0.3 D)     ω_c = 2 for decision drivers, 1 otherwise
    (for INSUFFICIENT_DATA no decision is made; confidence is reported as 0)
"""
from __future__ import annotations

import math
import re
from typing import Iterable, Optional

from .schemas.assessment import ConfidenceBreakdown, EvidenceItem
from .schemas.common import DataKind

CLAIM_FORMULA = "conf = Q × (0.5 + 0.5·G) × K"
ASSESSMENT_FORMULA = "conf = weighted_mean(conf_claims; drivers ×2) × C × (0.7 + 0.3·D)"


def resolution_km(spatial_resolution: str) -> float:
    s = spatial_resolution or ""
    m = re.search(r"~\s*(\d+(?:\.\d+)?)\s*km", s)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*°", s)
    if m:
        return float(m.group(1)) * 111.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*km", s)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*m\b", s)
    if m:
        return float(m.group(1)) / 1000.0
    return 10.0


def spatial_factor(distance_km: Optional[float], spatial_resolution: str) -> float:
    d = distance_km or 0.0
    r = resolution_km(spatial_resolution)
    return round(math.exp(-max(0.0, d - 0.71 * r) / 50.0) * (1.0 - min(0.3, r / 150.0)), 3)


def temporal_factor(kind: DataKind, lead_h: Optional[float] = None, age_h: Optional[float] = None,
                    validity_h: float = 24.0, within_validity: bool = True) -> float:
    if kind == DataKind.FORECAST:
        return round(math.exp(-max(0.0, lead_h or 0.0) / 168.0), 3)
    if kind in (DataKind.ANALYSIS, DataKind.OBSERVED, DataKind.HISTORICAL):
        return round(math.exp(-max(0.0, (age_h or 0.0) - validity_h) / 48.0), 3)
    return 1.0 if within_validity else 0.5


def item_weight(authority: float, freshness: float, spatial: float, temporal: float) -> float:
    return round(authority * freshness * spatial * temporal, 4)


def independence_weights(items: Iterable[EvidenceItem]) -> list[float]:
    seen: set[str] = set()
    out = []
    for it in items:
        key = it.lineage or it.source_id
        out.append(0.3 if key in seen else 1.0)
        seen.add(key)
    return out


def claim_confidence(items: list[EvidenceItem], claim_level: Optional[str]) -> ConfidenceBreakdown:
    if not items:
        return ConfidenceBreakdown(evidence_quality=0, agreement=0, agreement_factor=0.5, completeness=1,
                                   independence=0, value=0, formula=CLAIM_FORMULA, weakest_link="no evidence")
    iw = independence_weights(items)
    tot = sum(iw)
    q = sum(w * it.weight for w, it in zip(iw, items)) / tot
    agree = [(it.supports is not False) for it in items]
    g = sum(w for w, a in zip(iw, agree) if a) / tot
    lineages = {it.lineage or it.source_id for it in items}
    k = 1.0 if len(lineages) >= 2 else 0.85
    val = q * (0.5 + 0.5 * g) * k
    comps = {"evidence quality (Q)": q, "agreement (0.5+0.5G)": 0.5 + 0.5 * g, "corroboration (K)": k}
    weakest_item = min(items, key=lambda it: it.weight)
    parts = {"authority": weakest_item.authority, "freshness": weakest_item.freshness,
             "spatial match": weakest_item.spatial, "temporal match": weakest_item.temporal}
    wp = min(parts, key=parts.get)
    weakest = min(comps, key=comps.get)
    notes = [f"{len(items)} evidence item(s) from {len(lineages)} independent lineage(s)"]
    if k < 1:
        notes.append("single independent lineage → corroboration penalty")
    return ConfidenceBreakdown(
        evidence_quality=round(q, 3), agreement=round(g, 3), agreement_factor=round(0.5 + 0.5 * g, 3),
        completeness=1.0, independence=round(len(lineages) / max(1, len(items)), 3), value=round(val, 3),
        formula=CLAIM_FORMULA,
        weakest_link=f"{weakest} = {comps[weakest]:.2f}; weakest item: {weakest_item.source} ({wp} {parts[wp]:.2f})",
        notes=notes)


def assessment_confidence(claims: list[tuple[ConfidenceBreakdown, bool]], completeness: float,
                          notes: Optional[list[str]] = None, coverage: float = 1.0) -> ConfidenceBreakdown:
    """claims: (breakdown, is_driver)."""
    if not claims:
        return ConfidenceBreakdown(evidence_quality=0, agreement=0, agreement_factor=0.5, completeness=completeness,
                                   independence=0, value=0, formula=ASSESSMENT_FORMULA, weakest_link="no claims",
                                   notes=notes or [])
    ws = [2.0 if d else 1.0 for _, d in claims]
    tot = sum(ws)
    mean = sum(w * c.value for w, (c, _) in zip(ws, claims)) / tot
    q = sum(w * c.evidence_quality for w, (c, _) in zip(ws, claims)) / tot
    g = sum(w * c.agreement for w, (c, _) in zip(ws, claims)) / tot
    val = mean * completeness * (0.7 + 0.3 * coverage)
    worst = min(claims, key=lambda x: x[0].value)[0]
    weakest = ("critical-source coverage" if coverage < 0.75 else
               "data completeness" if completeness < min(1.0, worst.value + 0.05) else worst.weakest_link)
    return ConfidenceBreakdown(evidence_quality=round(q, 3), agreement=round(g, 3), agreement_factor=round(0.5 + 0.5 * g, 3),
                               completeness=round(completeness, 3), independence=round(
                                   sum(c.independence for c, _ in claims) / len(claims), 3),
                               value=round(val, 3), formula=ASSESSMENT_FORMULA, weakest_link=weakest,
                               notes=(notes or []) + [f"{len(claims)} claim(s) aggregated; drivers weighted ×2",
                                                      f"critical-source coverage D = {coverage:.2f}"])
