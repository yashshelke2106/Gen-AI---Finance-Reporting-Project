"""JSON-schema normalization for provider tool declarations.

Anthropic accepts standard JSON Schema (with ``$ref``/``$defs``) directly, but
Gemini's ``FunctionDeclaration`` does not resolve references and rejects several
keywords Pydantic emits. ``flatten_schema`` inlines all ``$ref`` targets,
collapses ``anyOf: [T, null]`` into ``T`` + ``nullable``, and strips unsupported
keys so the schema is safe to hand to Gemini.
"""
from __future__ import annotations

from typing import Any

# Keys Gemini's schema validator does not accept.
_STRIP_KEYS = {"title", "default", "$defs", "additionalProperties", "$schema"}


def flatten_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `schema` with refs inlined and Gemini-safe keys only."""
    defs = schema.get("$defs", {})
    return _resolve(schema, defs)


def _resolve(node: Any, defs: dict[str, Any]) -> Any:
    if not isinstance(node, dict):
        return node

    # Inline a $ref, merging any sibling keys (e.g. description) on top.
    if "$ref" in node:
        name = node["$ref"].split("/")[-1]
        resolved = _resolve(dict(defs.get(name, {})), defs)
        for k, v in node.items():
            if k != "$ref":
                resolved[k] = v
        return _clean(resolved, defs)

    node = dict(node)

    # Collapse Optional -> single type + nullable.
    if "anyOf" in node:
        variants = [_resolve(v, defs) for v in node["anyOf"]]
        non_null = [v for v in variants if v.get("type") != "null"]
        has_null = any(v.get("type") == "null" for v in variants)
        if len(non_null) == 1:
            base = non_null[0]
            if has_null:
                base["nullable"] = True
            for k, v in node.items():
                if k != "anyOf":
                    base.setdefault(k, v)
            return _clean(base, defs)
        node["anyOf"] = non_null
        if has_null:
            node["nullable"] = True

    return _clean(node, defs)


def _clean(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in node.items():
        if k in _STRIP_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _resolve(pv, defs) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _resolve(v, defs)
        elif k == "anyOf" and isinstance(v, list):
            out[k] = [_resolve(x, defs) for x in v]
        else:
            out[k] = v
    return out
