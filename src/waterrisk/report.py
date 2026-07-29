"""Rendering: Markdown (matches the brief's example format) and CSV (bonus)."""

from __future__ import annotations

import csv
import io

from .models import LocationReport, ValidationStatus


def _summary(reports: list[LocationReport]) -> tuple[int, int]:
    total = ok = 0
    for r in reports:
        for f in r.all_findings():
            total += 1
            if f.validation and f.validation.status.is_ok:
                ok += 1
    return ok, total


def render_markdown(reports: list[LocationReport]) -> str:
    ok, total = _summary(reports)
    rate = (ok / total * 100) if total else 0.0
    out: list[str] = [
        "# Water Risk Research Report",
        "",
        f"**Locations analysed:** {len(reports)}  ",
        f"**Verified data points:** {ok}/{total} ({rate:.0f}% source-validated)",
        "",
        "> Every data point below was independently re-fetched from its source and "
        "its excerpt checked against the live page. `❌ FAILED VALIDATION` means the "
        "claim could not be proven — it is surfaced, never hidden.",
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
        "http_status", "relevance_score",
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
                f.relevance.score if f.relevance else "",
            ])
    return buf.getvalue()
