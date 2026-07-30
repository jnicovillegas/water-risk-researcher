"""Command-line entrypoint.

Examples
--------
    waterrisk --input locations.json --output out/report.md --csv --critique
    python -m waterrisk "Plant in Mexicali, Mexico" "Factory in Chandler, Arizona, USA"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import Settings, require_api_key
from .pipeline import Pipeline
from .report import render_csv, render_markdown

DEFAULT_LOCATIONS = [
    "Plant in Mexicali, Mexico",
    "Plant in Monterrey, Mexico",
    "Factory in Chandler, Arizona, USA",
]


def _load_locations(args) -> list[str]:
    if args.locations:
        return args.locations
    if args.input:
        raw = Path(args.input).read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
            raise SystemExit(f"ERROR: {args.input} must be a JSON array of strings.")
        return data
    return DEFAULT_LOCATIONS


def _parse_args(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="waterrisk",
        description="Automated, source-verified water-risk research.",
    )
    p.add_argument("locations", nargs="*", help="Locations to research (overrides --input).")
    p.add_argument("-i", "--input", help="JSON file: array of location strings.")
    p.add_argument("-o", "--output", default="out/report.md", help="Markdown output path.")
    p.add_argument("--csv", action="store_true", help="Also write a consolidated CSV report.")
    p.add_argument("--no-support", action="store_true",
                   help="Disable the claim-support check (does the excerpt back the claim?).")
    p.add_argument("--critique", action="store_true", help="AI self-critique of source relevance (bonus).")
    p.add_argument("--no-cache", action="store_true", help="Disable the on-disk cache.")
    p.add_argument("--model", help="Override the Anthropic model id.")
    p.add_argument("--research-concurrency", type=int, default=4)
    p.add_argument("--verify-concurrency", type=int, default=8)
    p.add_argument("--quiet", action="store_true", help="Do not print the report to stdout.")
    return p.parse_args(argv)


def _emit(location: str, msg: str) -> None:
    label = (location[:24] + "…") if len(location) > 25 else location
    print(f"  [{label:<25}] {msg}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    require_api_key()

    settings = Settings(
        use_cache=not args.no_cache,
        support_check=not args.no_support,
        critique=args.critique,
        research_concurrency=args.research_concurrency,
        verify_concurrency=args.verify_concurrency,
    )
    if args.model:
        settings.model = args.model

    locations = _load_locations(args)
    print(f"Researching {len(locations)} location(s) with model '{settings.model}'…",
          file=sys.stderr)

    pipeline = Pipeline(settings)
    reports = asyncio.run(pipeline.run(locations, on_event=_emit))

    markdown = render_markdown(reports, settings.sources_per_dimension)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    print(f"\nMarkdown report → {out_path}", file=sys.stderr)

    if args.csv:
        csv_path = out_path.with_suffix(".csv")
        csv_path.write_text(render_csv(reports), encoding="utf-8")
        print(f"CSV report → {csv_path}", file=sys.stderr)

    if not args.quiet:
        print("\n" + markdown)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
