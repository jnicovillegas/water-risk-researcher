"""Command-line entrypoint.

Examples
--------
    waterrisk --input locations.json --format md,csv --relevance
    python -m waterrisk "Plant in Mexicali, Mexico" "Factory in Chandler, Arizona, USA"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .config import Settings, require_api_key
from .pipeline import Pipeline
from .report import render_csv, render_json, render_markdown, render_pdf

FORMATS = ("md", "csv", "json", "pdf")

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
    p.add_argument("-o", "--output", default="out/report",
                   help="Base path for the reports (default: out/report). Each format adds its extension.")
    p.add_argument("--format", default="md",
                   help=f"Comma-separated output formats: {', '.join(FORMATS)} (default: md). E.g. --format md,csv,pdf")
    p.add_argument("--no-support", action="store_true",
                   help="Skip the claim-support check — seal 2 (on by default).")
    p.add_argument("--relevance", action="store_true",
                   help="Add the source-relevance rating — seal 3 (off by default).")
    p.add_argument("--no-cache", action="store_true", help="Force fresh searches instead of reusing saved results.")
    p.add_argument("--model", help="Use a different model id.")
    p.add_argument("--research-concurrency", type=int, default=4)
    p.add_argument("--verify-concurrency", type=int, default=8)
    p.add_argument("--quiet", action="store_true", help="Do not print the report to the screen.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def _parse_formats(raw: str) -> list[str]:
    formats = [f.strip().lower() for f in raw.split(",") if f.strip()]
    invalid = [f for f in formats if f not in FORMATS]
    if invalid:
        raise SystemExit(f"ERROR: unknown format(s) {invalid}. Choose from: {', '.join(FORMATS)}.")
    return formats or ["md"]


def _emit(location: str, msg: str) -> None:
    label = (location[:24] + "…") if len(location) > 25 else location
    print(f"  [{label:<25}] {msg}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    require_api_key()

    formats = _parse_formats(args.format)
    settings = Settings(
        use_cache=not args.no_cache,
        support_check=not args.no_support,
        critique=args.relevance,
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

    # Output base path — strip a known report extension if the user included one.
    base = Path(args.output)
    if base.suffix.lower().lstrip(".") in FORMATS:
        base = base.with_suffix("")
    base.parent.mkdir(parents=True, exist_ok=True)

    writers = {
        "md":   lambda p: p.write_text(markdown, encoding="utf-8"),
        "csv":  lambda p: p.write_text(render_csv(reports), encoding="utf-8"),
        "json": lambda p: p.write_text(render_json(reports), encoding="utf-8"),
        "pdf":  lambda p: p.write_bytes(render_pdf(reports, settings.sources_per_dimension)),
    }
    for fmt in formats:
        path = base.with_suffix(f".{fmt}")
        writers[fmt](path)
        print(f"{fmt.upper()} report → {path}", file=sys.stderr)

    if not args.quiet:
        print("\n" + markdown)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
