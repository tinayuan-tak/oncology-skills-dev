"""structure_features_static.read — PDB + AlphaFold scalar-features reader.

Consumer: structure-features-static evidence card (Phase F) via
tractability-and-modality skill. Emits per-target scalar structural
features (PDB coverage + AlphaFold pLDDT summary + hotspot-pocket-adjacency
call) — no atomic coordinates, no interactive viewer.

Iter-1 wiring approach:
  - Reads the derived parquet at
    s3://onc-compbio/data-catalog/derived/pdb-alphafold-structure-features-per-uniprot-v1/
    when it exists.
  - Otherwise emits `data_unavailable` gracefully (avoids 20k API calls
    against PDB + AlphaFold REST at read-time; those belong in a batch
    ETL that produces the derived parquet).

Runtime discipline: @lru_cache + module-level negative cache — same patterns
as SIGNOR/CollecTri/Reactome (Sprint 2).

Companion:
  data-catalog:manifests/derived/pdb-alphafold-structure-features-per-uniprot-v1.yaml
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional


# 0.1.0 -> 0.2.0: + composite structural_ligandability_class leg (LIVE, from
# structure-ligandability-per-protein-v1) merged onto the hotspot-adjacency fields.
METHOD_VERSION = "0.2.0"

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DERIVED_MANIFEST_ID = "pdb-alphafold-structure-features-per-uniprot-v1"
DERIVED_S3_KEY = (
    "data-catalog/derived/pdb-alphafold-structure-features-per-uniprot-v1/"
    "structure_features.parquet"
)

# Composite small-molecule structural-LIGANDABILITY product (data-catalog derived).
# This is a LIVE structure signal: it fuses 6 shipped per-UniProt products (HOTPocket
# pockets, GenomeScreen VS-hits, PLINDER co-crystals, CryptoBench cryptic sites, AlphaFold
# disorder, InterPro binding/active sites) into one ordinal structural_ligandability_class.
# The hotspot-adjacency product above (DERIVED_MANIFEST_ID) is a DIFFERENT schema
# (mutation-hotspot-in-pocket). It is ALSO LIVE (materialized 2026-08-07; the read below
# loads it) — KRAS/BRAF/ERBB2 -> hotspot_pocket_adjacency_call='adjacent',
# mutation_hotspot_in_druggable_pocket=True; a target with no oncogenic hotspot in a
# druggable pocket -> 'no_hotspots_annotated'. Both legs feed the E8 SM-ligandability rules.
# (Historical note: this comment previously said the hotspot product was 'still-unmaterialized'
# — it was authored 2026-08-07 hours before the product landed and was never updated.)
LIGAND_MANIFEST_ID = "structure-ligandability-per-protein-v1"
LIGAND_S3_KEY = (
    "data-catalog/derived/structure-ligandability-per-protein-v1/"
    "structure_ligandability_per_protein.parquet"
)

CACHE_DIR = Path.home() / ".cache" / "framework-structure-features"
CACHE_PARQUET = CACHE_DIR / "structure_features.parquet"
CACHE_LIGAND_PARQUET = CACHE_DIR / "structure_ligandability_per_protein.parquet"

_DERIVED_STATUS: Optional[bool] = None  # negative cache (hotspot-adjacency product)
_LIGAND_STATUS: Optional[bool] = None   # negative cache (ligandability product)


def _boto3_client():
    # shared client carries an adaptive-retry Config (absorbs transient S3 throttling on batch reads)
    from methods.target_id_sidecar import s3_client
    return s3_client()


def _ensure_derived_cached() -> Optional[Path]:
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_PARQUET.exists() and CACHE_PARQUET.stat().st_size > 0:
        _DERIVED_STATUS = True
        return CACHE_PARQUET
    if _DERIVED_STATUS is None:
        try:
            s3 = _boto3_client()
            s3.download_file(S3_BUCKET, DERIVED_S3_KEY, str(CACHE_PARQUET))
            _DERIVED_STATUS = True
            return CACHE_PARQUET
        except Exception as e:
            # Distinguish "genuinely not published yet" (a definitive 404 / NoSuchKey) from a
            # TRANSIENT failure (expired creds, AccessDenied, network blip, throttling). Latch
            # _DERIVED_STATUS = False + return None ONLY on the definitive case — genuine absence →
            # honest, process-stable data_unavailable. For a TRANSIENT error, RAISE: the outer
            # @lru_cache on _load_structure_indexed would otherwise memoize an EMPTY index off one
            # blip and poison the whole process (the None-latch "retry" never re-fired because lru
            # never re-invoked this). lru_cache never memoizes a raise, so the next call retries.
            # (403/AccessDenied dropped from "definitive" per RD8 — it is almost always transient.)
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (code in ("404", "NoSuchKey")
                          or e.__class__.__name__ in ("NoSuchKey", "404")
                          or isinstance(e, FileNotFoundError))
            if definitive:
                _DERIVED_STATUS = False
                return None
            raise
    return None


def _index_by_symbol_and_ac(path, ac_col: str) -> dict:
    """Load a per-protein parquet and index each row by BOTH its gene_symbol (UPPER) and its accession
    column (`ac_col`), for O(1) per-target lookup. {} if the product is unavailable/empty. RAISES on a
    broken env (missing pandas/pyarrow) — never masks that as an empty index. Shared by the structure
    + ligandability loaders (was two copy-pasted parse-and-index blocks)."""
    if path is None:
        return {}
    try:
        import pandas as pd
        df = pd.read_parquet(path)
    except FileNotFoundError:
        return {}          # cache file vanished between the exists() check and the read (race) — absent
    except Exception:
        # A broken env (missing pandas/pyarrow) or a corrupt/partial cache is NOT data absence —
        # PROPAGATE (honest _live_read_error at the live-read seam; @lru_cache does not memoize the
        # raise, so it is retried). NB: this handler was previously `# absence-discipline: exempt`
        # ("S3 disciplined upstream") — that exemption was WRONG: the outer lru DEFEATED it by
        # memoizing the empty {} off a single corrupt/transient read, so it is now disciplined.
        raise
    if df.empty:
        return {}
    idx: dict[str, dict] = {}
    for _, row in df.iterrows():
        rec = row.to_dict()
        sym = str(rec.get("gene_symbol", "") or "").strip().upper()
        ac = str(rec.get(ac_col, "") or "").strip()
        if sym:
            idx[sym] = rec
        if ac:
            idx[ac] = rec
    return idx


@lru_cache(maxsize=1)
def _load_structure_indexed() -> dict:
    """Structure-features parquet indexed by gene_symbol + uniprot_ac (O(1) per-target lookup)."""
    return _index_by_symbol_and_ac(_ensure_derived_cached(), "uniprot_ac")


def _ensure_ligand_cached() -> Optional[Path]:
    """S3 read-through for the composite ligandability product. Same transient-vs-
    definitive error discipline as _ensure_derived_cached (only latch False on a
    definitive 404/403 so a transient failure retries instead of poisoning the process)."""
    global _LIGAND_STATUS
    if _LIGAND_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_LIGAND_PARQUET.exists() and CACHE_LIGAND_PARQUET.stat().st_size > 0:
        _LIGAND_STATUS = True
        return CACHE_LIGAND_PARQUET
    if _LIGAND_STATUS is None:
        try:
            s3 = _boto3_client()
            s3.download_file(S3_BUCKET, LIGAND_S3_KEY, str(CACHE_LIGAND_PARQUET))
            _LIGAND_STATUS = True
            return CACHE_LIGAND_PARQUET
        except Exception as e:
            # Same transient-vs-definitive discipline as _ensure_derived_cached: latch False + return
            # None ONLY on genuine absence (404/NoSuchKey); RAISE on transient/creds/broken-env so the
            # outer @lru_cache on _load_ligandability_indexed does not memoize an empty index off one
            # blip (would poison the SM-ligandability call process-wide). 403 is NOT definitive (RD8).
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (code in ("404", "NoSuchKey")
                          or e.__class__.__name__ in ("NoSuchKey", "404")
                          or isinstance(e, FileNotFoundError))
            if definitive:
                _LIGAND_STATUS = False
                return None
            raise
    return None


@lru_cache(maxsize=1)
def _load_ligandability_indexed() -> dict:
    """Composite ligandability parquet indexed by gene_symbol + uniprot_id (O(1) per-target lookup).
    {} if the product is unavailable."""
    return _index_by_symbol_and_ac(_ensure_ligand_cached(), "uniprot_id")


def _ligandability_fields(target: str) -> dict:
    """Composite structural-ligandability fields for a target (gene symbol or UniProt-AC).

    Returns the card-consumed ligandability keys. When the product is unavailable or the
    target is absent, returns the honest coverage-gap defaults (insufficient_evidence) —
    NEVER a false negative. Additive: these fields sit alongside the hotspot-adjacency
    fields and do not alter them."""
    # _load_ligandability_indexed raises on transient/broken-env (→ honest _live_read_error, NOT
    # memoized by its lru); returns {} on genuine absence. Let the transient propagate — masking it
    # as {} here would silently degrade the SM-ligandability call to insufficient_evidence.
    idx = _load_ligandability_indexed()
    if not idx:
        return _empty_ligandability("structure_ligandability_unavailable")
    row = idx.get(target.upper().strip()) or idx.get(target.strip())
    if row is None:
        return _empty_ligandability("target_not_in_ligandability")
    return {
        "structural_ligandability_class": row.get("structural_ligandability_class", "insufficient_evidence"),
        "n_ligandability_axes": int(row.get("n_ligandability_axes") or 0),
        "has_experimental_cocrystal": bool(row.get("experimental_cocrystal", False)),
        "has_druggable_pocket": bool(row.get("druggable_pocket", False)),
        "has_virtual_screen_hit": bool(row.get("virtual_screen_hit", False)),
        "has_cryptic_site": bool(row.get("cryptic_site", False)),
        "has_annotated_binding_site": bool(row.get("annotated_binding_site", False)),
        "is_foldable": bool(row.get("foldable", False)),
        "ligandability_disorder_class": row.get("disorder_tractability_class"),
        "_ligandability_source": LIGAND_MANIFEST_ID,
    }


def _empty_ligandability(note: str) -> dict:
    """Coverage-gap ligandability defaults — insufficient_evidence, never a false negative."""
    return {
        "structural_ligandability_class": "insufficient_evidence",
        "n_ligandability_axes": 0,
        "has_experimental_cocrystal": False,
        "has_druggable_pocket": False,
        "has_virtual_screen_hit": False,
        "has_cryptic_site": False,
        "has_annotated_binding_site": False,
        "is_foldable": False,
        "ligandability_disorder_class": None,
        "_ligandability_note": note,
    }


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target structural features from the pre-computed derived parquet.

    Args:
        target: HGNC gene symbol OR UniProt-AC.
        indication: unused.

    Returns:
        dict matching structure-features-static card summary shape. Always includes
        the composite structural-ligandability fields (from the LIVE ligandability
        product) merged onto the hotspot-adjacency fields. Both legs are LIVE +
        independent: if EITHER product is unavailable at read time its fields degrade
        to no_structure / insufficient_evidence (an honest coverage gap, never a false
        negative), while the other leg still populates.
    """
    # Hotspot-adjacency leg (LIVE: pdb-alphafold-structure-features-per-uniprot-v1). _load_structure_
    # indexed RAISES on transient/broken-env (→ honest _live_read_error at the live-read seam, NOT
    # memoized by its lru) and returns {} on genuine absence — so let a transient propagate rather
    # than mask it as a false no_structure. Genuine absence / target-not-present degrade honestly.
    idx = _load_structure_indexed()
    if not idx:
        base = _empty_result("structure_data_unavailable")
    else:
        target_up = target.upper().strip()
        row = idx.get(target_up) or idx.get(target.strip())
        base = _empty_result("target_not_in_structure_features") if row is None \
            else _hotspot_summary(row)
    # LIVE ligandability leg (always merged; independent of the hotspot product).
    base.update(_ligandability_fields(target))
    return base


def _hotspot_summary(row) -> dict:
    """The hotspot-adjacency summary fields from a hotspot-product row."""
    return {
        "hotspot_pocket_adjacency_call": row.get("hotspot_pocket_adjacency_call", "no_structure"),
        "mutation_hotspot_in_druggable_pocket": bool(row.get("mutation_hotspot_in_druggable_pocket", False)),
        "pdb_coverage_class": _classify_pdb_coverage(row),
        "alphafold_confidence_class": _classify_alphafold_confidence(row),
        "pdb_ids_available": _coerce_id_list(row.get("pdb_ids_available")),
        "pdb_best_resolution_angstrom": row.get("pdb_best_resolution_angstrom"),
        "pdb_best_method": row.get("pdb_best_method", "none"),
        "alphafold_plddt_mean": row.get("alphafold_plddt_mean"),
        "alphafold_plddt_min": row.get("alphafold_plddt_min"),
        "alphafold_plddt_min_domain": row.get("alphafold_plddt_min_domain"),
        "n_domains_low_plddt": row.get("n_domains_low_plddt", 0),
        "disordered_fraction": row.get("disordered_fraction"),
        "method_version": METHOD_VERSION,
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _coerce_id_list(v) -> list:
    """Normalise pdb_ids_available to a plain list. Parquet returns this list column as a numpy
    ndarray, for which `v or []` raises 'truth value of an array is ambiguous' — so never use
    truthiness on it. Handles ndarray / list / tuple / scalar str / None uniformly."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    try:
        return [x for x in list(v) if x is not None and str(x).strip()]
    except TypeError:
        return [v]


def _classify_pdb_coverage(row) -> str:
    ids = _coerce_id_list(row.get("pdb_ids_available"))
    if len(ids) >= 5:
        return "strong"
    if len(ids) >= 1:
        return "partial"
    if row.get("alphafold_prediction_id"):
        return "af_only"
    return "none"


def _classify_alphafold_confidence(row) -> str:
    mean = row.get("alphafold_plddt_mean")
    if mean is None:
        return "unavailable"
    try:
        m = float(mean)
    except (ValueError, TypeError):
        return "unavailable"
    if m >= 90:
        return "high"
    if m >= 70:
        return "moderate"
    return "low"


def _empty_result(note: str) -> dict:
    return {
        "hotspot_pocket_adjacency_call": "no_structure",
        "mutation_hotspot_in_druggable_pocket": False,
        "pdb_coverage_class": "none",
        "alphafold_confidence_class": "unavailable",
        "pdb_ids_available": [],
        "pdb_best_resolution_angstrom": None,
        "pdb_best_method": "none",
        "alphafold_plddt_mean": None,
        "alphafold_plddt_min": None,
        "alphafold_plddt_min_domain": None,
        "n_domains_low_plddt": 0,
        "disordered_fraction": None,
        "method_version": METHOD_VERSION,
        "_data_note": note,
    }
