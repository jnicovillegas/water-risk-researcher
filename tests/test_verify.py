"""Unit tests for the deterministic matcher.

Data integrity is the one thing that must never silently break, and — crucially —
it is testable with zero network and zero API cost. These tests pin the exact and
fuzzy matching behaviour that the whole tool's trustworthiness rests on.

Run: pytest
"""

from waterrisk.config import Settings
from waterrisk.fetch import extract_visible_text
from waterrisk.models import ValidationStatus
from waterrisk.verify import match_excerpt, normalize

S = Settings()

PAGE = (
    "<html><body><nav>Home About</nav>"
    "<article><p>Mexicali municipality faces extremely high baseline water "
    "stress, according to the WRI Aqueduct tool.</p>"
    "<p>Residents protested in 2018 against a new brewery.</p></article>"
    "<script>console.log('x')</script></body></html>"
)
TEXT = extract_visible_text(PAGE)


def test_exact_match():
    r = match_excerpt("Mexicali municipality faces extremely high baseline water stress", TEXT, S)
    assert r.status is ValidationStatus.MATCH
    assert r.method == "exact"


def test_fuzzy_match_absorbs_whitespace_and_ellipsis():
    # Extra spaces, smart quotes, and a leading ellipsis — a realistic model excerpt.
    excerpt = "…Mexicali  municipality   faces extremely high baseline water stress…"
    r = match_excerpt(excerpt, TEXT, S)
    assert r.status is ValidationStatus.MATCH


def test_hallucinated_excerpt_is_rejected():
    r = match_excerpt("Mexicali has abundant water and no restrictions whatsoever", TEXT, S)
    assert r.status is ValidationStatus.EXCERPT_NOT_FOUND
    assert r.score < S.fuzzy_threshold


def test_empty_excerpt_fails():
    r = match_excerpt("", TEXT, S)
    assert r.status is ValidationStatus.EXCERPT_NOT_FOUND


def test_short_excerpt_requires_exact_match():
    # Below min_excerpt_chars, a non-exact excerpt must NOT fuzzy-pass.
    r = match_excerpt("high water", TEXT, S)  # not a verbatim substring
    assert r.status is ValidationStatus.EXCERPT_NOT_FOUND


def test_scripts_are_stripped_from_page_text():
    assert "console.log" not in TEXT
    assert "Mexicali" in TEXT


def test_normalize_is_case_and_quote_insensitive():
    assert normalize("The “Quote”  Here") == normalize("the \"quote\" here")
