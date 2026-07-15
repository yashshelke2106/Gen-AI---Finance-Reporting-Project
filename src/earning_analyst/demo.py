"""Offline demo scaffolding.

Provides a `MockLLM` scripted to (1) compute ratios from the bundled sample
financials using the real `compute_ratios` tool (pure, offline) and (2) emit a
complete, schema-valid analyst brief. This lets `--mock` and the eval harness
run with no API key and no network.
"""
from __future__ import annotations

from typing import Any

from .llm import MockLLM

# Numbers mirror data/samples/sample_facts.json (Acme Corp, illustrative).
SAMPLE_FINANCIALS: dict[str, float] = {
    "revenue": 1250.0,
    "cost_of_revenue": 700.0,
    "operating_income": 300.0,
    "net_income": 210.0,
    "total_assets": 4200.0,
    "total_liabilities": 1800.0,
    "shareholders_equity": 2400.0,
    "current_assets": 1500.0,
    "current_liabilities": 600.0,
    "inventory": 250.0,
    "prior_revenue": 1100.0,
    "prior_net_income": 180.0,
    "shares_outstanding": 100.0,
    "price": 84.0,
}


def build_mock_llm(company: str, ticker: str | None, period: str) -> MockLLM:
    """Return a MockLLM that computes ratios then emits a brief."""
    brief_input = _sample_brief(company, ticker, period)
    script: list[list[dict[str, Any]]] = [
        # Turn 1: ask the ratios tool to compute everything from raw line items.
        [
            {"type": "text", "text": "Computing ratios from reported line items."},
            {
                "type": "tool_use",
                "id": "toolu_ratios_1",
                "name": "compute_ratios",
                "input": {"financials": SAMPLE_FINANCIALS},
            },
        ],
        # Turn 2: emit the completed brief.
        [
            {"type": "text", "text": "Emitting the analyst brief."},
            {
                "type": "tool_use",
                "id": "toolu_emit_1",
                "name": "emit_analyst_brief",
                "input": brief_input,
            },
        ],
    ]
    return MockLLM(script)


def _sample_brief(company: str, ticker: str | None, period: str) -> dict[str, Any]:
    return {
        "company": company,
        "ticker": ticker,
        "period": period,
        "headline": (
            f"{company} grew revenue 13.6% YoY to $1.25B with margin expansion, "
            "though customer concentration remains a watch item."
        ),
        "key_metrics": [
            {
                "name": "Total revenue",
                "value": 1250.0,
                "unit": "USD millions",
                "period": period,
                "yoy_change_pct": 13.64,
                "source": "ratios",
            },
            {
                "name": "Gross margin",
                "value": 44.0,
                "unit": "%",
                "period": period,
                "yoy_change_pct": None,
                "source": "ratios",
            },
            {
                "name": "Net margin",
                "value": 16.8,
                "unit": "%",
                "period": period,
                "yoy_change_pct": None,
                "source": "ratios",
            },
            {
                "name": "Return on equity",
                "value": 8.75,
                "unit": "%",
                "period": period,
                "yoy_change_pct": None,
                "source": "ratios",
            },
        ],
        "revenue_drivers": [
            {
                "driver": "Subscription segment",
                "direction": "up",
                "commentary": "Recurring revenue expanded on net new logos and seat expansion.",
                "supporting_metric": {
                    "name": "Revenue YoY",
                    "value": 13.64,
                    "unit": "%",
                    "period": period,
                    "yoy_change_pct": 13.64,
                    "source": "ratios",
                },
            },
            {
                "driver": "Professional services",
                "direction": "flat",
                "commentary": "Services revenue was roughly stable as delivery capacity was held constant.",
                "supporting_metric": None,
            },
        ],
        "margin_changes": [
            {
                "margin_type": "Gross margin",
                "current": 44.0,
                "prior": 41.0,
                "delta_bps": 300.0,
                "driver_commentary": "Cloud cost optimization and pricing lifted gross margin ~300 bps.",
            },
            {
                "margin_type": "Operating margin",
                "current": 24.0,
                "prior": 22.0,
                "delta_bps": 200.0,
                "driver_commentary": "Operating leverage as revenue outgrew opex.",
            },
        ],
        "risk_flags": [
            {
                "risk": "Customer concentration",
                "severity": "medium",
                "rationale": "Top three customers represent a large share of revenue, creating renewal risk.",
                "quote": "our three largest customers accounted for a significant portion of revenue",
            },
            {
                "risk": "FX exposure",
                "severity": "low",
                "rationale": "Growing international mix increases sensitivity to currency moves.",
                "quote": None,
            },
        ],
        "sentiment_shift": {
            "assessment": "more_positive",
            "confidence": 0.6,
            "evidence": [
                "Management raised full-year guidance versus the prior call.",
                "More confident language around pipeline and win rates.",
            ],
        },
        "plain_english_summary": (
            f"{company} had a strong quarter. It sold about 14% more than the same "
            "period last year, and it kept more of each dollar as profit because its "
            "costs grew more slowly than sales. Leadership sounded more upbeat than "
            "last quarter and nudged up expectations for the rest of the year. The "
            "main thing to keep an eye on is that a few big customers make up a large "
            "chunk of sales, so losing one would hurt. Overall, the business is "
            "growing and becoming more profitable."
        ),
    }
