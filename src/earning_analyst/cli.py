"""Command-line interface.

Example:
    earnings-analyst --company "Acme Corp" --ticker ACME --period "Q2 FY2024" \
        --filing data/samples/sample_10q_excerpt.txt \
        --transcript data/samples/sample_transcript.txt \
        --out brief.md
"""
from __future__ import annotations

import argparse
import sys

from .engine import EngineError, run_analysis
from .ingestion import load_document


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="earnings-analyst",
        description="Generate a structured analyst brief from filings + transcript.",
    )
    p.add_argument("--company", required=True, help="Company name")
    p.add_argument("--ticker", default=None, help="Stock ticker (enables live tool data)")
    p.add_argument("--period", required=True, help="Reporting period, e.g. 'Q2 FY2024'")
    p.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "gemini"],
        help="LLM provider (default: from EARNINGS_ANALYST_PROVIDER or 'anthropic')",
    )
    p.add_argument("--filing", default=None, help="Path to 10-Q/10-K (pdf/html/txt)")
    p.add_argument("--transcript", default=None, help="Path to earnings-call transcript")
    p.add_argument("--prior-transcript", default=None, help="Prior-quarter transcript for tone diff")
    p.add_argument("--out", default=None, help="Write markdown brief to this path")
    p.add_argument("--json", dest="json_out", default=None, help="Write raw JSON brief to this path")
    p.add_argument(
        "--mock",
        action="store_true",
        help="Run with a canned MockLLM (offline demo, no API key needed)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    filing = load_document(args.filing, kind="filing") if args.filing else None
    transcript = load_document(args.transcript, kind="transcript") if args.transcript else None
    prior = (
        load_document(args.prior_transcript, kind="transcript")
        if args.prior_transcript
        else None
    )

    llm = None
    if args.mock:
        from .demo import build_mock_llm

        llm = build_mock_llm(args.company, args.ticker, args.period)

    try:
        result = run_analysis(
            company=args.company,
            ticker=args.ticker,
            period=args.period,
            filing=filing,
            transcript=transcript,
            prior_transcript=prior,
            llm=llm,
            provider=args.provider,
        )
    except (EngineError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    md = result.brief.to_markdown()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"Wrote markdown brief to {args.out}")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(result.brief.model_dump_json(indent=2))
        print(f"Wrote JSON brief to {args.json_out}")
    if not args.out and not args.json_out:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
