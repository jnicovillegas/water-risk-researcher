"""Central configuration. All tunables live here so behaviour is easy to reason
about and to defend in a design review."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Default model. Overridable via env in case the account maps a different id.
DEFAULT_MODEL = os.getenv("WATERRISK_MODEL", "claude-sonnet-5")

# A realistic desktop UA. Many sites 403 the default httpx/python UA.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


@dataclass
class Settings:
    """Runtime settings for a single research run."""

    model: str = DEFAULT_MODEL

    # --- Research (generation) ---
    max_tokens: int = 24000           # output budget: must cover the model's thinking +
                                      # web-search steps + the final JSON. Too low and the
                                      # response is truncated before the JSON is written.
    max_search_uses: int = 5          # cap web_search calls per location (cost control)
    sources_per_dimension: int = 2    # brief requires >= 2 sources per item
    research_concurrency: int = 4     # locations processed simultaneously
    research_retries: int = 2         # retry the (long) research call on transient failures
    research_timeout: float = 600.0   # generous ceiling for the streamed research call

    # --- Verification ---
    verify_concurrency: int = 8       # simultaneous URL fetches
    fuzzy_threshold: float = 88.0     # rapidfuzz partial_ratio cutoff for a fuzzy MATCH
    min_excerpt_chars: int = 25       # shorter excerpts require an exact match (fuzzy too noisy)
    max_page_chars: int = 300_000     # cap page text fed to the matcher

    # --- Fetching ---
    request_timeout: float = 20.0
    max_retries: int = 2
    user_agent: str = DEFAULT_USER_AGENT

    # --- Caching ---
    use_cache: bool = True
    cache_dir: str = ".cache"

    # --- Optional stages ---
    critique: bool = False            # AI self-critique of source relevance (bonus)


def require_api_key() -> str:
    """Return the Anthropic API key or raise a clear, actionable error."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "Create a .env file (see .env.example) or export the variable:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "Get a key at https://console.anthropic.com (separate from a Claude.ai plan)."
        )
    return key
