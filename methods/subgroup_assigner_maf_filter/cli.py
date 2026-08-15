#!/usr/bin/env python3
"""subgroup_assigner_maf_filter CLI — generate per-sample subgroup assignments
from MAF (mutation annotation format) predicates.

Invocation:
    subgroup-assigner-maf-filter \
      --subgroup-catalog /path/to/coadread-subgroups-2026-q2.yaml \
      --data-source tcga \
      --release-pin 2026-Q2 \
      --catalog-repo /path/to/data-catalog \
      --out /path/to/output-dir/

The CLI:
  1. Loads the subgroup_catalog YAML; filters to atomic_strata with
     derivation_source == maf_filter_per_rule.
  2. Resolves the MAF manifest per data-source
     (gdc-pancohort-somatic-dr45-0 for TCGA; OmicsSomaticMutations.csv for DepMap).
  3. For each stratum: applies the AND/OR/negation predicate against MAF rows;
     aggregates to sample-level (any-hit-per-sample); emits tri-valued
     is_member per resolver-product design.
  4. Emits assignments.parquet + manifest.yaml conforming to
     subgroup_assignment.schema.json.

Iter-1b implementation — Phase 2a.2 of iDAS Subtype Pipeline. See
target-contracts docs/design/SAMPLE_ANNOTATION_PLAN.md for Modality B design.
"""

from __future__ import annotations
import os

import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import pandas as pd
import yaml

from methods.subgroup_common.manifest import emit_assignment_manifest
from methods.subgroup_common.paths import cache_root


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.2.0"  # Phase 2a.2 — first executable version

SUPPORTED_DERIVATION_SOURCES = {"maf_filter_per_rule"}


# ---------- MAF-predicate parser -------------------------------------------
#
# MAF rules in the 8 Phase-1 catalogs come in these forms (from grep):
#
#   `gene_symbol == 'X' && protein_change == 'p.YnnnZ'`        # exact hotspot
#   `gene_symbol == 'X' && protein_change in ['p.Y', ...]`     # any-of hotspots
#   `gene_symbol == 'X' && effect == 'in_frame_deletion' && exon == 19`
#   `gene_symbol == 'X' && effect in ['nonsense', 'frameshift', ...]`
#   `!(gene_symbol == 'KRAS' && protein_change in [...])`       # KRAS-WT (negation)
#   `sample.tmb >= 10`                                           # TMB threshold
#   `fusion_gene == 'ALK'`                                       # fusion (Modality A, but sometimes B)
#   `copy_number.ERBB2 == 'amplified'`                           # copy-number (Modality A)
#
# The parser produces a callable predicate: (row) → bool | None.
# Predicate returns None when a required field is NaN (tri-value:
# insufficient upstream).

_ATOMIC_EQ = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*==\s*'([^']*)'$")
_ATOMIC_IN = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s+in\s+\[([^\]]+)\]$")
_ATOMIC_INT_EQ = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*==\s*(\d+)$")
_ATOMIC_GTE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*>=\s*(\d+\.?\d*)$")
_ATOMIC_LTE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*<=\s*(\d+\.?\d*)$")


def _extract_column_name(lhs: str) -> str:
    """Strip a `namespace.field` prefix down to `field` for DataFrame lookup."""
    if "." in lhs:
        return lhs.split(".", 1)[1]
    return lhs


def _atomic_predicate(atom: str):
    """Return a row-level callable for a single atomic predicate.

    The callable returns True/False/None (None = source-value NaN → insufficient).
    """
    atom = atom.strip()
    m = _ATOMIC_EQ.match(atom)
    if m:
        col = _extract_column_name(m.group(1))
        target = m.group(2)
        def _pred(row):
            v = row.get(col)
            if pd.isna(v):
                return None
            return v == target
        return _pred
    m = _ATOMIC_IN.match(atom)
    if m:
        col = _extract_column_name(m.group(1))
        values = [v.strip().strip("'\"") for v in m.group(2).split(",")]
        def _pred(row):
            v = row.get(col)
            if pd.isna(v):
                return None
            return v in values
        return _pred
    m = _ATOMIC_INT_EQ.match(atom)
    if m:
        col = _extract_column_name(m.group(1))
        target = int(m.group(2))
        def _pred(row):
            v = row.get(col)
            if pd.isna(v):
                return None
            try:
                return int(v) == target
            except (ValueError, TypeError):
                return False
        return _pred
    m = _ATOMIC_GTE.match(atom)
    if m:
        col = _extract_column_name(m.group(1))
        target = float(m.group(2))
        def _pred(row):
            v = row.get(col)
            if pd.isna(v):
                return None
            try:
                return float(v) >= target
            except (ValueError, TypeError):
                return False
        return _pred
    raise ValueError(f"Unsupported atomic predicate: {atom!r}")


def _split_top_level(expr: str, sep: str) -> list[str]:
    """Split `expr` on `sep` at bracket-depth 0."""
    parts, depth, cur = [], 0, []
    i = 0
    while i < len(expr):
        c = expr[i]
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
        elif depth == 0 and expr[i:i+len(sep)] == sep:
            parts.append("".join(cur).strip())
            cur = []
            i += len(sep)
            continue
        cur.append(c)
        i += 1
    parts.append("".join(cur).strip())
    return parts


def compile_rule(rule: str):
    """Compile a MAF-filter rule string into a row-level callable predicate.

    Returns a function (row) → bool | None. None represents "evaluated but
    a required source field is NaN" — the resolver-product null semantic.
    """
    rule = rule.strip()

    # Negation wrapper: `!(...)`
    if rule.startswith("!(") and rule.endswith(")"):
        inner = compile_rule(rule[2:-1])
        def _neg(row):
            r = inner(row)
            return None if r is None else (not r)
        return _neg

    # Conjunction: `a && b && c`
    if "&&" in rule and not (rule.startswith("(") and rule.endswith(")")):
        parts = _split_top_level(rule, "&&")
        if len(parts) > 1:
            compiled = [compile_rule(p) for p in parts]
            def _conj(row):
                for p in compiled:
                    r = p(row)
                    if r is None:
                        return None
                    if not r:
                        return False
                return True
            return _conj

    # Disjunction: `a || b`
    if "||" in rule:
        parts = _split_top_level(rule, "||")
        if len(parts) > 1:
            compiled = [compile_rule(p) for p in parts]
            def _disj(row):
                any_none = False
                for p in compiled:
                    r = p(row)
                    if r is None:
                        any_none = True
                        continue
                    if r:
                        return True
                return None if any_none else False
            return _disj

    # Fallback: atomic predicate
    return _atomic_predicate(rule)


# ---------- Source-data loaders --------------------------------------------

def _load_tcga_maf(catalog_repo: Path, indication: str) -> pd.DataFrame:
    """Load TCGA MAF for the indication.

    Returns DataFrame with normalized columns: Tumor_Sample_Barcode
    (aliquot) mapped to sample_id (truncated to sample level), plus
    gene_symbol, protein_change, effect, exon (from Consequence/HGVSp fields),
    Variant_Classification.

    Iter-1b: reads from cache fallback pending Phase 2a.4's canonical loader.
    Expected canonical source: s3://onc-compbio/data-catalog/sources/gdc-pancohort-somatic/dr45-0/
    """
    fallback = cache_root() / "framework-gdc-pancohort-somatic" / f"{indication.lower()}-mc3.parquet"
    if fallback.exists():
        return pd.read_parquet(fallback)
    csv_fallback = fallback.with_suffix(".csv")
    if csv_fallback.exists():
        return pd.read_csv(csv_fallback)
    raise FileNotFoundError(
        f"TCGA MAF for {indication} not found at {fallback} or {csv_fallback}. "
        f"Phase 2a.4 provides the canonical loader with S3-plus-local-cache. "
        f"For immediate execution: place a MAF-shaped parquet/csv with columns "
        f"(Tumor_Sample_Barcode, gene_symbol, protein_change, effect, exon, ...) "
        f"at the fallback path."
    )


def _load_genie_maf(catalog_repo: Path, indication: str) -> pd.DataFrame:
    """Load GENIE public v19-0 MAF pre-filtered to indication-relevant samples.

    Returns DataFrame with columns already normalized to resolver-product
    convention: sample_id (GENIE-{CENTER}-{PATIENT}-{SAMPLE}), gene_symbol,
    protein_change, effect, plus source_native_id (= sample_id since GENIE
    doesn't have a distinct aliquot-level ID).

    GENIE public v19 covers ~271K samples across ~30 sequencing centers; per
    indication the pre-filter step (via data_clinical_sample.txt CANCER_TYPE)
    reduces this substantially (e.g. Colorectal Cancer = 23,312 samples,
    22,642 with MAF rows). This method reads the pre-filtered per-indication
    parquet from cache; a Phase-2b/c prefetch step is responsible for pulling
    the 1.12 GB MAF from S3 + slicing to the indication.

    Iter-1b: reads from cache fallback pending Phase 2a.4's canonical loader.
    Expected canonical source: s3://onc-compbio/data-catalog/sources/synapse/
    genie-public-v19-0/data_mutations_extended.txt (1.12 GB) filtered via
    data_clinical_sample.txt to the target indication's CANCER_TYPE.
    """
    fallback = cache_root() / "framework-genie-public-v19" / f"{indication.lower()}-genie-maf.parquet"
    if fallback.exists():
        return pd.read_parquet(fallback)
    raise FileNotFoundError(
        f"GENIE MAF for {indication} not found at {fallback}. "
        f"For immediate execution: pull s3://onc-compbio/data-catalog/sources/"
        f"synapse/genie-public-v19-0/data_mutations_extended.txt (1.12 GB) + "
        f"data_clinical_sample.txt, filter to CANCER_TYPE == '{indication} '"
        f"target, save as {fallback}."
    )


def _load_depmap_somatic_mutations(catalog_repo: Path, indication: str | None = None) -> pd.DataFrame:
    """Load DepMap somatic mutations, normalized to MAF-like shape.

    Prefers the per-indication prefetched parquet produced by
    scripts/prefetch_source_maf.py --source depmap_somatic (already
    lineage-filtered + column-normalized: sample_id / gene_symbol /
    protein_change / effect). Falls back to the raw
    OmicsSomaticMutations.csv only if the prefetched parquet is absent.

    DepMap MAF uses Hugo_Symbol / Protein_Change / Variant_Classification /
    ModelID; the prefetch step already renames these to the resolver
    convention. DepMap Protein_Change is in `p.G12C` HGVS form — identical
    to the catalog rule syntax, no value normalization needed.
    """
    # Prefer prefetched, lineage-filtered, column-normalized parquet
    if indication:
        prefetched = (cache_root() / "framework-depmap-26q1"
                      / f"{indication.lower()}-depmap-maf.parquet")
        if prefetched.exists():
            return pd.read_parquet(prefetched)

    fallback = cache_root() / "framework-depmap-26q1" / "OmicsSomaticMutations.csv"
    if fallback.exists():
        df = pd.read_csv(fallback)
        # Raw CSV needs column normalization (prefetch parquet already has it)
        rename = {"Hugo_Symbol": "gene_symbol", "Protein_Change": "protein_change",
                  "Variant_Classification": "effect", "ModelID": "sample_id"}
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        if "sample_id" in df.columns:
            df["source_native_id"] = df["sample_id"]
        return df
    raise FileNotFoundError(
        f"No DepMap somatic MAF found for {indication}. Run "
        f"scripts/prefetch_source_maf.py --source depmap_somatic "
        f"--indication {indication or '<IND>'} to produce the prefetched parquet, "
        f"or place OmicsSomaticMutations.csv at {fallback}."
    )


def _cohort_samples_path(data_source: str, indication: str) -> Path | None:
    """Companion FULL-cohort sample list produced alongside the prefetched MAF.

    The prefetch step (scripts/prefetch_source_maf.py) computes the indication cohort
    (`keep_samples` from data_clinical_sample.txt CANCER_TYPE / lineage) but historically
    wrote only the mutation-bearing MAF rows. When it ALSO emits this companion parquet
    (a `sample_id` column, optionally source_native_id / patient_id for the full cohort
    INCLUDING fully-WT tumors), we use it as the WT/negation-stratum denominator. Convention:
    `{indication}-cohort-samples.parquet` in the same cache dir as the MAF."""
    dir_slug = {"tcga": "framework-gdc-pancohort-somatic",
                "genie": "framework-genie-public-v19",
                "depmap": "framework-depmap-26q1"}.get(data_source)
    if not dir_slug:
        return None
    p = cache_root() / dir_slug / f"{indication.lower()}-cohort-samples.parquet"
    return p if p.exists() else None


def _load_cohort_samples(data_source: str, indication: str, sample_id_col: str,
                         native_id_col: str, patient_id_col: str | None):
    """Full-cohort sample frame (INCLUDING zero-mutation tumors) from the companion file, or None.

    Returns a DataFrame with [sample_id_col, native_id_col, (patient_id_col)] deduped on
    sample_id_col, normalizing whatever id columns the companion file carries. None when the
    companion file is absent (caller then falls back to MAF-present samples + a WARNING)."""
    path = _cohort_samples_path(data_source, indication)
    if path is None:
        return None
    df = pd.read_parquet(path)
    # normalize to the id columns the stratum evaluator expects.
    if sample_id_col not in df.columns:
        for alt in ("sample_id", "SAMPLE_ID", "ModelID", "Tumor_Sample_Barcode"):
            if alt in df.columns:
                df = df.rename(columns={alt: sample_id_col})
                break
    if sample_id_col not in df.columns:
        return None  # companion file lacks a usable sample id — ignore it (fall back + WARN)
    if native_id_col not in df.columns:
        df[native_id_col] = df[sample_id_col]
    cols = [sample_id_col, native_id_col]
    if patient_id_col:
        if patient_id_col not in df.columns:
            df[patient_id_col] = None
        cols = [sample_id_col, patient_id_col, native_id_col]
    return df[cols].drop_duplicates(subset=[sample_id_col])


# ---------- Stratum evaluation ---------------------------------------------

def _evaluate_stratum_maf(
    stratum: dict,
    maf_df: pd.DataFrame,
    sample_id_col: str,
    patient_id_col: str | None,
    native_id_col: str,
    all_samples: pd.DataFrame,
) -> pd.DataFrame:
    """Evaluate a single MAF-filter stratum.

    A stratum is defined by a row-level predicate on MAF rows. A sample is
    a MEMBER if it has ANY MAF row matching the predicate. The tri-valued
    semantics require thinking at two levels:

    - per-MAF-row: predicate returns None if a required source field is NaN
      → don't count as a hit, but flag the sample as "evaluation had gaps"
    - per-sample: sample is a member iff ≥1 row-level True; not-a-member
      iff all rows are False (no data-gaps); insufficient iff no True and
      any None (or if sample isn't in MAF at all — see all_samples)

    Simplification for iter-1: MAF-derived strata use `is_member=false` for
    samples with no MAF hits + no missing fields. `is_member=null` for
    samples missing from the MAF entirely (not evaluated in cohort). Rows
    with mixed False/None on required fields → False (any-hit wins).

    SAMPLE-LEVEL NEGATION (`!(...)`): a wild-type stratum like KRAS-WT means the
    SAMPLE carries no matching mutation — NOT that some row fails to match. A
    row-level `!(...)` predicate is True for every non-KRAS row (a TP53 row is
    "not a KRAS hotspot"), so any-hit aggregation would mark every mutated sample
    a member. We instead detect the top-level negation, evaluate the INNER
    predicate, and take the sample-level complement: member iff the sample has
    ZERO inner-hit rows (across the assayed cohort).
    """
    rule = stratum["rule"].strip()
    is_sample_negation = rule.startswith("!(") and rule.endswith(")")
    predicate = compile_rule(rule[2:-1]) if is_sample_negation else compile_rule(rule)

    # Apply the (possibly inner) per-MAF-row predicate; collect ≥1-True samples.
    maf_df = maf_df.copy()
    maf_df["_hit"] = maf_df.apply(predicate, axis=1)

    hits = maf_df[maf_df["_hit"] == True]
    hit_samples = hits.groupby(sample_id_col).agg(
        _first_native=(native_id_col, "first"),
        _first_hit=("protein_change", "first") if "protein_change" in maf_df.columns else (sample_id_col, "first"),
    ).reset_index() if len(hits) > 0 else pd.DataFrame(columns=[sample_id_col, "_first_native", "_first_hit"])

    # For every sample in `all_samples`, produce an assignment row
    out_rows = []
    hit_set = set(hit_samples[sample_id_col]) if len(hit_samples) > 0 else set()
    hit_lookup = hit_samples.set_index(sample_id_col).to_dict("index") if len(hit_samples) > 0 else {}

    for _, sample_row in all_samples.iterrows():
        sid = sample_row[sample_id_col]
        pid = sample_row.get(patient_id_col) if patient_id_col else None
        native = sample_row[native_id_col]
        has_inner_hit = sid in hit_set
        # Sample-level negation inverts membership: WT = no inner-hit.
        is_member = (not has_inner_hit) if is_sample_negation else has_inner_hit
        # derivation_value only carries the matched variant for positive (hit)
        # strata; a WT member has no matching variant to report.
        deriv_value = hit_lookup.get(sid, {}).get("_first_hit", "") if (is_member and not is_sample_negation) else ""
        out_rows.append({
            "sample_id": sid,
            "patient_id": pid,
            "source_native_id": native,
            "stratum_id": stratum["id"],
            "is_member": is_member,
            "derivation_source": stratum["derivation_source"],
            "derivation_value": deriv_value,
        })
    return pd.DataFrame(out_rows)


# ---------- Output emission ------------------------------------------------

# The schema-valid subgroup_assignment_product manifest is emitted via the
# shared subgroup_common.manifest.emit_assignment_manifest. The maf_filter
# product uses variant="maf" so its product id doesn't collide with the
# directly_tagged product on the same (source × indication).


# ---------- CLI ------------------------------------------------------------

@click.command()
@click.option("--subgroup-catalog", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to the subgroup_catalog YAML.")
@click.option("--data-source", required=True, type=click.Choice(["tcga", "depmap", "genie"]),
              help="Which data source's MAF to assign against.")
@click.option("--release-pin", required=True, help="Catalog release_pin identifier (e.g., 2026-Q2).")
@click.option("--catalog-repo", type=click.Path(file_okay=False, path_type=Path),
              default=Path(os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")),
              help="Path to the data-catalog repo for input-manifest resolution.")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Output directory; assignments.parquet + manifest.yaml land here.")
@click.option("--dry-run", is_flag=True,
              help="Parse the catalog, print the plan, do not produce assignments.")
def main(subgroup_catalog: Path, data_source: str, release_pin: str,
         catalog_repo: Path, out: Path, dry_run: bool) -> int:
    """Generate per-sample subgroup assignments from MAF-filter predicates."""
    with subgroup_catalog.open() as f:
        catalog = yaml.safe_load(f)

    indication = catalog.get("indication")
    catalog_id = catalog.get("id")
    atomic = catalog.get("atomic_strata", [])

    applicable = []
    for s in atomic:
        if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES:
            continue
        applicable_sources = s.get("applicable_data_sources", [])
        if data_source not in applicable_sources:
            continue
        applicable.append(s)

    click.echo(f"=== subgroup_assigner_maf_filter v{METHOD_VERSION} ===")
    click.echo(f"  catalog:       {catalog_id} (indication={indication})")
    click.echo(f"  data_source:   {data_source}")
    click.echo(f"  release_pin:   {release_pin}")
    click.echo(f"  out:           {out}")
    click.echo(f"  applicable MAF-filter strata ({len(applicable)} of {len(atomic)}):")
    for s in applicable:
        rule = s.get("rule", "")
        m = re.search(r"gene_symbol\s*==\s*['\"]([A-Z0-9]+)['\"]", rule)
        gene_hint = f"  [gene={m.group(1)}]" if m else ""
        click.echo(f"    - {s['id']:<20}{gene_hint}")
        click.echo(f"      rule: {rule}")

    skipped = [s["id"] for s in atomic if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES]
    if skipped:
        click.echo(f"  skipped strata (non-MAF derivation): {skipped}")
        click.echo(f"  → dispatch to subgroup_assigner_directly_tagged or subgroup_assigner_classifier")

    if not applicable:
        click.echo(f"WARNING: no applicable MAF-filter strata for data_source={data_source}", err=True)
        return 0

    if dry_run:
        click.echo("(--dry-run: skipping actual assignment generation)")
        return 0

    # ============ Load MAF + cohort samples ============
    if data_source == "tcga":
        maf = _load_tcga_maf(catalog_repo, indication)
        sample_id_col = "sample_id"
        patient_id_col = "patient_id"
        native_id_col = "source_native_id"
    elif data_source == "genie":
        maf = _load_genie_maf(catalog_repo, indication)
        sample_id_col = "sample_id"       # already normalized in the prefetch step
        patient_id_col = None             # GENIE has PATIENT_ID but is not carried in the CRC-scoped subset
        native_id_col = "source_native_id"
    else:
        maf = _load_depmap_somatic_mutations(catalog_repo, indication)
        # Prefetched parquet normalizes to sample_id/source_native_id; the raw-CSV
        # fallback also renames ModelID→sample_id. Prefer sample_id when present.
        sample_id_col = "sample_id" if "sample_id" in maf.columns else "ModelID"
        patient_id_col = None
        native_id_col = "source_native_id" if "source_native_id" in maf.columns else sample_id_col

    click.echo(f"  loaded {len(maf):,} MAF rows")

    # Derive the cohort (all_samples) — the WT/negation-stratum DENOMINATOR. Prefer the FULL cohort
    # (companion cohort-samples file, which includes fully-WT tumors); else fall back to MAF-present
    # samples. The MAF-only denominator UNDER-COUNTS WT strata: a tumor with zero MAF rows (fully WT
    # for every gene in the panel) is absent from the MAF entirely, so it never contributes a WT-side
    # row — inflating mutant fractions in the verdict-inert panorama/subtype rules.
    cohort = _load_cohort_samples(data_source, indication, sample_id_col, native_id_col, patient_id_col)
    if cohort is not None:
        # union with any MAF-present samples not in the cohort file (belt-and-suspenders), so a
        # mutated sample is never dropped from the denominator.
        if patient_id_col and patient_id_col in maf.columns:
            maf_samples = maf[[sample_id_col, patient_id_col, native_id_col]].drop_duplicates(subset=[sample_id_col])
        else:
            maf_samples = maf[[sample_id_col, native_id_col]].drop_duplicates(subset=[sample_id_col])
            if patient_id_col:
                maf_samples[patient_id_col] = None
        extra = maf_samples[~maf_samples[sample_id_col].isin(set(cohort[sample_id_col]))]
        all_samples = pd.concat([cohort, extra], ignore_index=True).drop_duplicates(subset=[sample_id_col])
        click.echo(f"  cohort samples: {len(all_samples):,} (full cohort incl. WT tumors)")
    else:
        if patient_id_col and patient_id_col in maf.columns:
            all_samples = maf[[sample_id_col, patient_id_col, native_id_col]].drop_duplicates(subset=[sample_id_col])
        else:
            all_samples = maf[[sample_id_col, native_id_col]].drop_duplicates(subset=[sample_id_col])
            if patient_id_col:
                all_samples[patient_id_col] = None
        click.echo(f"  cohort samples: {len(all_samples):,}")
        click.echo(
            "  WARNING: cohort denominator drawn from MAF-PRESENT samples only (no companion "
            f"{indication.lower()}-cohort-samples.parquet found). Fully-WT tumors (zero MAF rows) are "
            "under-counted in WT/negation strata → mutant fractions may be inflated. Emit the "
            "companion cohort-samples file from the prefetch step for an exact denominator.",
            err=True)

    # ============ Evaluate strata ============
    per_stratum_dfs = []
    for stratum in applicable:
        try:
            rows = _evaluate_stratum_maf(stratum, maf, sample_id_col, patient_id_col, native_id_col, all_samples)
        except ValueError as e:
            click.echo(f"  SKIP {stratum['id']}: {e}", err=True)
            continue
        per_stratum_dfs.append(rows)
        n_hit = int((rows["is_member"] == True).sum())
        n_neg = int((rows["is_member"] == False).sum())
        click.echo(f"    {stratum['id']:<25} is_member=true: {n_hit:>5}, false: {n_neg:>5}")

    if not per_stratum_dfs:
        click.echo("ERROR: no strata produced rows", err=True)
        return 1

    assignments = pd.concat(per_stratum_dfs, ignore_index=True)
    assignments["evaluated_at_release"] = release_pin

    # ============ Emit outputs ============
    out.mkdir(parents=True, exist_ok=True)
    parquet_path = out / "assignments.parquet"
    assignments.to_parquet(parquet_path, index=False)
    click.echo(f"  wrote {parquet_path} ({len(assignments):,} rows)")

    emit_assignment_manifest(
        out_dir=out, catalog=catalog, catalog_path=subgroup_catalog,
        data_source=data_source, release_pin=release_pin,
        assignments=assignments,
        assigner_method="subgroup_assigner_maf_filter",
        variant="maf",
    )
    click.echo(f"  wrote {out / 'manifest.yaml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
