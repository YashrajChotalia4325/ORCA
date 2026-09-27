"""Formal data freshness engine.

Two independent clocks are tracked for every datum:

* **product age**   = now - last_updated   (model run availability, satellite product time,
                                            bulletin issue time)
* **retrieval age** = now - retrieved_at   (when ORCA actually fetched it)

Status rules (evaluated in order):

1. no data                                         -> UNAVAILABLE
2. mode == REPLAY                                  -> REPLAY    (never LIVE)
3. mode == DEMO                                    -> SIMULATED (never LIVE)
4. reference data with no refresh cycle            -> STATIC
5. product age > (expected interval + expected latency) * 1.25 grace
                                                   -> STALE
6. retrieval age <= 15 min                         -> LIVE
7. retrieval age <= 60 min                         -> RECENT
8. otherwise                                       -> STALE

The confidence factor attached to each status is documented in REASONING.md.
"""
from __future__ import annotations

from datetime import datetime

from .clock import human_age
from .schemas.common import DataMode, FreshnessStatus
from .schemas.provenance import Freshness

LIVE_MAX_RETRIEVAL_S = 15 * 60
RECENT_MAX_RETRIEVAL_S = 60 * 60
PRODUCT_GRACE = 1.25

FACTORS = {
    FreshnessStatus.LIVE: 1.0,
    FreshnessStatus.RECENT: 0.95,
    FreshnessStatus.STALE: 0.6,
    FreshnessStatus.UNAVAILABLE: 0.0,
    FreshnessStatus.REPLAY: 1.0,       # scored as at recording time; labelled REPLAY everywhere
    FreshnessStatus.SIMULATED: 1.0,    # scored normally so demo pipelines behave realistically
    FreshnessStatus.STATIC: 0.9,
}


def assess(
    *,
    now: datetime,
    mode: DataMode,
    last_updated: datetime | None,
    retrieved_at: datetime | None,
    expected_update_interval_s: int | None,
    expected_latency_s: int | None = 0,
    from_cache: bool = False,
    has_data: bool = True,
    static: bool = False,
) -> Freshness:
    age = (now - last_updated).total_seconds() if last_updated else None
    r_age = (now - retrieved_at).total_seconds() if retrieved_at else None

    if not has_data:
        status = FreshnessStatus.UNAVAILABLE
    elif mode == DataMode.REPLAY:
        status = FreshnessStatus.REPLAY
    elif mode == DataMode.DEMO:
        status = FreshnessStatus.SIMULATED
    elif static:
        status = FreshnessStatus.STATIC
    elif (age is not None and expected_update_interval_s
          and age > (expected_update_interval_s + (expected_latency_s or 0)) * PRODUCT_GRACE):
        status = FreshnessStatus.STALE
    elif r_age is not None and r_age <= LIVE_MAX_RETRIEVAL_S:
        status = FreshnessStatus.LIVE
    elif r_age is not None and r_age <= RECENT_MAX_RETRIEVAL_S:
        status = FreshnessStatus.RECENT
    else:
        status = FreshnessStatus.STALE

    return Freshness(
        last_updated=last_updated,
        retrieved_at=retrieved_at,
        expected_update_interval_s=expected_update_interval_s,
        expected_latency_s=expected_latency_s,
        age_s=age,
        retrieval_age_s=r_age,
        from_cache=from_cache,
        status=status,
        label=label(status, age, r_age, from_cache, retrieved_at),
        factor=FACTORS[status],
    )


def label(status: FreshnessStatus, age: float | None, r_age: float | None, from_cache: bool,
          retrieved_at: datetime | None = None) -> str:
    if status == FreshnessStatus.UNAVAILABLE:
        return "unavailable"
    if status == FreshnessStatus.SIMULATED:
        return "simulated (demo)"
    if status == FreshnessStatus.STATIC:
        return "static reference"
    parts = []
    if status == FreshnessStatus.REPLAY:
        parts.append("REPLAY — recorded " + (retrieved_at.strftime("%Y-%m-%d %H:%MZ") if retrieved_at else "earlier"))
        if age is not None:
            parts.append(f"product was {human_age(age)} old at recording")
        return " · ".join(parts)
    if r_age is not None:
        parts.append(f"fetched {human_age(r_age)} ago" + (" (cache)" if from_cache else ""))
    if age is not None:
        parts.append(f"product updated {human_age(age)} ago")
    return " · ".join(parts)


def summarize(items: list[Freshness]) -> dict:
    counts: dict[str, int] = {}
    for f in items:
        counts[f.status.value] = counts.get(f.status.value, 0) + 1
    worst = min((f.factor for f in items), default=0.0)
    return {"counts": counts, "worst_factor": worst}
