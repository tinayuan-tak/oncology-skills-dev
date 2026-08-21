"""Q5 RNA↔protein concordance assembler (cell-line). Joins per-ModelID target RNA vs protein,
computes correlation + detection fractions + the rna_as_biomarker verdict. data_unavailable-safe.
"""
from __future__ import annotations

import math
from typing import Optional
from pathlib import Path

from methods.catalog_query.read import bucket_key_for

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


def read_rna_protein_concordance(target: str, release_pin: str = "26q1",
                                 plot_data_out: "Optional[Path]" = None) -> dict:
    """Q5 assembler — cell-line RNA↔protein concordance for target. target-grain (no indication).

    Returns rna_protein_r (Pearson) + spearman + n_paired_models + detection fractions +
    rna_high_protein_low_fraction (the RNA-misleads population) + rna_as_biomarker verdict.

    plot_data_out (figure Stage 6): OPT-IN — persist the per-model scatter points
    (plot_data_rna_protein.parquet) so the figure renders offline. Best-effort, verdict-inert."""
    if plot_data_out is not None:
        try:
            import pandas as _pd
            pts = (read_rna_protein_scatter(target, release_pin=release_pin).get("points")) or []
            if pts:
                Path(plot_data_out).mkdir(parents=True, exist_ok=True)
                _pd.DataFrame([{"rna": p["rna"], "protein": p["protein"]} for p in pts]).to_parquet(
                    Path(plot_data_out) / "plot_data_rna_protein.parquet", index=False)
        except Exception:  # noqa: BLE001 — persistence best-effort; never break the verdict read
            pass
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
    # Classify on Spearman (G10) — the consensus rank metric for the nonlinear mRNA↔protein relationship;
    # fall back to Pearson only when scipy is unavailable (spear is None). rna_protein_r stays Pearson.
    _classify_r = spear if spear is not None else pear
    out["rna_as_biomarker"] = _classify_rna_biomarker(_classify_r, n)
    out["rna_proxy_classified_on"] = "spearman" if spear is not None else "pearson_fallback"
    out.update(_proxy_boundary_ci(_classify_r, n))   # G10: Fisher-z CI + boundary-fragility flag
    return out


def _classify_rna_biomarker(r, n_paired) -> str:
    """Categorical for the card/rules, classified on the SPEARMAN rank correlation (see caller):
      adequate_proxy  — RNA tracks protein tightly (r >= 0.7): RNA biomarker/inference trustworthy
      partial_proxy   — moderate (0.4 <= r < 0.7): RNA is a partial proxy, interpret with caution
      poor_proxy      — decoupled (r < 0.4): RNA misleads; protein must be measured directly
      insufficient_paired_models / data_unavailable — handled by the caller.

    G10 (tumor-presence expert review): classify on SPEARMAN, not Pearson. The mRNA↔protein relationship
    across samples is monotonic-but-nonlinear and outlier-prone (post-transcriptional buffering,
    saturation), so the rank correlation is the consensus proteogenomics metric (Zhang 2014, Mertins
    2016) and is less flip-prone than Pearson at the same n. The caller passes Spearman (falling back to
    Pearson only when scipy is unavailable)."""
    if r is None:
        return "data_unavailable"
    if r >= STRONG_CONCORDANCE_R:
        return "adequate_proxy"
    if r >= MODERATE_CONCORDANCE_R:
        return "partial_proxy"
    return "poor_proxy"


def _proxy_boundary_ci(r, n_paired) -> dict:
    """G10 refinement: the Fisher-z 95% CI of the classifying correlation + whether it STRADDLES an
    rna_as_biomarker class boundary (0.4 / 0.7). At small n the r estimate is wide (at n=20 the 95% CI
    half-width is ~±0.35), so the adequate/partial/poor qualifier can flip by sampling alone. This
    surfaces that instability as a verdict-INERT flag — it never changes rna_as_biomarker (a consumer
    can down-weight a boundary-fragile call). Returns rna_protein_r_ci95_low/high +
    rna_proxy_class_boundary_fragile (None when the CI can't be formed: r None, or n<=3)."""
    if r is None or n_paired is None or n_paired <= 3:
        return {"rna_protein_r_ci95_low": None, "rna_protein_r_ci95_high": None,
                "rna_proxy_class_boundary_fragile": None}
    rc = max(min(float(r), 0.999999), -0.999999)   # atanh is undefined at |r|==1
    z = math.atanh(rc)
    se = 1.0 / math.sqrt(n_paired - 3)              # Fisher-z standard error
    lo = math.tanh(z - 1.96 * se)
    hi = math.tanh(z + 1.96 * se)
    fragile = any(lo <= b <= hi for b in (MODERATE_CONCORDANCE_R, STRONG_CONCORDANCE_R))
    return {"rna_protein_r_ci95_low": round(lo, 4), "rna_protein_r_ci95_high": round(hi, 4),
            "rna_proxy_class_boundary_fragile": bool(fragile)}


# ---- TUMOR arm (CPTAC matched RNA+protein, cptac-rna-protein-matched-per-sample-v1) ------------
# The tumor analogue of the cell-line concordance above. Reads the matched product (one row per
# (cohort, patient_id, gene, rna_log2tpm, protein_log2abundance)) and computes the SAME correlation
# + rna_as_biomarker classification per the indication's CPTAC cohort. Tumor concordance is a
# DISTINCT signal from cell-line (purity/stroma noise; strongly gene-specific).
CPTAC_MATCHED_MANIFEST_ID = "cptac-rna-protein-matched-per-sample-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, CPTAC_MATCHED_KEY = bucket_key_for(CPTAC_MATCHED_MANIFEST_ID)
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
        import pyarrow.fs as pafs   # was s3fs — the ONLY module importing it; s3fs is absent from
                                    # pixi.toml so this reader crashed at import in the pixi runtime
                                    # (cards review 2026-08-17, S2). pyarrow.fs.S3FileSystem is the
                                    # sibling-standard S3 reader (see dgidb_drug_gene/read.py).
        fs = pafs.S3FileSystem()
        tbl = pq.read_table(f"{S3_BUCKET}/{CPTAC_MATCHED_KEY}", filesystem=fs,
                            filters=[("cohort", "==", cohort)])
        return tbl.to_pandas()
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # Only a GENUINELY missing object (NoSuchKey/404, or pyarrow FileNotFoundError) is data
        # absence -> empty frame (unchanged data_unavailable). A transient/creds/broken-env failure is
        # NOT absence -> re-raise so it surfaces as an honest _live_read_error, never a silent empty
        # cohort (which would read as "no matched tumors" and dead-axe the concordance verdict).
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return pd.DataFrame(columns=["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"])
        raise


def read_tumor_rna_protein_concordance(target: str, indication: str,
                                       plot_data_out: "Optional[Path]" = None) -> dict:
    """Q5 TUMOR arm — CPTAC matched tumor RNA↔protein concordance for target in the indication's
    CPTAC cohort. Same correlation + rna_as_biomarker vocab as the cell-line arm. data_unavailable-safe.

    plot_data_out (figure Stage 6): OPT-IN — persist the per-tumor scatter points
    (plot_data_rna_protein_tumor.parquet) so the figure renders offline. Best-effort."""
    if plot_data_out is not None:
        try:
            import pandas as _pd
            pts = (read_tumor_rna_protein_scatter(target, indication).get("points")) or []
            if pts:
                Path(plot_data_out).mkdir(parents=True, exist_ok=True)
                _pd.DataFrame([{"rna": p["rna"], "protein": p["protein"]} for p in pts]).to_parquet(
                    Path(plot_data_out) / "plot_data_rna_protein_tumor.parquet", index=False)
        except Exception:  # noqa: BLE001 — persistence best-effort
            pass
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
    _classify_r = spear if spear is not None else pear   # G10: classify on Spearman (Pearson fallback)
    base.update({
        "rna_protein_r": round(pear, 4),
        "rna_protein_spearman": (round(spear, 4) if spear is not None else None),
        "n_paired_tumors": n,
        "rna_as_biomarker": _classify_rna_biomarker(_classify_r, n),
        "rna_proxy_classified_on": "spearman" if spear is not None else "pearson_fallback",
        **_proxy_boundary_ci(_classify_r, n),   # G10: Fisher-z CI + boundary-fragility flag
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
