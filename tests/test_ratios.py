import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earnings_analyst.tools.ratios import (  # noqa: E402
    compute_ratios,
    delta_bps,
    pct,
    yoy_growth,
)


def test_pct_and_growth():
    assert pct(550, 1250) == 44.0
    assert pct(None, 1250) is None
    assert pct(10, 0) is None
    assert yoy_growth(1250, 1100) == 13.64
    assert yoy_growth(1250, 0) is None


def test_delta_bps():
    assert delta_bps(44.0, 41.0) == 300.0
    assert delta_bps(None, 41.0) is None


def test_compute_ratios_full():
    fin = {
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
        "shares_outstanding": 100.0,
        "price": 84.0,
    }
    r = compute_ratios(fin)
    assert r["gross_margin_pct"] == 44.0
    assert r["net_margin_pct"] == 16.8
    assert r["operating_margin_pct"] == 24.0
    assert r["current_ratio"] == 2.5
    assert r["quick_ratio"] == round((1500 - 250) / 600, 2)
    assert r["debt_to_equity"] == 0.75
    assert r["return_on_equity_pct"] == 8.75
    assert r["revenue_yoy_pct"] == 13.64
    assert r["eps"] == 2.1
    assert r["pe_ratio"] == 40.0


def test_compute_ratios_handles_missing():
    # Only revenue -> no divide-by-None crashes, and empty-ish result.
    r = compute_ratios({"revenue": 100.0})
    assert "gross_margin_pct" not in r  # no gross profit / cost given
    assert isinstance(r, dict)
