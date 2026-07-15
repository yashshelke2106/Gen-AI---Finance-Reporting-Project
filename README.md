# Automated Financial Report & Earnings Analyst

> Not another "I called an API" project — every number in the brief is verified against the filing.

**Tech:** Python · Anthropic Claude / Google Gemini · function-calling · Pydantic · SEC EDGAR · yfinance · Streamlit · pytest

Feed it a company's quarterly filing (10-Q/10-K) and earnings-call transcript; it
returns a **structured, tool-grounded analyst brief**: revenue drivers, margin
changes, risk flags, a management-tone / sentiment shift vs. last quarter, and a
plain-English summary a non-finance stakeholder can act on.

The differentiator: **every number is fetched or computed by a tool, not
hallucinated.** The model calls SEC EDGAR and yfinance for figures and a
deterministic ratio engine for margins/growth — and an **eval harness** checks
that the numbers in the brief actually match the source of truth.

---

## Why this project

| Target field | What it demonstrates |
|---|---|
| Fintech / finance | Domain fluency: filings, ratios, margins, risk factors |
| Consulting | Turning raw data into a decision-ready memo |
| IT / AI eng | Prompt engineering, function-calling, structured-output validation |
| Data analytics | Deterministic metric computation + an accuracy eval harness |

---

## Architecture

```
document(s) ──► ingestion ──► engine (Anthropic tool-use loop) ──► AnalystBrief (Pydantic)
                                     │
                                     ├─ get_filing_financials  → SEC EDGAR XBRL line items
                                     ├─ compute_ratios         → deterministic ratio math
                                     └─ get_market_snapshot    → yfinance price/multiples
                                     │
                              emit_analyst_brief (schema-forced structured output)
                                     │
                             eval harness ── checks numbers vs. ground truth
```

Key idea: the model is offered an `emit_analyst_brief` tool whose input schema
**is** the `AnalystBrief` Pydantic schema. The model can only "finish" by
returning data that validates. Each metric carries a `source` field, and the
engine records all tool results as `tool_evidence` so the eval harness can
verify grounding.

---

## Install

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .            # installs the `earnings_analyst` package + CLI entrypoint
cp .env.example .env        # then add your ANTHROPIC_API_KEY
```

Python 3.10+. After `pip install -e .` you can use either `earnings-analyst ...`
or `python -m earnings_analyst.cli ...`. If you'd rather not install, prefix
commands with `PYTHONPATH=src`.

### Choosing a provider (Anthropic or Gemini)

The engine is provider-agnostic. Pick one:

- **Anthropic** (default) — paid, no permanent free tier. Set `ANTHROPIC_API_KEY`.
- **Gemini** — has a free tier. Get a key at https://aistudio.google.com/apikey,
  set `GEMINI_API_KEY`, and either export `EARNINGS_ANALYST_PROVIDER=gemini` or
  pass `--provider gemini` on the CLI (a dropdown in the Streamlit app).

You cannot use a Gemini key with the Anthropic provider or vice-versa — the tool
schemas and message formats differ, which is why this is a real provider switch,
not just a key swap. Gemini's function declarations don't resolve JSON-schema
`$ref`, so `schema_utils.flatten_schema` inlines the Pydantic schema before
sending it.

```bash
# Free Gemini run:
export EARNINGS_ANALYST_PROVIDER=gemini   # Windows: set EARNINGS_ANALYST_PROVIDER=gemini
earnings-analyst --provider gemini --company "Apple Inc." --ticker AAPL \
  --period "Q2 FY2024" --filing path/to/aapl_10q.pdf --out brief.md
```

---

## Run

**Offline demo (no API key, no network)** — uses a scripted MockLLM that still
runs the real ratio tool and schema validation:

```bash
earnings-analyst --mock \
  --company "Acme Corp" --period "Q2 FY2024" \
  --filing data/samples/sample_10q_excerpt.txt \
  --transcript data/samples/sample_transcript.txt \
  --out brief.md
```

**Live analysis** (needs `ANTHROPIC_API_KEY`; `--ticker` turns on EDGAR/yfinance):

```bash
earnings-analyst \
  --company "Apple Inc." --ticker AAPL --period "Q2 FY2024" \
  --filing path/to/aapl_10q.pdf \
  --transcript path/to/aapl_call.txt \
  --prior-transcript path/to/aapl_prior_call.txt \
  --out brief.md --json brief.json
```

**Streamlit app:**

```bash
streamlit run app/streamlit_app.py
```

Upload or paste a filing + transcript, toggle the offline demo if you have no
key, and download the brief as Markdown.

---

## Eval harness

The harness runs each fixture case end-to-end and scores four things:

- **schema_valid** — engine returned a Pydantic-valid brief
- **numeric_accuracy** — reported metric values match ground truth within tolerance
- **source_grounding** — every numeric metric is tagged with a source that
  actually appears in the tool evidence (the anti-hallucination check)
- **qualitative** — sentiment label + expected risk keywords present

```bash
python eval/harness.py --json eval/reports/latest.json
```

It exits non-zero if numeric accuracy or grounding drops below 99% — usable as a
CI gate. Add your own labeled cases in `eval/fixtures/cases.json` (set
`"use_mock": false` to score a live model run).

---

## Tests

```bash
pytest -q
```

Covers ratio math, document ingestion/section detection, and a full
MockLLM-driven engine run.

---

## Project layout

```
src/earnings_analyst/
  schemas.py      Pydantic brief schema + markdown renderer
  ingestion.py    PDF/HTML/TXT parsing + section detection
  tools/          edgar.py, market_data.py, ratios.py, registry.py
  llm.py          Anthropic client + MockLLM
  engine.py       tool-use loop + schema-forced output + validation
  prompts.py      system + user prompt templates
  demo.py         offline scripted scenario
  cli.py          command-line entrypoint
app/streamlit_app.py
eval/harness.py   accuracy / grounding eval + fixtures
tests/            pytest suite
data/samples/     illustrative filing + transcripts
```

---

## Design notes & limitations

- **EDGAR** requires a descriptive `User-Agent` (set `SEC_EDGAR_USER_AGENT`).
  Concept tags vary across filers; `edgar.py` tries several aliases per line item.
- Ratios are intentionally **pure Python** — the model is instructed never to do
  arithmetic itself, so the eval can trust the ratio outputs.
- Long documents are trimmed (`Document.excerpt`) to fit context; for very large
  filings, a future improvement is retrieval over sections rather than truncation.
- Sample data is **illustrative** ("Acme Corp"), not a real company.

## License

MIT
