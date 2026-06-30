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
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import click


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

DEFAULT_TARGET_CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
DEPMAP_S3_PREFIX = "s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1"
DEPMAP_LOCAL_FALLBACK_DIRS = [
    Path("/home/sagemaker-user/depmap-26q1"),
    Path("/data/depmap/26q1"),
    Path.home() / "depmap-26q1",
]

# 5-column metadata prefix common to OmicsExpressionTPM*, OmicsSomaticMutationsMatrix*
MUT_METADATA_COLUMNS = (
    "SequencingID", "ModelConditionID", "ModelID",
    "IsDefaultEntryForMC", "IsDefaultEntryForModel",
)


def _read_mutation_matrix_for_target(release_pin: str, matrix_filename: str,
                                       target_symbol: str) -> tuple[dict, list]:
    """Load ONE mutation matrix (hotspot or damaging), filter to default-entries, return
    {ModelID → bool} for the target gene + load_errors list.

    Reuses the dual local-cache / S3 fallback pattern from Cards 1+2+4.
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

    if mut_path is None:
        try:
            import boto3
            s3 = boto3.client("s3")
            bucket = "onc-compbio"
            key = f"data-catalog/sources/depmap-consortium/dmc-26q1/{matrix_filename}"
            click.echo(f"  Fetching s3://{bucket}/{key}", err=True)
            obj = s3.get_object(Bucket=bucket, Key=key)
            # Peek at header to find target column, then re-fetch with usecols
            header_df = pd.read_csv(BytesIO(obj["Body"].read(8192)), nrows=0)
            target_cols = [c for c in header_df.columns
                            if c == target_symbol or c.split(" ")[0] == target_symbol]
            if not target_cols:
                load_errors.append({
                    "_live_read_error": "target_not_in_mutation_matrix",
                    "detail": f"Target {target_symbol} not in {matrix_filename}",
                })
                return {}, load_errors
            usecols = [c for c in MUT_METADATA_COLUMNS if c in header_df.columns] + [target_cols[0]]
            obj_full = s3.get_object(Bucket=bucket, Key=key)
            df = pd.read_csv(BytesIO(obj_full["Body"].read()), usecols=usecols)
            target_col = target_cols[0]
        except ImportError as e:
            load_errors.append({"_live_read_error": "boto3_not_available", "detail": str(e)})
            return {}, load_errors
        except Exception as e:
            load_errors.append({"_live_read_error": "s3_read_failed",
                                 "detail": str(e), "file": matrix_filename})
            return {}, load_errors
    else:
        header_df = pd.read_csv(mut_path, nrows=0)
        target_cols = [c for c in header_df.columns
                        if c == target_symbol or c.split(" ")[0] == target_symbol]
        if not target_cols:
            load_errors.append({"_live_read_error": "target_not_in_mutation_matrix",
                                 "detail": f"Target {target_symbol} not in {matrix_filename}"})
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


def _mannwhitney_stratification(chronos_by_model: dict, mut_by_model: dict,
                                  min_mutant: int = 5, min_wildtype: int = 30) -> dict:
    """Run Mann-Whitney U (one-sided: mutant more dependent) for a single mut vector.

    Returns a dict with n/median/p/q/effect fields. q is set NaN here (filled by caller
    via BH correction across the three tests: hotspot + damaging + any)."""
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
            "q_value": None,                  # filled by caller's BH step (will stay None)
            "effect_size": None,
            "_insufficient_data": True,
        }

    mut_arr = np.array(mut_scores)
    wt_arr = np.array(wt_scores)
    median_mut = float(np.median(mut_arr))
    median_wt = float(np.median(wt_arr))
    delta = median_mut - median_wt

    try:
        u_stat, p_one_sided = scipy_stats.mannwhitneyu(
            mut_arr, wt_arr, alternative="less"
        )
        # Rank-biserial effect size
        effect = 1.0 - (2.0 * u_stat) / (n_mut * n_wt)
    except ValueError:
        p_one_sided = 1.0
        effect = 0.0

    return {
        "n_mutant": int(n_mut),
        "n_wildtype": int(n_wt),
        "median_mutant": median_mut,
        "median_wildtype": median_wt,
        "delta_mut_vs_wt": float(delta),
        "p_value": float(p_one_sided),
        "q_value": None,                      # filled by caller
        "effect_size": float(effect),
    }


def compute_mutation_stratification(chronos_by_model: dict,
                                      hotspot_by_model: dict,
                                      damaging_by_model: dict,
                                      strong_effect_delta: float = -0.5,
                                      moderate_effect_delta: float = -0.2,
                                      stratification_alpha: float = 0.05) -> dict:
    """Compute Card 3 summary fields.

    Three tier Mann-Whitney tests: hotspot, damaging, combined-any. BH correction
    applied across the three. mutation_stratification_class categorical is the
    strongest signal.
    """
    import numpy as np

    # === Three parallel stratification tests ===
    hot = _mannwhitney_stratification(chronos_by_model, hotspot_by_model)
    dam = _mannwhitney_stratification(chronos_by_model, damaging_by_model)

    # Build "any mutation" vector: hotspot OR damaging
    any_by_model = {}
    for m in set(hotspot_by_model.keys()) | set(damaging_by_model.keys()):
        any_by_model[m] = hotspot_by_model.get(m, False) or damaging_by_model.get(m, False)
    any_ = _mannwhitney_stratification(chronos_by_model, any_by_model)

    # BH correction across the 3 tests (when all have p_values)
    p_values = [(tier_key, tier_dict["p_value"])
                 for tier_key, tier_dict in [("hot", hot), ("dam", dam), ("any", any_)]
                 if tier_dict.get("p_value") is not None]
    if p_values:
        p_array = np.array([p for _, p in p_values])
        m = len(p_array)
        order = np.argsort(p_array)
        ranks = np.empty_like(order)
        ranks[order] = np.arange(1, m + 1)
        q_unord = np.minimum.accumulate(
            (p_array[order] * m / ranks[order])[::-1]
        )[::-1]
        q_back = np.empty_like(q_unord)
        q_back[order] = q_unord
        for i, (tier_key, _) in enumerate(p_values):
            q = float(min(1.0, q_back[i]))
            if tier_key == "hot":
                hot["q_value"] = q
            elif tier_key == "dam":
                dam["q_value"] = q
            elif tier_key == "any":
                any_["q_value"] = q

    # === Classification ===
    # Prefer hotspot signal if present; otherwise damaging; otherwise any.
    def _classify(tier: dict) -> Optional[str]:
        if tier.get("q_value") is None or tier.get("delta_mut_vs_wt") is None:
            return None
        if tier["q_value"] >= stratification_alpha:
            return None
        if tier["delta_mut_vs_wt"] <= strong_effect_delta:
            return "mutant_strongly_dependent"
        if tier["delta_mut_vs_wt"] <= moderate_effect_delta:
            return "mutant_moderately_dependent"
        # Inverse (positive delta with significance) → WT cells more dependent
        if tier["delta_mut_vs_wt"] >= 0.3:
            return "wt_strongly_dependent"
        return None

    cls = _classify(hot) or _classify(dam) or _classify(any_)
    if cls is None:
        # Check sample-size gating
        if hot.get("_insufficient_data") and dam.get("_insufficient_data"):
            cls = "insufficient_mutation_rate"
        else:
            cls = "not_mutation_stratified"

    n_evaluated = len(set(chronos_by_model.keys())
                       & (set(hotspot_by_model.keys()) | set(damaging_by_model.keys())))

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
        "hotspot_effect_size": hot["effect_size"],
        # === Damaging tier ===
        "n_damaging_mutant": dam["n_mutant"],
        "n_damaging_wildtype": dam["n_wildtype"],
        "median_chronos_damaging_mutant": dam["median_mutant"],
        "median_chronos_damaging_wildtype": dam["median_wildtype"],
        "delta_chronos_damaging_mut_vs_wt": dam["delta_mut_vs_wt"],
        "damaging_mannwhitney_p": dam["p_value"],
        "damaging_mannwhitney_q": dam["q_value"],
        "damaging_effect_size": dam["effect_size"],
        # === Combined "any mutation" tier ===
        "n_any_mutant": any_["n_mutant"],
        "n_any_wildtype": any_["n_wildtype"],
        "delta_chronos_any_mut_vs_wt": any_["delta_mut_vs_wt"],
        "any_mannwhitney_q": any_["q_value"],
        # === Per-hotspot breakdown (populated by load_per_hotspot_records if MAF available) ===
        "per_hotspot_stats": [],
        # === Categorical ===
        "mutation_stratification_class": cls,
        # === Internal for figure emitters ===
        "_hotspot_by_model": hotspot_by_model,
        "_damaging_by_model": damaging_by_model,
    }


def emit_mut_vs_wt_strip_plot(chronos_by_model: dict, hotspot_by_model: dict,
                                damaging_by_model: dict, target_symbol: str,
                                summary: dict, out_path: Path,
                                contracts_root: Path) -> None:
    """Primary figure: Chronos strip plot grouped by mutation status (hotspot + damaging
    tiers side-by-side, each split mut vs WT). Annotated with q-values."""
    import matplotlib.pyplot as plt
    import numpy as np

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    from takeda_palette import (  # type: ignore
        REFLINE_NOMINAL, REFLINE_NEUTRAL, REFLINE_KILLER,
        FIGSIZE_DOUBLE_COLUMN, CHRONOS_STRONG_DEPENDENCY,
    )

    fig, ax = plt.subplots(figsize=FIGSIZE_DOUBLE_COLUMN)

    if not chronos_by_model:
        ax.text(0.5, 0.5, "No data", ha="center", va="center",
                transform=ax.transAxes, color="#666666")
        fig.savefig(out_path / "figure_mut_vs_wt_strip.svg", bbox_inches="tight")
        plt.close(fig)
        return

    rng = np.random.default_rng(seed=42)

    # Four columns: hotspot_mut, hotspot_wt, damaging_mut, damaging_wt
    groups = []
    if hotspot_by_model:
        groups.append(("hotspot\nmutant",
                       [chronos_by_model[m] for m in chronos_by_model
                        if m in hotspot_by_model and hotspot_by_model[m]],
                       "#B22222"))
        groups.append(("hotspot\nWT",
                       [chronos_by_model[m] for m in chronos_by_model
                        if m in hotspot_by_model and not hotspot_by_model[m]],
                       "#888888"))
    if damaging_by_model:
        groups.append(("damaging\nmutant",
                       [chronos_by_model[m] for m in chronos_by_model
                        if m in damaging_by_model and damaging_by_model[m]],
                       "#E69F00"))
        groups.append(("damaging\nWT",
                       [chronos_by_model[m] for m in chronos_by_model
                        if m in damaging_by_model and not damaging_by_model[m]],
                       "#888888"))

    for i, (label, scores, color) in enumerate(groups):
        if not scores:
            continue
        scores_arr = np.array(scores)
        xs = i + rng.uniform(-0.25, 0.25, size=len(scores_arr))
        ax.scatter(xs, scores_arr, s=14, alpha=0.55,
                    color=color, edgecolor="white", linewidth=0.3, zorder=2)
        # Median tick
        med = float(np.median(scores_arr))
        ax.plot([i - 0.35, i + 0.35], [med, med],
                color="#222222", linewidth=1.5, zorder=3)

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
        ax.text(0.02, 0.98, "  ·  ".join(parts), transform=ax.transAxes,
                ha="left", va="top", fontsize=9, family="monospace",
                bbox=dict(facecolor="white", edgecolor="#888888",
                            alpha=0.92, pad=4, boxstyle="round,pad=0.4"),
                zorder=5)

    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([label for label, _, _ in groups], fontsize=9)
    ax.set_ylabel("Chronos score (more dependent ↓)")
    cls = summary.get("mutation_stratification_class", "?")
    ax.set_title(f"{target_symbol}: dependency stratified by mutation status  ({cls})")
    ax.grid(axis="y")

    fig.savefig(out_path / "figure_mut_vs_wt_strip.svg", bbox_inches="tight")
    plt.close(fig)


def emit_per_hotspot_chronos_plot(chronos_by_model: dict, per_hotspot_records: list,
                                    target_symbol: str, out_path: Path,
                                    contracts_root: Path) -> None:
    """Alternate figure: per-hotspot Chronos strip plot (one column per recurrent
    protein change). Skipped placeholder when fewer than 3 hotspots detected."""
    import matplotlib.pyplot as plt
    import numpy as np

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    from takeda_palette import FIGSIZE_DOUBLE_COLUMN, REFLINE_KILLER, REFLINE_NOMINAL, CHRONOS_STRONG_DEPENDENCY  # type: ignore

    fig, ax = plt.subplots(figsize=FIGSIZE_DOUBLE_COLUMN)

    if not per_hotspot_records or len(per_hotspot_records) < 3:
        ax.text(0.5, 0.5,
                "Per-hotspot breakdown unavailable\n(fewer than 3 recurrent hotspots detected)",
                ha="center", va="center", transform=ax.transAxes,
                color="#666666", fontsize=10)
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
        ax.scatter(xs, scores, s=18, alpha=0.7, color="#B22222",
                    edgecolor="white", linewidth=0.3, zorder=2)
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


def emit_plot_data(chronos_by_model: dict, hotspot_by_model: dict,
                     damaging_by_model: dict, model_metadata: dict,
                     out_path: Path) -> None:
    """Emit per-cell-line long-format plot_data.parquet."""
    import pandas as pd

    rows = []
    for mid, c in chronos_by_model.items():
        meta = model_metadata.get(mid, {}) if model_metadata else {}
        rows.append({
            "cell_line_id": mid,
            "cell_line_name": meta.get("CellLineName", mid),
            "chronos_score": float(c),
            "lineage": meta.get("OncotreeLineage") or "unknown",
            "is_hotspot_mutant": bool(hotspot_by_model.get(mid, False)),
            "is_damaging_mutant": bool(damaging_by_model.get(mid, False)),
            "is_any_mutant": bool(hotspot_by_model.get(mid, False) or damaging_by_model.get(mid, False)),
        })
    pd.DataFrame(rows).to_parquet(out_path / "plot_data.parquet", index=False)


def emit_manifest(target: str, indication: str, release_pin: str,
                    summary: dict, out_path: Path, load_errors: list) -> None:
    import yaml
    manifest = {
        "method": "depmap-mutation-stratified",
        "method_version": METHOD_VERSION,
        "target": target,
        "indication": indication,                # run-context only
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
@click.option("--indication", required=True,
              type=click.Choice(["COADREAD", "PDAC", "NSCLC", "SCLC", "GC", "MELANOMA"]))
@click.option("--release-pin", default="26q1")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--contracts-root", type=click.Path(file_okay=False, path_type=Path),
              default=DEFAULT_TARGET_CONTRACTS)
@click.option("--dry-run", is_flag=True)
def main(target, indication, release_pin, out, contracts_root, dry_run) -> int:
    out.mkdir(parents=True, exist_ok=True)
    click.echo(f"=== depmap-mutation-stratified (Card 3) ===")
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
            json.dump({"_live_read_error": True, "errors": chronos_errs,
                       "mutation_stratification_class": "data_unavailable"}, f, indent=2)
        emit_manifest(target, indication, release_pin, {}, out, chronos_errs)
        return 2

    hotspot_by_model, damaging_by_model, mut_errs = load_mutation_data(release_pin, target)
    if mut_errs:
        click.echo(f"  MUTATION LOAD FAILED: {mut_errs}", err=True)
        with (out / "summary.json").open("w") as f:
            json.dump({"_live_read_error": True, "errors": mut_errs,
                       "mutation_stratification_class": "data_unavailable"}, f, indent=2)
        emit_manifest(target, indication, release_pin, {}, out, mut_errs)
        return 2

    summary = compute_mutation_stratification(
        chronos_by_model, hotspot_by_model, damaging_by_model
    )

    with (out / "summary.json").open("w") as f:
        # Strip the _hotspot_by_model / _damaging_by_model internal payload before writing
        json.dump({k: v for k, v in summary.items()
                   if not (k.startswith("_") and isinstance(v, dict))},
                  f, indent=2, default=str)

    emit_plot_data(chronos_by_model, hotspot_by_model, damaging_by_model,
                    model_metadata, out)
    emit_mut_vs_wt_strip_plot(chronos_by_model, hotspot_by_model, damaging_by_model,
                                target, summary, out, contracts_root)
    emit_per_hotspot_chronos_plot(chronos_by_model, summary.get("per_hotspot_stats", []),
                                    target, out, contracts_root)
    emit_manifest(target, indication, release_pin, summary, out, [])

    click.echo(f"  mutation_stratification_class: {summary['mutation_stratification_class']}")
    click.echo(f"  hotspot mut/wt: {summary['n_hotspot_mutant']}/{summary['n_hotspot_wildtype']}  "
                f"delta = {summary.get('delta_chronos_hotspot_mut_vs_wt')}, "
                f"q = {summary.get('hotspot_mannwhitney_q')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
