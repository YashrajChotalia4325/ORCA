"""Source-conflict detection.

ORCA never averages away a disagreement. Every pair of sources reporting the
same variable for the same place/time window is compared against a
variable-specific tolerance, and against the decision thresholds. A conflict
is 'decision_relevant' when sources fall into different risk levels.
Resolution policy for safety-critical variables: use the conservative
(worst-case) value and reduce confidence via the agreement factor.
"""
from __future__ import annotations

from typing import Optional

from ..core.schemas.assessment import Conflict, ConflictEntry, RiskFactor
from ..core.schemas.common import DataKind, RiskLevel

TOLERANCE = {
    # variable: (absolute tolerance, relative tolerance)
    "wave_height": (0.5, 0.25),
    "wind_speed": (10.0, 0.30),
    "wind_gusts": (15.0, 0.30),
    "current_speed": (2.0, 0.50),
    "precipitation": (5.0, 1.0),
    "cape": (800.0, 0.5),
    "visibility": (3.0, 0.5),
    "sst": (1.0, 0.0),
}


def tolerance(var: str, values: list[float]) -> float:
    a, r = TOLERANCE.get(var, (0.0, 0.3))
    mean = sum(abs(v) for v in values) / len(values) if values else 0.0
    return max(a, r * mean)


def factor_conflicts(factors: list[RiskFactor], authority: dict[str, float], critical_ids: set[str]) -> list[Conflict]:
    out: list[Conflict] = []
    for f in factors:
        vals = [m for m in f.per_source if m.value is not None]
        if len(vals) < 2:
            continue
        nums = [m.value for m in vals]
        diff = max(nums) - min(nums)
        tol = tolerance(f.id, nums)
        levels = {m.level for m in vals}
        decision_relevant = len(levels) > 1
        if diff <= tol and not decision_relevant:
            continue
        severity = "decision_relevant" if decision_relevant else "material"
        hi = max(vals, key=lambda m: m.value)
        lo = min(vals, key=lambda m: m.value)
        entries = [ConflictEntry(source=m.source, source_id=m.source_id, value=m.value, units=m.units, time=m.at,
                                 kind=m.kind, authority=authority.get(m.source_id, 0.8), level=m.level) for m in vals]
        crit = f.id in critical_ids
        if decision_relevant:
            impact = (f"Sources place {f.label.lower()} in different risk levels "
                      f"({', '.join(sorted(l.value for l in levels))}). ")
            impact += ("The conservative level was used for the decision" if crit or f.level != RiskLevel.NOMINAL
                       else "Informational factor; level taken from worst case")
            impact += " and confidence is reduced through the agreement term."
        else:
            impact = "Values differ beyond tolerance but agree on the risk level; confidence reduced slightly."
        out.append(Conflict(
            id=f"conflict_{f.id}", variable=f.id,
            description=f"{f.label}: {hi.source} reports {hi.value:g} {f.units} vs {lo.source} {lo.value:g} {f.units} "
                        f"(Δ {diff:.2f} {f.units}, tolerance {tol:.2f})",
            severity=severity, entries=entries, difference=round(diff, 3), tolerance=round(tol, 3),
            resolution="Conservative policy: worst-case value retained; no averaging." if crit or decision_relevant
            else "Reported; worst-case retained.",
            impact=impact, decision_relevant=decision_relevant and (crit or f.level != RiskLevel.NOMINAL)))
    return out


def sst_satellite_vs_model(sat: Optional[float], sat_src: str, model: Optional[float], model_src: str,
                           sat_time=None, model_time=None) -> Optional[Conflict]:
    if sat is None or model is None:
        return None
    diff = abs(sat - model)
    tol = TOLERANCE["sst"][0]
    if diff <= tol:
        return None
    return Conflict(
        id="conflict_sst_sat_model", variable="sst",
        description=f"Sea-surface temperature: satellite analysis {sat:.2f} °C ({sat_src}) vs model {model:.2f} °C "
                    f"({model_src}), Δ {diff:.2f} °C",
        severity="material",
        entries=[ConflictEntry(source=sat_src, source_id="noaa_coastwatch", value=round(sat, 2), units="°C",
                               time=sat_time, kind=DataKind.ANALYSIS, authority=0.88),
                 ConflictEntry(source=model_src, source_id="om_smoc", value=round(model, 2), units="°C",
                               time=model_time, kind=DataKind.FORECAST, authority=0.88)],
        difference=round(diff, 2), tolerance=tol,
        resolution="Observation-based satellite analysis preferred for fisheries reasoning; model SST reported only.",
        impact="Does not affect the safety decision; lowers confidence of SST-dependent fisheries claims.")


def advisory_vs_models(advisory_level: RiskLevel, advisory_src: str, model_level: RiskLevel,
                       detail: str) -> Optional[Conflict]:
    if advisory_level in (RiskLevel.UNKNOWN, RiskLevel.NOMINAL) or model_level == RiskLevel.UNKNOWN:
        return None
    rank = {RiskLevel.NOMINAL: 0, RiskLevel.CAUTION: 1, RiskLevel.DANGER: 2}
    if rank[advisory_level] <= rank.get(model_level, 0):
        return None
    return Conflict(
        id="conflict_advisory_models", variable="official_advisory",
        description=f"{advisory_src} advisory is {advisory_level.value} while model-based factors indicate "
                    f"{model_level.value}. {detail}",
        severity="decision_relevant",
        entries=[ConflictEntry(source=advisory_src, source_id="advisory", value_text=advisory_level.value,
                               kind=DataKind.ADVISORY, authority=0.95, level=advisory_level),
                 ConflictEntry(source="Numerical models (worst case)", source_id="models", value_text=model_level.value,
                               kind=DataKind.FORECAST, authority=0.88, level=model_level)],
        resolution="Official advisory takes precedence (conservative).",
        impact="Decision raised to the advisory level; confidence reduced for disagreement.",
        decision_relevant=True)
