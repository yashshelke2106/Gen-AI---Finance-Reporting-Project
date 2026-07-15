"""LLM client abstraction.

`AnthropicLLM` wraps the real API. `MockLLM` returns scripted responses so the
engine, tool-use loop, and eval harness can run with no API key and no network
(used in CI and unit tests).
"""
from __future__ import annotations

from typing import Any, Protocol

from .config import settings


class LLMClient(Protocol):
    def create(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> "LLMResponse":
        ...


class LLMResponse:
    """Normalized response: a stop reason and a list of content blocks.

    Each block is a dict with 'type' in {'text','tool_use'} mirroring the
    Anthropic messages API so the engine handles real and mock identically.
    """

    def __init__(self, stop_reason: str, content: list[dict[str, Any]]):
        self.stop_reason = stop_reason
        self.content = content

    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]

    def text(self) -> str:
        return "\n".join(b.get("text", "") for b in self.content if b.get("type") == "text")


class AnthropicLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("The 'anthropic' package is required for live analysis.") from exc
        key = api_key or settings.anthropic_api_key
        if not key:
            raise RuntimeError(
                "No ANTHROPIC_API_KEY found. Set it in your environment or .env, "
                "or use MockLLM for offline runs."
            )
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model or settings.model

    def create(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        content = []
        for block in resp.content:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
        return LLMResponse(stop_reason=resp.stop_reason, content=content)


class GeminiLLM:
    """Google Gemini client exposing the same interface as AnthropicLLM.

    The engine speaks in Anthropic-style message blocks; this class translates
    that history into Gemini `contents` on every call and normalizes Gemini's
    response back into our `LLMResponse` (text + tool_use blocks). Tool schemas
    are flattened (see schema_utils) because Gemini won't resolve $ref.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        try:
            from google import genai  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "The 'google-genai' package is required for the Gemini provider "
                "(pip install google-genai)."
            ) from exc
        key = api_key or settings.gemini_api_key
        if not key:
            raise RuntimeError(
                "No GEMINI_API_KEY found. Set it in your environment or .env, "
                "or use a different provider."
            )
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=key)
        self.model = model or settings.gemini_model

    def create(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        from google.genai import types

        from .schema_utils import flatten_schema

        fn_decls = [
            types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters=flatten_schema(t["input_schema"]),
            )
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=fn_decls)],
            temperature=0,
            max_output_tokens=max_tokens,
        )
        contents = self._to_contents(messages, types)
        resp = self._client.models.generate_content(
            model=self.model, contents=contents, config=config
        )
        return self._to_response(resp)

    # -- translation helpers -------------------------------------------------

    def _to_contents(self, messages, types):
        """Anthropic-style messages -> Gemini contents.

        Tracks tool_use_id -> function name so tool_result blocks (which only
        carry an id in Anthropic's format) can be sent as Gemini
        function_response parts, which require the function name.
        """
        id_to_name: dict[str, str] = {}
        contents = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if isinstance(content, str):
                contents.append(
                    types.Content(role="user", parts=[types.Part.from_text(text=content)])
                )
                continue
            parts = []
            gem_role = "model" if role == "assistant" else "user"
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    parts.append(types.Part.from_text(text=block.get("text", "")))
                elif btype == "tool_use":
                    id_to_name[block["id"]] = block["name"]
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=block["name"], args=block.get("input", {})
                            )
                        )
                    )
                elif btype == "tool_result":
                    name = id_to_name.get(block.get("tool_use_id", ""), "unknown_tool")
                    payload = block.get("content", "{}")
                    parts.append(
                        types.Part.from_function_response(
                            name=name, response=_as_dict(payload)
                        )
                    )
            if parts:
                contents.append(types.Content(role=gem_role, parts=parts))
        return contents

    def _to_response(self, resp) -> LLMResponse:
        content: list[dict[str, Any]] = []
        candidates = getattr(resp, "candidates", None) or []
        if candidates and candidates[0].content and candidates[0].content.parts:
            for i, part in enumerate(candidates[0].content.parts):
                if getattr(part, "text", None):
                    content.append({"type": "text", "text": part.text})
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": f"gemini_{fc.name}_{i}",
                            "name": fc.name,
                            "input": dict(fc.args or {}),
                        }
                    )
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        return LLMResponse(stop_reason=stop, content=content)


def _as_dict(payload: Any) -> dict[str, Any]:
    import json

    if isinstance(payload, dict):
        return payload
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    except Exception:
        return {"result": str(payload)}


def make_llm(provider: str | None = None, **kwargs) -> LLMClient:
    """Factory: return an LLM client for the chosen provider."""
    provider = (provider or settings.provider or "anthropic").lower()
    if provider == "gemini":
        return GeminiLLM(**kwargs)
    if provider == "anthropic":
        return AnthropicLLM(**kwargs)
    raise ValueError(f"Unknown provider '{provider}'. Use 'anthropic' or 'gemini'.")


class MockLLM:
    """Deterministic client driven by a list of scripted turns.

    Each scripted turn is a dict identical to an assistant message content list.
    Use for tests/evals: it lets you simulate a model that calls tools then
    emits a brief, without touching the network.
    """

    def __init__(self, script: list[list[dict[str, Any]]]):
        self._script = list(script)
        self._i = 0

    def create(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        if self._i >= len(self._script):
            raise RuntimeError("MockLLM script exhausted")
        content = self._script[self._i]
        self._i += 1
        stop = "tool_use" if any(b.get("type") == "tool_use" for b in content) else "end_turn"
        return LLMResponse(stop_reason=stop, content=content)
