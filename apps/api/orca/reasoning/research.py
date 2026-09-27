"""Research analytics: period comparison, trend, correlation and hypothesis evaluation.

Strict epistemic separation:
    OBSERVATION  measured change in a variable (with test statistic)
    CORRELATION  statistical association between variables (never causal)
    HYPOTHESIS   physically-motivated explanation with explicit supporting /
                 contradicting evidence
    CONCLUSION   what the evidence does and does not establish
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
from scipy import stats

from ..core.schemas.provenance import TimeSeries


@dataclass
class PeriodStats:
    variable: str
    units: str
    current_mean: Optional[float]
    previous_mean: Optional[float]
    delta: Optional[float]
    pct_change: Optional[float]
    n_current: int
    n_previous: int
    p_value: Optional[float]
    slope_per_day: Optional[float]
    significant: bool
    source: str


@dataclass
class Correlation:
    a: str
    b: str
    r: Optional[float]
    p_value: Optional[float]
    n: int
    best_lag_days: Optional[int] = None
    best_lag_r: Optional[float] = None


@dataclass
class Hypothesis:
    id: str
    statement: str
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)
    status: str = "insufficient evidence"     # consistent | partially consistent | not supported | insufficient evidence
    score: float = 0.0


def period_stats(ts: Optional[TimeSeries], cur: tuple[datetime, datetime], prev: tuple[datetime, datetime]) -> Optional[PeriodStats]:
    if ts is None or not ts.times:
        return None
    c = [v for t, v in zip(ts.times, ts.values) if v is not None and cur[0] <= t <= cur[1]]
    p = [v for t, v in zip(ts.times, ts.values) if v is not None and prev[0] <= t < cur[0]]
    cm = float(np.mean(c)) if c else None
    pm = float(np.mean(p)) if p else None
    pv = None
    if len(c) >= 3 and len(p) >= 3:
        pv = float(stats.ttest_ind(c, p, equal_var=False).pvalue)
    xs = [(t - ts.times[0]).total_seconds() / 86400 for t, v in zip(ts.times, ts.values) if v is not None]
    ys = [v for v in ts.values if v is not None]
    slope = float(np.polyfit(xs, ys, 1)[0]) if len(xs) >= 4 else None
    delta = (cm - pm) if cm is not None and pm is not None else None
    pct = (100 * delta / pm) if delta is not None and pm not in (0, None) else None
    return PeriodStats(ts.variable, ts.units, cm, pm, delta, pct, len(c), len(p), pv, slope,
                       bool(pv is not None and pv < 0.05), ts.provenance.source)


def correlate(a: Optional[TimeSeries], b: Optional[TimeSeries], max_lag: int = 5) -> Optional[Correlation]:
    if a is None or b is None:
        return None
    da = {t.date(): v for t, v in zip(a.times, a.values) if v is not None}
    db = {t.date(): v for t, v in zip(b.times, b.values) if v is not None}
    common = sorted(set(da) & set(db))
    if len(common) < 6:
        return Correlation(a.variable, b.variable, None, None, len(common))
    x = np.array([da[d] for d in common])
    y = np.array([db[d] for d in common])
    if np.std(x) == 0 or np.std(y) == 0:
        return Correlation(a.variable, b.variable, None, None, len(common))
    r, p = stats.pearsonr(x, y)
    best = (0, float(r))
    for lag in range(1, max_lag + 1):
        if len(x) - lag < 6:
            break
        rr = float(np.corrcoef(x[:-lag], y[lag:])[0, 1])
        if abs(rr) > abs(best[1]):
            best = (lag, rr)
    return Correlation(a.variable, b.variable, float(r), float(p), len(common), best[0], best[1])


def hypotheses(target: str, st: dict[str, Optional[PeriodStats]], corr: Optional[Correlation],
               month: int, west_coast: bool, chl_gapfilled: bool) -> list[Hypothesis]:
    """Rule-based hypothesis generation and evaluation (no LLM)."""
    H: list[Hypothesis] = []
    chl, sst, wind, anom = st.get("chlorophyll"), st.get("sst"), st.get("wind_speed"), st.get("sst_anomaly")

    def d(s: Optional[PeriodStats]) -> Optional[float]:
        return s.delta if s else None

    dchl, dsst, dwind = d(chl), d(sst), d(wind)

    h1 = Hypothesis("H1", "Reduced vertical mixing / weakened upwelling (warmer, more stratified surface layer) "
                          "limited nutrient supply to phytoplankton.")
    if dchl is not None and dchl < 0:
        h1.supporting.append(f"chlorophyll-a changed {dchl:+.2f} mg/m³")
    elif dchl is not None:
        h1.contradicting.append(f"chlorophyll-a did not decline ({dchl:+.2f} mg/m³)")
    if dsst is not None and dsst > 0.2:
        h1.supporting.append(f"SST warmed {dsst:+.2f} °C")
    elif dsst is not None and dsst < -0.2:
        h1.contradicting.append(f"SST cooled {dsst:+.2f} °C (upwelling signature, not stratification)")
    if dwind is not None and dwind < -2:
        h1.supporting.append(f"mean wind speed dropped {dwind:+.1f} km/h (less wind-driven mixing)")
    elif dwind is not None and dwind > 2:
        h1.contradicting.append(f"mean wind speed increased {dwind:+.1f} km/h")
    if corr and corr.r is not None and corr.r < -0.3 and (corr.p_value or 1) < 0.05:
        h1.supporting.append(f"SST and chlorophyll negatively correlated (r = {corr.r:.2f}, n = {corr.n})")
    H.append(h1)

    if west_coast:
        h2 = Hypothesis("H2", "Seasonal transition: the south-west-monsoon coastal upwelling along India's west coast "
                              "(peaking Jul–Sep) is relaxing.")
        if month in (9, 10, 11):
            h2.supporting.append(f"period falls in month {month}, when west-coast upwelling typically relaxes")
        else:
            h2.contradicting.append(f"month {month} is outside the usual relaxation season (Sep–Nov)")
        if dsst is not None and dsst > 0:
            h2.supporting.append("warming SST consistent with upwelling relaxation")
        if dchl is not None and dchl < 0:
            h2.supporting.append("chlorophyll decline consistent with reduced nutrient supply")
        H.append(h2)

    h3 = Hypothesis("H3", "Observation artefact: cloud cover and DINEOF gap-filling or coastal turbidity bias the "
                          "satellite chlorophyll signal.")
    if chl_gapfilled:
        h3.supporting.append("chlorophyll product is DINEOF gap-filled (reconstructed under cloud)")
    if month in (6, 7, 8, 9):
        h3.supporting.append("monsoon months have persistent cloud over the region")
    if chl and chl.p_value is not None and chl.p_value < 0.01:
        h3.contradicting.append(f"change is statistically strong (p = {chl.p_value:.3f}), less likely pure noise")
    H.append(h3)

    h4 = Hypothesis("H4", "Positive SST anomaly (marine heatwave-like conditions) suppressing productivity.")
    if anom and anom.current_mean is not None:
        if anom.current_mean > 1.0:
            h4.supporting.append(f"mean SST anomaly {anom.current_mean:+.2f} °C vs climatology")
        else:
            h4.contradicting.append(f"SST anomaly only {anom.current_mean:+.2f} °C")
    H.append(h4)

    for h in H:
        s, c = len(h.supporting), len(h.contradicting)
        h.score = round((s - 1.5 * c) / max(1, s + c), 2)
        if s == 0 and c == 0:
            h.status = "insufficient evidence"
        elif c == 0 and s >= 2:
            h.status = "consistent"
        elif s > c:
            h.status = "partially consistent"
        else:
            h.status = "not supported"
    H.sort(key=lambda h: -h.score)
    return H


def fmt_p(p: Optional[float]) -> str:
    if p is None:
        return "n/a"
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def summarize_change(s: PeriodStats) -> str:
    if s.delta is None:
        return f"{s.variable}: insufficient data for comparison"
    direction = "increased" if s.delta > 0 else "decreased"
    pct = f" ({s.pct_change:+.1f} %)" if s.pct_change is not None and math.isfinite(s.pct_change) else ""
    sig = "statistically significant" if s.significant else "not statistically significant"
    return (f"{s.variable} {direction} from {s.previous_mean:.2f} to {s.current_mean:.2f} {s.units}{pct}; "
            f"Welch t-test p = {fmt_p(s.p_value)} ({sig}, n = {s.n_current}/{s.n_previous} days)")
