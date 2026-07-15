"""Streamlit UI for the Earnings Analyst.

Run:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running without installing the package (adds ../src to path).
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st  # noqa: E402

from earnings_analyst.config import settings  # noqa: E402
from earnings_analyst.engine import EngineError, run_analysis  # noqa: E402
from earnings_analyst.ingestion import load_text  # noqa: E402

st.set_page_config(page_title="Earnings Analyst", page_icon="📊", layout="wide")

st.title("📊 Automated Financial Report & Earnings Analyst")
st.caption(
    "Feed a quarterly filing and earnings-call transcript; get a structured, "
    "tool-grounded analyst brief. Numbers come from SEC EDGAR / yfinance / "
    "deterministic ratio math — not the model's imagination."
)

with st.sidebar:
    st.header("Setup")
    _providers = ["anthropic", "gemini"]
    _default_ix = _providers.index(settings.provider) if settings.provider in _providers else 0
    provider = st.selectbox("Provider", _providers, index=_default_ix)
    if provider == "anthropic":
        has_key = bool(settings.anthropic_api_key)
        st.write("Anthropic API key:", "✅ found" if has_key else "❌ not set")
    else:
        has_key = bool(settings.gemini_api_key)
        st.write("Gemini API key:", "✅ found" if has_key else "❌ not set")
    use_mock = st.toggle(
        "Offline demo (MockLLM)",
        value=not has_key,
        help="Runs a canned analysis with no API key or network.",
    )
    company = st.text_input("Company", "Acme Corp")
    ticker = st.text_input("Ticker (enables live tool data)", "")
    period = st.text_input("Reporting period", "Q2 FY2024")

col1, col2 = st.columns(2)
with col1:
    filing_file = st.file_uploader("10-Q / 10-K", type=["pdf", "htm", "html", "txt"])
    filing_text = st.text_area("…or paste filing text", height=160)
with col2:
    transcript_file = st.file_uploader("Earnings-call transcript", type=["pdf", "htm", "html", "txt"])
    transcript_text = st.text_area("…or paste transcript text", height=160)

prior_text = st.text_area("Prior-quarter transcript (optional, for tone diff)", height=100)


def _read_upload(upload) -> str:
    if upload is None:
        return ""
    data = upload.read()
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


if st.button("Generate brief", type="primary"):
    filing_raw = _read_upload(filing_file) or filing_text
    transcript_raw = _read_upload(transcript_file) or transcript_text

    if not filing_raw and not use_mock:
        st.error("Provide a filing (upload or paste), or switch on the offline demo.")
        st.stop()

    filing_doc = load_text(filing_raw, kind="filing") if filing_raw else None
    transcript_doc = load_text(transcript_raw, kind="transcript") if transcript_raw else None
    prior_doc = load_text(prior_text, kind="transcript") if prior_text else None

    llm = None
    if use_mock:
        from earnings_analyst.demo import build_mock_llm

        llm = build_mock_llm(company, ticker or None, period)

    with st.spinner("Analyzing… (running tool-use loop)"):
        try:
            result = run_analysis(
                company=company,
                ticker=ticker or None,
                period=period,
                filing=filing_doc,
                transcript=transcript_doc,
                prior_transcript=prior_doc,
                llm=llm,
                provider=provider,
            )
        except (EngineError, RuntimeError) as exc:
            st.error(f"Analysis failed: {exc}")
            st.stop()

    brief = result.brief
    st.success("Brief generated.")

    st.subheader(brief.headline)
    if brief.key_metrics:
        st.markdown("**Key metrics**")
        st.dataframe(
            [
                {
                    "Metric": m.name,
                    "Value": f"{m.value:,.2f} {m.unit}",
                    "Period": m.period,
                    "YoY": f"{m.yoy_change_pct:+.1f}%" if m.yoy_change_pct is not None else "—",
                    "Source": m.source,
                }
                for m in brief.key_metrics
            ],
            use_container_width=True,
            hide_index=True,
        )

    left, right = st.columns(2)
    with left:
        if brief.revenue_drivers:
            st.markdown("**Revenue drivers**")
            for d in brief.revenue_drivers:
                st.markdown(f"- {d.direction.value.upper()} · **{d.driver}** — {d.commentary}")
        if brief.margin_changes:
            st.markdown("**Margin changes**")
            for mc in brief.margin_changes:
                delta = f"{mc.delta_bps:+.0f} bps" if mc.delta_bps is not None else "—"
                st.markdown(f"- **{mc.margin_type}** ({delta}) — {mc.driver_commentary}")
    with right:
        if brief.risk_flags:
            st.markdown("**Risk flags**")
            for r in brief.risk_flags:
                st.markdown(f"- `{r.severity.value.upper()}` **{r.risk}** — {r.rationale}")
        if brief.sentiment_shift:
            s = brief.sentiment_shift
            st.markdown("**Management tone / sentiment shift**")
            st.markdown(f"{s.assessment.value.replace('_', ' ').title()} · confidence {s.confidence:.0%}")
            for e in s.evidence:
                st.markdown(f"- {e}")

    st.markdown("### Plain-English summary")
    st.write(brief.plain_english_summary)

    with st.expander("Raw structured output (JSON)"):
        st.json(brief.model_dump())
    with st.expander("Tool evidence (what the model actually fetched)"):
        st.json(brief.tool_evidence)

    st.download_button(
        "Download brief (Markdown)",
        brief.to_markdown(),
        file_name=f"{company.replace(' ', '_')}_{period.replace(' ', '_')}_brief.md",
    )
