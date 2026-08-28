"""The cross-evidence agent consumes the evidence-capsule DATA layer (retrieve-don't-recall: it may cite
only what is in its input). _render_capsule_data surfaces the on-indication stratum, cross-source
conflicts, and data-quality flags the claim-vector atoms don't carry. Deterministic; no Bedrock."""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run as CE  # noqa: E402


def _caps():
    return {"functional-requirement": {"capsules": {
        "dependency-lineage-selectivity": {"card_id": "dependency-lineage-selectivity", "evidence_state": "measured",
            "top_k_strata": [{"role": "INDICATION", "stratum": "COADREAD", "value": -1.28, "n": 19},
                             {"role": "extreme_weakest", "stratum": "LXSC", "value": -0.2, "n": 7}]},
        "crispr-rnai-dependency-concordance": {"card_id": "crispr-rnai-dependency-concordance", "evidence_state": "measured",
            "conflict_pairs": [{"measurement_type": "crispr_rnai_concordance",
                                "other_sources": [{"card": "pan-cancer-crispr-dependency-distribution"}]}]},
        "genomic-event-model-match": {"card_id": "genomic-event-model-match", "evidence_state": "measured",
            "data_quality_flags": [{"field": "patient_functional_state_class",
                                    "flag": "activating-direction card carries a loss-of-function state label — do NOT narrate as LoF"}]},
        "empty-card": {"card_id": "empty-card", "evidence_state": "data_unavailable"},
    }}}


def test_renders_indication_conflict_and_dq_only():
    out = CE._render_capsule_data(_caps())
    assert "evidence-capsule DATA" in out and "card-floor complete" in out
    assert "indication_stratum COADREAD=-1.28(n=19)" in out          # on-indication stratum surfaced
    assert "CONFLICT(mt=crispr_rnai_concordance" in out               # cross-source conflict surfaced
    assert "DATA_QUALITY:" in out and "loss-of-function" in out       # DQ flag surfaced
    assert "extreme_weakest" not in out                               # salience-gated: only the indication row
    assert "empty-card" not in out                                    # data_unavailable card skipped from data block


def test_renders_categorical_anchors_for_clinical_cards():
    caps = {"differentiation": {"capsules": {
        "clinical-precedent": {"card_id": "clinical-precedent", "evidence_state": "measured",
            "categorical_anchors": [{"field": "highest_clinical_stage", "value": "approved"},
                                    {"field": "approved_agents", "value": ["adagrasib", "sotorasib"]}]},
        "competitor-landscape": {"card_id": "competitor-landscape", "evidence_state": "measured",
            "categorical_anchors": [{"field": "n_approved", "value": 0},
                                    {"field": "highest_clinical_stage", "value": "PHASE_3"}]},
    }}}
    out = CE._render_capsule_data(caps)
    assert "highest_clinical_stage=approved" in out                  # clinical stage now a citable token
    assert "approved_agents=['adagrasib', 'sotorasib']" in out       # actual competitor drug names
    assert "n_approved=0" in out                                     # indication-approval count surfaced


def test_empty_is_byte_stable_noop():
    assert CE._render_capsule_data({}) == ""
    assert CE._render_capsule_data(None) == ""
    assert CE._render_capsule_data({"x": {"capsules": {}}}) == ""     # no rows → no block
