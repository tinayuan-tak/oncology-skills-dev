"""measured_potency_tractability.read — per-target MEASURED small-molecule potency from ChEMBL + BindingDB.

The tractability review (T3.1) found chembl-bioactivity-per-protein-v1 + bindingdb-affinity-per-protein-v1
INERT — both materialized on S3, consumed by nothing — even though their manifests say they were built
"for tractability-small-molecule". They carry the one dimension the SM axis lacked: MEASURED binding
potency + clinical phase. The existing chemical legs are retrospective cell-line killing (PRISM),
predicted pockets (structure composite), and a presence-not-potency drug catalogue (DGIdb, a Dec-2023
snapshot). This reader fuses the two measured-potency products into a `measured_bioactivity_class` so
"is there a POTENT (<=1 uM) chemical start point?" — a med-chemist's first question — becomes a signal.

FUSION (max-potency-wins over the two independent sources):
  potent_measured_ligand   ChEMBL best_pchembl >= 6 (<=1 uM) OR BindingDB has_sub_micromolar_binder
                            (best_p_affinity >= 6) — a real potent chemical handle.
  weak_measured_ligand      measured activity in >=1 source but NOT potent (best below the 1 uM bar).
  no_measured_activity      present in >=1 source but no measured activity value at all.
  data_unavailable          absent from BOTH products (a coverage gap, NOT a negative).

LICENSE: ChEMBL is CC-BY-SA-3.0 (share-alike). This reader consumes ONLY the AGGREGATE rollup columns
(best_pchembl / n_potent_ligands / max_clinical_phase — counts + maxima, not raw activity rows), which
the derived product already reduced to (PLINDER applied the same discipline). No raw-affinity passthrough.

CONSUMES the DERIVED products (payload + resolver sidecar), NOT the raw sources. Both are UniProt-keyed;
symbol->AC via each product's sidecar (same discipline as the GPI / CSPA readers). Absent-from-both is
data_unavailable (coverage gap), NEVER a false negative.
"""

from __future__ import annotations

import io
from functools import lru_cache
from typing import Optional

from onc_methods.catalog_query.read import bucket_key_for, sidecar_bucket_key_for

METHOD_VERSION = "0.3.0"  # 2026-09-04: + chembl_approved_engagement_class (directness-gated approved signal, shared DGIdb-directional metric)     # 2026-08-24: + chembl_clinical_phase_class (rule-matchable real-phase categorical)
CHEMBL_MANIFEST_ID = "chembl-bioactivity-per-protein-v1"
BINDINGDB_MANIFEST_ID = "bindingdb-affinity-per-protein-v1"
POTENT_PCHEMBL = 6.0  # -log10(M); pchembl/p_affinity >= 6 == <= 1 uM (the per-activity potent bar)
# CALIBRATION (verified against the live product): best_pchembl>=6 fires for 3,753/5,720 proteins (66%)
# — a SINGLE potent activity is near-universal for any studied gene, a weak discriminator. The real
# gradient is the NUMBER of potent ligands (a chemotype SAR series vs one reported binder): n_potent
# median 2, 75th pct 31, and >=10 => 1,859 proteins. So `potent_measured_ligand` (the STRONG signal)
# requires a potent-ligand SERIES; a handful of potent hits is `weak_measured_ligand`. This avoids the
# over-call the review flagged for predicted_ligandable (71% of proteome on a single weak axis).
POTENT_SERIES_MIN = 10  # >= this many potent (<=1 uM) ligands = a real chemotype series
DEFAULT_AWS_PROFILE = "cbg"


from onc_methods.target_id_sidecar import ensure_aws_profile


def _read_parquet(path_or_none, bucket, key):
    import pandas as pd

    if path_or_none is not None:
        return pd.read_parquet(path_or_none)
    ensure_aws_profile()
    # shared client: AWS_PROFILE=cbg + adaptive-retry Config (absorbs transient S3 throttling on
    # batch reads — the failure mode that silently dropped cards on full dossier runs).
    from onc_methods.target_id_sidecar import s3_client

    body = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def _index_product(manifest_id: str, payload_path=None, sidecar_path=None):
    """Return (row_by_ac: dict, symbol_to_ac: dict) for a UniProt-keyed product. None if unavailable.

    Definitive-vs-transient discipline: a genuine NoSuchKey/404 (product absent) returns None →
    honest data_unavailable. A broken-env / transient-S3 (throttle/timeout) / creds error RE-RAISES
    so the live-read seam surfaces an honest _live_read_error rather than a silent dead axis — and,
    critically, so the @lru_cache on _load_indexed does NOT memoize a poisoned None (lru_cache does
    not cache exceptions, so a raised transient failure is retried on the next target in the batch)."""
    try:
        bucket, pkey = bucket_key_for(manifest_id)
        payload = _read_parquet(payload_path, bucket, pkey)
    except Exception as e:  # noqa: BLE001
        from onc_methods.target_id_sidecar import is_definitively_absent

        if not is_definitively_absent(e):
            raise
        return None
    row_by_ac = {}
    for rec in payload.to_dict("records"):
        ac = str(rec.get("uniprot_id", "")).strip()
        if ac:
            row_by_ac[ac] = rec
    symbol_to_ac = {}
    try:
        _, skey = sidecar_bucket_key_for(manifest_id)
        sc = _read_parquet(sidecar_path, bucket, skey)
        if "hgnc_primary_symbol_at_resolution" in sc.columns and "native_row_key" in sc.columns:
            for sym, ac in zip(sc["hgnc_primary_symbol_at_resolution"].values, sc["native_row_key"].values):
                if isinstance(sym, str) and sym.strip() and isinstance(ac, str):
                    symbol_to_ac[sym.strip().upper()] = ac.strip()
    except Exception as e:  # noqa: BLE001 — sidecar genuinely-absent: AC lookups still work.
        # A transient/creds/broken-env failure must NOT be masked (would silently drop symbol→AC
        # for the whole batch AND poison the lru_cache with a partial index) — re-raise it.
        from onc_methods.target_id_sidecar import is_definitively_absent

        if not is_definitively_absent(e):
            raise
    return row_by_ac, symbol_to_ac


@lru_cache(maxsize=1)
def _load_indexed(chembl_payload=None, chembl_sidecar=None, bdb_payload=None, bdb_sidecar=None):
    return (
        _index_product(CHEMBL_MANIFEST_ID, chembl_payload, chembl_sidecar),
        _index_product(BINDINGDB_MANIFEST_ID, bdb_payload, bdb_sidecar),
    )


def _lookup(idx, target):
    if idx is None:
        return None
    row_by_ac, symbol_to_ac = idx
    key = target.strip()
    ac = key if key in row_by_ac else symbol_to_ac.get(key.upper())
    return row_by_ac.get(ac) if ac else None


def _finite(x) -> bool:
    """True iff x is a real, finite measured value (not None, not NaN/inf). A ChEMBL row can EXIST
    with a NaN best_pchembl (present in ChEMBL, no quantified potency); the bare `is not None` test
    treats NaN as a real measurement (cards review 2026-08-17, S2 — GPR151 falsely read
    weak_measured_ligand with a NaN potency leaking into the output field)."""
    import math

    return x is not None and not (isinstance(x, float) and math.isnan(x))


def classify_measured_bioactivity(chembl_row: Optional[dict], bdb_row: Optional[dict]) -> str:
    """Fuse ChEMBL + BindingDB into the measured_bioactivity_class.

    STRONG (potent_measured_ligand) requires a potent-ligand SERIES (>= POTENT_SERIES_MIN potent
    ligands in ChEMBL, OR a BindingDB sub-micromolar-binder series) — not a single potent activity,
    which is near-universal for studied genes. A few potent hits or sub-potent measured activity is
    `weak_measured_ligand`. Max-wins across the two independent sources.
    """
    if chembl_row is None and bdb_row is None:
        return "data_unavailable"
    best_pchembl = (chembl_row or {}).get("best_pchembl")
    best_p_aff = (bdb_row or {}).get("best_p_affinity")
    chembl_n_potent = (chembl_row or {}).get("n_potent_ligands") or 0
    bdb_n_potent = (bdb_row or {}).get("n_potent_ligands") or 0

    # STRONG: a potent chemotype SERIES in either source.
    potent_series = (chembl_n_potent >= POTENT_SERIES_MIN) or (bdb_n_potent >= POTENT_SERIES_MIN)
    if potent_series:
        return "potent_measured_ligand"

    # WEAK: some measured potency exists (a potent hit or two, or sub-potent activity) but not a series.
    chembl_any_potent = _finite(best_pchembl) and best_pchembl >= POTENT_PCHEMBL
    bdb_any_potent = bool((bdb_row or {}).get("has_sub_micromolar_binder")) or (
        _finite(best_p_aff) and best_p_aff >= POTENT_PCHEMBL
    )
    has_measured = _finite(best_pchembl) or _finite(best_p_aff)  # NaN != a real measurement
    if chembl_any_potent or bdb_any_potent or has_measured:
        return "weak_measured_ligand"
    return "no_measured_activity"


def classify_chembl_clinical_phase(chembl_row: Optional[dict]) -> str:
    """Rule-matchable categorical from ChEMBL max_clinical_phase (2026-08-24 druggability audit).

    chembl_max_clinical_phase was pulled but DISPLAY-only; the SM clinical-precedent tier instead ran
    off a coarse PRISM `Prioritized`-flag proxy (highest_clinical_phase). This distils the REAL ChEMBL
    phase into a class the SM resolver can key on (authoritative over the PRISM proxy):
      approved            max_phase >= 4  — an approved drug hits this target (chemically_active tier)
      clinical            1 <= max_phase < 4 — a phase 1-3 compound (real clinical precedent)
      preclinical_or_none chembl row exists but phase < 1 / absent (incl. Early-Phase-1 0.5, conservatively)
      data_unavailable    no ChEMBL row for the target
    """
    if chembl_row is None:
        return "data_unavailable"
    try:
        ph = float(chembl_row.get("max_clinical_phase"))
    except (TypeError, ValueError):
        return "preclinical_or_none"
    if ph >= 4:
        return "approved"
    if ph >= 1:
        return "clinical"
    return "preclinical_or_none"


def classify_chembl_approved_engagement(phase_class: str, n_direct: Optional[int]) -> str:
    """Gate the ChEMBL APPROVED signal on DIRECT engagement — the SAME directness metric the DGIdb leg
    uses (typed direct-SM interactions in dgidb-drug-target-directional-v1). Mirrors dgidb_drug_gene's
    approved_drug_engagement_class so the ChEMBL-approved rung (max_phase>=4 → chemically_active) cannot
    inflate an undruggable TF/scaffold whose approved-phase compounds are INDIRECT (β-catenin, MYC).
    Directness UNMEASURED (transient read) fails toward approved_direct (never demote on a read failure).
      approved_direct        ChEMBL max_phase>=4 AND (>=5 typed-direct interactions OR directness unmeasured)
      approved_indirect_only ChEMBL max_phase>=4 BUT indirect/sparse roster
      not_chembl_approved     ChEMBL max_phase<4 / absent (the approved rung never applied)
    """
    if phase_class != "approved":
        return "not_chembl_approved"
    from onc_methods.dgidb_drug_gene.read import DIRECT_ENGAGEMENT_MIN

    if n_direct is None or n_direct >= DIRECT_ENGAGEMENT_MIN:
        return "approved_direct"
    return "approved_indirect_only"


def measured_potency_for_gene(
    target: str,
    chembl_row: Optional[dict] = None,
    bdb_row: Optional[dict] = None,
    chembl_payload=None,
    chembl_sidecar=None,
    bdb_payload=None,
    bdb_sidecar=None,
    directional_direct_count: Optional[int] = None,
) -> dict:
    """Per-target measured-potency summary_fields. rows may be injected for tests.
    directional_direct_count may be injected for tests; None triggers a live directional read UNLESS
    chembl_row was injected (hermetic unit-test path → directness left unmeasured)."""
    live = chembl_row is None and bdb_row is None
    if live:
        chembl_idx, bdb_idx = _load_indexed(chembl_payload, chembl_sidecar, bdb_payload, bdb_sidecar)
        chembl_row = _lookup(chembl_idx, target)
        bdb_row = _lookup(bdb_idx, target)

    klass = classify_measured_bioactivity(chembl_row, bdb_row)
    phase_class = classify_chembl_clinical_phase(chembl_row)
    # DIRECTNESS (2026-09-04): count typed direct-SM interactions (reuse the DGIdb directional leg). Live
    # read only when nothing was injected; a transient failure leaves directness unmeasured (fail-safe).
    if directional_direct_count is None and live:
        from onc_methods.dgidb_drug_gene.read import _count_direct, _read_directional_rows

        directional_direct_count = _count_direct(_read_directional_rows(target))
    chembl_approved_engagement = classify_chembl_approved_engagement(phase_class, directional_direct_count)
    best_pchembl = (chembl_row or {}).get("best_pchembl")
    best_p_aff = (bdb_row or {}).get("best_p_affinity")
    # best measured potency across the two sources (both are -log10 M, directly comparable)
    best_measured = max([v for v in (best_pchembl, best_p_aff) if _finite(v)], default=None)
    return {
        "measured_bioactivity_class": klass,
        "best_measured_potency_neglog_m": best_measured,  # -log10(M); >=6 == <=1 uM
        "chembl_best_pchembl": best_pchembl,
        "chembl_n_potent_ligands": (chembl_row or {}).get("n_potent_ligands"),
        "chembl_max_clinical_phase": (chembl_row or {}).get("max_clinical_phase"),
        "chembl_clinical_phase_class": phase_class,  # rule-matchable (2026-08-24)
        # DIRECTNESS-gated approved signal (2026-09-04): the ChEMBL-approved rung keys on THIS, not the raw
        # phase class, so an approved-phase compound annotated against an undruggable TF (indirect) does not
        # inflate to chemically_active. n_direct from dgidb-drug-target-directional-v1 (shared metric).
        "chembl_approved_engagement_class": chembl_approved_engagement,
        "n_direct_interactions": directional_direct_count,
        "bindingdb_best_p_affinity": best_p_aff,
        "bindingdb_n_potent_ligands": (bdb_row or {}).get("n_potent_ligands"),
        "measured_potency_context": _context(target, klass, best_measured),
        "method_version": METHOD_VERSION,
        "_data_source": f"{CHEMBL_MANIFEST_ID} + {BINDINGDB_MANIFEST_ID}",
    }


def _context(sym, klass, best_measured) -> Optional[str]:
    if klass == "potent_measured_ligand":
        pot = f" (best {best_measured:.1f} -log10 M, <= 1 uM)" if best_measured is not None else ""
        return (
            f"{sym}: a POTENT measured small-molecule ligand exists{pot} (ChEMBL/BindingDB). A real "
            f"sub-micromolar chemical start point — stronger than a predicted pocket or a bare drug "
            f"catalogue entry."
        )
    if klass == "weak_measured_ligand":
        return (
            f"{sym}: measured small-molecule activity exists but is WEAK (best affinity above the "
            f"1 uM potent bar). A starting point that needs optimization."
        )
    if klass == "no_measured_activity":
        return (
            f"{sym}: present in a bioactivity source but no measured potency value — chemical matter "
            f"is annotated but unquantified."
        )
    return None
