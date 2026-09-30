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
as SIGNOR/CollecTri/Reactome.

Companion:
  data-catalog:manifests/derived/pdb-alphafold-structure-features-per-uniprot-v1.yaml
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

# + composite structural_ligandability_class leg (LIVE, from
# structure-ligandability-per-protein-v1) merged onto the hotspot-adjacency fields.
METHOD_VERSION = "0.2.0"

DEFAULT_AWS_PROFILE = "cbg"
# Object locations resolve through the catalog manifest (single source of truth) via
# bucket_key_for(<manifest_id>) at read time — NOT a hardcoded s3://bucket/key literal.
# The manifest owns the (bucket, key); a re-point (bucket move, key rename) therefore
# propagates to this reader instead of silently missing it. The *_MANIFEST_ID constants
# below are the only location handles this reader carries.
DERIVED_MANIFEST_ID = "pdb-alphafold-structure-features-per-uniprot-v1"

# Composite small-molecule structural-LIGANDABILITY product (data-catalog derived).
# This is a LIVE structure signal: it fuses 6 shipped per-UniProt products (HOTPocket
# pockets, GenomeScreen VS-hits, PLINDER co-crystals, CryptoBench cryptic sites, AlphaFold
# disorder, InterPro binding/active sites) into one ordinal structural_ligandability_class.
# The hotspot-adjacency product above (DERIVED_MANIFEST_ID) is a DIFFERENT schema
# (mutation-hotspot-in-pocket). It is ALSO LIVE (the read below
# loads it) — KRAS/BRAF/ERBB2 -> hotspot_pocket_adjacency_call='adjacent',
# mutation_hotspot_in_druggable_pocket=True; a target with no oncogenic hotspot in a
# druggable pocket -> 'no_hotspots_annotated'. Both legs feed the E8 SM-ligandability rules.
LIGAND_MANIFEST_ID = "structure-ligandability-per-protein-v1"

CACHE_DIR = Path.home() / ".cache" / "framework-structure-features"
CACHE_PARQUET = CACHE_DIR / "structure_features.parquet"
CACHE_LIGAND_PARQUET = CACHE_DIR / "structure_ligandability_per_protein.parquet"

_DERIVED_STATUS: Optional[bool] = None  # negative cache (hotspot-adjacency product)
_LIGAND_STATUS: Optional[bool] = None  # negative cache (ligandability product)


from onc_methods.catalog_query.read import bucket_key_for
from onc_methods.target_id_sidecar import s3_client as _boto3_client


def _ensure_derived_cached() -> Optional[Path]:
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_PARQUET.exists() and CACHE_PARQUET.stat().st_size > 0:
        _DERIVED_STATUS = True
        return CACHE_PARQUET
    if _DERIVED_STATUS is None:
        # Resolve (bucket, key) from the catalog manifest OUTSIDE the try: an unknown/broken
        # manifest id is a wiring error (fail loud), NOT data absence to latch False on.
        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        try:
            s3 = _boto3_client()
            s3.download_file(bucket, key, str(CACHE_PARQUET))
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
            # (403/AccessDenied dropped from "definitive" — it is almost always transient.)
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (
                code in ("404", "NoSuchKey")
                or e.__class__.__name__ in ("NoSuchKey", "404")
                or isinstance(e, FileNotFoundError)
            )
            if definitive:
                _DERIVED_STATUS = False
                return None
            raise
    return None


def _none_for_missing(rec: dict) -> dict:
    """Every MISSING parquet cell as None, so no float('nan') escapes this frame boundary.

    A missing value in a float64 pandas column IS `float('nan')` — there is no other in-band marker —
    and `row.to_dict()` carries that float straight into the card summary, where json.dumps writes the
    bare token `NaN` (invalid JSON, and Python's own parser accepts it by default, which is why nothing
    downstream complained). Measured over the 504-package archetype corpus before this fix: 78 packages
    / 48 targets emitted a non-finite structural feature — alphafold_plddt_min_domain 57,
    pdb_best_resolution_angstrom 29, and alphafold_plddt_mean / _min / disordered_fraction 10 each.

    ⚠️⚠️ Those five are all float64 — but do NOT read that as "only numeric columns leak." That WAS this
    docstring's claim and CI refuted it. How a missing cell round-trips is decided by the INSTALLED
    PANDAS, and `pixi.toml` pins `pandas = "*"`, so the lockfile chooses the regime:

        pandas 2.3.3 / numpy 1.26  missing str cell -> None   (the regime the 78-package figure was measured in)
        pandas 3.0.3 / numpy 2.5.1 missing str cell -> nan    (default string dtype is `str`; its sentinel is NaN)

    So on pandas >= 3 every string column with a null cell leaks too, and the corpus figure above is a
    per-interpreter measurement rather than a property of this code. That is not academic: it costs 50
    product rows through `_classify_pdb_coverage`, which tests `alphafold_prediction_id` by TRUTHINESS —
    and a NaN is truthy. 94 of 20,329 rows carry a null prediction id and 50 of those have zero PDB IDs,
    so on pandas 3 they answer `af_only`, asserting an AlphaFold model that does not exist.

    ★ This function is nevertheless correct under BOTH regimes by construction, and the reason is the part
    worth keeping: it branches on the RUNTIME TYPE OF THE VALUE, never on the column's dtype. A NaN in a
    string column is a float with no `__len__`, so it falls through to the `pd.isna` arm and becomes None.

    ★ The target is None, not 0.0 and not a literal default, because the consumer already declares its
    own absence handling and None ACTIVATES it. `_classify_alphafold_confidence` opens with
    `if mean is None: return "unavailable"` — a guard NaN walks straight through (`nan is None` is
    False, `float(nan)` does NOT raise, and every `>=` comparison against NaN is False), so control
    fell through to the terminal `return "low"` and the card published a MEASURED structural negative
    for a value it never measured.

    ★★ That guard was not merely weak, it was UNREACHABLE: `alphafold_confidence_class` was
    "unavailable" in 0 of 20,329 product rows and 0 of 504 corpus packages. The 4 corpus packages that
    do emit "unavailable" reach it through `_empty_result` instead — they carry
    `_data_note="target_not_in_structure_features"` and their target has no row in the product at all,
    an absent ROW rather than a null CELL. This fix makes the null-cell branch reachable for the first
    time, so the two absence routes finally agree.

    ⚠️ MUST stay list-safe, and the failure mode is length-dependent so a fixture can miss it.
    `pdb_ids_available` round-trips from parquet as a numpy ndarray; `pd.isna(ndarray)` returns an
    ARRAY, and `bool()` of an array is well-defined only at len 1 — len > 1 raises in every version, and
    len 0 raises under numpy >= 2 (numpy 1.26 returned False with a DeprecationWarning, which an earlier
    draft here mistook for the permanent behaviour). So a naive scalar-only conversion breaks on the
    well-studied targets AND on the empty ones, and passes only in the middle. Non-scalars are therefore
    passed through untouched (same reason `_coerce_id_list` below refuses to use truthiness on that
    column).

    ⚠️ `pd.isna` here means MISSING, not non-finite. That is deliberate: a ±Inf in a numeric column
    is a value, not a gap, and nulling it would destroy data. If one ever appears it must be refused
    at the writer (`allow_nan=False`), never laundered here.
    """
    import pandas as pd

    out = {}
    for k, v in rec.items():
        if isinstance(v, (str, bytes)) or hasattr(v, "__len__"):
            out[k] = v  # str / ndarray / list cell — never a scalar gap, and isna() would not be a bool
        else:
            out[k] = None if pd.isna(v) else v
    return out


def _index_by_symbol_and_ac(path, ac_col: str) -> dict:
    """Load a per-protein parquet and index each row by BOTH its gene_symbol (UPPER) and its accession
    column (`ac_col`), for O(1) per-target lookup. {} if the product is unavailable/empty. RAISES on a
    broken env (missing pandas/pyarrow) — never masks that as an empty index. Shared by the structure
    + ligandability loaders (was two copy-pasted parse-and-index blocks).

    Rows go through _none_for_missing() so a missing cell reaches the card as None rather than
    float('nan') — see that docstring for why None specifically, and for the list-column hazard."""
    if path is None:
        return {}
    try:
        import pandas as pd

        df = pd.read_parquet(path)
    except FileNotFoundError:
        return {}  # cache file vanished between the exists() check and the read (race) — absent
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
        rec = _none_for_missing(row.to_dict())
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
        # Resolve (bucket, key) from the catalog manifest OUTSIDE the try (see _ensure_derived_cached).
        bucket, key = bucket_key_for(LIGAND_MANIFEST_ID)
        try:
            s3 = _boto3_client()
            s3.download_file(bucket, key, str(CACHE_LIGAND_PARQUET))
            _LIGAND_STATUS = True
            return CACHE_LIGAND_PARQUET
        except Exception as e:
            # Same transient-vs-definitive discipline as _ensure_derived_cached: latch False + return
            # None ONLY on genuine absence (404/NoSuchKey); RAISE on transient/creds/broken-env so the
            # outer @lru_cache on _load_ligandability_indexed does not memoize an empty index off one
            # blip (would poison the SM-ligandability call process-wide). 403 is NOT definitive.
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (
                code in ("404", "NoSuchKey")
                or e.__class__.__name__ in ("NoSuchKey", "404")
                or isinstance(e, FileNotFoundError)
            )
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
    # `or`, not `.get(k, default)` — see _hotspot_summary's docstring for why a .get default cannot fire
    # on a present key. Defensive here too: measured on the shipped product, structural_ligandability_class
    # has 0 null cells and all six axis flags are true `bool` dtype, which cannot represent a missing value
    # — so bool(nan) is not reachable on this leg and these wrappers are already correct.
    return {
        "structural_ligandability_class": row.get("structural_ligandability_class") or "insufficient_evidence",
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
        base = _empty_result("target_not_in_structure_features") if row is None else _hotspot_summary(row)
    # LIVE ligandability leg (always merged; independent of the hotspot product).
    base.update(_ligandability_fields(target))
    return base


def _hotspot_summary(row) -> dict:
    """The hotspot-adjacency summary fields from a hotspot-product row.

    The declared fallbacks below are spelled `or`, NOT `.get(key, default)`, because a `.get` default
    fires on an ABSENT KEY and never on a present-but-empty VALUE. Every one of these keys is PRESENT in
    every product row, so a `.get` default could not fire whatever the value was: not before
    _none_for_missing() (the value would be float('nan')) and not after it (the value is None).
    Converting the sentinel fixes a truthiness guard for free; it does NOT fix a `.get` default.

    ⚠️ These three rewrites are DEFENSIVE, not bug fixes — measured on the shipped product, the columns
    they guard have no missing cells at all (hotspot_pocket_adjacency_call and pdb_best_method are
    object/0 null, n_domains_low_plddt is int64 so it cannot hold one). They are here so the declared
    default is the value that actually ships if that ever changes, which is the property the old
    spelling only appeared to have. The genuine defect this function had is in the two classifiers
    below, which read the float64 columns.
    """
    return {
        "hotspot_pocket_adjacency_call": row.get("hotspot_pocket_adjacency_call") or "no_structure",
        "mutation_hotspot_in_druggable_pocket": bool(row.get("mutation_hotspot_in_druggable_pocket", False)),
        "pdb_coverage_class": _classify_pdb_coverage(row),
        "alphafold_confidence_class": _classify_alphafold_confidence(row),
        "pdb_ids_available": _coerce_id_list(row.get("pdb_ids_available")),
        "pdb_best_resolution_angstrom": row.get("pdb_best_resolution_angstrom"),
        "pdb_best_method": row.get("pdb_best_method") or "none",
        "alphafold_plddt_mean": row.get("alphafold_plddt_mean"),
        "alphafold_plddt_min": row.get("alphafold_plddt_min"),
        "alphafold_plddt_min_domain": row.get("alphafold_plddt_min_domain"),
        "n_domains_low_plddt": row.get("n_domains_low_plddt") or 0,
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
