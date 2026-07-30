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
convincing quote — all at once. So this tool never trusts the model. It splits the
work so that generation (which can lie) is always checked by verification (trusted):

```
                 ┌─────────────────────────────────────────────┐
   locations ──▶ │  1. GENERATION  (can hallucinate)           │
                 │  LLM + web search → {data, url, excerpt}     │
                 └───────────────────────┬─────────────────────┘
                                         │  proposals
                 ┌───────────────────────▼─────────────────────┐
                 │  2. VERIFICATION  (trusted)                  │
                 │  a. does the excerpt exist?   (no AI)        │
                 │  b. does it back the claim?   (AI judge)     │
                 └───────────────────────┬─────────────────────┘
                                         │  validated findings
                 ┌───────────────────────▼─────────────────────┐
                 │  3. REPORT   md/csv/json/pdf, failures shown │
                 └─────────────────────────────────────────────┘
```

**Verification asks two separate questions.** *Does the excerpt exist?* — a
deterministic, no-AI string match against the live page; the model cannot make text
appear on a page it doesn't control, so a survived check is real evidence.
*Does the excerpt back the claim?* — a separate, closed-book judge (given only the
claim and its verified excerpt) rules `YES / PARTIAL / NO`, catching claims that
overreach their source. A third, optional pass (`--relevance`) rates each source's
authority. Every failure is surfaced — `❌ FAILED VALIDATION` or a `NO` — never hidden.

---

## Quick start

> 📄 Prefer a step-by-step printable guide? See **[`user-guide.pdf`](user-guide.pdf)** —
> install, configure, run, and read the results, for any user.

Requires Python 3.9+ and an **Anthropic API key** (from
[console.anthropic.com](https://console.anthropic.com) — a developer key, separate
from any chat subscription; a run costs a few cents). **The key must be Anthropic's**
— the tool uses Anthropic's server-side web search, so a key from another provider
won't work. Any Claude model works via `--model`; the default is **Claude Sonnet 5**,
which we recommend: it's economical and more than enough for this use case.

```bash
# 1. install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. configure your key
cp .env.example .env      # then edit .env and paste your ANTHROPIC_API_KEY

# 3. run on the example locations, in several formats
waterrisk --input locations.example.json --format md,csv,pdf
```

Or pass locations directly:

```bash
waterrisk "Plant in Mexicali, Mexico" "Factory in Chandler, Arizona, USA"
```

The Markdown report prints to the console; every requested `--format` is written
to `<output>.<ext>` (default base `out/report`).

### Options

| Flag | Description |
|------|-------------|
| `-i, --input FILE` | JSON file with an array of location strings |
| `-o, --output PATH` | Base path for the reports (default `out/report`) |
| `--format LIST` | Output formats: `md`, `csv`, `json`, `pdf` (default `md`). E.g. `--format md,csv,pdf` |
| `--no-support` | Skip the claim-support check — seal ② (on by default) |
| `--relevance` | Add the source-relevance rating — seal ③ (off by default) |
| `--no-cache` | Force fresh searches instead of reusing saved results |
| `--model ID` | Use a different model id |
| `--version` | Show the version |
| `--research-concurrency N` / `--verify-concurrency N` | Tune fan-out |

---

## Output format

```markdown
## 📍 Location: Mexicali, Mexico

### 💧 Dimension: Water Stress  ·  Sources: 3 distinct
- **Data:** Mexicali faces extremely high baseline water stress.
  - **Source:** https://www.wri.org/applications/aqueduct/... — WRI Aqueduct
  - **Excerpt:** “...Mexicali faces extremely high baseline water stress...”
  - **Validation:** ✅ MATCH FOUND (fuzzy 96%)
    - _matched on page: “...mexicali faces extremely high baseline water stress...”_
  - **Claim support:** ✅ YES — the excerpt directly supports the claim.
  - **Source relevance:** 5/5 — WRI Aqueduct is the authoritative source.

### ⚠️ Dimension: Incidents  ·  Sources: 2 distinct
- **Data:** Residents protested a brewery plant over its water use.
  - **Source:** https://www.example-news.com/...
  - **Excerpt:** “Residents of Mexicali protested against...”
  - **Validation:** ❌ FAILED VALIDATION: excerpt not found in source content
```

`Claim support` and `Source relevance` (the latter only with `--relevance`) appear
under each verified finding. `matched on page` is shown for fuzzy matches.

---

## How it addresses the evaluation criteria

**Architecture.** Three isolated layers (research / verify / report) with typed
pydantic contracts between them. The search engine sits behind a single class
(`research.py`) so it can be swapped for Tavily, Serper or Brave without touching
verification. The LLM's `web_search` is a server-side tool: one API call performs
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
whitespace/encoding noise without letting false positives through. On top of that,
a closed-book claim-support judge checks that the excerpt actually *backs* the claim
(not just that it exists), and a deterministic multi-source check requires ≥2 distinct
source domains per dimension. This logic is unit-tested (`tests/`) with no network.

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
- ✅ **Consolidated reports** in `csv`, `json`, and `pdf` (`--format`), alongside Markdown.
- ✅ **AI self-critique** of source relevance (`--relevance`) — a separate,
  web-less LLM pass scoring each verified source 0–5 for authority/fit.
  Deliberately distinct from verification: a quote can be *real* yet come from a
  *weak* source.

---

## Testing

```bash
pip install -e ".[dev]"
pytest
```

The tests pin the deterministic logic — excerpt matching (exact, fuzzy, hallucination
rejection), the multi-source check, and every output renderer (md/csv/json/pdf) —
with no network calls.

---

## Known limitations & next steps

- **JavaScript-rendered pages**: text is extracted from raw HTML, so
  content injected by client-side JS may be missed and flagged as
  `excerpt_not_found`. Escalation path: a Playwright-based fetcher behind the same
  `Fetcher` interface, used selectively when the static fetch looks empty.
- **Aggressive anti-bot walls** (some news sites) will return `blocked`; a
  headless browser or a paid scraping API would recover a fraction of these.
- **Scanned / image-only PDFs** have no text layer, so they can't be verified
  without OCR (text-based PDFs are read and verified). Sites pinned to obsolete
  TLS versions may fail the fetch with an SSL error.
- **Excerpt selection** depends on the model quoting verbatim; when it
  paraphrases, verification correctly fails — which is the intended, honest
  behaviour rather than a bug to paper over.

---

## Project layout

```
src/waterrisk/
├── cli.py         # argument parsing, entrypoint
├── pipeline.py    # async orchestration (research → verify → support → relevance)
├── research.py    # generation: LLM + web search → structured findings
├── verify.py      # deterministic excerpt verification — seal 1 (the core)
├── support.py     # closed-book claim-support judge — seal 2
├── critique.py    # optional AI source-relevance rating — seal 3
├── sources.py     # deterministic multi-source check (distinct domains)
├── fetch.py       # robust async fetching (HTML + PDF) + block detection
├── cache.py       # on-disk cache (research responses + page bodies)
├── report.py      # Markdown / CSV / JSON / PDF rendering
├── models.py      # typed pydantic contracts
└── config.py      # all tunables in one place
tests/            # test_verify.py · test_sources.py · test_report.py
```
