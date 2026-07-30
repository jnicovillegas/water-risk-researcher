"""Rendering: Markdown (matches the brief's example format), CSV, JSON, and PDF."""

from __future__ import annotations

import csv
import io
import json

from .models import LocationReport, SupportVerdict, ValidationResult, ValidationStatus
from .sources import source_counts


def _summary(reports: list[LocationReport]) -> tuple[int, int, int, int]:
    """Return (total, verified, judged, fully_supported)."""
    total = verified = judged = fully_supported = 0
    for r in reports:
        for f in r.all_findings():
            total += 1
            if f.validation and f.validation.status.is_ok:
                verified += 1
            if f.support:
                judged += 1
                if f.support.verdict is SupportVerdict.YES:
                    fully_supported += 1
    return total, verified, judged, fully_supported


def render_markdown(reports: list[LocationReport], min_sources: int = 2) -> str:
    total, verified, judged, fully_supported = _summary(reports)
    rate = (verified / total * 100) if total else 0.0

    dims_total = dims_ok = 0
    for r in reports:
        for dim in r.dimensions:
            if dim.findings:
                dims_total += 1
                if source_counts(dim.findings)[0] >= min_sources:
                    dims_ok += 1

    out: list[str] = [
        "# Water Risk Research Report",
        "",
        f"**Locations analysed:** {len(reports)}  ",
        f"**Verified data points:** {verified}/{total} ({rate:.0f}% source-validated)",
    ]
    if judged:
        s_rate = fully_supported / judged * 100
        out.append(
            f"**Fully supported by source:** {fully_supported}/{judged} "
            f"({s_rate:.0f}% of verified claims fully backed by their excerpt)  "
        )
    if dims_total:
        out.append(
            f"**Multi-source coverage:** {dims_ok}/{dims_total} dimensions with "
            f"≥{min_sources} distinct sources  "
        )
    out += [
        "",
        "> Two independent checks per data point: **Validation** confirms the excerpt "
        "really exists on the page (mechanical); **Claim support** confirms the excerpt "
        "actually backs the claim (`YES`/`PARTIAL`/`NO`). Failures are surfaced, never hidden.",
        "",
        "---",
        "",
    ]

    for r in reports:
        out.append(f"## 📍 Location: {r.location}")
        out.append("")
        if r.error:
            out.append(f"> ⛔ Research error: {r.error}")
            out.append("")
            continue

        for dim in r.dimensions:
            header = f"### {dim.dimension.emoji} Dimension: {dim.dimension.label}"
            if dim.findings:
                n_dom, n_url = source_counts(dim.findings)
                if n_dom >= min_sources:
                    extra = f" across {n_url} articles" if n_url > n_dom else ""
                    header += f"  ·  Sources: {n_dom} distinct{extra}"
                else:
                    word = "source" if n_dom == 1 else "sources"
                    header += f"  ·  ⚠️ {n_dom} distinct {word} (brief requires ≥{min_sources})"
            out.append(header)
            if not dim.findings:
                out.append(f"- _No data — {dim.note or 'no source found'}_")
                out.append("")
                continue
            for f in dim.findings:
                v = f.validation
                out.append(f"- **Data:** {f.data}")
                title = f" — {f.source_title}" if f.source_title else ""
                out.append(f"  - **Source:** {f.source_url or '_none_'}{title}")
                out.append(f"  - **Excerpt:** “{f.excerpt}”" if f.excerpt else "  - **Excerpt:** _none_")
                out.append(f"  - **Validation:** {v.label() if v else '_not run_'}")
                if v and v.detail and not v.status.is_ok:
                    out.append(f"    - _{v.detail}_")
                if v and v.method == "fuzzy" and v.status.is_ok and v.matched_text:
                    out.append(f"    - _matched on page: “{v.matched_text}”_")
                if f.support:
                    out.append(f"  - **Claim support:** {f.support.label()}")
                if f.relevance:
                    out.append(f"    - **Source relevance:** {f.relevance.score}/5 — {f.relevance.reason}")
            out.append("")
        out.append("---")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def render_csv(reports: list[LocationReport]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "location", "dimension", "data", "source_url", "source_title",
        "excerpt", "validation_status", "match_method", "match_score", "matched_snippet",
        "http_status", "claim_support", "claim_support_reason", "relevance_score",
    ])
    for r in reports:
        for f in r.all_findings():
            v = f.validation
            writer.writerow([
                r.location, f.dimension.value, f.data, f.source_url, f.source_title,
                f.excerpt,
                v.status.value if v else "not_run",
                v.method if v else "",
                f"{v.score:.0f}" if v else "",
                v.matched_text if v else "",
                v.http_status if v and v.http_status else "",
                f.support.verdict.value if f.support else "",
                f.support.reason if f.support else "",
                f.relevance.score if f.relevance else "",
            ])
    return buf.getvalue()


def render_json(reports: list[LocationReport]) -> str:
    """Full structured output — machine-readable, nothing dropped."""
    return json.dumps(
        [r.model_dump(mode="json") for r in reports],
        indent=2, ensure_ascii=False,
    )


# ── PDF rendering (fpdf2 — pure Python, no system deps) ──────────────────────

_TEAL = (15, 76, 92)
_GREY = (110, 125, 132)
_DARK = (45, 55, 60)
_GREEN = (26, 138, 74)
_AMBER = (176, 116, 25)
_RED = (192, 57, 43)

# fpdf2 core fonts are latin-1; map typographic characters and drop the rest.
_PDF_REPL = {
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "—": "-", "–": "-", "…": "...", "→": "->",
    "·": "-", " ": " ", "•": "-",
}


def _l1(text: str) -> str:
    for k, v in _PDF_REPL.items():
        text = text.replace(k, v)
    # Bold/italic markers would be interpreted by markdown=True; neutralize them.
    text = text.replace("**", "").replace("__", "")
    return text.encode("latin-1", "replace").decode("latin-1")


def _validation_text(v: ValidationResult) -> str:
    if v.status.is_ok:
        method = "exact" if v.method == "exact" else f"fuzzy {v.score:.0f}%"
        return f"MATCH FOUND ({method})"
    reasons = {
        ValidationStatus.EXCERPT_NOT_FOUND: "excerpt not found in source",
        ValidationStatus.UNREACHABLE: "source unreachable",
        ValidationStatus.BLOCKED: "source blocked (bot protection)",
        ValidationStatus.NO_SOURCE: "no source provided",
    }
    return "FAILED VALIDATION - " + reasons.get(v.status, v.status.value)


def render_pdf(reports: list[LocationReport], min_sources: int = 2) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    NEXT = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def line(txt, size=9.5, color=_DARK, style="", h=5.0, md=True):
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(0, h, _l1(txt), markdown=md, **NEXT)

    total, verified, judged, fully = _summary(reports)
    dims_total = dims_ok = 0
    for r in reports:
        for dim in r.dimensions:
            if dim.findings:
                dims_total += 1
                if source_counts(dim.findings)[0] >= min_sources:
                    dims_ok += 1

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    line("Water Risk Research Report", size=20, color=_TEAL, style="B", h=9)
    rate = (verified / total * 100) if total else 0.0
    line(f"Locations analysed: {len(reports)}", size=10, color=_GREY, h=5)
    line(f"Verified data points: {verified}/{total} ({rate:.0f}% source-validated)", size=10, color=_GREY, h=5)
    if judged:
        line(f"Fully supported by source: {fully}/{judged} ({fully / judged * 100:.0f}%)", size=10, color=_GREY, h=5)
    if dims_total:
        line(f"Multi-source coverage: {dims_ok}/{dims_total} dimensions with >={min_sources} distinct sources",
             size=10, color=_GREY, h=5)

    for r in reports:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*_TEAL)
        pdf.set_draw_color(*_TEAL)
        pdf.cell(0, 8, _l1(f"Location: {r.location}"), border="B", **NEXT)
        pdf.ln(1)
        if r.error:
            line(f"Research error: {r.error}", color=_RED, style="I")
            continue

        for dim in r.dimensions:
            src = ""
            if dim.findings:
                nd, nu = source_counts(dim.findings)
                if nd >= min_sources:
                    src = f"  -  {nd} distinct sources" + (f" across {nu} articles" if nu > nd else "")
                else:
                    src = f"  -  {nd} distinct source (needs >={min_sources})"
            pdf.ln(1.5)
            line(f"{dim.dimension.label}{src}", size=11, color=_TEAL, style="B", h=6)
            if not dim.findings:
                line(f"No data - {dim.note or 'no source found'}", size=9, color=_GREY, style="I")
                continue

            for f in dim.findings:
                pdf.ln(1)
                line(f"**Data:** {f.data}")
                if f.source_url:
                    title = f" - {f.source_title}" if f.source_title else ""
                    line(f"**Source:** {f.source_url}{title}", size=8.5, color=_GREY)
                if f.excerpt:
                    line(f'**Excerpt:** "{f.excerpt}"', size=9, color=(90, 100, 105), style="I", md=True)
                if f.validation:
                    ok = f.validation.status.is_ok
                    line(f"**Validation:** {_validation_text(f.validation)}",
                         color=(_GREEN if ok else _RED))
                    if f.validation.method == "fuzzy" and ok and f.validation.matched_text:
                        line(f"matched on page: \"{f.validation.matched_text}\"",
                             size=8, color=_GREY, style="I", h=4.5)
                if f.support:
                    c = {SupportVerdict.YES: _GREEN, SupportVerdict.PARTIAL: _AMBER,
                         SupportVerdict.NO: _RED}[f.support.verdict]
                    reason = f" - {f.support.reason}" if f.support.reason else ""
                    line(f"**Claim support:** {f.support.verdict.value}{reason}", color=c)
                if f.relevance:
                    line(f"**Source relevance:** {f.relevance.score}/5 - {f.relevance.reason}",
                         size=8.5, color=_GREY)

    return bytes(pdf.output())
