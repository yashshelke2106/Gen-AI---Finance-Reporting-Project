"""Pydantic schemas for the structured analyst brief.

The whole point of the project is that the model must return output that
conforms to these schemas. Anything numeric that the model asserts should be
traceable to a tool call (see `sources`), which the eval harness checks.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Direction(str, Enum):
    up = "up"
    down = "down"
    flat = "flat"


class Sentiment(str, Enum):
    more_positive = "more_positive"
    more_cautious = "more_cautious"
    unchanged = "unchanged"
    mixed = "mixed"


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Metric(BaseModel):
    """A single quantified metric with provenance."""

    name: str = Field(..., description="e.g. 'Total revenue', 'Gross margin'")
    value: float = Field(..., description="Numeric value in the stated unit")
    unit: str = Field(..., description="e.g. 'USD millions', '%', 'x'")
    period: str = Field(..., description="e.g. 'Q2 FY2024'")
    yoy_change_pct: Optional[float] = Field(
        None, description="Year-over-year change in percent, if computed"
    )
    source: str = Field(
        ...,
        description="Where this number came from: a tool name (e.g. 'edgar', "
        "'ratios', 'yfinance') or 'filing_text' if read from the document.",
    )


class RevenueDriver(BaseModel):
    driver: str = Field(..., description="Segment, product, or region")
    direction: Direction
    commentary: str = Field(..., description="One or two sentences of explanation")
    supporting_metric: Optional[Metric] = None


class MarginChange(BaseModel):
    margin_type: str = Field(..., description="e.g. 'Gross margin', 'Operating margin'")
    current: Optional[float] = Field(None, description="Current period value, %")
    prior: Optional[float] = Field(None, description="Prior comparable period value, %")
    delta_bps: Optional[float] = Field(
        None, description="Change in basis points (current - prior) * 100"
    )
    driver_commentary: str


class RiskFlag(BaseModel):
    risk: str
    severity: Severity
    rationale: str
    quote: Optional[str] = Field(
        None, description="Short supporting quote from the filing/transcript"
    )


class SentimentShift(BaseModel):
    assessment: Sentiment
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: list[str] = Field(
        default_factory=list,
        description="Concrete phrases/behaviors driving the assessment",
    )


class AnalystBrief(BaseModel):
    """The full structured output returned to the user."""

    company: str
    ticker: Optional[str] = None
    period: str = Field(..., description="Reporting period the brief covers")

    headline: str = Field(..., description="One-sentence takeaway")

    key_metrics: list[Metric] = Field(default_factory=list)
    revenue_drivers: list[RevenueDriver] = Field(default_factory=list)
    margin_changes: list[MarginChange] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    sentiment_shift: Optional[SentimentShift] = None

    plain_english_summary: str = Field(
        ...,
        description="A jargon-free summary a non-finance stakeholder can act on.",
    )

    # Populated by the engine, not the model: every value the tools actually
    # returned, so the eval harness can verify the model didn't drift.
    tool_evidence: dict = Field(default_factory=dict)

    def to_markdown(self) -> str:
        """Render the brief as a readable markdown memo."""
        lines: list[str] = []
        tkr = f" ({self.ticker})" if self.ticker else ""
        lines.append(f"# Analyst Brief — {self.company}{tkr}")
        lines.append(f"**Period:** {self.period}")
        lines.append("")
        lines.append(f"> {self.headline}")
        lines.append("")

        if self.key_metrics:
            lines.append("## Key Metrics")
            lines.append("")
            lines.append("| Metric | Value | Period | YoY | Source |")
            lines.append("|---|---|---|---|---|")
            for m in self.key_metrics:
                yoy = f"{m.yoy_change_pct:+.1f}%" if m.yoy_change_pct is not None else "—"
                lines.append(
                    f"| {m.name} | {m.value:,.2f} {m.unit} | {m.period} | {yoy} | {m.source} |"
                )
            lines.append("")

        if self.revenue_drivers:
            lines.append("## Revenue Drivers")
            lines.append("")
            for d in self.revenue_drivers:
                arrow = {"up": "▲", "down": "▼", "flat": "▬"}[d.direction.value]
                lines.append(f"- {arrow} **{d.driver}** — {d.commentary}")
            lines.append("")

        if self.margin_changes:
            lines.append("## Margin Changes")
            lines.append("")
            for mc in self.margin_changes:
                delta = f"{mc.delta_bps:+.0f} bps" if mc.delta_bps is not None else "—"
                cur = f"{mc.current:.1f}%" if mc.current is not None else "—"
                lines.append(f"- **{mc.margin_type}:** {cur} ({delta}). {mc.driver_commentary}")
            lines.append("")

        if self.risk_flags:
            lines.append("## Risk Flags")
            lines.append("")
            for r in self.risk_flags:
                lines.append(f"- **[{r.severity.value.upper()}] {r.risk}** — {r.rationale}")
                if r.quote:
                    lines.append(f"  > _{r.quote}_")
            lines.append("")

        if self.sentiment_shift:
            s = self.sentiment_shift
            lines.append("## Management Tone / Sentiment Shift")
            lines.append("")
            lines.append(
                f"**{s.assessment.value.replace('_', ' ').title()}** "
                f"(confidence {s.confidence:.0%})"
            )
            for e in s.evidence:
                lines.append(f"- {e}")
            lines.append("")

        lines.append("## Plain-English Summary")
        lines.append("")
        lines.append(self.plain_english_summary)
        lines.append("")
        return "\n".join(lines)
