"""ORCA deterministic marine risk model (orca-risk-1.0).

No LLM participates in this computation. Inputs are normalised, provenance-
tagged values; outputs are a decision (GO / CAUTION / DONT_GO /
INSUFFICIENT_DATA), a 0-100 risk index, per-factor levels and the list of
decision rules that fired.

Thresholds are ORCA defaults, configurable per deployment, and MUST be
validated with IMD / INCOIS / DG Shipping before operational use. They are
informed by IMD's fishermen-warning practice (squally weather ≈ 45–55 km/h
gusting 65 km/h => "fishermen advised not to venture") and common small-craft
seamanship limits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .schemas.assessment import ModelValue, RiskAssessment, RiskFactor, ThresholdSpec
from .schemas.common import DataKind, Decision, FreshnessStatus, GeoPoint, RiskLevel

T = ThresholdSpec
BASIS_WIND = "ORCA default informed by IMD fishermen-warning criteria (squally winds 45–55 km/h); configurable"
BASIS_WAVE = "ORCA default small-craft / vessel-class sea-state limits; configurable"
BASIS_GEN = "ORCA default; configurable"

THRESHOLDS: dict[str, dict[str, ThresholdSpec]] = {
    "small_craft": {
        "wind_speed": T(caution=28, danger=45, units="km/h", basis=BASIS_WIND),
        "wind_gusts": T(caution=40, danger=60, units="km/h", basis=BASIS_WIND),
        "wave_height": T(caution=1.5, danger=2.5, units="m", basis=BASIS_WAVE),
        "current_speed": T(caution=3.7, danger=5.6, units="km/h", basis=BASIS_GEN),
        "precipitation": T(caution=5, danger=15, units="mm/h", basis=BASIS_GEN),
        "cape": T(caution=1500, danger=2500, units="J/kg", basis="convective (lightning) potential from model CAPE; not observed lightning"),
        "visibility": T(caution=4, danger=1, direction="below", units="km", basis=BASIS_GEN),
        "cyclone_distance": T(caution=800, danger=300, direction="below", units="km", basis="distance to active tropical cyclone centre"),
        "boundary_distance": T(caution=10, danger=2, direction="below", units="km", basis="proximity to international maritime boundary (IMBL)"),
    },
    "mechanized": {
        "wind_speed": T(caution=40, danger=55, units="km/h", basis=BASIS_WIND),
        "wind_gusts": T(caution=55, danger=75, units="km/h", basis=BASIS_WIND),
        "wave_height": T(caution=2.0, danger=3.0, units="m", basis=BASIS_WAVE),
        "current_speed": T(caution=4.6, danger=7.4, units="km/h", basis=BASIS_GEN),
        "precipitation": T(caution=8, danger=20, units="mm/h", basis=BASIS_GEN),
        "cape": T(caution=2000, danger=3000, units="J/kg", basis="convective (lightning) potential from model CAPE; not observed lightning"),
        "visibility": T(caution=2, danger=0.5, direction="below", units="km", basis=BASIS_GEN),
        "cyclone_distance": T(caution=600, danger=250, direction="below", units="km", basis="distance to active tropical cyclone centre"),
        "boundary_distance": T(caution=10, danger=2, direction="below", units="km", basis="proximity to international maritime boundary (IMBL)"),
    },
    "large_vessel": {
        "wind_speed": T(caution=55, danger=75, units="km/h", basis=BASIS_WIND),
        "wind_gusts": T(caution=75, danger=100, units="km/h", basis=BASIS_WIND),
        "wave_height": T(caution=3.5, danger=5.0, units="m", basis=BASIS_WAVE),
        "current_speed": T(caution=5.6, danger=9.3, units="km/h", basis=BASIS_GEN),
        "precipitation": T(caution=15, danger=30, units="mm/h", basis=BASIS_GEN),
        "cape": T(caution=2500, danger=3500, units="J/kg", basis="convective (lightning) potential from model CAPE; not observed lightning"),
        "visibility": T(caution=1, danger=0.3, direction="below", units="km", basis=BASIS_GEN),
        "cyclone_distance": T(caution=400, danger=200, direction="below", units="km", basis="distance to active tropical cyclone centre"),
    },
}

FACTOR_META = {
    # id: (label, critical, weight)
    "wind_speed": ("Sustained wind", True, 1.0),
    "wave_height": ("Significant wave height", True, 1.0),
    "wind_gusts": ("Wind gusts", False, 0.8),
    "current_speed": ("Surface current", False, 0.5),
    "precipitation": ("Rainfall rate", False, 0.5),
    "cape": ("Thunderstorm / lightning potential", False, 0.5),
    "visibility": ("Visibility", False, 0.6),
    "cyclone_distance": ("Tropical cyclone proximity", False, 1.0),
    "official_advisory": ("Official warnings (IMD / INCOIS)", False, 1.0),
    "boundary_distance": ("International maritime boundary", False, 0.7),
}

MODEL_VERSION = "orca-risk-1.0"


@dataclass
class Sample:
    time: Optional[datetime]
    value: Optional[float]
    location: Optional[GeoPoint] = None


@dataclass
class SourceSamples:
    source: str
    source_id: str
    kind: DataKind
    samples: list[Sample]
    freshness: FreshnessStatus = FreshnessStatus.LIVE
    units: str = ""
    meta: dict = field(default_factory=dict)      # provenance / lineage / grid distance for the evidence agent


@dataclass
class FactorInput:
    factor_id: str
    sources: list[SourceSamples] = field(default_factory=list)
    note: str = ""


@dataclass
class AdvisoryInput:
    available: bool
    level: RiskLevel = RiskLevel.NOMINAL
    items: list[dict] = field(default_factory=list)
    note: str = ""


def level_for(value: Optional[float], th: ThresholdSpec) -> RiskLevel:
    if value is None:
        return RiskLevel.UNKNOWN
    if th.direction == "above":
        return RiskLevel.DANGER if value >= th.danger else RiskLevel.CAUTION if value >= th.caution else RiskLevel.NOMINAL
    return RiskLevel.DANGER if value <= th.danger else RiskLevel.CAUTION if value <= th.caution else RiskLevel.NOMINAL


def score_for(value: Optional[float], th: ThresholdSpec) -> float:
    """0 → benign, 0.5 at the caution threshold, 1.0 at/after the danger threshold."""
    if value is None:
        return 0.0
    if th.direction == "above":
        lo, c, d = 0.5 * th.caution, th.caution, th.danger
        if value <= lo:
            return 0.0
        if value <= c:
            return 0.5 * (value - lo) / (c - lo)
        return min(1.0, 0.5 + 0.5 * (value - c) / (d - c))
    # below: smaller is worse
    hi, c, d = th.caution * 2, th.caution, th.danger
    if value >= hi:
        return 0.0
    if value >= c:
        return 0.5 * (hi - value) / (hi - c)
    return min(1.0, 0.5 + 0.5 * (c - value) / max(1e-9, c - d))


def _worst(samples: list[Sample], th: ThresholdSpec) -> Optional[Sample]:
    vals = [s for s in samples if s.value is not None]
    if not vals:
        return None
    return max(vals, key=lambda s: s.value) if th.direction == "above" else min(vals, key=lambda s: s.value)


def _onset(samples: list[Sample], th: ThresholdSpec) -> Optional[datetime]:
    hits = [s.time for s in samples if s.value is not None and s.time is not None and
            level_for(s.value, th) in (RiskLevel.CAUTION, RiskLevel.DANGER)]
    return min(hits) if hits else None


def evaluate_factor(fid: str, inp: FactorInput, th: ThresholdSpec) -> RiskFactor:
    label, critical, _ = FACTOR_META[fid]
    per: list[ModelValue] = []
    worst_overall: tuple[Optional[Sample], Optional[SourceSamples]] = (None, None)
    onsets = []
    for src in inp.sources:
        w = _worst(src.samples, th)
        if w is None:
            continue
        lvl = level_for(w.value, th)
        per.append(ModelValue(source=src.source, source_id=src.source_id, value=round(w.value, 2), units=th.units,
                              at=w.time, location=w.location, level=lvl, kind=src.kind))
        o = _onset(src.samples, th)
        if o:
            onsets.append(o)
        cur = worst_overall[0]
        if cur is None or (w.value > cur.value if th.direction == "above" else w.value < cur.value):
            worst_overall = (w, src)
    if not per:
        return RiskFactor(id=fid, label=label, critical=critical, level=RiskLevel.UNKNOWN, units=th.units,
                          threshold=th, available=False,
                          explanation=inp.note or f"No usable {label.lower()} data from any source.")
    w, src = worst_overall
    vals = [m.value for m in per if m.value is not None]
    spread = round(max(vals) - min(vals), 2) if len(vals) > 1 else None
    lvl = level_for(w.value, th)
    expl = (f"Worst value {w.value:.1f} {th.units} ({src.source}); caution ≥ {th.caution:g}, danger ≥ {th.danger:g} {th.units}"
            if th.direction == "above" else
            f"Minimum {w.value:.1f} {th.units} ({src.source}); caution ≤ {th.caution:g}, danger ≤ {th.danger:g} {th.units}")
    if len(per) > 1:
        expl += f"; {len(per)} sources, spread {spread:g} {th.units} — conservative (worst-case) value used"
    return RiskFactor(id=fid, label=label, critical=critical, level=lvl, value=round(w.value, 2), units=th.units,
                      at=w.time, location=w.location, threshold=th, score=round(score_for(w.value, th), 3),
                      per_source=per, spread=spread, onset=min(onsets) if onsets else None, explanation=expl)


def evaluate(vessel_class: str, window_start: datetime, window_end: datetime,
             inputs: dict[str, FactorInput], advisory: Optional[AdvisoryInput] = None,
             zone_notes: Optional[list[str]] = None) -> RiskAssessment:
    ths = THRESHOLDS[vessel_class]
    factors: list[RiskFactor] = []
    for fid, th in ths.items():
        inp = inputs.get(fid)
        if inp is None:
            if fid in ("cyclone_distance", "boundary_distance"):
                continue  # evaluated only when a check was performed
            inp = FactorInput(fid)
        factors.append(evaluate_factor(fid, inp, th))
    if advisory is not None:
        label, critical, _ = FACTOR_META["official_advisory"]
        if advisory.available:
            factors.append(RiskFactor(id="official_advisory", label=label, critical=False, level=advisory.level,
                                      score={RiskLevel.DANGER: 1.0, RiskLevel.CAUTION: 0.6}.get(advisory.level, 0.0),
                                      explanation=advisory.note or f"{len(advisory.items)} official warning(s) in effect",
                                      available=True))
        else:
            factors.append(RiskFactor(id="official_advisory", label=label, critical=False, level=RiskLevel.UNKNOWN,
                                      available=False, explanation=advisory.note or "Official national warnings not accessible"))

    rules: list[str] = []
    adjustments: list[str] = []
    for f in factors:
        # R2b: convective potential is model-inferred (CAPE gated by co-located model rain), not observed lightning.
        # It may raise the decision to CAUTION but never on its own to DON'T GO.
        if f.id == "cape" and f.level == RiskLevel.DANGER:
            f.level = RiskLevel.CAUTION
            f.score = min(f.score, 0.6)
            f.explanation += " — capped at CAUTION (R2b: model-inferred potential, not observed lightning)"
    missing = [f.id for f in factors if f.critical and not f.available]
    danger = [f for f in factors if f.level == RiskLevel.DANGER]
    caution = [f for f in factors if f.level == RiskLevel.CAUTION]

    if missing:
        decision = Decision.INSUFFICIENT_DATA
        rules.append(f"R1 critical factor(s) unavailable: {', '.join(missing)} → no reliable assessment possible")
        drivers = missing
    elif danger:
        decision = Decision.DONT_GO
        rules.append("R2 at least one factor at DANGER level → DON'T GO: " + ", ".join(f.label for f in danger))
        drivers = [f.id for f in danger]
    elif caution:
        decision = Decision.CAUTION
        rules.append("R4 at least one factor at CAUTION level → CAUTION: " + ", ".join(f.label for f in caution))
        drivers = [f.id for f in caution]
    else:
        decision = Decision.GO
        rules.append("R6 all evaluated factors below caution thresholds → GO (not a guarantee of safety)")
        drivers = []

    # R5: conservative floor for critical factors whose sources straddle the caution threshold
    if decision == Decision.GO:
        for f in factors:
            if f.critical and f.per_source and f.threshold:
                lv = {m.level for m in f.per_source}
                if RiskLevel.CAUTION in lv or RiskLevel.DANGER in lv:
                    decision = Decision.CAUTION
                    adjustments.append(f"R5 sources disagree on {f.label} across the caution threshold → CAUTION floor")
                    drivers.append(f.id)
    # R3: stale-only critical inputs
    stale_critical = [fid for fid in ("wind_speed", "wave_height") if inputs.get(fid) and inputs[fid].sources and
                      all(s.freshness == FreshnessStatus.STALE for s in inputs[fid].sources)]
    if stale_critical and decision == Decision.GO:
        decision = Decision.CAUTION
        adjustments.append("R3 all sources for " + ", ".join(stale_critical) + " are STALE → CAUTION floor")
        drivers += stale_critical
    if zone_notes:
        adjustments += zone_notes

    avail = [f for f in factors if f.available]
    max_w = max((f.score * FACTOR_META[f.id][2] for f in avail), default=0.0)
    crit = [f.score for f in avail if f.critical]
    mean_c = sum(crit) / len(crit) if crit else 0.0
    risk_index: Optional[float] = round(100 * min(1.0, 0.7 * max_w + 0.3 * mean_c), 1)
    if decision == Decision.INSUFFICIENT_DATA:
        risk_index = None

    return RiskAssessment(decision=decision, risk_index=risk_index,
                          vessel_class=vessel_class, window_start=window_start, window_end=window_end,
                          factors=factors, drivers=drivers, rules_fired=rules, missing_critical=missing,
                          conservative_adjustments=adjustments, model_version=MODEL_VERSION)


def point_risk(vessel_class: str, values: dict[str, Optional[float]]) -> tuple[float, RiskLevel, list[str]]:
    """Instantaneous risk at one location/time from normalised values (used for route cost & heatmaps)."""
    ths = THRESHOLDS[vessel_class]
    best, lvl, drivers = 0.0, RiskLevel.NOMINAL, []
    known = 0
    for fid in ("wave_height", "wind_speed", "wind_gusts", "current_speed", "precipitation"):
        v = values.get(fid)
        if v is None or fid not in ths:
            continue
        known += 1
        s = score_for(v, ths[fid]) * FACTOR_META[fid][2]
        l = level_for(v, ths[fid])
        if l in (RiskLevel.CAUTION, RiskLevel.DANGER):
            drivers.append(fid)
        if s > best:
            best = s
        if l == RiskLevel.DANGER or (l == RiskLevel.CAUTION and lvl == RiskLevel.NOMINAL):
            lvl = l
    if known == 0:
        return 0.0, RiskLevel.UNKNOWN, []
    return round(best, 3), lvl, drivers


def score_array(values, th: ThresholdSpec):
    """Vectorised score_for() for numpy arrays (NaN → 0)."""
    import numpy as np
    v = np.nan_to_num(np.asarray(values, dtype=float), nan=0.0 if th.direction == "above" else 1e9)
    if th.direction == "above":
        lo, c, d = 0.5 * th.caution, th.caution, th.danger
        s = np.where(v <= lo, 0.0, np.where(v <= c, 0.5 * (v - lo) / (c - lo), 0.5 + 0.5 * (v - c) / (d - c)))
    else:
        hi, c, d = th.caution * 2, th.caution, th.danger
        s = np.where(v >= hi, 0.0, np.where(v >= c, 0.5 * (hi - v) / (hi - c), 0.5 + 0.5 * (c - v) / max(1e-9, c - d)))
    return np.clip(s, 0.0, 1.0)


def risk_cube(vessel_class: str, fields: dict):
    """Max weighted factor score over wave / wind / gust / current / rain arrays of equal shape."""
    import numpy as np
    ths = THRESHOLDS[vessel_class]
    out = None
    for fid in ("wave_height", "wind_speed", "wind_gusts", "current_speed", "precipitation"):
        a = fields.get(fid)
        if a is None or fid not in ths:
            continue
        s = score_array(a, ths[fid]) * FACTOR_META[fid][2]
        out = s if out is None else np.maximum(out, s)
    return out
