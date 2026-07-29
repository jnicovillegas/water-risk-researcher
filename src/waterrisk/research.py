"""The generation layer — Claude + the native web_search tool.

Claude runs grounded searches (executed server-side by Anthropic in a single
request) and returns structured findings. We treat its output as a *proposal*:
real URLs, but excerpts that still must be independently verified downstream.

The search layer is intentionally isolated behind one class so it can be swapped
(Tavily, Serper, Brave) without touching verification or reporting.
"""

from __future__ import annotations

import json

from anthropic import AsyncAnthropic

from .cache import DiskCache
from .config import Settings
from .models import Dimension, DimensionResult, Finding, LocationReport

SYSTEM_PROMPT = """You are a water-risk research assistant for an environmental \
data company. Accuracy and traceability are the absolute priority. You use the \
web_search tool to find real, authoritative sources and you NEVER invent URLs, \
quotes, or figures.

Rules:
- For each dimension, provide findings from at least {n_sources} DIFFERENT sources \
(different domains).
- Prefer authoritative sources (e.g. WRI Aqueduct, government/regulatory bodies, \
established news outlets, peer-reviewed or institutional reports).
- The "excerpt" MUST be copied VERBATIM from the page at "source_url" — a \
contiguous quote of one to three sentences, exactly as it appears on the page. \
Do not paraphrase, summarize, translate, or stitch together non-adjacent text. \
An independent program will re-download the page and check the excerpt character \
by character, so an inexact excerpt will be flagged as a failure.
- If you cannot find a genuine source for a dimension, return an empty "findings" \
list for it and explain in "note". Never fabricate a source to fill the gap.

Return ONLY a JSON object, no prose and no markdown fences, matching exactly:
{{
  "dimensions": [
    {{
      "dimension": "water_stress" | "incidents" | "regulations",
      "findings": [
        {{
          "data": "concise factual claim",
          "source_url": "https://...",
          "source_title": "page or publication title",
          "excerpt": "verbatim quote from the page"
        }}
      ],
      "note": "only if findings is empty"
    }}
  ]
}}"""


def _build_user_prompt() -> str:
    lines = ["Research the following three water-risk dimensions for this location.", ""]
    for dim in Dimension:
        lines.append(f"- {dim.value}: {dim.prompt_hint}")
    return "\n".join(lines)


class ResearchAgent:
    def __init__(self, settings: Settings, cache: DiskCache):
        self.settings = settings
        self.cache = cache
        self.client = AsyncAnthropic()
        self.system = SYSTEM_PROMPT.format(n_sources=settings.sources_per_dimension)
        self.user_dims = _build_user_prompt()

    async def research(self, location: str) -> LocationReport:
        cache_key = f"{self.settings.model}|{location}"
        cached = self.cache.get("research", cache_key)
        if cached is not None:
            return self._parse(location, cached)

        try:
            raw = await self._call_claude(location)
        except Exception as exc:  # surface API/network errors per-location, don't crash the run
            return LocationReport(location=location, error=f"research failed: {type(exc).__name__}: {exc}")

        self.cache.set("research", cache_key, raw)
        return self._parse(location, raw)

    async def _call_claude(self, location: str) -> dict:
        message = f"Location: {location}\n\n{self.user_dims}"
        resp = await self.client.messages.create(
            model=self.settings.model,
            max_tokens=4096,
            system=self.system,
            messages=[{"role": "user", "content": message}],
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": self.settings.max_search_uses,
            }],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content if b.type == "text")
        return _extract_json(text)

    def _parse(self, location: str, payload: dict) -> LocationReport:
        report = LocationReport(location=location)
        by_dim = {d.value: d for d in Dimension}
        seen = set()
        for raw_dim in payload.get("dimensions", []):
            key = str(raw_dim.get("dimension", "")).strip().lower()
            if key not in by_dim or key in seen:
                continue
            seen.add(key)
            dim = by_dim[key]
            findings = [
                Finding(
                    dimension=dim,
                    data=str(f.get("data", "")).strip(),
                    source_url=str(f.get("source_url", "")).strip(),
                    source_title=str(f.get("source_title", "")).strip(),
                    excerpt=str(f.get("excerpt", "")).strip(),
                )
                for f in raw_dim.get("findings", [])
                if str(f.get("data", "")).strip()
            ]
            report.dimensions.append(
                DimensionResult(dimension=dim, findings=findings,
                                note=str(raw_dim.get("note", "")).strip())
            )
        # Ensure all three dimensions are represented, even if empty.
        for dim in Dimension:
            if dim.value not in seen:
                report.dimensions.append(
                    DimensionResult(dimension=dim, note="no data returned by research step")
                )
        report.dimensions.sort(key=lambda d: list(Dimension).index(d.dimension))
        return report


def _extract_json(text: str) -> dict:
    """Tolerant JSON extraction: handles bare JSON, fenced blocks, or JSON with
    surrounding prose."""
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown fences if present.
    if "```" in text:
        segment = text.split("```")[1]
        segment = segment[4:] if segment.lower().startswith("json") else segment
        try:
            return json.loads(segment.strip())
        except json.JSONDecodeError:
            pass
    # Last resort: first '{' .. last '}'.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}
