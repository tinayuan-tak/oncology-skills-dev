"""Default heuristic reader + subgroup_signals_for — so fleet wiring needs no per-skill reader spec.
The heuristic picks the primary signal field (*_class, else signal-keyword string) + n fields; the
convenience helper loads a skill's question_hierarchy.yaml and derives pooled + stratified in one call."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.subgroup_derivation import _heuristic_reader, subgroup_signals_for  # noqa: E402


def _contracts_absent():
    root = Path(os.environ.get("TARGET_CONTRACTS_ROOT",
                               "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
    return not (root / "cards").is_dir()


def test_heuristic_picks_class_field():
    r = _heuristic_reader({"tumor_expression_class": "broadly_high", "n_tumor_samples": 669, "median_log2tpm": 9.6})
    assert r["class"] == "tumor_expression_class" and "n_tumor_samples" in r["n"]


def test_heuristic_picks_keyword_field_when_no_class():
    # concordance card's signal field has no _class suffix — caught by the signal-keyword fallback
    r = _heuristic_reader({"rna_as_biomarker": "adequate_proxy", "n_paired_models": 370})
    assert r["class"] == "rna_as_biomarker" and "n_paired_models" in r["n"]


def test_heuristic_none_when_no_signal_field():
    assert _heuristic_reader({"method_version": "1.0", "target": "X"}) is None


@pytest.mark.skipif(_contracts_absent(), reason="target-contracts absent")
def test_signals_for_derives_reader_spec_free():
    """subgroup_signals_for on presence's hierarchy + EPCAM cards, WITHOUT an explicit reader spec
    (pure heuristic) — proves fleet wiring is reader-spec-free."""
    fix = SKILLS / "tumor-presence/tests/fixtures/epcam_coadread.yaml"
    frozen = yaml.safe_load(fix.read_text()) or {}
    cards = [{"card_id": k, "summary": v} for k, v in frozen.items() if isinstance(v, dict)]
    sg = subgroup_signals_for(SKILLS / "tumor-presence", cards)   # no reader_spec => heuristic
    assert set(sg) >= {"abundance", "malignant_intrinsic", "generality"}, f"got {set(sg)}"
    assert sg["abundance"]["signal"] == "strong"
    assert any(s["card"] == "cellline-protein-abundance-procan" for s in sg["abundance"]["sources"])
