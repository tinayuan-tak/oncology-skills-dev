"""hcmi_model_availability.read — card-side reader for the per-indication HCMI model-availability product.

Reads the MATERIALIZED per-indication table (one row per framework indication) and returns the
translational model-availability summary the target-model-availability card consumes. This is an
INDICATION-level signal (target-INDEPENDENT — "how many patient-derived HCMI organoid/cell models exist
for indication Y to preclinically validate any target"), so only `indication` filters. Graceful
data_unavailable when the indication is not in the HCMI crosswalk (no mapped models) or the product is
absent.

Resolves both derived products through the manifest (`catalog_query.bucket_key_for`) rather than a
hardcoded S3 URI — a bucket/key move fails loud (FileNotFoundError -> data_unavailable) instead of
silently stranding the reader. Reads through pyarrow's S3FileSystem with predicate pushdown + column
projection (mirrors pdxe_drug_response.read / organoid_dependency_precompute.lookup), not a whole-object
`aws s3 cp`. Asserts the expected product columns at the read boundary (schema-drift guard, mirrors
target_id_sidecar.read_resolver_sidecar_map) instead of trusting an unpinned upstream schema.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from onc_methods.catalog_query.read import bucket_key_for
from onc_methods.target_id_sidecar import ensure_aws_profile

MANIFEST_ID_AVAILABILITY = "hcmi-model-availability-per-indication-v1"
MANIFEST_ID_GENOTYPE = "hcmi-genotype-matched-model-per-gene-v1"
_S3_REGION = "us-east-1"  # default cred chain honours AWS_PROFILE=cbg

_AVAILABILITY_COLS = [
    "indication",
    "n_patient_derived_models",
    "model_availability_class",
    "source",
    "primary_site_breakdown",
]

_GENOTYPE_COLS = [
    "gene_symbol",
    "indication",
    "n_models_in_indication",
    "n_models_with_alteration",
    "n_models_with_recurrent_hotspot",
    "variant_classes_present",
    "hgvsp_examples",
    "genotype_matched_class",
    "source",
]

_UNAVAILABLE = {
    "model_availability_class": "data_unavailable",
    "n_patient_derived_models": 0,
    "primary_site_breakdown": None,
    "source": "HCMI-CMDC-DR45",
}

# genotype-matched "no altered model found" is an honest NEGATIVE (class 'none'), distinct from an
# absent/unreachable product (class 'data_unavailable'). Both carry n_models_with_alteration=0.
_GENOTYPE_NONE = {
    "genotype_matched_class": "none",
    "n_models_with_alteration": 0,
    "n_models_with_recurrent_hotspot": 0,
    "n_models_in_indication": 0,
    "variant_classes_present": None,
    "hgvsp_examples": None,
    "source": "HCMI-CMDC-DR45",
}
_GENOTYPE_UNAVAILABLE = dict(_GENOTYPE_NONE, genotype_matched_class="data_unavailable")


# Indication normalization (2026-09-02, translational-readiness assessment). The HCMI products are keyed
# on the framework's COMPOSITE indication vocabulary (COADREAD / NSCLC / GC / ESCA / …; see the build
# crosswalk cli.crosswalk_indication), but consumers (target-profile fan-out, the example gallery) query
# with OncoTree LEAF codes (LUAD, STAD, COAD, …). An exact-match read therefore MISSED common leaves —
# e.g. EGFR/LUAD reported 0 patient-derived models though 27 NSCLC HCMI models exist, and ERBB2/STAD
# reported 0 though GC=25 — a false "no models" that the sibling organoid leg (which DOES alias
# STAD→Esophagus/Stomach) does not make. Normalize leaf→composite here, reusing the framework's existing
# convention (methods/dge_deseq2 + methods/gdc_somatic_hotspot both encode NSCLC={LUAD,LUSC}). Conservative:
# only UNAMBIGUOUS single-composite expansions; a genuinely composite/leaf code already matching a product
# key (NSCLC, GC, COADREAD, …) passes through unchanged (the map is a no-op for it).
_INDICATION_ALIAS = {
    "LUAD": "NSCLC",
    "LUSC": "NSCLC",  # non-small-cell lung: pooled NSCLC (dge_deseq2/gdc_somatic_hotspot)
    "STAD": "GC",  # stomach adenocarcinoma → gastric (product tags gastric 'GC')
    "ESCC": "ESCA",  # esophageal (squamous) → esophageal-carcinoma product key
    "COAD": "COADREAD",
    "READ": "COADREAD",  # colon / rectum → pooled colorectal
    "PDAC": "PAAD",  # pancreatic ductal adenocarcinoma
}


def normalize_indication(indication: "Optional[str]") -> "Optional[str]":
    """Map an OncoTree leaf code to the composite indication key the HCMI products are built on.
    Idempotent: a code that is already a product key (or unknown) is returned unchanged. Case-preserving
    on miss, upper-cased on the alias lookup so lower-case callers still resolve."""
    if not indication:
        return indication
    return _INDICATION_ALIAS.get(indication.strip().upper(), indication)


def _assert_schema(df, expected_cols: "list[str]", manifest_id: str) -> None:
    """Fail loud on a schema-drifted product instead of KeyError-ing (or silently mis-reading) downstream.
    Mirrors target_id_sidecar.read_resolver_sidecar_map's boundary assert."""
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"{manifest_id} product missing expected columns {missing} "
            f"(present: {list(df.columns)[:10]}) — schema drift"
        )


def _is_absent(e: Exception) -> bool:
    from onc_methods.target_id_sidecar import is_definitively_absent

    return is_definitively_absent(e) or isinstance(e, FileNotFoundError)


@lru_cache(maxsize=8)
def _load_availability_table(product_path: "Optional[str]" = None):
    """Load the (small, 12-row) per-indication model-availability product. Local override for tests;
    else resolves the manifest key + reads through pyarrow S3FS with column projection (no `aws s3 cp`,
    no whole-object subprocess transport)."""
    import pandas as pd

    if product_path is not None:
        from pathlib import Path

        if not Path(product_path).exists():
            return None
        df = pd.read_parquet(product_path)
    else:
        try:
            bucket, key = bucket_key_for(MANIFEST_ID_AVAILABILITY)
        except FileNotFoundError:
            return None
        ensure_aws_profile()
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        s3fs = fs.S3FileSystem(region=_S3_REGION)
        try:
            tbl = pq.read_table(f"{bucket}/{key}", filesystem=s3fs, columns=_AVAILABILITY_COLS)
        except Exception as e:  # noqa: BLE001 — genuine absence -> None; broken-env/transient propagates
            if not _is_absent(e):
                raise
            return None
        df = tbl.to_pandas()
    if df.empty:
        return df
    _assert_schema(df, _AVAILABILITY_COLS, MANIFEST_ID_AVAILABILITY)
    return df


@lru_cache(maxsize=2)
def _covered_genotype_indications(product_path: "Optional[str]" = None):
    """The set of indications the genotype-matched product actually carries rows for (used to
    distinguish an honest 'none' — indication covered, gene just absent — from 'data_unavailable' —
    indication not in the crosswalk at all). A single-column projection (no gene filter), not a
    whole-object read: touches only the `indication` column across the 80k-row product."""
    import pandas as pd

    if product_path is not None:
        from pathlib import Path

        if not Path(product_path).exists():
            return None
        df = pd.read_parquet(product_path, columns=["indication"])
        return set(df["indication"].unique())
    try:
        bucket, key = bucket_key_for(MANIFEST_ID_GENOTYPE)
    except FileNotFoundError:
        return None
    ensure_aws_profile()
    import pyarrow.fs as fs
    import pyarrow.parquet as pq

    s3fs = fs.S3FileSystem(region=_S3_REGION)
    try:
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=s3fs, columns=["indication"])
    except Exception as e:  # noqa: BLE001
        if not _is_absent(e):
            raise
        return None
    return set(tbl.to_pandas()["indication"].unique())


@lru_cache(maxsize=256)
def _load_genotype_rows(gene: "Optional[str]", product_path: "Optional[str]" = None):
    """Rows for a single gene_symbol from the genotype-matched product. Local override for tests; else
    resolves the manifest key + reads through pyarrow S3FS with predicate pushdown on `gene_symbol`
    (the product's sort key) + column projection."""
    import pandas as pd

    if product_path is not None:
        from pathlib import Path

        if not Path(product_path).exists():
            return None
        df = pd.read_parquet(product_path)
        df = df[df["gene_symbol"] == gene] if gene is not None else df
    else:
        try:
            bucket, key = bucket_key_for(MANIFEST_ID_GENOTYPE)
        except FileNotFoundError:
            return None
        ensure_aws_profile()
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        s3fs = fs.S3FileSystem(region=_S3_REGION)
        filters = [("gene_symbol", "==", gene)] if gene is not None else None
        try:
            tbl = pq.read_table(f"{bucket}/{key}", filesystem=s3fs, filters=filters, columns=_GENOTYPE_COLS)
        except Exception as e:  # noqa: BLE001
            if not _is_absent(e):
                raise
            return None
        df = tbl.to_pandas()
    if not df.empty:
        _assert_schema(df, _GENOTYPE_COLS, MANIFEST_ID_GENOTYPE)
    return df


def read_model_availability(
    indication: "Optional[str]" = None, product_path: "Optional[str]" = None, *, target: "Optional[str]" = None
) -> dict:
    """Per-indication HCMI patient-derived model-availability summary. VERDICT-INERT translational signal.

    `target` is accepted (and IGNORED) to satisfy the compose-dashboard generic-dispatch contract
    (_live_readers._generic_dispatch calls every reader as fn(target=, indication=)): model
    availability is INDICATION-level / target-INDEPENDENT, so the target symbol is irrelevant here."""
    df = _load_availability_table(product_path)
    if df is None or df.empty:
        return dict(_UNAVAILABLE, _missing_reason="no HCMI model-availability product materialized/reachable")
    norm = normalize_indication(indication)
    hit = df[df["indication"] == norm]
    if hit.empty:
        _via = f" (normalized {indication}→{norm})" if norm != indication else ""
        return dict(
            _UNAVAILABLE,
            _missing_reason=f"{indication} not in the HCMI (primary_site, disease_type) crosswalk "
            f"(no mapped patient-derived models){_via}",
        )
    row = hit.iloc[0]
    return {
        "model_availability_class": row["model_availability_class"],
        "n_patient_derived_models": int(row["n_patient_derived_models"]),
        "primary_site_breakdown": row["primary_site_breakdown"],
        "source": row["source"],
    }


def read_genotype_matched_model(
    target: "Optional[str]" = None, indication: "Optional[str]" = None, product_path: "Optional[str]" = None
) -> dict:
    """Genotype-matched-model summary for (target gene, indication): do HCMI patient-derived models
    carry a COARSE (any functional coding) alteration in the target? VERDICT-INERT translational signal.

    This IS target-dependent (unlike read_model_availability): it filters the per-(gene_symbol,
    indication) product on both the gene and the indication. A missing (gene, indication) pair is an
    honest NEGATIVE (`none`, no altered model), NOT `data_unavailable` (which means the product itself
    is absent/unreachable). Accepts fn(target=, indication=) for the compose-dashboard generic-dispatch
    contract."""
    if not target:
        return dict(_GENOTYPE_UNAVAILABLE, _missing_reason="no target gene supplied")
    df = _load_genotype_rows(target, product_path)
    if df is None:
        return dict(
            _GENOTYPE_UNAVAILABLE, _missing_reason="no HCMI genotype-matched-model product materialized/reachable"
        )
    ind = normalize_indication(indication) or "ALL"
    # Disambiguate the two honest-negative-vs-gap cases (previously both collapsed to 'none'):
    #   - the indication IS covered by the HCMI crosswalk but no model carries a functional alteration in
    #     the target  → genotype_matched_class 'none' (a real translational negative);
    #   - the indication is NOT in the HCMI crosswalk at all → 'data_unavailable' (a coverage gap, not a
    #     negative — a 'none' here would falsely assert "no model carries the alteration").
    hit = df[df["indication"] == ind] if not df.empty else df
    if hit.empty:
        covered = _covered_genotype_indications(product_path)
        if covered is None:
            return dict(
                _GENOTYPE_UNAVAILABLE,
                _missing_reason="no HCMI genotype-matched-model product materialized/reachable",
            )
        if ind not in covered:
            _via = f" (normalized {indication}→{ind})" if ind != (indication or "ALL") else ""
            return dict(
                _GENOTYPE_UNAVAILABLE,
                _missing_reason=f"{indication} not in the HCMI indication crosswalk"
                f" — genotype-matched coverage unavailable{_via}",
            )
        return dict(
            _GENOTYPE_NONE, _missing_reason=f"no HCMI model with a functional alteration in {target} mapped to {ind}"
        )
    row = hit.iloc[0]
    return {
        "genotype_matched_class": row["genotype_matched_class"],
        "n_models_with_alteration": int(row["n_models_with_alteration"]),
        # distinct models carrying a cohort-recurrent (>=2 models) HGVSp_Short in the gene; 0 if the
        # column is absent (pre-broaden product) so an older parquet still reads gracefully.
        "n_models_with_recurrent_hotspot": int(row["n_models_with_recurrent_hotspot"])
        if "n_models_with_recurrent_hotspot" in row
        else 0,
        "n_models_in_indication": int(row["n_models_in_indication"]),
        "variant_classes_present": row["variant_classes_present"],
        "hgvsp_examples": row["hgvsp_examples"],
        "source": row["source"],
    }
