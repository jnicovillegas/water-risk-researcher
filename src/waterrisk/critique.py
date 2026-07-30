"""Optional AI self-critique of source relevance (bonus feature).

After verification, a second Claude pass — with NO web access — scores how
authoritative and on-topic each *verified* source is for its dimension. This is
a separate concern from "does the excerpt exist" (verification): a quote can be
real but come from a weak source. Only runs with --relevance.
"""

from __future__ import annotations

import json

from anthropic import AsyncAnthropic

from .config import Settings
from .models import Finding, LocationReport, Relevance

_SYSTEM = """You are a critical reviewer of source quality for water-risk \
research. For each item you receive {location, dimension, data, source_url}, \
rate how authoritative and relevant the SOURCE is for that specific claim, from \
0 (irrelevant/unreliable) to 5 (authoritative and directly on-topic). \
Consider domain authority (government, WRI, established outlets vs blogs/forums) \
and topical fit. Return ONLY JSON: \
{"ratings": [{"index": <int>, "score": <0-5>, "reason": "<one short sentence>"}]}."""


class CritiqueAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncAnthropic()

    async def critique(self, report: LocationReport) -> None:
        """Attach a Relevance score to each verified finding, in place."""
        items: list[Finding] = [
            f for f in report.all_findings()
            if f.validation and f.validation.status.is_ok
        ]
        if not items:
            return

        payload = [
            {"index": i, "location": report.location,
             "dimension": f.dimension.value, "data": f.data, "source_url": f.source_url}
            for i, f in enumerate(items)
        ]
        try:
            resp = await self.client.messages.create(
                model=self.settings.model,
                max_tokens=1024,
                system=_SYSTEM,
                messages=[{"role": "user", "content": json.dumps(payload)}],
            )
            text = "".join(getattr(b, "text", "") for b in resp.content if b.type == "text")
            data = json.loads(_first_json(text))
        except Exception:
            return  # critique is best-effort; never break the run

        for rating in data.get("ratings", []):
            idx = rating.get("index")
            if isinstance(idx, int) and 0 <= idx < len(items):
                items[idx].relevance = Relevance(
                    score=max(0, min(5, int(rating.get("score", 0)))),
                    reason=str(rating.get("reason", "")).strip(),
                )


def _first_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else "{}"
