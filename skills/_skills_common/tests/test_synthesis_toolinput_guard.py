"""Guard against the malformed-tool-use failure mode in synthesize_structured.

Regression for the 2026-08-24 finding: the synthesis model intermittently lapses out of
native JSON tool-use into the XML `<parameter name="...">` dialect, so the first array/string
field's value swallows subsequent fields as raw markup (12/25 target-profile runs had a
corrupted `top_arguments_for` + a dropped `top_arguments_against`). The guard detects such
defects against the tool schema, retries the call, and — if still malformed — salvages the
defective fields to schema-valid empties with a visible `_malformed_fields` record instead of
shipping leaked markup into the evidence package.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common import llm as LLM  # noqa: E402


_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "top_arguments_for": {"type": "array", "items": {"type": "string"}},
        "top_arguments_against": {"type": "array", "items": {"type": "string"}},
        "overall_recommendation": {"type": "string"},
    },
    "required": ["executive_summary", "overall_recommendation"],
}

# The exact corruption shape observed in the DLL3/SCLC run.
_MALFORMED = {
    "executive_summary": "DLL3 is a surface Notch ligand.",
    "top_arguments_for": '\n<parameter name="top_arguments_against">\n<parameter name="overall_recommendation">hold',
    "overall_recommendation": "hold",
}
_CLEAN = {
    "executive_summary": "DLL3 is a surface Notch ligand.",
    "top_arguments_for": ["approved TCE (tarlatamab)", "strong tumor selectivity"],
    "top_arguments_against": ["forebrain-neuron liability", "sub-threshold surface density"],
    "overall_recommendation": "hold",
}


# ---- pure helpers (no Bedrock) -------------------------------------------------

def test_leak_marker_detection():
    assert LLM._leaks_toolcall_markup('x <parameter name="y">')
    assert LLM._leaks_toolcall_markup("</parameter>")
    assert not LLM._leaks_toolcall_markup("a normal argument string")


def test_defects_flags_array_arrived_as_string_and_dropped_field():
    defects = LLM._tool_input_defects(_MALFORMED, _SCHEMA)
    # top_arguments_for: declared array, arrived as a string carrying leaked markup.
    assert "top_arguments_for" in defects
    # top_arguments_against: required? no — but it is absent; not required so NOT a defect here.
    assert "top_arguments_against" not in defects  # absent + optional


_ENUM_SCHEMA = {
    "type": "object",
    "properties": {
        "risk_level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "not_assessed"]},
        "grade": {"type": "string", "enum": ["strong", "moderate", "weak"]},  # no null-ish member
        "justification": {"type": "string"},
    },
    "required": ["risk_level", "justification"],
}


def test_defects_flags_off_enum_value():
    # an off-enum categorical is a defect (was silently stored verbatim before)
    defects = LLM._tool_input_defects(
        {"risk_level": "moderate-high", "justification": "j"}, _ENUM_SCHEMA)
    assert "risk_level" in defects


def test_valid_enum_value_is_not_a_defect():
    assert LLM._tool_input_defects(
        {"risk_level": "not_assessed", "justification": "j"}, _ENUM_SCHEMA) == []


def test_salvage_enum_prefers_nullish_member():
    payload = {"risk_level": "moderate-high", "justification": "j"}
    defects = LLM._tool_input_defects(payload, _ENUM_SCHEMA)
    out = LLM._salvage_tool_input(payload, _ENUM_SCHEMA, defects)
    # honest abstention, and schema-VALID (in the enum) — not "" which is off-enum
    assert out["risk_level"] == "not_assessed"
    assert out["risk_level"] in _ENUM_SCHEMA["properties"]["risk_level"]["enum"]
    assert "risk_level" in out["_malformed_fields"]


def test_salvage_enum_without_nullish_uses_first_member():
    payload = {"risk_level": "not_assessed", "grade": "bogus", "justification": "j"}
    defects = LLM._tool_input_defects(payload, _ENUM_SCHEMA)
    out = LLM._salvage_tool_input(payload, _ENUM_SCHEMA, defects)
    assert out["grade"] == "strong"   # no null-ish member → first declared, still schema-valid


def test_defects_flags_missing_required():
    payload = {"top_arguments_for": ["ok"]}  # missing both required fields
    defects = LLM._tool_input_defects(payload, _SCHEMA)
    assert "executive_summary" in defects and "overall_recommendation" in defects


def test_clean_payload_has_no_defects():
    assert LLM._tool_input_defects(_CLEAN, _SCHEMA) == []


def test_salvage_coerces_to_schema_empties_and_records():
    payload = dict(_MALFORMED)
    defects = LLM._tool_input_defects(payload, _SCHEMA)
    out = LLM._salvage_tool_input(payload, _SCHEMA, defects)
    assert out["top_arguments_for"] == []            # array defect -> []
    assert out["_malformed_fields"] == defects
    # No leaked markup survives anywhere in the salvaged payload.
    for v in out.values():
        assert not (isinstance(v, str) and LLM._leaks_toolcall_markup(v))


# ---- retry / salvage loop (mocked Bedrock client) ------------------------------

def _fake_response(tool_input: dict):
    block = SimpleNamespace(type="tool_use", input=tool_input)
    return SimpleNamespace(content=[block], stop_reason="tool_use")


def _run_with_sequence(input_sequence, max_retries=2):
    """Invoke synthesize_structured with a fake client whose messages.create yields
    the given tool_input dicts in order."""
    responses = [_fake_response(i) for i in input_sequence]
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kw: responses.pop(0))
    )
    fake_cfg = SimpleNamespace(synthesis_model="test-model")
    ModelConfig = SimpleNamespace(from_env=staticmethod(lambda: fake_cfg))
    with patch.object(LLM, "_import_bedrock_client",
                      return_value=(lambda: fake_client, ModelConfig, RuntimeError)), \
         patch.object(LLM, "_bedrock_profile"):
        return LLM.synthesize_structured(
            system_prompt="s", user_prompt="u", tool_name="t",
            tool_schema=_SCHEMA, max_retries=max_retries,
        )


def test_retry_recovers_clean_output():
    out = _run_with_sequence([_MALFORMED, _CLEAN])
    assert out["top_arguments_for"]["value"] == _CLEAN["top_arguments_for"]
    assert out["top_arguments_against"]["value"] == _CLEAN["top_arguments_against"]
    assert "_malformed_fields" not in out


def test_persistent_malformation_is_salvaged_not_shipped():
    out = _run_with_sequence([_MALFORMED, _MALFORMED, _MALFORMED])  # never recovers
    # top_arguments_for salvaged to [] (wrapped by provenance stamping into {"value": []}).
    assert out["top_arguments_for"]["value"] == []
    # _malformed_fields is framework meta — passed through untagged (a bare list).
    assert "top_arguments_for" in out["_malformed_fields"]
    # The garbage string never reaches the package.
    tv = out["top_arguments_for"]["value"]
    assert not (isinstance(tv, str) and LLM._leaks_toolcall_markup(tv))


# ---- XML-dialect RECOVERY (parse leaked <parameter> blocks, don't discard) --------------
# A realistic corruption: the first array field's value carries its OWN JSON-array content,
# then swallows the subsequent parameters as closed <parameter name="X">...</parameter> blocks;
# top_arguments_against + overall_recommendation drop to absent. Unlike the degenerate _MALFORMED
# above (empty inner values), this carries recoverable content.
_MALFORMED_RICH = {
    "executive_summary": "DLL3 is a surface Notch ligand; an approved TCE target in SCLC.",
    "top_arguments_for": (
        '["approved TCE (tarlatamab)", "strong tumor selectivity"]\n'
        '<parameter name="top_arguments_against">'
        '["forebrain-neuron liability", "sub-threshold surface density"]</parameter>\n'
        '<parameter name="overall_recommendation">hold</parameter>'
    ),
    # top_arguments_against + overall_recommendation swallowed (absent from payload)
}


def test_recover_extracts_swallowed_fields():
    payload = dict(_MALFORMED_RICH)
    defects = LLM._tool_input_defects(payload, _SCHEMA)
    assert "top_arguments_for" in defects and "overall_recommendation" in defects
    out = LLM._recover_leaked_toolcall(payload, _SCHEMA, defects)
    # swallower field's OWN content recovered + coerced to a list
    assert out["top_arguments_for"] == ["approved TCE (tarlatamab)", "strong tumor selectivity"]
    # swallowed fields recovered
    assert out["top_arguments_against"] == ["forebrain-neuron liability", "sub-threshold surface density"]
    assert out["overall_recommendation"] == "hold"
    assert set(out["_recovered_fields"]) == {"top_arguments_for", "top_arguments_against", "overall_recommendation"}
    # after recovery there are NO residual defects (nothing to salvage)
    assert LLM._tool_input_defects(out, _SCHEMA) == []
    # and no leaked markup survives anywhere
    def _leaks(v):
        if isinstance(v, str): return LLM._leaks_toolcall_markup(v)
        if isinstance(v, list): return any(isinstance(x, str) and LLM._leaks_toolcall_markup(x) for x in v)
        return False
    assert not any(_leaks(v) for v in out.values())


def test_recover_does_not_clobber_a_clean_field():
    """A field that arrived CLEAN must never be overwritten by a recovered block."""
    payload = {
        "executive_summary": "CLEAN summary — keep me.",
        "top_arguments_for": (
            'x\n<parameter name="executive_summary">WRONG do not use</parameter>\n'
            '<parameter name="overall_recommendation">veto</parameter>'
        ),
    }
    defects = LLM._tool_input_defects(payload, _SCHEMA)
    out = LLM._recover_leaked_toolcall(payload, _SCHEMA, defects)
    assert out["executive_summary"] == "CLEAN summary — keep me."   # not clobbered
    assert out["overall_recommendation"] == "veto"                  # missing required -> recovered


def test_full_loop_recovers_on_persistent_rich_malformation():
    """End-to-end: a model that malforms on EVERY attempt (rich content) is RECOVERED, not
    salvaged-to-empty — the ERBB2/STAD near-deterministic case."""
    out = _run_with_sequence([_MALFORMED_RICH, _MALFORMED_RICH, _MALFORMED_RICH])
    assert out["top_arguments_for"]["value"] == ["approved TCE (tarlatamab)", "strong tumor selectivity"]
    assert out["top_arguments_against"]["value"] == ["forebrain-neuron liability", "sub-threshold surface density"]
    assert out["overall_recommendation"]["value"] == "hold"
    assert "_malformed_fields" not in out          # nothing left to salvage
    assert "top_arguments_for" in out["_recovered_fields"]
