"""Automated Financial Report & Earnings Analyst.

A library + CLI + Streamlit app that turns a company's quarterly filings and
earnings-call transcript into a structured, validated analyst brief. Live
figures and ratios come from tool-calling (yfinance + SEC EDGAR) rather than
being hallucinated by the model.
"""

__version__ = "0.1.0"

from .schemas import AnalystBrief

__all__ = ["AnalystBrief", "__version__"]
