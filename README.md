# Water Risk Researcher

A CLI that automates water-risk research across multiple locations and — the part
that matters — **proves that every data point is faithfully supported by its
source**. For each location it investigates three dimensions (water stress,
incidents/conflicts, regulations), gathers findings from multiple web sources,
and then independently re-fetches each source to verify the quoted excerpt
actually exists on the page.

> Built for the Waterplan FDE practical case. Not aiming for absolute perfection —
> aiming for a clear, defensible design that treats data traceability as the
> first-class requirement.

---

## The core idea: generation and verification are different trust levels

An LLM can hallucinate a plausible statistic, a real-looking URL, and a
convincing quote — all at once. So this tool never trusts the model to be
correct. It splits the work into two layers:

```
                 ┌─────────────────────────────────────────────┐
   locations ──▶ │  1. GENERATION  (can hallucinate)           │
                 │  Claude + web_search → {data, url, excerpt}  │
                 └───────────────────────┬─────────────────────┘
                                         │  proposals
                 ┌───────────────────────▼─────────────────────┐
                 │  2. VERIFICATION  (deterministic, trusted)   │
                 │  re-fetch the live URL → extract text →      │
                 │  prove the excerpt is really there           │
                 └───────────────────────┬─────────────────────┘
                                         │  validated findings
                 ┌───────────────────────▼─────────────────────┐
                 │  3. REPORT   Markdown + CSV, failures shown  │
                 └─────────────────────────────────────────────┘
```

The verifier uses **no AI**. It downloads the page Claude cited and checks the
excerpt with exact + fuzzy string matching. The model cannot make text appear on
a page it doesn't control, so a survived check is real evidence — not a second
opinion from the same fallible source. Failures are surfaced as
`❌ FAILED VALIDATION`, never hidden.

---

## Quick start

Requires Python 3.10+ and an Anthropic API key (from
[console.anthropic.com](https://console.anthropic.com) — separate from a Claude.ai
subscription; a run costs a few cents).

```bash
# 1. install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. configure your key
cp .env.example .env      # then edit .env and paste your ANTHROPIC_API_KEY

# 3. run on the example locations
waterrisk --input locations.example.json --output out/report.md --csv
```

Or pass locations directly:

```bash
waterrisk "Plant in Mexicali, Mexico" "Factory in Chandler, Arizona, USA"
```

The Markdown report prints to the console and is written to `--output`. With
`--csv` a consolidated `out/report.csv` is written too.

### Options

| Flag | Description |
|------|-------------|
| `-i, --input FILE` | JSON file with an array of location strings |
| `-o, --output PATH` | Markdown output path (default `out/report.md`) |
| `--csv` | Also write a consolidated CSV report (bonus) |
| `--critique` | AI self-critique scoring source relevance 0–5 (bonus) |
| `--no-cache` | Disable the on-disk cache |
| `--model ID` | Override the Anthropic model id |
| `--research-concurrency N` / `--verify-concurrency N` | Tune fan-out |

---

## Output format

```markdown
## 📍 Location: Mexicali, Mexico

### 💧 Dimension: Water Stress
- **Data:** Extremely High baseline water stress (score 4.8/5)
  - **Source:** https://www.wri.org/applications/aqueduct/... — WRI Aqueduct
  - **Excerpt:** “...Mexicali faces extremely high baseline water stress...”
  - **Validation:** ✅ MATCH FOUND (fuzzy 96%)

### ⚠️ Dimension: Incidents
- **Data:** Protests in 2018 over a brewery plant.
  - **Source:** https://www.example-news.com/...
  - **Excerpt:** “Residents of Mexicali protested against...”
  - **Validation:** ❌ FAILED VALIDATION: excerpt not found in source content
```

---

## How it addresses the evaluation criteria

**Architecture.** Three isolated layers (research / verify / report) with typed
pydantic contracts between them. The search engine sits behind a single class
(`research.py`) so it can be swapped for Tavily, Serper or Brave without touching
verification. Claude's `web_search` is a server-side tool: one API call performs
the whole grounded search loop, keeping the client simple.

**Robustness (dynamic content / bot blocks).** Fetching uses a realistic
User-Agent, redirect following, timeouts, and linear-backoff retries. It
distinguishes *unreachable* (DNS/timeout/5xx) from *blocked* (403/429 or a
Cloudflare/CAPTCHA interstitial detected in the body) and flags them differently.
JS-only pages are a known limitation — see below.

**Data integrity (anti-hallucination).** Two independent guards: (1) the model
works from real retrieved search content, not parametric memory, and is told it
cannot invent sources; (2) every excerpt is re-checked, character by character,
against the live page by a deterministic matcher. Exact match first, then a
length- and threshold-guarded fuzzy match (`rapidfuzz.partial_ratio`) to absorb
whitespace/encoding noise without letting false positives through. This logic has
unit tests (`tests/test_verify.py`) that run with no network.

**Scalability (1,000 locations).** See the next section.

**Failure handling.** Nothing fails silently. Every finding ends in one explicit
state — `match`, `excerpt_not_found`, `unreachable`, `blocked`, or `no_source` —
and a per-location research error is captured without aborting the run. A missing
source for a dimension is reported as such, never back-filled.

---

## Scaling to 1,000 locations

The architecture is already the scalable one; the difference at 1,000 is
configuration and a few operational additions:

- **Bounded async concurrency** at every stage (`asyncio.Semaphore`) — research
  and verification already run concurrently, tunable via CLI flags.
- **Caching** (`.cache/`) keyed by location (research) and by URL (page bodies).
  At scale, sources repeat heavily — the same WRI Aqueduct page, the same
  regulation — so the cache hit-rate climbs and both cost and latency drop. This
  is also the "avoid duplicate searches" bonus.
- **Per-domain rate limiting + politeness** (respect `robots.txt`, throttle by
  host) would be the next addition to avoid hammering a single source.
- **Checkpointing / resumability**: persist each `LocationReport` as it completes
  (the cache already makes completed work free to replay) so a crash at #700
  resumes rather than restarts.
- **Queue/worker split**: for true scale, move locations onto a work queue with
  idempotent workers; the pipeline function is already the worker body.
- **Cost control**: `max_search_uses` caps searches per location; the model id is
  configurable to trade accuracy for cost.

---

## Bonus features

- ✅ **Caching** to avoid duplicate searches/fetches (`--no-cache` to disable).
- ✅ **Consolidated CSV** report (`--csv`).
- ✅ **AI self-critique** of source relevance (`--critique`) — a separate,
  web-less Claude pass scoring each verified source 0–5 for authority/fit.
  Deliberately distinct from verification: a quote can be *real* yet come from a
  *weak* source.

---

## Testing

```bash
pip install -e ".[dev]"
pytest
```

The tests pin the matching behaviour (exact, fuzzy, hallucination rejection,
short-excerpt safety, HTML text extraction) with no network calls.

---

## Known limitations & next steps

- **JavaScript-rendered pages**: text is extracted from raw HTML, so
  content injected by client-side JS may be missed and flagged as
  `excerpt_not_found`. Escalation path: a Playwright-based fetcher behind the same
  `Fetcher` interface, used selectively when the static fetch looks empty.
- **Aggressive anti-bot walls** (some news sites) will return `blocked`; a
  headless browser or a paid scraping API would recover a fraction of these.
- **Excerpt selection** depends on the model quoting verbatim; when it
  paraphrases, verification correctly fails — which is the intended, honest
  behaviour rather than a bug to paper over.

---

## Project layout

```
src/waterrisk/
├── cli.py         # argument parsing, entrypoint
├── pipeline.py    # async orchestration (research → verify → critique)
├── research.py    # generation: Claude + web_search → structured findings
├── verify.py      # deterministic excerpt verification (the core)
├── fetch.py       # robust async fetching + text extraction + block detection
├── critique.py    # optional AI self-critique of source relevance
├── cache.py       # on-disk cache (research responses + page bodies)
├── report.py      # Markdown + CSV rendering
├── models.py      # typed pydantic contracts
└── config.py      # all tunables in one place
tests/test_verify.py
```
