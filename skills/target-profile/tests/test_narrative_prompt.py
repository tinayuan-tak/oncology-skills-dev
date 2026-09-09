"""Tier-3 synthesis prompt — per-verdict narrative block + citation instruction.

Asserts _render_narrative_block emits the movers/dissenters/flip anchors, that _build_user_prompt
includes it, and that the tool schema requests inline [rule_id]/[card_id] citations while keeping
`citations` OPTIONAL (so the deterministic skip-stub / salvage path is unaffected).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = Path(__file__).resolve().parents[2]  # .../skills — for `_skills_common`
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tp_synthesis_prompt as tp  # noqa: E402

_NBA = {
    "safety": {
        "verdict": "highly_constrained_safety_concern",
        "driving_rule_id": "highly-constrained-safety-warning",
        "movers": [
            {"rule_id": "highly-constrained-safety-warning", "card_id": "gnomad-lof-constraint", "role": "driver"}
        ],
        "dissenters": [
            {
                "rule_id": "clingen-recessive-only-safety-reassurance",
                "channel": "small_molecule",
                "sentence": "Recessive-only reassurance.",
            },
            {
                "rule_id": "clingen-recessive-only-safety-reassurance",
                "channel": "degrader",
                "sentence": "Recessive-only reassurance.",
            },
        ],
        "flip_conditions": [
            {
                "rule_id": "highly-constrained-safety-warning",
                "present": True,
                "to_verdict": "insufficient",
                "recommendation_flip": True,
            }
        ],
        "gaps": [{"kind": "strengthen", "availability": "insufficient", "missing_cards": []}],
    }
}


def test_narrative_block_renders_anchors_and_dissent():
    blk = "\n".join(tp._render_narrative_block(_NBA))
    assert "Per-verdict narrative" in blk
    assert "[highly-constrained-safety-warning]" in blk  # driver anchor
    assert "DESPITE (dissent on small_molecule, degrader)" in blk  # deduped channels
    assert "crosses GO/NO-GO" in blk  # recommendation flip flag
    assert "GAP (strengthen" in blk


def test_empty_narrative_renders_nothing():
    assert tp._render_narrative_block(None) == []
    assert tp._render_narrative_block({}) == []


def test_user_prompt_includes_narrative_block():
    sr = {
        "safety": {
            "skill_dir": "safety",
            "fired": [],
            "verdict": ("highly_constrained_safety_concern", "highly-constrained-safety-warning"),
            "cards": [],
        }
    }
    up = tp._build_user_prompt("BRAF", "COADREAD", sr, narrative_by_axis=_NBA)
    assert "Per-verdict narrative" in up and "CITE" in up


_RECONCILER_CFG = [
    {
        "reconciles": {"sub_skill": "selectivity", "verdict": "selective_but_broadly_normal"},
        "when_present": [{"sub_skill": "surface_modality", "verdict": "adc_preferred_tce_unsafe"}],
    }
]


def test_reconciled_block_names_trigger_and_directs_not_to_veto(monkeypatch):
    """The prompt must tell the LLM which contradictions the gate RECONCILED (so it stops calling a
    reconciled axis decisive — the ERBB3/LUAD 'selectivity veto owns the call' failure). Names the
    reconciling co-present axis; empty when nothing reconciles."""
    import tp_gates as tpg

    monkeypatch.setattr(tpg, "_load_contradiction_reconcilers", lambda *a, **k: _RECONCILER_CFG)
    sr = {
        "selectivity": {
            "verdict": ("selective_but_broadly_normal", "tvn-no-therapeutic-window-veto"),
            "skill_dir": "tumor-selectivity",
            "cards": [],
            "fired": [],
        },
        "surface_modality": {
            "verdict": ("adc_preferred_tce_unsafe", "adc-fit"),
            "skill_dir": "surface-modality-fit",
            "cards": [],
            "fired": [],
        },
    }
    block = "\n".join(tp._render_reconciled_block(sr))
    assert "Reconciled contradictions" in block and "do NOT" in block
    assert "selectivity" in block and "surface_modality:adc_preferred_tce_unsafe" in block
    # and it is wired into the assembled prompt
    assert "Reconciled contradictions" in tp._build_user_prompt("ERBB3", "LUAD", sr)
    # nothing reconciled → no block (fail-closed / clean-selectivity)
    assert tp._render_reconciled_block({"selectivity": {"verdict": ("strong_tumor_selective", "r")}}) == []


def test_narrative_block_surfaces_reconciled_contradiction():
    """A per-axis entry stamped reconciled_contradiction renders the RECONCILED note in the trace."""
    nba = {
        "selectivity": {
            "verdict": "selective_but_broadly_normal",
            "driving_rule_id": "tvn-no-therapeutic-window-veto",
            "reconciled_contradiction": True,
            "movers": [],
            "dissenters": [],
            "flip_conditions": [],
        }
    }
    block = "\n".join(tp._render_narrative_block(nba))
    assert "RECONCILED (cross-axis)" in block and "do NOT read it as opposing" in block
    # absent the stamp, no note
    nba["selectivity"].pop("reconciled_contradiction")
    assert "RECONCILED (cross-axis)" not in "\n".join(tp._render_narrative_block(nba))


def test_tool_schema_requests_citations_but_keeps_them_optional():
    tool = tp._build_synthesis_tool()
    props, req = tool["properties"], tool["required"]
    assert "citations" in props and "citations" not in req  # optional — skip-stub safe
    assert "[rule_id]" in props["executive_summary"]["description"]
    assert "[brackets]" in props["tension_analysis"]["description"]
    # the audit-critical enums are unchanged
    assert props["overall_recommendation"]["enum"] == ["nominate", "hold", "veto", "insufficient_evidence"]


def test_measurement_applicability_caveat_dependency_under_sampling():
    """Class-B caveat: a pooled non_dependent read + a co-present genomic DRIVER → a verdict-INERT
    'measurement-scope' caveat (KIT/GIST, ABL1 pattern), so the LLM does not read the pooled negative as a
    target-negative. Silent when there's no driver context (a real negative) or the target IS dependent."""
    fires = {
        "dependency": {"verdict": ("non_dependent", "r")},
        "genomic_alteration": {"verdict": ("multi_class_driver", "r")},
    }
    block = "\n".join(tp._render_measurement_applicability_block(fires))
    assert "Measurement-applicability caveat" in block and "do NOT read as a target-negative" in block
    assert "non_dependent" in block and "multi_class_driver" in block
    # no driver context (missense-only) → a real negative, no caveat
    assert (
        tp._render_measurement_applicability_block(
            {
                "dependency": {"verdict": ("non_dependent", "r")},
                "genomic_alteration": {"verdict": ("missense_dominant_pattern", "r")},
            }
        )
        == []
    )
    # a DEPENDENT target → no caveat
    assert (
        tp._render_measurement_applicability_block(
            {
                "dependency": {"verdict": ("concordant_dependent", "r")},
                "genomic_alteration": {"verdict": ("confirmed_driver", "r")},
            }
        )
        == []
    )
