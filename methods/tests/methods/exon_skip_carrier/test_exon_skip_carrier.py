"""exon_skip_carrier — METex14 carrier classifier.

The classifier is pinned against the REAL DepMap 26Q1 MET splice variants observed in
OmicsSomaticMutationsMAF.maf (ModelID / Chromosome / Start_Position / Variant_Classification),
captured live 2026-09-02. The genomic window MUST recover the three exon-14 lines and EXCLUDE
the five distant MET splice sites — the exact discrimination that splice-classification-alone
(the only signal in the derived parquet) cannot make.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.exon_skip_carrier import (  # noqa: E402
    EXON_SKIP_EVENTS,
    VariantObs,
    carriers_for_event,
    carriers_from_observations,
    exon_skip_landscape_summary,
)
from methods.exon_skip_carrier.read import _observations_from_maf  # noqa: E402

# Real DepMap 26Q1 MET splice-site variants (chr7, hg38): (ModelID, Start_Position, VariantInfo).
# The first three are the exon-14 cluster (donor @116,771,990 = EBC-1/Hs746T; acceptor-side
# @116,771,656). The rest are splice sites 1-40 kb from exon 14 — NOT METex14.
_MET_EX14_POSITIVE = [
    ("ACH-000616", 116_771_990, "splice_donor_variant"),  # EBC-1  (canonical METex14)
    ("ACH-000628", 116_771_990, "splice_donor_variant"),  # Hs746T (canonical METex14)
    ("ACH-000988", 116_771_656, "splice_donor_variant"),  # intron-13 acceptor side
]
_MET_SPLICE_OFFTARGET = [
    ("ACH-001864", 116_769_792, "splice_donor_variant"),
    ("ACH-001321", 116_755_516, "splice_donor_variant"),
    ("ACH-001653", 116_775_112, "splice_donor_variant"),
    ("ACH-000755", 116_774_880, "splice_acceptor_variant"),
    ("ACH-001306", 116_731_662, "splice_acceptor_variant&coding_sequence_variant&intron_variant"),
]


def _obs(rows, chrom="chr7"):
    return [VariantObs(sample_id=m, chrom=chrom, pos=p, classification=c) for m, p, c in rows]


def test_recovers_exon14_cluster_only():
    all_rows = _MET_EX14_POSITIVE + _MET_SPLICE_OFFTARGET
    carriers = carriers_for_event(_obs(all_rows), "METex14")
    assert carriers == {"ACH-000616", "ACH-000628", "ACH-000988"}
    # none of the distant splice sites leak in
    assert carriers.isdisjoint({m for m, _, _ in _MET_SPLICE_OFFTARGET})


def test_canonical_anchors_are_positive():
    ev = EXON_SKIP_EVENTS["METex14"]
    carriers = carriers_for_event(_obs(_MET_EX14_POSITIVE), "METex14")
    assert ev.canonical_positive_samples <= carriers  # EBC-1 + Hs746T always recovered


def test_chromosome_normalization():
    # a source emitting bare "7" (no chr prefix) is handled identically
    carriers = carriers_for_event(_obs(_MET_EX14_POSITIVE, chrom="7"), "METex14")
    assert carriers == {"ACH-000616", "ACH-000628", "ACH-000988"}


def test_position_required_no_overcall():
    # splice classification WITHOUT a position never calls a carrier (the parquet-only failure mode)
    obs = [VariantObs("ACH-999999", "chr7", None, "splice_donor_variant")]
    assert carriers_for_event(obs, "METex14") == set()


def test_wrong_chromosome_excluded():
    obs = [VariantObs("ACH-XCHR", "chr1", 116_771_990, "splice_donor_variant")]
    assert carriers_for_event(obs, "METex14") == set()


def test_nonsplice_in_window_excluded():
    # a non-splice variant inside the window is not an exon-skip carrier by this predicate
    obs = [VariantObs("ACH-SILENT", "chr7", 116_771_900, "silent")]
    assert carriers_for_event(obs, "METex14") == set()


def test_compound_vep_consequence_matches():
    obs = [VariantObs("ACH-DEL", "chr7", 116_771_870, "splice_acceptor_variant&coding_sequence_variant&intron_variant")]
    assert carriers_for_event(obs, "METex14") == {"ACH-DEL"}


def test_unknown_event_raises():
    import pytest

    with pytest.raises(KeyError):
        carriers_for_event([], "EGFRvIII")


def test_maf_adapter_gene_filter_and_summary():
    # header + rows in raw-MAF column order; adapter filters to the event gene and windows.
    header = ["Hugo_Symbol", "Chromosome", "Start_Position", "End_Position", "Variant_Classification", "ModelID"]
    rows = [
        header,
        ["MET", "chr7", "116771990", "116771990", "Splice_Site", "ACH-000616"],
        ["MET", "chr7", "116769792", "116769792", "Splice_Site", "ACH-001864"],  # off-target
        ["EGFR", "chr7", "116771990", "116771990", "Splice_Site", "ACH-OTHER"],  # wrong gene
        ["MET", "chr7", "116771900", "116771900", "Missense_Mutation", "ACH-MIS"],
    ]  # non-splice
    obs = list(_observations_from_maf(iter(rows), gene="MET"))
    assert {o.sample_id for o in obs} == {"ACH-000616", "ACH-001864", "ACH-MIS"}  # EGFR filtered out
    summary = carriers_from_observations(obs, "METex14")
    assert summary["carrier_samples"] == ["ACH-000616"]
    assert summary["n_carriers"] == 1
    assert summary["gene"] == "MET"
    assert summary["window"] == "chr7:116771600-116772050"


def test_maf_adapter_missing_column_raises():
    import pytest

    bad = [["Hugo_Symbol", "Chromosome", "Variant_Classification", "ModelID"]]  # no Start_Position
    with pytest.raises(ValueError):
        list(_observations_from_maf(iter(bad), gene="MET"))


# ------------------------------- product builder -------------------------------


def _maf(rows):
    header = [
        "Hugo_Symbol",
        "Chromosome",
        "Start_Position",
        "End_Position",
        "Variant_Classification",
        "ModelID",
        "VariantType",
    ]
    return [header] + rows


def test_builder_retains_only_splice_and_sorts():
    from methods.exon_skip_carrier.build import splice_rows_from_maf

    rows = _maf(
        [
            ["MET", "chr7", "116771990", "116771990", "Splice_Site", "ACH-000616", "SNV"],
            ["MET", "7", "116769792", "116769792", "Splice_Region", "ACH-001864", "SNV"],  # bare chrom
            ["KRAS", "chr12", "25245350", "25245350", "Missense_Mutation", "ACH-XX", "SNV"],  # non-splice dropped
            ["APC", "chr5", "112839999", "112840010", "Splice_Site", "ACH-YY", "deletion"],
        ]
    )
    out = splice_rows_from_maf(rows)
    assert [r["gene_symbol"] for r in out] == ["APC", "MET", "MET"]  # gene-sorted, non-splice dropped
    met = [r for r in out if r["gene_symbol"] == "MET"]
    assert met[0]["chrom"] == "chr7" and met[1]["chrom"] == "chr7"  # bare "7" normalized
    assert met[0]["start_position"] == 116769792 < met[1]["start_position"]  # sorted within gene
    assert out[0]["end_position"] == 112840010  # End_Position retained


def test_builder_unparseable_position_dropped():
    from methods.exon_skip_carrier.build import splice_rows_from_maf

    rows = _maf([["MET", "chr7", "", "", "Splice_Site", "ACH-NOPOS", "SNV"]])
    assert splice_rows_from_maf(rows) == []


def test_builder_table_schema():
    from methods.exon_skip_carrier.build import build_table

    rows = _maf([["MET", "chr7", "116771990", "116771990", "Splice_Site", "ACH-000616", "SNV"]])
    tbl = build_table(rows)
    assert tbl.schema.names == [
        "gene_symbol",
        "model_id",
        "chrom",
        "start_position",
        "end_position",
        "variant_classification",
        "variant_type",
    ]
    assert tbl.num_rows == 1


def test_builder_missing_column_raises():
    import pytest

    from methods.exon_skip_carrier.build import splice_rows_from_maf

    bad = [["Hugo_Symbol", "Start_Position", "Variant_Classification", "ModelID"]]  # no Chromosome
    with pytest.raises(ValueError):
        splice_rows_from_maf(iter(bad))


# ------------------------- landscape reader (genomic-alt substrate) -------------------------


def test_landscape_met_luad_is_recurrent_splice_driver():
    r = exon_skip_landscape_summary("MET", "LUAD", _carrier_probe=False)
    assert r["splice_exon_skip_class"] == "recurrent_splice_driver"
    assert r["event_id"] == "METex14"
    assert r["driver_direction"] == "activating"
    assert "SPLICE-skipping" in r["splice_context"]


def test_landscape_met_off_indication():
    r = exon_skip_landscape_summary("MET", "COADREAD", _carrier_probe=False)
    assert r["splice_exon_skip_class"] == "splice_event_off_indication"
    assert r["event_id"] == "METex14"


def test_landscape_met_nsclc_composite():
    r = exon_skip_landscape_summary("MET", "NSCLC", _carrier_probe=False)
    assert r["splice_exon_skip_class"] == "recurrent_splice_driver"


def test_landscape_no_registered_event():
    r = exon_skip_landscape_summary("KRAS", "LUAD", _carrier_probe=False)
    assert r["splice_exon_skip_class"] == "no_registered_event"
    assert r["event_id"] is None


def test_metex14_event_has_dual_build_and_oncogenic_scope():
    ev = EXON_SKIP_EVENTS["METex14"]
    assert ev.window_start_hg19 and ev.window_end_hg19  # hg19 window curated
    assert ev.window_start_hg19 < ev.window_end_hg19
    assert ev.oncogenic_indications == frozenset({"LUAD", "LUSC", "NSCLC"})
    assert ev.driver_direction == "activating"


def test_landscape_case_insensitive_target():
    r = exon_skip_landscape_summary("met", "luad", _carrier_probe=False)
    assert r["splice_exon_skip_class"] == "recurrent_splice_driver"
