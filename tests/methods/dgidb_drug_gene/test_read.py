"""dgidb_drug_gene.read — hermetic tests (injected DGIdb rows, no S3).

Pins the known_drug_tractability_class precedence (approved hoisted above clinically_actionable),
the coverage-gap default (absent -> no_known_drug_evidence, NOT undruggable), and field passthrough.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.dgidb_drug_gene import read as dgidb  # noqa: E402
from methods.dgidb_drug_gene.read import known_drug_tractability_for_gene  # noqa: E402


def _row(**kw):
    base = {"druggability_tier": "category_only", "is_druggable_genome": False,
            "is_clinically_actionable": False, "has_approved_drug": False,
            "n_drug_interactions": 0, "n_approved_drug_interactions": 0,
            "n_antineoplastic_interactions": 0, "n_categories": 1, "gene_categories": "ENZYME"}
    base.update(kw)
    return base


def test_approved_drug_hoisted_above_clinical():
    # both flags true -> approved wins (the harder pharmacology fact)
    s = known_drug_tractability_for_gene("EGFR", dgidb_row=_row(
        has_approved_drug=True, is_clinically_actionable=True, is_druggable_genome=True,
        n_drug_interactions=549, n_approved_drug_interactions=200, n_antineoplastic_interactions=311,
        gene_categories="CLINICALLY ACTIONABLE|DRUGGABLE GENOME|KINASE"))
    assert s["known_drug_tractability_class"] == "approved_drug_tractable"
    assert s["n_approved_drug_interactions"] == 200
    assert s["has_approved_drug"] is True


def test_clinically_actionable_when_no_approved():
    s = known_drug_tractability_for_gene("KRAS", dgidb_row=_row(
        is_clinically_actionable=True, n_drug_interactions=165, n_antineoplastic_interactions=113))
    assert s["known_drug_tractability_class"] == "clinically_actionable"


def test_druggable_genome_only():
    s = known_drug_tractability_for_gene("CACNA2D4", dgidb_row=_row(
        is_druggable_genome=True, n_drug_interactions=3, gene_categories="DRUGGABLE GENOME|ION CHANNEL"))
    assert s["known_drug_tractability_class"] == "druggable_genome"


def test_interaction_only():
    s = known_drug_tractability_for_gene("X", dgidb_row=_row(n_drug_interactions=2, n_categories=0,
                                                             gene_categories=None))
    assert s["known_drug_tractability_class"] == "interaction_only"


def test_category_only():
    s = known_drug_tractability_for_gene("VPS4A", dgidb_row=_row())  # enzyme category, no drugs
    assert s["known_drug_tractability_class"] == "category_only"


def test_absent_is_coverage_gap_not_undruggable(monkeypatch):
    # Simulate a gene GENUINELY absent from DGIdb (the reader returns None on a real 404 / empty
    # rollup). Must stay hermetic (no live S3): passing dgidb_row=None triggers a real _read_dgidb_row,
    # so we stub it to the genuine-absence sentinel. (Burndown P1: _read_dgidb_row now re-raises a
    # transient/creds failure instead of masking it as None, so a live read here would surface that.)
    monkeypatch.setattr(dgidb, "_read_dgidb_row", lambda *_a, **_k: None)
    monkeypatch.setattr(dgidb, "_read_directional_rows", lambda *_a, **_k: [])  # directness read stubbed absent
    s = known_drug_tractability_for_gene("NOTAGENE", dgidb_row=None)
    assert s["known_drug_tractability_class"] == "no_known_drug_evidence"
    assert s["has_approved_drug"] is False
    assert s["n_drug_interactions"] == 0
    assert "coverage gap" in s["known_drug_context"].lower()
    # directness: genuinely absent → 0 typed-direct, not_approved (no approved drug to gate)
    assert s["n_direct_interactions"] == 0
    assert s["direct_engagement_class"] == "indirect_or_untyped_only"
    assert s["approved_drug_engagement_class"] == "not_approved"


# ── DIRECTNESS metadata (2026-09-04) ─────────────────────────────────────────────────────────────────
def _dir_rows(*type_lists):
    """Build directional rows from interaction_types strings (one per drug)."""
    return [{"drug_name_norm": f"d{i}", "interaction_types": t} for i, t in enumerate(type_lists)]


def test_count_direct_only_typed_sm_interactions():
    # inhibitor/antagonist/binder count; antibody/vaccine/untyped do NOT
    rows = _dir_rows("inhibitor", "antagonist", "binder", "antibody|inhibitor", "antibody", "vaccine", "")
    assert dgidb._count_direct(rows) == 4          # 3 pure-direct + 1 antibody|inhibitor (has inhibitor)
    assert dgidb._count_direct([]) == 0
    assert dgidb._count_direct(None) is None        # unmeasured


def test_direct_engagement_threshold():
    assert dgidb._direct_engagement_class(5) == "direct_typed"
    assert dgidb._direct_engagement_class(10) == "direct_typed"
    assert dgidb._direct_engagement_class(4) == "sparse_direct"     # TP53-shape
    assert dgidb._direct_engagement_class(1) == "sparse_direct"     # CTNNB1-shape
    assert dgidb._direct_engagement_class(0) == "indirect_or_untyped_only"  # MYC-shape
    assert dgidb._direct_engagement_class(None) == "unmeasured"


def test_approved_engagement_class_gates_on_directness():
    # approved + direct → approved_direct (BRAF/KRAS/BTK/IDH1)
    assert dgidb._approved_drug_engagement_class(True, "direct_typed") == "approved_direct"
    # approved + sparse/indirect → approved_indirect_only (CTNNB1/MYC/TP53 — the inflation)
    assert dgidb._approved_drug_engagement_class(True, "sparse_direct") == "approved_indirect_only"
    assert dgidb._approved_drug_engagement_class(True, "indirect_or_untyped_only") == "approved_indirect_only"
    # UNMEASURED directness must NOT demote (fail toward prior behaviour)
    assert dgidb._approved_drug_engagement_class(True, "unmeasured") == "approved_direct"
    # non-approved genes → not_approved regardless
    assert dgidb._approved_drug_engagement_class(False, "direct_typed") == "not_approved"


def test_ctnnb1_shape_approved_but_indirect():
    # CTNNB1: approved drug catalogued, but only 1 typed-direct interaction (pri-724, itself indirect)
    s = known_drug_tractability_for_gene(
        "CTNNB1", dgidb_row=_row(has_approved_drug=True, n_approved_drug_interactions=17,
                                 n_drug_interactions=50, n_antineoplastic_interactions=27),
        directional_rows=_dir_rows("inhibitor"))
    assert s["known_drug_tractability_class"] == "approved_drug_tractable"   # UNCHANGED (Design B2)
    assert s["n_direct_interactions"] == 1
    assert s["approved_drug_engagement_class"] == "approved_indirect_only"
    assert "indirect" in s["directness_context"].lower()


def test_braf_shape_approved_direct():
    s = known_drug_tractability_for_gene(
        "BRAF", dgidb_row=_row(has_approved_drug=True, n_approved_drug_interactions=194,
                               n_drug_interactions=424),
        directional_rows=_dir_rows(*(["inhibitor"] * 44)))
    assert s["n_direct_interactions"] == 44
    assert s["approved_drug_engagement_class"] == "approved_direct"


# ── MODALITY gate (CASE-008) ─────────────────────────────────────────────────────────────────────
# A BIOLOGICS-ONLY approved antigen (curated crosswalk entry with biologics_only: true) must resolve
# approved_drug_engagement_class=approved_biologic_only regardless of DGIdb direct-count, so the
# resolver's SM-supportive approved-drug rung can be gated on modality. Dual-modality SM targets
# (EGFR/ERBB2/MET; NO biologics_only flag) are NEVER demoted — the osimertinib guard.

def test_biologics_only_demotes_even_when_falsely_direct():
    # CEACAM5 shape: an approved ADC/TCE + 8 typed-"direct" (mistyped antibody) records → the directness
    # proxy would call it approved_direct, but the modality gate overrides to approved_biologic_only.
    s = known_drug_tractability_for_gene(
        "CEACAM5", dgidb_row=_row(has_approved_drug=True, n_approved_drug_interactions=3,
                                  n_drug_interactions=20, n_antineoplastic_interactions=9),
        directional_rows=_dir_rows(*(["inhibitor"] * 8)),
        biologic_precedent={"modality": "adc_tce", "biologics_only": True})
    assert s["n_direct_interactions"] == 8                       # directness proxy WOULD say direct
    assert s["approved_drug_engagement_class"] == "approved_biologic_only"   # modality overrides
    assert s["approved_drug_modality"] == "biologic"
    assert s["approved_drug_modality_tag"] == "adc_tce"
    assert "biologic" in s["modality_context"].lower()


def test_biologics_only_demotes_indirect_case():
    # DLL3/FOLR1 shape: approved biologic + sparse/indirect roster. Without the gate → approved_indirect_only;
    # with it → approved_biologic_only (the more accurate modality label).
    s = known_drug_tractability_for_gene(
        "DLL3", dgidb_row=_row(has_approved_drug=True, n_approved_drug_interactions=2, n_drug_interactions=6),
        directional_rows=_dir_rows("inhibitor", "antibody"),
        biologic_precedent={"modality": "tce", "biologics_only": True})
    assert s["n_direct_interactions"] == 1
    assert s["approved_drug_engagement_class"] == "approved_biologic_only"
    assert s["approved_drug_modality"] == "biologic"


def test_dual_modality_sm_target_not_demoted_osimertinib_guard():
    # EGFR shape: a genuine SM target that ALSO has approved biologics (in the crosswalk, but NO
    # biologics_only flag). The fail-safe positive-only gate must NOT demote it.
    s = known_drug_tractability_for_gene(
        "EGFR", dgidb_row=_row(has_approved_drug=True, n_approved_drug_interactions=200,
                               n_drug_interactions=549),
        directional_rows=_dir_rows(*(["inhibitor"] * 40)),
        biologic_precedent={"modality": "adc_tce"})   # crosswalk hit but biologics_only absent
    assert s["approved_drug_engagement_class"] == "approved_direct"     # UNCHANGED
    assert s["approved_drug_modality"] == "small_molecule_or_unknown"
    assert s["approved_drug_modality_tag"] is None
    assert s["modality_context"] is None


def test_not_in_crosswalk_unchanged():
    # KRAS: not a biologics-precedent antigen → prior behaviour, byte-stable.
    s = known_drug_tractability_for_gene(
        "KRAS", dgidb_row=_row(has_approved_drug=True, n_approved_drug_interactions=113,
                               n_drug_interactions=165),
        directional_rows=_dir_rows(*(["inhibitor"] * 43)),
        biologic_precedent=None)
    assert s["approved_drug_engagement_class"] == "approved_direct"
    assert s["approved_drug_modality"] == "small_molecule_or_unknown"


def test_no_approved_drug_modality_not_applicable():
    s = known_drug_tractability_for_gene(
        "STEAP1", dgidb_row=_row(is_druggable_genome=True, n_drug_interactions=3),
        directional_rows=_dir_rows("inhibitor"),
        biologic_precedent={"modality": "tce", "biologics_only": True})
    assert s["has_approved_drug"] is False
    assert s["approved_drug_engagement_class"] == "not_approved"       # no approved drug to gate
    assert s["approved_drug_modality"] == "not_applicable"
    assert s["modality_context"] is None


def test_injected_row_without_precedent_leaves_modality_unread():
    # dgidb_row injected + biologic_precedent UNSET → no live crosswalk read (pure-rollup unit path).
    s = known_drug_tractability_for_gene(
        "DLL3", dgidb_row=_row(has_approved_drug=True, n_drug_interactions=6),
        directional_rows=_dir_rows("inhibitor"))
    assert s["approved_drug_modality"] == "small_molecule_or_unknown"   # unread → not demoted
    assert s["approved_drug_engagement_class"] in ("approved_direct", "approved_indirect_only")
