"""Live market data via yfinance.

Provides current price, market cap, and headline valuation multiples so the
model can ground statements about how the market is pricing the company.
Network failures degrade gracefully into an informative error dict rather than
raising, so the tool-use loop can continue.
"""
from __future__ import annotations

from typing import Any


def get_market_snapshot(ticker: str) -> dict[str, Any]:
    """Return a small, LLM-friendly snapshot of market data for `ticker`."""
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed", "ticker": ticker}

    try:
        t = yf.Ticker(ticker)
        info = getattr(t, "info", {}) or {}
        fast = getattr(t, "fast_info", {}) or {}

        def pick(*keys):
            for k in keys:
                v = info.get(k)
                if v is not None:
                    return v
            return None

        price = pick("currentPrice", "regularMarketPrice") or _fast(fast, "last_price")
        snapshot = {
            "ticker": ticker.upper(),
            "name": pick("longName", "shortName"),
            "price": price,
            "currency": pick("currency") or _fast(fast, "currency"),
            "market_cap": pick("marketCap") or _fast(fast, "market_cap"),
            "trailing_pe": pick("trailingPE"),
            "forward_pe": pick("forwardPE"),
            "price_to_sales": pick("priceToSalesTrailing12Months"),
            "profit_margin_pct": _to_pct(pick("profitMargins")),
            "gross_margin_pct": _to_pct(pick("grossMargins")),
            "operating_margin_pct": _to_pct(pick("operatingMargins")),
            "revenue_growth_yoy_pct": _to_pct(pick("revenueGrowth")),
            "fifty_two_week_high": pick("fiftyTwoWeekHigh"),
            "fifty_two_week_low": pick("fiftyTwoWeekLow"),
        }
        # Remove Nones to keep the payload tight.
        clean = {k: v for k, v in snapshot.items() if v is not None}
        if len(clean) <= 1:
            clean["warning"] = "No market data returned; ticker may be invalid or offline."
        return clean
    except Exception as exc:  # pragma: no cover - network dependent
        return {"error": f"market data fetch failed: {exc}", "ticker": ticker}


def _fast(fast, key):
    try:
        return fast[key]
    except Exception:
        return None


def _to_pct(x):
    return round(x * 100, 2) if isinstance(x, (int, float)) else None
