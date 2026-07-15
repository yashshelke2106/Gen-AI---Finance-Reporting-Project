"""SEC EDGAR line-item retrieval.

Pulls actual reported financial-statement line items from the SEC's XBRL
`companyfacts` API. These are the source-of-truth numbers the eval harness
checks the model's output against.

SEC fair-access policy requires a descriptive User-Agent with contact info.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import requests

from ..config import settings

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Common us-gaap concept aliases -> our canonical field name. EDGAR filers use
# different tags across periods, so we try several.
_CONCEPT_MAP: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "shareholders_equity": ["StockholdersEquity"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "inventory": ["InventoryNet"],
    "interest_expense": ["InterestExpense"],
    "shares_outstanding": ["CommonStockSharesOutstanding", "dei:EntityCommonStockSharesOutstanding"],
}

_session = requests.Session()


def _headers() -> dict[str, str]:
    return {"User-Agent": settings.edgar_user_agent, "Accept-Encoding": "gzip, deflate"}


def lookup_cik(ticker: str) -> Optional[str]:
    """Resolve a ticker symbol to a zero-padded 10-digit CIK."""
    try:
        r = _session.get(_TICKER_MAP_URL, headers=_headers(), timeout=settings.request_timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None
    ticker = ticker.upper()
    for row in data.values():
        if str(row.get("ticker", "")).upper() == ticker:
            return str(row["cik_str"]).zfill(10)
    return None


def get_filing_financials(
    ticker: str,
    fiscal_year: Optional[int] = None,
    fiscal_period: Optional[str] = None,
) -> dict[str, Any]:
    """Return canonical line items for a company.

    If `fiscal_year`/`fiscal_period` (e.g. 2024 / "Q2") are given, the value
    from the matching XBRL fact is returned; otherwise the most recent value
    for each concept is used. Each item includes the value, unit, form and
    period end so it is fully traceable.
    """
    cik = lookup_cik(ticker)
    if not cik:
        return {"error": f"could not resolve CIK for ticker '{ticker}'", "ticker": ticker}

    try:
        r = _session.get(
            _FACTS_URL.format(cik=cik), headers=_headers(), timeout=settings.request_timeout
        )
        r.raise_for_status()
        facts = r.json()
    except Exception as exc:  # pragma: no cover - network dependent
        return {"error": f"EDGAR fetch failed: {exc}", "ticker": ticker, "cik": cik}

    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    out: dict[str, Any] = {"ticker": ticker.upper(), "cik": cik, "line_items": {}}

    for field, concepts in _CONCEPT_MAP.items():
        picked = None
        for concept in concepts:
            node = us_gaap.get(concept)
            if not node:
                continue
            picked = _select_fact(node, fiscal_year, fiscal_period)
            if picked:
                picked["concept"] = concept
                break
        if picked:
            out["line_items"][field] = picked

    if not out["line_items"]:
        out["warning"] = "No matching us-gaap line items found."
    return out


def _select_fact(
    node: dict, fiscal_year: Optional[int], fiscal_period: Optional[str]
) -> Optional[dict]:
    """Choose the best XBRL fact from a concept node."""
    units = node.get("units", {})
    # Prefer USD, then shares, then whatever unit exists.
    unit_key = next(
        (u for u in ("USD", "shares") if u in units),
        next(iter(units), None),
    )
    if not unit_key:
        return None
    entries = units[unit_key]

    def matches(e: dict) -> bool:
        if fiscal_year is not None and e.get("fy") != fiscal_year:
            return False
        if fiscal_period is not None and str(e.get("fp", "")).upper() != fiscal_period.upper():
            return False
        return True

    candidates = [e for e in entries if e.get("val") is not None and matches(e)]
    if not candidates:
        candidates = [e for e in entries if e.get("val") is not None]
    if not candidates:
        return None

    best = max(candidates, key=lambda e: e.get("end", ""))
    return {
        "value": best.get("val"),
        "unit": unit_key,
        "period_end": best.get("end"),
        "fiscal_year": best.get("fy"),
        "fiscal_period": best.get("fp"),
        "form": best.get("form"),
    }


def line_items_to_financials(line_items: dict) -> dict:
    """Flatten the {field: {value, ...}} structure into {field: value} for ratios."""
    return {k: v.get("value") for k, v in line_items.items() if isinstance(v, dict)}


if __name__ == "__main__":  # simple manual check
    print(json.dumps(get_filing_financials("AAPL"), indent=2)[:2000])
