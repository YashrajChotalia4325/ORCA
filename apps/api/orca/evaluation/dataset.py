"""ORCA evaluation dataset v1 — 100 marine queries with ground truth.

Two tiers:
* understanding cases (all 100): intent, place, language, time window, vessel class
* pipeline cases (subset, flagged `run`): executed end-to-end in DEMO scenarios with expected
  decision, required agents / tools, and consistency groups (paraphrases and translations of the
  same question must yield the same decision).
Clock for every case: DEMO scenario time 2026-09-26T00:30Z (06:00 IST).
"""
from __future__ import annotations

from typing import Any

# (text, intent, place_id or None, lang, extra expectations)
_SAFETY_EN = [
    ("Is it safe for a fishing boat to leave {p} tomorrow at 5 AM?", {"start": (27, 5), "hours": 6}),
    ("Is it safe to fish 30 km off the coast of {p} tomorrow morning?", {"start": (27, 5), "offshore": 30}),
    ("Can I go fishing from {p} tomorrow morning?", {"start": (27, 5)}),
    ("Should my trawler leave {p} tonight?", {"vessel": "mechanized"}),
    ("Is it dangerous to take a boat out from {p} today afternoon?", {"start": (26, 12)}),
]
_PLACES = ["kochi", "mumbai", "chennai", "visakhapatnam", "mangaluru", "ratnagiri", "thoothukudi", "paradip", "veraval", "kollam"]
_NAMES = {"kochi": "Kochi", "mumbai": "Mumbai", "chennai": "Chennai", "visakhapatnam": "Visakhapatnam",
          "mangaluru": "Mangaluru", "ratnagiri": "Ratnagiri", "thoothukudi": "Thoothukudi", "paradip": "Paradip",
          "veraval": "Veraval", "kollam": "Kollam"}

MULTILINGUAL = [
    ("क्या कल सुबह मुंबई से मछली पकड़ने जाना सुरक्षित है?", "hi", "mumbai"),
    ("क्या कल सुबह कोच्चि से मछली पकड़ने जाना सुरक्षित है?", "hi", "kochi"),
    ("उद्या सकाळी रत्नागिरीहून मासेमारीला जाणे सुरक्षित आहे का?", "mr", "ratnagiri"),
    ("उद्या सकाळी मुंबईहून मासेमारीला जाणे सुरक्षित आहे का?", "mr", "mumbai"),
    ("நாளை காலை ராமேஸ்வரத்தில் இருந்து மீன்பிடிக்க போகலாமா?", "ta", "rameswaram"),
    ("நாளை காலை சென்னையில் இருந்து மீன்பிடிக்க போகலாமா?", "ta", "chennai"),
    ("రేపు ఉదయం విశాఖపట్నం నుండి చేపల వేటకు వెళ్ళవచ్చా?", "te", "visakhapatnam"),
    ("రేపు ఉదయం కాకినాడ నుండి చేపల వేటకు వెళ్ళవచ్చా?", "te", "kakinada"),
    ("നാളെ രാവിലെ കൊച്ചിയിൽ നിന്ന് മീൻ പിടിക്കാൻ പോകാമോ?", "ml", "kochi"),
    ("നാളെ രാവിലെ കൊല്ലത്ത് നിന്ന് മീൻ പിടിക്കാൻ പോകാമോ?", "ml", "kollam"),
    ("ನಾಳೆ ಬೆಳಿಗ್ಗೆ ಮಂಗಳೂರಿನಿಂದ ಮೀನುಗಾರಿಕೆಗೆ ಹೋಗಬಹುದೇ?", "kn", "mangaluru"),
    ("ನಾಳೆ ಬೆಳಿಗ್ಗೆ ಕಾರವಾರದಿಂದ ಮೀನುಗಾರಿಕೆಗೆ ಹೋಗಬಹುದೇ?", "kn", "karwar"),
    ("আগামীকাল সকালে দীঘা থেকে মাছ ধরতে যাওয়া কি নিরাপদ?", "bn", "digha"),
    ("আগামীকাল সকালে হলদিয়া থেকে মাছ ধরতে যাওয়া কি নিরাপদ?", "bn", "haldia"),
]

OTHER = [
    ("Show potential fishing zones near Mumbai.", "FISHING_ZONES", "mumbai", {}),
    ("Show potential fishing zones near Mangaluru", "FISHING_ZONES", "mangaluru", {}),
    ("Where are the productive fishing zones near Kochi?", "FISHING_ZONES", "kochi", {}),
    ("Find regions with favorable SST and chlorophyll conditions near Mangaluru", "FISHING_ZONES", "mangaluru", {}),
    ("Find hotspots for fishing off Ratnagiri", "FISHING_ZONES", "ratnagiri", {}),
    ("Calculate a lower-risk route from Mumbai to Goa.", "ROUTE_PLAN", "mumbai", {"dest": "goa"}),
    ("Give me a safe route from Kochi to Lakshadweep.", "ROUTE_PLAN", "kochi", {"dest": "kavaratti"}),
    ("Plan a route from Thoothukudi to Rameswaram for a fishing boat tomorrow morning", "ROUTE_PLAN", "thoothukudi", {"dest": "rameswaram"}),
    ("Route from Chennai to Visakhapatnam departing tomorrow 6 AM", "ROUTE_PLAN", "chennai", {"dest": "visakhapatnam", "start": (27, 6)}),
    ("Find a lower-risk route from Mumbai to Goa for a trawler departing tomorrow at 6 AM", "ROUTE_PLAN", "mumbai", {"dest": "goa", "vessel": "mechanized"}),
    ("Is it safe to sail from Mumbai to Goa tomorrow morning?", "ROUTE_PLAN", "mumbai", {"dest": "goa"}),
    ("Navigate from Kakinada to Visakhapatnam", "ROUTE_PLAN", "kakinada", {"dest": "visakhapatnam"}),
    ("Show cyclone risk across Maharashtra coast for next 24 hours.", "REGIONAL_RISK", None, {"region": "maharashtra_coast"}),
    ("Show cyclone risk across the Andhra Pradesh coast for the next 24 hours", "REGIONAL_RISK", None, {"region": "andhra_coast"}),
    ("What is the hazard situation along the Odisha coast?", "REGIONAL_RISK", None, {"region": "odisha_coast"}),
    ("Hazards across the Kerala coast for the next 24 hours", "REGIONAL_RISK", None, {"region": "kerala_coast"}),
    ("Why did chlorophyll concentration decline off Kochi over the past 14 days?", "RESEARCH_TREND", "kochi", {}),
    ("Why has productivity declined near Mangaluru?", "RESEARCH_TREND", "mangaluru", {}),
    ("Why did SST increase near Chennai in the last 10 days?", "RESEARCH_TREND", "chennai", {}),
    ("Why is chlorophyll lower off Ratnagiri over the past 3 weeks?", "RESEARCH_TREND", "ratnagiri", {}),
    ("Compare this week's marine conditions near Chennai with last week", "COMPARE_PERIODS", "chennai", {}),
    ("Compare this week's marine conditions near Kochi with last week", "COMPARE_PERIODS", "kochi", {}),
    ("What hazards exist within 50 km of 15.2N 72.9E?", "HAZARD_SCAN", "coordinate", {}),
    ("What hazards exist within 30 km of 9.10N 79.30E?", "HAZARD_SCAN", "coordinate", {}),
    ("Is there a cyclone near Paradip?", "HAZARD_SCAN", "paradip", {}),
    ("Show wave conditions for the next 12 hours near Visakhapatnam", "CONDITIONS", "visakhapatnam", {"hours": 12}),
    ("What are the wind and waves off Kollam now?", "CONDITIONS", "kollam", {}),
    ("Sea surface temperature near Kochi", "CONDITIONS", "kochi", {}),
    ("Current conditions off Veraval for the next 6 hours", "CONDITIONS", "veraval", {"hours": 6}),
    ("Is 9.12N 78.90E inside a protected area?", "GEOFENCE_CHECK", "coordinate", {}),
    ("Is Malvan inside a marine sanctuary boundary?", "GEOFENCE_CHECK", "malvan", {}),
    ("What are the wave heights off Puri tomorrow?", "CONDITIONS", "puri", {}),
    ("Is it safe to fish near Minicoy tomorrow morning?", "SAFETY_CHECK", "minicoy", {"start": (27, 5)}),
    ("Which data sources disagree?", "CONFLICTS", None, {}),
    ("What sources support your conclusion?", "SOURCES", None, {}),
    ("Explain why you classified this region as high risk", "EXPLAIN", None, {}),
]

# end-to-end cases (DEMO) — expected decision and consistency groups
PIPELINE = [
    {"scenario": "kochi_fishing", "text": "Is it safe for a fishing boat to leave Kochi tomorrow at 5 AM?", "decision": "CAUTION",
     "agents": ["geospatial", "ocean", "weather", "satellite", "advisory", "hazard", "evidence", "communication"],
     "tools": ["risk.evaluate"], "group": "kochi"},
    {"scenario": "kochi_fishing", "text": "Is it safe to fish off Kochi tomorrow at 5 AM?", "decision": "CAUTION", "group": "kochi"},
    {"scenario": "kochi_fishing", "text": "നാളെ രാവിലെ 5 മണിക്ക് കൊച്ചിയിൽ നിന്ന് മീൻ പിടിക്കാൻ പോകാമോ?", "decision": "CAUTION", "group": "kochi"},
    {"scenario": "kochi_fishing", "text": "क्या कल सुबह 5 बजे कोच्चि से मछली पकड़ने जाना सुरक्षित है?", "decision": "CAUTION", "group": "kochi"},
    {"scenario": "approaching_cyclone", "text": "Is it safe to fish off Visakhapatnam tomorrow morning?", "decision": "DONT_GO",
     "agents": ["advisory", "hazard"], "group": "vizag"},
    {"scenario": "approaching_cyclone", "text": "రేపు ఉదయం విశాఖపట్నం నుండి చేపల వేటకు వెళ్ళవచ్చా?", "decision": "DONT_GO", "group": "vizag"},
    {"scenario": "approaching_cyclone", "text": "Show cyclone risk across the Andhra Pradesh coast for the next 24 hours", "decision": "DONT_GO"},
    {"scenario": "mumbai_goa_route", "text": "Find a lower-risk route from Mumbai to Goa for a trawler departing tomorrow at 6 AM",
     "decision": "CAUTION", "agents": ["route", "hazard"], "tools": ["routing.astar"]},
    {"scenario": "protected_geofence", "text": "Plan a route from Thoothukudi to Rameswaram for a fishing boat tomorrow morning",
     "decision": "GO", "agents": ["route"]},
    {"scenario": "pfz_mangaluru", "text": "Show potential fishing zones near Mangaluru", "decision": "GO", "agents": ["fisheries"],
     "tools": ["fronts.gradient_analysis"]},
    {"scenario": "conflicting_sources", "text": "Is it safe to fish 25 km off Chennai tomorrow morning?", "decision": "CAUTION",
     "expect_conflict": True},
    {"scenario": "degraded_sources", "text": "Is it safe to fish 20 km off Kochi tomorrow morning?", "decision": "GO"},
    {"scenario": "total_outage", "text": "Is it safe to fish 20 km off Kochi tomorrow morning?", "decision": "INSUFFICIENT_DATA"},
    {"scenario": "research_chl", "text": "Why did chlorophyll concentration decline off Kochi over the past 14 days?",
     "decision": "NOT_APPLICABLE", "agents": ["research", "satellite"], "tools": ["stats.welch_ttest"]},
]


def build() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for tmpl, exp in _SAFETY_EN:
        for pid in _PLACES:
            cases.append({"text": tmpl.format(p=_NAMES[pid]), "intent": "SAFETY_CHECK", "place": pid, "lang": "en", **exp})
    for text, lang, pid in MULTILINGUAL:
        cases.append({"text": text, "intent": "SAFETY_CHECK", "place": pid, "lang": lang, "start": (27, 5)})
    for text, intent, pid, exp in OTHER:
        cases.append({"text": text, "intent": intent, "place": pid, "lang": "en", **exp})
    for i, c in enumerate(cases, 1):
        c["id"] = f"Q{i:03d}"
    return cases[:100]


CASES = build()
