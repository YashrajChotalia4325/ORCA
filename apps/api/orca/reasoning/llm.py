"""Optional LLM layer (Anthropic Claude).

The LLM is used for exactly two things, both optional:

1. **Interpretation fallback** — when rule-based NLU confidence is low. The
   LLM returns *identifiers* from ORCA's gazetteer and a time expression in
   English; it can never supply coordinates. The deterministic temporal
   resolver and gazetteer then produce the actual location/time.
2. **Narration** — rephrasing a computed, structured result for a role and
   language. A grounding guard extracts every number from the LLM text and
   rejects the narration if any number is absent from the facts it was
   given; ORCA then falls back to its template renderer.

Risk, geometry, routing, thresholds and confidence are never delegated.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import Settings

log = logging.getLogger("orca.llm")

try:  # the SDK is optional at runtime
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore

FALLBACK_BETA = "server-side-fallback-2026-07-01"

INTERPRET_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [
            "SAFETY_CHECK", "CONDITIONS", "ROUTE_PLAN", "FISHING_ZONES", "HAZARD_SCAN", "REGIONAL_RISK",
            "RESEARCH_TREND", "COMPARE_PERIODS", "GEOFENCE_CHECK", "EXPLAIN", "SOURCES", "CONFLICTS", "UNKNOWN"]},
        "place_ids": {"type": "array", "items": {"type": "string"}},
        "origin_id": {"type": "string"},
        "destination_id": {"type": "string"},
        "region_id": {"type": "string"},
        "offshore_km": {"type": "number"},
        "time_expression_en": {"type": "string"},
        "vessel_class": {"type": "string", "enum": ["small_craft", "mechanized", "large_vessel", "unknown"]},
        "role": {"type": "string", "enum": ["fisherman", "authority", "researcher", "operator", "public"]},
    },
    "required": ["intent", "place_ids", "origin_id", "destination_id", "region_id", "offshore_km",
                 "time_expression_en", "vessel_class", "role"],
    "additionalProperties": False,
}

NARRATE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "summary", "bullets"],
    "additionalProperties": False,
}

NUM_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


@dataclass
class LLMResult:
    data: Optional[dict]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def numbers_in(text: str) -> list[float]:
    return [float(x) for x in NUM_RE.findall(text.replace(",", ""))]


def allowed_numbers(facts: Any) -> set[float]:
    """Every number appearing in the facts, plus its common roundings."""
    raw = json.dumps(facts, default=str, ensure_ascii=False)   # keep "05:00–11:00" intact (no \u2013 escapes)
    out: set[float] = set()
    for v in numbers_in(raw):
        out.add(v)
        for nd in (0, 1, 2):
            out.add(round(v, nd))
        out.add(abs(v))
    return out


def grounding_check(text: str, facts: Any) -> dict:
    allowed = allowed_numbers(facts)
    found = numbers_in(text)
    unsupported = [v for v in found if not any(abs(v - a) <= 1e-6 for a in allowed)]
    return {"numbers_found": len(found), "unsupported_numbers": unsupported, "passed": not unsupported}


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.llm_model
        self._client = None
        if settings.llm_available and anthropic is not None:
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=45.0, max_retries=1)

    @property
    def available(self) -> bool:
        return self._client is not None

    async def _json_call(self, system: str, user: str, schema: dict, effort: str, max_tokens: int = 4000) -> LLMResult:
        if not self._client:
            return LLMResult(None, self.model, error="LLM not configured")
        kwargs = dict(model=self.model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": user}],
                      output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
        try:
            try:
                resp = await self._client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            except anthropic.BadRequestError as e:
                # fallbacks not supported for this model / account: retry once without them
                log.info("retrying without server-side fallbacks: %s", e.message)
                resp = await self._client.messages.create(**kwargs)
        except anthropic.RateLimitError:
            return LLMResult(None, self.model, error="rate limited")
        except anthropic.APIStatusError as e:
            return LLMResult(None, self.model, error=f"API error {e.status_code}")
        except anthropic.APIConnectionError:
            return LLMResult(None, self.model, error="connection error")
        usage = getattr(resp, "usage", None)
        res = LLMResult(None, getattr(resp, "model", self.model),
                        getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)
        if resp.stop_reason == "refusal":
            res.error = "model declined the request"
            return res
        if resp.stop_reason == "max_tokens":
            res.error = "output truncated"
            return res
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
        if not text:
            res.error = "no text block"
            return res
        try:
            res.data = json.loads(text)
        except json.JSONDecodeError:
            res.error = "invalid JSON"
        return res

    async def interpret(self, text: str, gazetteer: list[dict], regions: list[dict]) -> LLMResult:
        places = "; ".join(f"{p['id']}={p['name']}" for p in gazetteer)
        regs = "; ".join(f"{r['id']}={r['name']}" for r in regions)
        system = (
            "You convert a marine-safety question (any language) into ORCA's structured query form. "
            "Only use place identifiers from the provided lists; use an empty string when none applies. "
            "Never output coordinates. Translate the time phrase to short English (e.g. 'tomorrow 5 am', "
            "'next 12 hours', 'past 14 days'); empty string if no time is mentioned. Use -1 for offshore_km "
            "when not stated.")
        user = f"PLACES: {places}\nREGIONS: {regs}\n\nQUESTION: {text}"
        return await self._json_call(system, user, INTERPRET_SCHEMA, effort="low", max_tokens=2000)

    async def narrate(self, facts: dict, role: str, language: str) -> LLMResult:
        system = (
            "You are the communication layer of ORCA, a marine decision-support system. You receive facts computed "
            "by deterministic software. Rewrite them for the given audience and language. Rules: do not add, change "
            "or infer any number, place, time or source that is not in FACTS; copy numbers exactly using Western "
            "digits; keep the decision label exactly as given; do not number list items; never state that conditions "
            "are definitely safe; say clearly when data was unavailable. Audience styles: fisherman = short, plain, "
            "practical; authority = formal situation report; researcher = precise with methods and uncertainty; "
            "operator = navigational and route-focused.")
        user = f"AUDIENCE: {role}\nLANGUAGE (ISO 639-1): {language}\nFACTS:\n{json.dumps(facts, default=str, ensure_ascii=False)}"
        res = await self._json_call(system, user, NARRATE_SCHEMA, effort="medium", max_tokens=6000)
        if res.data:
            text = " ".join([res.data.get("headline", ""), res.data.get("summary", ""), *res.data.get("bullets", [])])
            chk = grounding_check(text, facts)
            res.notes.append(json.dumps(chk))
            if not chk["passed"]:
                res.error = f"grounding check failed: unsupported numbers {chk['unsupported_numbers'][:5]}"
                res.data = None
        return res
