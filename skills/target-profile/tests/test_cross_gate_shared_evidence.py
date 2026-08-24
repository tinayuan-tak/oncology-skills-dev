"""Cross-gate shared-evidence facet (VERDICT_REPRESENTATION.md — de-dup cross-gate cards). Verdict-inert:
surfaces input cards that drive >1 gate's fired signal, so a roll-up doesn't count correlated gate
verdicts as independent corroboration."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = Path(__file__).resolve().parents[2]          # for `_skills_common` (tp_facets imports it)
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from tp_facets import _cross_gate_shared_evidence  # noqa: E402


def _sr(**by_short):
    """sub_results from {short: [card_id, ...]} (the cards its fired rules read)."""
    return {short: {"fired": [{"rule_id": f"r-{c}", "card_id": c} for c in cards]}
            for short, cards in by_short.items()}


def test_shared_card_flags_correlated_gates():
    sr = _sr(safety=["normal-tissue-liability", "gnomad-lof-constraint"],
             surface_modality=["normal-tissue-liability", "adc-tce-modality-fit"],
             dependency=["pan-cancer-crispr-dependency-distribution"])
    out = _cross_gate_shared_evidence(sr)
    # normal-tissue-liability drives safety AND surface -> shared, correlated
    assert out["shared_input_cards"]["normal-tissue-liability"] == ["safety", "surface_modality"]
    assert ["safety", "surface_modality"] in out["correlated_gate_pairs"]
    # a card in only one gate is NOT shared
    assert "gnomad-lof-constraint" not in out["shared_input_cards"]
    assert "pan-cancer-crispr-dependency-distribution" not in out["shared_input_cards"]


def test_no_shared_evidence_is_empty():
    sr = _sr(safety=["gnomad-lof-constraint"], dependency=["pan-cancer-crispr-dependency-distribution"])
    out = _cross_gate_shared_evidence(sr)
    assert out["shared_input_cards"] == {}
    assert out["correlated_gate_pairs"] == []


def test_robust_to_missing_fired_and_card_id():
    sr = {"safety": {"verdict": ("x", "y")}, "dependency": {"fired": [{"rule_id": "r"}]}, "x": "malformed"}
    assert _cross_gate_shared_evidence(sr)["shared_input_cards"] == {}   # no crash, no card_ids
