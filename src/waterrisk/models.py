"""Typed data model for the whole pipeline.

Everything flows as pydantic models so each stage has a validated contract and
rendering (Markdown/CSV/JSON) is trivial and consistent.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Dimension(str, Enum):
    WATER_STRESS = "water_stress"
    INCIDENTS = "incidents"
    REGULATIONS = "regulations"

    @property
    def label(self) -> str:
        return {
            Dimension.WATER_STRESS: "Water Stress",
            Dimension.INCIDENTS: "Incidents",
            Dimension.REGULATIONS: "Regulations",
        }[self]

    @property
    def emoji(self) -> str:
        return {
            Dimension.WATER_STRESS: "\U0001F4A7",  # 💧
            Dimension.INCIDENTS: "⚠️",     # ⚠️
            Dimension.REGULATIONS: "\U0001F4CB",     # 📋
        }[self]

    @property
    def prompt_hint(self) -> str:
        return {
            Dimension.WATER_STRESS: "Level of water scarcity or physical water risk in the area (e.g. WRI Aqueduct baseline water stress score).",
            Dimension.INCIDENTS: "Reports of strikes, protests, or previous water-related conflicts or crises in the area.",
            Dimension.REGULATIONS: "Relevant local/regional regulations on industrial use of water.",
        }[self]


class ValidationStatus(str, Enum):
    MATCH = "match"                       # excerpt provably found on the live page
    EXCERPT_NOT_FOUND = "excerpt_not_found"
    UNREACHABLE = "unreachable"           # DNS/timeout/HTTP error
    BLOCKED = "blocked"                   # bot protection / anti-scraping wall
    NO_SOURCE = "no_source"               # model returned no usable URL

    @property
    def is_ok(self) -> bool:
        return self is ValidationStatus.MATCH


class ValidationResult(BaseModel):
    """Output of the deterministic verifier for a single finding."""

    status: ValidationStatus
    method: str = "none"          # "exact" | "fuzzy" | "none"
    score: float = 0.0            # match confidence 0-100
    detail: str = ""             # human-readable reason, esp. on failure
    http_status: Optional[int] = None

    def label(self) -> str:
        """Short label for the Markdown report."""
        if self.status is ValidationStatus.MATCH:
            method = "exact" if self.method == "exact" else f"fuzzy {self.score:.0f}%"
            return f"✅ MATCH FOUND ({method})"
        reasons = {
            ValidationStatus.EXCERPT_NOT_FOUND: "excerpt not found in source content",
            ValidationStatus.UNREACHABLE: f"source unreachable{f' (HTTP {self.http_status})' if self.http_status else ''}",
            ValidationStatus.BLOCKED: "source blocked by bot protection",
            ValidationStatus.NO_SOURCE: "no source URL provided",
        }
        return f"❌ FAILED VALIDATION: {reasons.get(self.status, self.status.value)}"


class Relevance(BaseModel):
    """Optional AI self-critique of a source's authority/relevance (bonus)."""

    score: int = Field(ge=0, le=5)
    reason: str = ""


class Finding(BaseModel):
    """A single claim about a location+dimension, with its source and proof."""

    dimension: Dimension
    data: str
    source_url: str = ""
    source_title: str = ""
    excerpt: str = ""
    validation: Optional[ValidationResult] = None
    relevance: Optional[Relevance] = None


class DimensionResult(BaseModel):
    dimension: Dimension
    findings: list[Finding] = Field(default_factory=list)
    note: str = ""   # e.g. "no reliable source found"


class LocationReport(BaseModel):
    location: str
    dimensions: list[DimensionResult] = Field(default_factory=list)
    error: str = ""   # set if the whole location failed (e.g. research API error)

    def all_findings(self) -> list[Finding]:
        return [f for d in self.dimensions for f in d.findings]
