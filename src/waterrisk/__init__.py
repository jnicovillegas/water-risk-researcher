"""water-risk-researcher — automated, source-verified water-risk research.

Core idea: AI generation and data verification are two layers with different
trust levels. The LLM proposes {data, source, excerpt}; a deterministic layer
re-fetches the live source and proves the excerpt is really there. The model is
never trusted to audit itself.
"""

__version__ = "0.1.0"
