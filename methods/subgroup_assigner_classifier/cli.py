#!/usr/bin/env python3
"""subgroup_assigner_classifier CLI — Modality C: signature-score subgroup assignments.

Invocation:
    subgroup-assigner-classifier \
      --subgroup-catalog /path/to/sclc-subgroups-2026-q3.yaml \
      --classifier-config /path/to/sclc-napy-classifier-config.yaml \
      --data-source depmap \
      --release-pin 2026-Q3 \
      --catalog-repo /path/to/data-catalog \
      --out /path/to/output-dir/

Two classifier types supported iter-1:

1. **single_gene_zscore_threshold** — one marker gene per stratum; sample is
   member iff z-score(gene) >= threshold. Used for DLL3-high SCLC.

2. **napy_zscore_classifier** — N marker genes (one per stratum); sample is
   assigned to the stratum whose marker has the maximum z-score (argmax) AND
   that z-score exceeds a `min_zscore` floor. Used for SCLC NAPY assignment
   (ASCL1 → SCLC-A, NEUROD1 → SCLC-N, POU2F3 → SCLC-P, YAP1 → SCLC-Y).

Iter-1 SCLC strata come from data-catalog PR #135 (SCLC/2026-Q3.yaml). The
matching classifier_config is a Phase 2a.3 companion file (this method reads
its own classifier config YAML; the subgroup catalog specifies
`derivation_source: classifier_run` + `data_source.method: <method_name>`).

iter-1 caveat: SCLC NAPY on DepMap is a small cohort (~28 SCLC cell lines
combined across A/N/P/Y). Per docs/design/idas-strata/sclc.md,
"iter-1 SCLC evidence should be marked hypothesis_generating upstream"
per extrapolation discipline. This method emits assignments faithfully;
the rules layer downstream is responsible for hypothesis-generating flag.

Phase 2a.3 of iDAS Subtype Pipeline. NEW method — no prior version.
"""

from __future__ import annotations
import os

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import numpy as np
import pandas as pd
import yaml

from methods.subgroup_common.manifest import emit_assignment_manifest
from methods.subgroup_common.paths import cache_root


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

SUPPORTED_DERIVATION_SOURCES = {"classifier_run"}
SUPPORTED_CLASSIFIER_METHODS = {"single_gene_zscore_threshold", "napy_zscore_classifier"}


# ---------- Classifier config ----------------------------------------------

def _load_classifier_config(config_path: Path) -> dict:
    """Load the classifier config YAML.

    Expected shape:

    ```yaml
    id: sclc-napy-classifier-2026-q3
    classifier_method: napy_zscore_classifier
    marker_genes:
      SCLC_A: ASCL1
      SCLC_N: NEUROD1
      SCLC_P: POU2F3
      SCLC_Y: YAP1
    min_zscore: 0.0
    reference_cohort: depmap_lung_sclc
    ```

    Or for single-gene threshold:
    ```yaml
    id: dll3-high-classifier-2026-q3
    classifier_method: single_gene_zscore_threshold
    marker_gene: DLL3
    zscore_threshold: 1.0
    label_when_high: DLL3_high
    reference_cohort: depmap_lung_sclc
    ```
    """
    with config_path.open() as f:
        config = yaml.safe_load(f)
    m = config.get("classifier_method")
    if m not in SUPPORTED_CLASSIFIER_METHODS:
        raise ValueError(
            f"classifier_method={m!r} not supported. "
            f"iter-1 supports: {SUPPORTED_CLASSIFIER_METHODS}"
        )
    return config


# ---------- Source-data loaders --------------------------------------------

_REFERENCE_COHORT_ONCOTREE = {
    "depmap_lung_sclc": "SCLC",
    "depmap_all": None,
}


def _load_depmap_expression(gene_symbols: list[str], reference_cohort: str | None = None) -> pd.DataFrame:
    """Load DepMap OmicsExpressionProteinCodingGenesTPMLogp1 for the given genes.

    Returns wide DataFrame indexed by ModelID with one column per gene
    (values are log2(TPM+1)).

    The real DepMap 26Q1 file has columns as 'SYMBOL (EntrezID)' and extra
    metadata columns. We resolve gene symbols to the first matching column,
    filter to IsDefaultEntryForModel='Yes', and optionally restrict to an
    OncotreeCode cohort via Model.csv (for reference_cohort filtering).
    """
    cache = cache_root() / "framework-depmap-26q1"
    fallback = cache / "OmicsExpressionProteinCodingGenesTPMLogp1.csv"
    if not fallback.exists():
        raise FileNotFoundError(
            f"DepMap expression matrix not found at {fallback}. "
            f"Pull s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1/"
            f"OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv into that path."
        )
    # Read header to map gene symbols to actual column names ('GENE (ID)' format)
    header_df = pd.read_csv(fallback, nrows=0)
    all_cols = list(header_df.columns)
    sym_to_col: dict[str, str] = {}
    for col in all_cols:
        sym = col.split(" (")[0]
        if sym not in sym_to_col:
            sym_to_col[sym] = col

    missing = [g for g in gene_symbols if g not in sym_to_col]
    if missing:
        raise KeyError(f"Marker genes not in expression matrix: {missing}")

    gene_cols = [sym_to_col[g] for g in gene_symbols]
    needed = ["ModelID", "IsDefaultEntryForModel"] + gene_cols

    # Read only the columns we need + ModelID/filter cols
    df = pd.read_csv(fallback, usecols=lambda c: c in set(needed))
    df = df[df["IsDefaultEntryForModel"] == "Yes"].set_index("ModelID")
    df = df.drop(columns=["IsDefaultEntryForModel"], errors="ignore")
    # Rename 'SYMBOL (ID)' columns → bare symbol
    df = df.rename(columns={sym_to_col[g]: g for g in gene_symbols})

    # Optional cohort filter via Model.csv
    oncotree_code = _REFERENCE_COHORT_ONCOTREE.get(reference_cohort) if reference_cohort else None
    if oncotree_code:
        model_path = cache / "Model.csv"
        if model_path.exists():
            model = pd.read_csv(model_path, usecols=["ModelID", "OncotreeCode"])
            cohort_ids = set(model[model["OncotreeCode"] == oncotree_code]["ModelID"])
            df = df[df.index.isin(cohort_ids)]
            if df.empty:
                raise ValueError(
                    f"No models found for OncotreeCode={oncotree_code!r} "
                    f"after cohort filtering. Check Model.csv."
                )
        else:
            click.echo(
                f"  WARNING: Model.csv not found at {model_path}; "
                f"reference_cohort filter ({reference_cohort!r}) skipped",
                err=True,
            )

    return df[gene_symbols]


def _load_tcga_expression(gene_symbols: list[str], indication: str) -> pd.DataFrame:
    """Load TCGA per-sample expression (recount3 log2(TPM+1)) for given genes.

    Same cache-fallback pattern; Phase 2a.4 canonical loader.
    """
    fallback = cache_root() / "framework-tcga-recount3" / f"{indication.lower()}-expression.parquet"
    if not fallback.exists():
        raise FileNotFoundError(
            f"TCGA expression matrix for {indication} not found at {fallback}. "
            f"Phase 2a.4 provides the canonical loader from recount3."
        )
    df = pd.read_parquet(fallback)
    return df


# ---------- Classifier core ------------------------------------------------

def _zscore(series: pd.Series) -> pd.Series:
    """Compute z-score for a pandas Series (mean 0, std 1). NaN-safe."""
    mu = series.mean(skipna=True)
    sd = series.std(skipna=True)
    if sd == 0 or pd.isna(sd):
        return pd.Series([0.0] * len(series), index=series.index)
    return (series - mu) / sd


def _run_napy_classifier(expression_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Assign each sample to its argmax NAPY subtype.

    Returns DataFrame indexed by sample_id with columns:
        stratum_id, is_member, derivation_value (z-score of winning marker)
    One row per (sample, stratum) — all N NAPY strata get a row per sample;
    only the argmax stratum has is_member=True.
    """
    marker_genes = config["marker_genes"]  # {stratum_id: gene_symbol}
    min_zscore = config.get("min_zscore", 0.0)

    # Z-score each marker gene across the cohort
    z = pd.DataFrame({
        stratum_id: _zscore(expression_df[gene])
        for stratum_id, gene in marker_genes.items()
    })

    # For each sample: argmax stratum (the "winner")
    winners = z.idxmax(axis=1)
    winner_scores = z.max(axis=1)

    # Sample is member of its winner stratum ONLY IF winner_score >= min_zscore
    # (otherwise: "undefined" NAPY assignment → all strata is_member=False)
    out_rows = []
    for sample_id in expression_df.index:
        w = winners[sample_id]
        w_score = winner_scores[sample_id]
        winner_valid = (not pd.isna(w_score)) and (w_score >= min_zscore)
        for stratum_id in marker_genes:
            is_member = winner_valid and (stratum_id == w)
            deriv = f"{marker_genes[stratum_id]}_z={z.at[sample_id, stratum_id]:.2f}"
            out_rows.append({
                "sample_id": sample_id,
                "stratum_id": stratum_id,
                "is_member": is_member,
                "derivation_value": deriv if is_member else "",
            })
    return pd.DataFrame(out_rows)


def _run_single_gene_threshold(expression_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Assign is_member for a single-gene z-score threshold classifier.

    Returns DataFrame with one row per sample. Stratum id from config
    (`label_when_high`).
    """
    gene = config["marker_gene"]
    threshold = config["zscore_threshold"]
    label = config["label_when_high"]

    z = _zscore(expression_df[gene])
    out_rows = []
    for sample_id in expression_df.index:
        z_val = z[sample_id]
        if pd.isna(z_val):
            is_member = None  # tri-value insufficient
        else:
            is_member = bool(z_val >= threshold)
        deriv = f"{gene}_z={z_val:.2f}" if is_member else ""
        out_rows.append({
            "sample_id": sample_id,
            "stratum_id": label,
            "is_member": is_member,
            "derivation_value": deriv,
        })
    return pd.DataFrame(out_rows)


# ---------- Output emission ------------------------------------------------

# The schema-valid subgroup_assignment_product manifest is emitted via the
# shared subgroup_common.manifest.emit_assignment_manifest (variant="classifier").
# NB: the classifier-config lineage is intentionally NOT stamped on the manifest
# — subgroup_assignment.schema.json has unevaluatedProperties:false and no
# classifier_config_ref field; config provenance belongs in input_manifest_ids.


# ---------- CLI ------------------------------------------------------------

@click.command()
@click.option("--subgroup-catalog", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to the subgroup_catalog YAML.")
@click.option("--classifier-config", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to the classifier config YAML (companion file).")
@click.option("--data-source", required=True, type=click.Choice(["tcga", "depmap"]),
              help="Which data source's expression matrix to classify against.")
@click.option("--release-pin", required=True, help="Catalog release_pin identifier.")
@click.option("--catalog-repo", type=click.Path(file_okay=False, path_type=Path),
              default=Path(os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")),
              help="Path to the data-catalog repo.")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Output directory.")
@click.option("--dry-run", is_flag=True,
              help="Parse catalog + config, print the plan, do not classify.")
def main(subgroup_catalog: Path, classifier_config: Path, data_source: str,
         release_pin: str, catalog_repo: Path, out: Path, dry_run: bool) -> int:
    """Generate per-sample subgroup assignments from signature-score classifiers."""
    with subgroup_catalog.open() as f:
        catalog = yaml.safe_load(f)
    config = _load_classifier_config(classifier_config)

    indication = catalog.get("indication")
    catalog_id = catalog.get("id")
    atomic = catalog.get("atomic_strata", [])

    config_method = config["classifier_method"]
    applicable = []
    skipped = []
    for s in atomic:
        if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES:
            skipped.append((s["id"], "derivation_source not classifier_run"))
            continue
        applicable_sources = s.get("applicable_data_sources", [])
        if data_source not in applicable_sources:
            skipped.append((s["id"], f"data_source {data_source!r} not applicable"))
            continue
        # Filter to strata whose catalog method matches this classifier config's method
        stratum_method = s.get("data_source", {}).get("method", "")
        if stratum_method and stratum_method != config_method:
            skipped.append((s["id"], f"method {stratum_method!r} != config {config_method!r}"))
            continue
        applicable.append(s)

    click.echo(f"=== subgroup_assigner_classifier v{METHOD_VERSION} ===")
    click.echo(f"  catalog:            {catalog_id} (indication={indication})")
    click.echo(f"  classifier_method:  {config['classifier_method']}")
    click.echo(f"  data_source:        {data_source}")
    click.echo(f"  release_pin:        {release_pin}")
    click.echo(f"  out:                {out}")
    click.echo(f"  applicable classifier-run strata ({len(applicable)} of {len(atomic)}):")
    for s in applicable:
        click.echo(f"    - {s['id']:<20} rule={s['rule']!r}")
    if skipped:
        click.echo(f"  skipped strata ({len(skipped)}):")
        for sid, reason in skipped:
            click.echo(f"    - {sid:<20} ({reason})")

    if not applicable:
        click.echo(f"WARNING: no applicable classifier-run strata for data_source={data_source} / method={config_method}", err=True)
        return 0

    if dry_run:
        click.echo("(--dry-run: skipping actual classification)")
        return 0

    # ============ Load expression data ============
    if config["classifier_method"] == "napy_zscore_classifier":
        gene_symbols = list(config["marker_genes"].values())
    else:
        gene_symbols = [config["marker_gene"]]

    if data_source == "depmap":
        expression = _load_depmap_expression(gene_symbols, reference_cohort=config.get("reference_cohort"))
    else:
        expression = _load_tcga_expression(gene_symbols, indication)
    click.echo(f"  loaded expression matrix: {expression.shape}")

    # ============ Run classifier ============
    if config["classifier_method"] == "napy_zscore_classifier":
        assignments = _run_napy_classifier(expression, config)
    else:
        assignments = _run_single_gene_threshold(expression, config)

    # Enrich with resolver-product columns
    assignments["patient_id"] = None if data_source == "depmap" else assignments["sample_id"]
    assignments["source_native_id"] = assignments["sample_id"]
    assignments["derivation_source"] = "classifier_run"
    assignments["evaluated_at_release"] = release_pin
    # Reorder columns per resolver-product design
    assignments = assignments[[
        "sample_id", "patient_id", "source_native_id", "stratum_id",
        "is_member", "derivation_source", "derivation_value", "evaluated_at_release",
    ]]

    # Filter to strata that appear in the catalog (be safe if classifier config has extras)
    applicable_ids = {s["id"] for s in applicable}
    n_before = len(assignments)
    assignments = assignments[assignments["stratum_id"].isin(applicable_ids)]
    if n_before != len(assignments):
        click.echo(f"  filtered classifier output: {n_before} → {len(assignments)} "
                   f"rows (dropped strata not in catalog)")

    for sid in applicable_ids:
        rows_for_stratum = assignments[assignments["stratum_id"] == sid]
        n_true = int((rows_for_stratum["is_member"] == True).sum())
        n_false = int((rows_for_stratum["is_member"] == False).sum())
        n_null = int(rows_for_stratum["is_member"].isna().sum())
        click.echo(f"    {sid:<20} true: {n_true:>4}, false: {n_false:>4}, null: {n_null:>4}")

    # ============ Emit outputs ============
    out.mkdir(parents=True, exist_ok=True)
    parquet_path = out / "assignments.parquet"
    assignments.to_parquet(parquet_path, index=False)
    click.echo(f"  wrote {parquet_path} ({len(assignments):,} rows)")

    emit_assignment_manifest(
        out_dir=out, catalog=catalog, catalog_path=subgroup_catalog,
        data_source=data_source, release_pin=release_pin,
        assignments=assignments,
        assigner_method="subgroup_assigner_classifier",
        variant="classifier",
    )
    click.echo(f"  wrote {out / 'manifest.yaml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
