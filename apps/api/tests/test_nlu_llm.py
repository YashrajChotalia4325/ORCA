"""Intent / entity understanding across languages, and the LLM grounding guard."""
from datetime import datetime, timezone

import pytest

from orca.core.schemas import QueryRequest
from orca.core.schemas.common import Intent, UserRole, VesselClass
from orca.geo.reference import ReferenceStore
from orca.reasoning import nlu
from orca.reasoning.llm import grounding_check

NOW = datetime(2026, 9, 26, 0, 30, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def ref():
    return ReferenceStore.get()


CASES = [
    ("Is it safe for a fishing boat to leave Kochi tomorrow at 5 AM?", Intent.SAFETY_CHECK, "kochi"),
    ("Is it safe to fish 30 km off the coast of Kochi tomorrow morning?", Intent.SAFETY_CHECK, "kochi"),
    ("Show potential fishing zones near Mumbai.", Intent.FISHING_ZONES, "mumbai"),
    ("Calculate a lower-risk route from Mumbai to Goa.", Intent.ROUTE_PLAN, "mumbai"),
    ("Give me a safe route from Kochi to Lakshadweep.", Intent.ROUTE_PLAN, "kochi"),
    ("Show cyclone risk across Maharashtra coast for next 24 hours.", Intent.REGIONAL_RISK, None),
    ("Why did chlorophyll concentration decline off Kochi over the past 14 days?", Intent.RESEARCH_TREND, "kochi"),
    ("Compare this week's marine conditions near Chennai with last week", Intent.COMPARE_PERIODS, "chennai"),
    ("What hazards exist within 50 km of 15.2N 72.9E?", Intent.HAZARD_SCAN, "coordinate"),
    ("Show wave conditions for the next 12 hours near Visakhapatnam", Intent.CONDITIONS, "visakhapatnam"),
    ("Find regions with favorable SST and chlorophyll conditions near Mangaluru", Intent.FISHING_ZONES, "mangaluru"),
    ("Is my planned route from Thoothukudi to Rameswaram entering a protected area?", Intent.ROUTE_PLAN, "thoothukudi"),
    ("Which data sources disagree?", Intent.CONFLICTS, None),
    ("What sources support your conclusion?", Intent.SOURCES, None),
    ("Explain why you classified this region as high risk", Intent.EXPLAIN, None),
]


@pytest.mark.parametrize("text,intent,place", CASES)
def test_intent_and_place(ref, text, intent, place):
    u = nlu.parse(QueryRequest(text=text), NOW, ref)
    assert u.intent == intent
    if place:
        assert u.places and u.places[0].id == place


LANGS = [
    ("क्या कल सुबह मुंबई से मछली पकड़ने जाना सुरक्षित है?", "hi", "mumbai"),
    ("उद्या सकाळी रत्नागिरीहून मासेमारीला जाणे सुरक्षित आहे का?", "mr", "ratnagiri"),
    ("நாளை காலை ராமேஸ்வரத்தில் இருந்து மீன்பிடிக்க போகலாமா?", "ta", "rameswaram"),
    ("రేపు ఉదయం విశాఖపట్నం నుండి చేపల వేటకు వెళ్ళవచ్చా?", "te", "visakhapatnam"),
    ("നാളെ രാവിലെ കൊച്ചിയിൽ നിന്ന് മീൻ പിടിക്കാൻ പോകാമോ?", "ml", "kochi"),
    ("ನಾಳೆ ಬೆಳಿಗ್ಗೆ ಮಂಗಳೂರಿನಿಂದ ಮೀನುಗಾರಿಕೆಗೆ ಹೋಗಬಹುದೇ?", "kn", "mangaluru"),
    ("আগামীকাল সকালে দীঘা থেকে মাছ ধরতে যাওয়া কি নিরাপদ?", "bn", "digha"),
]


@pytest.mark.parametrize("text,lang,place", LANGS)
def test_multilingual_safety_questions(ref, text, lang, place):
    u = nlu.parse(QueryRequest(text=text), NOW, ref)
    assert u.language == lang and u.output_language == lang
    assert u.intent == Intent.SAFETY_CHECK and u.places[0].id == place
    assert u.role == UserRole.FISHERMAN and u.safety_critical


def test_vessel_and_offshore_extraction(ref):
    u = nlu.parse(QueryRequest(text="Is it safe for my trawler 20 nm offshore of Veraval tonight?"), NOW, ref)
    assert u.vessel_class == VesselClass.MECHANIZED and abs(u.offshore_km - 37.04) < 0.01


def test_two_coordinates_route(ref):
    u = nlu.parse(QueryRequest(text="Plan a route from 18.90,72.80 to 15.40,73.75"), NOW, ref)
    assert u.intent == Intent.ROUTE_PLAN and u.origin.point.lat == 18.9 and u.destination.point.lon == 73.75


def test_follow_up_inherits_location(ref):
    first = nlu.parse(QueryRequest(text="Is it safe to fish off Kochi tomorrow morning?"), NOW, ref)
    ctx = nlu.ConversationContext("q1", first)
    fu = nlu.parse(QueryRequest(text="What about the wind?"), NOW, ref, ctx)
    assert fu.places and fu.places[0].id == "kochi" and fu.inherited_from == "q1"


def test_missing_location_asks_for_clarification(ref):
    u = nlu.parse(QueryRequest(text="Is it safe to go fishing tomorrow?"), NOW, ref)
    assert u.clarification_needed


# ------------------------------------------------------------------------------------------------ hallucination guard
FACTS = {"decision": "CAUTION", "wave": 2.12, "wind": 34.8, "window": "Tomorrow 05:00–11:00 IST", "confidence_pct": 62}


def test_grounding_accepts_facts_numbers():
    txt = "CAUTION: waves up to 2.12 m (about 2.1 m) and wind 35 km/h between 05:00 and 11:00 IST. Confidence 62%."
    assert grounding_check(txt, FACTS)["passed"]


def test_grounding_rejects_invented_numbers():
    chk = grounding_check("Waves will reach 3.4 m and winds 60 km/h.", FACTS)
    assert not chk["passed"] and 3.4 in chk["unsupported_numbers"]
