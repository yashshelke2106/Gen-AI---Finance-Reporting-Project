"""Tool schemas (Anthropic tool-use format) and a dispatcher.

`TOOL_SCHEMAS` is passed to the Anthropic API as `tools`. When the model emits
a `tool_use` block, `dispatch_tool` runs the matching Python function and the
result is returned to the model as a `tool_result`.
"""
from __future__ import annotations

from typing import Any

from . import edgar, market_data, ratios

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_filing_financials",
        "description": (
            "Fetch actual reported financial-statement line items (revenue, net "
            "income, assets, etc.) for a company from the SEC EDGAR XBRL API. Use "
            "this to get ground-truth numbers instead of reading them off the "
            "filing text. Returns each item with its value, unit, form and period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. 'AAPL'"},
                "fiscal_year": {
                    "type": "integer",
                    "description": "Optional fiscal year to match, e.g. 2024",
                },
                "fiscal_period": {
                    "type": "string",
                    "description": "Optional fiscal period: 'Q1','Q2','Q3','FY'",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "compute_ratios",
        "description": (
            "Compute standard financial ratios (margins, ROE, ROA, current ratio, "
            "debt-to-equity, YoY growth, EPS, P/E) deterministically from raw line "
            "items. ALWAYS use this instead of computing ratios yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "financials": {
                    "type": "object",
                    "description": (
                        "Raw line items in a single currency unit. Keys may include: "
                        "revenue, cost_of_revenue, gross_profit, operating_income, "
                        "net_income, total_assets, total_liabilities, shareholders_equity, "
                        "current_assets, current_liabilities, inventory, ebit, "
                        "interest_expense, prior_revenue, prior_net_income, "
                        "shares_outstanding, price."
                    ),
                    "additionalProperties": {"type": "number"},
                }
            },
            "required": ["financials"],
        },
    },
    {
        "name": "get_market_snapshot",
        "description": (
            "Fetch a live market snapshot (price, market cap, trailing/forward P/E, "
            "margins, 52-week range) via yfinance. Use for how the market is pricing "
            "the company, not for filing line items."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. 'MSFT'"}
            },
            "required": ["ticker"],
        },
    },
]


def dispatch_tool(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool by name and return a JSON-serializable result."""
    if name == "get_filing_financials":
        return edgar.get_filing_financials(
            ticker=tool_input["ticker"],
            fiscal_year=tool_input.get("fiscal_year"),
            fiscal_period=tool_input.get("fiscal_period"),
        )
    if name == "compute_ratios":
        return ratios.compute_ratios(tool_input.get("financials", {}))
    if name == "get_market_snapshot":
        return market_data.get_market_snapshot(tool_input["ticker"])
    return {"error": f"unknown tool '{name}'"}
