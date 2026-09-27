"""Deterministic temporal resolution.

Natural-language time expressions are resolved to an explicit UTC window in
the user's display zone (IST by default). Every resolution records the rule
that fired and any assumption made (e.g. an unstated trip duration), so the
UI can show "Tomorrow 05:00–11:00 IST (assumed 6 h trip)" instead of an
ambiguous "tomorrow morning".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional

from .clock import IST, UTC
from .schemas.common import TimeWindow

DEFAULT_TRIP_H = 6

# multilingual cue words (lower-cased; scripts without case are matched as-is)
TOMORROW = ["tomorrow", "tmrw", "tommorow", "कल", "उद्या", "நாளை", "రేపు", "ನಾಳೆ", "നാളെ", "আগামীকাল", "কাল"]
TODAY = ["today", "आज", "இன்று", "ఈరోజు", "ఈ రోజు", "ಇಂದು", "ഇന്ന്", "আজ"]
TONIGHT = ["tonight", "आज रात", "இன்றிரவு", "ఈ రాత్రి", "ಇಂದು ರಾತ್ರಿ", "ഇന്ന് രാത്രി", "আজ রাতে"]
NOW = ["right now", "now", "currently", "at the moment", "अभी", "आत्ता", "இப்போது", "ఇప్పుడు", "ಈಗ", "ഇപ്പോൾ", "এখন"]
PARTS = {
    "dawn": (4, 7), "early morning": (4, 8),
    "morning": (5, 11), "afternoon": (12, 17), "evening": (17, 20), "night": (20, 29),
    "सुबह": (5, 11), "सकाळी": (5, 11), "காலை": (5, 11), "ఉదయం": (5, 11), "ಬೆಳಿಗ್ಗೆ": (5, 11), "ರಾವಿಲೆ": (5, 11),
    "രാവിലെ": (5, 11), "সকালে": (5, 11), "সকাল": (5, 11),
    "दोपहर": (12, 17), "मध्याह्न": (12, 17), "மதியம்": (12, 17), "మధ్యాహ్నం": (12, 17), "ಮಧ್ಯಾಹ್ನ": (12, 17),
    "ഉച്ച": (12, 17), "দুপুর": (12, 17),
    "शाम": (17, 20), "संध्याकाळी": (17, 20), "மாலை": (17, 20), "సాయంత్రం": (17, 20), "ಸಂಜೆ": (17, 20), "വൈകുന്നേരം": (17, 20), "সন্ধ্যা": (17, 20),
    "रात": (20, 29), "रात्री": (20, 29), "இரவு": (20, 29), "రాత్రి": (20, 29), "ರಾತ್ರಿ": (20, 29), "രാത്രി": (20, 29), "রাত": (20, 29),
}
OCLOCK = r"(?:बजे|वाजता|மணிக்கு|மணி|గంటలకు|గంటకు|ಗಂಟೆಗೆ|മണിക്ക്|মণিক্ক|টায়|টা)"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


@dataclass
class TemporalResult:
    window: TimeWindow
    comparison: Optional[TimeWindow] = None
    explicit: bool = False


def _contains(text: str, words: list[str]) -> Optional[str]:
    for w in sorted(words, key=len, reverse=True):
        if re.search(r"[a-z]", w):
            if re.search(rf"\b{re.escape(w)}\b", text):
                return w
        elif w in text:
            return w
    return None


def _local(day: datetime, h: float) -> datetime:
    base = datetime.combine(day.date(), time(0, 0), tzinfo=IST)
    return base + timedelta(hours=h)


def _clock_time(text: str) -> Optional[tuple[int, int]]:
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", text)
    if m:
        h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
        if m.group(3).startswith("p"):
            h += 12
        return h, mi
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\s*(?:hrs|h|ist)?\b", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(rf"(\d{{1,2}})\s*{OCLOCK}", text)
    if m:
        return int(m.group(1)) % 24, 0
    m = re.search(r"\bat\s+(\d{1,2})\b(?!\s*(?:km|nm|nautical|hours?|hrs?|days?|%))", text)
    if m:
        return int(m.group(1)) % 24, 0
    return None


def _duration_hours(text: str) -> Optional[float]:
    m = re.search(r"\bfor\s+(\d{1,2})\s*(?:hours?|hrs?|h)\b", text)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d{1,2})\s*(?:घंटे|तास|மணி நேரம்|గంటలు|ಗಂಟೆ|മണിക്കൂർ|ঘণ্টা)", text)
    return float(m.group(1)) if m else None


def resolve(text: str, now: datetime, *, activity: Optional[str] = None,
            default_hours: float = 24.0) -> TemporalResult:
    """Resolve a time expression in `text` relative to `now` (UTC)."""
    t = text.lower()
    now_l = now.astimezone(IST)
    assumptions: list[str] = []

    def win(start_l: datetime, end_l: datetime, label: str, rule: str, explicit: bool = True) -> TemporalResult:
        return TemporalResult(TimeWindow(start=start_l.astimezone(UTC), end=end_l.astimezone(UTC), label=label,
                                         rule=rule, assumptions=assumptions), explicit=explicit)

    # --- comparison: "this week vs last week", "compare ... with last week"
    if re.search(r"(this week).*(last|previous) week|(last|previous) week.*(this week)|compare.*week", t):
        end = now_l
        cur = win(end - timedelta(days=7), end, "Last 7 days", "compare_week").window
        prev = TimeWindow(start=(end - timedelta(days=14)).astimezone(UTC), end=(end - timedelta(days=7)).astimezone(UTC),
                          label="Previous 7 days", rule="compare_week")
        return TemporalResult(cur, prev, True)

    # --- past N days / weeks (research)
    m = re.search(r"(?:past|last|previous|over the last|over the past)\s+(\d{1,3})\s*(day|days|week|weeks|month|months)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        days = n * (7 if unit.startswith("week") else 30 if unit.startswith("month") else 1)
        cur = TimeWindow(start=(now_l - timedelta(days=days)).astimezone(UTC), end=now, label=f"Last {days} days",
                         rule="past_n_days", assumptions=[f"compared against the preceding {days} days"])
        prev = TimeWindow(start=(now_l - timedelta(days=2 * days)).astimezone(UTC),
                          end=(now_l - timedelta(days=days)).astimezone(UTC), label=f"Preceding {days} days",
                          rule="past_n_days")
        return TemporalResult(cur, prev, True)
    if re.search(r"\b(last|past|previous) week\b", t):
        cur = TimeWindow(start=(now_l - timedelta(days=7)).astimezone(UTC), end=now, label="Last 7 days", rule="last_week")
        prev = TimeWindow(start=(now_l - timedelta(days=14)).astimezone(UTC), end=(now_l - timedelta(days=7)).astimezone(UTC),
                          label="Preceding 7 days", rule="last_week")
        return TemporalResult(cur, prev, True)

    # --- next N hours / days
    m = re.search(r"(?:next|coming|upcoming|within(?: the)?(?: next)?)\s+(\d{1,3})\s*(hours?|hrs?|h|days?)\b", t) or \
        re.search(r"(\d{1,3})\s*(hours?|hrs?)\s+(?:ahead|from now)", t)
    if m:
        n = int(m.group(1))
        hours = n * 24 if m.group(2).startswith("d") else n
        return win(now_l, now_l + timedelta(hours=hours), f"Next {hours} h", "next_n_hours")
    m = re.search(r"(?:अगले|पुढील|அடுத்த|తదుపరి|ಮುಂದಿನ|അടുത്ത|পরবর্তী)\s*(\d{1,3})\s*(?:घंटे|तास|மணி|గంట|ಗಂಟೆ|മണിക്കൂർ|ঘণ্টা)", t)
    if m:
        hours = int(m.group(1))
        return win(now_l, now_l + timedelta(hours=hours), f"Next {hours} h", "next_n_hours")

    # --- day anchor
    day = None
    day_label = ""
    if _contains(t, TONIGHT):
        s = _local(now_l, 20)
        return win(max(s, now_l), _local(now_l, 29), "Tonight 20:00–05:00 IST", "tonight")
    if _contains(t, TOMORROW):
        day, day_label = now_l + timedelta(days=1), "Tomorrow"
    elif _contains(t, TODAY):
        day, day_label = now_l, "Today"
    else:
        for i, wd in enumerate(WEEKDAYS):
            if re.search(rf"\b{wd}\b", t):
                delta = (i - now_l.weekday()) % 7 or 7
                day, day_label = now_l + timedelta(days=delta), wd.capitalize()
                break
        m = re.search(r"\b(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", t) or \
            re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})\b", t)
        if m and day is None:
            a, b = m.group(1), m.group(2)
            d, mon = (int(a), MONTHS[b[:3]]) if a.isdigit() else (int(b), MONTHS[a[:3]])
            try:
                cand = datetime(now_l.year, mon, d, tzinfo=IST)
                if cand.date() < now_l.date():
                    cand = cand.replace(year=now_l.year + 1)
                day, day_label = cand, cand.strftime("%d %b")
            except ValueError:
                pass
        m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", t)
        if m and day is None:
            day = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=IST)
            day_label = day.strftime("%d %b %Y")

    clock = _clock_time(t)
    dur = _duration_hours(t)
    part_key = _contains(t, list(PARTS.keys()))

    if clock is not None:
        base = day or now_l
        start = _local(base, clock[0] + clock[1] / 60)
        if day is None and start < now_l - timedelta(minutes=30):
            start += timedelta(days=1)
            day_label = "Tomorrow"
            assumptions.append("stated time already passed today; interpreted as tomorrow")
        hours = dur or (DEFAULT_TRIP_H if activity in ("fishing", "sailing", "transit", None) else 3)
        if dur is None:
            assumptions.append(f"trip duration not stated; assumed {hours:g} h from departure")
        label = f"{day_label or start.strftime('%d %b')} {start:%H:%M}–{(start + timedelta(hours=hours)):%H:%M} IST"
        return win(start, start + timedelta(hours=hours), label.strip(), "clock_time")

    if part_key:
        h0, h1 = PARTS[part_key]
        base = day or now_l
        start, end = _local(base, h0), _local(base, h1)
        if day is None and end < now_l:
            start, end = start + timedelta(days=1), end + timedelta(days=1)
            day_label = "Tomorrow"
            assumptions.append(f"'{part_key}' already passed today; interpreted as tomorrow")
        if start < now_l:
            start = now_l
        assumptions.append(f"'{part_key}' interpreted as {h0:02d}:00–{h1 % 24:02d}:00 IST")
        label = f"{day_label or 'Today'} {start:%H:%M}–{end:%H:%M} IST"
        return win(start, end, label, "part_of_day")

    if day is not None:
        start = _local(day, 0)
        end = _local(day, 24)
        if start < now_l:
            start = now_l
        if activity == "fishing":
            start, end = max(_local(day, 4), now_l), _local(day, 18)
            assumptions.append("fishing day interpreted as 04:00–18:00 IST")
        return win(start, end, f"{day_label} {start:%H:%M}–{end:%H:%M} IST", "day")

    if _contains(t, NOW):
        return win(now_l, now_l + timedelta(hours=3), "Now (next 3 h)", "now")

    # default window
    assumptions.append(f"no time stated; assessed the next {default_hours:g} h")
    return TemporalResult(TimeWindow(start=now, end=now + timedelta(hours=default_hours),
                                     label=f"Next {default_hours:g} h (default)", rule="default",
                                     assumptions=assumptions), explicit=False)
