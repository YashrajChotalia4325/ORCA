"""Clock abstraction. LIVE uses wall-clock UTC; REPLAY/DEMO use a virtual 'now'."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)


def fmt_ist(dt: datetime | None, with_date: bool = True) -> str:
    if dt is None:
        return "n/a"
    d = to_ist(dt)
    return d.strftime("%d %b %H:%M IST" if with_date else "%H:%M IST")


def fmt_utc(dt: datetime | None) -> str:
    if dt is None:
        return "n/a"
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%MZ")


def floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def parse_utc(s: str) -> datetime:
    """Parse an ISO timestamp; naive values are interpreted as UTC (Open-Meteo GMT)."""
    s = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def human_age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown age"
    s = abs(seconds)
    if s < 90:
        return f"{int(s)} s"
    if s < 5400:
        return f"{int(round(s / 60))} min"
    if s < 172800:
        return f"{s / 3600:.1f} h"
    return f"{s / 86400:.1f} days"


class Clock:
    def __init__(self, fixed: datetime | None = None):
        self._fixed = fixed
        self._started = utcnow()

    @property
    def virtual(self) -> bool:
        return self._fixed is not None

    def now(self) -> datetime:
        if self._fixed is None:
            return utcnow()
        # advance virtual time with wall time so ages still tick during a run
        return self._fixed + (utcnow() - self._started)

    def shifted(self, **kw) -> datetime:
        return self.now() + timedelta(**kw)
