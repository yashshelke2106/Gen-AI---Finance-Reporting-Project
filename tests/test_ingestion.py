import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earnings_analyst.ingestion import load_document, load_text  # noqa: E402


def test_load_filing_detects_sections():
    doc = load_document(str(ROOT / "data" / "samples" / "sample_10q_excerpt.txt"))
    assert doc.kind == "filing"
    assert "risk_factors" in doc.sections
    assert "mdna" in doc.sections or "results_of_operations" in doc.sections
    assert doc.char_count > 0


def test_transcript_kind_guess():
    doc = load_document(str(ROOT / "data" / "samples" / "sample_transcript.txt"))
    assert doc.kind == "transcript"


def test_excerpt_trims_long_text():
    doc = load_text("A" * 200_000, kind="transcript")
    ex = doc.excerpt(max_chars=1000)
    assert len(ex) < 2000
    assert "omitted" in ex
