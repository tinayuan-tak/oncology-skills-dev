"""tcga_patient_cn.stratified — by-subgroup patient copy-number panorama (scope-coherence Phase 3).

DESCRIPTIVE / verdict-inert SUBTYPE view of patient_focal_cn_class: recompute GISTIC amp/del prevalence
WITHIN each molecular-subgroup member-set (e.g. COADREAD MSI-H vs MSS, CMS1-4), mirroring
gdc_somatic_hotspot.read_stratified_mutation_frequency for the SNV axis. It broadens the genomic-alteration
subtype scope beyond the SNV-frequency-only sibling (scope-coherence gap c) to the copy-number axis.

Emits NO verdict and fires no resolver rung — it feeds the subgroup-stratified-copy-number card's
per_subgroup_metrics panorama for render/LLM only. Reuses the raw per-sample GISTIC read + the amp/del
classifiers from read.py verbatim, so a per-stratum call cannot drift from the whole-cohort call.

ID-grain note: GISTIC columns are aliquot barcodes collapsed to the 3-segment PATIENT barcode
(_barcode_to_patient); the stratum member-set is normalized to the SAME patient grain before the
intersection, so the join does not silently drop to zero (the id-convention-mismatch failure the
subgroup_common fan-out coverage guard warns on). See methods/subgroup_common/scoping.py.
"""

from __future__ import annotations

from functools import partial

from onc_methods.subgroup_common.iteration import subgroup_iterable
from onc_methods.subgroup_common.panorama import (
    SUBGROUP_N_FLOOR,
    build_panorama,
    delta_reducer,
    evidence_state,
)
from onc_methods.tcga_patient_cn.read import (
    INDICATION_TO_TCGA,
    _barcode_to_patient,
    _load_sample_cancer_types,
    _read_gistic_gene,
    _summarize,
)


@subgroup_iterable
def read_stratified_copy_number(target: str, indication: str, _sample_id_filter: set | None = None) -> dict:
    """Per-stratum patient GISTIC amp/del summary. `_sample_id_filter` is injected by @subgroup_iterable;
    this reader collapses GISTIC aliquots to patient grain, restricts to the indication cohort, intersects
    with the (patient-normalized) stratum member-set, and RECOMPUTES the amp/del fractions within that
    stratum denominator via read.py::_summarize. Absent / underpowered strata are named honestly."""
    pairs = _read_gistic_gene(target)  # tuple[(aliquot_barcode, int GISTIC value)]
    codeset = INDICATION_TO_TCGA.get(str(indication).upper())
    by_patient: dict[str, int] = {}
    if pairs:
        cancer = _load_sample_cancer_types()  # {patient_barcode: cancer_type}
        for aliquot, val in pairs:
            pid = _barcode_to_patient(aliquot)
            if codeset is not None and cancer.get(pid) not in codeset:
                continue  # keep only this indication's tumours
            by_patient[pid] = val  # one tumour aliquot per patient in the matrix
    cohort_ids = set(by_patient)

    # Intersect with the stratum member-set, normalizing members to the SAME patient grain as GISTIC.
    if _sample_id_filter is not None:
        members = {_barcode_to_patient(s) for s in _sample_id_filter}
        member_ids = cohort_ids & members
    else:
        member_ids = cohort_ids

    vals = [by_patient[p] for p in member_ids]
    n = len(vals)
    floor_met = n >= SUBGROUP_N_FLOOR
    summ = _summarize(vals) or {}
    return {
        "target": target,
        "indication": indication,
        "subgroup_n": n,  # int → auto-enables the fan-out coverage guard
        "subgroup_n_floor_met": floor_met,
        "evidence_state": evidence_state(n, floor_met),  # measured | underpowered | absent
        # Primary per-stratum class: the FOCAL (verdict-consensus) CN class; "insufficient" when empty.
        "patient_focal_cn_class": summ.get("patient_focal_cn_class") or "insufficient",
        "patient_copy_number_class": summ.get("patient_copy_number_class"),
        "patient_high_amp_fraction": summ.get("patient_high_amp_fraction"),
        "patient_homdel_fraction": summ.get("patient_homdel_fraction"),
        "source_cohort": "TCGA-GISTIC",
    }


def _cn_freq_projection(stratum_id: str, rec: dict) -> dict:
    """Flat per_subgroup_metrics record for the subgroup-stratified-copy-number card (mirrors
    gdc_somatic_hotspot._mutation_freq_projection)."""
    return {
        "stratum": stratum_id,
        "class": rec["patient_focal_cn_class"],
        "evidence_state": rec["evidence_state"],
        "patient_focal_cn_class": rec["patient_focal_cn_class"],
        "patient_copy_number_class": rec["patient_copy_number_class"],
        "patient_high_amp_fraction": rec["patient_high_amp_fraction"],
        "patient_homdel_fraction": rec["patient_homdel_fraction"],
        "subgroup_n": rec["subgroup_n"],
        "subgroup_n_floor_met": rec["subgroup_n_floor_met"],
        "subtype_defining_data": "genomic",
        "source_cohort": rec["source_cohort"],
    }


def build_copy_number_panorama(
    target: str, indication: str, subgroups: list, subgroup_assignments_manifest: str, subgroup_catalog_repo=None
) -> dict:
    """By-subgroup patient copy-number panorama. Cross-stratum spread is reported on the focal high-amp
    fraction (the actionable oncogene signal), so cross_subgroup_delta_high_amp_fraction flags a
    subgroup-specific amplification gradient (e.g. HER2-amp enriched in a molecular subset)."""
    pan = build_panorama(
        read_stratified_copy_number,
        target=target,
        indication=indication,
        subgroups=subgroups,
        subgroup_assignments_manifest=subgroup_assignments_manifest,
        record_projection=_cn_freq_projection,
        reducer=partial(delta_reducer, metric_key="patient_high_amp_fraction", label="high_amp_fraction"),
        subgroup_catalog_repo=subgroup_catalog_repo,
    )
    pan["_data_source"] = "TCGA GISTIC per-sample (subgroup-stratified)"
    return pan
