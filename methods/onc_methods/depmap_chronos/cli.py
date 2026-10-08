#!/usr/bin/env python3
"""depmap-chronos CLI — lineage-specific dependency analysis.

Consumes DepMap 26Q3 CRISPRGeneEffect.csv + Model.csv, computes per-target lineage-
selectivity stats (target lineage vs panel + all-other-lineages forest), emits
summary.json + two SVG figures (forest_plot + lineage_strip) + plot_data.parquet
for the dependency-lineage-selectivity card (Card 2).

Usage:
    depmap-chronos \
        --target KRAS \
        --indication COADREAD \
        --release-pin 26q3 \
        --out /tmp/depmap_chronos_KRAS_COADREAD/

Outputs (in --out directory):
  - summary.json          — decision-grade scalars matching Card 2's outputs.summary_fields
  - figure_forest_plot.svg — per-lineage Chronos median + IQR forest plot
  - figure_lineage_strip.svg — per-lineage strip/swarm of cell-line Chronos points
  - plot_data.parquet     — long-format per-cell-line data
  - manifest.yaml         — provenance + lineage list + input md5s

Like Card 1's depmap-chronos-distribution: S3-aware loader with local-cache fallback.
Graceful degradation via _live_read_error on AccessDenied.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import click

from onc_methods.catalog_query.read import bucket_prefix_for, s3_uri_for
from onc_methods.roots import contracts_root, data_catalog_root

METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "2.0.0"

# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
DEFAULT_CATALOG_REPO = data_catalog_root()
DEFAULT_TARGET_CONTRACTS = contracts_root()
DEPMAP_SOURCE_MANIFEST_ID = "depmap-consortium-26q3"
# Resolved from the data-catalog manifest (single source of truth). DEPMAP_S3_PREFIX (s3://-form,
# no trailing slash) feeds echo/provenance strings; _DEPMAP_KEY_PREFIX (bucket-relative) builds the
# actual get_object read keys below.
DEPMAP_S3_PREFIX = s3_uri_for(DEPMAP_SOURCE_MANIFEST_ID).rstrip("/")
_DEPMAP_KEY_PREFIX = bucket_prefix_for(DEPMAP_SOURCE_MANIFEST_ID)[1].rstrip("/")
DEPMAP_LOCAL_FALLBACK_DIRS = [
    Path("/data/depmap/26q3"),
    Path.home() / "depmap-26q3",
]


@lru_cache(maxsize=32)
def load_depmap_files(release_pin: str, target_symbol: str) -> tuple[dict, dict, list]:
    """Same loader pattern as depmap_chronos_distribution.cli — local cache, then S3.
    Returns (chronos_by_model_id, model_metadata_by_id, load_errors).

    PROCESS-CACHED (lru_cache, keyed by the pinned release + target): the target-profile fan-out
    calls this once per card × stratum for the SAME target — 6+ cards (dependency, 3 stratified
    siblings, cis-coherence, combination) across up to 14 COADREAD strata. Uncached, a parquet-MISS
    (an alias like SCD1→SCD, or a gene absent from the fast-path column) re-read the full ~564MB
    CRISPRGeneEffect CSV on EVERY call (observed 12× per run → the ~535s stall). Caching collapses
    that to one read. SAFE: the returned dicts are consumed READ-ONLY (callers only iterate
    chronos_by_model.items() / model_metadata.get(...)); release_pin pins the data so cross-run
    staleness is a non-issue. (Canonical targets already hit the cached parquet fast path via
    get_chronos_column; this closes the fallback-path over-read too.)"""
    import pandas as pd

    crispr_path = None
    model_path = None
    load_errors = []

    for fallback_dir in DEPMAP_LOCAL_FALLBACK_DIRS:
        cc = fallback_dir / "CRISPRGeneEffect.csv"
        cm = fallback_dir / "Model.csv"
        if cc.exists() and cm.exists():
            crispr_path = cc
            model_path = cm
            click.echo(f"  Using local DepMap cache at {fallback_dir}", err=True)
            break

    # Model.csv: prefer the local-cache Model.csv when a local-cache CRISPR was
    # found (test-fixture consistency); otherwise use the shared cached S3 loader.
    if model_path is not None:
        model_df = pd.read_csv(model_path)
    else:
        from onc_methods.depmap_common import load_model_csv

        try:
            model_df = load_model_csv(release_pin)
        except FileNotFoundError as e:
            load_errors.append(
                {
                    "_live_read_error": "s3_read_failed",
                    "detail": str(e),
                }
            )
            return {}, {}, load_errors

    # === TIER-2 PATH: parquet derived product (100-500× faster than CSV) ===
    if crispr_path is None:
        try:
            from onc_methods.depmap_common.parquet import get_chronos_column

            target_df = get_chronos_column(target_symbol, release_pin)
            if target_df is not None:
                target_col = next((c for c in target_df.columns if c != "ModelID"), None)
                if target_col:
                    chronos_by_model = {}
                    for _, row in target_df.iterrows():
                        val = row[target_col]
                        if pd.notna(val):
                            chronos_by_model[row["ModelID"]] = float(val)
                    model_id_col = "ModelID" if "ModelID" in model_df.columns else model_df.columns[0]
                    model_metadata = {row[model_id_col]: row.to_dict() for _, row in model_df.iterrows()}
                    return chronos_by_model, model_metadata, load_errors
        except (FileNotFoundError, ImportError):
            pass  # fall through to CSV

    # === LEGACY CSV PATH (fallback) ===
    if crispr_path is None:
        try:
            import boto3

            s3 = boto3.client("s3")
            bucket = "onc-compbio"
            crispr_key = f"{_DEPMAP_KEY_PREFIX}/CRISPRGeneEffect.csv"
            click.echo(f"  Fetching s3://{bucket}/{crispr_key}", err=True)
            crispr_obj = s3.get_object(Bucket=bucket, Key=crispr_key)
            crispr_df = pd.read_csv(BytesIO(crispr_obj["Body"].read()))
        except ImportError as e:
            load_errors.append(
                {
                    "_live_read_error": "boto3_not_available",
                    "detail": str(e),
                    "remediation": f"Install boto3 or provide local cache at {[str(d) for d in DEPMAP_LOCAL_FALLBACK_DIRS]}",
                }
            )
            return {}, {}, load_errors
        except Exception as e:
            load_errors.append(
                {
                    "_live_read_error": "s3_read_failed",
                    "detail": str(e),
                    "remediation": f"Ensure AWS credentials are set and bucket {DEPMAP_S3_PREFIX} is accessible.",
                }
            )
            return {}, {}, load_errors
    else:
        crispr_df = pd.read_csv(crispr_path)

    # Extract target column
    target_columns = [c for c in crispr_df.columns if c == target_symbol or c.split(" ")[0] == target_symbol]
    if not target_columns:
        load_errors.append(
            {
                "_live_read_error": "target_not_in_crispr_panel",
                "detail": f"Target {target_symbol} not found in CRISPRGeneEffect.csv",
            }
        )
        return {}, {}, load_errors

    target_col = target_columns[0]
    cell_line_col = crispr_df.columns[0]
    chronos_by_model = {}
    for _, row in crispr_df[[cell_line_col, target_col]].iterrows():
        if pd.notna(row[target_col]):
            chronos_by_model[row[cell_line_col]] = float(row[target_col])

    model_id_col = "ModelID" if "ModelID" in model_df.columns else model_df.columns[0]
    model_metadata = {row[model_id_col]: row.to_dict() for _, row in model_df.iterrows()}
    return chronos_by_model, model_metadata, load_errors


# ============================================================================
# CANONICAL indication → DepMap OncotreeLineage map — SINGLE SOURCE OF TRUTH.
# ============================================================================
# The one authoritative framework-indication → DepMap 26Q1 OncotreeLineage
# crosswalk. Every value is a REAL lineage in DepMap 26Q1 Model.csv (34 non-null
# OncotreeLineage categories; verified live 2026-08-16). It lives HERE (the leaf
# module — cli.py imports nothing from read.py) and is re-exported by
# depmap_chronos.read as INDICATION_TO_DEPMAP_LINEAGE (the SAME object, no fork)
# and imported by the 4 stratified-dependency readers, the 3 sibling depmap
# display CLIs, and pathway_node_leverage. Do NOT re-fork this literal in another
# module — alias-import it (guarded by
# tests/methods/depmap_chronos/test_lineage_map_single_source.py).
#
# Used by the figure emitters (highlight the target lineage at render time) + the
# indication-conditioned stratified-dependency ladder. NOT consumed by
# compute_lineage_summary — that method's output is target-only.
#
# History: the original GC/STAD → "Stomach" was a LATENT BUG (DepMap 26Q1 has NO
# "Stomach" lineage; the real merged value is "Esophagus/Stomach") — corrected in
# #365; consolidated from 6 forks to this single source + full framework coverage
# (heme AML/CML + defensive MELANOMA alias) in the lineage-scoping residual
# consolidation (2026-08-16).
INDICATION_LINEAGE = {
    "COADREAD": "Bowel",
    "COAD": "Bowel",
    "READ": "Bowel",
    "LUAD": "Lung",
    "LUSC": "Lung",
    "NSCLC": "Lung",
    "SCLC": "Lung",
    "BRCA": "Breast",
    "PAAD": "Pancreas",
    "PDAC": "Pancreas",
    "SKCM": "Skin",
    "MELANOMA": "Skin",  # MELANOMA aliases SKCM (defensive)
    "STAD": "Esophagus/Stomach",
    "ESCA": "Esophagus/Stomach",
    "GC": "Esophagus/Stomach",  # was "Stomach" (nonexistent lineage) — fixed
    "PRAD": "Prostate",
    "OV": "Ovary/Fallopian Tube",
    "KIRC": "Kidney",
    "GBM": "CNS/Brain",
    "LGG": "CNS/Brain",
    "HNSC": "Head and Neck",
    "BLCA": "Bladder/Urinary Tract",
    "LIHC": "Liver",
    "UCEC": "Uterus",
    "CESC": "Cervix",
    "LAML": "Myeloid",
    "AML": "Myeloid",
    "CML": "Myeloid",  # heme (LAML=TCGA code; AML/CML=framework codes)
    "DLBC": "Lymphoid",
    # TCGA-pancan coverage expansion (2026-09-09; mirrors target-contracts
    # indication_crosswalk.yaml — values MUST match the crosswalk's depmap_lineage or the
    # cross-repo agreement test fails). THYM is deliberately absent: DepMap 26Q1 has no
    # thymus lineage, so the crosswalk carries depmap_lineage: null and no scoping is possible.
    "ACC": "Adrenal Gland",
    "CHOL": "Biliary Tract",
    "KICH": "Kidney",
    "KIRP": "Kidney",
    "PCPG": "Adrenal Gland",
    "SARC": "Soft Tissue",
    "TGCT": "Testis",
    "THCA": "Thyroid",
    "UCS": "Uterus",
    "MESO": "Pleura",
    # Discovery-register codes the 2026-09-09 expansion MISSED (added 2026-09-12). All three are
    # first-class canonical_codes in the crosswalk with a non-null depmap_lineage, so their absence here
    # was a silent pan-lineage fallback: apply_lineage_ladder resolves the indication through THIS map,
    # so `--indication NBL` produced pan-scope evidence rather than a within-indication read. That is
    # decision-relevant — NBL is one of the panel's genuine lineage-selective dependencies (GATA3/NBL
    # median Chronos -0.553, n=45) and UVM's Eye lineage carries MDM2 -1.61 / CDK4 -1.10 / SHOC2 -0.57.
    # The cross-repo agreement guard could not see the gap because it only iterated the CROSSWALK; it is
    # now bidirectional (target-contracts #737), and the coverage guard below reads the crosswalk itself
    # instead of a hand-copied code list.
    "BCC": "Skin",
    "NBL": "Peripheral Nervous System",
    "UVM": "Eye",  # crosswalk repaired from null in target-contracts #737 (26Q1 Eye: UM=16, RBL=6)
    # ONCOTREE-CODE ALIASES (2026-09-18). Each is the `oncotree_code` the crosswalk already declares on
    # its own entry — DLBCL on DLBC, UM on UVM — so the vocabulary was PUBLISHING a code that resolved
    # nowhere, here or there. Callers pass these forms: measured over the 504-pair atlas run population,
    # DLBCL appears on 7 target-indication pairs and UM on 2, and every one of those 9 resolved to
    # nothing and took the skill's "not in the framework indication vocabulary" branch — no
    # indication-scoped read at all. Same class as the MELANOMA/GC/PDAC/LAML aliases above.
    #
    # ORDERING (measured as a 2x2 over {this map} x {crosswalk}, not assumed): this half must land
    # FIRST. analysis-methods CI checks out target-contracts at `ref: main` — a live read, NOT a SHA
    # pin — and the coverage guard folds the crosswalk's `aliases` into its supported set. So if the
    # crosswalk half landed first, `test_every_framework_indication_resolves_to_a_real_lineage` would
    # red on ['DLBCL', 'UM'] for every push until this landed. The reverse exposure does not exist:
    # contracts-validate.yml (now folded into skills-validate.yml) checks out no siblings, so the
    # contracts-side agreement guard SKIPS in its own CI and only bites locally. Only (this map NEW,
    # crosswalk NEW) is green on both sides.
    "DLBCL": "Lymphoid",  # oncotree_code of crosswalk canonical DLBC
    "UM": "Eye",  # oncotree_code of crosswalk canonical UVM; also its depmap_oncotree_codes member
}


def _lineage_depth_cleared(
    record: dict,
    dependency_cut: float,
    sublineage_stats: list = None,
    min_n: int = 5,
) -> tuple:
    """Does an enrichment record reach the absolute dependency cut at ANY adequately-powered grain?

    The admissibility half of the lineage-selectivity call (see compute_lineage_summary). Returns
    (cleared, grain, cleared_sublineages).

    WHY TWO GRAINS AND NOT JUST THE LINEAGE MEDIAN (panel-established 2026-09-12): a coarse
    OncotreeLineage median DILUTES a sublineage-restricted dependency, because the lineage pools
    tumour types that do not share the dependency. A flat cut on the lineage median alone discards
    four separately-validated lineage dependencies on a 44-gene panel:
        IRF4   Lymphoid -0.455  but PCM (plasma-cell myeloma) -2.041 (n=19) — the canonical
               myeloma dependency (Shaffer 2008); the Lymphoid pool is mostly leukaemia/lymphoma
        SPI1   Myeloid  -0.364  but AML     -0.552 (n=39)
        RUNX1  Myeloid  -0.486  but AML     -0.510 (n=39), AMLNOS -1.369 (n=5)
        GATA3  PNS      -0.430  but NBL     -0.553 (n=45) — neuroblastoma core regulatory circuitry
        PAX8   Uterus   -0.470  but UCEC    -0.677 (n=20)
    So the floor is satisfied by EITHER the lineage's own median OR any constituent OncotreeCode
    with n >= min_n. `min_n` mirrors the enrichment table's own admissibility floor, so a sublineage
    cannot rescue a lineage on 1-2 lines. A missing median is NOT cleared — an unmeasurable depth
    cannot license a positive verdict.
    """
    cleared_subs = [
        s
        for s in (sublineage_stats or [])
        if s.get("oncotree_lineage") == record.get("lineage")
        and s.get("n") is not None
        and int(s["n"]) >= min_n
        and s.get("median_chronos") is not None
        and s["median_chronos"] == s["median_chronos"]
        and float(s["median_chronos"]) <= dependency_cut
    ]
    median = record.get("median_chronos")
    if median is not None and median == median and float(median) <= dependency_cut:
        return True, "lineage", cleared_subs
    if cleared_subs:
        return True, "oncotree_code", cleared_subs
    return False, None, []


def compute_lineage_summary(
    chronos_by_model: dict,
    model_metadata: dict,
    indication: str = None,  # kept for back-compat; unused
    strong_threshold: float = -1.0,
    moderate_threshold: float = -0.5,
    min_n_lineage: int = 5,
    enrichment_alpha: float = 0.05,
    enrichment_effect_size_min: float = 0.3,
    broadly_dependent_panel_median: float = -0.5,
) -> dict:
    """Compute Card 2 summary fields. PURE-DATA / TARGET-ONLY shape (v3.0.0).

    Returns:
      - panel-wide stats (n_cell_lines_panel, median_chronos_panel)
      - per_lineage_stats: full ranked table for ALL lineages with n ≥ min_n_lineage
      - enriched_lineages: lineages significantly more dependent than the rest (BH-corrected) AND
        dependent in ABSOLUTE terms (own median Chronos <= moderate_threshold) — the verdict-bearing set
      - relative_only_enriched_lineages: significant vs rest but NOT absolutely dependent (verdict-inert)
      - enrichment_class: categorical describing the SHAPE of lineage variation

    DECOUPLED FROM INDICATION (Decision 2A): the `indication` parameter is kept for
    backward-compatibility with existing callers but is NOT consumed. The method
    returns one ranked table per target; indication-specific row-highlighting is
    a synthesis-layer concern.
    """
    import numpy as np
    import pandas as pd
    from scipy import stats as scipy_stats

    # Build merged dataframe
    rows = []
    for mid, c in chronos_by_model.items():
        meta = model_metadata.get(mid, {})
        lineage = meta.get("OncotreeLineage") or meta.get("lineage") or "unknown"
        # OncotreeCode disambiguates SHARED coarse lineages that merge >1 indication (Esophagus/Stomach
        # → STAD/ESCA/ESCC; Lung → LUAD/SCLC/LUSC/…) — the substrate for a per-oncotree-sublineage read.
        oncotree_code = meta.get("OncotreeCode") or "unknown"
        rows.append({"ModelID": mid, "chronos": c, "OncotreeLineage": lineage, "OncotreeCode": oncotree_code})
    merged = pd.DataFrame(rows)

    n_panel = len(merged)
    if n_panel == 0:
        return {
            "n_cell_lines_panel": 0,
            "median_chronos_panel": None,
            "per_lineage_stats": [],
            "n_lineages_evaluated": 0,
            "enriched_lineages": [],
            "n_enriched_lineages": 0,
            "relative_only_enriched_lineages": [],
            "n_relative_only_enriched_lineages": 0,
            "enrichment_class": "data_unavailable",
            "per_oncotree_code_stats": [],
            "n_oncotree_codes_evaluated": 0,
        }
    median_panel = float(merged["chronos"].median())

    # Per-lineage descriptive stats — full ranked table (target-only data product)
    per_lineage_stats = []
    for ln_name, subset in merged.groupby("OncotreeLineage"):
        if len(subset) < min_n_lineage:
            continue
        per_lineage_stats.append(
            {
                "lineage": str(ln_name),
                "n": int(len(subset)),
                "median_chronos": float(subset["chronos"].median()),
                "p25_chronos": float(subset["chronos"].quantile(0.25)),
                "p75_chronos": float(subset["chronos"].quantile(0.75)),
                "fraction_strongly_dependent": float((subset["chronos"] <= strong_threshold).mean()),
            }
        )
    per_lineage_stats.sort(key=lambda x: x["median_chronos"])
    n_lineages_evaluated = len(per_lineage_stats)

    # ADDITIVE per-OncotreeCode SUBLINEAGE table (2026-08-19) — the substrate for disambiguating the
    # SHARED coarse lineages an indication reduction confounds (Esophagus/Stomach → STAD/ESCA/ESCC;
    # Lung → LUAD/SCLC/LUSC/…). Same descriptive shape as per_lineage_stats, keyed by OncotreeCode +
    # its parent OncotreeLineage. NO LONGER VERDICT-INERT (2026-09-12): this table is now also the
    # finer-grain substrate for the absolute-depth admissibility floor on enriched_lineages, so a
    # sublineage-restricted dependency (IRF4/PCM inside Lymphoid) can clear a floor its diluted
    # coarse-lineage median misses — see _lineage_depth_cleared. The indication→OncotreeCode-set
    # aggregation (e.g. NSCLC = LUAD+LUSC+NSCLC+LCLC+LUAS) is a CONSUMER concern (skill reduction +
    # crosswalk), NOT computed here — this emits the granular per-code stats so the consumer can sum them.
    per_oncotree_code_stats = []
    if "OncotreeCode" in merged.columns:
        for code, subset in merged.groupby("OncotreeCode"):
            if code in (None, "unknown", "") or len(subset) < min_n_lineage:
                continue
            parent = subset["OncotreeLineage"].iloc[0]
            per_oncotree_code_stats.append(
                {
                    "oncotree_code": str(code),
                    "oncotree_lineage": str(parent),
                    "n": int(len(subset)),
                    "median_chronos": float(subset["chronos"].median()),
                    "p25_chronos": float(subset["chronos"].quantile(0.25)),
                    "p75_chronos": float(subset["chronos"].quantile(0.75)),
                    "fraction_strongly_dependent": float((subset["chronos"] <= strong_threshold).mean()),
                }
            )
        per_oncotree_code_stats.sort(key=lambda x: x["median_chronos"])

    # DepMap-style enrichment test: Mann-Whitney U each lineage vs rest of panel,
    # one-sided (alternative: lineage more dependent = lower Chronos). BH multiple-
    # testing correction across all evaluated lineages.
    enriched_lineages = []
    relative_only_enriched_lineages = []
    if n_lineages_evaluated >= 2:
        p_values = []
        records = []
        for stat in per_lineage_stats:
            ln = stat["lineage"]
            lineage_scores = merged[merged["OncotreeLineage"] == ln]["chronos"].to_numpy()
            rest_scores = merged[merged["OncotreeLineage"] != ln]["chronos"].to_numpy()
            if len(lineage_scores) < 2 or len(rest_scores) < 2:
                p_values.append(1.0)
                records.append(
                    {
                        "lineage": ln,
                        "n": stat["n"],
                        "delta_vs_rest": 0.0,
                        "p_value": 1.0,
                        "effect_size": 0.0,
                        "median_chronos": stat["median_chronos"],
                    }
                )
                continue
            try:
                u_stat, p_one_sided = scipy_stats.mannwhitneyu(lineage_scores, rest_scores, alternative="less")
            except ValueError:
                p_one_sided = 1.0
            delta_vs_rest = float(np.median(lineage_scores) - np.median(rest_scores))
            # Effect size as rank-biserial correlation (Mann-Whitney standard effect size):
            # 1 - 2U/(n1*n2)
            n1, n2 = len(lineage_scores), len(rest_scores)
            try:
                effect = 1.0 - (2.0 * u_stat) / (n1 * n2)
            except (ZeroDivisionError, NameError):
                effect = 0.0
            p_values.append(float(p_one_sided))
            records.append(
                {
                    "lineage": ln,
                    "n": stat["n"],
                    "median_chronos": stat["median_chronos"],
                    "delta_vs_rest": delta_vs_rest,
                    "p_value": float(p_one_sided),
                    "effect_size": float(effect),
                }
            )

        # BH correction
        p_array = np.array(p_values)
        m = len(p_array)
        order = np.argsort(p_array)
        ranks = np.empty_like(order)
        ranks[order] = np.arange(1, m + 1)
        q_values = np.minimum.accumulate((p_array[order] * m / ranks[order])[::-1])[::-1]
        q_unordered = np.empty_like(q_values)
        q_unordered[order] = q_values
        for i, rec in enumerate(records):
            rec["q_value"] = float(min(1.0, q_unordered[i]))

        # Filter to significantly enriched (q < α AND meaningful effect AND delta is negative i.e. more dependent)
        relatively_enriched = [
            r for r in records if r["q_value"] < enrichment_alpha and r["delta_vs_rest"] <= -enrichment_effect_size_min
        ]
        # ABSOLUTE-DEPTH ADMISSIBILITY (2026-09-12). Both tests above are RELATIVE: `q_value` asks
        # "is this lineage's Chronos distribution shifted below the rest of the panel?" and
        # `delta_vs_rest` measures that shift. NEITHER asks whether the enriched lineage is dependent
        # AT ALL — so nothing structurally prevents a lineage sitting at Chronos ~= -0.2 from being
        # called "significantly more dependent" than a panel sitting at ~= 0.0, and since
        # `lineage_selective` outranks the `non_dependent` veto in dependency.resolver.yaml, such a
        # hit would license a POSITIVE selective-dependency verdict on no absolute signal.
        #
        # This is HARDENING, not a live-bug fix: on a 44-gene panel every admitted hit was already
        # genuinely dependent in its lineage (shallowest: TEAD1/Pleura -0.541, SHOC2/Eye -0.570).
        # NOTE the correct frame — a near-zero POOLED panel median is NOT evidence against a lineage
        # call, it IS what selectivity looks like (TP63 pools to -0.033 while Head and Neck sits at
        # -0.705). The floor is therefore applied to the ENRICHED LINEAGE's depth, never the panel's.
        #
        # Depth is evaluated at the finest ADEQUATELY-POWERED grain (lineage median OR any
        # constituent OncotreeCode with n >= min_n_lineage) because coarse lineage medians dilute
        # sublineage-restricted dependencies — see _lineage_depth_cleared for the four validated
        # targets (IRF4/PCM, SPI1/AML, RUNX1/AML, GATA3/NBL) a flat coarse cut would discard.
        #
        # Relative-only hits are NOT discarded: they move to `relative_only_enriched_lineages`
        # (additive, verdict-inert) so a real-but-shallow lineage skew stays visible to a reader and
        # to the synthesis layer. When every hit is relative-only, `enrichment_class` falls through to
        # the existing `broadly_lineage_dependent` / `no_lineage_enrichment` branches — no new enum
        # value, and the pooled veto survives, which is the correct read.
        for r in relatively_enriched:
            cleared, grain, cleared_subs = _lineage_depth_cleared(
                r, moderate_threshold, per_oncotree_code_stats, min_n_lineage
            )
            if cleared:
                r["depth_cleared_at_grain"] = grain
                if grain == "oncotree_code":
                    # Name the sublineage(s) that carried the call — without this the reader sees a
                    # positive lineage verdict whose lineage median looks non-dependent.
                    r["depth_cleared_sublineages"] = [
                        {"oncotree_code": s["oncotree_code"], "n": s["n"], "median_chronos": s["median_chronos"]}
                        for s in cleared_subs
                    ]
                enriched_lineages.append(r)
            else:
                relative_only_enriched_lineages.append(r)
        enriched_lineages.sort(key=lambda r: r["q_value"])
        relative_only_enriched_lineages.sort(key=lambda r: r["q_value"])

    n_enriched = len(enriched_lineages)

    # Enrichment class — descriptive SHAPE of lineage variation across the panel
    if n_lineages_evaluated == 0:
        enrichment_class = "data_unavailable"
    elif n_enriched >= 1:
        enrichment_class = "lineage_selective"
    elif median_panel <= broadly_dependent_panel_median:
        enrichment_class = "broadly_lineage_dependent"
    else:
        enrichment_class = "no_lineage_enrichment"

    # Axis-3 (contextualized interpretation): ACROSS-LINEAGE OMNIBUS effect size.
    # COMPLEMENTARY to enrichment_class (which is a per-lineage one-vs-rest THRESHOLD test):
    # this is the GLOBAL variance view — "how much of the dependency (Chronos) variance across
    # the whole panel is explained by lineage?" — via Kruskal-Wallis + epsilon-squared. Reuses
    # the SAME proven helper the tumor-presence subtype omnibus uses (pure numpy, ships its own
    # chi-square SF; scipy is its test-oracle only), fed per-lineage Chronos vectors instead of
    # per-subtype log2TPM. Kept ALONGSIDE enrichment_class, NOT replacing it — exactly as
    # presence keeps subtype_stratification_class + the omnibus (non-redundant: a target can be
    # pan_subtype_uniform on the threshold view yet moderate on the global-variance view).
    # DISPLAY-ONLY / verdict-inert: the CLASS bins on ε² ONLY (effect size); the omnibus p is
    # display-only (at DepMap n's KW p is near-always significant → significance != actionability).
    lineage_vectors = {
        stat["lineage"]: merged[merged["OncotreeLineage"] == stat["lineage"]]["chronos"].tolist()
        for stat in per_lineage_stats
    }
    omnibus = _lineage_omnibus(lineage_vectors, min_group_n=min_n_lineage)

    return {
        "n_cell_lines_panel": n_panel,
        "median_chronos_panel": median_panel,
        "per_lineage_stats": per_lineage_stats,
        "n_lineages_evaluated": n_lineages_evaluated,
        "enriched_lineages": enriched_lineages,
        "n_enriched_lineages": n_enriched,
        "enrichment_class": enrichment_class,
        # Relative-only enrichment: significant + meaningful delta_vs_rest, but the lineage's own
        # median Chronos does NOT clear the absolute dependency cut. VERDICT-INERT disclosure — a
        # shallow-but-real lineage skew a reader should see, which must not license a positive
        # dependency verdict on its own (see the admissibility note in compute_lineage_summary).
        "relative_only_enriched_lineages": relative_only_enriched_lineages,
        "n_relative_only_enriched_lineages": len(relative_only_enriched_lineages),
        # ADDITIVE per-OncotreeCode sublineage table (verdict-inert) — disambiguates shared coarse
        # lineages (STAD/ESCA, NSCLC/SCLC) for a consumer-side indication reduction; see above.
        "per_oncotree_code_stats": per_oncotree_code_stats,
        "n_oncotree_codes_evaluated": len(per_oncotree_code_stats),
        # Axis-3 across-lineage omnibus (display-only; complements enrichment_class):
        **omnibus,
        # Internal-only payload preserved for the figure emitters (which need the
        # ranked table to draw the forest plot). Underscore-prefixed → renderer hides
        # per dashboard-rendering-discipline.
        "_per_lineage_records": per_lineage_stats,
    }


def _lineage_omnibus(lineage_vectors: dict, min_group_n: int = 5) -> dict:
    """Across-lineage Kruskal-Wallis + epsilon-squared omnibus, remapped to lineage_* keys.

    Reuses tcga_gtex_expression_distribution.stats.kruskal_epsilon_squared (substrate-agnostic:
    {group_id: [values]} → omnibus dict) — feeding per-lineage Chronos vectors gives the true
    across-lineage variance-explained effect size that the per-lineage one-vs-rest enrichment
    test does not provide. Renames the helper's subtype_* keys to lineage_* so the field names
    read correctly for the dependency card. data_unavailable-safe (never raises): a helper import
    failure degrades to a data_unavailable omnibus block, leaving the descriptive stats intact.
    """
    try:
        from onc_methods.tcga_gtex_expression_distribution.stats import kruskal_epsilon_squared

        res = kruskal_epsilon_squared(lineage_vectors, min_group_n=min_group_n, min_groups=2)
    except Exception:  # noqa: BLE001  # absence-discipline: exempt -- Axis-3 lineage-omnibus is a verdict-inert DISPLAY facet (never flips the dependency verdict); the guarded call is an in-memory Kruskal stats computation over already-loaded vectors (kruskal_epsilon_squared), NOT an S3 read, so there is no transient-read seam to mask -- a stats/degenerate-input failure must not break the lineage summary
        return {
            "lineage_omnibus_kruskal_h": None,
            "lineage_omnibus_p": None,
            "lineage_variance_explained": None,
            "lineage_omnibus_effect_size_class": "data_unavailable",
            "which_lineages_separate": None,
            "n_lineages_omnibus_tested": 0,
        }
    return {
        "lineage_omnibus_kruskal_h": res.get("subtype_omnibus_kruskal_h"),
        "lineage_omnibus_p": res.get("subtype_omnibus_p"),  # DISPLAY-ONLY
        "lineage_variance_explained": res.get("subtype_variance_explained"),  # ε²
        "lineage_omnibus_effect_size_class": res.get("subtype_effect_size_class"),
        "which_lineages_separate": res.get("which_subtypes_separate"),
        "n_lineages_omnibus_tested": res.get("n_subtypes_tested", 0),
    }


def emit_forest_plot(
    per_lineage_records: list,
    target_lineage: str,
    target_symbol: str,
    indication: str,
    summary: dict,
    out_path: Path,
    contracts_root: Path,
) -> None:
    """Emit the lineage forest plot: median + IQR per lineage, target highlighted."""
    import matplotlib.pyplot as plt
    import numpy as np

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    from oncology_target_contracts.plot_styles.takeda_palette import (  # type: ignore
        CHRONOS_STRONG_DEPENDENCY,
        FIGSIZE_SINGLE_COLUMN_TALL,
        get_lineage_color,
    )

    if not per_lineage_records:
        fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE_COLUMN_TALL)
        ax.text(
            0.5,
            0.5,
            "No per-lineage data available",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=10,
            color="#666666",
        )
        ax.axis("off")
        fig.savefig(out_path / "figure_forest_plot.svg", bbox_inches="tight")
        plt.close(fig)
        return

    # Truncate to top 20 lineages (most dependent) to keep plot readable
    plotted = per_lineage_records[:20]
    n = len(plotted)
    fig_h = max(2.5, 0.25 * n + 0.8)
    fig, ax = plt.subplots(figsize=(4.5, fig_h))

    y_positions = np.arange(n)
    for i, rec in enumerate(plotted):
        is_target = rec["lineage"] == target_lineage
        color = "#B22222" if is_target else get_lineage_color(rec["lineage"])
        # IQR bar
        ax.plot(
            [rec["p25_chronos"], rec["p75_chronos"]],
            [y_positions[i], y_positions[i]],
            color=color,
            linewidth=2.0 if is_target else 1.0,
            alpha=0.9,
            zorder=2,
        )
        # Median point
        ax.plot(
            rec["median_chronos"],
            y_positions[i],
            marker="D" if is_target else "o",
            markersize=7 if is_target else 5,
            color=color,
            markeredgecolor="white",
            markeredgewidth=0.8,
            zorder=3,
        )

    # Y-axis labels (lineage names with n)
    labels = [f"{rec['lineage']} (n={rec['n']})" for rec in plotted]
    # Bold the target lineage
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=8)
    for i, rec in enumerate(plotted):
        if rec["lineage"] == target_lineage:
            ax.get_yticklabels()[i].set_fontweight("bold")
            ax.get_yticklabels()[i].set_color("#B22222")

    # Reference lines (vertical, since lineages are on Y)
    ax.axvline(x=0, color="#999999", linestyle="-", linewidth=0.8, alpha=0.5, zorder=1)
    ax.axvline(x=-0.5, color="#666666", linestyle="--", linewidth=1.0, alpha=0.7, zorder=1)
    ax.axvline(x=CHRONOS_STRONG_DEPENDENCY, color="#B22222", linestyle="--", linewidth=1.5, alpha=0.9, zorder=1)

    ax.invert_yaxis()  # Most dependent at top
    ax.set_xlabel("Chronos score (more dependent ←)")
    ax.set_title(f"{target_symbol}: per-lineage dependency in {indication}")
    ax.grid(axis="x")
    fig.savefig(out_path / "figure_forest_plot.svg", bbox_inches="tight")
    plt.close(fig)


def emit_oncotree_forest_plot(
    per_oncotree_code_stats: list,
    target_lineage: str,
    target_symbol: str,
    indication: str,
    out_path: Path,
    contracts_root: Path,
    top_k_lineages: int = 15,
) -> Path | None:
    """Emit forest plot by OncotreeCode, grouped by lineage with right-side annotations.

    Groups codes by their parent lineage, draws horizontal separators between groups,
    and shows lineage summary (name, median, n) in a right-side annotation area.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    from collections import defaultdict

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    try:
        from takeda_palette import CHRONOS_STRONG_DEPENDENCY, get_lineage_color
    except ImportError:
        CHRONOS_STRONG_DEPENDENCY = -1.0
        get_lineage_color = lambda x: "#56B4E9"

    if not per_oncotree_code_stats:
        return None

    # Group codes by lineage
    lineage_codes = defaultdict(list)
    for rec in per_oncotree_code_stats:
        lineage_codes[rec["oncotree_lineage"]].append(rec)

    # Compute lineage-level stats
    lineage_stats = {}
    for lineage, codes in lineage_codes.items():
        total_n = sum(c["n"] for c in codes)
        if total_n > 0:
            weighted_med = sum(c["median_chronos"] * c["n"] for c in codes) / total_n
            lineage_stats[lineage] = {"median": weighted_med, "n": total_n}
        else:
            lineage_stats[lineage] = {"median": 0, "n": 0}

    # Sort lineages by their median (most dependent first), take top_k
    sorted_lineages = sorted(lineage_stats.keys(), key=lambda x: lineage_stats[x]["median"])[:top_k_lineages]

    # Build flat list of codes with their lineage info and compressed y-positions
    plot_items = []
    lineage_spans = []  # (start_y, end_y, lineage) for drawing group boxes
    y_positions = []

    row_spacing = 0.6  # Compressed spacing within groups
    group_gap = 0.7    # Extra gap between groups (includes separator line space)
    current_y = 0

    for lineage_idx, lineage in enumerate(sorted_lineages):
        codes = sorted(lineage_codes[lineage], key=lambda x: x["median_chronos"])

        # Add gap before group (except first)
        if lineage_idx > 0:
            current_y += group_gap

        start_y = current_y
        for i, rec in enumerate(codes):
            plot_items.append({
                "code": rec["oncotree_code"],
                "rec": rec,
                "lineage": lineage,
            })
            y_positions.append(current_y)
            if i < len(codes) - 1:
                current_y += row_spacing

        end_y = current_y
        lineage_spans.append((start_y, end_y, lineage))
        current_y += row_spacing  # Move to next position

    y_positions = np.array(y_positions)
    n = len(plot_items)
    fig_h = max(4.0, current_y * 0.22 + 1.2)
    fig, ax = plt.subplots(figsize=(6.5, fig_h))

    # Draw codes
    for i, item in enumerate(plot_items):
        rec = item["rec"]
        is_target = item["lineage"] == target_lineage
        color = "#B22222" if is_target else get_lineage_color(item["lineage"])

        # IQR bar
        ax.plot(
            [rec["p25_chronos"], rec["p75_chronos"]],
            [y_positions[i], y_positions[i]],
            color=color,
            linewidth=2.0 if is_target else 1.2,
            alpha=0.85,
            zorder=2,
        )
        # Median point
        ax.plot(
            rec["median_chronos"],
            y_positions[i],
            marker="o",
            markersize=6 if is_target else 4,
            color=color,
            markeredgecolor="white",
            markeredgewidth=0.6,
            zorder=3,
        )

    # Y-axis labels (code names with n)
    labels = [f"{item['code']} (n={item['rec']['n']})" for item in plot_items]
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=8)

    # Color target lineage labels
    for i, item in enumerate(plot_items):
        if item["lineage"] == target_lineage:
            ax.get_yticklabels()[i].set_color("#B22222")
            ax.get_yticklabels()[i].set_fontweight("bold")

    # Reference lines
    ax.axvline(x=0, color="#999999", linestyle="-", linewidth=0.8, alpha=0.5, zorder=1)
    ax.axvline(x=CHRONOS_STRONG_DEPENDENCY, color="#B22222", linestyle="--", linewidth=1.5, alpha=0.9, zorder=1)

    ax.invert_yaxis()
    ax.set_xlabel("Chronos score (more dependent = lower)")
    ax.set_title(f"{target_symbol}: dependency by cancer type ({indication} highlighted)", fontsize=10, pad=12)
    ax.grid(axis="x", alpha=0.3)

    # Get x-axis limits for positioning annotations
    x_min, x_max = ax.get_xlim()
    annot_x = x_max + 0.02 * (x_max - x_min)  # Position annotations closer to the right edge

    # Draw group separators and right-side lineage annotations
    for i, (start_y, end_y, lineage) in enumerate(lineage_spans):
        is_target = lineage == target_lineage
        color = "#B22222" if is_target else "#666666"
        stats = lineage_stats[lineage]

        # Draw horizontal separator line above group (except first)
        # Position at middle of gap for even spacing above and below
        if i > 0:
            prev_end_y = lineage_spans[i-1][1]
            sep_y = (prev_end_y + start_y) / 2
            ax.axhline(y=sep_y, color="#CCCCCC", linewidth=1.0, linestyle="-", zorder=0)

        # Lineage label: name and median
        y_mid = (start_y + end_y) / 2
        ax.text(annot_x, y_mid, f"{lineage} (med = {stats['median']:.2f})",
                fontsize=7.5, va="center", ha="left", color=color, clip_on=False)

    # Expand x-axis to make room for annotations (reduced padding)
    ax.set_xlim(x_min, x_max + 0.45 * (x_max - x_min))

    out_file = out_path / "figure_oncotree_forest_plot.svg"
    fig.savefig(out_file, bbox_inches="tight")
    plt.close(fig)
    return out_file


def emit_oncotree_faceted_bars(
    per_oncotree_code_stats: list,
    target_lineage: str,
    target_symbol: str,
    indication: str,
    out_path: Path,
    contracts_root: Path,
    top_k_lineages: int = 12,
) -> Path | None:
    """Emit faceted horizontal bar chart by lineage.

    One small panel per lineage, codes as horizontal bars within each.
    Lineages sorted by their median dependency.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    from collections import defaultdict

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    try:
        from takeda_palette import CHRONOS_STRONG_DEPENDENCY
    except ImportError:
        CHRONOS_STRONG_DEPENDENCY = -1.0

    if not per_oncotree_code_stats:
        return None

    # Group codes by lineage
    lineage_codes = defaultdict(list)
    for rec in per_oncotree_code_stats:
        lineage_codes[rec["oncotree_lineage"]].append(rec)

    # Compute lineage-level median
    lineage_medians = {}
    for lineage, codes in lineage_codes.items():
        total_n = sum(c["n"] for c in codes)
        if total_n > 0:
            weighted_med = sum(c["median_chronos"] * c["n"] for c in codes) / total_n
            lineage_medians[lineage] = weighted_med

    # Sort lineages and take top_k
    sorted_lineages = sorted(lineage_medians.keys(), key=lambda x: lineage_medians[x])[:top_k_lineages]

    # Determine grid layout
    n_lineages = len(sorted_lineages)
    n_cols = 3
    n_rows = (n_lineages + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_rows, n_cols, figsize=(10, 2.2 * n_rows), squeeze=False)

    # Find global x limits
    all_medians = [r["median_chronos"] for r in per_oncotree_code_stats]
    x_min = min(min(all_medians), CHRONOS_STRONG_DEPENDENCY) - 0.2
    x_max = max(all_medians) + 0.3

    for idx, lineage in enumerate(sorted_lineages):
        row, col = idx // n_cols, idx % n_cols
        ax = axes[row, col]

        codes = sorted(lineage_codes[lineage], key=lambda x: x["median_chronos"])
        is_target = lineage == target_lineage

        y_pos = np.arange(len(codes))
        medians = [c["median_chronos"] for c in codes]
        labels = [f"{c['oncotree_code']} (n={c['n']})" for c in codes]

        # Bar color
        color = "#B22222" if is_target else "#5a9bd4"

        ax.barh(y_pos, medians, color=color, alpha=0.8, height=0.7, zorder=2)

        # Reference lines
        ax.axvline(x=0, color="#999999", linestyle="-", linewidth=0.6, alpha=0.5, zorder=1)
        ax.axvline(x=CHRONOS_STRONG_DEPENDENCY, color="#B22222", linestyle="--", linewidth=1.0, alpha=0.7, zorder=1)

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=7)
        ax.set_xlim(x_min, x_max)
        ax.invert_yaxis()

        # Panel title
        lineage_n = sum(c["n"] for c in codes)
        title_color = "#B22222" if is_target else "#333333"
        ax.set_title(f"{lineage} (n={lineage_n})", fontsize=9, fontweight="bold", color=title_color)
        ax.grid(axis="x", alpha=0.3, linewidth=0.5)

    # Hide empty subplots
    for idx in range(n_lineages, n_rows * n_cols):
        row, col = idx // n_cols, idx % n_cols
        axes[row, col].axis("off")

    # Add common x-label
    fig.text(0.5, 0.02, "Median Chronos score (more dependent = lower)", ha="center", fontsize=10)
    fig.suptitle(f"{target_symbol}: dependency by cancer type ({indication} highlighted)", fontsize=11, y=0.98)

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])

    out_file = out_path / "figure_oncotree_faceted_bars.svg"
    fig.savefig(out_file, bbox_inches="tight")
    plt.close(fig)
    return out_file


def emit_oncotree_table_bars(
    per_oncotree_code_stats: list,
    target_lineage: str,
    target_symbol: str,
    indication: str,
    out_path: Path,
    contracts_root: Path,
    top_k_lineages: int = 15,
) -> Path | None:
    """Emit summary table with embedded inline bars.

    Table with columns: Lineage | Code | N | Median | [inline bar]
    Target lineage rows highlighted.
    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
    from collections import defaultdict

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    try:
        from takeda_palette import CHRONOS_STRONG_DEPENDENCY
    except ImportError:
        CHRONOS_STRONG_DEPENDENCY = -1.0

    if not per_oncotree_code_stats:
        return None

    # Group codes by lineage
    lineage_codes = defaultdict(list)
    for rec in per_oncotree_code_stats:
        lineage_codes[rec["oncotree_lineage"]].append(rec)

    # Compute lineage-level median
    lineage_medians = {}
    for lineage, codes in lineage_codes.items():
        total_n = sum(c["n"] for c in codes)
        if total_n > 0:
            weighted_med = sum(c["median_chronos"] * c["n"] for c in codes) / total_n
            lineage_medians[lineage] = weighted_med

    # Sort lineages and take top_k
    sorted_lineages = sorted(lineage_medians.keys(), key=lambda x: lineage_medians[x])[:top_k_lineages]

    # Build table data
    table_rows = []
    for lineage in sorted_lineages:
        codes = sorted(lineage_codes[lineage], key=lambda x: x["median_chronos"])
        is_target = lineage == target_lineage
        for i, rec in enumerate(codes):
            table_rows.append({
                "lineage": lineage if i == 0 else "",  # Only show lineage on first row
                "lineage_full": lineage,
                "code": rec["oncotree_code"],
                "n": rec["n"],
                "median": rec["median_chronos"],
                "is_target": is_target,
                "is_first": i == 0,
            })

    # Calculate figure size
    n_rows = len(table_rows)
    row_height = 0.3
    fig_height = max(4, n_rows * row_height + 1.5)
    fig_width = 9

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis("off")

    # Column positions (as fractions of width)
    col_x = [0.02, 0.22, 0.36, 0.44, 0.52]  # Lineage, Code, N, Median, Bar
    col_widths = [0.18, 0.12, 0.06, 0.08, 0.42]

    # Find bar scale
    all_medians = [r["median"] for r in table_rows]
    bar_min = min(min(all_medians), CHRONOS_STRONG_DEPENDENCY) - 0.1
    bar_max = max(0.2, max(all_medians) + 0.1)
    bar_range = bar_max - bar_min

    # Header
    header_y = 1 - 0.06
    headers = ["Lineage", "Code", "N", "Median", ""]
    for i, (x, header) in enumerate(zip(col_x, headers)):
        ax.text(x, header_y, header, fontsize=9, fontweight="bold", va="center",
                transform=ax.transAxes)

    # Draw header line
    ax.plot([0.01, 0.98], [header_y - 0.02, header_y - 0.02], color="#CCCCCC", linewidth=1,
            transform=ax.transAxes)

    # Data rows
    for idx, row in enumerate(table_rows):
        y = header_y - 0.06 - (idx * row_height / fig_height * 3)

        # Row background for target lineage
        if row["is_target"]:
            rect = mpatches.FancyBboxPatch(
                (0.01, y - 0.015), 0.97, 0.035,
                boxstyle="round,pad=0.002,rounding_size=0.01",
                facecolor="#FFEEEE", edgecolor="none",
                transform=ax.transAxes, zorder=0
            )
            ax.add_patch(rect)

        # Lineage separator line
        if row["is_first"] and idx > 0:
            ax.plot([0.01, 0.98], [y + 0.018, y + 0.018], color="#EEEEEE", linewidth=0.8,
                    transform=ax.transAxes)

        # Text color
        text_color = "#B22222" if row["is_target"] else "#333333"
        weight = "bold" if row["is_first"] else "normal"

        # Lineage
        ax.text(col_x[0], y, row["lineage"], fontsize=8, va="center",
                fontweight="bold" if row["lineage"] else "normal",
                color=text_color, transform=ax.transAxes)

        # Code
        ax.text(col_x[1], y, row["code"], fontsize=8, va="center",
                color=text_color, transform=ax.transAxes)

        # N
        ax.text(col_x[2], y, str(row["n"]), fontsize=8, va="center",
                color=text_color, transform=ax.transAxes)

        # Median
        ax.text(col_x[3], y, f"{row['median']:.2f}", fontsize=8, va="center",
                color=text_color, transform=ax.transAxes)

        # Inline bar
        bar_x_start = col_x[4]
        bar_width = col_widths[4]
        bar_height = 0.018

        # Zero line position
        zero_pos = bar_x_start + (0 - bar_min) / bar_range * bar_width

        # Draw bar from zero to median
        bar_color = "#B22222" if row["is_target"] else "#5a9bd4"
        median_pos = bar_x_start + (row["median"] - bar_min) / bar_range * bar_width

        if row["median"] < 0:
            bar_rect = mpatches.Rectangle(
                (median_pos, y - bar_height/2), zero_pos - median_pos, bar_height,
                facecolor=bar_color, alpha=0.8,
                transform=ax.transAxes, zorder=2
            )
        else:
            bar_rect = mpatches.Rectangle(
                (zero_pos, y - bar_height/2), median_pos - zero_pos, bar_height,
                facecolor=bar_color, alpha=0.8,
                transform=ax.transAxes, zorder=2
            )
        ax.add_patch(bar_rect)

        # Zero line (draw once per row area)
        ax.plot([zero_pos, zero_pos], [y - bar_height, y + bar_height],
                color="#999999", linewidth=0.5, transform=ax.transAxes, zorder=1)

    # Strong dependency reference line in bar area
    strong_dep_pos = col_x[4] + (CHRONOS_STRONG_DEPENDENCY - bar_min) / bar_range * col_widths[4]
    ax.plot([strong_dep_pos, strong_dep_pos], [0.02, header_y - 0.04], color="#B22222",
            linestyle="--", linewidth=1, alpha=0.5, transform=ax.transAxes)

    # Title
    ax.set_title(f"{target_symbol}: dependency by cancer type ({indication} highlighted)",
                 fontsize=11, pad=10, loc="left")

    out_file = out_path / "figure_oncotree_table_bars.svg"
    fig.savefig(out_file, bbox_inches="tight", dpi=150)
    plt.close(fig)
    return out_file


def emit_lineage_strip(
    merged_data: list, target_lineage: str, target_symbol: str, indication: str, out_path: Path, contracts_root: Path
) -> None:
    """Emit the lineage strip plot — per-lineage cell-line points."""
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    from oncology_target_contracts.plot_styles.takeda_palette import (  # type: ignore
        CHRONOS_STRONG_DEPENDENCY,
        FIGSIZE_DOUBLE_COLUMN,
    )

    df = pd.DataFrame(merged_data)
    if df.empty:
        fig, ax = plt.subplots(figsize=FIGSIZE_DOUBLE_COLUMN)
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        fig.savefig(out_path / "figure_lineage_strip.svg", bbox_inches="tight")
        plt.close(fig)
        return

    # Filter to lineages with >= 5 cell lines
    lineage_counts = df["lineage"].value_counts()
    keep_lineages = lineage_counts[lineage_counts >= 5].index.tolist()
    df = df[df["lineage"].isin(keep_lineages)]

    # Sort lineages by median ascending
    lineage_medians = df.groupby("lineage")["chronos"].median().sort_values()
    lineage_order = lineage_medians.index.tolist()[:20]  # top 20

    fig, ax = plt.subplots(figsize=(7.0, max(3.5, 0.2 * len(lineage_order) + 0.8)))

    for i, lineage in enumerate(lineage_order):
        subset = df[df["lineage"] == lineage]
        is_target = lineage == target_lineage
        color = "#B22222" if is_target else "#56B4E9"
        # Jitter y
        rng = np.random.default_rng(seed=hash(lineage) % (2**31))
        y_jitter = rng.uniform(-0.3, 0.3, size=len(subset))
        ax.scatter(
            subset["chronos"],
            np.full(len(subset), i) + y_jitter,
            s=12,
            c=color,
            alpha=0.6,
            edgecolor="white",
            linewidth=0.3,
        )
        # Median tick
        ax.plot(
            [lineage_medians[lineage]] * 2,
            [i - 0.4, i + 0.4],
            color="#222222" if not is_target else "#B22222",
            linewidth=1.5,
            zorder=3,
        )

    ax.set_yticks(np.arange(len(lineage_order)))
    labels = [f"{ln} (n={lineage_counts[ln]})" for ln in lineage_order]
    ax.set_yticklabels(labels, fontsize=8)
    for i, ln in enumerate(lineage_order):
        if ln == target_lineage:
            ax.get_yticklabels()[i].set_fontweight("bold")
            ax.get_yticklabels()[i].set_color("#B22222")

    ax.invert_yaxis()
    ax.axvline(x=0, color="#999999", linewidth=0.8, alpha=0.5, zorder=1)
    ax.axvline(x=-0.5, color="#666666", linestyle="--", linewidth=1.0, alpha=0.7, zorder=1)
    ax.axvline(x=CHRONOS_STRONG_DEPENDENCY, color="#B22222", linestyle="--", linewidth=1.5, zorder=1)

    ax.set_xlabel("Chronos score")
    ax.set_title(f"{target_symbol}: per-lineage Chronos distribution in {indication}")
    ax.grid(axis="x")
    fig.savefig(out_path / "figure_lineage_strip.svg", bbox_inches="tight")
    plt.close(fig)


# ============================================================================
# SUBTYPE-STRATIFIED DEPENDENCY STRIP PLOT
# ============================================================================
# S3 paths for DepMap subgroup assignments by indication
SUBTYPE_ASSIGNMENTS_S3 = {
    "COADREAD": "s3://onc-compbio/data-catalog/derived/subgroup-assignments/COADREAD/depmap/cms-classifier/2026-Q3/assignments.parquet",
    "NSCLC": "s3://onc-compbio/data-catalog/derived/subgroup-assignments/NSCLC/depmap/2026-Q3/assignments.parquet",
    "SCLC": "s3://onc-compbio/data-catalog/derived/subgroup-assignments/SCLC/depmap/classifier/2026-Q3/assignments.parquet",
    "PAAD": "s3://onc-compbio/data-catalog/derived/subgroup-assignments/PAAD/depmap/2026-Q3/assignments.parquet",
    "STAD": "s3://onc-compbio/data-catalog/derived/subgroup-assignments/STAD/depmap/2026-Q3/assignments.parquet",
    "ESCA": "s3://onc-compbio/data-catalog/derived/subgroup-assignments/ESCA/depmap/2026-Q3/assignments.parquet",
    "HNSC": "s3://onc-compbio/data-catalog/derived/subgroup-assignments/HNSC/depmap/2026-Q3/assignments.parquet",
}

# Signal colors for subtype dependency (Takeda red for dependent, gray for not)
_SUBTYPE_SIGNAL_COLORS = {
    "strong_dependency": ("#B22222", "#8B0000"),      # Takeda red — strong
    "moderate_dependency": ("#D46A6A", "#A04040"),    # lighter red — moderate
    "not_dependent": ("#c9ccd1", "#8a8d91"),          # gray — not dependent
    "insufficient": ("#e8e8e8", "#aaaaaa"),           # light gray — insufficient n
    None: ("#e8e8e8", "#aaaaaa"),
}


def load_subtype_assignments(indication: str) -> dict:
    """Load DepMap subtype assignments for an indication from S3.

    Returns dict mapping ModelID (sample_id) to stratum_id for members only.
    Returns empty dict if indication has no subtype catalog or load fails.
    """
    s3_uri = SUBTYPE_ASSIGNMENTS_S3.get(indication.upper())
    if not s3_uri:
        return {}

    try:
        import boto3
        import pandas as pd
        from io import BytesIO
        from urllib.parse import urlparse

        parsed = urlparse(s3_uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")

        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        df = pd.read_parquet(BytesIO(obj["Body"].read()))

        # Filter to members only
        members = df[df["is_member"] == True]
        return dict(zip(members["sample_id"], members["stratum_id"]))
    except Exception as e:
        print(f"[depmap_chronos] subtype assignments load failed for {indication}: {e}", file=sys.stderr)
        return {}


def emit_subtype_strip(
    chronos_by_model: dict,
    target_symbol: str,
    indication: str,
    out_path: Path,
    contracts_root: Path,
    strong_threshold: float = -1.0,
    moderate_threshold: float = -0.5,
) -> Path | None:
    """Emit subtype-stratified dependency strip plot if subtypes exist for indication.

    Shows Chronos score distribution per molecular subtype (e.g., CMS1-4 for COADREAD).
    Returns path to SVG or None if no subtypes available.
    """
    import matplotlib.pyplot as plt
    import numpy as np

    # Load subtype assignments
    subtype_map = load_subtype_assignments(indication)
    if not subtype_map:
        return None

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    try:
        from takeda_palette import CHRONOS_STRONG_DEPENDENCY
    except ImportError:
        CHRONOS_STRONG_DEPENDENCY = -1.0

    # Build per-subtype data
    subtype_data = {}
    for model_id, chronos in chronos_by_model.items():
        stratum = subtype_map.get(model_id)
        if stratum:
            subtype_data.setdefault(stratum, []).append(chronos)

    if not subtype_data:
        return None

    # Compute stats per subtype
    strata = []
    for stratum_id, values in subtype_data.items():
        arr = np.array(values)
        median = float(np.median(arr))
        n = len(arr)
        # Classify dependency signal
        if n < 3:
            signal = "insufficient"
        elif median <= strong_threshold:
            signal = "strong_dependency"
        elif median <= moderate_threshold:
            signal = "moderate_dependency"
        else:
            signal = "not_dependent"
        strata.append({
            "stratum_id": stratum_id,
            "values": values,
            "median": median,
            "n": n,
            "signal": signal,
        })

    # Sort by median (most dependent first)
    strata.sort(key=lambda s: s["median"])

    # Compute pooled median
    all_values = [v for s in strata for v in s["values"]]
    pooled_median = float(np.median(all_values))
    pooled_n = len(all_values)

    # Create figure with extra height for table
    fig, ax = plt.subplots(figsize=(7.6, max(4.0, 0.6 * len(strata) + 2.5)))

    groups = [s["values"] for s in strata]
    bp = ax.boxplot(
        groups,
        orientation="horizontal",
        widths=0.6,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "#222", "linewidth": 1.2},
    )

    rng = np.random.default_rng(seed=42)
    labels = []
    for i, s in enumerate(strata):
        fill, line = _SUBTYPE_SIGNAL_COLORS.get(s["signal"], _SUBTYPE_SIGNAL_COLORS[None])
        bp["boxes"][i].set(facecolor=fill, edgecolor=line, alpha=0.55, linewidth=1.0)
        # Jitter points
        yy = rng.uniform(i + 1 - 0.16, i + 1 + 0.16, size=len(s["values"]))
        ax.scatter(s["values"], yy, s=12, color=line, alpha=0.5, edgecolor="none", zorder=3)
        # Clean up stratum label (remove _depmap suffix if present)
        clean_label = s["stratum_id"].replace("_depmap", "")
        labels.append(clean_label)

    # Reference lines (0 and strong dependency threshold only)
    ax.axvline(0, color="#999999", linewidth=0.8, alpha=0.5, zorder=1)
    ax.axvline(CHRONOS_STRONG_DEPENDENCY, color="#B22222", linestyle="--", linewidth=1.5, alpha=0.9, zorder=1)

    # Pooled median reference line with text annotation at top of plot
    ax.axvline(pooled_median, color="#444", linewidth=1.0, linestyle=":", zorder=1)
    ax.text(pooled_median, len(strata) + 0.6, f"pooled median = {pooled_median:.2f}",
            color="#444", fontsize=7, ha="center", va="bottom")

    ax.set_yticks(range(1, len(labels) + 1))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Chronos score (more dependent = lower)")
    ax.set_title(f"{target_symbol} in {indication}: dependency by molecular subtype", pad=24)
    ax.grid(axis="x", alpha=0.25, linewidth=0.4)

    # Table with subtype medians - positioned below x-axis label
    col_labels = ["Subtype", "N", "Median Chronos", "Signal"]
    table_data = []
    for s in strata:
        clean_label = s["stratum_id"].replace("_depmap", "")
        sig_label = s["signal"].replace("_", " ")
        table_data.append([clean_label, str(s["n"]), f"{s['median']:.2f}", sig_label])
    # Add pooled row
    table_data.append(["Pooled", str(pooled_n), f"{pooled_median:.2f}", "—"])

    # Calculate table height based on number of rows
    n_rows = len(table_data) + 1  # +1 for header
    table_height = 0.045 * n_rows
    table = ax.table(
        cellText=table_data,
        colLabels=col_labels,
        loc="bottom",
        cellLoc="center",
        bbox=[0.0, -table_height - 0.18, 1.0, table_height],
        colWidths=[0.30, 0.15, 0.30, 0.25],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)

    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#CCCCCC")
        cell.set_linewidth(0.5)
        if row == 0:
            cell.set_text_props(fontweight="bold")
            cell.set_facecolor("#F0F0F0")
        elif row == len(table_data):  # Pooled row
            cell.set_facecolor("#F8F8F8")
            cell.set_text_props(fontweight="bold")
        else:
            cell.set_facecolor("white")

    fig.subplots_adjust(bottom=0.30)

    out_file = out_path / "figure_subtype_strip.svg"
    fig.savefig(out_file, bbox_inches="tight")
    plt.close(fig)
    return out_file


def emit_plotly_specs(
    per_lineage_records: list,
    target_lineage: str,
    target_symbol: str,
    indication: str,
    summary: dict,
    out_path: Path,
    contracts_root: Path,
) -> list:
    """Emit interactive Plotly spec SIBLING to the lineage forest SVG (Gate-C plotly debt, 2026-07-21).

    Interactive twin of emit_forest_plot: per-lineage median Chronos with a p25–p75 IQR bar, top-20
    most-dependent lineages, the target lineage highlighted (red diamond). Built from the SAME
    per_lineage_records the SVG + plot_data.parquet use (no drift). Reflines at 0 / -0.5 / -1.0
    (CHRONOS_STRONG_DEPENDENCY) mirror the SVG. Writes figure_forest_plot.plotly.json.
    Best-effort (Plotly optional → SVG guaranteed)."""
    try:
        import plotly.graph_objects as go
        from oncology_target_contracts.plot_styles.takeda_palette import (  # type: ignore
            CHRONOS_STRONG_DEPENDENCY,
            get_lineage_color,
        )
    except Exception as e:  # noqa: BLE001 — Plotly optional; never block the SVG artifact
        print(f"[depmap_chronos] plotly spec emission skipped: {e}", file=sys.stderr)
        return []
    if not per_lineage_records:
        return []

    written = []
    try:
        # top-20 most-dependent (records are pre-sorted ascending by median_chronos); reverse so the
        # MOST dependent sits at the TOP of the horizontal plot (mirrors the SVG's invert_yaxis).
        plotted = list(per_lineage_records[:20])[::-1]
        ys = list(range(len(plotted)))
        labels = [f"{r['lineage']} (n={r['n']})" for r in plotted]
        medians = [r["median_chronos"] for r in plotted]
        colors = ["#B22222" if r["lineage"] == target_lineage else get_lineage_color(r["lineage"]) for r in plotted]
        fig = go.Figure()
        # IQR bars as per-row line traces (one shape per lineage keeps hover on the median marker).
        for i, r in enumerate(plotted):
            fig.add_trace(
                go.Scatter(
                    x=[r["p25_chronos"], r["p75_chronos"]],
                    y=[i, i],
                    mode="lines",
                    line=dict(color=colors[i], width=3 if r["lineage"] == target_lineage else 1.5),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )
        fig.add_trace(
            go.Scatter(
                x=medians,
                y=ys,
                mode="markers",
                marker=dict(
                    color=colors,
                    size=[11 if r["lineage"] == target_lineage else 7 for r in plotted],
                    symbol=["diamond" if r["lineage"] == target_lineage else "circle" for r in plotted],
                    line=dict(width=0.8, color="white"),
                ),
                customdata=list(zip([r["lineage"] for r in plotted], [r["n"] for r in plotted])),
                hovertemplate="%{customdata[0]} (n=%{customdata[1]})<br>median Chronos %{x:.2f}<extra></extra>",
                showlegend=False,
            )
        )
        for xv, col, dash in [
            (0.0, "#999999", "solid"),
            (-0.5, "#666666", "dash"),
            (CHRONOS_STRONG_DEPENDENCY, "#B22222", "dash"),
        ]:
            fig.add_vline(x=xv, line=dict(color=col, dash=dash, width=1.5))
        fig.update_layout(
            title=f"{target_symbol}: per-lineage dependency in {indication}",
            xaxis_title="Chronos score (more dependent ←)",
            yaxis=dict(tickmode="array", tickvals=ys, ticktext=labels),
            template="plotly_white",
            margin=dict(l=140, r=20, t=50, b=50),
        )
        (out_path / "figure_forest_plot.plotly.json").write_text(fig.to_json())
        written.append({"id": "forest_plot", "path": "figure_forest_plot.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[depmap_chronos] forest plotly skipped: {e}", file=sys.stderr)

    return written


def emit_plot_data(
    chronos_by_model: dict, model_metadata: dict, target_lineage: str, strong_threshold: float, out_path: Path
) -> list:
    """Emit plot_data.parquet — one row per cell line. Returns the merged data
    for use by the strip-plot emitter."""
    import pandas as pd

    rows = []
    for mid, c in chronos_by_model.items():
        meta = model_metadata.get(mid, {})
        lineage = meta.get("OncotreeLineage") or meta.get("lineage") or "unknown"
        rows.append(
            {
                "cell_line_id": mid,
                "cell_line_name": meta.get("CellLineName", mid),
                "chronos_score": float(c),
                "lineage": str(lineage),
                # Sublineage code — the substrate the offline per-OncotreeCode forest needs
                # (without it render_from_plot_data recomputes empty per_oncotree_code_stats).
                "oncotree_code": str(meta.get("OncotreeCode") or "unknown"),
                "is_target_lineage": bool(lineage == target_lineage),
                "is_strongly_dependent": bool(c <= strong_threshold),
                # Alias used by the strip plotter
                "chronos": float(c),
            }
        )

    df = pd.DataFrame(rows)
    df.to_parquet(out_path / "plot_data.parquet", index=False)
    return rows


def emit_manifest(
    target: str,
    indication: str,
    release_pin: str,
    summary: dict,
    chronos_by_model: dict,
    out_path: Path,
    load_errors: list,
) -> None:
    """Write provenance manifest. `indication` is recorded for run-context (which
    dashboard invocation produced this artifact) but the method's data product is
    target-only — same artifact serves all indications."""
    import yaml

    manifest = {
        "method": "depmap-chronos",
        "method_version": METHOD_VERSION,
        "target": target,
        "indication": indication,  # run-context, not data-product binding
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_manifest": "depmap-consortium-26q3",
        "input_files_consumed": ["CRISPRGeneEffect.csv", "Model.csv"],
        "n_cell_lines_panel": summary.get("n_cell_lines_panel"),
        "n_lineages_evaluated": summary.get("n_lineages_evaluated"),
        "n_enriched_lineages": summary.get("n_enriched_lineages"),
        "enrichment_class": summary.get("enrichment_class"),
        "load_errors": load_errors,
    }
    with (out_path / "manifest.yaml").open("w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)


@click.command()
@click.option("--target", required=True)
@click.option(
    "--indication", required=True, type=click.Choice(sorted(INDICATION_LINEAGE))
)  # validated against the canonical map — no silent unmapped fallback
@click.option("--release-pin", default="26q3")
@click.option("--strong-dependency-threshold", type=float, default=-1.0)
@click.option("--catalog-repo", type=click.Path(file_okay=False, path_type=Path), default=DEFAULT_CATALOG_REPO)
@click.option("--contracts-root", type=click.Path(file_okay=False, path_type=Path), default=DEFAULT_TARGET_CONTRACTS)
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--dry-run", is_flag=True)
def main(
    target, indication, release_pin, strong_dependency_threshold, catalog_repo, contracts_root, out, dry_run
) -> int:
    """Lineage-specific dependency analysis for (target, indication)."""
    out.mkdir(parents=True, exist_ok=True)
    click.echo("=== depmap-chronos (lineage-selectivity) ===")
    click.echo(f"  target:      {target}")
    click.echo(f"  indication:  {indication}")
    click.echo(f"  release_pin: {release_pin}")
    click.echo(f"  out:         {out}")
    if dry_run:
        click.echo("(--dry-run: skipping)")
        return 0

    chronos_by_model, model_metadata, load_errors = load_depmap_files(release_pin, target)
    if load_errors:
        click.echo(f"  LOAD ERRORS: {len(load_errors)}", err=True)
        with (out / "summary.json").open("w") as f:
            json.dump(
                {"_live_read_error": True, "errors": load_errors, "target": target, "indication": indication},
                f,
                indent=2,
            )
        emit_manifest(target, indication, release_pin, {}, {}, out, load_errors)
        return 2

    summary = compute_lineage_summary(
        chronos_by_model,
        model_metadata,
        indication,
        strong_threshold=strong_dependency_threshold,
    )
    # Resolve target_lineage from the indication → lineage map (figure emitters need
    # it for indication-context highlighting). The method's data product is
    # target-only; this is a render-time concern.
    target_lineage = INDICATION_LINEAGE.get((indication or "").upper().strip(), "")

    with (out / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2, default=str)

    merged_data = emit_plot_data(
        chronos_by_model,
        model_metadata,
        target_lineage,
        strong_dependency_threshold,
        out,
    )

    emit_forest_plot(
        summary.get("_per_lineage_records", []),
        target_lineage,
        target,
        indication,
        summary,
        out,
        contracts_root,
    )
    emit_lineage_strip(merged_data, target_lineage, target, indication, out, contracts_root)
    emit_manifest(target, indication, release_pin, summary, chronos_by_model, out, load_errors)

    click.echo(f"  → summary.json:   {out / 'summary.json'}")
    click.echo(f"  → forest_plot:    {out / 'figure_forest_plot.svg'}")
    click.echo(f"  → lineage_strip:  {out / 'figure_lineage_strip.svg'}")
    click.echo(f"  → plot_data:      {out / 'plot_data.parquet'}")
    click.echo(f"  → manifest:       {out / 'manifest.yaml'}")
    click.echo(
        f"  enrichment_class: {summary.get('enrichment_class')}"
        f"  ({summary.get('n_enriched_lineages', 0)} enriched lineages "
        f"of {summary.get('n_lineages_evaluated', 0)} evaluated)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
