"""Rendering tests for all output formats — no network, no AI."""

import json

from waterrisk.models import (
    ClaimSupport, Dimension, DimensionResult, Finding, LocationReport,
    SupportVerdict, ValidationResult, ValidationStatus,
)
from waterrisk.report import render_csv, render_json, render_markdown, render_pdf


def _sample() -> list[LocationReport]:
    ok = Finding(
        dimension=Dimension.WATER_STRESS,
        data="São Paulo faces low-to-medium baseline water stress.",
        source_url="https://www.wri.org/x", source_title="WRI",
        excerpt="São Paulo faces low to medium water stress.",
        validation=ValidationResult(status=ValidationStatus.MATCH, method="exact", score=100),
        support=ClaimSupport(verdict=SupportVerdict.YES, reason="fully supported"),
    )
    blocked = Finding(
        dimension=Dimension.INCIDENTS, data="Protests in 2015.",
        source_url="https://news.example/x", excerpt="…residents protested…",
        validation=ValidationResult(status=ValidationStatus.BLOCKED, detail="bot protection"),
    )
    dims = [
        DimensionResult(dimension=Dimension.WATER_STRESS, findings=[ok]),
        DimensionResult(dimension=Dimension.INCIDENTS, findings=[blocked]),
        DimensionResult(dimension=Dimension.REGULATIONS, note="no source found"),
    ]
    return [LocationReport(location="Brewery in São Paulo, Brazil", dimensions=dims)]


def test_markdown_has_title_and_location():
    md = render_markdown(_sample())
    assert "Water Risk Research Report" in md
    assert "São Paulo" in md


def test_csv_round_trips():
    import csv, io
    rows = list(csv.DictReader(io.StringIO(render_csv(_sample()))))
    assert len(rows) == 2                       # two findings; the empty dimension has none
    assert rows[0]["claim_support"] == "YES"


def test_json_is_valid_and_complete():
    data = json.loads(render_json(_sample()))
    assert data[0]["location"] == "Brewery in São Paulo, Brazil"
    assert data[0]["dimensions"][0]["findings"][0]["support"]["verdict"] == "YES"


def test_pdf_produces_valid_pdf_bytes():
    out = render_pdf(_sample())
    assert out[:4] == b"%PDF"          # a real PDF
    assert len(out) > 800              # non-trivial content (accents survived sanitizing)
