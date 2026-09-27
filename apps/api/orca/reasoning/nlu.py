"""Deterministic natural-language understanding for marine queries.

Produces a typed `Understanding` (intent, places, time window, vessel, role,
variables, assumptions) with a parse confidence. When confidence is low and
an LLM is configured, the planner may ask the LLM for a structured
interpretation, which is then validated against the same schema and the
gazetteer (the LLM can never invent a location).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..core import temporal
from ..core.schemas.common import (BBox, GeoPoint, Intent, Place, UserRole, VesselClass)
from ..core.schemas.blackboard import QueryRequest, Understanding
from ..geo.reference import ReferenceStore
from .lexicon import (CUES, HINDI_MARKERS, MARATHI_MARKERS, SCRIPT_RANGES, VARIABLE_CUES, VESSEL_CUES)


# ------------------------------------------------------------------------------------------ language
def detect_language(text: str) -> str:
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for lang, lo, hi in SCRIPT_RANGES:
            if lo <= cp <= hi:
                counts[lang] = counts.get(lang, 0) + 1
                break
    if not counts:
        return "en"
    lang = max(counts, key=counts.get)
    if lang == "deva":
        mr = sum(1 for w in MARATHI_MARKERS if w in text)
        hi = sum(1 for w in HINDI_MARKERS if w in text)
        return "mr" if mr > hi else "hi"
    return lang


def _has(text: str, word: str) -> bool:
    """Latin cues match at a word start (so 'correlat' matches 'correlation'); Indic cues match as substrings."""
    if word != word.strip():            # cues padded with spaces are literal substrings (e.g. " vs ")
        return word in f" {text} "
    if re.search(r"[a-z]", word):
        return re.search(rf"(?<![a-z]){re.escape(word)}", text) is not None
    return word in text


def cue_score(text: str, cue: str) -> int:
    t = text.lower()
    n = 0
    for words in CUES[cue].values():
        for w in words:
            if _has(t, w):
                n += 1
    return n


# ------------------------------------------------------------------------------------------ places
@dataclass
class _Match:
    start: int
    end: int
    place: Place


def find_places(text: str, ref: ReferenceStore) -> tuple[list[_Match], list[Place]]:
    """Return point places (ordered by position) and regions mentioned in text."""
    t = text.lower()
    matches: list[_Match] = []
    taken: list[tuple[int, int]] = []

    def overlaps(s: int, e: int) -> bool:
        return any(not (e <= a or s >= b) for a, b in taken)

    regions: list[Place] = []
    for r in sorted(ref.regions, key=lambda r: -max(len(x) for x in [r["name"], *r["aliases"]])):
        for alias in sorted([r["name"].lower(), *r["aliases"], *r.get("names", {}).values()], key=len, reverse=True):
            a = alias.lower()
            idx = t.find(a) if not re.search(r"[a-z]", a) else (m.start() if (m := re.search(rf"\b{re.escape(a)}\b", t)) else -1)
            if idx >= 0 and not overlaps(idx, idx + len(a)):
                p = ref.region_place(r["id"])
                p.matched_text = alias
                regions.append(p)
                taken.append((idx, idx + len(a)))
                break

    cands = []
    for p in ref.places:
        names = [p["name"].lower(), p["id"].replace("_", " "), *p.get("aliases", []), *p.get("names", {}).values()]
        for n in names:
            cands.append((n.lower(), p))
            # Indic case endings modify the final syllable (ராமேஸ்வரம் -> ராமேஸ்வரத்தில், ಮಂಗಳೂರು -> ಮಂಗಳೂರಿನಿಂದ):
            # also match the stem with the last 1-2 code points removed.
            if not re.search(r"[a-z]", n) and len(n) >= 5:
                cands.append((n[:-1], p))
                cands.append((n[:-2], p))
    cands.sort(key=lambda x: -len(x[0]))
    for n, p in cands:
        if len(n) < 3:
            continue
        if re.search(r"[a-z]", n):
            it = re.finditer(rf"\b{re.escape(n)}\b", t)
        else:
            it = re.finditer(re.escape(n), t)
        for m in it:
            if overlaps(m.start(), m.end()):
                continue
            pl = ref.place(p["id"])
            pl.matched_text = text[m.start():m.end()]
            matches.append(_Match(m.start(), m.end(), pl))
            taken.append((m.start(), m.end()))
    # a place whose id duplicates a region anchor-only match (e.g. "Goa" region vs Goa port) → keep the port
    if any(pl.place.id == "goa" for pl in matches):
        regions = [r for r in regions if r.id != "goa_coast"]
    matches.sort(key=lambda m: m.start)
    return matches, regions


COORD_RE = re.compile(r"(-?\d{1,2}(?:\.\d+)?)\s*°?\s*([ns])?\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*°?\s*([ew])?", re.I)


def find_coordinates(text: str) -> Optional[GeoPoint]:
    pts = find_all_coordinates(text)
    return pts[0] if pts else None


def find_all_coordinates(text: str) -> list[GeoPoint]:
    out: list[GeoPoint] = []
    for m in COORD_RE.finditer(text):
        lat, ns, lon, ew = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4)
        if not (ns or ew or "." in m.group(1)):
            continue
        if ns and ns.lower() == "s":
            lat = -lat
        if ew and ew.lower() == "w":
            lon = -lon
        if -40 <= lat <= 40 and 30 <= lon <= 120:
            out.append(GeoPoint(lat=lat, lon=lon))
    return out


DIST_UNITS = r"(km|kms|kilomet\w*|nm|nmi|nautical miles?|miles?|किमी|कि\.मी\.|കി\.മീ|കിലോമീറ്റർ|கி\.மீ|கிலோமீட்டர்|కి\.మీ|కిలోమీటర్ల|ಕಿ\.ಮೀ|ಕಿಲೋಮೀಟರ್|কিমি|কিলোমিটার)"


def _to_km(v: float, unit: str) -> float:
    u = unit.lower()
    if u.startswith("n") or "nautical" in u:
        return v * 1.852
    if u.startswith("mile"):
        return v * 1.852  # maritime context: miles are nautical miles
    return v


def find_offshore_km(text: str) -> Optional[float]:
    t = text.lower()
    m = re.search(rf"(\d+(?:\.\d+)?)\s*{DIST_UNITS}\s*(?:off|offshore|out|away|into the sea|from (?:the )?(?:coast|shore)|seaward)", t)
    if not m:
        m = re.search(rf"(\d+(?:\.\d+)?)\s*{DIST_UNITS}\s*(?:समुद्र|दूर|കടലിൽ|ദൂര|கடலில்|தூர|సముద్ర|దూర|ಸಮುದ್ರ|ದೂರ|সমুদ্র|দূর)", t)
    if m:
        return _to_km(float(m.group(1)), m.group(2))
    return None


def find_radius_km(text: str) -> Optional[float]:
    t = text.lower()
    m = re.search(rf"(?:within|in a radius of|radius of|around)\s+(\d+(?:\.\d+)?)\s*{DIST_UNITS}", t)
    return _to_km(float(m.group(1)), m.group(2)) if m else None


def find_vessel(text: str, role: UserRole) -> tuple[VesselClass, bool]:
    t = text.lower()
    for cls in ("mechanized", "small_craft", "large_vessel"):
        for w in VESSEL_CUES[cls]:
            if (re.search(rf"\b{re.escape(w)}\b", t) if re.search(r"[a-z]", w) else w in t):
                return VesselClass(cls), True
    if role == UserRole.OPERATOR:
        return VesselClass.LARGE_VESSEL, False
    return VesselClass.SMALL_CRAFT, False


def find_variables(text: str) -> list[str]:
    t = text.lower()
    out = []
    for var, words in VARIABLE_CUES.items():
        if any((re.search(rf"\b{re.escape(w)}", t) if re.search(r"[a-z]", w) else w in t) for w in words):
            out.append(var)
    return out


# ------------------------------------------------------------------------------------------ parse
@dataclass
class ConversationContext:
    last_query_id: Optional[str] = None
    last_understanding: Optional[Understanding] = None


def parse(req: QueryRequest, now: datetime, ref: ReferenceStore,
          context: Optional[ConversationContext] = None) -> Understanding:
    text = req.text.strip()
    t = text.lower()
    lang = detect_language(text)
    s = {c: cue_score(text, c) for c in CUES}
    matches, regions = find_places(text, ref)
    all_coords = find_all_coordinates(text)
    coord = req.location or (all_coords[0] if all_coords else None)
    offshore = find_offshore_km(text)
    radius = find_radius_km(text)
    variables = find_variables(text)
    assumptions: list[str] = []
    signals = 0.0

    two_places = len(matches) + len(all_coords) >= 2
    from_to = bool(re.search(r"\bfrom\b.+\bto\b", t)) or bool(re.search(r"से.+(?:तक|को)", text)) or \
        bool(re.search(r"(?:थी|वरून|இருந்து|నుండి|ನಿಂದ|നിന്ന്|থেকে)", text))

    # ----- intent scoring (ordered, deterministic)
    intent = Intent.UNKNOWN
    secondary: list[Intent] = []
    has_place = bool(matches or regions or coord)
    if s["conflict"]:
        intent = Intent.CONFLICTS
    elif s["sources"] and not (s["safe"] or s["route"]):
        intent = Intent.SOURCES
    elif s["explain"] and not has_place:
        intent = Intent.EXPLAIN
    elif (s["route"] and (two_places or from_to)) or (two_places and from_to):
        intent = Intent.ROUTE_PLAN
        if s["geofence"]:
            secondary.append(Intent.GEOFENCE_CHECK)
        if s["cyclone"] or s["hazard"]:
            secondary.append(Intent.HAZARD_SCAN)
    elif s["route"] and (s["cyclone"] or s["hazard"] or s["geofence"]) and not has_place:
        intent = Intent.HAZARD_SCAN if (s["cyclone"] or s["hazard"]) else Intent.GEOFENCE_CHECK
        assumptions.append("refers to the previously discussed route")
    elif s["compare"] and (s["conditions"] or "week" in t):
        intent = Intent.COMPARE_PERIODS
    elif s["research"] and (variables or s["fish"]) and not s["safe"]:
        intent = Intent.RESEARCH_TREND
    elif s["fish"] and s["zone"] and not s["safe"]:
        intent = Intent.FISHING_ZONES
    elif ("favorable" in t or "favourable" in t) and ("sst" in variables or "chlorophyll" in variables):
        intent = Intent.FISHING_ZONES
    elif s["geofence"] and not s["safe"]:
        intent = Intent.GEOFENCE_CHECK
    elif regions and not matches and (s["cyclone"] or s["hazard"] or s["regional"] or "risk" in t):
        intent = Intent.REGIONAL_RISK
    elif s["hazard"] and (radius or "vessel" in t or s["cyclone"]):
        intent = Intent.HAZARD_SCAN
    elif s["cyclone"] and not s["safe"]:
        intent = Intent.HAZARD_SCAN if not regions else Intent.REGIONAL_RISK
    elif s["safe"] or (s["fish"] and not s["zone"]) or ("sail" in t and not s["route"]):
        intent = Intent.SAFETY_CHECK
    elif s["conditions"] or variables:
        intent = Intent.CONDITIONS
    elif s["explain"]:
        intent = Intent.EXPLAIN
    if intent != Intent.UNKNOWN:
        signals += 0.45

    # ----- role
    role = req.role or UserRole.PUBLIC
    if req.role is None:
        if intent in (Intent.RESEARCH_TREND, Intent.COMPARE_PERIODS):
            role = UserRole.RESEARCHER
        elif intent == Intent.REGIONAL_RISK or s["regional"]:
            role = UserRole.AUTHORITY
        elif intent == Intent.ROUTE_PLAN or re.search(r"\b(vessel|ship|cargo|ferry|operator)\b", t):
            role = UserRole.OPERATOR
        elif s["fish"] or re.search(r"\b(boat|my boat|fishermen|fisherman)\b", t):
            role = UserRole.FISHERMAN
        else:
            role = UserRole.FISHERMAN if lang != "en" else UserRole.PUBLIC

    vessel, vessel_explicit = find_vessel(text, role)
    if req.vessel_class:
        vessel, vessel_explicit = req.vessel_class, True
    if not vessel_explicit and intent in (Intent.SAFETY_CHECK, Intent.ROUTE_PLAN, Intent.HAZARD_SCAN, Intent.REGIONAL_RISK):
        assumptions.append(f"vessel type not stated; assessed for {vessel.value.replace('_', ' ')} thresholds")

    activity = "fishing" if s["fish"] else ("transit" if intent == Intent.ROUTE_PLAN else
                                            ("sailing" if "sail" in t else None))
    if intent in (Intent.RESEARCH_TREND, Intent.COMPARE_PERIODS):
        activity = "research"

    # ----- time
    tr = temporal.resolve(text, now, activity=activity,
                          default_hours=24 if intent != Intent.CONDITIONS else 24)
    tw, comp = tr.window, tr.comparison
    if tr.explicit:
        signals += 0.2
    if ("कल" in text or "কাল" in text) and intent not in (Intent.RESEARCH_TREND, Intent.COMPARE_PERIODS):
        tw.assumptions.append("'कल/কাল' can mean yesterday or tomorrow; interpreted as tomorrow (future planning)")
    if intent in (Intent.RESEARCH_TREND,) and comp is None:
        tr2 = temporal.resolve("past 14 days", now)
        tw, comp = tr2.window, tr2.comparison
        assumptions.append("no period stated; compared the last 14 days with the preceding 14 days")

    # ----- places / roles of places
    origin = destination = region = None
    places = [m.place for m in matches]
    coords_for_places = all_coords if (req.location is None and len(all_coords) >= 2) else ([coord] if coord else [])
    for k, cpt in enumerate(coords_for_places):
        cp = Place(id=f"coordinate{k or ''}", name=f"{cpt.lat:.3f}°N {cpt.lon:.3f}°E", kind="coordinate", point=cpt)
        places.insert(k, cp)
    if intent == Intent.ROUTE_PLAN and len(places) == 1 and regions:
        # "from Kochi to Lakshadweep": use the region's principal anchor as the other end
        anchor = next((a for a in ref.regions if a["id"] == regions[0].id), {}).get("anchors", [])
        if anchor:
            ap = ref.place(anchor[0])
            ap.matched_text = regions[0].matched_text
            places.append(ap)
            assumptions.append(f"'{regions[0].name}' resolved to {ap.name} as route end-point")
            regions = []
    if intent == Intent.ROUTE_PLAN and len(places) >= 2:
        origin, destination = places[0], places[1]
        m_to = re.search(r"\bto\s+([a-z .]+)", t)
        if m_to:
            # "to X ... from Y" ordering
            for p in places:
                if p.matched_text and p.matched_text.lower() in m_to.group(1)[:len(p.matched_text) + 2]:
                    destination = p
                    origin = next(q for q in places if q.id != p.id)
                    break
        signals += 0.3
    elif places:
        signals += 0.3
    if regions:
        region = regions[0]
        if not places:
            signals += 0.3

    inherited = None
    if context and context.last_understanding:
        lu = context.last_understanding
        if not places and not regions and intent not in (Intent.UNKNOWN,):
            # follow-up without a location: inherit the previous spatial context
            places = lu.places
            origin, destination, region = lu.origin, lu.destination, lu.region
            offshore = offshore if offshore is not None else lu.offshore_km
            inherited = context.last_query_id
            if not tr.explicit and lu.time_window and intent not in (Intent.RESEARCH_TREND, Intent.COMPARE_PERIODS):
                tw = lu.time_window
            if intent in (Intent.HAZARD_SCAN, Intent.GEOFENCE_CHECK) and lu.origin and lu.destination:
                secondary.append(Intent.ROUTE_PLAN)
            assumptions.append("location/time carried over from the previous question")
            signals += 0.25
        if intent == Intent.UNKNOWN and lu:
            intent = lu.intent
            inherited = context.last_query_id
            assumptions.append("intent carried over from the previous question")

    if intent in (Intent.SAFETY_CHECK, Intent.CONDITIONS) and places and offshore is None and \
            places[0].kind not in ("coordinate",):
        offshore = 20.0 if activity == "fishing" else 10.0
        assumptions.append(f"distance offshore not stated; assessed a point {offshore:g} km offshore of {places[0].name}")

    clarification = None
    needs_place = intent in (Intent.SAFETY_CHECK, Intent.CONDITIONS, Intent.FISHING_ZONES, Intent.HAZARD_SCAN,
                             Intent.GEOFENCE_CHECK, Intent.RESEARCH_TREND, Intent.COMPARE_PERIODS)
    if intent == Intent.ROUTE_PLAN and not (origin and destination):
        clarification = "Please give both the departure and destination ports (e.g. 'from Mumbai to Goa')."
    elif needs_place and not (places or region) and not inherited:
        clarification = "Which location? Name a coastal town or harbour, a coastal region, or click the map."
    elif intent == Intent.UNKNOWN:
        clarification = ("I could not identify what you want to know. Try e.g. 'Is it safe to fish 20 km off Kochi "
                         "tomorrow morning?' or 'Show potential fishing zones near Mangaluru'.")

    safety_critical = intent in (Intent.SAFETY_CHECK, Intent.ROUTE_PLAN, Intent.HAZARD_SCAN, Intent.REGIONAL_RISK)
    out_lang = req.language or lang
    return Understanding(
        intent=intent, secondary_intents=secondary, role=role, language=lang, output_language=out_lang,
        activity=activity, places=places, origin=origin, destination=destination, region=region,
        offshore_km=offshore, radius_km=radius or (50.0 if intent == Intent.HAZARD_SCAN else None),
        time_window=tw, comparison_window=comp, vessel_class=vessel, variables=variables,
        safety_critical=safety_critical, assumptions=assumptions + list(tw.assumptions),
        parse_method="rules+context" if inherited else "rules", parse_confidence=round(min(1.0, signals), 2),
        clarification_needed=clarification, inherited_from=inherited,
    )
