"""Deterministic financial-ratio computation.

These are plain Python. The LLM is *not* allowed to compute ratios in its head;
it calls `compute_ratios` and receives exact numbers. This is what stops the
model from hallucinating margins and growth rates.
"""
from __future__ import annotations

from typing import Optional


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def pct(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """Return numerator/denominator as a percentage, rounded to 2 dp."""
    r = _safe_div(numerator, denominator)
    return round(r * 100, 2) if r is not None else None


def yoy_growth(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    """Year-over-year growth in percent."""
    if current is None or prior in (None, 0):
        return None
    return round((current - prior) / abs(prior) * 100, 2)


def delta_bps(current_pct: Optional[float], prior_pct: Optional[float]) -> Optional[float]:
    """Change between two percentage figures, expressed in basis points."""
    if current_pct is None or prior_pct is None:
        return None
    return round((current_pct - prior_pct) * 100, 1)


def compute_ratios(financials: dict) -> dict:
    """Compute a standard ratio pack from a dict of raw line items.

    Expected (all optional) keys, in the same currency unit:
        revenue, cost_of_revenue, gross_profit, operating_income, net_income,
        total_assets, total_liabilities, shareholders_equity, current_assets,
        current_liabilities, inventory, ebit, interest_expense,
        prior_revenue, prior_net_income, shares_outstanding, price
    """
    f = financials
    revenue = f.get("revenue")
    gross_profit = f.get("gross_profit")
    if gross_profit is None and revenue is not None and f.get("cost_of_revenue") is not None:
        gross_profit = revenue - f["cost_of_revenue"]

    net_income = f.get("net_income")
    equity = f.get("shareholders_equity")
    total_assets = f.get("total_assets")

    ratios: dict[str, Optional[float]] = {
        "gross_margin_pct": pct(gross_profit, revenue),
        "operating_margin_pct": pct(f.get("operating_income"), revenue),
        "net_margin_pct": pct(net_income, revenue),
        "current_ratio": _round(_safe_div(f.get("current_assets"), f.get("current_liabilities"))),
        "quick_ratio": _round(
            _safe_div(
                (f.get("current_assets") or 0) - (f.get("inventory") or 0)
                if f.get("current_assets") is not None
                else None,
                f.get("current_liabilities"),
            )
        ),
        "debt_to_equity": _round(_safe_div(f.get("total_liabilities"), equity)),
        "return_on_equity_pct": pct(net_income, equity),
        "return_on_assets_pct": pct(net_income, total_assets),
        "interest_coverage": _round(_safe_div(f.get("ebit"), f.get("interest_expense"))),
        "revenue_yoy_pct": yoy_growth(revenue, f.get("prior_revenue")),
        "net_income_yoy_pct": yoy_growth(net_income, f.get("prior_net_income")),
    }

    if net_income is not None and f.get("shares_outstanding"):
        eps = net_income / f["shares_outstanding"]
        ratios["eps"] = _round(eps, 4)
        if f.get("price"):
            ratios["pe_ratio"] = _round(_safe_div(f["price"], eps))

    # Drop keys that couldn't be computed so the model isn't handed nulls to guess with.
    return {k: v for k, v in ratios.items() if v is not None}


def _round(x: Optional[float], ndigits: int = 2) -> Optional[float]:
    return round(x, ndigits) if x is not None else None
