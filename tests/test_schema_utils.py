import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earnings_analyst.schema_utils import flatten_schema  # noqa: E402
from earnings_analyst.schemas import AnalystBrief  # noqa: E402


def _walk(node, seen_keys):
    if isinstance(node, dict):
        seen_keys.update(node.keys())
        for v in node.values():
            _walk(v, seen_keys)
    elif isinstance(node, list):
        for v in node:
            _walk(v, seen_keys)


def test_flatten_removes_refs_and_defs():
    schema = AnalystBrief.model_json_schema()
    assert "$defs" in schema  # precondition: nested models exist
    flat = flatten_schema(schema)
    keys: set[str] = set()
    _walk(flat, keys)
    assert "$ref" not in keys
    assert "$defs" not in keys
    assert "title" not in keys
    assert "additionalProperties" not in keys


def test_optional_collapses_to_nullable():
    schema = {
        "type": "object",
        "properties": {
            "ticker": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Ticker"}
        },
    }
    flat = flatten_schema(schema)
    ticker = flat["properties"]["ticker"]
    assert ticker.get("type") == "string"
    assert ticker.get("nullable") is True
    assert "anyOf" not in ticker


def test_enum_ref_is_inlined():
    schema = {
        "$defs": {"Dir": {"enum": ["up", "down"], "type": "string", "title": "Dir"}},
        "type": "object",
        "properties": {"d": {"$ref": "#/$defs/Dir"}},
    }
    flat = flatten_schema(schema)
    assert flat["properties"]["d"]["enum"] == ["up", "down"]
    assert flat["properties"]["d"]["type"] == "string"
