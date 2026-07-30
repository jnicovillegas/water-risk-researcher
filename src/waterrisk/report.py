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
_CHIP = (222, 230, 233)   # neutral badge background

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

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(16, 14, 16)
    pdf.add_page()
    RIGHT = pdf.w - pdf.r_margin
    IND = pdf.l_margin + 4

    def block(txt, x, size, color, style="", h=4.5):
        """A wrapped paragraph starting at x, flowing to the right margin."""
        pdf.set_x(x)
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(RIGHT - x, h, _l1(txt), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def badge(txt, bg, fg=(255, 255, 255)):
        pdf.set_font("Helvetica", "B", 7)
        w = pdf.get_string_width(_l1(txt)) + 4
        if pdf.get_x() + w > RIGHT:
            pdf.ln(5.2)
            pdf.set_x(IND)
        x, y = pdf.get_x(), pdf.get_y()
        pdf.set_fill_color(*bg)
        pdf.rect(x, y, w, 4.4, style="F")
        pdf.set_text_color(*fg)
        pdf.set_xy(x, y + 0.55)
        pdf.cell(w, 3.3, _l1(txt), align="C")
        pdf.set_xy(x + w + 1.6, y)

    # ── Header ───────────────────────────────────────────────────────────────
    pdf.set_xy(pdf.l_margin, 13)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*_TEAL)
    pdf.cell(0, 9, "Water Risk Research Report", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # ── Summary box ──────────────────────────────────────────────────────────
    total, verified, judged, fully = _summary(reports)
    dims_total = dims_ok = 0
    for r in reports:
        for dim in r.dimensions:
            if dim.findings:
                dims_total += 1
                if source_counts(dim.findings)[0] >= min_sources:
                    dims_ok += 1
    rate = (verified / total * 100) if total else 0.0
    metrics = [
        ("Locations analysed", str(len(reports))),
        ("Verified data points", f"{verified}/{total}   ({rate:.0f}% source-validated)"),
    ]
    if judged:
        metrics.append(("Fully supported", f"{fully}/{judged}   ({fully / judged * 100:.0f}% of verified)"))
    if dims_total:
        metrics.append(("Multi-source coverage", f"{dims_ok}/{dims_total} dimensions   (>= {min_sources} distinct)"))

    y0 = pdf.get_y()
    box_h = 3.6 + len(metrics) * 4.8
    pdf.set_fill_color(238, 245, 247)
    pdf.rect(pdf.l_margin, y0, RIGHT - pdf.l_margin, box_h, style="F")
    pdf.set_xy(pdf.l_margin + 4, y0 + 2.4)
    for label, val in metrics:
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*_TEAL)
        pdf.cell(48, 4.8, _l1(label))
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*_DARK)
        pdf.cell(0, 4.8, _l1(val), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_x(pdf.l_margin + 4)
    pdf.set_y(y0 + box_h + 3)

    # ── Body ─────────────────────────────────────────────────────────────────
    for r in reports:
        pdf.ln(2.5)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*_TEAL)
        pdf.set_draw_color(*_TEAL)
        pdf.set_line_width(0.4)
        pdf.cell(0, 7, _l1(f"Location: {r.location}"), border="B",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if r.error:
            pdf.ln(1)
            block(f"Research error: {r.error}", pdf.l_margin, 9, _RED, style="I")
            continue

        for dim in r.dimensions:
            src = ""
            if dim.findings:
                nd, nu = source_counts(dim.findings)
                if nd >= min_sources:
                    src = f"    {nd} distinct sources" + (f" / {nu} articles" if nu > nd else "")
                else:
                    src = f"    {nd} distinct source (needs >= {min_sources})"
            pdf.ln(1.5)
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.set_text_color(*_TEAL)
            pdf.cell(0, 5.5, _l1(dim.dimension.label + src),
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if not dim.findings:
                block(f"No data - {dim.note or 'no source found'}", IND, 9, _GREY, style="I")
                continue

            for f in dim.findings:
                pdf.ln(1.8)
                # teal bullet + Data headline
                y = pdf.get_y()
                pdf.set_fill_color(*_TEAL)
                pdf.rect(pdf.l_margin, y + 1.4, 1.7, 1.7, style="F")
                block(f.data, IND, 10, _DARK, style="B", h=4.9)
                if f.source_url:
                    title = f"   -   {f.source_title}" if f.source_title else ""
                    block(f.source_url + title, IND, 7.8, _GREY, h=3.9)
                if f.excerpt:
                    block('"' + f.excerpt + '"', IND, 8.7, (95, 105, 110), style="I", h=4.3)
                v = f.validation
                if v and v.method == "fuzzy" and v.status.is_ok and v.matched_text:
                    block('matched on page: "' + v.matched_text + '"', IND + 2, 7.3, _GREY, style="I", h=3.6)

                # badge row (verdicts at a glance)
                pdf.ln(0.8)
                pdf.set_x(IND)
                if v:
                    if v.status.is_ok:
                        method = "exact" if v.method == "exact" else f"fuzzy {v.score:.0f}%"
                        badge(f"MATCH  {method}", _GREEN)
                    else:
                        badge("FAILED VALIDATION", _RED)
                if f.support:
                    c = {SupportVerdict.YES: _GREEN, SupportVerdict.PARTIAL: _AMBER,
                         SupportVerdict.NO: _RED}[f.support.verdict]
                    badge(f"SUPPORT  {f.support.verdict.value}", c)
                if f.relevance:
                    badge(f"SOURCE  {f.relevance.score}/5", _CHIP, fg=_DARK)
                pdf.ln(5.6)

                # detail lines (content that the badges summarize)
                if v and not v.status.is_ok:
                    reason = _validation_text(v).replace("FAILED VALIDATION - ", "")
                    block(reason, IND, 7.8, _RED, style="I", h=3.8)
                if f.support and f.support.reason:
                    block(f.support.reason, IND, 8, _GREY, style="I", h=4.0)
                if f.relevance and f.relevance.reason:
                    block("Source: " + f.relevance.reason, IND, 7.6, _GREY, h=3.7)

    return bytes(pdf.output())
