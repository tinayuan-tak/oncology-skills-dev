#!/usr/bin/env python3
"""subgroup_assigner_directly_tagged CLI — generate per-sample subgroup assignments
from directly-tagged source fields.

Invocation:
    subgroup-assigner-directly-tagged \
      --subgroup-catalog /path/to/coadread-subgroups-2026-q2.yaml \
      --data-source tcga \
      --release-pin 2026-Q2 \
      --catalog-repo /path/to/data-catalog \
      --out /path/to/output-dir/

The CLI:
  1. Loads the subgroup_catalog YAML; filters to atomic_strata with
     derivation_source in {directly_tagged_clinical, directly_tagged_source_provided}.
  2. Resolves the catalog's input manifest per data-source (TCGA marker paper
     for tcga; DepMap OmicsInferredMolecularSubtypes.csv + Model.csv for depmap).
  3. Evaluates each stratum's CEL-subset rule to produce per-sample membership.
  4. Emits:
       <out>/assignments.parquet  (tall rows: sample_id, stratum_id, is_member, ...)
       <out>/manifest.yaml        (validates against subgroup_assignment.schema.json)

Iter-1b implementation — Phase 2a.1 of iDAS Subtype Pipeline. See
target-contracts docs/design/SAMPLE_ANNOTATION_PLAN.md for Modality A design.
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import pandas as pd
import yaml


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.2.0"  # Phase 2a.1 — first executable version

SUPPORTED_DERIVATION_SOURCES = {
    "directly_tagged_clinical",
    "directly_tagged_source_provided",
}


# ---------- CEL-subset rule parser -----------------------------------------

# iter-1 rules are all forms of:
#   `<lhs> == '<value>'`
#   `<lhs> in [<values>]`
# Where <lhs> is `namespace.field` (e.g. `clinical.MSI_status`,
# `copy_number.ERBB2`).

_EQ_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*==\s*'([^']*)'$")
_IN_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s+in\s+\[([^\]]+)\]$")


def parse_rule(rule: str) -> tuple[str, str, list[str]]:
    """Parse a CEL-subset rule into (field_lhs, op, values).

    Returns:
        (lhs, 'eq', [single_value]) for `field == 'value'`
        (lhs, 'in', [val1, val2, ...]) for `field in ['v1', 'v2']`

    Raises ValueError on unsupported forms (e.g., MAF predicates, negations,
    numeric comparisons — those belong in maf_filter or classifier assigners).
    """
    rule = rule.strip()
    m = _EQ_RE.match(rule)
    if m:
        return m.group(1), "eq", [m.group(2)]
    m = _IN_RE.match(rule)
    if m:
        raw_values = m.group(2)
        # Split on commas; strip whitespace + single quotes
        values = [v.strip().strip("'\"") for v in raw_values.split(",")]
        return m.group(1), "in", values
    raise ValueError(
        f"Unsupported rule form for directly-tagged assigner: {rule!r}. "
        f"This method only supports `field == 'value'` and `field in [values]`. "
        f"Other forms (MAF predicates, thresholds, classifiers) belong in "
        f"subgroup_assigner_maf_filter or subgroup_assigner_classifier."
    )


# ---------- Source-data loaders --------------------------------------------

def _load_tcga_marker_paper_labels(catalog_repo: Path, indication: str) -> pd.DataFrame:
    """Load TCGA marker-paper subtype labels for the indication.

    Returns a DataFrame with columns: sample_id (TCGA aliquot), patient_id
    (TCGA barcode), source_native_id, and whatever subtype columns the
    marker paper ships for this indication.

    Iter-1b scaffold: this reads a local CSV fallback if the S3 fetch is
    unavailable. The canonical source is
    s3://onc-compbio/data-catalog/sources/tcga-marker-papers/subtypes-2018/,
    with per-cohort files tcga_subtype_{CRC,LUAD,LUSC,PAAD,STAD,HNSC}.csv +
    the pancan_atlas_subtypes_curated.csv.

    For iter-1 the caller passes indication codes; the mapping to
    marker-paper file is:
        COADREAD -> tcga_subtype_CRC.csv
        NSCLC    -> (composed from tcga_subtype_LUAD.csv + tcga_subtype_LUSC.csv)
        HNSC     -> tcga_subtype_HNSC.csv
        STAD     -> tcga_subtype_STAD.csv
        PAAD     -> tcga_subtype_PAAD.csv
        AML      -> tcga_subtype_LAML.csv (if present in marker paper)
        ESCA     -> pancan_atlas_subtypes_curated.csv (histology from clinical)

    Not implemented here as a full fetch — the actual S3-plus-local-cache
    fetcher lives in subgroup_common/loaders.py (Phase 2a.4). This method's
    Phase-2a.1 responsibility is the CLI + rule-application logic; the
    loader is stubbed with a fallback-file protocol.
    """
    # Delegate to a lightweight local resolver that reads a session-cached
    # copy if present, otherwise returns None + prints a fetch instruction.
    fallback = Path.home() / ".cache" / "framework-tcga-marker-paper" / indication.lower() / "subtypes.csv"
    if not fallback.exists():
        raise FileNotFoundError(
            f"TCGA marker-paper labels for {indication} not found at {fallback}. "
            f"Phase 2a.1 stubs the fetch; Phase 2a.4 (subgroup_common/loaders.py) "
            f"provides the canonical loader with S3-plus-local-cache resolution. "
            f"For immediate execution: pull the source file from "
            f"s3://onc-compbio/data-catalog/sources/tcga-marker-papers/subtypes-2018/ "
            f"into the fallback path."
        )

    df = pd.read_csv(fallback)

    # ---- Source-specific column normalization (Phase 2b/c real-data fix) ----
    # TCGA marker-paper CSVs (TCGAbiolinks::PanCancerAtlas_subtypes export) are
    # patient-level with column `patient` = TCGA barcode. Normalize to the
    # resolver-product convention: sample_id / patient_id / source_native_id
    # per docs/design/IDAS_SUBTYPE_PIPELINE.md.
    if "patient" in df.columns and "sample_id" not in df.columns:
        df = df.rename(columns={"patient": "patient_id"})
        # Marker-paper is patient-level; sample_id == patient_id for this source.
        df["sample_id"] = df["patient_id"]
        df["source_native_id"] = df["patient_id"]

    # ---- Source-specific value normalization ----
    # TCGA anatomic_organ_subdivision uses Title-Case-With-Spaces
    # (`Sigmoid Colon`, `Ascending Colon`). Catalog rules use lowercase-with-
    # underscores (`sigmoid_colon`). Normalize at load time so catalog rules
    # stay clean.
    if "anatomic_organ_subdivision" in df.columns:
        df["primary_site"] = df["anatomic_organ_subdivision"].str.lower().str.replace(" ", "_")

    return df


def _load_depmap_inferred_subtypes(catalog_repo: Path) -> pd.DataFrame:
    """Load DepMap OmicsInferredMolecularSubtypes.csv + Model.csv join.

    Returns a DataFrame with columns: ModelID, OncotreeLineage,
    OncotreePrimaryDisease, OncotreeSubtype, and the OmicsInferredMolecularSubtypes
    flag columns (KRAS_G12C, MSI, EWSR1_FLI1, etc.).

    Phase 2a.4 (subgroup_common/loaders.py) will provide the canonical
    S3-plus-local-cache resolver. Here we delegate to the existing
    depmap_common/loaders.py pattern where possible.
    """
    try:
        # Prefer the existing depmap_common loader if it has this
        from methods.depmap_common import loaders as depmap_loaders  # noqa
        # depmap_common may not have OmicsInferredMolecularSubtypes yet — that's
        # a Phase-2a.4 add. For now, try local-cache fallback.
    except ImportError:
        pass
    fallback = Path.home() / ".cache" / "framework-depmap-26q1" / "OmicsInferredMolecularSubtypes.csv"
    model_fallback = Path.home() / ".cache" / "framework-depmap-26q1" / "Model.csv"
    if not (fallback.exists() and model_fallback.exists()):
        raise FileNotFoundError(
            f"DepMap OmicsInferredMolecularSubtypes.csv + Model.csv not found at "
            f"{fallback} + {model_fallback}. Phase 2a.4 provides the canonical "
            f"loader. For immediate execution: pull both CSVs from "
            f"s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1/ "
            f"into the fallback path."
        )
    subtypes = pd.read_csv(fallback)
    model = pd.read_csv(model_fallback)
    df = model.merge(subtypes, on="ModelID", how="left")

    # ---- Source-specific column normalization (Phase 2b/c real-data fix) ----
    # DepMap Model.csv uses `ModelID` as the cell-line identifier. Normalize to
    # resolver-product convention: sample_id / source_native_id. DepMap has NO
    # patient concept (cell lines have anonymous PatientID that isn't a
    # clinical patient), so patient_id is null.
    df["sample_id"] = df["ModelID"]
    df["source_native_id"] = df["ModelID"]
    df["patient_id"] = None  # cell lines have no clinical-patient concept
    return df


# ---------- Rule evaluation ------------------------------------------------

def _extract_field_value(row: pd.Series, field_lhs: str) -> object:
    """Extract a namespaced field value from a row.

    `clinical.MSI_status` -> row['MSI_status'] (namespace is contextual,
    dropped when reading the DataFrame; assigner method is responsible for
    supplying the right DataFrame per data-source).

    `copy_number.ERBB2` -> row['ERBB2_copy_number'] (namespace prefix
    remapped to column suffix when reading DepMap or GDC copy-number tables).
    """
    if "." in field_lhs:
        namespace, field = field_lhs.split(".", 1)
        # For iter-1, all rules use `clinical.<field>` semantics; namespace is
        # informational, actual column is <field>. Namespace normalization is
        # per-source; the loader is responsible for landing the DataFrame in
        # a shape where `<field>` is the column name.
        return row.get(field)
    return row.get(field_lhs)


def _evaluate_stratum(
    stratum: dict,
    df: pd.DataFrame,
    sample_id_col: str,
    patient_id_col: str | None,
    native_id_col: str,
) -> pd.DataFrame:
    """Evaluate a single stratum's rule against the source DataFrame.

    Returns a DataFrame with the resolver-product columns for this stratum's rows:
        sample_id, patient_id, source_native_id, stratum_id, is_member,
        derivation_source, derivation_value, evaluated_at_release
    """
    lhs, op, values = parse_rule(stratum["rule"])
    _, field = lhs.split(".", 1) if "." in lhs else (None, lhs)

    def _predicate(row):
        v = row.get(field)
        if pd.isna(v):
            return None  # tri-value: evaluated but source-value missing → insufficient
        if op == "eq":
            return v == values[0]
        return v in values

    df = df.copy()
    df["_is_member"] = df.apply(_predicate, axis=1)

    out = pd.DataFrame({
        "sample_id": df[sample_id_col],
        "patient_id": df[patient_id_col] if patient_id_col else None,
        "source_native_id": df[native_id_col],
        "stratum_id": stratum["id"],
        "is_member": df["_is_member"],
        "derivation_source": stratum["derivation_source"],
        "derivation_value": df[field].astype(str).where(df["_is_member"] == True, ""),
    })
    return out


# ---------- Output emission ------------------------------------------------

def _emit_manifest(
    out_dir: Path,
    catalog: dict,
    data_source: str,
    release_pin: str,
    strata_ids: list[str],
    n_samples: int,
    n_rows: int,
    parquet_md5: str,
) -> None:
    """Emit the sibling manifest.yaml conforming to
    target-contracts/schemas/subgroup_assignment.schema.json.
    """
    manifest = {
        "manifest_kind": "subgroup_assignment",
        "schema_version": 1,
        "id": f"{data_source}-subgroup-assignments-{catalog['indication'].lower()}-{release_pin.lower()}",
        "indication": catalog["indication"],
        "data_source": data_source,
        "release_pin": release_pin,
        "subgroup_catalog_ref": {
            "id": catalog["id"],
            "version": catalog["version"],
        },
        "assigner_method": {
            "name": "subgroup_assigner_directly_tagged",
            "version": METHOD_VERSION,
        },
        "assignments_parquet": {
            "path": "assignments.parquet",
            "md5": parquet_md5,
            "n_samples": n_samples,
            "n_rows": n_rows,
        },
        "strata_evaluated": strata_ids,
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))


def _md5sum(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------- CLI ------------------------------------------------------------

@click.command()
@click.option("--subgroup-catalog", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to the subgroup_catalog YAML.")
@click.option("--data-source", required=True, type=click.Choice(["tcga", "depmap"]),
              help="Which data source to assign against.")
@click.option("--release-pin", required=True, help="Catalog release_pin identifier (e.g., 2026-Q2).")
@click.option("--catalog-repo", type=click.Path(file_okay=False, path_type=Path),
              default=Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog"),
              help="Path to the data-catalog repo for input-manifest resolution.")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Output directory; assignments.parquet + manifest.yaml land here.")
@click.option("--dry-run", is_flag=True,
              help="Parse the catalog, print the plan, do not produce assignments.")
def main(subgroup_catalog: Path, data_source: str, release_pin: str,
         catalog_repo: Path, out: Path, dry_run: bool) -> int:
    """Generate per-sample subgroup assignments from directly-tagged source fields."""
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

    click.echo(f"=== subgroup_assigner_directly_tagged v{METHOD_VERSION} ===")
    click.echo(f"  catalog:       {catalog_id} (indication={indication})")
    click.echo(f"  data_source:   {data_source}")
    click.echo(f"  release_pin:   {release_pin}")
    click.echo(f"  out:           {out}")
    click.echo(f"  applicable strata ({len(applicable)} of {len(atomic)}):")
    for s in applicable:
        click.echo(f"    - {s['id']:<20} rule={s['rule']!r}")

    skipped = [s["id"] for s in atomic if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES]
    if skipped:
        click.echo(f"  skipped strata (non-tagged derivation): {skipped}")
        click.echo(f"  → dispatch these to subgroup_assigner_maf_filter or subgroup_assigner_classifier")

    if not applicable:
        click.echo(f"WARNING: no applicable directly-tagged strata for data_source={data_source}", err=True)
        return 0

    if dry_run:
        click.echo("(--dry-run: skipping actual assignment generation)")
        return 0

    # ============ Load source data ============
    if data_source == "tcga":
        source_df = _load_tcga_marker_paper_labels(catalog_repo, indication)
        sample_id_col = "sample_id"      # produced by loader normalization
        patient_id_col = "patient_id"
        native_id_col = "source_native_id"
    else:  # depmap
        source_df = _load_depmap_inferred_subtypes(catalog_repo)
        sample_id_col = "ModelID"
        patient_id_col = None  # cell lines have no patient concept
        native_id_col = "ModelID"

    click.echo(f"  loaded {len(source_df):,} source rows")

    # ============ Evaluate strata ============
    per_stratum_dfs = []
    for stratum in applicable:
        try:
            rows = _evaluate_stratum(stratum, source_df, sample_id_col, patient_id_col, native_id_col)
        except ValueError as e:
            click.echo(f"  SKIP {stratum['id']}: {e}", err=True)
            continue
        per_stratum_dfs.append(rows)
        n_hit = int((rows["is_member"] == True).sum())
        n_null = int(rows["is_member"].isna().sum())
        click.echo(f"    {stratum['id']:<20} is_member=true: {n_hit:>5}, null (data-missing): {n_null:>5}")

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

    _emit_manifest(
        out_dir=out,
        catalog=catalog,
        data_source=data_source,
        release_pin=release_pin,
        strata_ids=[s["id"] for s in applicable],
        n_samples=int(assignments["sample_id"].nunique()),
        n_rows=len(assignments),
        parquet_md5=_md5sum(parquet_path),
    )
    click.echo(f"  wrote {out / 'manifest.yaml'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
