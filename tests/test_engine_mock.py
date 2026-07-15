"""End-to-end engine test using MockLLM (no API key, no network)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_analyst.demo import build_mock_llm  # noqa: E402
from earnings_analyst.engine import run_analysis  # noqa: E402
from earnings_analyst.ingestion import load_document  # noqa: E402
from earnings_analyst.schemas import AnalystBrief  # noqa: E402


def _run():
    filing = load_document(str(ROOT / "data" / "samples" / "sample_10q_excerpt.txt"), "filing")
    llm = build_mock_llm("Acme Corp", None, "Q2 FY2024")
    return run_analysis(
        company="Acme Corp",
        ticker=None,
        period="Q2 FY2024",
        filing=filing,
        llm=llm,
    )


def test_engine_returns_valid_brief():
    result = _run()
    assert isinstance(result.brief, AnalystBrief)
    assert result.brief.company == "Acme Corp"
    assert result.brief.key_metrics
    assert result.brief.plain_english_summary


def test_tool_evidence_recorded():
    result = _run()
    # compute_ratios must have actually run and its result captured.
    assert "compute_ratios" in result.brief.tool_evidence
    ratios_result = result.brief.tool_evidence["compute_ratios"][0]["result"]
    assert ratios_result["gross_margin_pct"] == 44.0


def test_every_metric_is_source_tagged():
    result = _run()
    for m in result.brief.key_metrics:
        assert m.source, "each metric must name its source"


def test_markdown_render():
    md = _run().brief.to_markdown()
    assert "# Analyst Brief" in md
    assert "Plain-English Summary" in md
