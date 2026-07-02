#!/usr/bin/env python3
"""depmap-prism-precompute — batch job: PRISM sources → gene-level activity parquet.

Reads two PRISM release lineages, computes per-compound activity stats within
each release's own cell-line panel, then aggregates to gene-level rows (one row
per HGNC-annotated gene). Writes a single frozen parquet + manifest to
`s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v3/`.

The thin `depmap_prism_activity.cli` card reads one gene row via pyarrow
predicate pushdown at compose-dashboard runtime — no CSV parsing, no
cross-release joins at read time.

v3 (2026-07-01, PRISM metric-switch to Log2AUC):
  Primary activity metric switches from single-dose median-LFC to **Log2AUC**
  (mean-centered dose-response curve integral). Motivated by KRAS-in-Bowel
  reproducing as flat under median-LFC (single dose column collapses signal)
  but showing genuine lineage-selectivity under Log2AUC (integrated
  dose-response captures partial-response biology that median-LFC masks).

  Splits activity signals into TWO metrics:
    - `median_log2auc_across_compounds`     : primary target-eval signal
    - `per_lineage_activity.median_log2auc` : per-lineage primary signal
    - `per_lineage_activity.best_responder_lfc` : min raw LFC across all
        (compound × dose × cell_line) entries — captures deep-responder tail
        that Log2AUC's 0-cap can't resolve.

  Data-source additions:
    - OncRef: reads BOTH `PRISMOncologyReferenceLumLog2AUCMatrix.csv` (primary)
      AND `PRISMOncologyReferenceLumLFCCollapsed.csv` (best-responder tail).
    - Repurposing: reads `Repurposing_Public_24Q2_LFC_COLLAPSED.csv` for
      annotation-purpose only — Repurposing has NO AUC file (single-dose screen).
      Repurposing compounds contribute to n_compounds_targeting + top_compounds
      (annotation completeness) but their activity numbers do NOT roll up to
      lineage-level or gene-level activity fields. Documented caveat.

  Bumps derived product to `depmap-prism-activity-v3/`.

Cross-release-pin substrate (v2 semantics preserved):
  - OncRef 25Q4: primary; SampleID = PRC-ID; `GeneSymbolOfTargets` gene column.
  - Repurposing 24Q2: fallback for annotation only; IDs = BRD-ID;
    `repurposing_target` gene column.
  - Cross-release dedup by uppercase drug_name; OncRef wins.

Lineage stratification (v2 semantics preserved):
  - Requires DepMap 26Q1 Model.csv for ModelID → OncotreeLineage join.
  - Per-lineage aggregation for the primary activity metric.
  - prism_lineage_selectivity vocabulary: lineage_selective / broadly_active
    / no_lineage_signal / data_unavailable.

Wall time: ~5-10 min (S3 downloads dominate; aggregation is quick).
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import click


DEPMAP_S3_BUCKET = "onc-compbio"
DEFAULT_OUTPUT_PREFIX = "data-catalog/derived/depmap-prism-activity-v3"
DERIVED_PRODUCT_ID = "depmap-prism-activity-v3"
DERIVED_PRODUCT_VERSION = "0.3.0"

# Release-pin ↔ source-prefix registry. v3: OncRef contributes both Log2AUC
# (primary metric) and LFCCollapsed (best-responder tail). Repurposing
# contributes annotation only.
RELEASES = {
    "oncref-25q4": {
        "lineage": "oncref",
        "source_prefix": "data-catalog/sources/depmap-consortium/prism-oncref-dmc-25q4",
        "compound_list_filename": "PRISMOncologyReferenceLumCompoundList.csv",
        # v3: primary activity metric — Log2AUC (mean-centered dose-response integral)
        "log2auc_filename": "PRISMOncologyReferenceLumLog2AUCMatrix.csv",
        # v3: best-responder tail signal — raw LFC across all (compound × dose × cell_line)
        "lfc_collapsed_filename": "PRISMOncologyReferenceLumLFCCollapsed.csv",
        "priority": 1,   # lower wins in cross-release dedup
    },
    "repurposing-24q2": {
        "lineage": "repurposing",
        "source_prefix": "data-catalog/sources/depmap-consortium/prism-primary-repurposing-24q2",
        "compound_list_filename": "Repurposing_Public_24Q2_Extended_Primary_Compound_List.csv",
        # Repurposing has NO AUC file (single-dose screen). We fetch LFC only for
        # annotation-completeness (Repurposing compounds appear in top_compounds)
        # but activity numbers do NOT roll up to lineage-level or gene-level
        # activity fields in v3. Documented caveat.
        "lfc_filename": "Repurposing_Public_24Q2_LFC_COLLAPSED.csv",
        "priority": 2,
    },
}

# LFC threshold: viability calls below this are "responding" (log2 fold change).
# -1.0 = ~50% viability drop; canonical cell-line-screen cutoff.
# Applied only against raw LFC data (Repurposing single-dose + OncRef LFCCollapsed).
LFC_RESPONDING_THRESHOLD = -1.0

# v3: lineage-stratification thresholds recalibrated for Log2AUC scale.
# Log2AUC compresses response into (-∞, 0]; typical active-drug values are -0.3 to -1.0.
# Recalibration data-point: BRAF Skin Log2AUC median = -0.50; KRAS Bowel Log2AUC
# median = -0.17. Setting active threshold at -0.15 captures both selective +
# broadly-cytotoxic drugs; inactive at > -0.05 (nearly-flat Log2AUC).
MIN_CELL_LINES_IN_LINEAGE = 5             # E2 parity — smaller lineages excluded from per-lineage stats
LINEAGE_ACTIVE_LOG2AUC_THRESHOLD = -0.15  # lineage's median Log2AUC below this → 'active'
LINEAGE_INACTIVE_LOG2AUC_THRESHOLD = -0.05 # lineage's median Log2AUC above this → 'inactive'
LINEAGE_SELECTIVE_MIN_ACTIVE = 1          # ≥1 lineages active AND ≥1 inactive → lineage_selective
LINEAGE_SELECTIVE_MIN_INACTIVE = 1        # mirrors E2 (which requires 1 significant enrichment)

# Compound-level activity thresholds (Log2AUC scale).
WEAKLY_ACTIVE_LOG2AUC_THRESHOLD = -0.15   # tool compound must clear this to count as weakly_active
CLINICALLY_ACTIVE_LOG2AUC_THRESHOLD = -0.10  # phase_1+ compound needs Log2AUC below this
                                             # for the "clinically_active with signal" call

# Vocabulary buckets for prism_activity_class. See card spec for authoritative copy.
CLASS_CLINICALLY_ACTIVE = "clinically_active"
CLASS_TOOL_COMPOUND_ONLY = "tool_compound_only"
CLASS_WEAKLY_ACTIVE = "weakly_active"
CLASS_NO_COMPOUNDS_FOUND = "no_compounds_found"
CLASS_DATA_UNAVAILABLE = "data_unavailable"

# v2 vocabulary buckets for prism_lineage_selectivity.
LINEAGE_SEL_SELECTIVE = "lineage_selective"
LINEAGE_SEL_BROADLY_ACTIVE = "broadly_active"
LINEAGE_SEL_NO_SIGNAL = "no_lineage_signal"
LINEAGE_SEL_DATA_UNAVAILABLE = "data_unavailable"

# Ordered phase ladder (max phase across a gene's compounds → highest_clinical_phase).
CLINICAL_PHASES = ["tool", "preclinical", "phase_1", "phase_2", "phase_3", "approved"]


def _log(msg: str) -> None:
    click.echo(msg, err=True)


def _sha256_bytes(b: bytes, chunk_size: int = 8_388_608) -> str:
    h = hashlib.sha256()
    view = memoryview(b)
    for i in range(0, len(view), chunk_size):
        h.update(view[i:i + chunk_size])
    return h.hexdigest()


def _fetch_source(s3, source_key: str) -> tuple[bytes, str, int]:
    _log(f"  Fetching s3://{DEPMAP_S3_BUCKET}/{source_key}")
    obj = s3.get_object(Bucket=DEPMAP_S3_BUCKET, Key=source_key)
    body = obj["Body"].read()
    sha256 = _sha256_bytes(body)
    _log(f"    {len(body) / 1e6:.1f} MB, sha256={sha256[:12]}...")
    return body, sha256, len(body)


# ---------------------------------------------------------------------------
# Compound-list loaders (per-lineage schema normalization)
# ---------------------------------------------------------------------------

_GENE_SPLIT_RE = re.compile(r"[,;\s]+")


def _split_gene_list(cell) -> list[str]:
    """Split a comma/space-separated gene-symbol string. Returns unique upper-case
    HGNC-looking symbols; empty list on NaN/empty/'NA'.
    """
    if cell is None:
        return []
    s = str(cell).strip()
    if not s or s.upper() in {"NA", "NONE", "NAN", ""}:
        return []
    parts = [p.strip().upper() for p in _GENE_SPLIT_RE.split(s) if p.strip()]
    # HGNC symbols are typically letters/digits/hyphens; drop obvious junk.
    return sorted({p for p in parts if re.match(r"^[A-Z0-9][A-Z0-9\-\.]*$", p)})


def load_oncref_compound_list(body: bytes) -> "pandas.DataFrame":
    """Normalize OncRef 25Q4 compound list to unified compound-row schema.

    Unified columns:
      compound_id   — SampleID (PRC-XXX-XXX-XX), unique per compound-dose row
      drug_name     — CompoundName
      gene_targets  — list<str> of HGNC symbols (from GeneSymbolOfTargets)
      moa           — TargetOrMechanism free-text
      prioritized   — bool (Prioritized column)
      source_release — 'oncref-25q4'
    """
    import pandas as pd
    df = pd.read_csv(BytesIO(body))
    df = df.copy()
    df["compound_id"] = df["SampleID"].astype(str)
    df["drug_name"] = df["CompoundName"].astype(str).str.strip()
    df["gene_targets"] = df["GeneSymbolOfTargets"].apply(_split_gene_list)
    df["moa"] = df.get("TargetOrMechanism", "").astype(str).fillna("").str.strip()
    df["prioritized"] = df.get("Prioritized", False).astype(str).str.upper().isin({"TRUE", "T", "1", "YES"})
    df["source_release"] = "oncref-25q4"
    return df[["compound_id", "drug_name", "gene_targets", "moa", "prioritized", "source_release"]]


def load_repurposing_compound_list(body: bytes) -> "pandas.DataFrame":
    """Normalize Repurposing 24Q2 compound list to unified compound-row schema.

    Unified columns:
      compound_id   — parsed BRD-ID stem (e.g. 'BRD-A04843135' from 'BRD:BRD-A04843135-001-09-9')
      drug_name     — Drug.Name
      gene_targets  — list<str> from repurposing_target
      moa           — MOA free-text
      prioritized   — False (Repurposing library has no priority flag)
      source_release — 'repurposing-24q2'
    """
    import pandas as pd
    df = pd.read_csv(BytesIO(body))
    df = df.copy()
    # Parse 'BRD:BRD-A04843135-001-09-9' → 'BRD-A04843135' stem (drops well/plate/version)
    def _parse_brd(x):
        s = str(x)
        if s.startswith("BRD:"):
            s = s[4:]
        # keep only the first two hyphen-segments to strip well/plate/version suffixes
        parts = s.split("-")
        if len(parts) >= 2:
            return "-".join(parts[:2])
        return s
    df["compound_id"] = df["IDs"].apply(_parse_brd)
    df["drug_name"] = df["Drug.Name"].astype(str).str.strip()
    df["gene_targets"] = df["repurposing_target"].apply(_split_gene_list)
    df["moa"] = df["MOA"].astype(str).fillna("").str.strip()
    df["prioritized"] = False
    df["source_release"] = "repurposing-24q2"
    return df[["compound_id", "drug_name", "gene_targets", "moa", "prioritized", "source_release"]]


# ---------------------------------------------------------------------------
# Activity loaders — v3: Log2AUC primary + LFCCollapsed responder-tail
# ---------------------------------------------------------------------------


def load_oncref_log2auc(body: bytes) -> "pandas.DataFrame":
    """Melt the OncRef 25Q4 Log2AUC wide matrix to (ModelID, compound_id, log2auc).

    Log2AUC is the log-transformed, mean-centered area-under-dose-response-curve
    per (compound, cell_line). Columns are pure SampleID (PRC-IDs); first column
    is the unnamed row-index containing ModelIDs. Non-responders sit near
    Log2AUC = 0; active drugs push negative (typical clinical hits: -0.5 to -3).

    Primary v3 activity metric. DepMap portal-default sensitivity signal.
    """
    import pandas as pd
    df = pd.read_csv(BytesIO(body))
    id_col = df.columns[0]
    df = df.rename(columns={id_col: "model_id"})
    long = df.melt(id_vars=["model_id"], var_name="compound_id", value_name="log2auc")
    long = long.dropna(subset=["log2auc"])
    long["source_release"] = "oncref-25q4"
    return long[["model_id", "compound_id", "log2auc", "source_release"]]


def load_oncref_lfccollapsed(body: bytes, compound_ids_wanted: set[str]) -> "pandas.DataFrame":
    """Parse OncRef 25Q4 LFCCollapsed (long-format) → per-(compound_id × cell_line)
    min LFC across doses. This is the source for `best_responder_lfc` — the
    deepest-responder tail statistic that Log2AUC's 0-cap can't preserve.

    Filters to `compound_ids_wanted` (from OncRef compound-list) at parse time
    to keep memory tractable — the raw file is ~537 MB with 8 doses × ~900 lines
    × ~444 compounds ≈ 3.2M rows.
    """
    import pandas as pd
    parts = []
    chunk_iter = pd.read_csv(BytesIO(body), chunksize=500_000,
                              usecols=["SampleID", "depmap_id", "LFC"])
    for chunk in chunk_iter:
        chunk = chunk[chunk["SampleID"].isin(compound_ids_wanted)]
        if len(chunk):
            parts.append(chunk.rename(columns={"SampleID": "compound_id",
                                                "depmap_id": "model_id"}))
    if not parts:
        return pd.DataFrame(columns=["model_id", "compound_id", "min_lfc", "source_release"])
    long = pd.concat(parts, ignore_index=True)
    # min LFC per (compound_id, model_id) across the 8 doses — deepest single-line kill
    agg = long.groupby(["model_id", "compound_id"], as_index=False).agg(min_lfc=("LFC", "min"))
    agg["source_release"] = "oncref-25q4"
    return agg


def load_repurposing_lfc(body: bytes, compound_ids_wanted: set[str]) -> "pandas.DataFrame":
    """Parse the Repurposing 24Q2 long-format LFC and aggregate per (ModelID × compound_id).

    Filters to compound_ids_wanted at parse time (chunked read) to keep memory
    tractable — the raw file is ~150 MB. Extracts ModelID from the compound
    row_id ('ACH-000001::P946.2::PR500B::REP300' → 'ACH-000001').
    Drops rows with '- QC Failure' in the broad_id.
    """
    import pandas as pd
    parts = []
    chunk_iter = pd.read_csv(BytesIO(body), chunksize=500_000,
                              usecols=["row_id", "broad_id", "dose", "LFC"])
    for chunk in chunk_iter:
        # QC filter
        chunk = chunk[~chunk["broad_id"].astype(str).str.contains(" - QC Failure", regex=False)]
        # Parse ModelID from row_id
        chunk["model_id"] = chunk["row_id"].astype(str).str.split("::").str[0]
        # Parse BRD stem from broad_id (same convention as compound-list)
        chunk["compound_id"] = chunk["broad_id"].astype(str).apply(
            lambda s: "-".join(s.split("-")[:2]) if len(s.split("-")) >= 2 else s
        )
        chunk = chunk[chunk["compound_id"].isin(compound_ids_wanted)]
        if len(chunk):
            parts.append(chunk[["model_id", "compound_id", "dose", "LFC"]])
    if not parts:
        return pd.DataFrame(columns=["model_id", "compound_id", "median_lfc", "source_release"])
    long = pd.concat(parts, ignore_index=True)
    agg = long.groupby(["model_id", "compound_id"], as_index=False).agg(median_lfc=("LFC", "median"))
    agg["source_release"] = "repurposing-24q2"
    return agg


# ---------------------------------------------------------------------------
# Cross-release compound merge + gene aggregate
# ---------------------------------------------------------------------------

def merge_compound_universes(dfs: list["pandas.DataFrame"]) -> "pandas.DataFrame":
    """Concatenate per-release compound rows and dedup by (drug_name, gene_targets-signature).

    Cross-release dedup is by normalized drug_name: if the same drug appears in
    OncRef (priority 1) and Repurposing (priority 2), keep the OncRef row.
    We use drug_name (not compound_id) because BRD-IDs and PRC-IDs are different
    ID schemes; drug_name is the human-readable key that carries across.

    Compounds NOT deduplicated remain — a compound present only in Repurposing
    stays under its BRD stem; a compound only in OncRef stays under its PRC stem.
    """
    import pandas as pd
    all_cmp = pd.concat(dfs, ignore_index=True)
    all_cmp["_drug_key"] = all_cmp["drug_name"].str.upper().str.strip()
    # Sort by release priority so OncRef rows come first; drop_duplicates keeps first
    priority = {r: RELEASES[r]["priority"] for r in RELEASES}
    all_cmp["_prio"] = all_cmp["source_release"].map(priority)
    all_cmp = all_cmp.sort_values(["_drug_key", "_prio"])
    deduped = all_cmp.drop_duplicates(subset=["_drug_key"], keep="first").copy()
    deduped = deduped.drop(columns=["_drug_key", "_prio"])
    return deduped.reset_index(drop=True)


def load_model_to_lineage(model_csv_body: bytes) -> dict[str, str]:
    """Parse DepMap Model.csv → {ModelID: OncotreeLineage} map.

    Only reads two columns; the map is used to join PRISM (ModelID, compound_id, LFC)
    rows to their tumor-lineage-of-origin for v2's per-lineage aggregation.
    Missing/empty lineages are dropped from the map so downstream aggregation
    doesn't produce a '' or NaN lineage bucket.
    """
    import pandas as pd
    df = pd.read_csv(BytesIO(model_csv_body), usecols=["ModelID", "OncotreeLineage"])
    df = df.dropna(subset=["OncotreeLineage"])
    df = df[df["OncotreeLineage"].astype(str).str.strip() != ""]
    return dict(zip(df["ModelID"].astype(str), df["OncotreeLineage"].astype(str)))


def build_gene_aggregate(
    merged_compounds: "pandas.DataFrame",
    oncref_log2auc: Optional["pandas.DataFrame"] = None,
    oncref_lfccollapsed_min: Optional["pandas.DataFrame"] = None,
    repurposing_lfc: Optional["pandas.DataFrame"] = None,
    model_to_lineage: Optional[dict[str, str]] = None,
    min_cell_lines_in_lineage: int = MIN_CELL_LINES_IN_LINEAGE,
) -> "pandas.DataFrame":
    """v3 gene-aggregate builder.

    Primary activity metric is Log2AUC (from OncRef 25Q4 Log2AUCMatrix); the
    responder-tail signal is min raw LFC (from OncRef LFCCollapsed). Repurposing
    24Q2 contributes annotation only — Repurposing compounds appear in
    top_compounds + n_compounds_targeting but do NOT contribute to Log2AUC-based
    activity rollups (Repurposing has no AUC file — single-dose screen).

    Inputs:
      merged_compounds: unified compound-list rows (from merge_compound_universes).
      oncref_log2auc: DataFrame from load_oncref_log2auc — (model_id, compound_id,
        log2auc) rows. Optional; if None, primary metric fields are None.
      oncref_lfccollapsed_min: DataFrame from load_oncref_lfccollapsed — (model_id,
        compound_id, min_lfc) rows (per-line min across doses). Optional; if None,
        best_responder_lfc fields are None.
      repurposing_lfc: DataFrame from load_repurposing_lfc — (model_id, compound_id,
        median_lfc) rows. Optional; if None, Repurposing compounds still appear in
        top_compounds using single-dose LFC = None (annotation-only).
      model_to_lineage: {ModelID: OncotreeLineage}. Optional; if None,
        per_lineage_activity is empty.

    Returns a DataFrame with one row per HGNC gene that has ≥1 annotated compound.
    """
    import pandas as pd

    # ---------- Gene ↔ compound edges ----------
    exploded = merged_compounds.explode("gene_targets")
    exploded = exploded[exploded["gene_targets"].notna() & (exploded["gene_targets"] != "")]
    exploded = exploded.rename(columns={"gene_targets": "gene_symbol"})

    # ---------- Polyselective annotation ----------
    def _n_targets(x):
        return len(x) if isinstance(x, list) else 0
    merged_compounds = merged_compounds.copy()
    merged_compounds["n_annotated_targets"] = merged_compounds["gene_targets"].apply(_n_targets)
    merged_compounds["polyselective"] = merged_compounds["n_annotated_targets"] > 1
    poly_map = dict(zip(merged_compounds["compound_id"], merged_compounds["polyselective"]))
    ntgt_map = dict(zip(merged_compounds["compound_id"], merged_compounds["n_annotated_targets"]))
    exploded["polyselective"] = exploded["compound_id"].map(poly_map).fillna(False)
    exploded["n_annotated_targets"] = exploded["compound_id"].map(ntgt_map).fillna(0).astype(int)

    # ---------- Per-compound primary activity (Log2AUC) ----------
    # OncRef compounds get real Log2AUC; Repurposing compounds get None (no AUC data).
    per_compound_log2auc = {}   # {compound_id: {median_log2auc, n_lines_screened, ...}}
    if oncref_log2auc is not None and len(oncref_log2auc):
        stats = oncref_log2auc.groupby("compound_id").agg(
            median_log2auc=("log2auc", "median"),
            n_lines_screened=("log2auc", "size"),
        ).reset_index()
        for _, row in stats.iterrows():
            per_compound_log2auc[row["compound_id"]] = {
                "median_log2auc": float(row["median_log2auc"]),
                "n_lines_screened": int(row["n_lines_screened"]),
                "source_release": "oncref-25q4",
            }

    # ---------- Per-compound responder tail (min LFC from LFCCollapsed) ----------
    per_compound_min_lfc = {}   # {compound_id: min_lfc across all (dose × line) entries}
    if oncref_lfccollapsed_min is not None and len(oncref_lfccollapsed_min):
        # Already aggregated per (model_id, compound_id) as min-across-doses; take
        # min across model_ids for the deepest responder.
        stats = oncref_lfccollapsed_min.groupby("compound_id").agg(
            best_responder_lfc=("min_lfc", "min"),
        ).reset_index()
        for _, row in stats.iterrows():
            per_compound_min_lfc[row["compound_id"]] = float(row["best_responder_lfc"])

    # ---------- Per-compound single-dose LFC (Repurposing, annotation-completeness) ----------
    per_compound_single_dose_lfc = {}   # {compound_id: median_lfc across screened lines}
    if repurposing_lfc is not None and len(repurposing_lfc):
        stats = repurposing_lfc.groupby("compound_id").agg(
            single_dose_lfc=("median_lfc", "median"),
            n_lines_screened=("median_lfc", "size"),
        ).reset_index()
        for _, row in stats.iterrows():
            per_compound_single_dose_lfc[row["compound_id"]] = {
                "single_dose_lfc": float(row["single_dose_lfc"]),
                "n_lines_screened": int(row["n_lines_screened"]),
                "source_release": "repurposing-24q2",
            }

    # ---------- Per-compound × per-lineage Log2AUC (OncRef only) ----------
    per_compound_lineage_log2auc = {}   # {(compound_id, lineage): {median_log2auc, n_lines_screened, ...}}
    if model_to_lineage and oncref_log2auc is not None and len(oncref_log2auc):
        df = oncref_log2auc.copy()
        df["lineage"] = df["model_id"].map(model_to_lineage)
        df = df.dropna(subset=["lineage"])
        if not df.empty:
            grouped = df.groupby(["compound_id", "lineage"]).agg(
                lin_median_log2auc=("log2auc", "median"),
                lin_n_lines_screened=("log2auc", "size"),
            ).reset_index()
            for _, row in grouped.iterrows():
                per_compound_lineage_log2auc[(row["compound_id"], row["lineage"])] = {
                    "median_log2auc": float(row["lin_median_log2auc"]),
                    "n_lines_screened": int(row["lin_n_lines_screened"]),
                    "source_release": "oncref-25q4",
                }

    # ---------- Per-compound × per-lineage min LFC (OncRef LFCCollapsed) ----------
    # Used for per-lineage best_responder_lfc.
    per_compound_lineage_min_lfc = {}   # {(compound_id, lineage): min_lfc}
    if model_to_lineage and oncref_lfccollapsed_min is not None and len(oncref_lfccollapsed_min):
        df = oncref_lfccollapsed_min.copy()
        df["lineage"] = df["model_id"].map(model_to_lineage)
        df = df.dropna(subset=["lineage"])
        if not df.empty:
            grouped = df.groupby(["compound_id", "lineage"]).agg(
                lin_min_lfc=("min_lfc", "min"),
            ).reset_index()
            for _, row in grouped.iterrows():
                per_compound_lineage_min_lfc[(row["compound_id"], row["lineage"])] = float(row["lin_min_lfc"])

    # ---------- Aggregate per gene ----------
    rows = []
    for gene, group in exploded.groupby("gene_symbol"):
        # Build top_compounds — rank by (prioritized DESC, median_log2auc ASC, source_release ASC).
        # OncRef compounds have log2auc; Repurposing compounds have single_dose_lfc (fallback ranking key).
        compound_rows = []
        for _, r in group.iterrows():
            cid = r["compound_id"]
            log2auc_stats = per_compound_log2auc.get(cid)
            sd_lfc_stats = per_compound_single_dose_lfc.get(cid)
            best_lfc = per_compound_min_lfc.get(cid)
            compound_rows.append({
                "compound_id": cid,
                "drug_name": r["drug_name"],
                "moa": r["moa"],
                "median_log2auc": log2auc_stats["median_log2auc"] if log2auc_stats else None,
                "best_responder_lfc": best_lfc,
                "single_dose_lfc": sd_lfc_stats["single_dose_lfc"] if sd_lfc_stats else None,
                "n_lines_screened": (log2auc_stats or sd_lfc_stats or {}).get("n_lines_screened"),
                "polyselective": bool(r["polyselective"]),
                "n_annotated_targets": int(r["n_annotated_targets"]),
                "source_release": r["source_release"],
                "prioritized": bool(r["prioritized"]),
                "metric_source": "log2auc" if log2auc_stats else ("single_dose_lfc" if sd_lfc_stats else "annotation_only"),
            })

        # Ranking key: sort primary by prioritized, then by whichever activity metric applies.
        # Compounds with Log2AUC data rank before compounds with only single_dose_lfc rank
        # before annotation-only compounds.
        def _rank_key(c):
            act = c["median_log2auc"] if c["median_log2auc"] is not None else (
                c["single_dose_lfc"] if c["single_dose_lfc"] is not None else 0.0
            )
            metric_priority = {"log2auc": 0, "single_dose_lfc": 1, "annotation_only": 2}[c["metric_source"]]
            return (not c["prioritized"], metric_priority, act)
        compound_rows.sort(key=_rank_key)
        top_compounds = compound_rows[:5]

        # Gene-level median Log2AUC — computed ONLY over OncRef compounds with real Log2AUC data
        oncref_log2aucs = [c["median_log2auc"] for c in compound_rows if c["median_log2auc"] is not None]
        median_log2auc_across_compounds = (
            float(pd.Series(oncref_log2aucs).median()) if oncref_log2aucs else None
        )

        n_compounds_targeting = len(compound_rows)
        # highest_clinical_phase — unchanged from v2 semantics (Prioritized/OncRef presence)
        any_prio_oncref = any(c["prioritized"] and c["source_release"] == "oncref-25q4" for c in compound_rows)
        any_oncref = any(c["source_release"] == "oncref-25q4" for c in compound_rows)
        if any_prio_oncref:
            highest_clinical_phase = "phase_1_plus"
        elif any_oncref:
            highest_clinical_phase = "preclinical"
        else:
            highest_clinical_phase = "tool"

        # Class assignment
        prism_activity_class = classify_prism_activity(
            n_compounds_targeting=n_compounds_targeting,
            highest_clinical_phase=highest_clinical_phase,
            median_log2auc_across_compounds=median_log2auc_across_compounds,
        )

        # v3 per-lineage aggregation — OncRef Log2AUC only
        per_lineage_activity, prism_lineage_selectivity = _build_per_lineage_activity(
            gene_compounds=group,
            per_compound_lineage_log2auc=per_compound_lineage_log2auc,
            per_compound_lineage_min_lfc=per_compound_lineage_min_lfc,
            min_cell_lines_in_lineage=min_cell_lines_in_lineage,
            model_to_lineage=model_to_lineage,
        )

        rows.append({
            "gene_symbol": gene,
            "n_compounds_targeting": int(n_compounds_targeting),
            "highest_clinical_phase": highest_clinical_phase,
            "median_log2auc_across_compounds": median_log2auc_across_compounds,
            "top_compounds": top_compounds,
            "prism_activity_class": prism_activity_class,
            "per_lineage_activity": per_lineage_activity,
            "prism_lineage_selectivity": prism_lineage_selectivity,
        })

    return pd.DataFrame(rows)


def _build_per_lineage_activity(
    gene_compounds: "pandas.DataFrame",
    per_compound_lineage_log2auc: dict,
    per_compound_lineage_min_lfc: dict,
    min_cell_lines_in_lineage: int,
    model_to_lineage: Optional[dict[str, str]],
) -> tuple[list[dict], str]:
    """Roll up per-(compound, lineage) Log2AUC + LFC stats to per-lineage entries.

    For each lineage present in this gene's compound × lineage stats:
      - median_log2auc: median of compound-level median Log2AUC in that lineage
                        (primary lineage-selectivity signal)
      - best_responder_lfc: min LFC across compounds in that lineage
                           (deepest-responder tail statistic)
      - top_compound_in_lineage: name of the most-active compound (Log2AUC-ranked)
      - n_compounds_evaluated: number of compounds with Log2AUC data in this lineage

    Returns (per_lineage_activity_list, prism_lineage_selectivity_class).
    """
    if not model_to_lineage or not per_compound_lineage_log2auc:
        return [], LINEAGE_SEL_DATA_UNAVAILABLE

    # Collect all (lineage → list of compound-level stats) for this gene's compounds
    lineage_bucket: dict[str, list[dict]] = {}
    compound_ids = set(gene_compounds["compound_id"].tolist())
    for (cid, lineage), stats in per_compound_lineage_log2auc.items():
        if cid not in compound_ids:
            continue
        entry = {"compound_id": cid, **stats}
        # Attach lineage-level min-LFC if available for this (compound, lineage)
        entry["min_lfc"] = per_compound_lineage_min_lfc.get((cid, lineage))
        lineage_bucket.setdefault(lineage, []).append(entry)

    if not lineage_bucket:
        return [], LINEAGE_SEL_DATA_UNAVAILABLE

    # Compound metadata for top_compound_in_lineage
    cmpmeta = {
        r["compound_id"]: {"drug_name": r["drug_name"], "prioritized": bool(r["prioritized"])}
        for _, r in gene_compounds.iterrows()
    }

    per_lineage_activity = []
    for lineage, compound_stats in sorted(lineage_bucket.items()):
        n_lines_screened = max(s["n_lines_screened"] for s in compound_stats)
        if n_lines_screened < min_cell_lines_in_lineage:
            continue
        # median-of-per-compound Log2AUC
        import statistics as _stats
        median_log2auc = float(_stats.median([s["median_log2auc"] for s in compound_stats]))
        # best_responder_lfc across compounds in this lineage — falls back to Log2AUC-derived
        # value if no LFC data is present (rare — happens when LFCCollapsed missed a compound).
        lfc_values = [s["min_lfc"] for s in compound_stats if s["min_lfc"] is not None]
        best_responder_lfc = float(min(lfc_values)) if lfc_values else None
        # top compound = min Log2AUC, prioritized-preferred as tiebreak
        ranked = sorted(
            compound_stats,
            key=lambda s: (not cmpmeta.get(s["compound_id"], {}).get("prioritized", False), s["median_log2auc"]),
        )
        top_compound_id = ranked[0]["compound_id"]
        top_compound_name = cmpmeta.get(top_compound_id, {}).get("drug_name") or top_compound_id
        per_lineage_activity.append({
            "lineage": lineage,
            "n_lines_screened": int(n_lines_screened),
            "median_log2auc": median_log2auc,
            "best_responder_lfc": best_responder_lfc,
            "top_compound_in_lineage": top_compound_name,
            "n_compounds_evaluated": len(compound_stats),
        })

    per_lineage_activity.sort(key=lambda e: e["median_log2auc"])

    prism_lineage_selectivity = classify_prism_lineage_selectivity(per_lineage_activity)
    return per_lineage_activity, prism_lineage_selectivity


def classify_prism_lineage_selectivity(per_lineage_activity: list[dict]) -> str:
    """v3: classify gene-level lineage selectivity of PRISM activity using Log2AUC.

    Vocabulary:
      - lineage_selective   → ≥1 lineages active (median_log2auc < LINEAGE_ACTIVE_LOG2AUC_THRESHOLD)
                              AND ≥1 lineages inactive (median_log2auc > LINEAGE_INACTIVE_LOG2AUC_THRESHOLD)
      - broadly_active      → majority of lineages active; no clear inactive contrast
      - no_lineage_signal   → too few active lineages
      - data_unavailable    → no evaluable lineages
    """
    if not per_lineage_activity:
        return LINEAGE_SEL_DATA_UNAVAILABLE
    n_active = sum(1 for e in per_lineage_activity
                   if e["median_log2auc"] is not None and e["median_log2auc"] < LINEAGE_ACTIVE_LOG2AUC_THRESHOLD)
    n_inactive = sum(1 for e in per_lineage_activity
                     if e["median_log2auc"] is not None and e["median_log2auc"] > LINEAGE_INACTIVE_LOG2AUC_THRESHOLD)
    if n_active >= LINEAGE_SELECTIVE_MIN_ACTIVE and n_inactive >= LINEAGE_SELECTIVE_MIN_INACTIVE:
        return LINEAGE_SEL_SELECTIVE
    if n_active >= max(3, len(per_lineage_activity) // 2):
        return LINEAGE_SEL_BROADLY_ACTIVE
    return LINEAGE_SEL_NO_SIGNAL


def classify_prism_activity(
    n_compounds_targeting: int,
    highest_clinical_phase: str,
    median_log2auc_across_compounds: Optional[float],
) -> str:
    """v3 vocabulary classifier — mirrors E5's _classify_dependency pattern.

    Priority order (first-match wins):
      1. No compounds → no_compounds_found (first-in-class opportunity, NOT killer)
      2. Any phase_1+ compound AND median Log2AUC < CLINICALLY_ACTIVE_LOG2AUC_THRESHOLD
         → clinically_active
      3. Any phase_1+ compound (regardless of Log2AUC signal) → clinically_active
         (clinical anchor exists even if pan-cancer signal is thin)
      4. tool / preclinical only AND median Log2AUC < WEAKLY_ACTIVE_LOG2AUC_THRESHOLD
         → weakly_active
      5. tool / preclinical only → tool_compound_only
    """
    if n_compounds_targeting == 0:
        return CLASS_NO_COMPOUNDS_FOUND
    has_activity = median_log2auc_across_compounds is not None
    has_clinical = highest_clinical_phase in ("phase_1_plus", "approved")
    if has_clinical and has_activity and median_log2auc_across_compounds < CLINICALLY_ACTIVE_LOG2AUC_THRESHOLD:
        return CLASS_CLINICALLY_ACTIVE
    if has_clinical:
        return CLASS_CLINICALLY_ACTIVE
    if has_activity and median_log2auc_across_compounds < WEAKLY_ACTIVE_LOG2AUC_THRESHOLD:
        return CLASS_WEAKLY_ACTIVE
    return CLASS_TOOL_COMPOUND_ONLY


# ---------------------------------------------------------------------------
# Parquet write
# ---------------------------------------------------------------------------

def write_gene_aggregate_parquet(df: "pandas.DataFrame", local_path: Path) -> int:
    """Write the per-gene aggregate DataFrame to parquet with an explicit schema.

    Uses a struct-list schema for `top_compounds` + `per_lineage_activity` (mirrors
    E5's `top_features_rf_shap` pattern) so pyarrow read_table + predicate pushdown
    on `gene_symbol` returns a fully-typed row without JSON parsing.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    top_struct = pa.struct([
        pa.field("compound_id", pa.string()),
        pa.field("drug_name", pa.string()),
        pa.field("moa", pa.string()),
        pa.field("median_log2auc", pa.float32()),         # v3: primary activity metric
        pa.field("best_responder_lfc", pa.float32()),      # v3: deepest single-line LFC
        pa.field("single_dose_lfc", pa.float32()),         # v3: Repurposing-only fallback
        pa.field("n_lines_screened", pa.int32()),
        pa.field("polyselective", pa.bool_()),
        pa.field("n_annotated_targets", pa.int32()),
        pa.field("source_release", pa.string()),
        pa.field("prioritized", pa.bool_()),
        pa.field("metric_source", pa.string()),            # v3: 'log2auc' | 'single_dose_lfc' | 'annotation_only'
    ])
    lineage_struct = pa.struct([
        pa.field("lineage", pa.string()),
        pa.field("n_lines_screened", pa.int32()),
        pa.field("median_log2auc", pa.float32()),
        pa.field("best_responder_lfc", pa.float32()),
        pa.field("top_compound_in_lineage", pa.string()),
        pa.field("n_compounds_evaluated", pa.int32()),
    ])
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("n_compounds_targeting", pa.int32()),
        pa.field("highest_clinical_phase", pa.string()),
        pa.field("median_log2auc_across_compounds", pa.float32()),
        pa.field("top_compounds", pa.list_(top_struct)),
        pa.field("prism_activity_class", pa.string()),
        pa.field("per_lineage_activity", pa.list_(lineage_struct)),
        pa.field("prism_lineage_selectivity", pa.string()),
    ])
    df = df.copy()
    df["median_log2auc_across_compounds"] = df["median_log2auc_across_compounds"].astype(object)
    if "per_lineage_activity" not in df.columns:
        df["per_lineage_activity"] = [[] for _ in range(len(df))]
    if "prism_lineage_selectivity" not in df.columns:
        df["prism_lineage_selectivity"] = LINEAGE_SEL_DATA_UNAVAILABLE
    table = pa.Table.from_pydict(
        {c.name: df[c.name].tolist() for c in schema},
        schema=schema,
    )
    local_path.parent.mkdir(parents=True, exist_ok=True)
    # Small row groups: this parquet is one-row-per-gene (~20k rows), sort-by-gene for
    # predicate-pushdown skipping.
    table = table.sort_by("gene_symbol")
    pq.write_table(table, str(local_path), compression="snappy", row_group_size=256)
    return local_path.stat().st_size


def _upload_to_s3(s3, local_path: Path, s3_key: str) -> None:
    _log(f"  Uploading {local_path.name} ({local_path.stat().st_size / 1e6:.1f} MB) -> s3://{DEPMAP_S3_BUCKET}/{s3_key}")
    with open(local_path, "rb") as f:
        s3.upload_fileobj(f, DEPMAP_S3_BUCKET, s3_key)


def _write_manifest(
    entries: list[dict], gene_agg_size: int, gene_agg_n_rows: int,
    local_dir: Path, output_prefix: str, s3, upload: bool = True,
) -> Path:
    import yaml
    manifest = {
        "derived_product_id": DERIVED_PRODUCT_ID,
        "derived_product_version": DERIVED_PRODUCT_VERSION,
        "framework_version": "v2",
        "generated_by": "methods.depmap_prism_precompute.cli",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_s3_prefix": f"s3://{DEPMAP_S3_BUCKET}/{output_prefix.rstrip('/')}/",
        "compression": "snappy",
        "release_pins": list(RELEASES.keys()),
        "cross_release_convention": (
            "Per-compound activity computed within its OWN release cell-line panel; never mixed. "
            "Cross-release dedup by uppercase drug_name; OncRef 25Q4 rows preferred over Repurposing 24Q2 "
            "when the same drug appears in both."
        ),
        "primary_activity_metric": "log2auc",
        "responder_tail_metric": "raw_lfc_min_across_doses",
        "thresholds": {
            "lfc_responding_threshold": LFC_RESPONDING_THRESHOLD,
            "min_cell_lines_in_lineage": MIN_CELL_LINES_IN_LINEAGE,
            "lineage_active_log2auc": LINEAGE_ACTIVE_LOG2AUC_THRESHOLD,
            "lineage_inactive_log2auc": LINEAGE_INACTIVE_LOG2AUC_THRESHOLD,
            "lineage_selective_min_active": LINEAGE_SELECTIVE_MIN_ACTIVE,
            "lineage_selective_min_inactive": LINEAGE_SELECTIVE_MIN_INACTIVE,
            "weakly_active_log2auc": WEAKLY_ACTIVE_LOG2AUC_THRESHOLD,
            "clinically_active_log2auc": CLINICALLY_ACTIVE_LOG2AUC_THRESHOLD,
        },
        "vocabulary": {
            "prism_activity_class": [
                CLASS_CLINICALLY_ACTIVE, CLASS_TOOL_COMPOUND_ONLY,
                CLASS_WEAKLY_ACTIVE, CLASS_NO_COMPOUNDS_FOUND,
                CLASS_DATA_UNAVAILABLE,
            ],
            "prism_lineage_selectivity": [
                LINEAGE_SEL_SELECTIVE, LINEAGE_SEL_BROADLY_ACTIVE,
                LINEAGE_SEL_NO_SIGNAL, LINEAGE_SEL_DATA_UNAVAILABLE,
            ],
            "highest_clinical_phase": ["tool", "preclinical", "phase_1_plus", "approved"],
            "metric_source": ["log2auc", "single_dose_lfc", "annotation_only"],
        },
        "notes": (
            "v3 primary activity metric: OncRef 25Q4 Log2AUC (mean-centered "
            "dose-response integral). best_responder_lfc is min raw LFC across "
            "all (compound × dose × cell_line) entries from LFCCollapsed. "
            "Repurposing 24Q2 compounds appear in top_compounds for annotation "
            "completeness but their activity numbers do NOT roll up to gene-level "
            "or lineage-level fields (Repurposing has no AUC file — single-dose "
            "screen). Requires DepMap 26q1 Model.csv for the ModelID -> "
            "OncotreeLineage join."
        ),
        "gene_aggregate": {
            "filename": "prism_activity_per_gene.parquet",
            "size_bytes": gene_agg_size,
            "n_rows": gene_agg_n_rows,
        },
        "source_files": entries,
    }
    manifest_path = local_dir / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False, default_flow_style=False)
    if upload:
        s3_key = f"{output_prefix.rstrip('/')}/manifest.yaml"
        _upload_to_s3(s3, manifest_path, s3_key)
    return manifest_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

@click.command()
@click.option("--output-prefix", default=DEFAULT_OUTPUT_PREFIX,
              help="S3 prefix (relative to bucket) where parquet + manifest get written.")
@click.option("--local-dir", type=click.Path(file_okay=False, writable=True, path_type=Path),
              default=Path.home() / "dev" / "framework-runs" / "depmap-prism-precompute-local",
              help="Local staging dir where the parquet is written before S3 upload.")
@click.option("--releases", multiple=True, type=click.Choice(list(RELEASES.keys())),
              default=list(RELEASES.keys()),
              help="Subset of releases to ingest. Default: all.")
@click.option("--no-upload", is_flag=True,
              help="Skip S3 upload; write local parquet only. Useful for testing.")
def main(output_prefix: str, local_dir: Path, releases: tuple[str, ...], no_upload: bool) -> None:
    """CLI: ingest PRISM sources → build per-gene activity parquet → upload."""
    import boto3
    import pandas as pd
    s3 = boto3.client("s3")

    releases_to_ingest = list(releases) if releases else list(RELEASES.keys())
    local_dir.mkdir(parents=True, exist_ok=True)
    _log(f"PRISM precompute v3 starting: releases={releases_to_ingest}")
    _log(f"Local staging: {local_dir}")

    entries = []
    compound_dfs = []
    oncref_log2auc = None
    oncref_lfccollapsed_min = None
    repurposing_lfc = None

    for release_pin in releases_to_ingest:
        rel = RELEASES[release_pin]
        _log(f"\n=== Release: {release_pin} ({rel['lineage']}) ===")

        # 1. Compound list
        cmp_key = f"{rel['source_prefix']}/{rel['compound_list_filename']}"
        cmp_body, cmp_sha, cmp_size = _fetch_source(s3, cmp_key)
        if rel["lineage"] == "oncref":
            cmp_df = load_oncref_compound_list(cmp_body)
        else:
            cmp_df = load_repurposing_compound_list(cmp_body)
        _log(f"  compound rows: {len(cmp_df)}, unique compound_ids: {cmp_df['compound_id'].nunique()}")
        compound_dfs.append(cmp_df)
        entries.append({
            "release_pin": release_pin,
            "source_key": cmp_key,
            "source_sha256": cmp_sha,
            "source_size_bytes": cmp_size,
            "role": "compound_list",
            "n_rows": len(cmp_df),
        })

        cmp_ids_here = set(cmp_df["compound_id"].astype(str))

        # 2. Activity data — OncRef fetches Log2AUC (primary) + LFCCollapsed (best-responder)
        #    Repurposing fetches LFC_COLLAPSED (single-dose LFC for annotation-only rank)
        if rel["lineage"] == "oncref":
            # 2a. Log2AUC (primary metric)
            log2auc_key = f"{rel['source_prefix']}/{rel['log2auc_filename']}"
            body, sha, size = _fetch_source(s3, log2auc_key)
            oncref_log2auc = load_oncref_log2auc(body)
            _log(f"  Log2AUC edges: {len(oncref_log2auc)}, "
                 f"unique compounds: {oncref_log2auc['compound_id'].nunique() if len(oncref_log2auc) else 0}")
            entries.append({
                "release_pin": release_pin,
                "source_key": log2auc_key,
                "source_sha256": sha,
                "source_size_bytes": size,
                "role": "log2auc_primary_activity",
                "n_rows_agg": len(oncref_log2auc),
            })
            # 2b. LFCCollapsed (best-responder tail from raw LFC)
            lfc_key = f"{rel['source_prefix']}/{rel['lfc_collapsed_filename']}"
            body, sha, size = _fetch_source(s3, lfc_key)
            oncref_lfccollapsed_min = load_oncref_lfccollapsed(body, cmp_ids_here)
            _log(f"  LFCCollapsed edges (min-LFC per cell-line×compound): {len(oncref_lfccollapsed_min)}")
            entries.append({
                "release_pin": release_pin,
                "source_key": lfc_key,
                "source_sha256": sha,
                "source_size_bytes": size,
                "role": "lfc_best_responder_tail",
                "n_rows_agg": len(oncref_lfccollapsed_min),
            })
        else:
            # Repurposing: single-dose LFC for annotation rank (no AUC available)
            lfc_key = f"{rel['source_prefix']}/{rel['lfc_filename']}"
            body, sha, size = _fetch_source(s3, lfc_key)
            repurposing_lfc = load_repurposing_lfc(body, cmp_ids_here)
            _log(f"  Repurposing LFC edges: {len(repurposing_lfc)}")
            entries.append({
                "release_pin": release_pin,
                "source_key": lfc_key,
                "source_sha256": sha,
                "source_size_bytes": size,
                "role": "single_dose_lfc_annotation_only",
                "n_rows_agg": len(repurposing_lfc),
            })

    _log("\n=== Fetching Model.csv for ModelID -> OncotreeLineage join ===")
    model_csv_key = "data-catalog/sources/depmap-consortium/dmc-26q1/Model.csv"
    model_body, model_sha, model_size = _fetch_source(s3, model_csv_key)
    model_to_lineage = load_model_to_lineage(model_body)
    _log(f"  {len(model_to_lineage)} ModelID -> OncotreeLineage mappings")
    entries.append({
        "release_pin": "dmc-26q1",
        "source_key": model_csv_key,
        "source_sha256": model_sha,
        "source_size_bytes": model_size,
        "role": "cell_line_lineage_metadata",
        "n_rows": len(model_to_lineage),
    })

    _log("\n=== Merging compound universes ===")
    merged = merge_compound_universes(compound_dfs)
    _log(f"  merged compound rows: {len(merged)}, unique compounds after cross-release dedup: "
         f"{len(merged)}")

    _log("\n=== Building gene aggregate ===")
    gene_agg = build_gene_aggregate(
        merged,
        oncref_log2auc=oncref_log2auc,
        oncref_lfccollapsed_min=oncref_lfccollapsed_min,
        repurposing_lfc=repurposing_lfc,
        model_to_lineage=model_to_lineage,
    )
    _log(f"  gene rows: {len(gene_agg)}")
    _log(f"  class distribution: {gene_agg['prism_activity_class'].value_counts().to_dict()}")
    _log(f"  lineage-selectivity distribution: {gene_agg['prism_lineage_selectivity'].value_counts().to_dict()}")

    # Write parquet
    parquet_path = local_dir / "prism_activity_per_gene.parquet"
    parquet_size = write_gene_aggregate_parquet(gene_agg, parquet_path)
    _log(f"\n  wrote {parquet_path} ({parquet_size / 1e6:.1f} MB)")

    if not no_upload:
        s3_key = f"{output_prefix.rstrip('/')}/prism_activity_per_gene.parquet"
        _upload_to_s3(s3, parquet_path, s3_key)

    _write_manifest(entries, parquet_size, len(gene_agg), local_dir, output_prefix,
                     s3, upload=not no_upload)

    _log("\n=== PRISM precompute complete ===")


if __name__ == "__main__":
    main()
