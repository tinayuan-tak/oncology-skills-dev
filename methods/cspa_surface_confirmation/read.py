"""cspa_surface_confirmation.read — wet-lab MEASURED surface confirmation from the Cell Surface
Protein Atlas (CSPA, Bausch-Fluck et al. 2015 PLOS ONE).

The live-firing provider of the `surface_confirmation` measurement_type (DATA_TO_SKILL_CONTRACT).
CSPA is the wet-lab (CSC-technology MS) companion to SURFY's in-silico prediction — this reader lets
a gate distinguish "measured on the surface" (evidence_tier: measured) from "predicted surface"
(inferred). It resolves the CSPA-orphan the doc opens with.

CONSUMES the DERIVED product, NOT the source xlsx (data-catalog discipline: methods read derived
manifests; ingestion goes through the id-resolver). Two artifacts under
derived/cspa-surface-confirmation-per-uniprot-v1/:
  - payload parquet: one row per UniProt AC (native key) → {surface_confirmation_class,
    cspa_category, n_celllines_detected}.
  - resolver SIDECAR parquet: native_row_key (UniProt AC) → canonical HGNC symbol/Ensembl/Entrez
    (target_id_resolver). The payload has NO symbol column, so a symbol lookup MUST join via the
    sidecar (same discipline as the topology + Gygi-proteomics readers).

Runtime: S3 get → in-process cache via lru_cache on the built index; single lookup per call.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_key_for, sidecar_bucket_key_for

METHOD_VERSION = "0.2.0"  # 0.1.0 -> 0.2.0: + HPA-IF orthogonal corroboration facet (surface_multimodal_support)
DERIVED_MANIFEST_ID = "cspa-surface-confirmation-per-uniprot-v1"
# payload + resolver-sidecar keys resolved from the data-catalog manifest (single
# source of truth): s3_uri is the payload; target_resolution.sidecar_s3_uri the sidecar.
S3_BUCKET, PAYLOAD_KEY = bucket_key_for(DERIVED_MANIFEST_ID)
_, SIDECAR_KEY = sidecar_bucket_key_for(DERIVED_MANIFEST_ID)
DEFAULT_AWS_PROFILE = "cbg"


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _read_parquet(path_or_none, bucket, key):
    import pandas as pd
    if path_or_none is not None:
        return pd.read_parquet(path_or_none)
    _ensure_aws_profile()
    # shared client: AWS_PROFILE=cbg + adaptive-retry Config (absorbs transient S3 throttling on
    # batch reads). A bare boto3.client("s3") had NO retry backoff (mirrors uniprot_gpi_anchor /
    # uniprot_protein_features).
    from methods.target_id_sidecar import s3_client
    body = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


@lru_cache(maxsize=1)
def _load_indexed(payload_path: Optional[str] = None, sidecar_path: Optional[str] = None):
    """Build (payload_by_ac, symbol_to_ac). None when the payload GENUINELY absent.

    payload_by_ac: uniprot_ac -> row dict (class, category, n_celllines).
    symbol_to_ac : UPPER(hgnc symbol) -> uniprot_ac, from the resolver sidecar."""
    try:
        payload = _read_parquet(payload_path, S3_BUCKET, PAYLOAD_KEY)
    except Exception as e:  # noqa: BLE001
        # Genuine 404/NoSuchKey (or a missing local fixture) → None (honest data_unavailable). A
        # transient S3 / creds / broken-env failure must NOT be masked as "product unavailable": it
        # would silently flip EVERY target to data_unavailable AND — because @lru_cache would memoize
        # the None — poison the whole process on one blip. Re-raise it; lru_cache never memoizes a
        # raise, so a subsequent call retries (mirrors uniprot_gpi_anchor).
        from methods.target_id_sidecar import is_definitively_absent
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return None
    payload_by_ac = {}
    for rec in payload.to_dict("records"):
        ac = str(rec.get("uniprot_ac", "")).strip()
        if ac:
            payload_by_ac[ac] = rec
    symbol_to_ac = {}
    try:
        sc = _read_parquet(sidecar_path, S3_BUCKET, SIDECAR_KEY)
        sym_col = "hgnc_primary_symbol_at_resolution"
        if sym_col in sc.columns and "native_row_key" in sc.columns:
            for sym, ac in zip(sc[sym_col].values, sc["native_row_key"].values):
                if isinstance(sym, str) and sym.strip() and isinstance(ac, str):
                    symbol_to_ac[sym.strip().upper()] = ac.strip()
    except Exception as e:  # noqa: BLE001 — sidecar genuinely-absent: AC-direct lookups still work
        # A transient/creds/broken-env failure must NOT be masked (would drop symbol→AC for the whole
        # batch AND poison the lru with a partial index) — re-raise; only genuine absence is swallowed.
        from methods.target_id_sidecar import is_definitively_absent
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
    return payload_by_ac, symbol_to_ac


def read_surface_confirmation(target: str, indication: Optional[str] = None,
                              payload_path: Optional[str] = None,
                              sidecar_path: Optional[str] = None,
                              hpa_if: Optional[dict] = None) -> dict:
    """CSPA surface-confirmation summary for `target` (HGNC symbol or UniProt AC).

    A target absent from the CSPA high-confidence master is an HONEST measured negative in the CSPA
    panel (`not_surface`, measured_in_cspa=False) — NOT data_unavailable. data_unavailable is
    reserved for the case where the derived product itself couldn't be loaded.

    SECOND measured provider (2026-08-07): HPA immunofluorescence subcellular location is an ORTHOGONAL
    measured surface-residency signal (microscopy vs CSPA mass-spec). It is composed here as
    CORROBORATION — surface_confirmation_class (the verdict-driving field) stays CSPA-DRIVEN so the
    surface-intrinsic rules are byte-stable; HPA adds a corroboration facet (agreement raises
    confidence, disagreement flags). `hpa_if` may be injected for tests; else read from the product."""
    idx = _load_indexed(payload_path, sidecar_path)
    if idx is None:
        base = _empty("cspa_derived_product_unavailable")
        base.update(_hpa_corroboration(target, "data_unavailable", hpa_if))
        return base
    payload_by_ac, symbol_to_ac = idx

    key = target.strip()
    ac = key if key in payload_by_ac else symbol_to_ac.get(key.upper())
    rec = payload_by_ac.get(ac) if ac else None
    if rec is None:
        out = {
            "surface_confirmation_class": "not_surface",
            "cspa_category": None,
            "n_celllines_detected": 0,
            "measured_in_cspa": False,
            "evidence_tier": "measured",
            "uniprot_ac": None,
            "method_version": METHOD_VERSION,
            "_data_source": DERIVED_MANIFEST_ID,
            "_data_note": f"{target!r} not in the CSPA high-confidence surfaceome master "
                          f"(measured-absent in the 41-cell-line panel, not a coverage gap)",
        }
        out.update(_hpa_corroboration(target, "not_surface", hpa_if))
        return out
    n = rec.get("n_celllines_detected")
    cspa_class = rec.get("surface_confirmation_class", "not_surface")
    out = {
        "surface_confirmation_class": cspa_class,
        "cspa_category": rec.get("cspa_category"),
        "n_celllines_detected": int(n) if n is not None and n == n else None,
        "measured_in_cspa": True,
        "evidence_tier": "measured",
        "uniprot_ac": rec.get("uniprot_ac"),
        "method_version": METHOD_VERSION,
        "_data_source": DERIVED_MANIFEST_ID,
    }
    out.update(_hpa_corroboration(target, cspa_class, hpa_if))
    return out


def _hpa_corroboration(target: str, cspa_class: str, hpa_if: Optional[dict]) -> dict:
    """Compose the HPA-IF orthogonal surface-confirmation facet + a CSPA↔HPA corroboration call.

    surface_confirmation_class stays CSPA-driven (verdict-stable); this adds:
      hpa_if_surface_class          — HPA IF class (plasma_membrane_main/.../location_unavailable)
      hpa_if_plasma_membrane        — bool
      surface_multimodal_support    — corroborated_surface | discordant | cspa_only | hpa_if_only |
                                      single_modality_negative | insufficient
    Two MEASURED modalities agreeing on surface = the strongest presence signal; disagreement is a flag."""
    if hpa_if is None:
        try:
            import sys as _sys
            _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
            from methods.hpa_subcellular_location.read import read_surface_if_location
            hpa_if = read_surface_if_location(target)
        except Exception:  # noqa: BLE001 — HPA leg is corroboration; its absence must not break CSPA
            hpa_if = None

    hpa_class = (hpa_if or {}).get("surface_if_location_class", "location_unavailable")
    hpa_pm = bool((hpa_if or {}).get("is_plasma_membrane", False))
    # CSPA product emits confirmed_high / confirmed / not_surface (VERIFIED against the live parquet —
    # NOT the doc's 'cell_surface_confirmed'; keying on the emitted values avoids the field-drift trap).
    cspa_surface = cspa_class in ("confirmed_high", "confirmed", "cell_surface_confirmed")
    cspa_neg = (cspa_class == "not_surface")
    hpa_surface = hpa_pm
    hpa_neg = (hpa_class == "intracellular_only")
    hpa_gap = (hpa_class == "location_unavailable" or hpa_if is None)

    if cspa_surface and hpa_surface:
        support = "corroborated_surface"
    elif (cspa_surface and hpa_neg) or (cspa_neg and hpa_surface):
        support = "discordant"
    elif cspa_surface:
        support = "cspa_only"
    elif hpa_surface:
        support = "hpa_if_only"
    elif cspa_neg or hpa_neg:
        support = "single_modality_negative"
    else:
        support = "insufficient"

    return {
        "hpa_if_surface_class": hpa_class,
        "hpa_if_plasma_membrane": hpa_pm,
        "hpa_if_reliability": (hpa_if or {}).get("if_reliability"),
        "surface_multimodal_support": support,
    }


def _empty(note: str) -> dict:
    return {
        "surface_confirmation_class": "data_unavailable",
        "cspa_category": None,
        "n_celllines_detected": None,
        "measured_in_cspa": None,
        "evidence_tier": "measured",
        "uniprot_ac": None,
        "method_version": METHOD_VERSION,
        "_data_source": DERIVED_MANIFEST_ID,
        "_data_note": note,
    }
