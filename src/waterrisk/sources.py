"""Deterministic multi-source check.

The brief requires >= 2 DIFFERENT sources per researched item (dimension). Like the
excerpt-existence check, this is deterministic and un-gameable — no AI, no judgment.

A "source" is an outlet, not a page: two articles from the same domain count as one
source, so the bar can't be met by pulling two quotes from a single site. We report
distinct domains as the bar plus the article count for transparency, keep every
finding, and only FLAG insufficient sourcing — never force a second source (forcing
would invite a fabricated one, which contradicts the whole point of the tool).

The check is per-dimension: sources are only compared within the same item.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .models import Finding


def normalize_domain(url: str) -> str:
    """Host without a leading 'www.', lowercased. www.x.com and x.com are one site."""
    try:
        host = urlparse(url).netloc.lower().strip()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def source_counts(findings: list[Finding]) -> tuple[int, int]:
    """Return (distinct_domains, distinct_article_urls) for one dimension's findings."""
    domains: set[str] = set()
    urls: set[str] = set()
    for f in findings:
        url = (f.source_url or "").strip()
        if not url:
            continue
        urls.add(url)
        domain = normalize_domain(url)
        if domain:
            domains.add(domain)
    return len(domains), len(urls)
