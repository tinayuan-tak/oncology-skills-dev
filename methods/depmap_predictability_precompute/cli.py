#!/usr/bin/env python3
"""depmap-predictability-precompute CLI — batch RF training for E5 predictability.

Trains one RandomForestRegressor per gene predicting Chronos dependency from
multi-omics + lineage features. Emits a single parquet (one row per gene) to be
read by the thin `depmap_predictability` card method at framework run-time.

Compute model: ~5-8 s per gene on a single core; medium scope (~500 genes)
parallelizes to ~7 min with ProcessPoolExecutor(max_workers=8). The output
parquet is the v1 frozen derived product `depmap-predictability-26q1-v1`.

Feature classes (target-own only in v1):
  - own_expression        : log2(TPM+1) from OmicsExpressionTPMLogp1HumanProteinCodingGenes
  - own_copy_number       : relative CN (WES primary + WGS fallback per gene)
  - own_mut_hotspot       : binary from OmicsSomaticMutationsMatrixHotspot
  - own_mut_damaging      : binary from OmicsSomaticMutationsMatrixDamaging
  - lineage_*             : one-hot of Model.csv.OncotreeLineage (lineages with
                            < min_lines_per_lineage collapsed to lineage_OTHER)

Gene set (medium scope):
  any-lineage-median-abs-chronos-gt-0.3: include gene if SOME OncotreeLineage
  (n_lines ≥ min_lines_per_lineage) has |median Chronos| > 0.3. Captures
  lineage-selective dependencies that would be flat at the pan-cancer median.
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import click


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

DEPMAP_S3_BUCKET = "onc-compbio"
DEPMAP_S3_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1"

# "SYMBOL (entrez_id)" → SYMBOL extractor used by CN + mutation matrices.
_GENE_PAREN_RE = re.compile(r"^([A-Za-z0-9._\-]+)\s*\(\d+\)$")

# Predictability classification thresholds (mirror card YAML).
R2_HIGH = 0.5
R2_MODERATE = 0.3

OWN_OMICS_FEATURES = {
    "own_expression",
    "own_copy_number",
    "own_mut_hotspot",
    "own_mut_damaging",
}


def _extract_symbol(col: str) -> Optional[str]:
    """Return the HGNC symbol from a column header in either form:
       - plain 'KRAS'  → 'KRAS'
       - 'KRAS (3845)' → 'KRAS'
    Returns None on whitespace / non-symbol inputs.
    """
    if not isinstance(col, str):
        return None
    s = col.strip().strip('"')
    if not s:
        return None
    m = _GENE_PAREN_RE.match(s)
    if m:
        return m.group(1)
    # Fall back: split on first whitespace — matches the CRISPR loader convention.
    return s.split(" ", 1)[0] or None


def _build_symbol_to_col(columns) -> dict:
    """Map HGNC symbol → first column whose header resolves to that symbol.

    When a matrix mixes plain and 'SYMBOL (entrez_id)' headers, the parenthesized
    form wins (it's the unambiguous DepMap canonical form). Last-write-wins is
    safe here because identical symbols across the same matrix would be a data
    pathology we'd want to surface, not silently dedupe.
    """
    sym_to_col = {}
    for c in columns:
        s = _extract_symbol(c)
        if not s:
            continue
        sym_to_col[s] = c
    return sym_to_col


def _coerce_isdefault(series) -> "pandas.Series":
    """Normalize DepMap's IsDefaultEntry* columns to boolean.

    26Q1 ships these as string 'Yes'/'No'; older releases as boolean. Mirrors
    the convention in depmap_expression_distribution.cli.
    """
    return series.isin([True, "Yes", "yes", "true", "TRUE"])


# ---------------------------------------------------------------------------
# Loaders — each returns a (cell_lines × genes) pandas DataFrame indexed by ModelID
# ---------------------------------------------------------------------------

def _s3_read_csv(bucket: str, key: str, **read_csv_kwargs):
    import boto3
    import pandas as pd
    s3 = boto3.client("s3")
    click.echo(f"  Fetching s3://{bucket}/{key}", err=True)
    obj = s3.get_object(Bucket=bucket, Key=key)
    return pd.read_csv(BytesIO(obj["Body"].read()), **read_csv_kwargs)


def load_chronos(release_pin: str = "26q1"):
    """Returns (chronos_df indexed by ModelID, gene-cols are HGNC symbols)."""
    import pandas as pd
    df = _s3_read_csv(DEPMAP_S3_BUCKET, f"{DEPMAP_S3_PREFIX}/CRISPRGeneEffect.csv")
    # First column is the ModelID index (unnamed in some releases)
    id_col = df.columns[0]
    df = df.set_index(id_col)
    df.index.name = "ModelID"
    # Rename gene columns to plain HGNC symbol
    df.columns = [_extract_symbol(c) or c for c in df.columns]
    # Collapse possible duplicate symbol columns (mean across them — matches
    # how downstream methods do the column lookup).
    if len(df.columns) != len(set(df.columns)):
        df = df.T.groupby(level=0).mean().T
    return df


def load_expression(release_pin: str = "26q1"):
    """Returns (expression_df indexed by ModelID, gene-cols are HGNC symbols).

    Applies IsDefaultEntryForModel=Yes filter to collapse multi-condition lines.
    """
    import pandas as pd
    df = _s3_read_csv(
        DEPMAP_S3_BUCKET,
        f"{DEPMAP_S3_PREFIX}/OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv",
    )
    if "IsDefaultEntryForModel" in df.columns:
        df = df[_coerce_isdefault(df["IsDefaultEntryForModel"])]
    # Drop metadata-prefix columns; keep ModelID as the row index.
    meta_cols = {
        "SequencingID", "ModelConditionID", "ModelID",
        "IsDefaultEntryForMC", "IsDefaultEntryForModel",
    }
    if "ModelID" not in df.columns:
        # Older release: first column is the ModelID index
        id_col = df.columns[0]
        df = df.set_index(id_col)
        df.index.name = "ModelID"
    else:
        df = df.set_index("ModelID")
    df = df.drop(columns=[c for c in df.columns if c in meta_cols], errors="ignore")
    df.columns = [_extract_symbol(c) or c for c in df.columns]
    if len(df.columns) != len(set(df.columns)):
        df = df.T.groupby(level=0).mean().T
    return df


def _load_cn_matrix(key: str, mc_to_model: dict):
    """Shared loader for OmicsCNGeneMC_WES / OmicsCNGeneWGS.

    Both matrices are ModelConditionID-indexed; we filter to IsDefaultEntryForMC
    rows then bridge to ModelID via the mc_to_model dict (from ModelCondition.csv).
    """
    import pandas as pd
    df = _s3_read_csv(DEPMAP_S3_BUCKET, key)
    if "IsDefaultEntryForMC" in df.columns:
        df = df[_coerce_isdefault(df["IsDefaultEntryForMC"])]
    if "ModelConditionID" not in df.columns:
        return None
    df = df.set_index("ModelConditionID")
    df = df.drop(columns=[c for c in df.columns if c == "IsDefaultEntryForMC"], errors="ignore")
    # Bridge MC → ModelID; rows with no mapping fall back to the MC ID itself.
    new_index = [mc_to_model.get(mc, mc) for mc in df.index]
    df.index = new_index
    df.index.name = "ModelID"
    # Collapse any duplicate ModelIDs (rare: one cell line with multiple default MCs).
    df = df[~df.index.duplicated(keep="first")]
    df.columns = [_extract_symbol(c) or c for c in df.columns]
    if len(df.columns) != len(set(df.columns)):
        df = df.T.groupby(level=0).mean().T
    return df


def load_copy_number(model_condition_df, release_pin: str = "26q1"):
    """WES primary + WGS fallback at the (cell_line, gene) CELL level.

    Combines OmicsCNGeneMC_WES and OmicsCNGeneWGS so every (ModelID, gene) cell
    prefers WES but falls back to WGS when WES is NaN. This preserves the
    ~1500-cell CRISPR panel's usable coverage instead of collapsing to the
    ~600-cell WES∩CRISPR intersection that a plain WES-only load produces.

    Returns one combined DataFrame indexed by ModelID, gene-cols are HGNC symbols.
    """
    mc_to_model = {}
    if {"ModelConditionID", "ModelID"}.issubset(model_condition_df.columns):
        mc_to_model = dict(zip(model_condition_df["ModelConditionID"],
                                model_condition_df["ModelID"]))
    wes = _load_cn_matrix(f"{DEPMAP_S3_PREFIX}/OmicsCNGeneMC_WES.csv", mc_to_model)
    wgs = _load_cn_matrix(f"{DEPMAP_S3_PREFIX}/OmicsCNGeneWGS.csv", mc_to_model)
    if wes is None and wgs is None:
        raise RuntimeError("Both CN matrices missing ModelConditionID; cannot load.")
    if wes is None:
        return wgs
    if wgs is None:
        return wes
    # combine_first: WES wins where non-NaN; WGS fills WES NaNs and supplies
    # both cell lines outside the WES panel AND genes outside the WES panel.
    combined = wes.combine_first(wgs)
    return combined


def load_mutation_matrix(filename_suffix: str, release_pin: str = "26q1"):
    """Shared loader for the Hotspot / Damaging mutation matrices.

    These are ModelID-row × gene-col binary matrices (0/1) with the standard
    DepMap metadata-column prefix. Returns DataFrame indexed by ModelID.
    """
    import pandas as pd
    key = f"{DEPMAP_S3_PREFIX}/OmicsSomaticMutationsMatrix{filename_suffix}.csv"
    df = _s3_read_csv(DEPMAP_S3_BUCKET, key)
    if "IsDefaultEntryForModel" in df.columns:
        df = df[_coerce_isdefault(df["IsDefaultEntryForModel"])]
    meta_cols = {
        "SequencingID", "ModelConditionID", "ModelID",
        "IsDefaultEntryForMC", "IsDefaultEntryForModel",
    }
    if "ModelID" not in df.columns:
        id_col = df.columns[0]
        df = df.set_index(id_col)
        df.index.name = "ModelID"
    else:
        df = df.set_index("ModelID")
    df = df.drop(columns=[c for c in df.columns if c in meta_cols], errors="ignore")
    df.columns = [_extract_symbol(c) or c for c in df.columns]
    if len(df.columns) != len(set(df.columns)):
        # Mutation matrices are binary; OR-aggregate duplicates.
        df = df.T.groupby(level=0).max().T
    # Coerce to int (some files have "Yes"/"No" strings)
    import numpy as np
    df = df.map(lambda v: 1 if v in (1, True, "Yes", "yes", "true", "TRUE") else 0)
    return df.astype("int8")


def load_model_metadata(release_pin: str = "26q1"):
    """Returns (model_df, model_condition_df) — both pandas DataFrames."""
    model_df = _s3_read_csv(DEPMAP_S3_BUCKET, f"{DEPMAP_S3_PREFIX}/Model.csv")
    mc_df = _s3_read_csv(DEPMAP_S3_BUCKET, f"{DEPMAP_S3_PREFIX}/ModelCondition.csv")
    return model_df, mc_df


# ---------------------------------------------------------------------------
# Gene-set selection (medium scope, per-lineage rule)
# ---------------------------------------------------------------------------

def build_medium_gene_set(chronos_df, model_df,
                            min_lines_per_lineage: int = 5,
                            threshold: float = 0.3) -> list:
    """Return sorted list of HGNC symbols whose |median Chronos| > threshold
    in at least one OncotreeLineage with ≥ min_lines_per_lineage cell lines.

    The chronos_df is ModelID-row × gene-col. The model_df provides
    OncotreeLineage per ModelID.
    """
    import numpy as np
    import pandas as pd
    if "ModelID" not in model_df.columns:
        raise ValueError("Model.csv missing ModelID column")
    if "OncotreeLineage" not in model_df.columns:
        raise ValueError("Model.csv missing OncotreeLineage column")
    lineage_map = dict(zip(model_df["ModelID"], model_df["OncotreeLineage"]))
    lineages = pd.Series([lineage_map.get(m) for m in chronos_df.index],
                          index=chronos_df.index, name="OncotreeLineage")
    # Bucket cell-line indices by lineage (ignore None/empty)
    lineage_groups = {}
    for mid, lin in lineages.items():
        if not isinstance(lin, str) or not lin:
            continue
        lineage_groups.setdefault(lin, []).append(mid)
    keepers = set()
    for lin, mids in lineage_groups.items():
        if len(mids) < min_lines_per_lineage:
            continue
        sub = chronos_df.loc[mids]
        medians = sub.median(axis=0, skipna=True)
        for gene, m in medians.items():
            if pd.notna(m) and abs(m) > threshold:
                keepers.add(gene)
    return sorted(keepers)


# ---------------------------------------------------------------------------
# Feature matrix assembly + RF training (per gene)
# ---------------------------------------------------------------------------

def build_lineage_one_hot(model_df, min_lines_per_lineage: int = 5):
    """Return (lineage_df indexed by ModelID, lineage_columns list).

    Lineages with fewer than `min_lines_per_lineage` cell lines are collapsed
    into a single `lineage_OTHER` column. The "unknown" / NaN bucket also folds
    into OTHER (treated as a non-informative one-hot dimension).
    """
    import pandas as pd
    df = model_df.set_index("ModelID")[["OncotreeLineage"]].copy()
    counts = df["OncotreeLineage"].value_counts(dropna=False)
    keep = set(counts[counts >= min_lines_per_lineage].index.dropna())
    df["lineage_bucket"] = df["OncotreeLineage"].where(
        df["OncotreeLineage"].isin(keep), other="OTHER"
    )
    df["lineage_bucket"] = df["lineage_bucket"].fillna("OTHER")
    oh = pd.get_dummies(df["lineage_bucket"], prefix="lineage")
    oh = oh.astype("int8")
    return oh, list(oh.columns)


def build_feature_matrix_for_gene(gene: str, omics):
    """Assemble X (n_cell_lines, n_features), y (n_cell_lines,), feature_names.

    `omics` is a dict with keys: chronos, expression, copy_number, mut_hotspot,
    mut_damaging, lineage_one_hot. Each value is a pandas DataFrame indexed by
    ModelID. We require the target gene to be present in chronos + at least one
    omics modality; missing modalities for the gene fill with NaN columns and
    are dropped row-wise in the complete-case alignment.

    Returns (X_array, y_array, feature_names, model_ids) or
    (None, None, None, None) if there is no usable signal.
    """
    import numpy as np
    import pandas as pd
    if gene not in omics["chronos"].columns:
        return None, None, None, None
    y_series = omics["chronos"][gene]
    own_cols = {}
    for fname, df_key in [
        ("own_expression", "expression"),
        ("own_copy_number", "copy_number"),
        ("own_mut_hotspot", "mut_hotspot"),
        ("own_mut_damaging", "mut_damaging"),
    ]:
        df = omics[df_key]
        if gene in df.columns:
            own_cols[fname] = df[gene]
    if not own_cols:
        # Nothing but Chronos; cannot train a meaningful model.
        return None, None, None, None
    own_df = pd.DataFrame(own_cols)
    lineage_df = omics["lineage_one_hot"]
    # Align everyone on the chronos index (the union of cell lines with a y value)
    y = y_series.dropna()
    own_df = own_df.reindex(y.index)
    lineage_df = lineage_df.reindex(y.index)
    full = pd.concat([own_df, lineage_df], axis=1)
    # Complete-case: drop rows missing any own_omic column. Lineage one-hot is
    # always present (rows missing in lineage_df get NaN → 0 for the OTHER one-hot
    # if we ever add one). For simplicity we require all own_omics columns present.
    mask = own_df.notna().all(axis=1) & lineage_df.notna().all(axis=1)
    full = full[mask]
    y = y[mask]
    if len(full) < 100:
        return None, None, None, None
    feature_names = list(full.columns)
    return full.values.astype(np.float32), y.values.astype(np.float32), feature_names, list(full.index)


def _classify_predictability(top_feature: str, r2: float) -> tuple[str, str]:
    """Return (predictability_class, dominant_feature_class).

    Class taxonomy:
      r2 < R2_MODERATE        → unpredictable     / 'unpredictable'
      R2_MODERATE ≤ r2 < R2_HIGH → weakly_predictable / dominant feature
      r2 ≥ R2_HIGH:
        top_feature starts with 'lineage_' → lineage_driven / 'lineage'
        top_feature in OWN_OMICS_FEATURES  → own_omics_driven / top_feature
    """
    if r2 < R2_MODERATE:
        return "unpredictable", "unpredictable"
    if top_feature.startswith("lineage_"):
        if r2 >= R2_HIGH:
            return "lineage_driven", "lineage"
        return "weakly_predictable", "lineage"
    if top_feature in OWN_OMICS_FEATURES:
        if r2 >= R2_HIGH:
            return "own_omics_driven", top_feature
        return "weakly_predictable", top_feature
    # Unrecognized feature name — treat as weakly_predictable / 'other'
    if r2 >= R2_HIGH:
        return "own_omics_driven", top_feature
    return "weakly_predictable", top_feature


def _feature_class(feature_name: str) -> str:
    if feature_name.startswith("lineage_"):
        return "lineage"
    if feature_name in OWN_OMICS_FEATURES:
        return feature_name
    return "other"


def train_one_gene(gene: str, X, y, feature_names,
                    n_estimators: int = 100, max_depth: int = 10,
                    cv_n_splits: int = 5, random_state: int = 42) -> dict:
    """Train RF, return per-gene record matching the parquet schema."""
    import numpy as np
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import KFold

    kf = KFold(n_splits=cv_n_splits, shuffle=True, random_state=random_state)
    y_oof = np.full_like(y, np.nan, dtype=np.float32)
    for tr, te in kf.split(X):
        m = RandomForestRegressor(n_estimators=n_estimators, max_depth=max_depth,
                                    random_state=random_state, n_jobs=1)
        m.fit(X[tr], y[tr])
        y_oof[te] = m.predict(X[te])

    # Out-of-fold Pearson² R². Handle the degenerate case where y or y_oof has
    # zero variance — np.corrcoef returns NaN, which we map to 0.0 so the
    # downstream classifier reads it as 'unpredictable' rather than blowing up.
    if np.std(y) < 1e-9 or np.std(y_oof) < 1e-9:
        r2 = 0.0
    else:
        r = float(np.corrcoef(y_oof, y)[0, 1])
        r2 = r * r
        if not np.isfinite(r2):
            r2 = 0.0

    # Refit on all data for importances
    full_model = RandomForestRegressor(n_estimators=n_estimators, max_depth=max_depth,
                                          random_state=random_state, n_jobs=1)
    full_model.fit(X, y)
    importances = full_model.feature_importances_
    order = np.argsort(importances)[::-1]
    top_features = []
    for idx in order[:5]:
        fname = feature_names[idx]
        top_features.append({
            "feature": fname,
            "feature_class": _feature_class(fname),
            "importance": float(importances[idx]),
        })

    top_feature_name = top_features[0]["feature"]
    pred_class, dominant_class = _classify_predictability(top_feature_name, r2)

    return {
        "gene_symbol": gene,
        "n_cell_lines_evaluated": int(X.shape[0]),
        "predictability_r2": float(r2),
        "top_features": top_features,
        "dominant_feature_class": dominant_class,
        "predictability_class": pred_class,
    }


# ---------------------------------------------------------------------------
# Parallel worker wrapper — extracts gene's slice of omics, trains, returns record.
# Defined at module level so ProcessPoolExecutor can pickle it.
# ---------------------------------------------------------------------------

_WORKER_OMICS = None  # set by initializer


def _worker_init(omics_pickle_path):
    """ProcessPool initializer: load omics dict once per worker from disk pickle."""
    global _WORKER_OMICS
    import pickle
    with open(omics_pickle_path, "rb") as f:
        _WORKER_OMICS = pickle.load(f)


def _worker_train(gene: str) -> Optional[dict]:
    if _WORKER_OMICS is None:
        raise RuntimeError("_WORKER_OMICS not initialized")
    X, y, fnames, _ = build_feature_matrix_for_gene(gene, _WORKER_OMICS)
    if X is None:
        return None
    try:
        return train_one_gene(gene, X, y, fnames)
    except Exception as e:
        return {"gene_symbol": gene, "_error": str(e)}


# ---------------------------------------------------------------------------
# Parquet writer
# ---------------------------------------------------------------------------

def write_parquet(records: list, out_path: Path) -> Path:
    """Write per-gene records to a sorted parquet with row-group-size=64 to
    enable predicate-pushdown reads in the thin lookup card.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows = sorted([r for r in records if r and "_error" not in r],
                   key=lambda r: r["gene_symbol"])
    # Build PyArrow schema explicitly for stable column types.
    top_feature_struct = pa.struct([
        pa.field("feature", pa.string()),
        pa.field("feature_class", pa.string()),
        pa.field("importance", pa.float32()),
    ])
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("n_cell_lines_evaluated", pa.int32()),
        pa.field("predictability_r2", pa.float32()),
        pa.field("top_features", pa.list_(top_feature_struct)),
        pa.field("dominant_feature_class", pa.string()),
        pa.field("predictability_class", pa.string()),
    ])
    arrays = {
        "gene_symbol": [r["gene_symbol"] for r in rows],
        "n_cell_lines_evaluated": [r["n_cell_lines_evaluated"] for r in rows],
        "predictability_r2": [r["predictability_r2"] for r in rows],
        "top_features": [r["top_features"] for r in rows],
        "dominant_feature_class": [r["dominant_feature_class"] for r in rows],
        "predictability_class": [r["predictability_class"] for r in rows],
    }
    table = pa.Table.from_pydict(arrays, schema=schema)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path, row_group_size=64, compression="snappy")
    return out_path


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

@click.command()
@click.option("--release-pin", default="26q1", show_default=True)
@click.option("--gene-set", type=click.Choice(["smoke", "medium", "explicit"]),
              default="medium", show_default=True,
              help="smoke=5-gene fixed; medium=per-lineage |median Chronos|>0.3; explicit=use --gene-set-override")
@click.option("--gene-set-override", default=None,
              help="Comma-separated HGNC symbols (overrides --gene-set when --gene-set=explicit, "
                    "or appended to smoke).")
@click.option("--out", required=True, type=click.Path(path_type=Path),
              help="Output directory or file path. Writes predictability_per_gene.parquet inside.")
@click.option("--workers", default=8, show_default=True, type=int)
@click.option("--min-lines-per-lineage", default=5, show_default=True, type=int)
@click.option("--threshold", default=0.3, show_default=True, type=float)
def main(release_pin, gene_set, gene_set_override, out, workers,
          min_lines_per_lineage, threshold):
    import pickle
    import tempfile

    out = Path(out)
    if out.suffix == ".parquet":
        parquet_path = out
        out_dir = out.parent
    else:
        out_dir = out
        parquet_path = out_dir / "predictability_per_gene.parquet"
    out_dir.mkdir(parents=True, exist_ok=True)

    click.echo("Loading DepMap inputs from S3...", err=True)
    model_df, mc_df = load_model_metadata(release_pin)
    chronos = load_chronos(release_pin)
    click.echo(f"  CRISPR loaded: {chronos.shape[0]} cell lines × {chronos.shape[1]} genes", err=True)
    expression = load_expression(release_pin)
    click.echo(f"  Expression loaded: {expression.shape}", err=True)
    cn = load_copy_number(mc_df, release_pin)
    click.echo(f"  CN loaded: {cn.shape}", err=True)
    mut_hot = load_mutation_matrix("Hotspot", release_pin)
    click.echo(f"  Mut hotspot loaded: {mut_hot.shape}", err=True)
    mut_dmg = load_mutation_matrix("Damaging", release_pin)
    click.echo(f"  Mut damaging loaded: {mut_dmg.shape}", err=True)

    lineage_oh, lineage_cols = build_lineage_one_hot(model_df, min_lines_per_lineage)
    click.echo(f"  Lineage one-hot: {lineage_oh.shape[1]} dims (post-collapse)", err=True)

    # Gene-set selection
    if gene_set == "smoke":
        smoke_set = ["KRAS", "TP53", "MYC", "BRAF", "EGFR"]
        if gene_set_override:
            smoke_set = list(dict.fromkeys(smoke_set + [g.strip() for g in gene_set_override.split(",")]))
        genes = smoke_set
    elif gene_set == "explicit":
        if not gene_set_override:
            raise click.UsageError("--gene-set=explicit requires --gene-set-override=SYM1,SYM2,...")
        genes = [g.strip() for g in gene_set_override.split(",") if g.strip()]
    else:  # medium
        click.echo("Building medium-scope gene set (any-lineage |median Chronos| > "
                    f"{threshold:.2f}, min {min_lines_per_lineage} lines/lineage)...", err=True)
        genes = build_medium_gene_set(chronos, model_df,
                                         min_lines_per_lineage=min_lines_per_lineage,
                                         threshold=threshold)
        click.echo(f"  Selected {len(genes)} genes", err=True)

    omics = {
        "chronos": chronos,
        "expression": expression,
        "copy_number": cn,
        "mut_hotspot": mut_hot,
        "mut_damaging": mut_dmg,
        "lineage_one_hot": lineage_oh,
    }

    # Workers — train in parallel via pool initializer-loaded pickle.
    records = []
    excluded_low_coverage = 0
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tf:
        omics_pkl = Path(tf.name)
    try:
        click.echo(f"Pickling shared omics dict to {omics_pkl} for workers...", err=True)
        with open(omics_pkl, "wb") as f:
            pickle.dump(omics, f, protocol=pickle.HIGHEST_PROTOCOL)

        click.echo(f"Training {len(genes)} genes across {workers} workers...", err=True)
        if workers <= 1:
            # Single-process path — simpler for tests + debugging
            _worker_init(omics_pkl)
            for i, gene in enumerate(genes):
                rec = _worker_train(gene)
                if rec is None:
                    excluded_low_coverage += 1
                else:
                    records.append(rec)
                if (i + 1) % 25 == 0:
                    click.echo(f"  {i + 1}/{len(genes)} genes done", err=True)
        else:
            with ProcessPoolExecutor(max_workers=workers,
                                       initializer=_worker_init,
                                       initargs=(omics_pkl,)) as ex:
                futures = {ex.submit(_worker_train, g): g for g in genes}
                for i, fut in enumerate(as_completed(futures)):
                    rec = fut.result()
                    if rec is None:
                        excluded_low_coverage += 1
                    else:
                        records.append(rec)
                    if (i + 1) % 25 == 0:
                        click.echo(f"  {i + 1}/{len(genes)} genes done", err=True)
    finally:
        omics_pkl.unlink(missing_ok=True)

    click.echo(f"Writing parquet to {parquet_path}", err=True)
    write_parquet(records, parquet_path)

    # Run manifest (for traceability — DOES NOT replace the catalog derived manifest)
    run_manifest = {
        "method_id": "depmap-predictability-precompute",
        "method_version": METHOD_VERSION,
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gene_set_mode": gene_set,
        "n_genes_requested": len(genes),
        "n_genes_evaluated": len([r for r in records if r and "_error" not in r]),
        "n_genes_excluded_low_coverage": excluded_low_coverage,
        "n_genes_errored": len([r for r in records if r and "_error" in r]),
        "parameters": {
            "min_lines_per_lineage": min_lines_per_lineage,
            "threshold": threshold,
            "rf_n_estimators": 100,
            "rf_max_depth": 10,
            "cv_n_splits": 5,
            "random_state": 42,
        },
    }
    (out_dir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2))
    click.echo(f"Done. Run manifest at {out_dir / 'run_manifest.json'}", err=True)


if __name__ == "__main__":
    main()
