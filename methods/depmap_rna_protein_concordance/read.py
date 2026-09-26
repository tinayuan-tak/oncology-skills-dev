"""Q5 RNA↔protein concordance assembler (cell-line). Joins per-ModelID target RNA vs protein,
computes correlation + detection fractions + the rna_as_biomarker verdict. data_unavailable-safe.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from methods.catalog_query.read import bucket_key_for

# concordance thresholds (correlation on paired per-model RNA vs protein; classified on Spearman).
STRONG_CONCORDANCE_R = 0.7  # RNA is an adequate protein proxy
MODERATE_CONCORDANCE_R = 0.4  # RNA is a partial proxy; interpret with caution
MIN_PAIRED_MODELS = 20  # below this the correlation is underpowered
# Confident-class bar: at n between MIN_PAIRED_MODELS and this the single pooled correlation is
# CI-fragile (the class can flip by sampling alone), so a near-floor class is flagged underpowered
# (verdict-INERT — the class is unchanged) rather than emitted as a confident call (F2).
ADEQUATE_POWER_N = 30
# Protein coverage below this ⇒ Gygi MS left-censoring (MNAR: undetected low-abundance proteins are
# dropped before the correlation) can attenuate r downward, so a poor/partial class may be a
# detection-floor artifact rather than genuine post-transcriptional decoupling (F1). Verdict-INERT.
DETECTION_LIMITED_FRACTION = 0.5
# RNA "expressed" / protein "detected" floors (log2 units; RNA matches stats.py detectable).
DETECTABLE_LOG2TPM = 1.0
# Fisher-z SE coefficient for the classifying correlation's 95% CI. Pearson = 1.0; the Spearman rank
# correlation's Fisher-z SE is ~6% larger (≈1.06/sqrt(n-3), Fieller/Bonett-Wright), so a Spearman-
# classified band built with the Pearson coefficient is ~6% too narrow and UNDER-reports fragility (F3).
PEARSON_FISHER_Z_SE_COEFF = 1.0
SPEARMAN_FISHER_Z_SE_COEFF = 1.06


def _paired_rna_protein(target: str, release_pin: str = "26q3"):
    """Per-ModelID paired (rna_log2tpm, protein_log2abundance) for target across DepMap cell lines.
    Reuses the two landed per-model readers (RNA = card4 S3 matrix; protein = Gygi MS).
    Returns (rna_by_model, protein_by_model, note) — note is a data-gap string or None."""
    from methods.depmap_expression_dependency import cli as _rna
    from methods.depmap_protein_abundance import cli as _prot

    try:
        _ch, rna_by_model, _meta, errs = _rna.load_depmap_files_for_card4(release_pin=release_pin, target_symbol=target)
    except Exception as e:  # noqa: BLE001
        return {}, {}, f"RNA load failed: {type(e).__name__}"
    if errs or not rna_by_model:
        return {}, {}, (errs[0].get("_live_read_error") if errs else "no model RNA")
    # Protein arm: guard symmetrically with the RNA arm above. resolve_accession/load_abundance_column
    # RAISE on transient S3, creds/broken-env (ProfileNotFound), or the schema-drift ValueError; those
    # must degrade to an honest data_unavailable rather than crash the data_unavailable-safe reader.
    # Genuine absence (acc is None, or an empty column) is preserved as its own "not quantified" note.
    try:
        acc = _prot.resolve_accession(target)
        if acc is None:
            return rna_by_model, {}, "target has no UniProt accession in the Gygi MS sidecar"
        prot_by_model, _panel = _prot.load_abundance_column(acc)
    except Exception as e:  # noqa: BLE001
        return rna_by_model, {}, f"protein load failed: {type(e).__name__}"
    if not prot_by_model:
        return rna_by_model, {}, "target not quantified in the Gygi MS panel"
    return rna_by_model, prot_by_model, None


def read_rna_protein_concordance(
    target: str, release_pin: str = "26q3", plot_data_out: "Optional[Path]" = None
) -> dict:
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
                    Path(plot_data_out) / "plot_data_rna_protein.parquet", index=False
                )
        except Exception:  # noqa: BLE001 — persistence best-effort; never break the verdict read
            pass
    rna_by_model, prot_by_model, note = _paired_rna_protein(target, release_pin=release_pin)
    base = {"target": target, "release_pin": release_pin}
    if not rna_by_model or not prot_by_model:
        base.update(
            {
                "rna_as_biomarker": "data_unavailable",
                "rna_protein_r": None,
                "n_paired_models": 0,
                "_data_note": note or "no paired RNA/protein",
            }
        )
        return base

    import numpy as np

    common = sorted(set(rna_by_model) & set(prot_by_model))
    n = len(common)
    if n < MIN_PAIRED_MODELS:
        base.update(
            {
                "rna_as_biomarker": "insufficient_paired_models",
                "rna_protein_r": None,
                "n_paired_models": n,
                "_data_note": f"only {n} models have BOTH RNA + protein (floor {MIN_PAIRED_MODELS})",
            }
        )
        return base

    rna = np.array([rna_by_model[m] for m in common], dtype=float)
    prot = np.array([prot_by_model[m] for m in common], dtype=float)
    # zero-variance guard: a constant arm makes the correlation undefined (NaN). Report it as an
    # honest coverage gap rather than a NaN r (a target expressed identically across all lines, or a
    # single-value protein column, carries no concordance signal).
    if np.ptp(rna) == 0 or np.ptp(prot) == 0:
        base.update(
            {
                "rna_as_biomarker": "insufficient_paired_models",
                "rna_protein_r": None,
                "n_paired_models": n,
                "_data_note": "RNA or protein is constant across paired models (correlation undefined)",
            }
        )
        return base
    # Pearson + Spearman (best-effort on scipy; numpy fallback for Pearson).
    try:
        from scipy.stats import pearsonr, spearmanr

        pear = float(pearsonr(rna, prot)[0])
        spear = float(spearmanr(rna, prot)[0])
    except Exception:  # noqa: BLE001
        pear = float(np.corrcoef(rna, prot)[0, 1])
        spear = None

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
        "rna_high_protein_low_fraction": (
            round(rna_high_protein_low / n_rna_expressed, 4) if n_rna_expressed else None
        ),
    }
    out.update(base)
    # Classify on Spearman (G10) — the consensus rank metric for the nonlinear mRNA↔protein relationship;
    # fall back to Pearson only when scipy is unavailable (spear is None). rna_protein_r stays Pearson.
    _classify_r = spear if spear is not None else pear
    _on_spearman = spear is not None
    rna_class = _classify_rna_biomarker(_classify_r, n)
    out["rna_as_biomarker"] = rna_class
    out["rna_proxy_classified_on"] = "spearman" if _on_spearman else "pearson_fallback"
    # G10/F3: Fisher-z CI + boundary-fragility flag, built with the SE coefficient of the classifying
    # metric (Spearman ≈1.06 vs Pearson 1.0) so a Spearman-classified band is not ~6% too narrow.
    out.update(_proxy_boundary_ci(_classify_r, n, spearman=_on_spearman))
    # F1/F2: verdict-INERT honesty qualifiers (never change rna_as_biomarker). Detection fraction lets
    # a consumer tell a poor/partial call driven by MS under-detection from genuine decoupling.
    out.update(_proxy_qualifiers(rna_class, n, protein_detection_fraction=out["protein_detection_fraction"]))
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


def _proxy_boundary_ci(r, n_paired, spearman: bool = True) -> dict:
    """G10 refinement: the Fisher-z 95% CI of the classifying correlation + whether it STRADDLES an
    rna_as_biomarker class boundary (0.4 / 0.7). At small n the r estimate is wide (at n=20 the 95% CI
    half-width is ~±0.35), so the adequate/partial/poor qualifier can flip by sampling alone. This
    surfaces that instability as a verdict-INERT flag — it never changes rna_as_biomarker (a consumer
    can down-weight a boundary-fragile call). Returns rna_protein_r_ci95_low/high +
    rna_proxy_class_boundary_fragile (None when the CI can't be formed: r None, or n<=3).

    F3: the classifying r is normally SPEARMAN, whose Fisher-z SE is ~6% larger than Pearson's
    (≈1.06/sqrt(n-3), Fieller/Bonett-Wright). Building it with the Pearson SE makes the band ~6% too
    narrow and UNDER-reports fragility. `spearman` selects the coefficient; default True (the classifying
    metric), Pearson only when scipy is unavailable and the class fell back to Pearson."""
    if r is None or n_paired is None or n_paired <= 3:
        return {
            "rna_protein_r_ci95_low": None,
            "rna_protein_r_ci95_high": None,
            "rna_proxy_class_boundary_fragile": None,
        }
    rc = max(min(float(r), 0.999999), -0.999999)  # atanh is undefined at |r|==1
    z = math.atanh(rc)
    coeff = SPEARMAN_FISHER_Z_SE_COEFF if spearman else PEARSON_FISHER_Z_SE_COEFF
    se = coeff / math.sqrt(n_paired - 3)  # Fisher-z standard error (Spearman SE ~6% wider than Pearson)
    lo = math.tanh(z - 1.96 * se)
    hi = math.tanh(z + 1.96 * se)
    fragile = any(lo <= b <= hi for b in (MODERATE_CONCORDANCE_R, STRONG_CONCORDANCE_R))
    return {
        "rna_protein_r_ci95_low": round(lo, 4),
        "rna_protein_r_ci95_high": round(hi, 4),
        "rna_proxy_class_boundary_fragile": bool(fragile),
    }


def _proxy_qualifiers(rna_class, n_paired, protein_detection_fraction=None) -> dict:
    """Verdict-INERT honesty qualifiers on the pooled rna_as_biomarker class (they NEVER change it).

    rna_proxy_underpowered (F2): the pooled correlation has no strata, and between MIN_PAIRED_MODELS
      (20) and the ≥30 confident bar the adequate/partial/poor class is CI-fragile and can flip by
      sampling alone. True when n_paired < ADEQUATE_POWER_N, so a consumer can treat a near-floor class
      as soft/exploratory without the method demoting it.
    rna_proxy_detection_limited (F1): Gygi MS is sparse and undetected (low-abundance) proteins are
      dropped before the correlation (MNAR left-censoring), which attenuates r downward. When the class
      is poor/partial AND protein coverage is low (< DETECTION_LIMITED_FRACTION), the discordance may be
      a detection-floor artifact rather than genuine post-transcriptional decoupling. None when the
      detection fraction is unavailable (e.g. the tumor arm reads a per-sample matched product)."""
    underpowered = n_paired is not None and n_paired < ADEQUATE_POWER_N
    detection_limited = None
    if protein_detection_fraction is not None:
        detection_limited = bool(
            rna_class in ("poor_proxy", "partial_proxy") and protein_detection_fraction < DETECTION_LIMITED_FRACTION
        )
    return {
        "rna_proxy_underpowered": bool(underpowered),
        "rna_proxy_detection_limited": detection_limited,
    }


# ---- TUMOR arm (CPTAC matched RNA+protein, cptac-rna-protein-matched-per-sample-v1) ------------
# The tumor analogue of the cell-line concordance above. Reads the matched product (one row per
# (cohort, patient_id, gene, rna_log2tpm, protein_log2abundance)) and computes the SAME correlation
# + rna_as_biomarker classification per the indication's CPTAC cohort. Tumor concordance is a
# DISTINCT signal from cell-line (purity/stroma noise; strongly gene-specific).
CPTAC_MATCHED_MANIFEST_ID = "cptac-rna-protein-matched-per-sample-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, CPTAC_MATCHED_KEY = bucket_key_for(CPTAC_MATCHED_MANIFEST_ID)
MIN_PAIRED_TUMORS = 20
# Columns the tumor arm consumes — projected at read time so the parquet reader
# materializes only these (not the full gene×patient matrix). cohort is the read
# filter (need not be projected).
_MATCHED_COLUMNS = ["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"]

# Module-level S3FileSystem singleton (OPT-2): reconstructing pafs.S3FileSystem()
# on every cohort read is wasteful for umbrella indications that loop leaf cohorts.
_S3FS = None


def _s3_filesystem():
    """Lazily construct + cache the module-level pyarrow S3FileSystem singleton."""
    global _S3FS
    if _S3FS is None:
        import pyarrow.fs as pafs  # sibling-standard S3 reader (see dgidb_drug_gene/read.py)

        _S3FS = pafs.S3FileSystem()
    return _S3FS


# indication → CPTAC cohort code (the 10 cohorts in the matched product).
INDICATION_TO_CPTAC_COHORT = {
    "BRCA": "brca",
    "KIRC": "ccrcc",
    "CCRCC": "ccrcc",
    "COADREAD": "coad",
    "COAD": "coad",
    "READ": "coad",
    "GBM": "gbm",
    "HNSC": "hnscc",
    "HNSCC": "hnscc",
    "LUSC": "lscc",
    "LSCC": "lscc",
    "LUAD": "luad",
    "OV": "ov",
    "PAAD": "pdac",
    "PDAC": "pdac",
    "UCEC": "ucec",
}


def _cptac_cohorts_for(indication: str) -> list[str]:
    """CPTAC matched-cohort codes for an indication, expanding an umbrella (NSCLC → luad+lscc) to its
    LEAF cohorts (CPTAC has no pooled NSCLC row). Each member OncoTree code is mapped through
    INDICATION_TO_CPTAC_COHORT; unmapped members drop out. Single-element for a leaf indication."""
    from methods.indication_aliases import indication_leaf_codes

    seen, out = set(), []
    for leaf in indication_leaf_codes(indication):
        c = INDICATION_TO_CPTAC_COHORT.get(leaf.upper().strip())
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _read_matched_cohorts_map(cohorts: list[str], target: "Optional[str]" = None) -> dict:
    """Read the matched CPTAC product PER leaf cohort → {cohort_code: DataFrame}. The per-cohort split
    is what lets the tumor arm compute stratified correlations (F3) instead of pooling independently
    normalized bcm batches (manifest:104) into one number. When target is given the gene predicate is
    pushed down per cohort (OPT-1)."""
    return {c: _read_matched_cohort(c, target=target) for c in cohorts}


def _read_matched_cohorts(cohorts: list[str], target: "Optional[str]" = None):
    """Read + row-concat the matched CPTAC product across one or more leaf cohorts (pooled NSCLC).
    When target is given the gene predicate is pushed down to the parquet reader (OPT-1)."""
    return _concat_matched(_read_matched_cohorts_map(cohorts, target=target), cohorts, target=target)


def _concat_matched(frames_by_cohort: dict, cohorts: list[str], target: "Optional[str]" = None):
    """Row-concat the per-cohort matched frames into the pooled frame (shared by _read_matched_cohorts
    and the tumor render, so a render reads each cohort exactly once)."""
    import pandas as pd

    frames = [f for f in frames_by_cohort.values() if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else _read_matched_cohort(cohorts[0], target=target)


def _read_matched_cohort(cohort: str, target: "Optional[str]" = None):
    """Read the matched CPTAC product for one cohort → DataFrame[patient_id, gene, rna_log2tpm,
    protein_log2abundance]. Empty on any read failure (data_unavailable-safe).

    OPT-1: project only the consumed columns and push the gene predicate down when target is
    given, so the reader materializes one gene's rows rather than the whole cohort gene×patient
    matrix. Output is identical to the prior "read whole cohort, filter gene in pandas" path."""
    import pandas as pd

    try:
        import pyarrow.parquet as pq

        # pyarrow.fs (not s3fs — the ONLY module importing s3fs, which is absent from pixi.toml so
        # this reader crashed at import in the pixi runtime, cards review 2026-08-17, S2). The
        # S3FileSystem is a module-level singleton (OPT-2), not reconstructed per cohort.
        fs = _s3_filesystem()
        filters = [("cohort", "==", cohort)]
        if target is not None:
            filters.append(("gene", "==", target.upper().strip()))
        tbl = pq.read_table(
            f"{S3_BUCKET}/{CPTAC_MATCHED_KEY}", filesystem=fs, columns=_MATCHED_COLUMNS, filters=filters
        )
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


def _tumor_confounds(rna_class, n_cohorts: int) -> list[str]:
    """Verdict-INERT tumor-specific caveats on rna_as_biomarker (they NEVER change it). Names the
    confounds that can drive a LOW tumor class independent of genuine post-transcriptional biology, so
    a consumer can gate a poor/partial tumor concordance the way the cell-line arm's detection/power
    qualifiers gate the cell-line class:

      lod_mnar_attenuation (F1)          — the matched product is a BUILD-TIME inner-join that drops
        NaN pairs (manifest:34), so below-LOD protein is MNAR left-censored before this reader ever
        sees it. Unlike the cell-line arm there is NO recoverable protein_detection_fraction here (the
        censored rows are gone), so a poor/partial r may be a MS detection-floor artifact rather than
        real decoupling — and the fraction cannot be surfaced to distinguish the two.
      bulk_purity_stromal_admixture (F2) — bulk-tumor purity + stromal admixture dilute the protein
        signal (manifest:12-14), strongly gene-specific, and are indistinguishable from genuine
        post-transcriptional decoupling in the emitted class; no cell-line analogue (cell lines have no
        stroma).
      cross_cohort_pooling (F3)          — >1 independently-normalized bcm cohort pooled into one
        correlation (manifest:104 — bcm abundance is NOT cross-comparable across cohorts), risking a
        Simpson's/batch artifact; see rna_proxy_per_cohort for the stratified view.

    F1/F2 threaten a spuriously LOW correlation, so they attach only to poor/partial classes (an
    adequate_proxy survived the attenuation); F3 is a pooling property independent of the class."""
    tags: list[str] = []
    if rna_class in ("poor_proxy", "partial_proxy"):
        tags += ["lod_mnar_attenuation", "bulk_purity_stromal_admixture"]
    if n_cohorts > 1:
        tags.append("cross_cohort_pooling")
    return tags


def _per_cohort_concordance(frames_by_cohort: dict, target: str) -> list[dict]:
    """F3: per-cohort Spearman/Pearson (verdict-INERT) so a consumer can detect a Simpson's/batch
    artifact from pooling the independently-normalized bcm cohorts (manifest:104) into one correlation.
    Returns [{cohort, n, spearman, pearson}] sorted by cohort; correlation is None where a cohort has
    <4 matched tumors or a constant arm (undefined). Computed on the same gene-filtered, NaN-dropped
    population as the pooled headline, per leaf cohort."""
    import numpy as np

    tgt = target.upper().strip()
    out: list[dict] = []
    for cohort in sorted(frames_by_cohort):
        f = frames_by_cohort[cohort]
        sub = f[f["gene"] == tgt] if not f.empty else f
        sub = sub.dropna(subset=["rna_log2tpm", "protein_log2abundance"]) if not sub.empty else sub
        n = len(sub)
        spear = pear = None
        if n >= 4:
            rna = sub["rna_log2tpm"].to_numpy(dtype=float)
            prot = sub["protein_log2abundance"].to_numpy(dtype=float)
            if np.ptp(rna) > 0 and np.ptp(prot) > 0:
                try:
                    from scipy.stats import pearsonr, spearmanr

                    spear = round(float(spearmanr(rna, prot)[0]), 4)
                    pear = round(float(pearsonr(rna, prot)[0]), 4)
                except Exception:  # noqa: BLE001 — scipy-unavailable fallback (Pearson only)
                    pear = round(float(np.corrcoef(rna, prot)[0, 1]), 4)
        out.append({"cohort": cohort, "n": n, "spearman": spear, "pearson": pear})
    return out


def read_tumor_rna_protein_concordance(target: str, indication: str, plot_data_out: "Optional[Path]" = None) -> dict:
    """Q5 TUMOR arm — CPTAC matched tumor RNA↔protein concordance for target in the indication's
    CPTAC cohort. Same correlation + rna_as_biomarker vocab as the cell-line arm. data_unavailable-safe.

    plot_data_out (figure Stage 6): OPT-IN — persist the per-tumor scatter points
    (plot_data_rna_protein_tumor.parquet) so the figure renders offline. Best-effort."""
    cohorts = _cptac_cohorts_for(indication)
    cohort = "+".join(cohorts) if cohorts else None  # e.g. "luad+lscc" for the NSCLC umbrella
    base = {"target": target, "indication": indication, "cptac_cohort": cohort, "substrate": "cptac_tumor"}
    if not cohorts:
        base.update(
            {
                "rna_as_biomarker": "data_unavailable",
                "rna_protein_r": None,
                "n_paired_tumors": 0,
                "_data_note": "no CPTAC cohort for this indication",
            }
        )
        return base
    # OPT-2: read the matched frame ONCE per render and reuse it for the plot-data persistence
    # (scatter), the pooled verdict, AND the F3 per-cohort stratification — reading each leaf cohort
    # exactly once. frames_by_cohort keeps the leaves separate so pooling artifacts are recoverable.
    frames_by_cohort = _read_matched_cohorts_map(cohorts, target)
    df = _concat_matched(frames_by_cohort, cohorts, target=target)
    if plot_data_out is not None:
        try:
            import pandas as _pd

            pts = (_scatter_from_frame(df, target, cohort).get("points")) or []
            if pts:
                Path(plot_data_out).mkdir(parents=True, exist_ok=True)
                _pd.DataFrame([{"rna": p["rna"], "protein": p["protein"]} for p in pts]).to_parquet(
                    Path(plot_data_out) / "plot_data_rna_protein_tumor.parquet", index=False
                )
        except Exception:  # noqa: BLE001 — persistence best-effort
            pass
    sub = df[df["gene"] == target.upper().strip()] if not df.empty else df
    sub = sub.dropna(subset=["rna_log2tpm", "protein_log2abundance"]) if not sub.empty else sub
    n = len(sub)
    if n < MIN_PAIRED_TUMORS:
        base.update(
            {
                "rna_as_biomarker": ("data_unavailable" if n == 0 else "insufficient_paired_tumors"),
                "rna_protein_r": None,
                "n_paired_tumors": n,
                "_data_note": (
                    f"{cohort}: {n} tumors with matched RNA+protein for {target} (floor {MIN_PAIRED_TUMORS})"
                ),
            }
        )
        return base
    import numpy as np

    rna = sub["rna_log2tpm"].to_numpy(dtype=float)
    prot = sub["protein_log2abundance"].to_numpy(dtype=float)
    if np.ptp(rna) == 0 or np.ptp(prot) == 0:
        base.update(
            {
                "rna_as_biomarker": "insufficient_paired_tumors",
                "rna_protein_r": None,
                "n_paired_tumors": n,
                "_data_note": "RNA or protein constant across tumors",
            }
        )
        return base
    try:
        from scipy.stats import pearsonr, spearmanr

        pear = float(pearsonr(rna, prot)[0])
        spear = float(spearmanr(rna, prot)[0])
    except Exception:  # noqa: BLE001
        pear = float(np.corrcoef(rna, prot)[0, 1])
        spear = None
    _classify_r = spear if spear is not None else pear  # G10: classify on Spearman (Pearson fallback)
    _on_spearman = spear is not None
    tumor_class = _classify_rna_biomarker(_classify_r, n)
    base.update(
        {
            "rna_protein_r": round(pear, 4),
            "rna_protein_spearman": (round(spear, 4) if spear is not None else None),
            "n_paired_tumors": n,
            "rna_as_biomarker": tumor_class,
            "rna_proxy_classified_on": "spearman" if _on_spearman else "pearson_fallback",
            # G10/F3: CI built with the classifying metric's SE coefficient (Spearman ~6% wider).
            **_proxy_boundary_ci(_classify_r, n, spearman=_on_spearman),
            # F2 (symmetric): verdict-INERT near-floor power flag. protein_detection_fraction is None —
            # the matched CPTAC product is a build-time inner-join, so the cell-line-style detection
            # fraction is unrecoverable here (rna_proxy_detection_limited stays None; see F1 below).
            **_proxy_qualifiers(tumor_class, n, protein_detection_fraction=None),
            # #741 tumor-specific verdict-INERT qualifiers (never change rna_as_biomarker):
            #   F1 (MS LOD/MNAR) + F2 (bulk purity/stromal admixture) attach to poor/partial classes;
            #   F3 (cross-cohort pooling) flags an umbrella + surfaces the per-cohort stratified view.
            "rna_proxy_tumor_confounds": _tumor_confounds(tumor_class, len(cohorts)),
            "rna_proxy_cross_cohort_pooled": bool(len(cohorts) > 1),
            "rna_proxy_per_cohort": _per_cohort_concordance(frames_by_cohort, target),
        }
    )
    return base


def _scatter_from_frame(df, target: str, cohort: "Optional[str]") -> dict:
    """Build the scatter dict from an already-read matched frame (shared by the public scatter
    reader and the concordance render's plot-data persistence, so a render reads the cohort once)."""
    sub = df[df["gene"] == target.upper().strip()] if not df.empty else df
    sub = sub.dropna(subset=["rna_log2tpm", "protein_log2abundance"]) if not sub.empty else sub
    return {
        "available": bool(len(sub)),
        "cptac_cohort": cohort,
        "points": [
            {
                "patient_id": r.patient_id,
                "rna": round(float(r.rna_log2tpm), 4),
                "protein": round(float(r.protein_log2abundance), 4),
            }
            for r in sub.itertuples()
        ],
    }


def read_tumor_rna_protein_scatter(target: str, indication: str) -> dict:
    """Per-tumor paired points for the Q5 TUMOR scatter figure. data-gap-safe."""
    cohorts = _cptac_cohorts_for(indication)
    if not cohorts:
        return {"available": False, "points": [], "cptac_cohort": None}
    cohort = "+".join(cohorts)
    df = _read_matched_cohorts(cohorts, target)
    return _scatter_from_frame(df, target, cohort)


def read_rna_protein_scatter(target: str, release_pin: str = "26q3") -> dict:
    """Per-model paired points for the Q5 scatter figure (RNA x, protein y). data-gap-safe."""
    rna_by_model, prot_by_model, note = _paired_rna_protein(target, release_pin=release_pin)
    if not rna_by_model or not prot_by_model:
        return {"available": False, "points": [], "_note": note}
    common = sorted(set(rna_by_model) & set(prot_by_model))
    return {
        "available": bool(common),
        "points": [
            {"model_id": m, "rna": round(float(rna_by_model[m]), 4), "protein": round(float(prot_by_model[m]), 4)}
            for m in common
        ],
    }
