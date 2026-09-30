"""subgroup_common.loaders — cached loaders for subgroup pipeline data.

Two families:

1. **Source-data loaders** for assigner methods (Phase 2a.1-3):
   - load_tcga_marker_paper_subtypes(indication) — TCGA marker-paper tables
     (Modality A patient-side labels)
   - load_tcga_maf(indication) — TCGA MC3 + GDC pancohort MAFs
     (Modality B mutation calls)
   - load_tcga_expression(indication, gene_symbols) — recount3 log2(TPM+1)
     for classifier (Modality C)
   - load_depmap_inferred_subtypes() — DepMap OmicsInferredMolecularSubtypes.csv
     + Model.csv join (Modality A cell-line-side)
   - load_depmap_somatic_mutations() — DepMap OmicsSomaticMutations.csv
     (Modality B cell-line-side)
   - load_depmap_expression(gene_symbols) — DepMap
     OmicsExpressionProteinCodingGenesTPMLogp1.csv (Modality C)

2. **Assignment-product loader** for Phase-3 methods (Path B iteration):
   - load_assignments(manifest_id) — reads the tall
     subgroup_assignments.parquet from a data-catalog derived manifest.
     Cached with lru_cache so all subgroups in one method invocation
     re-read the parquet once. This is the load-bearing optimization
     from the Phase-0d agent's I/O amortization argument.

Resolution order for every source loader:
  1. Session cache (~/.cache/framework-subgroup-*/...)
  2. Legacy local-cache directories (per-dataset — see per-loader docstring)
  3. S3 fetch → parse → write to session cache

Iter-1 note: S3 fetch is stubbed here; Phase 2a.4's remit is the API shape +
cache infrastructure + session-cache dir layout. Real S3 fetches come online
when the data-catalog manifests + boto3 credential resolution stabilize
in Phase 2b/c manifest wire-in.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd

from onc_methods.roots import data_catalog_root

# ---------- Cache infrastructure -------------------------------------------

# Session-persistent disk-cache location — populated on first fetch;
# subsequent invocations read locally. Auto-created if absent.
CACHE_ROOT = Path.home() / ".cache" / "framework-subgroup-pipeline"

# Per-dataset cache subdirs
CACHE_TCGA_MARKER = CACHE_ROOT / "tcga-marker-paper"
CACHE_TCGA_MAF = CACHE_ROOT / "gdc-pancohort-somatic"
CACHE_TCGA_EXPRESSION = CACHE_ROOT / "tcga-recount3"
# Bumped 26q1→26q3 (data-catalog#681, Wave-2 of #810). The indication→OncotreeLineage crosswalk is
# byte-stable 26q1→26q3 (#810 Model.csv re-validation: identical lineage/code/subtype value sets), so
# the narrowing LOGIC is unchanged; only per-lineage MEMBERSHIP COUNTS shifted (Lung 293→331, Myeloid
# 109→116, Esophagus/Stomach 189→199, Bowel 146→148, Eye 29→30). Moved in lockstep with (a) re-running
# the subgroup-assignment pipeline against 26q3 + re-publishing the derived subgroup_assignments
# products, and (b) re-transcribing the per-OncotreeCode census in
# tests/test_depmap_population_narrowing.py to the recomputed 26Q3 counts.
CACHE_DEPMAP = CACHE_ROOT / "depmap-26q3"
CACHE_ASSIGNMENTS = CACHE_ROOT / "subgroup-assignments"

# Legacy per-loader-scoped fallback directories (checked before session cache
# for backward compat with the Phase 2a.1-3 direct-fallback protocol)
LEGACY_TCGA_MARKER = Path.home() / ".cache" / "framework-tcga-marker-paper"
LEGACY_TCGA_MAF = Path.home() / ".cache" / "framework-gdc-pancohort-somatic"
LEGACY_TCGA_EXPRESSION = Path.home() / ".cache" / "framework-tcga-recount3"
LEGACY_DEPMAP = Path.home() / ".cache" / "framework-depmap-26q3"


def _log(msg: str) -> None:
    """Emit a fetch-progress line to stderr."""
    try:
        import click

        click.echo(msg, err=True)
    except ImportError:
        print(msg, file=sys.stderr)


def clear_all_caches() -> None:
    """Reset in-process lru_caches. For test scenarios only."""
    load_tcga_marker_paper_subtypes.cache_clear()
    load_tcga_maf.cache_clear()
    load_depmap_inferred_subtypes.cache_clear()
    load_depmap_somatic_mutations.cache_clear()
    load_assignments.cache_clear()


# ---------- Source-data loaders (source-side; Phase 2a.1-3 consumers) ------


@lru_cache(maxsize=32)
def load_tcga_marker_paper_subtypes(indication: str) -> pd.DataFrame:
    """Load per-sample TCGA marker-paper subtype labels for an indication.

    Returns a DataFrame with columns:
      sample_id, patient_id, source_native_id, plus indication-specific
      subtype columns (MSI_status, CMS_subtype, primary_site, etc.).

    Cache-fallback resolution (Phase 2a.1 preserved):
      1. Session cache: ~/.cache/framework-subgroup-pipeline/tcga-marker-paper/{indication_lower}/subtypes.csv
      2. Legacy cache: ~/.cache/framework-tcga-marker-paper/{indication_lower}/subtypes.csv
      3. S3 (not yet wired): s3://onc-compbio/data-catalog/sources/tcga-marker-papers/subtypes-2018/
    """
    ind_lower = indication.lower()
    session = CACHE_TCGA_MARKER / ind_lower / "subtypes.csv"
    legacy = LEGACY_TCGA_MARKER / ind_lower / "subtypes.csv"
    for p in [session, legacy]:
        if p.exists():
            _log(f"[subgroup_common] loaded TCGA marker-paper for {indication} from {p}")
            return pd.read_csv(p)
    raise FileNotFoundError(
        f"TCGA marker-paper labels for {indication} not in either cache path "
        f"({session} or {legacy}). Phase 2a.4 keeps the cache-fallback protocol; "
        f"Phase 2b/c wires S3 fetch. For immediate execution: place a CSV "
        f"with columns (sample_id, patient_id, source_native_id, "
        f"<subtype_columns>) at the session-cache path."
    )


@lru_cache(maxsize=32)
def load_tcga_maf(indication: str) -> pd.DataFrame:
    """Load TCGA MAF for an indication.

    Returns a MAF-shaped DataFrame with columns:
      sample_id, patient_id, source_native_id, gene_symbol, protein_change,
      effect, exon, Variant_Classification, ...

    Cache resolution: session → legacy → S3 (not yet wired).
    """
    ind_lower = indication.lower()
    for ext in ["parquet", "csv"]:
        session = CACHE_TCGA_MAF / f"{ind_lower}-mc3.{ext}"
        legacy = LEGACY_TCGA_MAF / f"{ind_lower}-mc3.{ext}"
        for p in [session, legacy]:
            if p.exists():
                _log(f"[subgroup_common] loaded TCGA MAF for {indication} from {p}")
                return pd.read_parquet(p) if ext == "parquet" else pd.read_csv(p)
    raise FileNotFoundError(
        f"TCGA MAF for {indication} not in cache. Phase 2b/c wires S3 fetch. "
        f"Expected at {CACHE_TCGA_MAF}/{ind_lower}-mc3.{{parquet,csv}} or "
        f"legacy path {LEGACY_TCGA_MAF}/{ind_lower}-mc3.{{parquet,csv}}."
    )


@lru_cache(maxsize=16)
def load_depmap_inferred_subtypes() -> pd.DataFrame:
    """Load DepMap OmicsInferredMolecularSubtypes.csv joined with Model.csv.

    Returns a DataFrame with columns:
      ModelID, OncotreeLineage, OncotreePrimaryDisease, OncotreeSubtype,
      plus OmicsInferredMolecularSubtypes flags (KRAS_G12C, MSI, etc.).
    """
    for base in [CACHE_DEPMAP, LEGACY_DEPMAP]:
        subtypes_path = base / "OmicsInferredMolecularSubtypes.csv"
        model_path = base / "Model.csv"
        if subtypes_path.exists() and model_path.exists():
            _log(f"[subgroup_common] loaded DepMap inferred-subtypes + Model from {base}")
            subtypes = pd.read_csv(subtypes_path)
            model = pd.read_csv(model_path)
            return model.merge(subtypes, on="ModelID", how="left")
    raise FileNotFoundError(
        f"DepMap OmicsInferredMolecularSubtypes.csv + Model.csv not found in cache. "
        f"Expected at {CACHE_DEPMAP} or {LEGACY_DEPMAP}."
    )


@lru_cache(maxsize=16)
def load_depmap_somatic_mutations() -> pd.DataFrame:
    """Load DepMap OmicsSomaticMutations.csv (cell-line MAF equivalent).

    Returns a MAF-shaped DataFrame keyed by ModelID.
    """
    for base in [CACHE_DEPMAP, LEGACY_DEPMAP]:
        path = base / "OmicsSomaticMutations.csv"
        if path.exists():
            _log(f"[subgroup_common] loaded DepMap somatic mutations from {path}")
            return pd.read_csv(path)
    raise FileNotFoundError(
        f"DepMap OmicsSomaticMutations.csv not found in cache. Expected at {CACHE_DEPMAP} or {LEGACY_DEPMAP}."
    )


def load_depmap_expression(gene_symbols: list[str] | tuple[str, ...]) -> pd.DataFrame:
    """Load DepMap OmicsExpressionProteinCodingGenesTPMLogp1.csv for a gene subset.

    Not lru_cached at the function level (gene-symbol lists are un-hashable
    as list; a tuple-input variant would be). Internal helper reads the full
    matrix once via _load_depmap_expression_full().
    """
    full = _load_depmap_expression_full()
    missing = [g for g in gene_symbols if g not in full.columns]
    if missing:
        raise KeyError(f"Marker genes not in DepMap expression matrix: {missing}")
    return full[list(gene_symbols)]


@lru_cache(maxsize=4)
def _load_depmap_expression_full() -> pd.DataFrame:
    """Load full DepMap expression matrix (log2(TPM+1)); cached once per session."""
    for base in [CACHE_DEPMAP, LEGACY_DEPMAP]:
        path = base / "OmicsExpressionProteinCodingGenesTPMLogp1.csv"
        if path.exists():
            _log(f"[subgroup_common] loaded DepMap expression matrix from {path}")
            return pd.read_csv(path, index_col=0)
    raise FileNotFoundError(
        f"DepMap expression matrix not found in cache. Expected at {CACHE_DEPMAP} or {LEGACY_DEPMAP}."
    )


# ---------- Assignment-product loader (Phase-3 Path B consumer) ------------


@lru_cache(maxsize=64)
def load_assignments(manifest_id: str, data_catalog_repo: Path | None = None) -> pd.DataFrame:
    """Load subgroup_assignments.parquet for a data-catalog derived manifest.

    This is the Path-B I/O amortization primitive from Phase-0d design: methods
    that iterate over N subgroups in one invocation call this ONCE (via
    lru_cache), then filter the returned DataFrame per subgroup.

    Args:
      manifest_id: derived-manifest id, e.g. `tcga-subgroup-assignments-coadread-v1`.
      data_catalog_repo: path to the data-catalog repo (default: standard SageMaker path).

    Returns:
      DataFrame with columns per resolver-product design:
      sample_id, patient_id, source_native_id, stratum_id, is_member,
      derivation_source, derivation_value, evaluated_at_release.
    """
    if data_catalog_repo is None:
        # Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
        data_catalog_repo = data_catalog_root()

    # Resolution order mirrors the source loaders above: session cache first,
    # then the data-catalog derived manifest's S3 pointer (Phase 2b/c). The
    # assigner writes the parquet + a sibling manifest.yaml into the session
    # cache at emit time, so a locally-emitted product resolves here WITHOUT a
    # published derived manifest — the manifest-in-repo requirement applies
    # only to the not-yet-wired S3 fetch path.
    parquet_local = CACHE_ASSIGNMENTS / manifest_id / "assignments.parquet"
    if parquet_local.exists():
        _log(f"[subgroup_common] loaded assignments for {manifest_id} from local cache")
        return pd.read_parquet(parquet_local)

    manifest_path = data_catalog_repo / "manifests" / "derived" / f"{manifest_id}.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Assignments for {manifest_id} not in session cache "
            f"({parquet_local}) and no derived manifest at {manifest_path}. "
            f"Either emit the product locally (run the matching subgroup_assigner "
            f"with --out {CACHE_ASSIGNMENTS / manifest_id}) or ship the derived "
            f"manifest (Phase 2b/c, ~20 shards, one PR per source × indication)."
        )

    import yaml

    manifest = yaml.safe_load(manifest_path.read_text())
    s3_uri = manifest.get("s3_uri")
    if not s3_uri:
        raise FileNotFoundError(
            f"Assignments for {manifest_id} not in session cache ({parquet_local}) "
            f"and its derived manifest declares no s3_uri to fetch from."
        )
    # S3 fetch → session cache → read. First fetch of a published product pays
    # the download; subsequent reads hit the local cache (+ the lru_cache above).
    # Routed through the hardened in-process client (adaptive-retry Config + profile
    # fallback) instead of a raw `aws s3 cp` subprocess, so a transient (ExpiredToken /
    # 403 / throttle / timeout) is distinguishable from a genuine 404/NoSuchKey — only
    # the latter degrades to FileNotFoundError; everything else re-raises (see
    # `is_definitively_absent` docstring / read.py:_read_gene_uncached exemplar).
    from onc_methods.target_id_sidecar import is_definitively_absent, s3_client

    parquet_local.parent.mkdir(parents=True, exist_ok=True)
    _log(f"[subgroup_common] fetching assignments for {manifest_id} from {s3_uri}")
    bucket, _, key = s3_uri.removeprefix("s3://").partition("/")
    try:
        # Whole-file by design (Path-B amortization primitive, docstring above): callers consume
        # EVERY stratum row of the small, tall assignments.parquet in one pass, so there is no
        # per-target/per-column pushdown to make. Replaces the equally-whole-file `aws s3 cp`
        # subprocess this superseded — not a new whole-file cold-start cost.
        s3_client().download_file(bucket, key, str(parquet_local))  # pushdown-discipline: exempt -- whole-file
    except Exception as e:  # noqa: BLE001
        if not is_definitively_absent(e):
            raise  # broken env / transient S3 / creds — propagate, don't mask as absence
        raise FileNotFoundError(
            f"S3 fetch of {manifest_id} failed ({s3_uri}): genuine absence ({type(e).__name__}: {e}). "
            f"Check that the product is published."
        ) from e
    if not parquet_local.exists():
        raise FileNotFoundError(f"S3 fetch of {manifest_id} reported success but {parquet_local} is missing.")
    return pd.read_parquet(parquet_local)
