"""Robust async page fetching + visible-text extraction.

This module is deliberately conservative: its job is to get the *full visible
text* of a page so the verifier can look for the excerpt anywhere on it. We do
NOT strip boilerplate (nav/footer) here, because an excerpt could legitimately
live in a caption or sidebar — over-cleaning would cause false negatives.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .cache import DiskCache
from .config import Settings
from .models import ValidationStatus

# Substrings that signal an anti-bot interstitial rather than real content.
_BLOCK_MARKERS = (
    "just a moment...",
    "cf-browser-verification",
    "attention required",
    "captcha-delivery",
    "verifying you are human",
    "access denied",
    "request blocked",
)


@dataclass
class FetchResult:
    ok: bool
    status: ValidationStatus            # MATCH is never set here; only failure kinds or a sentinel
    text: str = ""
    http_status: int | None = None
    detail: str = ""


def extract_visible_text(html: str) -> str:
    """Return all human-visible text from an HTML document."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    return soup.get_text(separator=" ")


def _looks_blocked(html: str) -> bool:
    head = html[:4000].lower()
    return any(marker in head for marker in _BLOCK_MARKERS)


class Fetcher:
    """Async fetcher with retries, block detection and a shared page cache."""

    def __init__(self, settings: Settings, cache: DiskCache):
        self.settings = settings
        self.cache = cache

    async def fetch(self, client: httpx.AsyncClient, url: str) -> FetchResult:
        if not url or not url.startswith(("http://", "https://")):
            return FetchResult(False, ValidationStatus.NO_SOURCE, detail="missing or invalid URL")

        cached = self.cache.get("page", url)
        if cached is not None:
            return FetchResult(**cached)

        result = await self._fetch_live(client, url)
        # Only cache successful text pulls; failures may be transient.
        if result.ok:
            self.cache.set("page", url, result.__dict__)
        return result

    async def _fetch_live(self, client: httpx.AsyncClient, url: str) -> FetchResult:
        last_detail = ""
        for attempt in range(self.settings.max_retries + 1):
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                last_detail = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(0.6 * (attempt + 1))  # linear backoff
                continue

            if resp.status_code in (403, 429) or resp.status_code >= 500:
                # 4xx auth/rate or 5xx server — retry a couple of times.
                last_detail = f"HTTP {resp.status_code}"
                if resp.status_code in (403, 429) and _looks_blocked(resp.text):
                    return FetchResult(False, ValidationStatus.BLOCKED,
                                       http_status=resp.status_code, detail="bot protection")
                await asyncio.sleep(0.6 * (attempt + 1))
                continue

            if resp.status_code >= 400:
                return FetchResult(False, ValidationStatus.UNREACHABLE,
                                   http_status=resp.status_code, detail=f"HTTP {resp.status_code}")

            html = resp.text
            if _looks_blocked(html):
                return FetchResult(False, ValidationStatus.BLOCKED,
                                   http_status=resp.status_code, detail="bot protection interstitial")

            text = extract_visible_text(html)[: self.settings.max_page_chars]
            return FetchResult(True, ValidationStatus.MATCH, text=text,
                               http_status=resp.status_code)

        # Exhausted retries.
        status = ValidationStatus.BLOCKED if "403" in last_detail or "429" in last_detail \
            else ValidationStatus.UNREACHABLE
        return FetchResult(False, status, detail=last_detail or "unreachable")


def build_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.request_timeout,
        follow_redirects=True,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        },
    )
