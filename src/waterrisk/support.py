"""Claim-support judge — the second, semantic verification layer.

The deterministic verifier proves the excerpt EXISTS on the page. It cannot prove
the excerpt SUPPORTS the data claim — that requires understanding meaning, which
only a model can do. So this is a separate, fresh agent (no research history, no
web access) that receives ONLY the claim and its verbatim excerpt and judges,
strictly and closed-book, whether the excerpt backs the claim.

Why this stays honest rather than "trusting the AI again":
  - Closed-book: it may use nothing but the excerpt provided.
  - Narrow, closed question (YES/PARTIAL/NO) — not open-ended generation.
  - Conservative bias: when in doubt, downgrade. A false YES is the worst outcome.
  - Auditable: the report shows claim + excerpt + verdict side by side, so a human
    can confirm each judgment in seconds.
  - It can only downgrade confidence, never invent data.

Runs only on findings whose excerpt was verified — judging an unverified (possibly
hallucinated) excerpt would be meaningless.
"""

from __future__ import annotations

import json

from anthropic import AsyncAnthropic

from .config import Settings
from .models import ClaimSupport, Finding, LocationReport, SupportVerdict

_SYSTEM = """You are a strict source-support auditor. You are given a list of \
items, each with a CLAIM and a verbatim EXCERPT quoted from the claim's source page. \
For each item, decide whether the excerpt supports the claim.

Rules:
- Judge ONLY from the excerpt. Do not use any outside knowledge. If the excerpt \
does not state something, it is NOT supported — even if you believe the claim is \
true. Being on the same TOPIC is NOT support.
- First identify the claim's CENTRAL assertion: its main action, event, or fact. \
Then break the rest of the claim into its individual factual assertions.
- YES: the central assertion AND every other assertion are supported by the excerpt.
- PARTIAL: the central assertion IS clearly supported, but the claim adds specifics \
(figures, dates, names, scope) the excerpt does not state.
- NO: the central assertion is NOT supported — even if the excerpt is on the same \
topic or only supports background details — or it is contradicted, or the excerpt \
is about something else. Example: claim = "residents protested the construction of \
data centers", excerpt = "frustration is boiling over" -> NO, because the central \
action (protesting data-center construction) is not in the excerpt.
- When genuinely in doubt, choose the more conservative label (YES -> PARTIAL -> NO).
- For PARTIAL or NO, name the exact part of the claim that is not supported.

Return ONLY JSON: {"results": [{"index": <int>, "verdict": "YES"|"PARTIAL"|"NO", \
"reason": "<one sentence; for PARTIAL/NO name the unsupported part>"}]}."""


class SupportJudge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncAnthropic()  # fresh agent: no web tools, no research context

    async def judge(self, report: LocationReport) -> None:
        """Attach a ClaimSupport verdict to each VERIFIED finding, in place."""
        items: list[Finding] = [
            f for f in report.all_findings()
            if f.validation and f.validation.status.is_ok and f.excerpt.strip()
        ]
        if not items:
            return

        payload = [
            {"index": i, "claim": f.data, "excerpt": f.excerpt}
            for i, f in enumerate(items)
        ]
        try:
            resp = await self.client.messages.create(
                model=self.settings.model,
                max_tokens=2048,
                system=_SYSTEM,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            )
            text = "".join(getattr(b, "text", "") for b in resp.content if b.type == "text")
            data = json.loads(_first_json(text))
        except Exception:
            return  # best-effort: never break the run over the support pass

        for row in data.get("results", []):
            idx = row.get("index")
            verdict = str(row.get("verdict", "")).strip().upper()
            if isinstance(idx, int) and 0 <= idx < len(items) and verdict in SupportVerdict.__members__:
                items[idx].support = ClaimSupport(
                    verdict=SupportVerdict[verdict],
                    reason=str(row.get("reason", "")).strip(),
                )


def _first_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else "{}"
