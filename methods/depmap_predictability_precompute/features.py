"""depmap_predictability_precompute.features — DepMap-parity feature-matrix assembly.

Builds per-gene (cell_line × feature) matrices for the E5 v2 precompute. Matches
DepMap Daintree's feature set as closely as public data allows, with three
target-own axes + genome-wide expr/CN + arm-level CN + OncoKB-derived GoF/LoF
driver flags + lineage one-hot. See the plan file § "Feature set" for the full
mapping to DepMap's transform_* pipeline.

Design:
  - Loaders read the parquet derived product (methods.depmap_common.parquet)
    once per pipeline run; then in-memory sliced per gene. First call downloads
    ~1 GB from S3 to ~/.cache/framework-depmap-26q1-parquet/; subsequent calls
    are local-disk reads.
  - Mutation matrices (Hotspot + Damaging) still come from CSVs — not
    parquetized in depmap-26q1-parquet-v1. Small enough (~340 MB combined)
    that a single S3 fetch per run is fine.
  - Arm-level CN feature class ("genetic_derangement" in DepMap parlance):
    per-gene coords from ensembl-coords manifest + cytoband labels from ucsc-
    cytoband manifest → per-gene arm assignment → mean CN across genes on
    each arm per cell line → shape (n_lines × ~48 arms).
  - OncoKB-derived driver flags: per-gene role from oncokb-gene-roles manifest
    + hotspot/damaging matrix → per-cell-line {Symbol}_GoF / {Symbol}_LoF
    binary flags. Approximates DepMap's transform_driver_events which uses
    OncoKB's auth-gated per-variant annotations.
  - Complete-case masking is applied at feature-matrix build time PER GENE
    (drop rows missing any of the target-own features). Cross-gene features
    are filled with 0 for missing cells (rather than dropping rows) to preserve
    the ~1500-cell CRISPR panel.
"""

from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEPMAP_S3_BUCKET = "onc-compbio"
DEPMAP_SOURCE_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1"

# External source manifests (v2 build depends on these)
CYTOBAND_S3_KEY = (
    "data-catalog/sources/ucsc-cytoband/hg38-snapshot-2026-07-01/cytoBand.txt.gz"
)
ONCOKB_GENE_ROLES_S3_KEY = (
    "data-catalog/sources/oncokb/gene-roles-public-snapshot-2026-07-01/"
    "oncokb_cancer_gene_list.json"
)
ENSEMBL_COORDS_S3_KEY_GLOB = (
    "data-catalog/sources/ensembl-coords/release-116-snapshot-2026-06-22/"
)

# Column-header parsing: "SYMBOL (entrez_id)" → SYMBOL, or plain "SYMBOL" → SYMBOL
_GENE_PAREN_RE = re.compile(r"^([A-Za-z0-9._\-]+)\s*\(\d+\)$")

# Feature-class taxonomy — every feature name resolves to one of these classes
# via _feature_class(). Used by the classifier to identify dominant-feature-class.
FEATURE_CLASS_OWN = {
    "own_expression", "own_copy_number", "own_mut_hotspot", "own_mut_damaging",
}


# ---------------------------------------------------------------------------
# Symbol extraction (shared between loaders)
# ---------------------------------------------------------------------------

def extract_symbol(col: str) -> Optional[str]:
    """Return HGNC symbol from a matrix column header in either form.

    Accepts 'KRAS' or 'KRAS (3845)' or '"KRAS (3845)"'. Returns None for
    empty / non-string inputs. Falls back to first whitespace-split token for
    unrecognized formats — matches the CRISPR loader convention.
    """
    if not isinstance(col, str):
        return None
    s = col.strip().strip('"')
    if not s:
        return None
    m = _GENE_PAREN_RE.match(s)
    if m:
        return m.group(1)
    return s.split(" ", 1)[0] or None


def _rename_gene_cols_to_symbols(df: pd.DataFrame,
                                    protect_cols: set) -> pd.DataFrame:
    """Rename gene-columns (SYMBOL or 'SYMBOL (entrez)') to plain HGNC symbol.
    Metadata columns in `protect_cols` are preserved verbatim. Duplicate symbol
    columns (from split annotations) are collapsed by mean-aggregation.
    """
    new_names = []
    for c in df.columns:
        if c in protect_cols:
            new_names.append(c)
        else:
            new_names.append(extract_symbol(c) or c)
    df = df.copy()
    df.columns = new_names
    # Collapse duplicate symbol columns (mean across them)
    if len(df.columns) != len(set(df.columns)):
        # Split into protected + gene parts, dedupe gene part
        gene_cols = [c for c in df.columns if c not in protect_cols]
        meta_df = df[[c for c in df.columns if c in protect_cols]]
        gene_df = df[gene_cols]
        gene_df = gene_df.T.groupby(level=0).mean().T
        df = pd.concat([meta_df, gene_df], axis=1)
    return df


# ---------------------------------------------------------------------------
# Loaders — each returns a ModelID-indexed DataFrame
# ---------------------------------------------------------------------------

def _s3_read_csv(key: str, **read_csv_kwargs) -> pd.DataFrame:
    """One-shot S3 CSV fetch. Boto3 is imported lazily so tests can monkey-patch."""
    import boto3
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=key)
    return pd.read_csv(BytesIO(obj["Body"].read()), **read_csv_kwargs)


def load_model_metadata() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (Model.csv, ModelCondition.csv) as pandas DataFrames."""
    model_df = _s3_read_csv(f"{DEPMAP_SOURCE_PREFIX}/Model.csv")
    mc_df = _s3_read_csv(f"{DEPMAP_SOURCE_PREFIX}/ModelCondition.csv")
    return model_df, mc_df


def _read_parquet_full(filename: str) -> pd.DataFrame:
    """Read a full parquet from the depmap-26q1-parquet-v1 derived product.

    Uses the shared local-disk cache in depmap_common.parquet — first call in
    a fresh cache pulls from S3, subsequent calls are local reads.
    """
    from methods.depmap_common.parquet import get_full_matrix_path
    import pyarrow.parquet as pq
    local_path = get_full_matrix_path(filename)
    return pq.read_table(local_path).to_pandas()


def load_chronos() -> pd.DataFrame:
    """Chronos matrix indexed by ModelID; columns are HGNC symbols."""
    df = _read_parquet_full("CRISPRGeneEffect.parquet")
    # First column is the unnamed row-index from the CSV; the parquet precompute
    # preserved it. Any of {'index', '', columns[0]} may be the ID col.
    id_col = next((c for c in df.columns if c in ("ModelID", "index")), df.columns[0])
    df = df.set_index(id_col)
    df.index.name = "ModelID"
    df = _rename_gene_cols_to_symbols(df, protect_cols=set())
    return df


def load_expression() -> pd.DataFrame:
    """Expression (log2 TPM+1) matrix indexed by ModelID; columns are HGNC symbols.

    Applies IsDefaultEntryForModel=Yes filter so each cell line has one row.
    """
    df = _read_parquet_full("OmicsExpressionTPMLogp1HumanProteinCodingGenes.parquet")
    if "IsDefaultEntryForModel" in df.columns:
        mask = df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])
        df = df[mask]
    meta_cols = {"SequencingID", "ModelConditionID", "ModelID",
                  "IsDefaultEntryForMC", "IsDefaultEntryForModel"}
    if "ModelID" in df.columns:
        df = df.set_index("ModelID")
    else:
        df = df.set_index(df.columns[0])
        df.index.name = "ModelID"
    df = df.drop(columns=[c for c in df.columns if c in meta_cols], errors="ignore")
    # Final safety net: drop any residual string-dtype columns (post-parquet-precompute
    # metadata leftovers that don't match the meta_cols set exactly).
    obj_cols = [c for c, dt in df.dtypes.items() if dt == object]
    if obj_cols:
        df = df.drop(columns=obj_cols)
    return _rename_gene_cols_to_symbols(df, protect_cols=set())


def _load_cn_parquet(filename: str, mc_to_model: dict) -> Optional[pd.DataFrame]:
    """Load a CN parquet (WES or WGS). Returns ModelID-indexed DataFrame.
    Filter to IsDefaultEntryForMC rows; bridge ModelConditionID → ModelID.
    """
    df = _read_parquet_full(filename)
    if "IsDefaultEntryForMC" in df.columns:
        mask = df["IsDefaultEntryForMC"].isin([True, "Yes", "yes", "true", "TRUE"])
        df = df[mask]
    if "ModelConditionID" not in df.columns:
        return None
    df = df.set_index("ModelConditionID")
    # Drop all standard DepMap metadata cols that CAN appear in a CN parquet.
    # The depmap-26q1-parquet-v1 build preserves several string metadata cols
    # (ModelID, SequencingID, IsDefaultEntryForModel, IsDefaultEntryForMC);
    # any survivor produces a "could not convert string to float" downstream.
    metadata_drops = {
        "ModelID", "SequencingID",
        "IsDefaultEntryForModel", "IsDefaultEntryForMC",
    }
    df = df.drop(columns=[c for c in df.columns if c in metadata_drops], errors="ignore")
    # Bridge MC → Model. Rows with no bridge fall through to the MC id itself.
    df.index = [mc_to_model.get(mc, mc) for mc in df.index]
    df.index.name = "ModelID"
    df = df[~df.index.duplicated(keep="first")]
    # Final safety net: drop any residual object-dtype columns.
    obj_cols = [c for c, dt in df.dtypes.items() if dt == object]
    if obj_cols:
        df = df.drop(columns=obj_cols)
    return _rename_gene_cols_to_symbols(df, protect_cols=set())


def load_copy_number(mc_df: pd.DataFrame) -> pd.DataFrame:
    """WES primary + WGS fallback at the (cell_line, gene) CELL level.

    Uses combine_first: WES value where present, WGS otherwise. Preserves
    ~1500-cell CRISPR panel usable coverage instead of collapsing to
    WES∩CRISPR intersection.
    """
    mc_to_model = {}
    if {"ModelConditionID", "ModelID"}.issubset(mc_df.columns):
        mc_to_model = dict(zip(mc_df["ModelConditionID"], mc_df["ModelID"]))
    wes = _load_cn_parquet("OmicsCNGeneMC_WES.parquet", mc_to_model)
    wgs = _load_cn_parquet("OmicsCNGeneWGS.parquet", mc_to_model)
    if wes is None and wgs is None:
        raise RuntimeError("Both CN parquets missing ModelConditionID; cannot load.")
    if wes is None:
        return wgs
    if wgs is None:
        return wes
    return wes.combine_first(wgs)


def load_mutation_matrix(suffix: str) -> pd.DataFrame:
    """Load OmicsSomaticMutationsMatrix{Hotspot,Damaging}.csv from S3.

    These matrices are NOT parquetized in depmap-26q1-parquet-v1 (only the
    long MAF is). Small enough to fetch as CSV per run (~9 MB Hotspot,
    ~328 MB Damaging).
    """
    key = f"{DEPMAP_SOURCE_PREFIX}/OmicsSomaticMutationsMatrix{suffix}.csv"
    df = _s3_read_csv(key)
    if "IsDefaultEntryForModel" in df.columns:
        mask = df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])
        df = df[mask]
    meta_cols = {"SequencingID", "ModelConditionID", "ModelID",
                  "IsDefaultEntryForMC", "IsDefaultEntryForModel"}
    if "ModelID" in df.columns:
        df = df.set_index("ModelID")
    else:
        df = df.set_index(df.columns[0])
        df.index.name = "ModelID"
    df = df.drop(columns=[c for c in df.columns if c in meta_cols], errors="ignore")
    df = _rename_gene_cols_to_symbols(df, protect_cols=set())
    # Coerce "Yes"/1/True → 1, else 0
    df = df.map(lambda v: 1 if v in (1, True, "Yes", "yes", "true", "TRUE") else 0)
    return df.astype("int8")


# ---------------------------------------------------------------------------
# External-source loaders: cytoband + OncoKB + Ensembl coords
# ---------------------------------------------------------------------------

def _s3_read_gzipped_tsv(key: str, **read_csv_kwargs) -> pd.DataFrame:
    import boto3, gzip
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=key)
    raw = gzip.decompress(obj["Body"].read())
    return pd.read_csv(BytesIO(raw), sep="\t", **read_csv_kwargs)


def load_cytoband() -> pd.DataFrame:
    """Load UCSC hg38 cytoBand table. Returns 5-column DataFrame:
    chrom, chromStart, chromEnd, name, gieStain. Filtered to primary-assembly
    chroms + non-empty band names (drops patch/alt scaffolds).
    """
    df = _s3_read_gzipped_tsv(
        CYTOBAND_S3_KEY,
        header=None,
        names=["chrom", "chromStart", "chromEnd", "name", "gieStain"],
    )
    # Primary-assembly filter: chr1-22, chrX, chrY, chrM (no '_' underscores)
    df = df[~df["chrom"].str.contains("_", na=False)]
    df = df[df["name"].notna() & (df["name"] != "")]
    return df.reset_index(drop=True)


def load_oncokb_gene_roles() -> pd.DataFrame:
    """Load OncoKB public gene-role list. Returns per-gene DataFrame with
    hugoSymbol + geneType columns (plus panel-membership flags kept as-is).
    """
    import boto3
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=ONCOKB_GENE_ROLES_S3_KEY)
    parsed = json.loads(obj["Body"].read())
    df = pd.DataFrame(parsed)
    return df


def load_ensembl_gene_coords() -> pd.DataFrame:
    """Load ensembl-coords release-116 snapshot. Returns per-gene DataFrame
    with HGNC symbol + chrom + start + end.

    The snapshot file name is dynamic (release number embedded). We list the
    prefix and pick the .tsv file inside.
    """
    import boto3
    s3 = boto3.client("s3")
    resp = s3.list_objects_v2(Bucket=DEPMAP_S3_BUCKET, Prefix=ENSEMBL_COORDS_S3_KEY_GLOB)
    tsv_keys = [o["Key"] for o in resp.get("Contents", []) if o["Key"].endswith(".tsv")]
    if not tsv_keys:
        raise FileNotFoundError(f"No .tsv under s3://{DEPMAP_S3_BUCKET}/{ENSEMBL_COORDS_S3_KEY_GLOB}")
    obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=tsv_keys[0])
    df = pd.read_csv(BytesIO(obj["Body"].read()), sep="\t")
    # Normalize column names to what our downstream expects
    df = df.rename(columns={
        "HGNC symbol": "hgnc_symbol",
        "Chromosome/scaffold name": "chrom_name",
        "Gene start (bp)": "gene_start",
        "Gene end (bp)": "gene_end",
    })
    # Only keep primary-assembly chroms
    df = df[df["chrom_name"].isin([str(i) for i in range(1, 23)] + ["X", "Y", "MT"])]
    df = df[df["hgnc_symbol"].notna() & (df["hgnc_symbol"] != "")]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Derived feature matrices: arm-level CN + OncoKB driver flags + lineage
# ---------------------------------------------------------------------------

def assign_genes_to_arms(coords_df: pd.DataFrame,
                           cytoband_df: pd.DataFrame) -> dict:
    """Return {hgnc_symbol -> arm_label} where arm_label = 'chr12p' | 'chr12q' | etc.

    A gene's arm is determined by the FIRST cytoband its midpoint falls into.
    Cytoband name prefix ('p' or 'q') selects the arm.
    """
    # Build a per-chrom sorted list of (start, end, arm) tuples
    band_lookup: dict = {}
    for _, row in cytoband_df.iterrows():
        arm = row["chrom"] + row["name"][0]  # 'chr12p' / 'chr12q'
        band_lookup.setdefault(row["chrom"], []).append(
            (int(row["chromStart"]), int(row["chromEnd"]), arm)
        )
    # Sort each chrom's bands by start position for a binary search
    for chrom in band_lookup:
        band_lookup[chrom].sort()

    def _find_arm(chrom_ucsc: str, midpoint: int) -> Optional[str]:
        bands = band_lookup.get(chrom_ucsc, [])
        for start, end, arm in bands:
            if start <= midpoint < end:
                return arm
        return None

    gene_to_arm = {}
    for _, row in coords_df.iterrows():
        chrom_ucsc = "chr" + str(row["chrom_name"])
        midpoint = int((row["gene_start"] + row["gene_end"]) // 2)
        arm = _find_arm(chrom_ucsc, midpoint)
        if arm:
            gene_to_arm[row["hgnc_symbol"]] = arm
    return gene_to_arm


def compute_arm_level_cn(cn_df: pd.DataFrame,
                          gene_to_arm: dict) -> pd.DataFrame:
    """Per-cell-line arm-mean CN (~48 columns × ~1500 rows).

    For each arm, take the mean CN across all genes on the arm (skipping NaN).
    Cell lines with no CN for any gene on an arm get NaN for that arm.
    """
    # Group gene columns by arm
    arm_to_genes: dict = {}
    for gene, arm in gene_to_arm.items():
        if gene in cn_df.columns:
            arm_to_genes.setdefault(arm, []).append(gene)
    arm_frames = {}
    for arm, genes in arm_to_genes.items():
        arm_frames[f"arm_{arm}"] = cn_df[genes].mean(axis=1, skipna=True)
    return pd.DataFrame(arm_frames)


def compute_oncokb_driver_flags(oncokb_df: pd.DataFrame,
                                    hotspot_df: pd.DataFrame,
                                    damaging_df: pd.DataFrame) -> pd.DataFrame:
    """Per-cell-line {Symbol}_GoF and {Symbol}_LoF driver flags from OncoKB
    gene roles × DepMap hotspot/damaging matrices.

    Rule:
      ONCOGENE + hotspot mutation → {Symbol}_GoF = 1
      TSG + damaging mutation → {Symbol}_LoF = 1
      ONCOGENE_AND_TSG genes get both flags per rule.
    """
    onc_genes = set(oncokb_df.loc[
        oncokb_df["geneType"].isin(["ONCOGENE", "ONCOGENE_AND_TSG"]),
        "hugoSymbol"
    ].dropna())
    tsg_genes = set(oncokb_df.loc[
        oncokb_df["geneType"].isin(["TSG", "ONCOGENE_AND_TSG"]),
        "hugoSymbol"
    ].dropna())
    frames = {}
    for gene in sorted(onc_genes):
        if gene in hotspot_df.columns:
            frames[f"driver_{gene}_GoF"] = hotspot_df[gene].astype("int8")
    for gene in sorted(tsg_genes):
        if gene in damaging_df.columns:
            frames[f"driver_{gene}_LoF"] = damaging_df[gene].astype("int8")
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames)


def build_lineage_one_hot(model_df: pd.DataFrame,
                            min_lines_per_lineage: int = 5) -> pd.DataFrame:
    """One-hot encode Model.csv.OncotreeLineage, collapsing < min_lines
    lineages (and null) into 'OTHER'.
    """
    df = model_df.set_index("ModelID")[["OncotreeLineage"]].copy()
    counts = df["OncotreeLineage"].value_counts(dropna=False)
    keep = set(counts[counts >= min_lines_per_lineage].index.dropna())
    df["bucket"] = df["OncotreeLineage"].where(
        df["OncotreeLineage"].isin(keep), other="OTHER"
    ).fillna("OTHER")
    oh = pd.get_dummies(df["bucket"], prefix="lineage").astype("int8")
    return oh


# ---------------------------------------------------------------------------
# Shared omics bundle (built once per pipeline run)
# ---------------------------------------------------------------------------

def load_all_omics(min_lines_per_lineage: int = 5) -> dict:
    """Load every input matrix + build derived matrices once. Returns dict
    consumed by build_gene_feature_matrix() below.

    All DataFrames are indexed by ModelID; columns are HGNC symbols for the
    numeric matrices and feature-labels for the derived ones (arm_chr12p,
    driver_KRAS_GoF, lineage_Bowel).
    """
    model_df, mc_df = load_model_metadata()
    chronos = load_chronos()
    expression = load_expression()
    copy_number = load_copy_number(mc_df)
    mut_hotspot = load_mutation_matrix("Hotspot")
    mut_damaging = load_mutation_matrix("Damaging")
    lineage_oh = build_lineage_one_hot(model_df, min_lines_per_lineage)

    coords = load_ensembl_gene_coords()
    cytoband = load_cytoband()
    gene_to_arm = assign_genes_to_arms(coords, cytoband)
    arm_cn = compute_arm_level_cn(copy_number, gene_to_arm)

    oncokb_df = load_oncokb_gene_roles()
    driver_flags = compute_oncokb_driver_flags(oncokb_df, mut_hotspot, mut_damaging)

    return {
        "chronos": chronos,
        "expression": expression,
        "copy_number": copy_number,
        "mut_hotspot": mut_hotspot,
        "mut_damaging": mut_damaging,
        "lineage_one_hot": lineage_oh,
        "arm_level_cn": arm_cn,
        "driver_flags": driver_flags,
        "model_df": model_df,
    }


# ---------------------------------------------------------------------------
# Per-gene feature-matrix assembly (the hot loop)
# ---------------------------------------------------------------------------

def feature_class_of(feature_name: str) -> str:
    """Map a feature name to its feature-class taxonomy label.

    Own-omics features have exact names; genome-wide-expr features are prefixed
    by 'expr_' at assembly time; genome-wide-CN by 'cn_'; arm-CN by 'arm_';
    driver flags by 'driver_'; lineage by 'lineage_'.
    """
    if feature_name in FEATURE_CLASS_OWN:
        return feature_name
    if feature_name.startswith("expr_"):
        return "cross_gene_expression"
    if feature_name.startswith("cn_"):
        return "cross_gene_copy_number"
    if feature_name.startswith("arm_"):
        return "arm_level_cn"
    if feature_name.startswith("driver_") and feature_name.endswith("_GoF"):
        return "oncokb_gof"
    if feature_name.startswith("driver_") and feature_name.endswith("_LoF"):
        return "oncokb_lof"
    if feature_name.startswith("lineage_"):
        return "lineage"
    return "other"


def build_gene_feature_matrix(gene: str, omics: dict,
                                  min_cell_lines: int = 100) -> Optional[dict]:
    """Assemble the full feature matrix for one gene. Returns dict:
        {
          'X': ndarray (n_lines, n_features),
          'y': ndarray (n_lines,),
          'feature_names': list[str],
          'model_ids': list[str],
        }
    or None if the gene has insufficient coverage / no target-own signal.

    Complete-case rule (matches the plan's contract):
      - REQUIRE target's Chronos value present (row-drop otherwise)
      - REQUIRE at least one of the four target-own features (drop rows missing
        ALL four); missing individual own-features filled with column median.
      - Cross-gene / arm / driver / lineage features: fill NaN with 0 (matrix-
        wide, most cells are structurally zero anyway for binaries and only
        modestly informative for numerics).
    """
    if gene not in omics["chronos"].columns:
        return None
    y = omics["chronos"][gene].dropna()
    if len(y) < min_cell_lines:
        return None

    parts = []
    feature_names: list = []

    # -- target-own features (four columns; may be missing individually) --
    own_cols = {}
    for fname, key in [
        ("own_expression", "expression"),
        ("own_copy_number", "copy_number"),
        ("own_mut_hotspot", "mut_hotspot"),
        ("own_mut_damaging", "mut_damaging"),
    ]:
        df = omics[key]
        if gene in df.columns:
            own_cols[fname] = df[gene]
    if not own_cols:
        return None
    own_df = pd.DataFrame(own_cols).reindex(y.index)
    # Drop rows where ALL target-own features are missing; median-impute the rest
    keep_mask = own_df.notna().any(axis=1)
    y = y[keep_mask]
    own_df = own_df[keep_mask]
    if len(y) < min_cell_lines:
        return None
    for c in own_df.columns:
        col = own_df[c]
        if col.isna().any():
            median = col.median()
            own_df.loc[:, c] = col.fillna(median if pd.notna(median) else 0.0)
    parts.append(own_df.astype(np.float32))
    feature_names.extend(own_df.columns.tolist())

    # -- cross-gene expression (excluding target's own column, already covered) --
    expr = omics["expression"].reindex(y.index)
    # Rename cols to expr_<SYMBOL>; drop target's own column
    expr_cols = [c for c in expr.columns if c != gene]
    expr = expr[expr_cols]
    expr.columns = [f"expr_{c}" for c in expr.columns]
    expr = expr.fillna(0.0)
    parts.append(expr.astype(np.float32))
    feature_names.extend(expr.columns.tolist())

    # -- cross-gene copy-number --
    cn = omics["copy_number"].reindex(y.index)
    cn_cols = [c for c in cn.columns if c != gene]
    cn = cn[cn_cols]
    cn.columns = [f"cn_{c}" for c in cn.columns]
    cn = cn.fillna(1.0)  # diploid default for CN
    parts.append(cn.astype(np.float32))
    feature_names.extend(cn.columns.tolist())

    # -- arm-level CN --
    arm_cn = omics["arm_level_cn"].reindex(y.index).fillna(1.0)
    parts.append(arm_cn.astype(np.float32))
    feature_names.extend(arm_cn.columns.tolist())

    # -- OncoKB driver flags (exclude own flags: would leak the mutation-status feature) --
    driver_flags = omics["driver_flags"].reindex(y.index).fillna(0)
    own_driver_cols = [f"driver_{gene}_GoF", f"driver_{gene}_LoF"]
    driver_flags = driver_flags.drop(
        columns=[c for c in own_driver_cols if c in driver_flags.columns],
        errors="ignore",
    )
    parts.append(driver_flags.astype(np.int8))
    feature_names.extend(driver_flags.columns.tolist())

    # -- lineage one-hot --
    lineage_oh = omics["lineage_one_hot"].reindex(y.index).fillna(0)
    parts.append(lineage_oh.astype(np.int8))
    feature_names.extend(lineage_oh.columns.tolist())

    # Guardrail: assert no string-dtype columns leaked into any part before hstack.
    # Catches loader regressions early (loud AssertionError with a diagnostic
    # column name beats silent 'could not convert string to float' at RF fit).
    for i, p in enumerate(parts):
        obj_cols = [c for c, dt in p.dtypes.items() if dt == object]
        assert not obj_cols, (
            f"Non-numeric columns in feature-matrix part {i} for gene {gene}: "
            f"{obj_cols[:5]} (dtypes: {p.dtypes[obj_cols[:5]].tolist()})"
        )
    X = np.hstack([p.values for p in parts]).astype(np.float32)
    return {
        "X": X,
        "y": y.values.astype(np.float32),
        "feature_names": feature_names,
        "model_ids": list(y.index),
    }
