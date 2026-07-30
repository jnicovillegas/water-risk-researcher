"""Async orchestration: research → verify → (optional) critique.

Concurrency is bounded at every stage with semaphores. This is the shape that
scales to 1,000 locations: the same code path, just wider fan-out plus the disk
cache absorbing shared sources. See README "Scaling to 1,000".
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from .cache import DiskCache
from .config import Settings
from .critique import CritiqueAgent
from .fetch import Fetcher, build_client
from .models import LocationReport
from .research import ResearchAgent
from .support import SupportJudge
from .verify import Verifier


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or "source"
    except ValueError:
        return "source"


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache = DiskCache(settings.cache_dir, enabled=settings.use_cache)
        self.research_agent = ResearchAgent(settings, self.cache)
        self.verifier = Verifier(settings, Fetcher(settings, self.cache))
        self.judge = SupportJudge(settings) if settings.support_check else None
        self.critic = CritiqueAgent(settings) if settings.critique else None

    async def run(self, locations: list[str], on_event=None) -> list[LocationReport]:
        research_sem = asyncio.Semaphore(self.settings.research_concurrency)
        verify_sem = asyncio.Semaphore(self.settings.verify_concurrency)

        def emit(loc: str, msg: str) -> None:
            if on_event:
                on_event(loc, msg)

        async with build_client(self.settings) as client:

            async def process(location: str) -> LocationReport:
                emit(location, "🔍 starting research…")
                async with research_sem:
                    report = await self.research_agent.research(
                        location, on_event=lambda m: emit(location, m)
                    )
                if report.error:
                    emit(location, f"⛔ {report.error}")
                    return report

                # Verify every finding concurrently (bounded).
                async def verify_one(finding):
                    async with verify_sem:
                        emit(location, f"🔗 verifying {_domain(finding.source_url)}…")
                        finding.validation = await self.verifier.verify(client, finding)

                await asyncio.gather(*(verify_one(f) for f in report.all_findings()))

                # Second verification layer: does each verified excerpt back its claim?
                if self.judge:
                    emit(location, "⚖️  checking claim support…")
                    await self.judge.judge(report)

                if self.critic:
                    emit(location, "🧠 scoring source relevance…")
                    await self.critic.critique(report)

                findings = report.all_findings()
                ok = sum(1 for f in findings if f.validation and f.validation.status.is_ok)
                emit(location, f"✓ done — {ok}/{len(findings)} verified")
                return report

            return await asyncio.gather(*(process(loc) for loc in locations))
