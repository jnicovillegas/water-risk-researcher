"""Unit tests for the deterministic multi-source check (no network, no AI)."""

from waterrisk.models import Dimension, Finding
from waterrisk.sources import normalize_domain, source_counts


def _f(url: str) -> Finding:
    return Finding(dimension=Dimension.WATER_STRESS, data="x", source_url=url, excerpt="y")


def test_www_is_stripped():
    assert normalize_domain("https://www.spglobal.com/a/b") == "spglobal.com"
    assert normalize_domain("https://spglobal.com/a") == "spglobal.com"


def test_two_articles_same_domain_count_as_one_source():
    findings = [
        _f("https://mexicobusiness.news/a"),
        _f("https://mexicobusiness.news/b"),   # different article, same outlet
        _f("https://spglobal.com/c"),
    ]
    domains, urls = source_counts(findings)
    assert domains == 2      # the bar: two distinct outlets
    assert urls == 3         # transparency: three distinct articles


def test_same_url_twice_counts_once():
    findings = [_f("https://x.com/a"), _f("https://x.com/a")]
    assert source_counts(findings) == (1, 1)


def test_missing_urls_are_ignored():
    findings = [_f(""), _f("https://x.com/a")]
    assert source_counts(findings) == (1, 1)


def test_meets_and_fails_the_bar():
    two_outlets = [_f("https://a.com/x"), _f("https://b.com/y")]
    one_outlet = [_f("https://a.com/x"), _f("https://a.com/y")]
    assert source_counts(two_outlets)[0] >= 2      # OK
    assert source_counts(one_outlet)[0] < 2        # flagged
