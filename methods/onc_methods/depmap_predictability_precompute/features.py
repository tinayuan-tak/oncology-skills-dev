"""depmap_predictability_precompute.features — DepMap-parity feature-matrix assembly.

Builds per-gene (cell_line × feature) matrices for the E5 v2 precompute. Matches
DepMap Daintree's feature set as closely as public data allows, with three
target-own axes + genome-wide expr/CN + arm-level CN + OncoKB-derived GoF/LoF
driver flags + lineage one-hot. See the plan file § "Feature set" for the full
mapping to DepMap's transform_* pipeline.

Design:
  - Loaders read the parquet derived product (methods.depmap_common.parquet)
    once per pipeline run; then in-memory sliced per gene. First call downloads
    ~1 GB from S3 to ~/.cache/framework-depmap-26q3-parquet/; subsequent calls
    are local-disk reads.
  - Mutation matrices (Hotspot + Damaging) still come from CSVs — not
    parquetized in depmap-26q3-parquet-v1. Small enough (~340 MB combined)
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
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEPMAP_S3_BUCKET = "onc-compbio"
DEPMAP_SOURCE_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q3"
DEPMAP_PROTEOMICS_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1-proteomics"
DEPMAP_PARALOGS_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1-paralogs"
DEPMAP_CCLE_2019_PREFIX = "data-catalog/sources/depmap-consortium/dmc-ccle-2019"

# External source manifests (v2 build depends on these)
CYTOBAND_S3_KEY = "data-catalog/sources/ucsc-cytoband/hg38-snapshot-2026-07-01/cytoBand.txt.gz"
ONCOKB_GENE_ROLES_S3_KEY = (
    "data-catalog/sources/oncokb/gene-roles-public-snapshot-2026-07-01/oncokb_cancer_gene_list.json"
)
ENSEMBL_COORDS_S3_KEY_GLOB = "data-catalog/sources/ensembl-coords/release-116-snapshot-2026-06-22/"

# v2.1 feature-source keys — all confirmed on S3 2026-07-01
FUSION_S3_KEY = f"{DEPMAP_SOURCE_PREFIX}/OmicsFusionFiltered.csv"
RPPA_S3_KEY = f"{DEPMAP_PROTEOMICS_PREFIX}/harmonized_RPPA_CCLE.csv"
MS_GYGI_S3_KEY = f"{DEPMAP_PROTEOMICS_PREFIX}/harmonized_MS_CCLE_Gygi.csv"
UNIPROT_HGNC_MAP_S3_KEY = f"{DEPMAP_PROTEOMICS_PREFIX}/uniprot_hugo_entrez_id_mapping_26q1.csv"
PARALOG_DEP_S3_KEY = f"{DEPMAP_PARALOGS_PREFIX}/ParalogGeneEffect.csv"
MOLSIG_S3_KEY = f"{DEPMAP_SOURCE_PREFIX}/OmicsMolecularSignatureMatrix.csv"
MSI_S3_KEY = f"{DEPMAP_SOURCE_PREFIX}/OmicsMicrosatelliteRepeats.csv"
SV_MATRIX_S3_KEY = f"{DEPMAP_SOURCE_PREFIX}/OmicsStructuralVariantsMatrix.csv"
OMICS_PROFILES_S3_KEY = f"{DEPMAP_SOURCE_PREFIX}/OmicsProfiles.csv"
RRBS_S3_KEY = f"{DEPMAP_CCLE_2019_PREFIX}/CCLE_RRBS_TSS_1kb_20180614.txt"
METABOLOMICS_S3_KEY = f"{DEPMAP_CCLE_2019_PREFIX}/CCLE_metabolomics_20190502.csv"

# Column-header parsing: "SYMBOL (entrez_id)" → SYMBOL, or plain "SYMBOL" → SYMBOL
_GENE_PAREN_RE = re.compile(r"^([A-Za-z0-9._\-]+)\s*\(\d+\)$")

# Bare Ensembl gene-ID header (e.g. "ENSG00000258790", optionally version-suffixed).
# Some DepMap matrix columns (notably CN genes with no HGNC mapping in DepMap) arrive
# as a bare ENSG id; naming a cross-gene feature `cn_ENSG…` makes it invisible to the
# sole mechanistic consumer (mechanism-and-pharmacology's SIGNOR cross-ref, which keys
# on HGNC symbols). We resolve ENSG→HGNC at feature-naming time via the manifest-pinned
# ensembl-id-mapping-release-116 sidecar (see _resolve_ensembl_id / #806).
_ENSG_RE = re.compile(r"^ENSG\d+")

# ensembl-id-mapping-release-116-snapshot-2026-06-18 (data-catalog manifest, bucket
# onc-compbio). TSV columns: "Gene stable ID" (ENSG…, no version) + "HGNC symbol".
ENSEMBL_ID_MAP_S3_KEY = (
    "data-catalog/sources/ensembl-id-mapping/release-116-snapshot-2026-06-18/hsapiens_gene_id_map_release-116.tsv"
)

# Module-wide lazy cache of the ENSG→HGNC bridge. None = not yet loaded.
_ensg_symbol_map: Optional[dict] = None

# Feature-class taxonomy — every feature name resolves to one of these classes
# via _feature_class(). Used by the classifier to identify dominant-feature-class.
FEATURE_CLASS_OWN = {
    "own_expression",
    "own_copy_number",
    "own_mut_hotspot",
    "own_mut_damaging",
}


# ---------------------------------------------------------------------------
# Symbol extraction (shared between loaders)
# ---------------------------------------------------------------------------


def _load_ensg_symbol_map() -> dict:
    """Ensembl gene ID ("Gene stable ID", ENSG…, version-stripped) → HGNC symbol.

    Reads the manifest-pinned ensembl-id-mapping-release-116 sidecar once and caches
    the dict module-wide. Only rows with a non-empty HGNC symbol are kept. Returns {}
    if the sidecar can't be read — feature naming then falls back to the bare ENSG id
    (a visible breadcrumb rather than a silent drop). Uses _s3_read_csv so tests can
    monkey-patch the S3 seam (or inject `_ensg_symbol_map` directly).
    """
    global _ensg_symbol_map
    if _ensg_symbol_map is not None:
        return _ensg_symbol_map
    mapping: dict[str, str] = {}
    try:
        df = _s3_read_csv(ENSEMBL_ID_MAP_S3_KEY, sep="\t")
        for gid, sym in zip(df["Gene stable ID"].astype(str), df["HGNC symbol"]):
            g = gid.strip()
            if g and isinstance(sym, str) and sym.strip():
                mapping[g] = sym.strip()
    except Exception:  # absence-discipline: exempt -- sidecar unreadable ⇒ ENSG id kept as breadcrumb (no silent drop)
        mapping = {}
    _ensg_symbol_map = mapping
    return _ensg_symbol_map


def _resolve_ensembl_id(ensg: str) -> str:
    """Map a bare Ensembl gene ID (ENSG…, any version suffix) to its HGNC symbol via
    the pinned ensembl-id-mapping-release-116 sidecar. When NO HGNC mapping exists the
    Ensembl ID is returned UNCHANGED — the unmapped feature keeps its ENSG name as a
    breadcrumb so the translation gap stays visible rather than being silently dropped.
    """
    return _load_ensg_symbol_map().get(ensg.split(".", 1)[0], ensg)


def extract_symbol(col: str) -> Optional[str]:
    """Return HGNC symbol from a matrix column header in either form.

    Accepts 'KRAS' or 'KRAS (3845)' or '"KRAS (3845)"'. Returns None for
    empty / non-string inputs. Falls back to first whitespace-split token for
    unrecognized formats — matches the CRISPR loader convention. A bare Ensembl
    gene ID (ENSG…) is resolved to its HGNC symbol via the pinned sidecar so
    cross-gene feature names stay symbol-keyed for the SIGNOR consumer (#806).
    """
    if not isinstance(col, str):
        return None
    s = col.strip().strip('"')
    if not s:
        return None
    m = _GENE_PAREN_RE.match(s)
    if m:
        token = m.group(1)
    else:
        token = s.split(" ", 1)[0] or None
    if token and _ENSG_RE.match(token):
        return _resolve_ensembl_id(token)
    return token


def _rename_gene_cols_to_symbols(df: pd.DataFrame, protect_cols: set) -> pd.DataFrame:
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
    """Read a full parquet from the depmap-26q3-parquet-v1 derived product.

    Uses the shared local-disk cache in depmap_common.parquet — first call in
    a fresh cache pulls from S3, subsequent calls are local reads.
    """
    import pyarrow.parquet as pq

    from onc_methods.depmap_common.parquet import get_full_matrix_path

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
    # Include "Unnamed: 0" (pandas row-index artifact from CSV→parquet conversion)
    # and pattern-match any other Unnamed columns to protect against schema drift.
    meta_cols = {"SequencingID", "ModelConditionID", "ModelID", "IsDefaultEntryForMC", "IsDefaultEntryForModel"}
    for c in df.columns:
        if c.startswith("Unnamed"):
            meta_cols.add(c)
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
    # The depmap-26q3-parquet-v1 build preserves several string metadata cols
    # (ModelID, SequencingID, IsDefaultEntryForModel, IsDefaultEntryForMC);
    # any survivor produces a "could not convert string to float" downstream.
    metadata_drops = {
        "ModelID",
        "SequencingID",
        "IsDefaultEntryForModel",
        "IsDefaultEntryForMC",
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

    These matrices are NOT parquetized in depmap-26q3-parquet-v1 (only the
    long MAF is). Small enough to fetch as CSV per run (~9 MB Hotspot,
    ~328 MB Damaging).
    """
    key = f"{DEPMAP_SOURCE_PREFIX}/OmicsSomaticMutationsMatrix{suffix}.csv"
    df = _s3_read_csv(key)
    if "IsDefaultEntryForModel" in df.columns:
        mask = df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])
        df = df[mask]
    meta_cols = {"SequencingID", "ModelConditionID", "ModelID", "IsDefaultEntryForMC", "IsDefaultEntryForModel"}
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
# v2.1 loaders — the 8 previously-declared "gaps" (all confirmed in S3)
# ---------------------------------------------------------------------------


def load_uniprot_hgnc_map() -> dict:
    """Return {UniprotID → HGNC Symbol} from Broad's shipped mapping file.

    Broad ships `uniprot_hugo_entrez_id_mapping_26q1.csv` alongside the RPPA
    and MS proteomics files — same UniProt IDs that appear as column headers.
    ~5,900 UniProt→Symbol pairs. Isoform suffixes like `-3` handled downstream
    by loaders (strip suffix before lookup).
    """
    df = _s3_read_csv(UNIPROT_HGNC_MAP_S3_KEY)
    # Columns: UniprotID, Symbol, EntrezID, Label, PTM, HPA*
    return dict(zip(df["UniprotID"], df["Symbol"]))


def load_omics_profiles() -> pd.DataFrame:
    """Load OmicsProfiles.csv — bridge from SequencingID → ModelID (needed for MSI)."""
    return _s3_read_csv(OMICS_PROFILES_S3_KEY)


def load_fusion() -> pd.DataFrame:
    """Fusion matrix indexed by ModelID; binary columns per gene involved in ANY fusion.

    Source is a long-format per-event table (~114K rows). We pivot: for each
    ModelID, collect the union of `LeftGene` + `RightGene` symbols across all
    fusion rows. Emit a binary DataFrame where entry (line, gene) = 1 if the
    line has a fusion involving that gene.
    """
    df = _s3_read_csv(FUSION_S3_KEY)
    if "IsDefaultEntryForModel" in df.columns:
        df = df[df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])]
    # Column names for gene identifiers vary slightly across DepMap releases.
    # Look for likely candidates.
    left_col = next(
        (c for c in df.columns if c.lower() in ("leftgene", "leftgenesymbol", "gene1", "leftbreakpointgene")), None
    )
    right_col = next(
        (c for c in df.columns if c.lower() in ("rightgene", "rightgenesymbol", "gene2", "rightbreakpointgene")), None
    )
    if left_col is None or right_col is None:
        # Fallback: single "FusionName" like GENE1_GENE2 or similar; not present
        # in current 26Q3 schema. Return empty frame indexed by unique ModelIDs.
        return pd.DataFrame(index=pd.Index(df["ModelID"].unique(), name="ModelID"))
    # Extract symbol from either raw string or "GENE (entrez)" style
    long_df = pd.DataFrame(
        {
            "ModelID": pd.concat([df["ModelID"], df["ModelID"]], ignore_index=True),
            "gene": pd.concat([df[left_col], df[right_col]], ignore_index=True),
        }
    )
    long_df["gene"] = long_df["gene"].map(extract_symbol)
    long_df = long_df.dropna(subset=["gene"])
    long_df["v"] = 1
    # Pivot: rows=ModelID, cols=gene, value=1 (dedup fusions)
    wide = long_df.pivot_table(index="ModelID", columns="gene", values="v", aggfunc="max", fill_value=0).astype("int8")
    return wide


def load_rppa() -> pd.DataFrame:
    """RPPA protein-abundance matrix indexed by ModelID.

    Columns are UniProt IDs; we map to HGNC symbols and prefix with 'rppa_'
    to keep the feature-class label transparent in top-features output.
    """
    df = _s3_read_csv(RPPA_S3_KEY)
    id_col = df.columns[0]  # unnamed; contains ModelID (ACH-*)
    df = df.set_index(id_col)
    df.index.name = "ModelID"
    uniprot_to_symbol = load_uniprot_hgnc_map()
    new_cols = []
    for c in df.columns:
        # Strip isoform suffix like "-3"
        base = c.split("-")[0] if "-" in c else c
        sym = uniprot_to_symbol.get(base) or uniprot_to_symbol.get(c)
        new_cols.append(f"rppa_{sym}" if sym else None)
    df.columns = new_cols
    df = df.loc[:, [c for c in df.columns if c is not None]]
    # Collapse duplicate symbol columns (mean)
    if len(df.columns) != len(set(df.columns)):
        df = df.T.groupby(level=0).mean().T
    return df.astype("float32")


def load_ms_proteomics() -> pd.DataFrame:
    """MS proteomics (Gygi) indexed by ModelID; column-prefixed `ms_`.

    ~375 cell lines × ~12K proteins. Sparse (many NaN); we don't zero-fill
    here — caller (build_gene_feature_matrix) does that with column median or
    zero depending on the class.
    """
    df = _s3_read_csv(MS_GYGI_S3_KEY)
    id_col = df.columns[0]  # unnamed; contains ModelID
    df = df.set_index(id_col)
    df.index.name = "ModelID"
    uniprot_to_symbol = load_uniprot_hgnc_map()
    new_cols = []
    for c in df.columns:
        base = c.split("-")[0] if "-" in c else c
        sym = uniprot_to_symbol.get(base) or uniprot_to_symbol.get(c)
        new_cols.append(f"ms_{sym}" if sym else None)
    df.columns = new_cols
    df = df.loc[:, [c for c in df.columns if c is not None]]
    if len(df.columns) != len(set(df.columns)):
        df = df.T.groupby(level=0).mean().T
    return df.astype("float32")


def load_paralog_dep() -> pd.DataFrame:
    """Paralog CRISPR dependency indexed by ModelID.

    The source has BOTH single-gene columns (e.g. 'A3GALT2') and gene-pair
    columns (e.g. 'A3GALT2_GLT6D1'). We keep only SINGLE-GENE columns for
    the paralog-dependency feature class; pair columns encode SL knockouts
    but as features they'd double-count downstream when we build per-target
    matrices. Feature name = `paralog_dep_{SYMBOL}`.
    """
    df = _s3_read_csv(PARALOG_DEP_S3_KEY)
    id_col = df.columns[0]
    df = df.set_index(id_col)
    df.index.name = "ModelID"
    # Drop pair columns (contain '_' between symbols); keep single-gene columns.
    # Also drop control columns (chr2_chr2, nonTarget_*).
    keep_cols = []
    for c in df.columns:
        if "_" in c:
            continue
        if c.lower().startswith(("chr", "nontarget")):
            continue
        keep_cols.append(c)
    df = df[keep_cols]
    df.columns = [f"paralog_dep_{c}" for c in df.columns]
    return df.astype("float32")


def load_molecular_signatures() -> pd.DataFrame:
    """OmicsMolecularSignatureMatrix indexed by ModelID.

    ~60 pre-computed pathway / mutational-signature columns (SBS, HRD, etc.).
    Substitutes for DepMap Daintree's ssGSEA feature class.
    """
    df = _s3_read_csv(MOLSIG_S3_KEY)
    if "IsDefaultEntryForModel" in df.columns:
        df = df[df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])]
    meta_cols = {"SequencingID", "ModelConditionID", "ModelID", "IsDefaultEntryForMC", "IsDefaultEntryForModel"}
    if "ModelID" in df.columns:
        df = df.set_index("ModelID")
    else:
        df = df.set_index(df.columns[0])
        df.index.name = "ModelID"
    df = df.drop(columns=[c for c in df.columns if c in meta_cols], errors="ignore")
    obj_cols = [c for c, dt in df.dtypes.items() if dt == object]
    if obj_cols:
        df = df.drop(columns=obj_cols)
    df.columns = [f"molsig_{c}" for c in df.columns]
    return df.astype("float32")


def load_msi_status() -> pd.DataFrame:
    """MSI status from OmicsMicrosatelliteRepeats.

    Source is transposed (rows = repeat sites × 4192 cols = SequencingIDs).
    We reduce to a single per-cell-line summary feature `msi_high_fraction` =
    fraction of repeat sites with atypical count patterns. Compact + directly
    interpretable (WRN's known biomarker).

    Requires OmicsProfiles.csv for SequencingID → ModelID bridge.
    """
    import boto3

    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=MSI_S3_KEY)
    df = pd.read_csv(BytesIO(obj["Body"].read()))
    # First 6 columns are per-repeat metadata; the rest are CDS-* (SequencingID).
    metadata_cols = ["Chromosome", "Location", "LeftFlank", "Repeat", "RightFlank"]
    seq_cols = [c for c in df.columns if c not in ({"Unnamed: 0"} | set(metadata_cols))]

    # For each SequencingID column: extract just the numeric repeat count
    # (values may be strings like "11[T]"). Length of repeat expansion is
    # first numeric token before `[`.
    def _extract_count(v):
        if isinstance(v, str):
            head = v.split("[", 1)[0]
            try:
                return int(head)
            except ValueError:
                return None
        return v

    counts_df = df[seq_cols].apply(lambda col: col.map(_extract_count))
    # For each repeat row, compute median count across all cell lines
    per_repeat_median = counts_df.median(axis=1, skipna=True)
    # For each cell line, count how many repeats differ by > 3 from the median
    # (proxy for MSI-high status; more mutation-like variability = higher MSI).
    n_repeats = len(counts_df)

    def _msi_frac(col):
        diff = (col - per_repeat_median).abs()
        return (diff > 3).sum() / max(n_repeats - diff.isna().sum(), 1)

    per_seq = counts_df.apply(_msi_frac, axis=0)
    # Bridge SequencingID → ModelID via OmicsProfiles.csv
    profiles = load_omics_profiles()
    if "SequencingID" in profiles.columns and "ModelID" in profiles.columns:
        seq_to_model = dict(zip(profiles["SequencingID"], profiles["ModelID"]))
    elif "ProfileID" in profiles.columns and "ModelID" in profiles.columns:
        # Older schema
        seq_to_model = dict(zip(profiles["ProfileID"], profiles["ModelID"]))
    else:
        seq_to_model = {}
    # Build ModelID-indexed DataFrame
    records = []
    for seq_id, val in per_seq.items():
        model_id = seq_to_model.get(seq_id, seq_id)
        records.append((model_id, float(val) if pd.notna(val) else np.nan))
    result = pd.DataFrame(records, columns=["ModelID", "msi_high_fraction"])
    result = result.dropna(subset=["ModelID"]).set_index("ModelID")
    # Deduplicate — a Model may have multiple Sequencing IDs; take mean
    result = result.groupby(level=0).mean()
    return result.astype("float32")


def load_sv_matrix() -> pd.DataFrame:
    """Structural variants per-gene binary indexed by ModelID.

    Source uses 'SYMBOL (entrez_id)' column headers with STRING values
    (`DUP`, `DEL`, `BND`, `DEL, DUP`) or NaN — DepMap encodes categorical SV
    type. We binarize: any non-NaN value → 1, indicating "at least one SV
    event of any type in this gene." Feature names get prefixed `sv_{SYMBOL}`.
    """
    df = _s3_read_csv(SV_MATRIX_S3_KEY)
    if "IsDefaultEntryForModel" in df.columns:
        df = df[df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])]
    meta_cols = {
        "SequencingID",
        "ModelConditionID",
        "ModelID",
        "IsDefaultEntryForMC",
        "IsDefaultEntryForModel",
        "Unnamed: 0",
    }
    if "ModelID" in df.columns:
        df = df.set_index("ModelID")
    else:
        df = df.set_index(df.columns[0])
        df.index.name = "ModelID"
    df = df.drop(columns=[c for c in df.columns if c in meta_cols], errors="ignore")
    # Binarize BEFORE the object-column drop. Gene columns have string SV-type
    # values or NaN; any non-NaN → 1.
    df = df.notna().astype("int8")
    df.columns = [f"sv_{extract_symbol(c) or c}" for c in df.columns]
    # Collapse duplicates (max — binary OR)
    if len(df.columns) != len(set(df.columns)):
        df = df.T.groupby(level=0).max().T
    return df.astype("int8")


def load_methylation() -> pd.DataFrame:
    """RRBS methylation β-values aggregated to per-gene mean, indexed by ModelID.

    Source has cell-line columns headed by CCLE_names (e.g. 'DMS53_LUNG') not
    ModelIDs. Requires Model.csv CCLEName column for the bridge.

    Aggregation: multiple TSS rows per gene → mean β-value across TSSs for
    each cell line. Result is per-gene continuous feature `methyl_{SYMBOL}`.
    """
    import boto3

    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=RRBS_S3_KEY)
    df = pd.read_csv(BytesIO(obj["Body"].read()), sep="\t")
    # First 7 cols are TSS metadata (TSS_id, gene, chr, fpos, tpos, strand, avg_coverage)
    meta_cols = ["TSS_id", "gene", "chr", "fpos", "tpos", "strand", "avg_coverage"]
    cell_cols = [c for c in df.columns if c not in meta_cols]
    # RRBS stores β-values as STRING (e.g. '0.00000') in the CCLE 2019 dump.
    # Coerce to float before the mean; non-parseable strings → NaN which the
    # per-gene mean then skips naturally.
    for c in cell_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Aggregate to per-gene: mean β across TSS rows sharing the gene symbol.
    by_gene = df.groupby("gene")[cell_cols].mean()
    # Transpose to rows=cell_lines, cols=gene
    by_gene_t = by_gene.T
    by_gene_t.index.name = "CCLEName"
    by_gene_t.columns.name = None
    # Bridge CCLE_name → ModelID via Model.csv
    model_df, _ = load_model_metadata()
    if "CCLEName" in model_df.columns and "ModelID" in model_df.columns:
        ccle_to_model = dict(zip(model_df["CCLEName"], model_df["ModelID"]))
    else:
        ccle_to_model = {}
    by_gene_t = by_gene_t.reset_index()
    by_gene_t["ModelID"] = by_gene_t["CCLEName"].map(ccle_to_model)
    by_gene_t = by_gene_t.dropna(subset=["ModelID"]).drop(columns=["CCLEName"])
    by_gene_t = by_gene_t.set_index("ModelID")
    by_gene_t = by_gene_t[~by_gene_t.index.duplicated(keep="first")]
    by_gene_t.columns = [f"methyl_{c}" for c in by_gene_t.columns]
    return by_gene_t.astype("float32")


def load_metabolomics() -> pd.DataFrame:
    """Metabolomics matrix indexed by ModelID; feature-prefixed `metab_`.

    Source has ModelID in the 'DepMap_ID' column (col 1); CCLE_ID is col 0
    and we ignore it. ~225 metabolites × ~927 cell lines.
    """
    df = _s3_read_csv(METABOLOMICS_S3_KEY)
    if "DepMap_ID" not in df.columns:
        raise RuntimeError("Metabolomics CSV missing DepMap_ID column")
    df = df.set_index("DepMap_ID")
    df.index.name = "ModelID"
    # Drop non-metabolite metadata cols
    drop_cols = [c for c in df.columns if c in ("CCLE_ID",)]
    df = df.drop(columns=drop_cols, errors="ignore")
    obj_cols = [c for c, dt in df.dtypes.items() if dt == object]
    if obj_cols:
        df = df.drop(columns=obj_cols)
    df.columns = [f"metab_{c}" for c in df.columns]
    return df.astype("float32")


# ---------------------------------------------------------------------------
# External-source loaders: cytoband + OncoKB + Ensembl coords
# ---------------------------------------------------------------------------


def _s3_read_gzipped_tsv(key: str, **read_csv_kwargs) -> pd.DataFrame:
    import gzip

    import boto3

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
    df = df.rename(
        columns={
            "HGNC symbol": "hgnc_symbol",
            "Chromosome/scaffold name": "chrom_name",
            "Gene start (bp)": "gene_start",
            "Gene end (bp)": "gene_end",
        }
    )
    # Only keep primary-assembly chroms
    df = df[df["chrom_name"].isin([str(i) for i in range(1, 23)] + ["X", "Y", "MT"])]
    df = df[df["hgnc_symbol"].notna() & (df["hgnc_symbol"] != "")]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Derived feature matrices: arm-level CN + OncoKB driver flags + lineage
# ---------------------------------------------------------------------------


def assign_genes_to_arms(coords_df: pd.DataFrame, cytoband_df: pd.DataFrame) -> dict:
    """Return {hgnc_symbol -> arm_label} where arm_label = 'chr12p' | 'chr12q' | etc.

    A gene's arm is determined by the FIRST cytoband its midpoint falls into.
    Cytoband name prefix ('p' or 'q') selects the arm.
    """
    # Build a per-chrom sorted list of (start, end, arm) tuples
    band_lookup: dict = {}
    for _, row in cytoband_df.iterrows():
        arm = row["chrom"] + row["name"][0]  # 'chr12p' / 'chr12q'
        band_lookup.setdefault(row["chrom"], []).append((int(row["chromStart"]), int(row["chromEnd"]), arm))
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


def compute_arm_level_cn(cn_df: pd.DataFrame, gene_to_arm: dict) -> pd.DataFrame:
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


def compute_oncokb_driver_flags(
    oncokb_df: pd.DataFrame, hotspot_df: pd.DataFrame, damaging_df: pd.DataFrame
) -> pd.DataFrame:
    """Per-cell-line {Symbol}_GoF and {Symbol}_LoF driver flags from OncoKB
    gene roles × DepMap hotspot/damaging matrices.

    Rule:
      ONCOGENE + hotspot mutation → {Symbol}_GoF = 1
      TSG + damaging mutation → {Symbol}_LoF = 1
      ONCOGENE_AND_TSG genes get both flags per rule.
    """
    onc_genes = set(oncokb_df.loc[oncokb_df["geneType"].isin(["ONCOGENE", "ONCOGENE_AND_TSG"]), "hugoSymbol"].dropna())
    tsg_genes = set(oncokb_df.loc[oncokb_df["geneType"].isin(["TSG", "ONCOGENE_AND_TSG"]), "hugoSymbol"].dropna())
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


def build_lineage_one_hot(model_df: pd.DataFrame, min_lines_per_lineage: int = 5) -> pd.DataFrame:
    """One-hot encode Model.csv.OncotreeLineage, collapsing < min_lines
    lineages (and null) into 'OTHER'.
    """
    df = model_df.set_index("ModelID")[["OncotreeLineage"]].copy()
    counts = df["OncotreeLineage"].value_counts(dropna=False)
    keep = set(counts[counts >= min_lines_per_lineage].index.dropna())
    df["bucket"] = df["OncotreeLineage"].where(df["OncotreeLineage"].isin(keep), other="OTHER").fillna("OTHER")
    oh = pd.get_dummies(df["bucket"], prefix="lineage").astype("int8")
    return oh


# ---------------------------------------------------------------------------
# Shared omics bundle (built once per pipeline run)
# ---------------------------------------------------------------------------


def _try_load(label: str, fn):
    """Wrap a loader with a try/except that returns None + logs the failure.
    v2.1 loaders touch multiple new S3 sources; if one is unreachable we want
    the pipeline to degrade gracefully rather than crash.
    """
    try:
        return fn()
    except Exception as e:
        print(
            f"[features] WARNING: {label} loader failed: {type(e).__name__}: {e}. "
            f"Feature class will be omitted for this run."
        )
        return None


def load_all_omics(min_lines_per_lineage: int = 5) -> dict:
    """Load every input matrix + build derived matrices once. Returns dict
    consumed by build_gene_feature_matrix() below.

    v2.1 adds fusion, RPPA, MS proteomics, paralog dependency, molecular
    signatures, MSI status, structural variants, methylation, metabolomics.
    Each optional-load returns None on failure and is skipped downstream.

    All DataFrames are indexed by ModelID; columns are HGNC symbols for the
    core numeric matrices and prefixed feature-labels for derived ones.
    """
    model_df, mc_df = load_model_metadata()

    # === Core v2 matrices (required) ===
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

    # === v2.1 gap-class matrices (optional; graceful degradation) ===
    fusion = _try_load("fusion", load_fusion)
    rppa = _try_load("rppa", load_rppa)
    ms_prot = _try_load("ms_proteomics", load_ms_proteomics)
    paralog_dep = _try_load("paralog_dep", load_paralog_dep)
    mol_sig = _try_load("mol_signatures", load_molecular_signatures)
    msi = _try_load("msi_status", load_msi_status)
    sv_matrix = _try_load("sv_matrix", load_sv_matrix)
    methylation = _try_load("methylation", load_methylation)
    metabolomics = _try_load("metabolomics", load_metabolomics)

    return {
        # v2 core
        "chronos": chronos,
        "expression": expression,
        "copy_number": copy_number,
        "mut_hotspot": mut_hotspot,
        "mut_damaging": mut_damaging,
        "lineage_one_hot": lineage_oh,
        "arm_level_cn": arm_cn,
        "driver_flags": driver_flags,
        "model_df": model_df,
        # v2.1 additions
        "fusion": fusion,
        "rppa": rppa,
        "ms_proteomics": ms_prot,
        "paralog_dep": paralog_dep,
        "mol_signatures": mol_sig,
        "msi_status": msi,
        "sv_matrix": sv_matrix,
        "methylation": methylation,
        "metabolomics": metabolomics,
    }


# ---------------------------------------------------------------------------
# Per-gene feature-matrix assembly (the hot loop)
# ---------------------------------------------------------------------------


def feature_class_of(feature_name: str) -> str:
    """Map a feature name to its feature-class taxonomy label.

    v2.0: own_*, expr_, cn_, arm_, driver_*_GoF/LoF, lineage_
    v2.1 additions: fusion_, rppa_, ms_, paralog_dep_, molsig_, msi_high_fraction,
                    sv_, methyl_, metab_
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
    if feature_name.startswith("fusion_"):
        return "fusion"
    if feature_name.startswith("rppa_"):
        return "rppa_protein"
    if feature_name.startswith("ms_"):
        return "ms_protein"
    if feature_name.startswith("paralog_dep_"):
        return "paralog_dep"
    if feature_name.startswith("molsig_"):
        return "mol_signature"
    if feature_name == "msi_high_fraction":
        return "msi_status"
    if feature_name.startswith("sv_"):
        return "sv_gene"
    if feature_name.startswith("methyl_"):
        return "methylation_tss"
    if feature_name.startswith("metab_"):
        return "metabolomics"
    return "other"


def build_gene_feature_matrix(gene: str, omics: dict, min_cell_lines: int = 100) -> Optional[dict]:
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

    # ================================================================
    # v2.1 gap-class blocks. Each is optional; None = feature omitted.
    # Own-target column excluded from every block where present to avoid
    # leakage into cross-signal features.
    # ================================================================

    fusion_df = omics.get("fusion")
    if fusion_df is not None and not fusion_df.empty:
        fusion_df = fusion_df.reindex(y.index).fillna(0)
        # Drop the target's own fusion column (leakage against own mutation state)
        fusion_df = fusion_df.drop(columns=[gene], errors="ignore")
        fusion_df.columns = [f"fusion_{c}" for c in fusion_df.columns]
        parts.append(fusion_df.astype(np.int8))
        feature_names.extend(fusion_df.columns.tolist())

    rppa_df = omics.get("rppa")
    if rppa_df is not None and not rppa_df.empty:
        rppa_df = rppa_df.reindex(y.index)
        rppa_df = rppa_df.drop(columns=[f"rppa_{gene}"], errors="ignore")
        rppa_df = rppa_df.fillna(0.0)
        parts.append(rppa_df.astype(np.float32))
        feature_names.extend(rppa_df.columns.tolist())

    ms_df = omics.get("ms_proteomics")
    if ms_df is not None and not ms_df.empty:
        ms_df = ms_df.reindex(y.index)
        ms_df = ms_df.drop(columns=[f"ms_{gene}"], errors="ignore")
        ms_df = ms_df.fillna(0.0)
        parts.append(ms_df.astype(np.float32))
        feature_names.extend(ms_df.columns.tolist())

    paralog_df = omics.get("paralog_dep")
    if paralog_df is not None and not paralog_df.empty:
        paralog_df = paralog_df.reindex(y.index)
        paralog_df = paralog_df.drop(columns=[f"paralog_dep_{gene}"], errors="ignore")
        paralog_df = paralog_df.fillna(0.0)
        parts.append(paralog_df.astype(np.float32))
        feature_names.extend(paralog_df.columns.tolist())

    molsig_df = omics.get("mol_signatures")
    if molsig_df is not None and not molsig_df.empty:
        molsig_df = molsig_df.reindex(y.index).fillna(0.0)
        parts.append(molsig_df.astype(np.float32))
        feature_names.extend(molsig_df.columns.tolist())

    msi_df = omics.get("msi_status")
    if msi_df is not None and not msi_df.empty:
        msi_df = msi_df.reindex(y.index).fillna(0.0)
        parts.append(msi_df.astype(np.float32))
        feature_names.extend(msi_df.columns.tolist())

    sv_df = omics.get("sv_matrix")
    if sv_df is not None and not sv_df.empty:
        sv_df = sv_df.reindex(y.index).fillna(0)
        # Drop own-target SV column (would leak with own_mut_hotspot)
        sv_df = sv_df.drop(columns=[f"sv_{gene}"], errors="ignore")
        parts.append(sv_df.astype(np.int8))
        feature_names.extend(sv_df.columns.tolist())

    methyl_df = omics.get("methylation")
    if methyl_df is not None and not methyl_df.empty:
        methyl_df = methyl_df.reindex(y.index)
        methyl_df = methyl_df.drop(columns=[f"methyl_{gene}"], errors="ignore")
        # Column-median fill (β-values in [0,1])
        col_median = methyl_df.median(axis=0, skipna=True).fillna(0.0)
        methyl_df = methyl_df.fillna(col_median)
        parts.append(methyl_df.astype(np.float32))
        feature_names.extend(methyl_df.columns.tolist())

    metab_df = omics.get("metabolomics")
    if metab_df is not None and not metab_df.empty:
        metab_df = metab_df.reindex(y.index).fillna(0.0)
        parts.append(metab_df.astype(np.float32))
        feature_names.extend(metab_df.columns.tolist())

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
