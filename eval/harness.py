"""Eval harness — does the model's brief match the source of truth?

For each case it runs the full analysis and scores four things:

  1. schema_valid       — did the engine return a Pydantic-valid AnalystBrief?
  2. numeric_accuracy   — do reported metric values match ground truth within tol?
  3. source_grounding   — is every numeric metric tagged with a source that
                          actually appears in the tool evidence (or 'filing_text')?
                          This is the anti-hallucination check.
  4. qualitative        — sentiment label + expected risk keywords present.

Run:
    python eval/harness.py                # all cases, mock LLM, prints a report
    python eval/harness.py --json out.json

Live mode (uses your ANTHROPIC_API_KEY and network) is enabled per-case by
setting "use_mock": false in the fixture.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_analyst.engine import run_analysis  # noqa: E402
from earnings_analyst.ingestion import load_document  # noqa: E402


@dataclass
class CaseScore:
    case_id: str
    schema_valid: bool = False
    metrics_checked: int = 0
    metrics_correct: int = 0
    grounded_metrics: int = 0
    total_metrics: int = 0
    sentiment_ok: bool = False
    risk_keywords_found: int = 0
    risk_keywords_expected: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def numeric_accuracy(self) -> float:
        return self.metrics_correct / self.metrics_checked if self.metrics_checked else 0.0

    @property
    def grounding_rate(self) -> float:
        return self.grounded_metrics / self.total_metrics if self.total_metrics else 0.0


def _grounded(source: str, tool_evidence: dict) -> bool:
    if not source:
        return False
    s = source.lower()
    if s in ("filing_text", "filing", "transcript"):
        return True
    # A tool source is grounded if that tool was actually called.
    aliases = {
        "ratios": "compute_ratios",
        "edgar": "get_filing_financials",
        "sec": "get_filing_financials",
        "yfinance": "get_market_snapshot",
        "market": "get_market_snapshot",
    }
    tool_name = aliases.get(s, s)
    return tool_name in tool_evidence


def score_case(case: dict) -> CaseScore:
    score = CaseScore(case_id=case["id"])

    def resolve(rel):
        return str(ROOT / rel) if rel else None

    filing = load_document(resolve(case["filing"]), "filing") if case.get("filing") else None
    transcript = (
        load_document(resolve(case["transcript"]), "transcript")
        if case.get("transcript")
        else None
    )
    prior = (
        load_document(resolve(case["prior_transcript"]), "transcript")
        if case.get("prior_transcript")
        else None
    )

    llm = None
    if case.get("use_mock", True):
        from earnings_analyst.demo import build_mock_llm

        llm = build_mock_llm(case["company"], case.get("ticker"), case["period"])

    try:
        result = run_analysis(
            company=case["company"],
            ticker=case.get("ticker"),
            period=case["period"],
            filing=filing,
            transcript=transcript,
            prior_transcript=prior,
            llm=llm,
        )
    except Exception as exc:
        score.errors.append(f"analysis failed: {exc}")
        return score

    brief = result.brief
    score.schema_valid = True
    gt = case.get("ground_truth", {})

    # ---- numeric accuracy + grounding ----
    by_name = {m.name.lower(): m for m in brief.key_metrics}
    score.total_metrics = len(brief.key_metrics)
    score.grounded_metrics = sum(
        1 for m in brief.key_metrics if _grounded(m.source, brief.tool_evidence)
    )

    for name, spec in gt.get("metrics", {}).items():
        score.metrics_checked += 1
        m = by_name.get(name.lower())
        if m is None:
            score.errors.append(f"missing metric '{name}'")
            continue
        if abs(m.value - spec["value"]) <= spec.get("tol", 0.01):
            score.metrics_correct += 1
        else:
            score.errors.append(
                f"metric '{name}' = {m.value}, expected {spec['value']} (±{spec.get('tol')})"
            )

    # ---- cross-check ratio math against ground truth via the same tool ----
    if "revenue_yoy_pct" in gt:
        _check_ratio(score, brief, "revenue_yoy_pct", gt["revenue_yoy_pct"])

    # ---- qualitative ----
    exp_sent = gt.get("expected_sentiment")
    if exp_sent and brief.sentiment_shift:
        score.sentiment_ok = brief.sentiment_shift.assessment.value == exp_sent
        if not score.sentiment_ok:
            score.errors.append(
                f"sentiment = {brief.sentiment_shift.assessment.value}, expected {exp_sent}"
            )

    keywords = [k.lower() for k in gt.get("expected_risk_keywords", [])]
    score.risk_keywords_expected = len(keywords)
    risk_blob = " ".join(
        f"{r.risk} {r.rationale} {r.quote or ''}" for r in brief.risk_flags
    ).lower()
    score.risk_keywords_found = sum(1 for k in keywords if k in risk_blob)

    return score


def _check_ratio(score: CaseScore, brief, key: str, spec: dict) -> None:
    """Cross-check a computed ratio that surfaced in tool evidence."""
    evidence = brief.tool_evidence.get("compute_ratios", [])
    for call in evidence:
        res = call.get("result", {})
        if key in res:
            score.metrics_checked += 1
            if abs(res[key] - spec["value"]) <= spec.get("tol", 0.01):
                score.metrics_correct += 1
            else:
                score.errors.append(
                    f"ratio '{key}' = {res[key]}, expected {spec['value']}"
                )
            return
    score.errors.append(f"ratio '{key}' not found in tool evidence")


def run(cases_path: str) -> dict:
    cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    scores = [score_case(c) for c in cases]

    total_checked = sum(s.metrics_checked for s in scores)
    total_correct = sum(s.metrics_correct for s in scores)
    total_metrics = sum(s.total_metrics for s in scores)
    total_grounded = sum(s.grounded_metrics for s in scores)

    summary = {
        "cases": len(scores),
        "schema_valid_rate": _rate(sum(s.schema_valid for s in scores), len(scores)),
        "numeric_accuracy": _rate(total_correct, total_checked),
        "source_grounding_rate": _rate(total_grounded, total_metrics),
        "sentiment_accuracy": _rate(sum(s.sentiment_ok for s in scores), len(scores)),
        "risk_recall": _rate(
            sum(s.risk_keywords_found for s in scores),
            sum(s.risk_keywords_expected for s in scores),
        ),
        "case_scores": [asdict(s) for s in scores],
    }
    return summary


def _rate(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _print_report(summary: dict) -> None:
    print("\n=== Earnings Analyst — Eval Report ===")
    print(f"Cases:                {summary['cases']}")
    print(f"Schema valid:         {summary['schema_valid_rate']:.0%}")
    print(f"Numeric accuracy:     {summary['numeric_accuracy']:.0%}")
    print(f"Source grounding:     {summary['source_grounding_rate']:.0%}  (anti-hallucination)")
    print(f"Sentiment accuracy:   {summary['sentiment_accuracy']:.0%}")
    print(f"Risk recall:          {summary['risk_recall']:.0%}")
    print("\nPer-case:")
    for cs in summary["case_scores"]:
        status = "OK" if not cs["errors"] else f"{len(cs['errors'])} issue(s)"
        print(
            f"  - {cs['case_id']}: numeric {cs['metrics_correct']}/{cs['metrics_checked']}, "
            f"grounded {cs['grounded_metrics']}/{cs['total_metrics']} [{status}]"
        )
        for e in cs["errors"]:
            print(f"      · {e}")
    print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the earnings-analyst eval harness.")
    p.add_argument(
        "--cases",
        default=str(ROOT / "eval" / "fixtures" / "cases.json"),
        help="Path to cases fixture JSON",
    )
    p.add_argument("--json", dest="json_out", default=None, help="Write full report JSON here")
    args = p.parse_args(argv)

    summary = run(args.cases)
    _print_report(summary)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Wrote report to {args.json_out}")

    # Exit non-zero if the anti-hallucination or accuracy bar isn't met (CI gate).
    ok = summary["numeric_accuracy"] >= 0.99 and summary["source_grounding_rate"] >= 0.99
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
