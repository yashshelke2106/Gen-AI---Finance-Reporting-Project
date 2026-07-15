# How It Works — Automated Financial Report & Earnings Analyst

This document explains the whole system end to end: what each file does, how a
request flows through the code, and the design decisions that make the output
trustworthy (numbers come from tools, not the model's imagination).

---

## 1. The one-paragraph mental model

You give the system a company's filing (10-Q/10-K) and earnings-call transcript.
It hands those documents to an LLM, but the LLM is **not allowed to state numbers
on its own** — it must call tools (SEC EDGAR for line items, a deterministic
ratio calculator, yfinance for market data). The LLM can only "finish" by filling
in a strict schema (an `emit_analyst_brief` tool). The engine validates that
schema with Pydantic, records every tool result as evidence, and returns a
structured brief. An eval harness then checks that the numbers in the brief match
the source of truth.

---

## 2. High-level flow

```
                ┌──────────────┐
   your docs ──►│  ingestion   │  parse PDF/HTML/TXT, detect sections, trim
                └──────┬───────┘
                       ▼
                ┌──────────────┐   system + user prompt
                │   engine     │──────────────────────────────┐
                └──────┬───────┘                               ▼
                       │  tool-use loop            ┌───────────────────────┐
                       │◄──────────────────────────│   LLM (Claude/Gemini) │
                       │   model asks for a tool    └───────────────────────┘
                       ▼
        ┌──────────────────────────────┐
        │  tools/                      │
        │   • get_filing_financials →  │  SEC EDGAR XBRL line items
        │   • compute_ratios        →  │  pure-Python ratio math
        │   • get_market_snapshot   →  │  yfinance price/multiples
        └──────────────┬───────────────┘
                       │  results fed back to model
                       ▼
        model calls  emit_analyst_brief (schema = AnalystBrief)
                       ▼
                ┌──────────────┐
                │ Pydantic     │  validate → AnalystBrief object (+ tool_evidence)
                │ validation   │
                └──────┬───────┘
                       ▼
             CLI  /  Streamlit  /  eval harness
```

---

## 3. File-by-file breakdown

### `src/earnings_analyst/schemas.py` — the contract
Defines the **shape of the output** using Pydantic models:
`AnalystBrief` contains `key_metrics`, `revenue_drivers`, `margin_changes`,
`risk_flags`, `sentiment_shift`, and `plain_english_summary`. Each `Metric`
carries a `source` field ("edgar", "ratios", "yfinance", or "filing_text") so
every number is traceable. `AnalystBrief.to_markdown()` renders the brief as a
readable memo. This file is the single source of truth for what a valid brief
looks like — the LLM's output is checked against it, and the tool schema handed
to the model is *generated from* it.

### `src/earnings_analyst/ingestion.py` — getting text in
Reads `.pdf` (pdfplumber), `.htm/.html` (BeautifulSoup), and `.txt`. Cleans
whitespace, guesses whether a document is a `filing` or a `transcript`, and for
filings detects sections (MD&A, risk factors, liquidity, results of operations).
`Document.excerpt()` trims very long filings so they fit the model's context
window. Returns a `Document` dataclass.

### `src/earnings_analyst/tools/` — what the model can call
This is the heart of the anti-hallucination design.

- **`ratios.py`** — pure Python. `compute_ratios()` takes raw line items and
  returns margins, ROE/ROA, current/quick ratio, debt-to-equity, YoY growth,
  EPS, and P/E. No LLM involved, so the numbers are exact and testable. The
  model is explicitly told never to do arithmetic itself.
- **`edgar.py`** — fetches real reported line items from SEC EDGAR's XBRL
  `companyfacts` API. Resolves a ticker to a CIK, then pulls concepts like
  `Revenues`, `NetIncomeLoss`, `Assets`, trying several tag aliases because
  filers tag things differently. Each value comes back with its unit, period,
  and source form (10-Q/10-K) — fully traceable.
- **`market_data.py`** — `get_market_snapshot()` uses yfinance for live price,
  market cap, trailing/forward P/E, margins, and 52-week range. Fails soft
  (returns an error dict instead of crashing) so the loop can continue offline.
- **`registry.py`** — `TOOL_SCHEMAS` are the JSON descriptions of these tools
  that get sent to the model; `dispatch_tool(name, input)` runs the matching
  Python function when the model asks for it.

### `src/earnings_analyst/prompts.py` — instructions
`SYSTEM_PROMPT` lays down the hard rules: never state numbers from memory, always
tag each number with its source, prefer tool numbers over the document if they
conflict, compare tone to last quarter, keep the summary jargon-free.
`build_user_message()` assembles the documents into the user turn.

### `src/earnings_analyst/llm.py` — talking to the model
Provides a common interface (`LLMResponse` with `text` + `tool_use` blocks) so
the engine doesn't care which provider it's using.
- **`AnthropicLLM`** — wraps Claude's messages API.
- **`GeminiLLM`** — wraps Google Gemini. Because Gemini's function-calling won't
  resolve JSON-schema `$ref`, and speaks a different message format, this class
  translates the engine's Anthropic-style history into Gemini `contents` and
  normalizes the response back. Tool schemas are flattened first
  (see `schema_utils.py`).
- **`MockLLM`** — returns scripted turns for offline tests/evals (no key, no
  network).
- **`make_llm(provider)`** — factory that returns the right client.

### `src/earnings_analyst/schema_utils.py` — Gemini compatibility
`flatten_schema()` inlines all `$ref`/`$defs`, collapses `Optional` fields
(`anyOf: [T, null]`) into `T` + `nullable`, and strips keywords Gemini rejects.
Anthropic doesn't need this; Gemini does.

### `src/earnings_analyst/engine.py` — the orchestrator
`run_analysis()` runs the loop (details in §4). It builds the tool list
(data tools **plus** an `emit_analyst_brief` tool whose schema *is* the
`AnalystBrief` schema), calls the model repeatedly, executes any tools the model
requests, feeds results back, and — when the model calls `emit_analyst_brief` —
validates the payload with Pydantic and attaches the collected `tool_evidence`.
Returns an `AnalysisResult`.

### `src/earnings_analyst/demo.py` — offline scenario
Scripts a `MockLLM` that calls the real `compute_ratios` tool on bundled sample
numbers, then emits a complete, schema-valid brief. Powers `--mock` and the eval
harness with no key and no network.

### `src/earnings_analyst/cli.py` — command-line entry
Parses args (`--company`, `--ticker`, `--period`, `--filing`, `--transcript`,
`--prior-transcript`, `--provider`, `--mock`, `--out`, `--json`), loads the
documents, runs the analysis, and writes/prints the brief.

### `app/streamlit_app.py` — web UI
Upload or paste a filing + transcript, pick a provider, toggle offline demo, and
click Generate. Renders the metrics table, drivers, margins, risks, sentiment,
plain-English summary, and expandable raw JSON + tool evidence. Download as
Markdown.

### `eval/harness.py` — the accuracy check
Runs each fixture case end to end and scores four things (details in §6):
schema validity, numeric accuracy vs. ground truth, source-grounding
(anti-hallucination), and qualitative checks (sentiment + risk keywords). Exits
non-zero if accuracy or grounding drops below 99% — usable as a CI gate.

### `tests/` — unit + integration tests
`test_ratios.py` (ratio math), `test_ingestion.py` (parsing + section detection),
`test_schema_utils.py` (the Gemini flattener), `test_engine_mock.py` (a full
MockLLM-driven run). Run with `pytest -q`.

### Config & samples
`config.py` loads settings from `.env` (provider, API keys, model, EDGAR
user-agent). `data/samples/` holds an illustrative filing + current/prior
transcripts. `.streamlit/config.toml` pins the app to port 8600.

---

## 4. The tool-use loop, step by step

This is the core algorithm in `engine.run_analysis()`:

1. **Assemble tools.** Combine the data tools (`get_filing_financials`,
   `compute_ratios`, `get_market_snapshot`) with a generated `emit_analyst_brief`
   tool. The emit tool's `input_schema` is literally
   `AnalystBrief.model_json_schema()` (minus the engine-only `tool_evidence`
   field). This is *schema-forced output* — the model can only finish by
   returning data that fits the schema.

2. **First model call.** Send the system prompt, the user message (documents),
   and the tool list.

3. **Inspect the response:**
   - If the model returns **text only** (no tool call) → error out (it broke the
     rule to emit via the tool).
   - If the model calls **`emit_analyst_brief`** → we're done: deep-copy the
     payload, attach `tool_evidence`, validate with
     `AnalystBrief.model_validate()`, return.
   - If the model calls **data tools** → run each via `dispatch_tool()`, record
     the result in `tool_evidence` and `tool_calls_log`, and append the results
     back as a `tool_result` message.

4. **Loop.** Repeat up to `max_iterations` (default 8). Each iteration the model
   sees the accumulated tool results and either asks for more data or emits the
   brief.

5. **Guardrails.** If the loop exceeds `max_iterations` without a brief, raise
   `EngineError`. Every tool result is retained so the brief's numbers can be
   audited afterward.

Why this matters: the model never has a chance to "just write a number." The only
numbers that reach the brief either came through a tool (and are recorded in
`tool_evidence`) or are explicitly tagged `filing_text`. The eval harness uses
exactly this to detect hallucination.

---

## 5. Structured output & validation

- The model's final answer is a **tool call**, not prose, so its shape is
  constrained by the JSON schema.
- Pydantic then does a second, stricter pass: types, enums (`Direction`,
  `Sentiment`, `Severity`), ranges (e.g. sentiment `confidence` in 0–1). If the
  model returns anything malformed, `model_validate()` raises and the run fails
  loudly instead of silently producing a bad brief.
- `tool_evidence` (all tool inputs/outputs) is attached by the engine, never by
  the model — so it's a trustworthy record of what actually happened.

---

## 6. The eval harness — how "does it match the filing?" is measured

For each case in `eval/fixtures/cases.json`, `harness.py`:

- **schema_valid** — did the engine return a Pydantic-valid brief at all?
- **numeric_accuracy** — for each ground-truth metric, is the brief's value
  within tolerance? It also cross-checks computed ratios (e.g. revenue YoY)
  against the `compute_ratios` output captured in `tool_evidence`.
- **source_grounding** — the anti-hallucination metric. For every metric in the
  brief, is its `source` a tool that *actually appears in `tool_evidence`* (or
  `filing_text`)? A number tagged "edgar" when EDGAR was never called would fail
  here.
- **qualitative** — is the sentiment label what we expected, and do the expected
  risk keywords show up in the risk flags?

It prints a report and can write JSON (`--json`). It returns a non-zero exit code
if numeric accuracy or grounding falls below 99%, so it can gate CI. To test a
real model (not the mock), set `"use_mock": false` on a case and supply real
ground-truth numbers.

---

## 7. Providers (Anthropic vs. Gemini)

The engine is provider-agnostic. `make_llm(provider)` returns either client.
Selection order: the `--provider` flag / Streamlit dropdown → the
`EARNINGS_ANALYST_PROVIDER` env var → default `anthropic`. A Gemini key cannot be
used with the Anthropic client (different auth, tool format, message shape) — the
`GeminiLLM` class exists precisely to bridge that gap, which is why switching is a
real provider change and not just a key swap.

---

## 8. Running it

```bash
pip install -r requirements.txt
pip install -e .

# Offline (no key, no network) — proves the pipeline:
earnings-analyst --mock --company "Acme Corp" --period "Q2 FY2024" \
  --filing data/samples/sample_10q_excerpt.txt \
  --transcript data/samples/sample_transcript.txt

# Live with Gemini (free tier):
#   .env: EARNINGS_ANALYST_PROVIDER=gemini, GEMINI_API_KEY=...
earnings-analyst --provider gemini --company "Apple Inc." --ticker AAPL \
  --period "Q2 FY2024" --filing aapl_10q.pdf --out brief.md

# Tests + eval:
pytest -q
python eval/harness.py

# Web app (port 8600):
streamlit run app/streamlit_app.py
```

---

## 9. Known limitations (be honest about these)

- The bundled eval case runs on `MockLLM`, so 100% scores prove the *plumbing*,
  not the model. Add real cases (`"use_mock": false`) with real filings and real
  ground truth to actually measure extraction accuracy.
- `edgar.py`'s concept aliases won't cover every filer (banks, insurers, foreign
  issuers tag differently).
- Long filings are truncated (`Document.excerpt`) rather than retrieved over, so
  a risk buried deep in a huge 10-K could be missed. Section-aware retrieval is
  the natural next improvement.
- Gemini Flash is weaker than Claude at pulling exact figures from messy filings;
  the tool-grounding protects the numbers, but the model still chooses which
  numbers to feed the tools.
- Sample data ("Acme Corp") is illustrative, not a real company.
