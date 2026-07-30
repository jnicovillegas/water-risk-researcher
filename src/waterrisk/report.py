"""Rendering: Markdown (matches the brief's example format) and CSV (bonus)."""

from __future__ import annotations

import csv
import io

from .models import LocationReport, SupportVerdict


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


def render_markdown(reports: list[LocationReport]) -> str:
    total, verified, judged, fully_supported = _summary(reports)
    rate = (verified / total * 100) if total else 0.0
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
            out.append(f"### {dim.dimension.emoji} Dimension: {dim.dimension.label}")
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
        "excerpt", "validation_status", "match_method", "match_score",
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
                v.http_status if v and v.http_status else "",
                f.support.verdict.value if f.support else "",
                f.support.reason if f.support else "",
                f.relevance.score if f.relevance else "",
            ])
    return buf.getvalue()
