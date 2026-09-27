"""Multilingual lexicon for intent cues.

Languages: en, hi (Hindi), mr (Marathi), ta (Tamil), te (Telugu), ml (Malayalam),
kn (Kannada), bn (Bengali). Entries were machine-authored for the prototype
and need native-speaker review (see docs/LIMITATIONS.md). Matching is
substring-based for Indic scripts (agglutinative morphology) and
word-boundary based for Latin script.
"""
from __future__ import annotations

SUPPORTED_LANGUAGES = {
    "en": "English", "hi": "हिन्दी", "mr": "मराठी", "ta": "தமிழ்", "te": "తెలుగు",
    "ml": "മലയാളം", "kn": "ಕನ್ನಡ", "bn": "বাংলা",
}

CUES: dict[str, dict[str, list[str]]] = {
    "safe": {
        "en": ["safe", "safety", "dangerous", "danger", "risky", "can i go", "should i go", "go out", "venture",
               "leave", "depart", "departure", "ok to", "okay to", "go fishing", "put out to sea", "head out"],
        "hi": ["सुरक्षित", "खतरा", "खतरनाक", "जा सकता", "जा सकते", "जाना चाहिए", "जाऊं", "निकल"],
        "mr": ["सुरक्षित", "धोका", "जाऊ शकतो", "जाऊ का", "जाणे", "जावे"],
        "ta": ["பாதுகாப்பா", "பாதுகாப்பு", "ஆபத்து", "போகலாமா", "செல்லலாமா", "போகலாம்"],
        "te": ["సురక్షిత", "ప్రమాద", "వెళ్ళవచ్చా", "వెళ్లవచ్చా", "వెళ్లొచ్చా"],
        "kn": ["ಸುರಕ್ಷಿತ", "ಅಪಾಯ", "ಹೋಗಬಹುದೇ", "ಹೋಗಬಹುದಾ"],
        "ml": ["സുരക്ഷിത", "അപകട", "പോകാമോ", "പോകാൻ പറ്റുമോ", "പോകാമോ"],
        "bn": ["নিরাপদ", "বিপদ", "যাওয়া যাবে", "যেতে পারি", "যাওয়া কি"],
    },
    "fish": {
        "en": ["fish", "fishing", "catch", "trawl", "pfz", "potential fishing"],
        "hi": ["मछली", "मछुआरे", "मत्स्य", "मछलियां"],
        "mr": ["मासेमारी", "मासे", "मच्छीमार"],
        "ta": ["மீன்", "மீன்பிடி"],
        "te": ["చేప", "చేపల", "వేట"],
        "kn": ["ಮೀನು", "ಮೀನುಗಾರಿಕೆ"],
        "ml": ["മീൻ", "മത്സ്യ"],
        "bn": ["মাছ", "মৎস্য"],
    },
    "zone": {
        "en": ["zone", "zones", "where", "find", "show", "hotspot", "hotspots", "productive", "favorable",
               "favourable", "good spots", "best area", "areas", "regions with", "locate"],
        "hi": ["कहाँ", "कहां", "क्षेत्र", "ज़ोन", "जोन"],
        "mr": ["कुठे", "क्षेत्र", "झोन"],
        "ta": ["எங்கே", "பகுதி", "மண்டலம்"],
        "te": ["ఎక్కడ", "ప్రాంతం", "జోన్"],
        "kn": ["ಎಲ್ಲಿ", "ಪ್ರದೇಶ", "ವಲಯ"],
        "ml": ["എവിടെ", "മേഖല", "സോൺ"],
        "bn": ["কোথায়", "এলাকা", "জোন"],
    },
    "route": {
        "en": ["route", "path", "navigate", "navigation", "passage", "voyage", "transit", "safest way", "sail from",
               "way to", "lower-risk route", "safe route", "course to"],
        "hi": ["रास्ता", "मार्ग"],
        "mr": ["मार्ग", "रस्ता"],
        "ta": ["வழி", "பாதை"],
        "te": ["మార్గం", "దారి"],
        "kn": ["ಮಾರ್ಗ", "ದಾರಿ"],
        "ml": ["വഴി", "റൂട്ട്", "പാത"],
        "bn": ["পথ", "রুট"],
    },
    "conditions": {
        "en": ["wave", "waves", "swell", "wind", "winds", "current", "currents", "sst", "sea surface temperature",
               "temperature", "conditions", "sea state", "weather", "forecast", "rain", "rainfall", "chlorophyll",
               "gust", "gusts"],
        "hi": ["लहर", "लहरें", "हवा", "मौसम", "बारिश", "तापमान"],
        "mr": ["लाटा", "वारा", "हवामान", "पाऊस"],
        "ta": ["அலை", "காற்று", "வானிலை", "மழை"],
        "te": ["అలల", "అలలు", "గాలి", "వాతావరణ", "వర్షం"],
        "kn": ["ಅಲೆ", "ಗಾಳಿ", "ಹವಾಮಾನ", "ಮಳೆ"],
        "ml": ["തിര", "കാറ്റ്", "കാലാവസ്ഥ", "മഴ"],
        "bn": ["ঢেউ", "বাতাস", "আবহাওয়া", "বৃষ্টি"],
    },
    "cyclone": {
        "en": ["cyclone", "cyclonic", "storm", "depression", "hurricane", "typhoon", "low pressure", "tropical"],
        "hi": ["चक्रवात", "तूफान", "तूफ़ान"],
        "mr": ["चक्रीवादळ", "वादळ"],
        "ta": ["புயல்"],
        "te": ["తుఫాను", "తుఫాన్"],
        "kn": ["ಚಂಡಮಾರುತ", "ಸೈಕ್ಲೋನ್"],
        "ml": ["ചുഴലിക്കാറ്റ്", "കൊടുങ്കാറ്റ്", "ന്യൂനമർദ"],
        "bn": ["ঘূর্ণিঝড়", "ঝড়"],
    },
    "hazard": {
        "en": ["hazard", "hazards", "threat", "threats", "warning", "warnings", "alert", "alerts", "near this vessel",
               "around this vessel", "near me", "around me", "within"],
        "hi": ["चेतावनी", "खतरे"],
        "mr": ["इशारा"],
        "ta": ["எச்சரிக்கை"],
        "te": ["హెచ్చరిక"],
        "kn": ["ಎಚ್ಚರಿಕೆ"],
        "ml": ["മുന്നറിയിപ്പ്"],
        "bn": ["সতর্কতা"],
    },
    "research": {
        "en": ["why", "trend", "trends", "decline", "declined", "declining", "increase", "increased", "decrease",
               "decreased", "drop", "dropped", "rise", "rose", "change", "changed", "productivity", "anomaly",
               "correlat", "cause", "reason for", "variability"],
        "hi": ["क्यों", "कमी", "बढ़", "घट"],
        "mr": ["कारण", "घट", "वाढ"],
        "ta": ["ஏன்", "குறைந்த", "அதிகரி"],
        "te": ["ఎందుకు", "తగ్గ", "పెరిగ"],
        "kn": ["ಏಕೆ", "ಯಾಕೆ", "ಕಡಿಮೆ"],
        "ml": ["എന്തുകൊണ്ട്", "കുറഞ്ഞ", "കൂടി"],
        "bn": ["কেন", "কমে", "বেড়ে"],
    },
    "compare": {
        "en": ["compare", "comparison", "versus", " vs ", "compared with", "compared to", "than last"],
        "hi": ["तुलना"], "mr": ["तुलना"], "ta": ["ஒப்பிடு"], "te": ["పోల్చ"], "kn": ["ಹೋಲಿಸ"], "ml": ["താരതമ്യ"], "bn": ["তুলনা"],
    },
    "geofence": {
        "en": ["protected", "mpa", "marine park", "national park", "sanctuary", "restricted", "boundary", "boundaries",
               "eez", "border", "imbl", "geofence", "entering", "enter", "cross", "crossing", "no-go", "prohibited"],
        "hi": ["सीमा", "संरक्षित", "प्रतिबंधित"],
        "mr": ["सीमा", "संरक्षित"],
        "ta": ["எல்லை", "பாதுகாக்கப்பட்ட"],
        "te": ["సరిహద్దు", "సంరక్షిత"],
        "kn": ["ಗಡಿ", "ಸಂರಕ್ಷಿತ"],
        "ml": ["അതിർത്തി", "സംരക്ഷിത"],
        "bn": ["সীমানা", "সংরক্ষিত"],
    },
    "explain": {
        "en": ["explain", "why did you", "why is it", "why was", "how did you", "reasoning", "justify", "classified",
               "why high risk", "why caution", "why don't go", "basis"],
        "hi": ["समझाओ", "समझाइए"], "mr": ["समजावून"], "ta": ["விளக்கு"], "te": ["వివరించ"], "kn": ["ವಿವರಿಸ"], "ml": ["വിശദീകരി"], "bn": ["ব্যাখ্যা"],
    },
    "sources": {
        "en": ["what sources", "which sources", "sources support", "source support", "evidence", "citation", "citations",
               "cite", "data sources", "where does the data", "provenance"],
        "hi": ["स्रोत"], "mr": ["स्रोत"], "ta": ["ஆதாரம்"], "te": ["మూలాలు"], "kn": ["ಮೂಲ"], "ml": ["ഉറവിട"], "bn": ["উৎস"],
    },
    "conflict": {
        "en": ["disagree", "disagreement", "conflict", "conflicting", "contradict", "inconsistent", "differ"],
        "hi": ["असहमत", "विरोधाभास"], "mr": ["विसंगत"], "ta": ["முரண்"], "te": ["విరుద్ధ"], "kn": ["ವಿರೋಧ"], "ml": ["വൈരുദ്ധ്യ"], "bn": ["বিরোধ"],
    },
    "regional": {
        "en": ["across", "along the", "entire", "whole", "all along", "coastline", "district", "districts", "state-wide",
               "statewide", "sector", "sectors"],
        "hi": ["पूरे", "तट पर"], "mr": ["संपूर्ण"], "ta": ["முழுவதும்"], "te": ["అంతటా"], "kn": ["ಉದ್ದಕ್ಕೂ"], "ml": ["മുഴുവൻ"], "bn": ["জুড়ে"],
    },
}

VESSEL_CUES = {
    "mechanized": ["trawler", "mechanised", "mechanized", "gillnetter", "gill-netter", "purse seiner", "purse-seiner",
                   "long liner", "longliner", "ट्रॉलर", "ட்ராலர்", "ട്രോളർ", "ట్రాలర్", "ಟ್ರಾಲರ್", "ট্রলার"],
    "large_vessel": ["ship", "vessel", "cargo", "ferry", "tanker", "container", "coaster", "merchant", "passenger vessel",
                     "जहाज", "கப்பல்", "കപ്പൽ", "ఓడ", "ಹಡಗು", "জাহাজ"],
    "small_craft": ["boat", "canoe", "vallam", "catamaran", "kattumaram", "country boat", "frp", "fibre boat",
                    "fiber boat", "outboard", "नाव", "नौका", "होडी", "படகு", "വള്ളം", "ബോട്ട്", "పడవ", "ದೋಣಿ", "নৌকা"],
}

VARIABLE_CUES = {
    "wave_height": ["wave", "waves", "swell", "sea state", "लहर", "लाटा", "அலை", "అల", "ಅಲೆ", "തിര", "ঢেউ"],
    "wind_speed": ["wind", "gust", "हवा", "वारा", "காற்று", "గాలి", "ಗಾಳಿ", "കാറ്റ്", "বাতাস"],
    "sst": ["sst", "sea surface temperature", "temperature", "तापमान", "வெப்பநிலை", "ఉష్ణోగ్రత", "ತಾಪಮಾನ", "താപനില", "তাপমাত্রা"],
    "chlorophyll": ["chlorophyll", "chl", "productivity", "phytoplankton", "bloom", "क्लोरोफिल"],
    "current_speed": ["current", "currents", "धारा", "நீரோட்டம்", "ప్రవాహ", "ಪ್ರವಾಹ", "ഒഴുക്ക്", "স্রোত"],
    "precipitation": ["rain", "rainfall", "precipitation", "बारिश", "पाऊस", "மழை", "వర్షం", "ಮಳೆ", "മഴ", "বৃষ্টি"],
    "cyclone": ["cyclone", "storm", "depression", "चक्रवात", "புயல்", "తుఫాను", "ಚಂಡಮಾರುತ", "ചുഴലിക്കാറ്റ്", "ঘূর্ণিঝড়"],
    "lightning": ["lightning", "thunder", "thunderstorm", "बिजली", "மின்னல்", "మెరుపు", "ಮಿಂಚು", "ഇടിമിന്നൽ", "বজ্রপাত"],
}

# Devanagari disambiguation (Hindi vs Marathi)
MARATHI_MARKERS = ["आहे", "उद्या", "मासेमारी", "जाऊ", "शकतो", "शकते", "सकाळी", "किनारा", "समुद्रात", "च्या",
                   "आत्ता", "का?", "वारा", "लाटा", "नाही", "आहेत", "करू"]
HINDI_MARKERS = ["है", "क्या", "कल", "मछली", "जाना", "सकता", "सुबह", "में", "के", "हैं", "नहीं", "की", "हवा", "लहर"]

SCRIPT_RANGES = [
    ("ml", 0x0D00, 0x0D7F), ("ta", 0x0B80, 0x0BFF), ("te", 0x0C00, 0x0C7F), ("kn", 0x0C80, 0x0CFF),
    ("bn", 0x0980, 0x09FF), ("gu", 0x0A80, 0x0AFF), ("or", 0x0B00, 0x0B7F), ("deva", 0x0900, 0x097F),
]
