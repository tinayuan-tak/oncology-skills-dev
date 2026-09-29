"""tcga_fusion_consensus.stratified — by-subgroup fusion-recurrence panorama (scope-coherence Phase 3).

DESCRIPTIVE / verdict-inert SUBTYPE view of fusion recurrence: recompute the target's fusion frequency
+ class WITHIN each molecular-subgroup member-set, mirroring the SNV subgroup-stratified-mutation-frequency
and the CN subgroup-stratified-copy-number siblings. Broadens the genomic-alteration subtype scope to the
fusion axis (scope-coherence gap c). Emits no verdict; fires no resolver rung.

HONEST-POWER caveat: per-tissue fusion counts are already small (fusion-rearrangement-landscape notes
~5 ALK-fusion LUAD samples); split across molecular strata, most strata will be `underpowered`/`absent`.
This reader is built for completeness + honesty (it names the gap), not because fusion-by-subtype is
usually informative — CN-by-subtype is the higher-power subtype axis.

Denominator = fusion-ASSAYED samples (sample_coverage sibling) intersected with the stratum member-set;
numerator = distinct stratum members with the target fused (>= min_callers). Both are normalized to the
3-segment PATIENT grain before intersection so the join does not silently drop to zero (id-convention
guard). Reuses the consensus df + coverage + tissue map from read.py.
"""

from __future__ import annotations

from functools import partial

from methods.subgroup_common.iteration import subgroup_iterable
from methods.subgroup_common.panorama import (
    SUBGROUP_N_FLOOR,
    build_panorama,
    delta_reducer,
    evidence_state,
)
from methods.tcga_fusion_consensus.read import (
    _DEFAULT_MIN_CALLERS,
    _RECURRENT_MIN_SAMPLES,
    _indication_tissue_codes,
    _load_consensus,
    _load_coverage,
)

_PARTNER_COLS = ("partners_tumorfusions", "partners_gao_2018", "partners_cbioportal")


def _to_patient(sample_key: str) -> str:
    """Collapse a 4-segment fusion sample_key (TCGA-tss-part-sampleNum) to the 3-segment PATIENT barcode,
    the common grain used to join against the subgroup-assignment sample ids."""
    parts = str(sample_key).split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(sample_key)


@subgroup_iterable
def read_stratified_fusion(
    target: str, indication: str, min_callers: int = _DEFAULT_MIN_CALLERS, _sample_id_filter: set | None = None
) -> dict:
    """Per-stratum fusion recurrence. Denominator = assayed samples in the indication tissue ∩ stratum
    members; numerator = distinct stratum members with the target fused. `_sample_id_filter` injected by
    @subgroup_iterable."""
    codes = _indication_tissue_codes(str(indication or "").upper().strip())
    members = {_to_patient(s) for s in _sample_id_filter} if _sample_id_filter is not None else None

    # Denominator: fusion-ASSAYED patients in the tissue, intersected with the stratum member-set.
    cov = _load_coverage()
    assayed: set = set()
    if cov is not None and not cov.empty and {"sample_key", "tissue"} <= set(cov.columns):
        cov_t = cov[cov["tissue"].astype(str).str.upper().isin(codes)]
        assayed = {_to_patient(sk) for sk in cov_t["sample_key"]}
    if members is not None:
        assayed &= members
    subgroup_n = len(assayed)

    # Numerator: distinct stratum patients with the target fused (>= min_callers), + recurrent partners.
    df = _load_consensus()
    fused: set = set()
    partner_samples: dict = {}
    if df is not None and not df.empty:
        sym = str(target or "").upper().strip()
        sub = df[df["gene_symbol"].astype(str).str.upper() == sym]
        if min_callers > 1:
            sub = sub[sub["caller_count"] >= min_callers]
        sub = sub[sub["tissue"].astype(str).str.upper().isin(codes)]
        for _, row in sub.iterrows():
            pid = _to_patient(row["sample_key"])
            if members is not None and pid not in members:
                continue
            fused.add(pid)
            parts: set = set()
            for col in _PARTNER_COLS:
                v = row.get(col)
                if v is not None and hasattr(v, "__len__") and not isinstance(v, str):
                    parts.update(str(p) for p in v if p)
            for p in parts:
                partner_samples.setdefault(p, set()).add(pid)

    recurrent = sorted(
        ((p, len(s)) for p, s in partner_samples.items() if len(s) >= _RECURRENT_MIN_SAMPLES),
        key=lambda x: (-x[1], x[0]),
    )
    recurrent_partners = [{"partner": p, "n_samples": n} for p, n in recurrent]
    n_with_fusion = len(fused)

    if recurrent_partners:
        fclass, conf = "recurrent_fusion_driver", "high_recurrent_partner"
    elif n_with_fusion >= _RECURRENT_MIN_SAMPLES:
        fclass, conf = "recurrent_fusion_driver", "moderate_promiscuous"
    elif n_with_fusion > 0:
        fclass, conf = "sporadic_fusion", None
    else:
        fclass, conf = "no_recurrent_fusion", None

    # evidence_state keys on the DENOMINATOR (assayed samples in the stratum), not the fusion count — a
    # well-assayed stratum with zero fusions is `measured` (a real negative), not `absent`.
    floor_met = subgroup_n >= SUBGROUP_N_FLOOR
    freq = (n_with_fusion / subgroup_n) if subgroup_n else None
    return {
        "target": target,
        "indication": indication,
        "subgroup_n": subgroup_n,  # assayed denominator (int → coverage guard)
        "subgroup_n_floor_met": floor_met,
        "evidence_state": evidence_state(subgroup_n, floor_met),
        "fusion_class": fclass if subgroup_n else "data_unavailable",
        "fusion_recurrence_confidence": conf,
        "n_samples_with_fusion": n_with_fusion,
        "fusion_frequency": round(freq, 4) if freq is not None else None,
        "recurrent_partners": recurrent_partners,
        "source_cohort": "TCGA-fusion-consensus",
    }


def _fusion_freq_projection(stratum_id: str, rec: dict) -> dict:
    return {
        "stratum": stratum_id,
        "class": rec["fusion_class"],
        "evidence_state": rec["evidence_state"],
        "fusion_class": rec["fusion_class"],
        "fusion_recurrence_confidence": rec["fusion_recurrence_confidence"],
        "fusion_frequency": rec["fusion_frequency"],
        "n_samples_with_fusion": rec["n_samples_with_fusion"],
        "recurrent_partners": rec["recurrent_partners"],
        "subgroup_n": rec["subgroup_n"],
        "subgroup_n_floor_met": rec["subgroup_n_floor_met"],
        "subtype_defining_data": "genomic",
        "source_cohort": rec["source_cohort"],
    }


def build_fusion_panorama(
    target: str, indication: str, subgroups: list, subgroup_assignments_manifest: str, subgroup_catalog_repo=None
) -> dict:
    """By-subgroup fusion-recurrence panorama. Cross-stratum spread on fusion_frequency flags a
    subgroup-specific fusion gradient (rare — see the honest-power caveat above)."""
    pan = build_panorama(
        read_stratified_fusion,
        target=target,
        indication=indication,
        subgroups=subgroups,
        subgroup_assignments_manifest=subgroup_assignments_manifest,
        record_projection=_fusion_freq_projection,
        reducer=partial(delta_reducer, metric_key="fusion_frequency", label="fusion_frequency"),
        subgroup_catalog_repo=subgroup_catalog_repo,
    )
    pan["_data_source"] = "TCGA fusion-consensus per-sample (subgroup-stratified)"
    return pan
