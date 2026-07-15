"""The analyst engine: orchestrates the tool-use loop and validates output.

Flow:
  1. Build system + user messages from the ingested documents.
  2. Offer the model the data tools plus an `emit_analyst_brief` tool whose
     input schema IS the AnalystBrief Pydantic schema (schema-forced output).
  3. Run the tool-use loop, executing each requested data tool and feeding the
     result back. Record every tool result as `tool_evidence`.
  4. When the model calls `emit_analyst_brief`, validate the payload with
     Pydantic, attach the collected evidence, and return an AnalystBrief.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from .config import settings
from .ingestion import Document
from .llm import LLMClient, make_llm
from .prompts import SYSTEM_PROMPT, build_user_message
from .schemas import AnalystBrief
from .tools import TOOL_SCHEMAS, dispatch_tool

EMIT_TOOL_NAME = "emit_analyst_brief"


def _emit_tool_schema() -> dict[str, Any]:
    schema = AnalystBrief.model_json_schema()
    # tool_evidence is populated by the engine, not the model.
    schema.get("properties", {}).pop("tool_evidence", None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"] if r != "tool_evidence"]
    return {
        "name": EMIT_TOOL_NAME,
        "description": (
            "Emit the final, completed analyst brief as structured data. Call this "
            "exactly once, after you have gathered and verified all numbers with the "
            "data tools."
        ),
        "input_schema": schema,
    }


@dataclass
class AnalysisResult:
    brief: AnalystBrief
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""


def run_analysis(
    company: str,
    period: str,
    filing: Document | None = None,
    transcript: Document | None = None,
    prior_transcript: Document | None = None,
    ticker: str | None = None,
    llm: LLMClient | None = None,
    provider: str | None = None,
    max_iterations: int | None = None,
    max_doc_chars: int = 60_000,
) -> AnalysisResult:
    """Run the full analysis and return a validated brief."""
    llm = llm or make_llm(provider)
    max_iterations = max_iterations or settings.max_tool_iterations

    tools = list(TOOL_SCHEMAS) + [_emit_tool_schema()]
    user_msg = build_user_message(
        company=company,
        ticker=ticker,
        period=period,
        filing_text=filing.excerpt(max_doc_chars) if filing else "",
        transcript_text=transcript.excerpt(max_doc_chars) if transcript else None,
        prior_transcript_text=prior_transcript.excerpt(max_doc_chars // 2)
        if prior_transcript
        else None,
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]

    tool_evidence: dict[str, Any] = {}
    tool_calls_log: list[dict[str, Any]] = []

    for _ in range(max_iterations):
        resp = llm.create(system=SYSTEM_PROMPT, messages=messages, tools=tools)
        tool_uses = resp.tool_uses()

        if not tool_uses:
            # Model returned text without emitting a brief. Nudge once by asking
            # for the structured emit, then break to avoid infinite loops.
            raise EngineError(
                "Model ended without calling emit_analyst_brief. "
                f"Last text: {resp.text()[:500]}"
            )

        # Append the assistant turn verbatim so tool_use ids line up.
        messages.append({"role": "assistant", "content": resp.content})

        emit_block = next((t for t in tool_uses if t["name"] == EMIT_TOOL_NAME), None)
        if emit_block is not None:
            payload = copy.deepcopy(emit_block["input"])
            payload["tool_evidence"] = tool_evidence
            brief = AnalystBrief.model_validate(payload)
            return AnalysisResult(brief=brief, tool_calls=tool_calls_log, raw_text=resp.text())

        # Execute every non-emit tool call and return results.
        results_content = []
        for tu in tool_uses:
            result = dispatch_tool(tu["name"], tu.get("input", {}))
            tool_calls_log.append({"name": tu["name"], "input": tu.get("input", {}), "result": result})
            tool_evidence.setdefault(tu["name"], []).append(
                {"input": tu.get("input", {}), "result": result}
            )
            results_content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": json.dumps(result, default=str),
                }
            )
        messages.append({"role": "user", "content": results_content})

    raise EngineError(f"Exceeded max_iterations ({max_iterations}) without a final brief.")


class EngineError(RuntimeError):
    """Raised when the tool-use loop fails to produce a valid brief."""
