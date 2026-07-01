#!/usr/bin/env python3
"""depmap-prism-precompute — batch job: PRISM sources → gene-level activity parquet.

Reads two PRISM release lineages, unifies their per-compound schemas, computes
per-compound activity stats within each release's own cell-line panel, then
aggregates to gene-level rows (one row per HGNC-annotated gene). Writes a
single frozen parquet + manifest to
`s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v1/`.

The thin `depmap_prism_activity.cli` card reads one gene row via pyarrow
predicate pushdown at compose-dashboard runtime — no CSV parsing, no
cross-release joins at read time.

Cross-release lineages (locked 2026-07-01, plan Q1):
  - OncRef 25Q4: 462 compound-dose rows / ~396 unique compounds / clinical-focus.
                 SampleID = PRC-ID. `GeneSymbolOfTargets` gene column.
                 LFC in Log2ViabilityCollapsedMatrix.csv (WIDE: cells × compound-dose).
  - Repurposing 24Q2: 6790 compounds / broad library. IDs = BRD-ID.
                      `repurposing_target` gene column.
                      LFC in LFC_COLLAPSED.csv (LONG: (row_id, broad_id, dose, LFC)).

Cross-release merge convention:
  - Per-compound activity computed within its OWN release panel; never mixed.
  - source_release column tags provenance per compound row.
  - When a BRD/PRC-normalized compound appears in both, OncRef 25Q4 wins.
  - `top_compounds` ranked across both by within-release activity.

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
DEFAULT_OUTPUT_PREFIX = "data-catalog/derived/depmap-prism-activity-v1"

# Release-pin ↔ source-prefix registry. Each release supplies (compound_list, lfc)
# alongside a lineage tag that switches the loader path.
RELEASES = {
    "oncref-25q4": {
        "lineage": "oncref",
        "source_prefix": "data-catalog/sources/depmap-consortium/prism-oncref-dmc-25q4",
        "compound_list_filename": "PRISMOncologyReferenceLumCompoundList.csv",
        "lfc_filename": "PRISMOncologyReferenceLumLog2ViabilityCollapsedMatrix.csv",
        "priority": 1,   # lower wins in cross-release dedup
    },
    "repurposing-24q2": {
        "lineage": "repurposing",
        "source_prefix": "data-catalog/sources/depmap-consortium/prism-primary-repurposing-24q2",
        "compound_list_filename": "Repurposing_Public_24Q2_Extended_Primary_Compound_List.csv",
        "lfc_filename": "Repurposing_Public_24Q2_LFC_COLLAPSED.csv",
        "priority": 2,
    },
}

# LFC threshold: viability calls below this are "responding" (log2 fold change).
# -1.0 = ~50% viability drop; canonical cell-line-screen cutoff.
LFC_RESPONDING_THRESHOLD = -1.0

# Vocabulary buckets for prism_activity_class. See card spec for authoritative copy.
CLASS_CLINICALLY_ACTIVE = "clinically_active"
CLASS_TOOL_COMPOUND_ONLY = "tool_compound_only"
CLASS_WEAKLY_ACTIVE = "weakly_active"
CLASS_NO_COMPOUNDS_FOUND = "no_compounds_found"
CLASS_DATA_UNAVAILABLE = "data_unavailable"

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
# LFC loaders (per-lineage → common (compound_id × ModelID → median_lfc) table)
# ---------------------------------------------------------------------------

_ONCREF_COL_RE = re.compile(r"^(.*?)\s*\((PRC[-0-9]+)\)\s*@([\d\.]+)\s*uM$")


def load_oncref_lfc(body: bytes) -> "pandas.DataFrame":
    """Melt the OncRef 25Q4 wide viability matrix to (ModelID, compound_id, lfc).

    The wide matrix has cell lines as rows (first col is ModelID / ACH-XXXXXX)
    and columns named 'CompoundName (PRC-XXX) @0.004572 uM'. We melt the whole
    matrix (only ~50 MB), parse each column name into (compound_name, PRC-id, dose),
    then aggregate by (ModelID × compound_id) taking the median across doses.
    """
    import pandas as pd
    df = pd.read_csv(BytesIO(body))
    # First column is the row-index (unnamed in CSV, becomes 'Unnamed: 0' in pandas).
    id_col = df.columns[0]
    df = df.rename(columns={id_col: "model_id"})
    # Melt to long form
    long = df.melt(id_vars=["model_id"], var_name="col_name", value_name="lfc")
    long = long.dropna(subset=["lfc"])

    # Parse compound_id + drug_name + dose from column name
    def _parse(colname):
        m = _ONCREF_COL_RE.match(str(colname))
        if not m:
            return None, None, None
        drug_name, prc, dose = m.group(1), m.group(2), m.group(3)
        return prc.strip(), drug_name.strip(), float(dose)

    parsed = long["col_name"].apply(lambda c: pd.Series(_parse(c), index=["compound_id", "drug_name_lfc", "dose"]))
    long = pd.concat([long.drop(columns=["col_name"]), parsed], axis=1)
    long = long.dropna(subset=["compound_id"])
    # Aggregate across doses (median → viability robust to outliers) per (model_id, compound_id).
    agg = long.groupby(["model_id", "compound_id"], as_index=False).agg(median_lfc=("lfc", "median"))
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


def build_gene_aggregate(
    merged_compounds: "pandas.DataFrame",
    lfc_by_release: dict[str, "pandas.DataFrame"],
    lfc_responding_threshold: float = LFC_RESPONDING_THRESHOLD,
) -> "pandas.DataFrame":
    """Build one row per HGNC-annotated gene.

    For each gene G:
      - all compounds with G in gene_targets across both releases
      - per-compound stats: median_lfc across cell lines (in own release panel)
                             n_lines_responding, n_lines_screened
                             polyselective, n_annotated_targets
      - gene-level rollup: n_compounds_targeting, highest_clinical_phase,
                           median_lfc_across_compounds, top_compounds (top-5 by activity)
                           prism_activity_class
    """
    import pandas as pd

    # Gene ↔ compound edges
    exploded = merged_compounds.explode("gene_targets")
    exploded = exploded[exploded["gene_targets"].notna() & (exploded["gene_targets"] != "")]
    exploded = exploded.rename(columns={"gene_targets": "gene_symbol"})

    # Annotate polyselectivity per compound
    # (recompute n_annotated_targets from merged_compounds, then map back)
    def _n_targets(x):
        v = x
        if isinstance(v, list):
            return len(v)
        return 0
    merged_compounds = merged_compounds.copy()
    merged_compounds["n_annotated_targets"] = merged_compounds["gene_targets"].apply(_n_targets)
    merged_compounds["polyselective"] = merged_compounds["n_annotated_targets"] > 1
    poly_map = dict(zip(merged_compounds["compound_id"], merged_compounds["polyselective"]))
    ntgt_map = dict(zip(merged_compounds["compound_id"], merged_compounds["n_annotated_targets"]))
    exploded["polyselective"] = exploded["compound_id"].map(poly_map).fillna(False)
    exploded["n_annotated_targets"] = exploded["compound_id"].map(ntgt_map).fillna(0).astype(int)

    # Per-compound activity stats — computed WITHIN each release's own cell-line panel
    per_compound_activity = {}
    for release, lfc_df in lfc_by_release.items():
        if lfc_df is None or lfc_df.empty:
            continue
        # For each compound: median across its screened lines, fraction responding
        stats = lfc_df.groupby("compound_id").agg(
            median_lfc=("median_lfc", "median"),
            n_lines_screened=("median_lfc", "size"),
            n_lines_responding=("median_lfc", lambda vals: int((vals < lfc_responding_threshold).sum())),
        ).reset_index()
        for _, row in stats.iterrows():
            key = row["compound_id"]
            per_compound_activity[key] = {
                "median_lfc": float(row["median_lfc"]),
                "n_lines_screened": int(row["n_lines_screened"]),
                "n_lines_responding": int(row["n_lines_responding"]),
                "fraction_lines_responding": float(row["n_lines_responding"]) / max(1, int(row["n_lines_screened"])),
                "source_release": release,
            }

    # Enrich exploded per-gene edges with activity
    def _lookup_activity(cid, field, default=None):
        act = per_compound_activity.get(cid)
        return act[field] if act else default

    for field in ("median_lfc", "n_lines_screened", "n_lines_responding", "fraction_lines_responding"):
        exploded[f"cmp_{field}"] = exploded["compound_id"].apply(
            lambda cid: _lookup_activity(cid, field, None)
        )

    # Aggregate per gene
    rows = []
    for gene, group in exploded.groupby("gene_symbol"):
        # Rank compounds: prefer PRIORITIZED, then most-active median_lfc (lower is better),
        # then largest n_lines_responding, then present-with-activity over absent.
        with_activity = group.dropna(subset=["cmp_median_lfc"]).copy()
        no_activity = group[group["cmp_median_lfc"].isna()].copy()
        if not with_activity.empty:
            with_activity = with_activity.sort_values(
                by=["prioritized", "cmp_median_lfc", "cmp_n_lines_responding"],
                ascending=[False, True, False],
            )
        top_compounds = []
        for _, r in with_activity.head(5).iterrows():
            top_compounds.append({
                "compound_id": r["compound_id"],
                "drug_name": r["drug_name"],
                "moa": r["moa"],
                "median_lfc": None if r["cmp_median_lfc"] is None else float(r["cmp_median_lfc"]),
                "fraction_lines_responding": None if r["cmp_fraction_lines_responding"] is None else float(r["cmp_fraction_lines_responding"]),
                "n_lines_screened": None if r["cmp_n_lines_screened"] is None else int(r["cmp_n_lines_screened"]),
                "polyselective": bool(r["polyselective"]),
                "n_annotated_targets": int(r["n_annotated_targets"]),
                "source_release": r["source_release"],
                "prioritized": bool(r["prioritized"]),
            })
        # Add up-to-5 compounds without activity (still valuable for the card — shows an annotation exists even without an LFC readout)
        if len(top_compounds) < 5:
            for _, r in no_activity.head(5 - len(top_compounds)).iterrows():
                top_compounds.append({
                    "compound_id": r["compound_id"],
                    "drug_name": r["drug_name"],
                    "moa": r["moa"],
                    "median_lfc": None,
                    "fraction_lines_responding": None,
                    "n_lines_screened": None,
                    "polyselective": bool(r["polyselective"]),
                    "n_annotated_targets": int(r["n_annotated_targets"]),
                    "source_release": r["source_release"],
                    "prioritized": bool(r["prioritized"]),
                })

        n_compounds_targeting = len(group)
        # Gene-level median LFC across compounds (only over those with LFC data)
        median_lfc_across_compounds = (
            float(with_activity["cmp_median_lfc"].median()) if not with_activity.empty else None
        )
        # highest_clinical_phase — v1 approximates from prioritized + presence in OncRef.
        # OncRef 25Q4 = clinically-anchored library (approved / phase 1-3 / preclinical mix);
        # Repurposing 24Q2 = broad tool + repurposed clinical library. Without a phase
        # annotation column in the source, we call:
        #   - approved / phase_1+  → any prioritized OncRef compound
        #   - tool                 → repurposing-only or non-prioritized OncRef
        # V2 would ingest an external phase annotation (e.g. ChEMBL max_phase).
        any_prio_oncref = any(
            (r["prioritized"] and r["source_release"] == "oncref-25q4") for _, r in group.iterrows()
        )
        any_oncref = any(r["source_release"] == "oncref-25q4" for _, r in group.iterrows())
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
            median_lfc_across_compounds=median_lfc_across_compounds,
        )

        rows.append({
            "gene_symbol": gene,
            "n_compounds_targeting": int(n_compounds_targeting),
            "highest_clinical_phase": highest_clinical_phase,
            "median_lfc_across_compounds": median_lfc_across_compounds,
            "top_compounds": top_compounds,
            "prism_activity_class": prism_activity_class,
        })

    return pd.DataFrame(rows)


def classify_prism_activity(
    n_compounds_targeting: int,
    highest_clinical_phase: str,
    median_lfc_across_compounds: Optional[float],
) -> str:
    """Vocabulary classifier — mirrors E5's _classify_dependency / _classify_expression pattern.

    Priority order (first-match wins):
      1. No compounds → no_compounds_found (NOT a killer signal; first-in-class opportunity)
      2. Any phase_1+ / approved compound AND at least one compound with median_lfc < -0.5 → clinically_active
      3. Any phase_1+ compound (regardless of LFC) → clinically_active (compound exists in clinic)
      4. tool / preclinical only AND median_lfc < -0.5 → weakly_active
      5. tool / preclinical only → tool_compound_only
    """
    if n_compounds_targeting == 0:
        return CLASS_NO_COMPOUNDS_FOUND
    has_lfc = median_lfc_across_compounds is not None
    has_clinical = highest_clinical_phase in ("phase_1_plus", "approved")
    if has_clinical and has_lfc and median_lfc_across_compounds < -0.5:
        return CLASS_CLINICALLY_ACTIVE
    if has_clinical:
        return CLASS_CLINICALLY_ACTIVE
    if has_lfc and median_lfc_across_compounds < -0.5:
        return CLASS_WEAKLY_ACTIVE
    return CLASS_TOOL_COMPOUND_ONLY


# ---------------------------------------------------------------------------
# Parquet write
# ---------------------------------------------------------------------------

def write_gene_aggregate_parquet(df: "pandas.DataFrame", local_path: Path) -> int:
    """Write the per-gene aggregate DataFrame to parquet with an explicit schema.

    Uses a struct-list schema for `top_compounds` (mirrors E5's `top_features_rf_shap`
    pattern) so pyarrow read_table + predicate pushdown on `gene_symbol` returns
    a fully-typed row without JSON parsing.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    top_struct = pa.struct([
        pa.field("compound_id", pa.string()),
        pa.field("drug_name", pa.string()),
        pa.field("moa", pa.string()),
        pa.field("median_lfc", pa.float32()),
        pa.field("fraction_lines_responding", pa.float32()),
        pa.field("n_lines_screened", pa.int32()),
        pa.field("polyselective", pa.bool_()),
        pa.field("n_annotated_targets", pa.int32()),
        pa.field("source_release", pa.string()),
        pa.field("prioritized", pa.bool_()),
    ])
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("n_compounds_targeting", pa.int32()),
        pa.field("highest_clinical_phase", pa.string()),
        pa.field("median_lfc_across_compounds", pa.float32()),
        pa.field("top_compounds", pa.list_(top_struct)),
        pa.field("prism_activity_class", pa.string()),
    ])
    # Ensure column presence + order + no NA in scalar fields (parquet cast happier)
    df = df.copy()
    df["median_lfc_across_compounds"] = df["median_lfc_across_compounds"].astype(object)
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
        "derived_product_id": "depmap-prism-activity-v1",
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
        "lfc_responding_threshold": LFC_RESPONDING_THRESHOLD,
        "vocabulary": {
            "prism_activity_class": [
                CLASS_CLINICALLY_ACTIVE, CLASS_TOOL_COMPOUND_ONLY,
                CLASS_WEAKLY_ACTIVE, CLASS_NO_COMPOUNDS_FOUND,
                CLASS_DATA_UNAVAILABLE,
            ],
            "highest_clinical_phase": ["tool", "preclinical", "phase_1_plus", "approved"],
        },
        "notes": (
            "Per-gene rollup of PRISM small-molecule viability screens. Consumed by "
            "methods.depmap_prism_activity thin lookup card. Row count: ~n_hgnc_genes_with_"
            "at_least_one_annotated_compound (bounded above by ~19k HGNC symbols)."
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
    _log(f"PRISM precompute starting: releases={releases_to_ingest}")
    _log(f"Local staging: {local_dir}")

    entries = []
    compound_dfs = []
    lfc_dfs = {}

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

        # 2. LFC — filter to compound_ids from this release's compound list
        lfc_key = f"{rel['source_prefix']}/{rel['lfc_filename']}"
        lfc_body, lfc_sha, lfc_size = _fetch_source(s3, lfc_key)
        cmp_ids_here = set(cmp_df["compound_id"].astype(str))
        if rel["lineage"] == "oncref":
            lfc_df = load_oncref_lfc(lfc_body)
        else:
            lfc_df = load_repurposing_lfc(lfc_body, cmp_ids_here)
        _log(f"  LFC edges: {len(lfc_df)}, "
             f"unique compounds with LFC: {lfc_df['compound_id'].nunique() if len(lfc_df) else 0}")
        lfc_dfs[release_pin] = lfc_df
        entries.append({
            "release_pin": release_pin,
            "source_key": lfc_key,
            "source_sha256": lfc_sha,
            "source_size_bytes": lfc_size,
            "role": "lfc_matrix",
            "n_rows_agg": len(lfc_df),
        })

    _log("\n=== Merging compound universes ===")
    merged = merge_compound_universes(compound_dfs)
    _log(f"  merged compound rows: {len(merged)}, unique compounds after cross-release dedup: "
         f"{len(merged)}")

    _log("\n=== Building gene aggregate ===")
    gene_agg = build_gene_aggregate(merged, lfc_dfs)
    _log(f"  gene rows: {len(gene_agg)}")
    _log(f"  class distribution: {gene_agg['prism_activity_class'].value_counts().to_dict()}")

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
