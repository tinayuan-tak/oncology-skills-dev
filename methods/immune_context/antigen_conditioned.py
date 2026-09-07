"""immune_context.antigen_conditioned — effector context CONDITIONED on antigen expression (v2).

The sharper TCE-efficacy question the per-indication immune-context (v1) does not answer: are the
ANTIGEN-HIGH patients also T-cell-HIGH? A T-cell engager only helps a patient who has BOTH the surface
antigen AND an effector population; the per-indication average can hide an anti-correlation (the
antigen-high subset is immune-COLD — a program-relevant failure mode).

Joins two per-patient signals on the TCGA barcode:
  - CIBERSORT LM22 CD8 T-cell fraction per sample (gdc-pancanatlas-immune-2018; SampleID = TCGA barcode)
  - per-sample antigen TPM (tcga-tumor-tpm-recount3-long-v1; UUID-keyed → bridged to barcode via the
    recount3 per-study metadata gdc_file_id→submitter_id map, reused from dge_deseq2)

THE JOIN TRAP (documented): CIBERSORT is barcode-keyed, the TPM product is UUID-keyed. A naive join
silently returns ~0 matches. This module GUARDS the join with a match-rate floor: if fewer than
`min_join_fraction` of the antigen-TPM samples map to a CIBERSORT barcode, it returns data_unavailable
WITH the coverage number — never a correlation computed on a handful of accidental matches.

Pure stat (antigen_conditioned_summary) is unit-testable on synthetic per-patient frames; the S3 join
(read_antigen_conditioned) is live-smoked.
"""
from __future__ import annotations


from . import classify as _classify

# antigen-high = top tertile of per-sample antigen TPM within the indication (patient-selection framing).
ANTIGEN_HIGH_QUANTILE = 2 / 3
# join-coverage guard: require at least this fraction of antigen-TPM samples to map to a CIBERSORT
# barcode, else the join is untrustworthy (barcode-vs-UUID trap) → data_unavailable.
MIN_JOIN_FRACTION = 0.5
# the effector gap that matters: antigen-high patients meaningfully colder than antigen-low.
COLD_IN_HIGH_DELTA = 0.02   # absolute CD8-fraction drop (high vs low) flagged as an effector-escape risk


def antigen_conditioned_summary(per_patient: list) -> dict:
    """Given per-patient (antigen_tpm, cd8_fraction) rows, split by antigen tertile and compare the
    effector (CD8) context of antigen-HIGH vs antigen-LOW patients.

    `per_patient`: list of dicts (or DataFrame) with 'antigen_tpm' + 'cd8_fraction'. Returns the
    high/low median CD8 fractions, their delta, an immune_context_class for the antigen-HIGH subset
    (reusing the v1 pan-cancer-anchored classifier), and an antigen_conditioned_call. Empty → gap."""
    import numpy as np
    import pandas as pd
    df = per_patient if isinstance(per_patient, pd.DataFrame) else pd.DataFrame(per_patient)
    if df.empty or "antigen_tpm" not in df.columns or "cd8_fraction" not in df.columns:
        return {"antigen_conditioned_call": "data_unavailable", "n_patients_joined": 0,
                "cd8_fraction_antigen_high": None, "cd8_fraction_antigen_low": None,
                "cd8_high_minus_low": None, "antigen_high_immune_context_class": "data_unavailable"}
    df = df.dropna(subset=["antigen_tpm", "cd8_fraction"])
    n = len(df)
    if n < 10:   # too few joined patients to tertile-split meaningfully
        return {"antigen_conditioned_call": "data_unavailable", "n_patients_joined": n,
                "cd8_fraction_antigen_high": None, "cd8_fraction_antigen_low": None,
                "cd8_high_minus_low": None, "antigen_high_immune_context_class": "data_unavailable"}
    thr = float(df["antigen_tpm"].quantile(ANTIGEN_HIGH_QUANTILE))
    high = df[df["antigen_tpm"] >= thr]
    low = df[df["antigen_tpm"] < thr]
    cd8_high = float(np.median(high["cd8_fraction"])) if len(high) else None
    cd8_low = float(np.median(low["cd8_fraction"])) if len(low) else None
    delta = (cd8_high - cd8_low) if (cd8_high is not None and cd8_low is not None) else None
    high_class = _classify.classify_immune_context(cd8_high)   # reuse pan-cancer-anchored bands
    # the call: the antigen-high subset's own hot/cold, plus a flag if it's colder than antigen-low
    if delta is not None and delta <= -COLD_IN_HIGH_DELTA:
        call = "antigen_high_is_colder"        # effector-escape risk: the targetable patients are T-cell-poorer
    elif high_class == "immune_hot":
        call = "antigen_high_immune_hot"       # the ideal: targetable AND inflamed
    elif high_class == "immune_cold":
        call = "antigen_high_immune_cold"
    else:
        call = "antigen_high_immune_intermediate"
    return {
        "antigen_conditioned_call": call,
        "n_patients_joined": n,
        "cd8_fraction_antigen_high": round(cd8_high, 4) if cd8_high is not None else None,
        "cd8_fraction_antigen_low": round(cd8_low, 4) if cd8_low is not None else None,
        "cd8_high_minus_low": round(delta, 4) if delta is not None else None,
        "antigen_high_immune_context_class": high_class,
    }


# ---- S3 join (bridges CIBERSORT barcode × recount3 UUID→barcode antigen TPM) ----

def _cibersort_cd8_by_barcode(indication: str):
    """{tcga_case_barcode: cd8_fraction} for the indication's TCGA studies, from the immune_context
    CIBERSORT frame. Keyed on the CASE-level barcode (first 3 barcode fields, e.g. TCGA-OR-A5JG) so it
    joins to recount3 submitter_id (which is case-level). None if unreadable."""
    from . import read as _ic
    studies = _ic.INDICATION_TO_TCGA_STUDIES.get(str(indication).upper().strip())
    if not studies:
        return None
    # Streamed pushdown of just this indication's study rows (2026-08-22): replaces the whole-frame
    # load + in-memory .isin filter with _read_samples_for_studies (pancanatlas-cibersort-lm22-per-
    # sample-v1). Columns are the derived product's: sample_id + T.cells.CD8 (LM22 names verbatim).
    sub = _ic._read_samples_for_studies(studies)
    if sub is None:
        return None
    if sub.empty:
        return {}
    sub = sub.copy()
    # sample_id like TCGA.OR.A5JG.01A... → case barcode TCGA-OR-A5JG (dots→dashes, first 3 fields)
    def _case(sid: str) -> str:
        parts = str(sid).replace("-", ".").split(".")
        return "-".join(parts[:3]).upper()
    sub["case"] = sub["sample_id"].map(_case)
    # a case can have multiple samples; take the max CD8 (tumor-dominant) per case
    return sub.groupby("case")["T.cells.CD8"].max().to_dict()


def read_antigen_conditioned(target: str, indication: str) -> dict:
    """Live antigen-conditioned effector join for one target+indication. Guards the barcode↔UUID join
    with MIN_JOIN_FRACTION; data_unavailable (with coverage) if the join is too thin, the indication
    is unmapped, or a product is unreadable — never a correlation on accidental matches."""
    ind = str(indication).upper().strip()
    cd8_by_case = _cibersort_cd8_by_barcode(ind)
    if cd8_by_case is None:
        return {**antigen_conditioned_summary([]), "target": target, "indication": ind,
                "_data_note": "CIBERSORT unreadable or indication unmapped"}
    try:
        per_patient, join_frac, n_tpm = _join_antigen_tpm(target, ind, cd8_by_case)
    except Exception as e:  # noqa: BLE001
        return {**antigen_conditioned_summary([]), "target": target, "indication": ind,
                "_data_note": f"antigen-TPM join failed: {type(e).__name__}: {e}"}
    if join_frac < MIN_JOIN_FRACTION:
        return {**antigen_conditioned_summary([]), "target": target, "indication": ind,
                "join_fraction": round(join_frac, 3), "n_tpm_samples": n_tpm,
                "_data_note": f"barcode↔UUID join coverage {join_frac:.0%} < {MIN_JOIN_FRACTION:.0%} floor "
                              f"— untrustworthy (barcode-vs-UUID trap); not scored"}
    out = antigen_conditioned_summary(per_patient)
    out.update({"target": target, "indication": ind, "join_fraction": round(join_frac, 3),
                "n_tpm_samples": n_tpm})
    return out


def _antigen_tpm_by_uuid_study(target: str):
    """{study: {sample_uuid: linear_tpm}} for one gene from the recount3 tumor long product
    (gene-filtered predicate-pushdown). Self-contained (does not depend on other methods' internals).
    The long product carries log2(TPM+1) per (gene_symbol, sample_id=UUID, study)."""
    from methods.catalog_query.read import s3_uri_for
    try:
        uri = s3_uri_for("tcga-tumor-tpm-recount3-long-v1")
    except Exception:  # noqa: BLE001
        return None
    import pyarrow.parquet as pq
    import pyarrow.fs as fs
    s3fs = fs.S3FileSystem(region="us-east-1")
    tbl = pq.read_table(uri.replace("s3://", ""), filesystem=s3fs,
                        filters=[("gene_symbol", "==", target.upper().strip())],
                        columns=["sample_id", "study", "log2_tpm"])
    df = tbl.to_pandas()
    out: dict = {}
    for sid, study, val in zip(df["sample_id"], df["study"], df["log2_tpm"]):
        out.setdefault(str(study), {})[str(sid)] = float(2 ** float(val) - 1)   # log2(TPM+1) → linear
    return out


def _join_antigen_tpm(target: str, indication: str, cd8_by_case: dict):
    """Bridge recount3 per-sample antigen TPM (UUID) → barcode (via per-study metadata submitter_id) →
    join to CIBERSORT cd8_by_case. Returns (per_patient rows, join_fraction, n_tpm_samples)."""
    from methods.dge_deseq2.read import _fetch_recount3_metadata, INDICATION_TO_TCGA_STUDIES

    studies = INDICATION_TO_TCGA_STUDIES.get(indication) or []
    tpm_by_study = _antigen_tpm_by_uuid_study(target)   # {study: {uuid: tpm}}
    if not tpm_by_study:
        return [], 0.0, 0
    rows, matched, total = [], 0, 0
    for study in studies:
        uuid_tpm = tpm_by_study.get(study) or {}
        if not uuid_tpm:
            continue
        meta = _fetch_recount3_metadata(study)  # [gdc_file_id, sample_type, submitter_id]
        uuid_to_case = {}
        for _, m in meta.iterrows():
            case = "-".join(str(m["submitter_id"]).split("-")[:3]).upper()  # barcode → case
            uuid_to_case[str(m["gdc_file_id"])] = case
        for uuid, tpm in uuid_tpm.items():
            total += 1
            case = uuid_to_case.get(str(uuid))
            if case and case in cd8_by_case:
                matched += 1
                rows.append({"antigen_tpm": tpm, "cd8_fraction": cd8_by_case[case]})
    join_frac = (matched / total) if total else 0.0
    return rows, join_frac, total
