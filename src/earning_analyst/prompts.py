"""Prompt templates for the analyst engine."""
from __future__ import annotations

SYSTEM_PROMPT = """You are a meticulous equity research analyst. You turn primary \
source documents (a company's 10-Q/10-K and its earnings-call transcript) into a \
concise, decision-ready analyst brief.

Hard rules:
1. NEVER state a financial figure or ratio from memory or by doing arithmetic in \
your head. Get line items via the `get_filing_financials` tool and compute every \
ratio via the `compute_ratios` tool. If you need market pricing, call \
`get_market_snapshot`.
2. Every numeric value in your final brief must have a `source` field naming the \
tool it came from (e.g. "edgar", "ratios", "yfinance") or "filing_text" only if you \
read it directly from the provided document text and no tool could supply it.
3. Prefer the tool numbers over any number printed in the document if they conflict, \
and note the discrepancy in a risk flag.
4. For sentiment, compare the tone of THIS quarter's management commentary to the \
prior quarter's if a prior transcript is provided; otherwise assess tone in absolute \
terms and set confidence accordingly.
5. Be specific and evidence-based. Quote sparingly but concretely for risk flags.
6. The plain-English summary must avoid jargon and tell a non-finance stakeholder \
what happened and why it matters, in 4-6 sentences.

Workflow: call the data tools first to gather and verify numbers, then call \
`emit_analyst_brief` exactly once with the completed structured brief. Do not write \
the brief as free text."""


def build_user_message(
    company: str,
    ticker: str | None,
    period: str,
    filing_text: str,
    transcript_text: str | None,
    prior_transcript_text: str | None,
) -> str:
    parts = [
        f"Company: {company}",
        f"Ticker: {ticker or 'unknown'}",
        f"Reporting period to analyze: {period}",
        "",
        "=== CURRENT FILING (10-Q/10-K excerpt) ===",
        filing_text or "(none provided)",
    ]
    if transcript_text:
        parts += ["", "=== CURRENT EARNINGS-CALL TRANSCRIPT ===", transcript_text]
    if prior_transcript_text:
        parts += [
            "",
            "=== PRIOR-QUARTER TRANSCRIPT (for tone comparison) ===",
            prior_transcript_text,
        ]
    parts += [
        "",
        "Produce the analyst brief. Use the tools to fetch and compute all numbers, "
        "then call emit_analyst_brief.",
    ]
    return "\n".join(parts)
