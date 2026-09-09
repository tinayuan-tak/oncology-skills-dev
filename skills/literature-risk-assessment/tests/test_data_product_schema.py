"""Emitted data-product contract guard for literature-risk-assessment (BESPOKE aux skill).

literature-risk-assessment is NOT a fan-out skill: it writes `risk_assessment.json`, not the
`skill_decision` envelope — there is NO run_health / headline.skill_report, `tier` is the literal
string "context" (never a gate/verdict input), and `provenance.citable_in_nominations` is false by
design. So the conformance target is the HAND-AUTHORED bespoke schema
`target-contracts/schemas/skills/literature-risk-assessment.emit.schema.json` (loaded with
suffix="emit"), and we assert the bespoke identity INLINE — `is_full_decision` does not apply.

REAL emit, no Bedrock / no network: this is an LLM skill, but `run()` assembles the dict through the
real emitter code (containment guard + confabulation downgrade + provenance) with only its two external
I/O boundaries replaced by frozen responses — literature retrieval (`retrieval_lanes.retrieve_axis_abstracts`,
imported into run.py as `rc.rl`) and the per-dimension model call (`synthesize_structured`). This is the
sanctioned offline-replay path, not a hand-faked JSON:
the assertions run against whatever `run()` actually produces. CI-liveness: schema unresolvable → SKIP
locally, FAIL in CI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SKILL = "literature-risk-assessment"
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from _skills_common.data_product_contract import (  # noqa: E402
    conformance_errors,
    load_schema,
    schema_path,
)
from _test_support import load_run_py  # noqa: E402

rc = load_run_py(SKILL_DIR, "lra_run_dp")

# The fixed six risk pillars — the bespoke identity the schema locks (dict-of-objects keyset).
SIX_DIMENSIONS = {"biological", "druggability", "translational", "clinical", "safety", "commercial"}


def _schema_or_gate() -> dict:
    schema = load_schema(SKILL, "emit")
    if schema is not None:
        return schema
    reason = (
        f"data-product emit schema not found at {schema_path(SKILL, 'emit')} — set "
        f"TARGET_CONTRACTS_ROOT / land the contracts schema PR first"
    )
    if os.environ.get("CI"):
        pytest.fail(reason + " [CI: the data-product lock must be live, not skipped]")
    pytest.skip(reason)


class _Ab:
    """Minimal stand-in for a pubmed_search abstract record (pmid/year/title/abstract)."""

    def __init__(self, pmid):
        self.pmid, self.year, self.title, self.abstract = pmid, 2021, f"title-{pmid}", f"abstract body {pmid}"


# Frozen per-dimension model responses. Cover every schema-relevant path:
#   biological  — kept LOW grade with a surviving (retrieved) citation
#   druggability— kept MEDIUM grade with a surviving citation
#   safety      — HIGH graded on a CONFABULATED cite only → downgrade path
#                 (risk_level_pre_containment + downgraded_reason)
#   translational/clinical/commercial — no abstracts retrieved → not_assessed (no model call)
_FROZEN_LLM = {
    "biological": {
        "risk_level": "LOW",
        "justification": "well-supported disease linkage.",
        "interpretation": "target is genetically implicated in the indication.",
        "cited_pmids": ["111"],
        "contradicts_deterministic": False,
    },
    "druggability": {
        "risk_level": "MEDIUM",
        "justification": "tool compounds exist but selectivity is unclear.",
        "interpretation": "chemical matter reported; developability partially characterized.",
        "cited_pmids": ["333"],
        "contradicts_deterministic": False,
    },
    "safety": {
        "risk_level": "HIGH",
        "justification": "normal-tissue liability reported.",
        "interpretation": "on-target normal-tissue expression raises a safety concern.",
        "cited_pmids": ["999"],
        "contradicts_deterministic": True,
    },  # 999 not retrieved → confabulated
}


def _fresh_emit(monkeypatch) -> dict:
    """Produce a REAL emit through run() with the retrieval + LLM boundaries replaced by frozen responses.

    Retrieval is now the shared per-axis seam retrieval_lanes.retrieve_axis_abstracts (imported into run.py
    as rc.rl) — one function to patch, returning the frozen abstract list per dimension (empty for the three
    dims that exercise the no-abstract → not_assessed path)."""
    retrieved = {"biological": [_Ab("111"), _Ab("222")], "druggability": [_Ab("333")], "safety": [_Ab("444")]}
    monkeypatch.setattr(rc.rl, "retrieve_axis_abstracts", lambda target, indication, axis, **k: retrieved.get(axis, []))
    # non-null anchor_verdict for the overlap dimensions (biological/druggability/safety)
    monkeypatch.setattr(
        rc,
        "_load_anchors",
        lambda pkg: {"dependency": "likely_dependency", "tractability_sm": "tractable", "safety": "tolerable"},
    )

    def _fake_synth(system, prompt, name, schema):
        for dim, resp in _FROZEN_LLM.items():
            if prompt.startswith(f"DIMENSION: {dim} "):
                return resp
        raise AssertionError(f"unexpected synthesize_structured call for prompt: {prompt[:60]!r}")

    monkeypatch.setattr(rc, "synthesize_structured", _fake_synth)
    return rc.run("FOLR1", "ovarian cancer", None, "2015", "2026", per_cat=6)


def test_schema_is_wellformed():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("version"), "data-product schema must carry a contract `version`"


def test_emit_is_bespoke_context_shape(monkeypatch):
    """Bespoke identity, asserted inline (NOT is_full_decision): tier is the literal 'context', the six
    fixed risk pillars are the dimensions keyset, and provenance never cites into nominations."""
    decision = _fresh_emit(monkeypatch)
    assert decision["tier"] == "context"
    assert set(decision["dimensions"]) == SIX_DIMENSIONS
    assert decision["provenance"]["citable_in_nominations"] is False
    # NOT the fan-out envelope — no run_health / headline
    assert "run_health" not in decision and "headline" not in decision
    # the confabulation-containment downgrade path is exercised (safety: HIGH cited only a confabulated PMID)
    safety = decision["dimensions"]["safety"]
    assert safety["risk_level"] == "not_assessed" and safety["risk_level_pre_containment"] == "HIGH"
    assert safety["confabulated_dropped"] == ["999"] and safety["cited_pmids"] == []


def test_emit_conforms_to_schema(monkeypatch):
    """The REAL emit validates against the hand-authored bespoke emit schema (CI-fail-not-skip)."""
    schema = _schema_or_gate()
    decision = _fresh_emit(monkeypatch)
    errors = conformance_errors(schema, decision)
    assert not errors, "emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )
