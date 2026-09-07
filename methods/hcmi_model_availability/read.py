"""hcmi_model_availability.read — card-side reader for the per-indication HCMI model-availability product.

Reads the MATERIALIZED per-indication table (one row per framework indication) and returns the
translational model-availability summary the target-model-availability card consumes. This is an
INDICATION-level signal (target-INDEPENDENT — "how many patient-derived HCMI organoid/cell models exist
for indication Y to preclinically validate any target"), so only `indication` filters. Graceful
data_unavailable when the indication is not in the HCMI crosswalk (no mapped models) or the product is
absent. Mirrors pancan_mutation_ccf.read's S3-resolve pattern (aws s3 cp -> pandas).
"""

from __future__ import annotations

import io
import subprocess
from functools import lru_cache
from typing import Optional

_DERIVED_S3 = (
    "s3://onc-compbio/data-catalog/derived/"
    "hcmi-model-availability-per-indication-v1/hcmi_model_availability_per_indication.parquet"
)

_GENOTYPE_DERIVED_S3 = (
    "s3://onc-compbio/data-catalog/derived/hcmi-genotype-matched-model-per-gene-v1/hcmi_genotype_matched_model.parquet"
)

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


from methods.target_id_sidecar import ensure_aws_profile


@lru_cache(maxsize=4)
def _load_parquet(s3_uri: str, product_path: "Optional[str]" = None):
    """Load a derived parquet (local product_path override for tests, else `aws s3 cp` from s3_uri)."""
    import pandas as pd

    if product_path:
        from pathlib import Path

        return pd.read_parquet(product_path) if Path(product_path).exists() else None
    ensure_aws_profile()
    try:
        raw = subprocess.run(["aws", "s3", "cp", s3_uri, "-"], capture_output=True, timeout=120).stdout
        return pd.read_parquet(io.BytesIO(raw)) if raw else None
    except Exception as e:  # noqa: BLE001
        # descriptive-inert product. A genuine absence surfaces above as empty stdout (→ None); the
        # except only catches broken-env (missing pandas) / corrupt parquet / subprocess timeout —
        # those must surface, not be masked as data_unavailable. Re-raise.
        from methods.target_id_sidecar import is_definitively_absent

        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return None


def _load_product(product_path: "Optional[str]" = None):
    """Load the per-indication model-availability product."""
    return _load_parquet(_DERIVED_S3, product_path)


def read_model_availability(
    indication: "Optional[str]" = None, product_path: "Optional[str]" = None, *, target: "Optional[str]" = None
) -> dict:
    """Per-indication HCMI patient-derived model-availability summary. VERDICT-INERT translational signal.

    `target` is accepted (and IGNORED) to satisfy the compose-dashboard generic-dispatch contract
    (_live_readers._generic_dispatch calls every reader as fn(target=, indication=)): model
    availability is INDICATION-level / target-INDEPENDENT, so the target symbol is irrelevant here."""
    df = _load_product(product_path)
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
    df = _load_parquet(_GENOTYPE_DERIVED_S3, product_path)
    if df is None or df.empty:
        return dict(
            _GENOTYPE_UNAVAILABLE, _missing_reason="no HCMI genotype-matched-model product materialized/reachable"
        )
    if not target:
        return dict(_GENOTYPE_UNAVAILABLE, _missing_reason="no target gene supplied")
    ind = normalize_indication(indication) or "ALL"
    # Disambiguate the two honest-negative-vs-gap cases (previously both collapsed to 'none'):
    #   - the indication IS covered by the HCMI crosswalk but no model carries a functional alteration in
    #     the target  → genotype_matched_class 'none' (a real translational negative);
    #   - the indication is NOT in the HCMI crosswalk at all → 'data_unavailable' (a coverage gap, not a
    #     negative — a 'none' here would falsely assert "no model carries the alteration").
    covered = set(df["indication"].unique())
    hit = df[(df["gene_symbol"] == target) & (df["indication"] == ind)]
    if hit.empty:
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
