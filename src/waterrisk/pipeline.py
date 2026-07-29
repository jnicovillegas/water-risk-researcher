"""Async orchestration: research → verify → (optional) critique.

Concurrency is bounded at every stage with semaphores. This is the shape that
scales to 1,000 locations: the same code path, just wider fan-out plus the disk
cache absorbing shared sources. See README "Scaling to 1,000".
"""

from __future__ import annotations

import asyncio

from .cache import DiskCache
from .config import Settings
from .critique import CritiqueAgent
from .fetch import Fetcher, build_client
from .models import LocationReport
from .research import ResearchAgent
from .verify import Verifier


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache = DiskCache(settings.cache_dir, enabled=settings.use_cache)
        self.research_agent = ResearchAgent(settings, self.cache)
        self.verifier = Verifier(settings, Fetcher(settings, self.cache))
        self.critic = CritiqueAgent(settings) if settings.critique else None

    async def run(self, locations: list[str], on_progress=None) -> list[LocationReport]:
        research_sem = asyncio.Semaphore(self.settings.research_concurrency)
        verify_sem = asyncio.Semaphore(self.settings.verify_concurrency)

        async with build_client(self.settings) as client:

            async def process(location: str) -> LocationReport:
                async with research_sem:
                    report = await self.research_agent.research(location)

                # Verify every finding concurrently (bounded).
                async def verify_one(finding):
                    async with verify_sem:
                        finding.validation = await self.verifier.verify(client, finding)

                await asyncio.gather(*(verify_one(f) for f in report.all_findings()))

                if self.critic:
                    await self.critic.critique(report)

                if on_progress:
                    on_progress(report)
                return report

            return await asyncio.gather(*(process(loc) for loc in locations))
