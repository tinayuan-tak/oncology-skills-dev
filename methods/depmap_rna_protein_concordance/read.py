"""Q5 RNA↔protein concordance assembler (cell-line). Joins per-ModelID target RNA vs protein,
computes correlation + detection fractions + the rna_as_biomarker verdict. data_unavailable-safe.
"""
from __future__ import annotations

from typing import Optional

# concordance thresholds (Pearson r on paired per-model RNA vs protein).
STRONG_CONCORDANCE_R = 0.7      # RNA is an adequate protein proxy
MODERATE_CONCORDANCE_R = 0.4    # RNA is a partial proxy; interpret with caution
MIN_PAIRED_MODELS = 20          # below this the correlation is underpowered
# RNA "expressed" / protein "detected" floors (log2 units; RNA matches stats.py detectable).
DETECTABLE_LOG2TPM = 1.0


def _paired_rna_protein(target: str, release_pin: str = "26q1"):
    """Per-ModelID paired (rna_log2tpm, protein_log2abundance) for target across DepMap cell lines.
    Reuses the two landed per-model readers (RNA = card4 S3 matrix; protein = Gygi MS).
    Returns (rna_by_model, protein_by_model, note) — note is a data-gap string or None."""
    from methods.depmap_expression_dependency import cli as _rna
    from methods.depmap_protein_abundance import cli as _prot
    try:
        _ch, rna_by_model, _meta, errs = _rna.load_depmap_files_for_card4(
            release_pin=release_pin, target_symbol=target)
    except Exception as e:  # noqa: BLE001
        return {}, {}, f"RNA load failed: {type(e).__name__}"
    if errs or not rna_by_model:
        return {}, {}, (errs[0].get("_live_read_error") if errs else "no model RNA")
    acc = _prot.resolve_accession(target)
    if acc is None:
        return rna_by_model, {}, "target has no UniProt accession in the Gygi MS sidecar"
    prot_by_model, _panel = _prot.load_abundance_column(acc)
    if not prot_by_model:
        return rna_by_model, {}, "target not quantified in the Gygi MS panel"
    return rna_by_model, prot_by_model, None


def read_rna_protein_concordance(target: str, release_pin: str = "26q1") -> dict:
    """Q5 assembler — cell-line RNA↔protein concordance for target. target-grain (no indication).

    Returns rna_protein_r (Pearson) + spearman + n_paired_models + detection fractions +
    rna_high_protein_low_fraction (the RNA-misleads population) + rna_as_biomarker verdict."""
    rna_by_model, prot_by_model, note = _paired_rna_protein(target, release_pin=release_pin)
    base = {"target": target, "release_pin": release_pin}
    if not rna_by_model or not prot_by_model:
        base.update({"rna_as_biomarker": "data_unavailable", "rna_protein_r": None,
                     "n_paired_models": 0, "_data_note": note or "no paired RNA/protein"})
        return base

    import numpy as np
    common = sorted(set(rna_by_model) & set(prot_by_model))
    n = len(common)
    if n < MIN_PAIRED_MODELS:
        base.update({"rna_as_biomarker": "insufficient_paired_models", "rna_protein_r": None,
                     "n_paired_models": n,
                     "_data_note": f"only {n} models have BOTH RNA + protein (floor {MIN_PAIRED_MODELS})"})
        return base

    rna = np.array([rna_by_model[m] for m in common], dtype=float)
    prot = np.array([prot_by_model[m] for m in common], dtype=float)
    # zero-variance guard: a constant arm makes the correlation undefined (NaN). Report it as an
    # honest coverage gap rather than a NaN r (a target expressed identically across all lines, or a
    # single-value protein column, carries no concordance signal).
    if np.ptp(rna) == 0 or np.ptp(prot) == 0:
        base.update({"rna_as_biomarker": "insufficient_paired_models", "rna_protein_r": None,
                     "n_paired_models": n,
                     "_data_note": "RNA or protein is constant across paired models (correlation undefined)"})
        return base
    # Pearson + Spearman (best-effort on scipy; numpy fallback for Pearson).
    try:
        from scipy.stats import pearsonr, spearmanr
        pear = float(pearsonr(rna, prot)[0]); spear = float(spearmanr(rna, prot)[0])
    except Exception:  # noqa: BLE001
        pear = float(np.corrcoef(rna, prot)[0, 1]); spear = None

    # protein detection fraction = models where protein was quantified over models where RNA expressed.
    rna_expressed = rna >= DETECTABLE_LOG2TPM
    # RNA-high / protein-low: RNA expressed but protein in the bottom decile of the paired protein dist
    prot_low_cut = float(np.percentile(prot, 10))
    rna_high_protein_low = int(np.sum(rna_expressed & (prot <= prot_low_cut)))
    n_rna_expressed = int(np.sum(rna_expressed))

    out = {
        "rna_protein_r": round(pear, 4),
        "rna_protein_spearman": (round(spear, 4) if spear is not None else None),
        "n_paired_models": n,
        "protein_detection_fraction": round(len(prot_by_model) / max(len(rna_by_model), 1), 4),
        "rna_expressed_fraction": round(n_rna_expressed / n, 4),
        "rna_high_protein_low_fraction": (round(rna_high_protein_low / n_rna_expressed, 4)
                                          if n_rna_expressed else None),
    }
    out.update(base)
    out["rna_as_biomarker"] = _classify_rna_biomarker(pear, n)
    return out


def _classify_rna_biomarker(pearson_r, n_paired) -> str:
    """Categorical for the card/rules:
      adequate_proxy  — RNA tracks protein tightly (r >= 0.7): RNA biomarker/inference trustworthy
      partial_proxy   — moderate (0.4 <= r < 0.7): RNA is a partial proxy, interpret with caution
      poor_proxy      — decoupled (r < 0.4): RNA misleads; protein must be measured directly
      insufficient_paired_models / data_unavailable — handled by the caller."""
    if pearson_r is None:
        return "data_unavailable"
    if pearson_r >= STRONG_CONCORDANCE_R:
        return "adequate_proxy"
    if pearson_r >= MODERATE_CONCORDANCE_R:
        return "partial_proxy"
    return "poor_proxy"


# ---- TUMOR arm (CPTAC matched RNA+protein, cptac-rna-protein-matched-per-sample-v1) ------------
# The tumor analogue of the cell-line concordance above. Reads the matched product (one row per
# (cohort, patient_id, gene, rna_log2tpm, protein_log2abundance)) and computes the SAME correlation
# + rna_as_biomarker classification per the indication's CPTAC cohort. Tumor concordance is a
# DISTINCT signal from cell-line (purity/stroma noise; strongly gene-specific).
S3_BUCKET = "onc-compbio"
CPTAC_MATCHED_KEY = ("data-catalog/derived/cptac-rna-protein-matched-per-sample-v1/"
                     "cptac_rna_protein_matched.parquet")
MIN_PAIRED_TUMORS = 20

# indication → CPTAC cohort code (the 10 cohorts in the matched product).
INDICATION_TO_CPTAC_COHORT = {
    "BRCA": "brca", "KIRC": "ccrcc", "CCRCC": "ccrcc", "COADREAD": "coad", "COAD": "coad",
    "READ": "coad", "GBM": "gbm", "HNSC": "hnscc", "HNSCC": "hnscc", "LUSC": "lscc", "LSCC": "lscc",
    "LUAD": "luad", "OV": "ov", "PAAD": "pdac", "PDAC": "pdac", "UCEC": "ucec",
}


def _read_matched_cohort(cohort: str):
    """Read the matched CPTAC product for one cohort → DataFrame[patient_id, gene, rna_log2tpm,
    protein_log2abundance]. Empty on any read failure (data_unavailable-safe)."""
    import pandas as pd
    try:
        import pyarrow.parquet as pq
        import s3fs
        fs = s3fs.S3FileSystem()
        tbl = pq.read_table(f"{S3_BUCKET}/{CPTAC_MATCHED_KEY}", filesystem=fs,
                            filters=[("cohort", "==", cohort)])
        return tbl.to_pandas()
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"])


def read_tumor_rna_protein_concordance(target: str, indication: str) -> dict:
    """Q5 TUMOR arm — CPTAC matched tumor RNA↔protein concordance for target in the indication's
    CPTAC cohort. Same correlation + rna_as_biomarker vocab as the cell-line arm. data_unavailable-safe."""
    cohort = INDICATION_TO_CPTAC_COHORT.get(indication.upper().strip())
    base = {"target": target, "indication": indication, "cptac_cohort": cohort,
            "substrate": "cptac_tumor"}
    if cohort is None:
        base.update({"rna_as_biomarker": "data_unavailable", "rna_protein_r": None,
                     "n_paired_tumors": 0, "_data_note": "no CPTAC cohort for this indication"})
        return base
    df = _read_matched_cohort(cohort)
    sub = df[df["gene"] == target.upper().strip()] if not df.empty else df
    sub = sub.dropna(subset=["rna_log2tpm", "protein_log2abundance"]) if not sub.empty else sub
    n = len(sub)
    if n < MIN_PAIRED_TUMORS:
        base.update({"rna_as_biomarker": ("data_unavailable" if n == 0 else "insufficient_paired_tumors"),
                     "rna_protein_r": None, "n_paired_tumors": n,
                     "_data_note": (f"{cohort}: {n} tumors with matched RNA+protein for {target} "
                                    f"(floor {MIN_PAIRED_TUMORS})")})
        return base
    import numpy as np
    rna = sub["rna_log2tpm"].to_numpy(dtype=float)
    prot = sub["protein_log2abundance"].to_numpy(dtype=float)
    if np.ptp(rna) == 0 or np.ptp(prot) == 0:
        base.update({"rna_as_biomarker": "insufficient_paired_tumors", "rna_protein_r": None,
                     "n_paired_tumors": n, "_data_note": "RNA or protein constant across tumors"})
        return base
    try:
        from scipy.stats import pearsonr, spearmanr
        pear = float(pearsonr(rna, prot)[0]); spear = float(spearmanr(rna, prot)[0])
    except Exception:  # noqa: BLE001
        pear = float(np.corrcoef(rna, prot)[0, 1]); spear = None
    base.update({
        "rna_protein_r": round(pear, 4),
        "rna_protein_spearman": (round(spear, 4) if spear is not None else None),
        "n_paired_tumors": n,
        "rna_as_biomarker": _classify_rna_biomarker(pear, n),
    })
    return base


def read_tumor_rna_protein_scatter(target: str, indication: str) -> dict:
    """Per-tumor paired points for the Q5 TUMOR scatter figure. data-gap-safe."""
    cohort = INDICATION_TO_CPTAC_COHORT.get(indication.upper().strip())
    if cohort is None:
        return {"available": False, "points": [], "cptac_cohort": None}
    df = _read_matched_cohort(cohort)
    sub = df[df["gene"] == target.upper().strip()] if not df.empty else df
    sub = sub.dropna(subset=["rna_log2tpm", "protein_log2abundance"]) if not sub.empty else sub
    return {"available": bool(len(sub)), "cptac_cohort": cohort,
            "points": [{"patient_id": r.patient_id, "rna": round(float(r.rna_log2tpm), 4),
                        "protein": round(float(r.protein_log2abundance), 4)}
                       for r in sub.itertuples()]}


def read_rna_protein_scatter(target: str, release_pin: str = "26q1") -> dict:
    """Per-model paired points for the Q5 scatter figure (RNA x, protein y). data-gap-safe."""
    rna_by_model, prot_by_model, note = _paired_rna_protein(target, release_pin=release_pin)
    if not rna_by_model or not prot_by_model:
        return {"available": False, "points": [], "_note": note}
    common = sorted(set(rna_by_model) & set(prot_by_model))
    return {"available": bool(common),
            "points": [{"model_id": m, "rna": round(float(rna_by_model[m]), 4),
                        "protein": round(float(prot_by_model[m]), 4)} for m in common]}
