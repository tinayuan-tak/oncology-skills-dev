#!/usr/bin/env python3
"""depmap-mutation-stratified CLI — Card 3 method.

Consumes DepMap 26Q1:
  - CRISPRGeneEffect.csv (Chronos; reused via depmap_chronos_distribution.cli.load_depmap_files)
  - OmicsSomaticMutationsMatrixHotspot.csv (small fast read; model × gene boolean for known hotspots)
  - OmicsSomaticMutationsMatrixDamaging.csv (model × gene boolean for damaging LOF)
  - OmicsSomaticMutations.csv (long-format MAF; lazy-loaded for per-hotspot detail)
  - Model.csv (lineage context)

For target gene, joins Chronos × mutation status (per matrix) across DepMap models;
runs Mann-Whitney U mut-vs-WT for hotspot + damaging + any-mutation tiers;
emits mut-vs-WT strip plot + per-hotspot strip plot + plot_data + manifest.

API convention from Cards 1+2: load_*, compute_*, emit_*_plot, emit_plot_data,
emit_manifest are PUBLIC helpers consumed by BOTH the CLI and the skill's
figure-emitter registry. No underscore prefix.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import click

from methods.catalog_query.read import bucket_prefix_for, s3_uri_for

METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
DEPMAP_SOURCE_MANIFEST_ID = "depmap-consortium-26q1"
# Resolved from the data-catalog manifest (single source of truth). DEPMAP_S3_PREFIX (s3://-form)
# feeds echo/provenance; _DEPMAP_KEY_PREFIX (bucket-relative) builds the get_object read keys below.
DEPMAP_S3_PREFIX = s3_uri_for(DEPMAP_SOURCE_MANIFEST_ID).rstrip("/")
_DEPMAP_KEY_PREFIX = bucket_prefix_for(DEPMAP_SOURCE_MANIFEST_ID)[1].rstrip("/")
DEPMAP_LOCAL_FALLBACK_DIRS = [
    Path("/data/depmap/26q1"),
    Path.home() / "depmap-26q1",
]

# 5-column metadata prefix common to OmicsExpressionTPM*, OmicsSomaticMutationsMatrix*
MUT_METADATA_COLUMNS = (
    "SequencingID",
    "ModelConditionID",
    "ModelID",
    "IsDefaultEntryForMC",
    "IsDefaultEntryForModel",
)


def _read_mutation_matrix_for_target(release_pin: str, matrix_filename: str, target_symbol: str) -> tuple[dict, list]:
    """Load ONE mutation matrix (hotspot or damaging), filter to default-entries, return
    {ModelID → bool} for the target gene + load_errors list.

    Tier-2 path: parquet with column projection via depmap_common.parquet.
    Legacy fallback: CSV path (local-cache first, then S3 with usecols).
    """
    import pandas as pd

    load_errors = []
    mut_path = None
    for fallback_dir in DEPMAP_LOCAL_FALLBACK_DIRS:
        candidate = fallback_dir / matrix_filename
        if candidate.exists():
            mut_path = candidate
            click.echo(f"  Using local cache for {matrix_filename}", err=True)
            break

    # === TIER-2 PATH: parquet column projection (~530 KB / 12.5 MB pulls vs ~10 MB / 328 MB CSV parses) ===
    if mut_path is None:
        try:
            from methods.depmap_common.parquet import (
                get_damaging_mutation_column,
                get_hotspot_mutation_column,
            )

            if "Hotspot" in matrix_filename:
                target_df = get_hotspot_mutation_column(target_symbol, release_pin)
            elif "Damaging" in matrix_filename:
                target_df = get_damaging_mutation_column(target_symbol, release_pin)
            else:
                target_df = None
            if target_df is not None:
                target_col = next(
                    (
                        c
                        for c in target_df.columns
                        if c not in ("ModelID", "IsDefaultEntryForModel", "IsDefaultEntryForMC")
                    ),
                    None,
                )
                if target_col is not None:
                    # IsDefaultEntryForModel filter (matches CSV path semantics)
                    filt = target_df
                    if "IsDefaultEntryForModel" in filt.columns:
                        filt = filt[filt["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])]
                        if filt.empty:
                            filt = target_df  # defensive fallback
                    id_col = "ModelID" if "ModelID" in filt.columns else filt.columns[0]
                    mut_by_model = {}
                    for _, row in filt[[id_col, target_col]].iterrows():
                        val = row[target_col]
                        if isinstance(val, bool):
                            is_mut = val
                        elif isinstance(val, (int, float)):
                            is_mut = bool(val) if not pd.isna(val) else False
                        elif isinstance(val, str):
                            is_mut = val.strip().lower() in ("true", "1", "yes")
                        else:
                            is_mut = False
                        mut_by_model[row[id_col]] = is_mut
                    return mut_by_model, load_errors
                else:
                    load_errors.append(
                        {
                            "_live_read_error": "target_not_in_mutation_matrix",
                            "detail": f"Target {target_symbol} not in {matrix_filename} (parquet)",
                        }
                    )
                    return {}, load_errors
        except (FileNotFoundError, ImportError):
            pass  # fall through to CSV path

    # === LEGACY CSV PATH ===
    if mut_path is None:
        try:
            import boto3

            s3 = boto3.client("s3")
            bucket = "onc-compbio"
            key = f"{_DEPMAP_KEY_PREFIX}/{matrix_filename}"
            click.echo(f"  Fetching s3://{bucket}/{key}", err=True)
            obj = s3.get_object(Bucket=bucket, Key=key)
            header_df = pd.read_csv(BytesIO(obj["Body"].read(8192)), nrows=0)
            target_cols = [c for c in header_df.columns if c == target_symbol or c.split(" ")[0] == target_symbol]
            if not target_cols:
                load_errors.append(
                    {
                        "_live_read_error": "target_not_in_mutation_matrix",
                        "detail": f"Target {target_symbol} not in {matrix_filename}",
                    }
                )
                return {}, load_errors
            usecols = [c for c in MUT_METADATA_COLUMNS if c in header_df.columns] + [target_cols[0]]
            obj_full = s3.get_object(Bucket=bucket, Key=key)
            df = pd.read_csv(BytesIO(obj_full["Body"].read()), usecols=usecols)
            target_col = target_cols[0]
        except ImportError as e:
            load_errors.append({"_live_read_error": "boto3_not_available", "detail": str(e)})
            return {}, load_errors
        except Exception as e:
            load_errors.append({"_live_read_error": "s3_read_failed", "detail": str(e), "file": matrix_filename})
            return {}, load_errors
    else:
        header_df = pd.read_csv(mut_path, nrows=0)
        target_cols = [c for c in header_df.columns if c == target_symbol or c.split(" ")[0] == target_symbol]
        if not target_cols:
            load_errors.append(
                {
                    "_live_read_error": "target_not_in_mutation_matrix",
                    "detail": f"Target {target_symbol} not in {matrix_filename}",
                }
            )
            return {}, load_errors
        usecols = [c for c in MUT_METADATA_COLUMNS if c in header_df.columns] + [target_cols[0]]
        df = pd.read_csv(mut_path, usecols=usecols)
        target_col = target_cols[0]

    # Filter to default-entry-per-model (DepMap 26Q1 string "Yes"/"No" — same as TPM matrix)
    if "IsDefaultEntryForModel" in df.columns:
        flag = df["IsDefaultEntryForModel"]
        filt = df[flag.isin([True, "Yes", "yes", "true", "TRUE"])]
        if filt.empty:
            filt = df  # defensive fallback if values surprise us
    else:
        filt = df

    model_id_col = "ModelID" if "ModelID" in filt.columns else filt.columns[0]
    mut_by_model = {}
    for _, row in filt[[model_id_col, target_col]].iterrows():
        val = row[target_col]
        # Matrix is boolean — but pandas may load as int (0/1) or str ("True"/"False")
        if isinstance(val, bool):
            is_mut = val
        elif isinstance(val, (int, float)):
            is_mut = bool(val) if not pd.isna(val) else False
        elif isinstance(val, str):
            is_mut = val.strip().lower() in ("true", "1", "yes")
        else:
            is_mut = False
        mut_by_model[row[model_id_col]] = is_mut
    return mut_by_model, load_errors


def load_mutation_data(release_pin: str, target_symbol: str) -> tuple[dict, dict, list]:
    """Load BOTH mutation matrices (hotspot + damaging) for the target gene.

    Returns:
      hotspot_by_model: {ModelID → bool}
      damaging_by_model: {ModelID → bool}
      load_errors: list (non-empty if BOTH failed; hotspot-only/damaging-only is ok)
    """
    hotspot, hot_errs = _read_mutation_matrix_for_target(
        release_pin, "OmicsSomaticMutationsMatrixHotspot.csv", target_symbol
    )
    damaging, dam_errs = _read_mutation_matrix_for_target(
        release_pin, "OmicsSomaticMutationsMatrixDamaging.csv", target_symbol
    )
    combined_errs = []
    if not hotspot and not damaging:
        # both failed
        combined_errs = (hot_errs + dam_errs) or [{"_live_read_error": "no_mutation_data"}]
    return hotspot, damaging, combined_errs


def _mannwhitney_stratification(
    chronos_by_model: dict, mut_by_model: dict, min_mutant: int = 5, min_wildtype: int = 30
) -> dict:
    """Run Mann-Whitney U for a single mut vector, testing BOTH directions.

    The FORWARD test (alternative="less": altered group more dependent / lower Chronos)
    is the primary oncogene-addiction hypothesis and drives `p_value`/`effect_size`
    (byte-identical to the historical one-sided behaviour). A SECOND-PASS reverse test
    (alternative="greater": comparator group more dependent) is ALSO computed so the
    reverse-direction classes (`wt_strongly_dependent` etc.) the classifier advertises
    are genuinely REACHABLE rather than dead branches — this is the "second-pass test"
    the card documents. `p_value_reverse` is significance-gated by the caller exactly
    like the forward p. The reverse direction is TSG-synthetic-dependency biology
    (WT/comparator cells more dependent); it feeds only neutral/inert rules, so surfacing
    it does not move any verdict.

    Returns n/median/p/q/effect fields. q (forward) is filled by the caller's BH step
    across the three tiers. A NaN/uncomputable direction is flagged, never silently
    collapsed to a non-significant null (that would report an uncomputable case as a
    tested negative)."""
    import numpy as np
    from scipy import stats as scipy_stats

    common = set(chronos_by_model.keys()) & set(mut_by_model.keys())
    mut_scores = [chronos_by_model[m] for m in common if mut_by_model[m]]
    wt_scores = [chronos_by_model[m] for m in common if not mut_by_model[m]]
    n_mut = len(mut_scores)
    n_wt = len(wt_scores)

    if n_mut < min_mutant or n_wt < min_wildtype:
        return {
            "n_mutant": int(n_mut),
            "n_wildtype": int(n_wt),
            "median_mutant": float(np.median(mut_scores)) if mut_scores else None,
            "median_wildtype": float(np.median(wt_scores)) if wt_scores else None,
            "delta_mut_vs_wt": None,
            "p_value": None,
            "p_value_reverse": None,
            "q_value": None,  # filled by caller's BH step (will stay None)
            "effect_size": None,
            "_insufficient_data": True,
        }

    mut_arr = np.array(mut_scores)
    wt_arr = np.array(wt_scores)
    median_mut = float(np.median(mut_arr))
    median_wt = float(np.median(wt_arr))
    delta = median_mut - median_wt

    # An uncomputable case is one with NO rank information: zero variance across the combined
    # sample (every Chronos identical) — the U-test is meaningless there. Modern scipy does
    # NOT raise on all-ties (it returns p=1.0 with a tie-corrected U), so detect it explicitly
    # rather than relying on an exception that no longer fires. This distinguishes "tested,
    # not significant" from "could not test" WITHOUT changing any numeric output —
    # the p/effect below stay byte-identical to the historical behaviour.
    combined = np.concatenate([mut_arr, wt_arr])
    uncomputable = bool(np.ptp(combined) == 0.0)

    # Determinism: method + use_continuity are set EXPLICITLY to scipy's current
    # defaults (method="auto", use_continuity=True) — verified byte-identical to leaving them unset
    # (see test_mannwhitney_determinism_pin). This is verdict-NEUTRAL: it does not change any p-value;
    # it makes the exact/asymptotic behaviour version-STABLE and transparent so a future scipy default
    # change cannot silently move results. `method="auto"` uses the EXACT null for a group of n<=8 with
    # no ties (the statistically correct choice at tiny n — Chronos is continuous so ties are rare) and
    # the tie-corrected asymptotic normal approximation for n>=9. We deliberately do NOT force
    # method="asymptotic": that would DEGRADE small-n accuracy (e.g. FLT3 n=5: exact p=1.1e-10 vs
    # asymptotic p=6.4e-5) purely for determinism — the exact test is the right one there, and the pin
    # already gives version-stability without that accuracy loss.
    _MW = dict(alternative="less", method="auto", use_continuity=True)
    try:
        u_stat, p_one_sided = scipy_stats.mannwhitneyu(mut_arr, wt_arr, **_MW)
        # Rank-biserial effect size (signed by the forward direction)
        effect = 1.0 - (2.0 * u_stat) / (n_mut * n_wt)
    except ValueError:
        p_one_sided = 1.0
        effect = 0.0
        uncomputable = True

    # SECOND-PASS REVERSE test: comparator/WT more dependent (higher Chronos in the altered
    # group). This makes the reverse-direction classes the classifier advertises
    # (`wt_strongly_dependent` etc.) genuinely REACHABLE — previously they sat behind a
    # `delta >= +0.3` branch that a one-sided "less" test could never satisfy at significance
    # (a dead branch). The reverse direction is TSG-synthetic-dependency biology and feeds
    # only neutral/inert rules, so surfacing it is verdict-safe. Same determinism pin.
    try:
        _, p_reverse = scipy_stats.mannwhitneyu(
            mut_arr, wt_arr, alternative="greater", method="auto", use_continuity=True
        )
        p_reverse = float(p_reverse)
    except ValueError:
        p_reverse = None

    # ── Dependency-classification PERFORMANCE ──────────────────────────────────────────────
    # Treat the biomarker (mutant/altered = positive) as a CLASSIFIER for the DepMap-dependency
    # phenotype (dependent = Chronos <= DEPENDENT_THRESHOLD, the -0.5 CHRONOS_STRONG_DEPENDENCY
    # convention). This yields honest, computable confusion-matrix metrics ON THE ONE GROUND TRUTH
    # THE FRAMEWORK HAS — DepMap genetic dependency — NOT drug response or a clinical endpoint.
    #   dependency_ppv         = P(dependent | biomarker+)   — of altered lines, how many are dependent
    #   dependency_sensitivity = P(biomarker+ | dependent)   — of dependent lines, how many are altered
    #   dependency_specificity = P(biomarker- | not dependent)
    #   dependency_base_rate   = P(dependent) over the evaluated panel (the PPV null to beat)
    # These are verdict-inert diagnostics; a consumer MUST label them dependency-* (a CRISPR-KO
    # dependency biomarker is not automatically an inhibitor/clinical biomarker — same guardrail the
    # BEST-role _note carries). Reported only when both classes are populated.
    DEPENDENT_THRESHOLD = -0.5
    tp = int(np.sum(mut_arr <= DEPENDENT_THRESHOLD))  # biomarker+ & dependent
    n_dep_wt = int(np.sum(wt_arr <= DEPENDENT_THRESHOLD))  # biomarker- & dependent (FN)
    tn = n_wt - n_dep_wt  # biomarker- & not dependent
    n_dependent = tp + n_dep_wt
    n_total = n_mut + n_wt
    dependency_ppv = (tp / n_mut) if n_mut else None
    dependency_sensitivity = (tp / n_dependent) if n_dependent else None
    dependency_specificity = (tn / (n_total - n_dependent)) if (n_total - n_dependent) else None
    dependency_base_rate = (n_dependent / n_total) if n_total else None
    # PPV LIFT over the base rate: does knowing the biomarker improve the dependency prior?
    dependency_ppv_lift = (
        (dependency_ppv / dependency_base_rate) if (dependency_ppv is not None and dependency_base_rate) else None
    )

    return {
        "n_mutant": int(n_mut),
        "n_wildtype": int(n_wt),
        "median_mutant": median_mut,
        "median_wildtype": median_wt,
        "delta_mut_vs_wt": float(delta),
        "p_value": float(p_one_sided),
        "p_value_reverse": p_reverse,
        "q_value": None,  # filled by caller (forward BH)
        "q_value_reverse": None,  # filled by caller (reverse BH)
        "effect_size": float(effect),
        "_uncomputable": uncomputable,
        # dependency-classification performance — DepMap dependency ground truth only
        "dependency_ppv": dependency_ppv,
        "dependency_sensitivity": dependency_sensitivity,
        "dependency_specificity": dependency_specificity,
        "dependency_base_rate": dependency_base_rate,
        "dependency_ppv_lift": dependency_ppv_lift,
        "dependency_threshold": DEPENDENT_THRESHOLD,
    }


# Indication → DepMap OncotreeLineage. Single source of truth is depmap_chronos
# (lineage-selectivity); imported lazily in the conditioning wrapper to avoid a hard
# module dependency at import time (and to keep the pan-DepMap core dependency-free).
_STRONG_TO_MODERATE_CAP = {
    "mutant_strongly_dependent": "mutant_moderately_dependent",
}


def compute_mutation_stratification(
    chronos_by_model: dict,
    hotspot_by_model: dict,
    damaging_by_model: dict,
    strong_effect_delta: float = -0.5,
    moderate_effect_delta: float = -0.2,
    stratification_alpha: float = 0.05,
) -> dict:
    """Compute Card 3 summary fields — PAN-DepMap core (no lineage conditioning).

    Three tier Mann-Whitney tests: hotspot, damaging, combined-any. BH correction
    applied across the three. mutation_stratification_class categorical is the
    strongest signal. Called with no lineage context, this is BYTE-IDENTICAL to the
    historical behaviour (the existing golden path). Lineage conditioning is layered
    on top by `compute_mutation_stratification_conditioned`."""
    import numpy as np

    # === Three parallel stratification tests ===
    hot = _mannwhitney_stratification(chronos_by_model, hotspot_by_model)
    dam = _mannwhitney_stratification(chronos_by_model, damaging_by_model)

    # Build "any mutation" vector: hotspot OR damaging
    any_by_model = {}
    for m in set(hotspot_by_model.keys()) | set(damaging_by_model.keys()):
        any_by_model[m] = hotspot_by_model.get(m, False) or damaging_by_model.get(m, False)
    any_ = _mannwhitney_stratification(chronos_by_model, any_by_model)

    # BH correction across the 3 tiers, applied to BOTH directions independently. The
    # forward `q_value` is byte-identical to before (same p-set, same math). The reverse
    # `q_value_reverse` is the second-pass family.
    def _bh_across_tiers(pkey: str, qkey: str):
        pvs = [(tk, td[pkey]) for tk, td in [("hot", hot), ("dam", dam), ("any", any_)] if td.get(pkey) is not None]
        if not pvs:
            return
        p_array = np.array([p for _, p in pvs])
        m = len(p_array)
        order = np.argsort(p_array)
        ranks = np.empty_like(order)
        ranks[order] = np.arange(1, m + 1)
        q_unord = np.minimum.accumulate((p_array[order] * m / ranks[order])[::-1])[::-1]
        q_back = np.empty_like(q_unord)
        q_back[order] = q_unord
        tier_map = {"hot": hot, "dam": dam, "any": any_}
        for i, (tk, _) in enumerate(pvs):
            tier_map[tk][qkey] = float(min(1.0, q_back[i]))

    _bh_across_tiers("p_value", "q_value")  # forward (unchanged)
    _bh_across_tiers("p_value_reverse", "q_value_reverse")  # second-pass reverse

    # === Classification ===
    # Prefer hotspot signal if present; otherwise damaging; otherwise any.
    def _classify(tier: dict) -> Optional[str]:
        if tier.get("delta_mut_vs_wt") is None:
            return None
        # FORWARD: mutant more dependent (significant forward q + negative delta).
        if tier.get("q_value") is not None and tier["q_value"] < stratification_alpha:
            if tier["delta_mut_vs_wt"] <= strong_effect_delta:
                return "mutant_strongly_dependent"
            if tier["delta_mut_vs_wt"] <= moderate_effect_delta:
                return "mutant_moderately_dependent"
        # REVERSE (second pass): WT/comparator more dependent — significant REVERSE q AND a
        # positive delta of meaningful size. This is now reachable (was a dead branch under
        # the forward-only test). Verdict-inert (neutral rule only).
        if (
            tier.get("q_value_reverse") is not None
            and tier["q_value_reverse"] < stratification_alpha
            and tier["delta_mut_vs_wt"] >= -strong_effect_delta
        ):  # >= +0.5, mirrors forward "strong"
            return "wt_strongly_dependent"
        return None

    # HOTSPOT-GATED oncogene-addiction: a DIRECTIONAL "mutant more dependent" call
    # (mutant_strongly/moderately_dependent = oncogene-addiction) may be set ONLY from the HOTSPOT
    # (activating) tier. The damaging/"any" tiers POOL activating + LoF + VUS mutations, so a
    # directional call arising ONLY there is biologically unsound (a KRAS-G12C-addicted line and a
    # KRAS-LoF/passenger line would be averaged into one "mutant" arm). The pooled tiers may still
    # corroborate a hotspot call, produce not_mutation_stratified, or surface wt_strongly_dependent —
    # they just cannot MANUFACTURE oncogene-addiction on their own. (Full GoF/LoF role-conditioning of
    # the mutant arm is a larger follow-on; the resolver already conjoins alteration-role into
    # confirmed_driver.)
    _ONCOGENE_ADDICTION = {"mutant_strongly_dependent", "mutant_moderately_dependent"}
    hot_cls = _classify(hot)
    pooled_cls = _classify(dam) or _classify(any_)
    hotspot_gated_note = None
    if hot_cls is not None:
        cls = hot_cls  # hotspot tier is authoritative when present
    elif pooled_cls in _ONCOGENE_ADDICTION:
        # directional call exists ONLY in the pooled tier → do NOT credit oncogene-addiction.
        cls = "not_mutation_stratified"
        hotspot_gated_note = (
            f"pooled-tier {pooled_cls} not credited: no hotspot-tier signal (mixed activating/LoF/VUS "
            "pool cannot establish oncogene-addiction; T2.1 hotspot-gate)"
        )
    else:
        cls = pooled_cls  # wt_strongly_dependent / None pass through
    if cls is None:
        # Check sample-size gating
        if hot.get("_insufficient_data") and dam.get("_insufficient_data"):
            cls = "insufficient_mutation_rate"
        else:
            cls = "not_mutation_stratified"

    n_evaluated = len(set(chronos_by_model.keys()) & (set(hotspot_by_model.keys()) | set(damaging_by_model.keys())))

    return {
        # === Panel coverage ===
        "n_cell_lines_evaluated": int(n_evaluated),
        # === Hotspot tier ===
        "n_hotspot_mutant": hot["n_mutant"],
        "n_hotspot_wildtype": hot["n_wildtype"],
        "median_chronos_hotspot_mutant": hot["median_mutant"],
        "median_chronos_hotspot_wildtype": hot["median_wildtype"],
        "delta_chronos_hotspot_mut_vs_wt": hot["delta_mut_vs_wt"],
        "hotspot_mannwhitney_p": hot["p_value"],
        "hotspot_mannwhitney_q": hot["q_value"],
        "hotspot_mannwhitney_q_reverse": hot.get("q_value_reverse"),
        "hotspot_effect_size": hot["effect_size"],
        # Dependency-classification performance — the hotspot biomarker as a classifier
        # for the DepMap-dependency phenotype (Chronos <= -0.5). DEPENDENCY performance, NOT clinical.
        "hotspot_dependency_ppv": hot.get("dependency_ppv"),
        "hotspot_dependency_sensitivity": hot.get("dependency_sensitivity"),
        "hotspot_dependency_specificity": hot.get("dependency_specificity"),
        "hotspot_dependency_base_rate": hot.get("dependency_base_rate"),
        "hotspot_dependency_ppv_lift": hot.get("dependency_ppv_lift"),
        # === Damaging tier ===
        "n_damaging_mutant": dam["n_mutant"],
        "n_damaging_wildtype": dam["n_wildtype"],
        "median_chronos_damaging_mutant": dam["median_mutant"],
        "median_chronos_damaging_wildtype": dam["median_wildtype"],
        "delta_chronos_damaging_mut_vs_wt": dam["delta_mut_vs_wt"],
        "damaging_mannwhitney_p": dam["p_value"],
        "damaging_mannwhitney_q": dam["q_value"],
        "damaging_mannwhitney_q_reverse": dam.get("q_value_reverse"),
        "damaging_effect_size": dam["effect_size"],
        # === Combined "any mutation" tier ===
        "n_any_mutant": any_["n_mutant"],
        "n_any_wildtype": any_["n_wildtype"],
        "delta_chronos_any_mut_vs_wt": any_["delta_mut_vs_wt"],
        "any_mannwhitney_q": any_["q_value"],
        "any_mannwhitney_q_reverse": any_.get("q_value_reverse"),
        # === Second-pass / uncomputable diagnostics ===
        "stratification_direction": (
            "reverse_wt_dependent"
            if cls == "wt_strongly_dependent"
            else "forward_mutant_dependent"
            if cls in _ONCOGENE_ADDICTION
            else "none"
        ),
        "_uncomputable_tiers": [
            k for k, td in (("hotspot", hot), ("damaging", dam), ("any", any_)) if td.get("_uncomputable")
        ],
        # === Per-hotspot breakdown: reserved, currently always empty (no per-hotspot loader is
        #     wired). The per-hotspot Chronos plot therefore renders its <3-hotspots placeholder. ===
        "per_hotspot_stats": [],
        # === Categorical ===
        "mutation_stratification_class": cls,
        "hotspot_gate_note": hotspot_gated_note,  # set when a pooled-tier oncogene-addiction call was NOT credited
        # === Internal for figure emitters ===
        "_hotspot_by_model": hotspot_by_model,
        "_damaging_by_model": damaging_by_model,
    }


def _resolve_indication_lineage(indication):
    """Indication → DepMap OncotreeLineage via the depmap_chronos single-source map.
    Returns the lineage string or None (unknown indication / no map entry)."""
    if not indication:
        return None
    try:
        from methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE
    except Exception:
        return None
    return INDICATION_TO_DEPMAP_LINEAGE.get(indication)


def _models_in_lineage(model_metadata: dict, lineage: str) -> set:
    """ModelIDs whose OncotreeLineage matches (the lineage universe for conditioning)."""
    if not model_metadata or not lineage:
        return set()
    return {mid for mid, meta in model_metadata.items() if (meta or {}).get("OncotreeLineage") == lineage}


def compute_mutation_stratification_conditioned(
    chronos_by_model: dict,
    hotspot_by_model: dict,
    damaging_by_model: dict,
    model_metadata: dict = None,
    indication: str = None,
    min_mutant: int = 5,
    min_wildtype: int = 30,
    strong_effect_delta: float = -0.5,
    moderate_effect_delta: float = -0.2,
    stratification_alpha: float = 0.05,
) -> dict:
    """Lineage-conditioned mutation-stratified dependency.

    Oncogenic hotspots are lineage-enriched (BRAF-V600E → melanoma/thyroid/CRC), so a
    pan-DepMap "mutant more dependent" contrast can be TISSUE-confounded. This wrapper
    runs the stratification WITHIN the indication's DepMap lineage when powered, and
    records the scope + a within-vs-pan divergence flag. Graceful-degradation ladder
    (matches the card's declared `evidence_scope` vocabulary):

      within_indication              mutant-in-lineage >= min_mutant AND WT-in-lineage >= min_wildtype
      within_indication_mut_vs_pan_wt mutant-in-lineage >= min_mutant, WT-in-lineage < min_wildtype
                                     → lineage-mutants vs the PAN-DepMap WT comparator
      pan_lineage_evidence_only      mutant-in-lineage < min_mutant → fall back to pan-DepMap; a STRONG
                                     call is CAPPED to moderate (the confound is unresolved)
      pan_no_indication              no indication / unmapped lineage / no metadata → pure pan-DepMap

    The pan-DepMap class is ALWAYS computed and preserved as `pan_lineage_mutation_stratification_class`
    (audit); `lineage_context_divergent` is True when the within-lineage direction disagrees with pan.
    Called with model_metadata=None / indication=None this degrades to `pan_no_indication` and returns
    the pan result verbatim (byte-identical to `compute_mutation_stratification`)."""
    # Pan-DepMap baseline (always computed — the audit anchor + the fallback).
    pan = compute_mutation_stratification(
        chronos_by_model,
        hotspot_by_model,
        damaging_by_model,
        strong_effect_delta,
        moderate_effect_delta,
        stratification_alpha,
    )
    pan_class = pan["mutation_stratification_class"]

    lineage = _resolve_indication_lineage(indication)
    lineage_models = _models_in_lineage(model_metadata, lineage)

    def _finish(result, scope, within_class=None):
        result["evidence_scope"] = scope
        result["pan_lineage_mutation_stratification_class"] = pan_class
        result["indication_lineage"] = lineage
        # divergence: a directional within-lineage call that disagrees with the pan direction
        div = False
        if within_class is not None:
            within_dir = _dir(within_class)
            pan_dir = _dir(pan_class)
            div = within_dir is not None and pan_dir is not None and within_dir != pan_dir
        result["lineage_context_divergent"] = bool(div)
        return result

    def _dir(cls):
        if cls in ("mutant_strongly_dependent", "mutant_moderately_dependent"):
            return "mutant"
        if cls == "wt_strongly_dependent":
            return "wt"
        return None

    # pan_no_indication: no usable lineage context → pan result verbatim.
    if not lineage or not lineage_models:
        return _finish(pan, "pan_no_indication")

    # Partition the lineage universe.
    chronos_lin = {m: c for m, c in chronos_by_model.items() if m in lineage_models}
    hot_lin = {m: v for m, v in hotspot_by_model.items() if m in lineage_models}
    dam_lin = {m: v for m, v in damaging_by_model.items() if m in lineage_models}
    n_mut_lin = sum(1 for m in chronos_lin if hot_lin.get(m) or dam_lin.get(m))
    n_wt_lin = sum(1 for m in chronos_lin if not (hot_lin.get(m) or dam_lin.get(m)))

    # within_indication: both arms powered inside the lineage.
    if n_mut_lin >= min_mutant and n_wt_lin >= min_wildtype:
        within = compute_mutation_stratification(
            chronos_lin, hot_lin, dam_lin, strong_effect_delta, moderate_effect_delta, stratification_alpha
        )
        return _finish(within, "within_indication", within["mutation_stratification_class"])

    # within_indication_mut_vs_pan_wt: lineage mutants vs the pan-WT comparator (broadens the
    # WT arm when the lineage has too few WT lines, keeping the mutant arm lineage-pure).
    if n_mut_lin >= min_mutant:
        lin_mut_ids = {m for m in chronos_lin if hot_lin.get(m) or dam_lin.get(m)}
        # chronos over: lineage mutants + ALL pan WT; hotspot/damaging True only for lineage mutants.
        chronos_mix = dict(chronos_lin)  # lineage mutants (+ any lineage WT, harmless — reclassified below)
        pan_wt_ids = {m for m in chronos_by_model if not (hotspot_by_model.get(m) or damaging_by_model.get(m))}
        for m in pan_wt_ids:
            chronos_mix[m] = chronos_by_model[m]
        hot_mix = {m: (m in lin_mut_ids and bool(hotspot_by_model.get(m))) for m in chronos_mix}
        dam_mix = {m: (m in lin_mut_ids and bool(damaging_by_model.get(m))) for m in chronos_mix}
        mix = compute_mutation_stratification(
            chronos_mix, hot_mix, dam_mix, strong_effect_delta, moderate_effect_delta, stratification_alpha
        )
        return _finish(mix, "within_indication_mut_vs_pan_wt", mix["mutation_stratification_class"])

    # pan_lineage_evidence_only: lineage mutant arm underpowered → pan-DepMap, but CAP a strong
    # call to moderate (the tissue confound is unresolved, so do not credit full strength).
    capped = dict(pan)
    if pan_class in _STRONG_TO_MODERATE_CAP:
        capped["mutation_stratification_class"] = _STRONG_TO_MODERATE_CAP[pan_class]
        capped["pan_fallback_strong_capped_to_moderate"] = True
    return _finish(capped, "pan_lineage_evidence_only")


def emit_mut_vs_wt_strip_plot(
    chronos_by_model: dict,
    hotspot_by_model: dict,
    damaging_by_model: dict,
    target_symbol: str,
    summary: dict,
    out_path: Path,
    contracts_root: Path,
) -> None:
    """Primary figure: Chronos strip plot grouped by mutation status (hotspot + damaging
    tiers side-by-side, each split mut vs WT). Annotated with q-values."""
    import matplotlib.pyplot as plt
    import numpy as np

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    from takeda_palette import (  # type: ignore
        CHRONOS_STRONG_DEPENDENCY,
        FIGSIZE_DOUBLE_COLUMN,
        REFLINE_KILLER,
        REFLINE_NOMINAL,
    )

    fig, ax = plt.subplots(figsize=FIGSIZE_DOUBLE_COLUMN)

    if not chronos_by_model:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes, color="#666666")
        fig.savefig(out_path / "figure_mut_vs_wt_strip.svg", bbox_inches="tight")
        plt.close(fig)
        return

    rng = np.random.default_rng(seed=42)

    # Four columns: hotspot_mut, hotspot_wt, damaging_mut, damaging_wt
    groups = []
    if hotspot_by_model:
        groups.append(
            (
                "hotspot\nmutant",
                [chronos_by_model[m] for m in chronos_by_model if m in hotspot_by_model and hotspot_by_model[m]],
                "#B22222",
            )
        )
        groups.append(
            (
                "hotspot\nWT",
                [chronos_by_model[m] for m in chronos_by_model if m in hotspot_by_model and not hotspot_by_model[m]],
                "#888888",
            )
        )
    if damaging_by_model:
        groups.append(
            (
                "damaging\nmutant",
                [chronos_by_model[m] for m in chronos_by_model if m in damaging_by_model and damaging_by_model[m]],
                "#E69F00",
            )
        )
        groups.append(
            (
                "damaging\nWT",
                [chronos_by_model[m] for m in chronos_by_model if m in damaging_by_model and not damaging_by_model[m]],
                "#888888",
            )
        )

    for i, (label, scores, color) in enumerate(groups):
        if not scores:
            continue
        scores_arr = np.array(scores)
        xs = i + rng.uniform(-0.25, 0.25, size=len(scores_arr))
        ax.scatter(xs, scores_arr, s=14, alpha=0.55, color=color, edgecolor="white", linewidth=0.3, zorder=2)
        # Median tick
        med = float(np.median(scores_arr))
        ax.plot([i - 0.35, i + 0.35], [med, med], color="#222222", linewidth=1.5, zorder=3)

    # Reference lines
    ax.axhline(y=0, **REFLINE_NOMINAL, zorder=1)
    ax.axhline(y=CHRONOS_STRONG_DEPENDENCY, **REFLINE_KILLER, zorder=1)

    # Annotation: q-values
    hot_q = summary.get("hotspot_mannwhitney_q")
    dam_q = summary.get("damaging_mannwhitney_q")
    parts = []
    if hot_q is not None:
        parts.append(f"hotspot q = {hot_q:.2e}")
    if dam_q is not None:
        parts.append(f"damaging q = {dam_q:.2e}")
    if parts:
        ax.text(
            0.02,
            0.98,
            "  ·  ".join(parts),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9,
            family="monospace",
            bbox=dict(facecolor="white", edgecolor="#888888", alpha=0.92, pad=4, boxstyle="round,pad=0.4"),
            zorder=5,
        )

    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([label for label, _, _ in groups], fontsize=9)
    ax.set_ylabel("Chronos score (more dependent ↓)")
    cls = summary.get("mutation_stratification_class", "?")
    ax.set_title(f"{target_symbol}: dependency stratified by mutation status  ({cls})")
    ax.grid(axis="y")

    fig.savefig(out_path / "figure_mut_vs_wt_strip.svg", bbox_inches="tight")
    plt.close(fig)


def emit_per_hotspot_chronos_plot(
    chronos_by_model: dict, per_hotspot_records: list, target_symbol: str, out_path: Path, contracts_root: Path
) -> None:
    """Alternate figure: per-hotspot Chronos strip plot (one column per recurrent
    protein change). Skipped placeholder when fewer than 3 hotspots detected."""
    import matplotlib.pyplot as plt
    import numpy as np

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    from takeda_palette import (  # type: ignore
        CHRONOS_STRONG_DEPENDENCY,
        FIGSIZE_DOUBLE_COLUMN,
        REFLINE_KILLER,
        REFLINE_NOMINAL,
    )

    fig, ax = plt.subplots(figsize=FIGSIZE_DOUBLE_COLUMN)

    if not per_hotspot_records or len(per_hotspot_records) < 3:
        ax.text(
            0.5,
            0.5,
            "Per-hotspot breakdown unavailable\n(fewer than 3 recurrent hotspots detected)",
            ha="center",
            va="center",
            transform=ax.transAxes,
            color="#666666",
            fontsize=10,
        )
        ax.axis("off")
        fig.savefig(out_path / "figure_per_hotspot_chronos.svg", bbox_inches="tight")
        plt.close(fig)
        return

    rng = np.random.default_rng(seed=42)
    records = sorted(per_hotspot_records, key=lambda r: r.get("median_chronos", 0))[:8]
    for i, rec in enumerate(records):
        cells_at_hotspot = rec.get("_cells", [])
        scores = [chronos_by_model[m] for m in cells_at_hotspot if m in chronos_by_model]
        if not scores:
            continue
        xs = i + rng.uniform(-0.25, 0.25, size=len(scores))
        ax.scatter(xs, scores, s=18, alpha=0.7, color="#B22222", edgecolor="white", linewidth=0.3, zorder=2)
        med = float(np.median(scores))
        ax.plot([i - 0.35, i + 0.35], [med, med], color="#222222", linewidth=1.5, zorder=3)

    ax.axhline(y=0, **REFLINE_NOMINAL, zorder=1)
    ax.axhline(y=CHRONOS_STRONG_DEPENDENCY, **REFLINE_KILLER, zorder=1)
    ax.set_xticks(range(len(records)))
    ax.set_xticklabels([r["protein_change"] for r in records], fontsize=8, rotation=30, ha="right")
    ax.set_ylabel("Chronos score")
    ax.set_title(f"{target_symbol}: Chronos by hotspot protein-change")
    ax.grid(axis="y")
    fig.savefig(out_path / "figure_per_hotspot_chronos.svg", bbox_inches="tight")
    plt.close(fig)


def emit_plotly_specs(
    chronos_by_model: dict,
    hotspot_by_model: dict,
    damaging_by_model: dict,
    target_symbol: str,
    summary: dict,
    out_path: Path,
    contracts_root: Path,
) -> list:
    """Emit interactive Plotly spec SIBLING to the mut-vs-WT strip SVG.

    Interactive twin of emit_mut_vs_wt_strip_plot: Chronos box+strip grouped by mutation status
    (hotspot mut/WT + damaging mut/WT — same 4 groups, same colors), reflines at 0 / -1.0
    (CHRONOS_STRONG_DEPENDENCY), q-values in the title. Built from the SAME chronos_by_model +
    hotspot/damaging membership the SVG + plot_data.parquet use (no drift). Writes
    figure_mut_vs_wt_strip.plotly.json. Best-effort (Plotly optional → SVG guaranteed)."""
    try:
        import plotly.graph_objects as go

        sys.path.insert(0, str(contracts_root / "plot_styles"))
        from takeda_palette import CHRONOS_STRONG_DEPENDENCY  # type: ignore
    except Exception as e:  # noqa: BLE001 — Plotly optional; never block the SVG artifact
        print(f"[depmap_mutation_dependency] plotly spec emission skipped: {e}", file=sys.stderr)
        return []
    if not chronos_by_model:
        return []

    written = []
    try:
        # SAME 4 groups + colors as the SVG (hotspot-mut red, damaging-mut amber, WT grey).
        groups = []
        if hotspot_by_model:
            groups.append(
                (
                    "hotspot mutant",
                    [chronos_by_model[m] for m in chronos_by_model if m in hotspot_by_model and hotspot_by_model[m]],
                    "#B22222",
                )
            )
            groups.append(
                (
                    "hotspot WT",
                    [
                        chronos_by_model[m]
                        for m in chronos_by_model
                        if m in hotspot_by_model and not hotspot_by_model[m]
                    ],
                    "#888888",
                )
            )
        if damaging_by_model:
            groups.append(
                (
                    "damaging mutant",
                    [chronos_by_model[m] for m in chronos_by_model if m in damaging_by_model and damaging_by_model[m]],
                    "#E69F00",
                )
            )
            groups.append(
                (
                    "damaging WT",
                    [
                        chronos_by_model[m]
                        for m in chronos_by_model
                        if m in damaging_by_model and not damaging_by_model[m]
                    ],
                    "#888888",
                )
            )

        fig = go.Figure()
        for label, scores, color in groups:
            if not scores:
                continue
            fig.add_trace(
                go.Box(
                    y=scores,
                    name=label,
                    marker_color=color,
                    boxpoints="all",
                    jitter=0.5,
                    pointpos=0,
                    marker=dict(size=4, opacity=0.55),
                    hovertemplate=f"{label}<br>Chronos %{{y:.2f}}<extra></extra>",
                )
            )
        for yv, col, dash in [(0.0, "#999999", "solid"), (CHRONOS_STRONG_DEPENDENCY, "#B22222", "dash")]:
            fig.add_hline(y=yv, line=dict(color=col, dash=dash, width=1.5))
        hot_q, dam_q = summary.get("hotspot_mannwhitney_q"), summary.get("damaging_mannwhitney_q")
        qparts = []
        if hot_q is not None:
            qparts.append(f"hotspot q={hot_q:.2e}")
        if dam_q is not None:
            qparts.append(f"damaging q={dam_q:.2e}")
        cls = summary.get("mutation_stratification_class", "?")
        qstr = ("  ·  " + "  ·  ".join(qparts)) if qparts else ""
        fig.update_layout(
            title=f"{target_symbol}: dependency stratified by mutation status ({cls}){qstr}",
            yaxis_title="Chronos score (more dependent ↓)",
            template="plotly_white",
            showlegend=False,
            margin=dict(l=60, r=20, t=50, b=50),
        )
        (out_path / "figure_mut_vs_wt_strip.plotly.json").write_text(fig.to_json())
        written.append({"id": "mut_vs_wt_strip", "path": "figure_mut_vs_wt_strip.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[depmap_mutation_dependency] strip plotly skipped: {e}", file=sys.stderr)

    return written


def emit_plot_data(
    chronos_by_model: dict, hotspot_by_model: dict, damaging_by_model: dict, model_metadata: dict, out_path: Path
) -> None:
    """Emit per-cell-line long-format plot_data.parquet."""
    import pandas as pd

    rows = []
    for mid, c in chronos_by_model.items():
        meta = model_metadata.get(mid, {}) if model_metadata else {}
        rows.append(
            {
                "cell_line_id": mid,
                "cell_line_name": meta.get("CellLineName", mid),
                "chronos_score": float(c),
                "lineage": meta.get("OncotreeLineage") or "unknown",
                "is_hotspot_mutant": bool(hotspot_by_model.get(mid, False)),
                "is_damaging_mutant": bool(damaging_by_model.get(mid, False)),
                "is_any_mutant": bool(hotspot_by_model.get(mid, False) or damaging_by_model.get(mid, False)),
            }
        )
    pd.DataFrame(rows).to_parquet(out_path / "plot_data.parquet", index=False)


def emit_manifest(
    target: str, indication: str, release_pin: str, summary: dict, out_path: Path, load_errors: list
) -> None:
    import yaml

    manifest = {
        "method": "depmap-mutation-stratified",
        "method_version": METHOD_VERSION,
        "target": target,
        "indication": indication,  # run-context only
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_manifest": "depmap-consortium-26q1",
        "input_files_consumed": [
            "CRISPRGeneEffect.csv",
            "OmicsSomaticMutationsMatrixHotspot.csv",
            "OmicsSomaticMutationsMatrixDamaging.csv",
        ],
        "n_cell_lines_evaluated": summary.get("n_cell_lines_evaluated"),
        "n_hotspot_mutant": summary.get("n_hotspot_mutant"),
        "n_damaging_mutant": summary.get("n_damaging_mutant"),
        "mutation_stratification_class": summary.get("mutation_stratification_class"),
        "load_errors": load_errors,
    }
    with (out_path / "manifest.yaml").open("w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)


@click.command()
@click.option("--target", required=True)
@click.option("--indication", required=True, type=click.Choice(["COADREAD", "PDAC", "NSCLC", "SCLC", "GC", "MELANOMA"]))
@click.option("--release-pin", default="26q1")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--contracts-root", type=click.Path(file_okay=False, path_type=Path), default=DEFAULT_TARGET_CONTRACTS)
@click.option("--dry-run", is_flag=True)
def main(target, indication, release_pin, out, contracts_root, dry_run) -> int:
    out.mkdir(parents=True, exist_ok=True)
    click.echo("=== depmap-mutation-stratified (Card 3) ===")
    click.echo(f"  target:      {target}")
    click.echo(f"  indication:  {indication}")
    click.echo(f"  out:         {out}")
    if dry_run:
        return 0

    # Reuse Card 1's loader for Chronos
    sys.path.insert(0, str(METHOD_DIR.parent.parent))
    from methods.depmap_chronos_distribution import cli as c1cli

    chronos_by_model, model_metadata, chronos_errs = c1cli.load_depmap_files(release_pin, target)
    if chronos_errs:
        click.echo(f"  CHRONOS LOAD FAILED: {chronos_errs}", err=True)
        with (out / "summary.json").open("w") as f:
            json.dump(
                {"_live_read_error": True, "errors": chronos_errs, "mutation_stratification_class": "data_unavailable"},
                f,
                indent=2,
            )
        emit_manifest(target, indication, release_pin, {}, out, chronos_errs)
        return 2

    hotspot_by_model, damaging_by_model, mut_errs = load_mutation_data(release_pin, target)
    if mut_errs:
        click.echo(f"  MUTATION LOAD FAILED: {mut_errs}", err=True)
        with (out / "summary.json").open("w") as f:
            json.dump(
                {"_live_read_error": True, "errors": mut_errs, "mutation_stratification_class": "data_unavailable"},
                f,
                indent=2,
            )
        emit_manifest(target, indication, release_pin, {}, out, mut_errs)
        return 2

    summary = compute_mutation_stratification_conditioned(
        chronos_by_model,
        hotspot_by_model,
        damaging_by_model,
        model_metadata=model_metadata,
        indication=indication,
    )

    with (out / "summary.json").open("w") as f:
        # Strip the _hotspot_by_model / _damaging_by_model internal payload before writing
        json.dump(
            {k: v for k, v in summary.items() if not (k.startswith("_") and isinstance(v, dict))},
            f,
            indent=2,
            default=str,
        )

    emit_plot_data(chronos_by_model, hotspot_by_model, damaging_by_model, model_metadata, out)
    emit_mut_vs_wt_strip_plot(
        chronos_by_model, hotspot_by_model, damaging_by_model, target, summary, out, contracts_root
    )
    emit_per_hotspot_chronos_plot(chronos_by_model, summary.get("per_hotspot_stats", []), target, out, contracts_root)
    emit_manifest(target, indication, release_pin, summary, out, [])

    click.echo(f"  mutation_stratification_class: {summary['mutation_stratification_class']}")
    click.echo(
        f"  hotspot mut/wt: {summary['n_hotspot_mutant']}/{summary['n_hotspot_wildtype']}  "
        f"delta = {summary.get('delta_chronos_hotspot_mut_vs_wt')}, "
        f"q = {summary.get('hotspot_mannwhitney_q')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
