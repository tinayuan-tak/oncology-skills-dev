"""Exon-skip evidence must score the SPL sub-group, never FUS.

`derive_subgroups` builds its `measurement_type -> sub_group` map from the hierarchy's
`questions[].measurement_types` only. While `splice_exon_skip` and `tumor_splice_dysregulation` sat under
FUS (target-contracts `question_hierarchies`, fixed in TC #757), both splice cards were pooled into the
FUSION signal. Measured on two real MET/LUAD runs (`~/dev/framework-runs/genomic-alteration-profile/
MET-LUAD-2026-09-07-audit` and `-2026-09-03-full`), that INVERTED the published FUS band:

    FUS  before: signal='strong'  n=4  [fusion-stratified-dependency, fusion-rearrangement-landscape,
                                       splice-exon-skip-landscape, tumor-splice-dysregulation]
    FUS  after:  signal='absent'  n=2  [fusion-stratified-dependency, fusion-rearrangement-landscape]
    SPL  before: absent from subgroup_signals entirely
    SPL  after:  signal='strong'  n=1  [splice-exon-skip-landscape]

MET is not a recurrent fusion driver in LUAD; the strong fusion band was `splice_exon_skip_class:
recurrent_splice_driver` being read as fusion evidence. `tumor-splice-dysregulation` was counted as a
fusion source too, despite its own summary saying "PATIENT alternative-splicing, verdict-inert".

The skill's pre-existing `kras_coadread_decision.json` fixture could not catch this: KRAS/COADREAD has no
splice signal, so both splice cards carry an EMPTY summary there and contribute to no sub-group under
either routing. The summaries below are therefore taken verbatim from the MET/LUAD audit run — a live
producer emission, not an invented shape.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL.parent))
sys.path.insert(0, str(SKILL / "scripts"))

import run as genomic_run  # noqa: E402  (the skill's own tuned value->tier map)
from _skills_common.subgroup_derivation import derive_subgroups, make_value_classifier  # noqa: E402

# --- MET/LUAD, verbatim from the 2026-09-07 audit run ------------------------------------------------
_CARDS = [
    {
        "card_id": "fusion-rearrangement-landscape",
        "summary": {
            "_data_source": "tcga-fusion-consensus-v1",
            "fusion_class": "recurrent_fusion_driver",
            "fusion_frequency": 0.004746835443037975,
            "fusion_recurrence_confidence": "moderate_promiscuous",
            "genie_sv_recurrence_class": "data_unavailable",
            "n_assayed_in_tissue": 632,
            "n_samples_with_fusion": 3,
        },
    },
    {
        "card_id": "fusion-stratified-dependency",
        "summary": {
            "fusion_stratification_class": "not_fusion_stratified",
            "n_cell_lines_evaluated": 1464,
            "n_fusion_positive": 24,
        },
    },
    {
        "card_id": "splice-exon-skip-landscape",
        "summary": {
            "driver_direction": "activating",
            "event_id": "METex14",
            "n_depmap_carriers": 3,
            "splice_exon_skip_class": "recurrent_splice_driver",
        },
    },
    {
        "card_id": "tumor-splice-dysregulation",
        "summary": {
            "_data_source": "tcga-spliceseq",
            "n_splice_events": 3,
            "n_tumor_samples": 517,
            "splicing_dysregulation_class": "stable",
        },
    },
]

_CLASSIFY = make_value_classifier(genomic_run._GENOMIC_VALUE_TIERS)


def _hierarchy() -> dict:
    return yaml.safe_load((SKILL / "question_hierarchy.yaml").read_text())


def _recollapsed(h: dict) -> dict:
    """The pre-TC#757 routing: no SPL sub-group, both splice types scored under FUS."""
    old = copy.deepcopy(h)
    old["sub_groups"] = [sg for sg in old["sub_groups"] if sg["id"] != "SPL"]
    for sg in old["sub_groups"]:
        if sg["id"] == "FUS":
            sg["questions"][0]["measurement_types"] += ["splice_exon_skip", "tumor_splice_dysregulation"]
    return old


def _signals(h: dict) -> dict:
    return derive_subgroups(h, _CARDS, None, _CLASSIFY)


def test_the_fixture_actually_reaches_the_splice_cards():
    """Anti-vacuity, and the reason this file exists. If the splice cards do not become SOURCES of any
    sub-group, every assertion below is decoration — which is exactly the state the skill's KRAS/COADREAD
    fixture is in, because its splice summaries are empty."""
    srcs = {s["card"] for d in _signals(_hierarchy()).values() for s in d.get("sources", [])}
    assert "splice-exon-skip-landscape" in srcs, (
        "the exon-skip card is not a scored source at all — this fixture cannot detect a mis-routing"
    )


def test_exon_skip_scores_spl_and_not_fus():
    sg = _signals(_hierarchy())
    assert [s["card"] for s in sg["SPL"]["sources"]] == ["splice-exon-skip-landscape"]
    assert sg["SPL"]["signal"] == "strong"  # METex14 is a curated activating exon-skipping driver
    fus_srcs = {s["card"] for s in sg["FUS"]["sources"]}
    assert fus_srcs == {"fusion-rearrangement-landscape", "fusion-stratified-dependency"}


def test_the_fusion_band_is_not_lifted_by_splice_evidence():
    """The measured defect, stated as the published value it corrupted. MET carries no recurrent fusion in
    LUAD, so FUS must not read `strong`; it did, on both real runs, because exon-skip drove it."""
    assert _signals(_hierarchy())["FUS"]["signal"] == "absent"
    assert _signals(_recollapsed(_hierarchy()))["FUS"]["signal"] == "strong"


def test_splice_dysregulation_is_never_a_scored_source():
    """It is an SPL `context_type`: on-axis, deliberately off-signal. Its own summary calls itself
    "PATIENT alternative-splicing, verdict-inert", and it was a FUS source regardless."""
    sg = _signals(_hierarchy())
    scored = {s["card"] for d in sg.values() for s in d.get("sources", [])}
    assert "tumor-splice-dysregulation" not in scored
    # ... and it WAS one before the split, so this assertion is load-bearing.
    old = {s["card"] for d in _signals(_recollapsed(_hierarchy())).values() for s in d.get("sources", [])}
    assert "tumor-splice-dysregulation" in old
