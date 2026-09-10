"""render_layer — the layer-addressable render dial (Stage D). Addresses a single card / question /
datum of a composed target_report and renders just it, reusing build_ir_for_skill + the existing
backends. Additive: existing render_report / render_skill_report paths are untouched (byte-stable).
"""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import pytest  # noqa: E402
from _skills_common.report_render import build_layer_ir, render_layer  # noqa: E402


def _nom():
    """A minimal composed nomination with a card-bearing per-subskill evidence_graph (the shared
    _fixtures don't populate evidence_graph.cards, so we hand-roll the shape the layer dial addresses)."""
    eg = {
        "target": "KRAS",
        "indication": "COADREAD",
        "verdict": {"call": "lineage_selective", "polarity": "supportive"},
        "questions": [
            {"id": "is_dependency", "seq": 1, "text": "Is it a dependency?", "card_ids": ["dep-lineage"]},
            {"id": "is_selective", "seq": 2, "text": "Is it selective?", "card_ids": ["dep-selectivity"]},
        ],
        "cards": [
            {
                "id": "dep-lineage",
                "measurement_type": "crispr_lof_dependency",
                "role": "gating",
                "question_ids": ["is_dependency"],
                "signal": {"polarity": "supportive", "tier": "strong"},
                "class": {"value": "lineage_selective"},
                "chain": {"dataset_ids": ["depmap"], "data": [], "is_driving": True},
                "key_evidence": {
                    "effect": {"metric": "median_chronos", "value": -1.18, "direction": "lower_is_stronger"}
                },
            },
            {
                "id": "dep-selectivity",
                "measurement_type": "crispr_lof_dependency",
                "role": "context",
                "question_ids": ["is_selective"],
                "signal": {"polarity": "supportive", "tier": "moderate"},
                "class": {"value": "selective"},
                "chain": {"dataset_ids": ["depmap"], "data": []},
            },
        ],
    }
    return {
        "target": "KRAS",
        "indication": "COADREAD",
        "target_report": {
            "skill_reports": {
                "dependency": {
                    "call": "lineage_selective",
                    "polarity": "supportive",
                    "role": "gating",
                    "evidence_graph": eg,
                }
            }
        },
    }


def test_render_layer_card_panel():
    nom = _nom()
    for backend in ("text", "html"):
        out = render_layer(nom, card="dep-lineage", backend=backend)
        assert isinstance(out, str) and len(out) > 50
    ir = build_layer_ir(nom, card="dep-lineage")
    assert len(ir.sections) == 1  # one focused section (the owning sub-skill, pruned to the card)


def test_render_layer_question_panel():
    out = render_layer(_nom(), question="is_dependency", backend="text")
    assert isinstance(out, str) and len(out) > 50


def test_render_layer_datum_narrows_to_card():
    # datum addresses a card + a field; renders the owning card panel.
    out = render_layer(_nom(), datum=("dep-lineage", "median_chronos"), backend="text")
    assert isinstance(out, str) and len(out) > 50


def test_render_layer_requires_exactly_one_address():
    nom = _nom()
    with pytest.raises(ValueError):
        build_layer_ir(nom)
    with pytest.raises(ValueError):
        build_layer_ir(nom, card="dep-lineage", question="is_dependency")


def test_render_layer_unknown_address_raises():
    with pytest.raises(ValueError, match="not found"):
        render_layer(_nom(), card="no-such-card-zzz")
