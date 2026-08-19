"""Synthetic offline tests for the by-subgroup patient copy-number panorama (scope-coherence Phase 3).

No S3 / credentials: the raw GISTIC gene read + the barcode→cancer-type crosswalk are monkeypatched, and
the subgroup member-set resolver is stubbed, so the stratified-CN reader + panorama run entirely on
in-memory fixtures. Mirrors the offline discipline of the SNV subgroup-stratified tests."""
from __future__ import annotations

import methods.tcga_patient_cn.stratified as strat
from methods.subgroup_common import iteration


def _patients(prefix, n):
    return [f"TCGA-{prefix}-{i:04d}" for i in range(n)]


def _install_gistic(monkeypatch, values_by_patient):
    """Patch the raw reads: GISTIC returns aliquot barcodes (patient + -01A vial), cancer map = all COAD."""
    pairs = tuple((f"{pid}-01A-01D-XXXX-01", v) for pid, v in values_by_patient.items())
    monkeypatch.setattr(strat, "_read_gistic_gene", lambda target: pairs)
    monkeypatch.setattr(strat, "_load_sample_cancer_types",
                        lambda: {pid: "COAD" for pid in values_by_patient})


def test_stratum_recomputes_focal_class_within_member_set(monkeypatch):
    # 40 patients: 8 high-amp (+2), rest neutral → within this member-set high_amp_frac 0.20 ≥ 0.10.
    pts = _patients("AA", 40)
    vals = {p: (2 if i < 8 else 0) for i, p in enumerate(pts)}
    _install_gistic(monkeypatch, vals)
    rec = strat.read_stratified_copy_number("MYGENE", "COADREAD", _sample_id_filter=set(pts))
    assert rec["subgroup_n"] == 40
    assert rec["evidence_state"] == "measured"
    assert rec["patient_focal_cn_class"] == "recurrent_focal_amplification"
    assert abs(rec["patient_high_amp_fraction"] - 0.20) < 1e-9


def test_sample_grain_filter_matches_patient_grain_gistic(monkeypatch):
    """The id-grain guard: a SAMPLE-grain member set (…-01) must still join the patient-grain GISTIC —
    the reader normalizes members to patient grain before intersecting (no silent zero-join)."""
    pts = _patients("BB", 35)
    _install_gistic(monkeypatch, {p: 0 for p in pts})
    sample_grain = {f"{p}-01" for p in pts}                       # 4-segment sample ids
    rec = strat.read_stratified_copy_number("MYGENE", "COADREAD", _sample_id_filter=sample_grain)
    assert rec["subgroup_n"] == 35                                # would be 0 without normalization
    assert rec["evidence_state"] == "measured"


def test_underpowered_and_absent_strata_named_honestly(monkeypatch):
    pts = _patients("CC", 40)
    _install_gistic(monkeypatch, {p: 0 for p in pts})
    # <30 members → underpowered
    small = strat.read_stratified_copy_number("MYGENE", "COADREAD", _sample_id_filter=set(pts[:10]))
    assert small["subgroup_n"] == 10 and small["evidence_state"] == "underpowered"
    # no overlap → absent + insufficient class (never a fabricated focal_neutral)
    none = strat.read_stratified_copy_number("MYGENE", "COADREAD",
                                             _sample_id_filter={"TCGA-ZZ-9999"})
    assert none["subgroup_n"] == 0 and none["evidence_state"] == "absent"
    assert none["patient_focal_cn_class"] == "insufficient"


def test_panorama_reports_cross_subgroup_amp_gradient(monkeypatch):
    """End-to-end panorama over two strata: MSI enriched for focal amp, MSS neutral → a subgroup-specific
    high-amp gradient. Stubs the member-set resolver so build_panorama runs offline."""
    msi = _patients("DA", 40)
    mss = _patients("DB", 40)
    vals = {**{p: (2 if i < 12 else 0) for i, p in enumerate(msi)},   # 30% high-amp in MSI
            **{p: 0 for p in mss}}                                    # 0% in MSS
    _install_gistic(monkeypatch, vals)
    members = {"MSI": set(msi), "MSS": set(mss)}
    monkeypatch.setattr(iteration, "resolve_subgroup_cohort",
                        lambda manifest, sid, data_catalog_repo=None: members[sid])

    pan = strat.build_copy_number_panorama(
        "MYGENE", "COADREAD", subgroups=["MSI", "MSS"],
        subgroup_assignments_manifest="tcga-subgroup-assignments-coadread-v1")
    rows = {r["stratum"]: r for r in pan["per_subgroup_metrics"]}
    assert rows["MSI"]["class"] == "recurrent_focal_amplification"
    assert rows["MSS"]["class"] == "focal_neutral"
    assert pan["n_subgroups_with_data"] == 2
    assert abs(pan["cross_subgroup_delta_high_amp_fraction"] - 0.30) < 1e-9
