"""Per-alteration-class decomposition (genomic_alteration_by_class).

The genomic_alteration_profile verdict collapses SNV/indel + copy-number + fusion into one multi_class
scalar. `genomic_alteration_by_class` reorganizes the already-computed per-card class fields into a
per-class breakdown (mirroring tumor-presence's presence_verdict_by_modality) so a consumer sees WHICH
class drives. ADDITIVE / verdict-inert — each class's `verdict` is its own primary card call."""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

gap = load_run_py(Path(__file__).resolve().parent.parent, "gap_run_byclass")


def _card(cid, **fields):
    return {"card_id": cid, "summary": dict(fields)}


def test_amplification_driven_class_is_isolated():
    """ERBB2-like: SNV moderate, but the copy-number class carries the amplification-addiction — the
    decomposition must show copy_number's stratified dependency distinctly from the SNV class."""
    cards = [
        _card("mutation-type-counts", mutation_landscape_class="missense_dominant"),
        _card("mutation-hotspot-frequency", driver_recurrence_class="not_recurrent"),
        _card("mutation-stratified-dependency", mutation_stratification_class="mutant_moderately_dependent"),
        _card("copy-number-distribution", copy_number_class="broadly_neutral", patient_copy_number_class="mixed"),
        _card("copy-number-stratified-dependency", cn_stratification_class="amplified_strongly_dependent"),
        _card("amp-expr-stratified-dependency", amp_expr_stratification_class="amplified_overexpressed_strongly_dependent"),
        _card("fusion-rearrangement-landscape", fusion_class="no_recurrent_fusion", genie_sv_recurrence_class="data_unavailable"),
        _card("fusion-stratified-dependency", fusion_stratification_class="not_fusion_stratified"),
    ]
    bc = gap._genomic_alteration_by_class(cards)
    assert set(bc) == {"snv_indel", "copy_number", "fusion", "splice"}
    assert bc["snv_indel"]["verdict"] == "missense_dominant"
    assert bc["snv_indel"]["stratified_dependency_class"] == "mutant_moderately_dependent"
    # the copy-number class isolates the amplification-addiction signal
    assert bc["copy_number"]["stratified_dependency_class"] == "amplified_strongly_dependent"
    assert bc["copy_number"]["amp_expr_dependency_class"] == "amplified_overexpressed_strongly_dependent"
    # every class WITH A CARD in this fixture is measured (splice card not provided → data_unavailable gap)
    assert all(bc[c]["evidence_state"] == "measured" for c in ("snv_indel", "copy_number", "fusion"))
    assert bc["splice"]["evidence_state"] == "data_unavailable"


def test_absent_class_is_named_data_unavailable_not_fabricated():
    """A class whose primary card did not resolve is an explicit data_unavailable gap, never a
    fabricated negative."""
    cards = [_card("mutation-type-counts", mutation_landscape_class="missense_dominant")]
    bc = gap._genomic_alteration_by_class(cards)
    assert bc["snv_indel"]["evidence_state"] == "measured"
    assert bc["copy_number"]["evidence_state"] == "data_unavailable"
    assert bc["copy_number"]["verdict"] in (None, "data_unavailable")
    assert bc["fusion"]["evidence_state"] == "data_unavailable"


def test_verdict_is_card_own_call_not_rederived():
    """Each class verdict is exactly the card's primary field — no re-derivation that could drift."""
    cards = [_card("copy-number-distribution", copy_number_class="focal_amplification")]
    bc = gap._genomic_alteration_by_class(cards)
    assert bc["copy_number"]["verdict"] == "focal_amplification"
