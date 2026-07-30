"""The deterministic verification layer — the heart of the tool.

No LLM is involved here. Given a finding {source_url, excerpt}, we re-fetch the
live page and prove (or disprove) that the excerpt actually exists in it. This
is what makes the whole pipeline trustworthy: the model can hallucinate, but it
cannot make text appear on a page it doesn't control.

Matching strategy:
  1. Normalize both excerpt and page text (unicode, whitespace, case).
  2. Exact substring check — fast and unambiguous.
  3. Fuzzy fallback (rapidfuzz.partial_ratio) to absorb real-world noise:
     whitespace, ellipses, HTML artifacts, minor punctuation differences.
     Guarded by a min length and a threshold to avoid false positives.
"""

from __future__ import annotations

import re
import unicodedata

import httpx
from rapidfuzz import fuzz

from .config import Settings
from .fetch import Fetcher
from .models import Finding, ValidationResult, ValidationStatus

_WS = re.compile(r"\s+")
# Common "…" style truncation the model adds around a quote; ignore for matching.
_ELLIPSIS = re.compile(r"(\.\.\.|…)")


def _snap_to_words(text: str, start: int, end: int) -> str:
    """Expand a character-level match window out to whole-word boundaries, so the
    shown snippet doesn't start or end mid-word (e.g. 'n 2022' -> 'in 2022')."""
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return text[start:end].strip()


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _ELLIPSIS.sub(" ", text)
    text = text.replace("“", '"').replace("”", '"')  # smart quotes
    text = text.replace("‘", "'").replace("’", "'")
    text = _WS.sub(" ", text)
    return text.strip().lower()


def match_excerpt(excerpt: str, page_text: str, settings: Settings) -> ValidationResult:
    """Pure function: does `excerpt` appear in `page_text`? No I/O."""
    ex = normalize(excerpt)
    page = normalize(page_text)

    if not ex:
        return ValidationResult(status=ValidationStatus.EXCERPT_NOT_FOUND,
                                detail="empty excerpt")
    if not page:
        return ValidationResult(status=ValidationStatus.EXCERPT_NOT_FOUND,
                                detail="empty page content")

    # 1. Exact substring — the strongest signal.
    if ex in page:
        return ValidationResult(status=ValidationStatus.MATCH, method="exact", score=100.0)

    # 2. Fuzzy fallback. Skip for very short excerpts (too easy to false-match).
    if len(ex) < settings.min_excerpt_chars:
        return ValidationResult(
            status=ValidationStatus.EXCERPT_NOT_FOUND, method="exact", score=0.0,
            detail="exact match failed; excerpt too short for a safe fuzzy check",
        )

    # partial_ratio_alignment gives both the score AND where on the page the best
    # match landed — so we can show the exact snippet that matched (auditable, not a
    # black-box score). The snippet is normalized (lowercase/collapsed) page text.
    alignment = fuzz.partial_ratio_alignment(ex, page)
    score = alignment.score if alignment else 0.0
    if score >= settings.fuzzy_threshold:
        matched = _snap_to_words(page, alignment.dest_start, alignment.dest_end) if alignment else ""
        return ValidationResult(
            status=ValidationStatus.MATCH, method="fuzzy", score=score, matched_text=matched,
        )

    return ValidationResult(
        status=ValidationStatus.EXCERPT_NOT_FOUND, method="fuzzy", score=score,
        detail=f"best fuzzy score {score:.0f}% < threshold {settings.fuzzy_threshold:.0f}%",
    )


class Verifier:
    def __init__(self, settings: Settings, fetcher: Fetcher):
        self.settings = settings
        self.fetcher = fetcher

    async def verify(self, client: httpx.AsyncClient, finding: Finding) -> ValidationResult:
        fetched = await self.fetcher.fetch(client, finding.source_url)
        if not fetched.ok:
            return ValidationResult(
                status=fetched.status, http_status=fetched.http_status,
                detail=fetched.detail,
            )
        result = match_excerpt(finding.excerpt, fetched.text, self.settings)
        result.http_status = fetched.http_status
        return result
