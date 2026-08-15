"""dgidb_drug_gene.read — per-target known-drug / druggable-category tractability (the PHARMACOLOGY leg).

Complements the tractability-small-molecule gate's STRUCTURE leg (structure-features-static /
structure-ligandability-per-protein-v1) with a KNOWN-DRUG signal: has a drug actually been
catalogued against this gene, and is it in a recognized druggable-genome category? Reads the
per-gene DGIdb rollup (dgidb-drug-gene-per-gene-v1, gene-symbol keyed).

known_drug_tractability_class (first match — strongest wins, mirrors the product's druggability_tier):
  approved_drug_tractable   — >=1 APPROVED-drug interaction (a drug against this target is approved)
  clinically_actionable     — DGIdb CLINICALLY ACTIONABLE category (clinically-relevant drug, not
                              necessarily approved for this gene)
  druggable_genome          — DGIdb DRUGGABLE GENOME category (recognized druggable family), no
                              approved drug / clinical-actionability flag yet
  interaction_only          — has catalogued drug interactions but no druggable category / approval
  category_only             — in a druggable family category but no interaction rows
  no_known_drug_evidence    — gene absent from DGIdb (coverage gap — NOT 'undruggable')

Ordering note vs the product's tier: we hoist APPROVED-drug above clinically_actionable for the
verdict-facing class (an approved drug is the harder pharmacology fact), while the product keeps the
DGIdb-native tier. Both are carried.

FORWARD-vs-RETROSPECTIVE: this is complementary to the PRISM cell-line cards. PRISM asks "does a
compound kill THIS cell line"; DGIdb asks "is there ANY catalogued drug-gene interaction (approved,
tool, or indirect) + druggable-category membership" — a broader, target-intrinsic pharmacology prior.
Absence in DGIdb is a coverage gap, never evidence of undruggability (measured-vs-null discipline).

STALENESS: the underlying DGIdb data self-reports Dec-2023 / v5.0.11 (the source is tagged 2026-06b
but repackaged). See the data-catalog source manifest dgidb-2026-06b.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

PRODUCT_MANIFEST_ID = "dgidb-drug-gene-per-gene-v1"
METHOD_VERSION = "0.1.0"


def _read_dgidb_row(target: str) -> Optional[dict]:
    """Pushdown-read the per-gene DGIdb rollup for one gene symbol. None if unresolvable/absent."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
                            filters=[("gene_symbol", "=", (target or "").strip().upper())])
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # A GENUINELY absent object (NoSuchKey/404, or pyarrow/s3fs FileNotFoundError) means the
        # DGIdb product truly has no row for this gene -> None -> _classify(None) ->
        # no_known_drug_evidence, the honest coverage-gap class (unchanged semantics; a gene absent
        # from DGIdb legitimately has no known drug). A transient/creds/broken-env failure (throttle,
        # expired token, missing pyarrow) is NOT absence -> re-raise so the live-read seam surfaces an
        # honest _live_read_error, never a false "no_known_drug_evidence" for a live gene.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def _classify(row: Optional[dict]) -> str:
    """Map a DGIdb rollup row -> known_drug_tractability_class (approved hoisted above clinical)."""
    if row is None:
        return "no_known_drug_evidence"
    if bool(row.get("has_approved_drug")):
        return "approved_drug_tractable"
    if bool(row.get("is_clinically_actionable")):
        return "clinically_actionable"
    if bool(row.get("is_druggable_genome")):
        return "druggable_genome"
    if int(row.get("n_drug_interactions") or 0) >= 1:
        return "interaction_only"
    if int(row.get("n_categories") or 0) >= 1:
        return "category_only"
    return "no_known_drug_evidence"


def known_drug_tractability_for_gene(target: str, dgidb_row: Optional[dict] = None) -> dict:
    """Per-target known-drug / druggable-category tractability. dgidb_row may be injected for tests."""
    sym = (target or "").strip().upper()
    row = dgidb_row if dgidb_row is not None else _read_dgidb_row(sym)
    klass = _classify(row)
    return {
        "known_drug_tractability_class": klass,
        "druggability_tier": (row or {}).get("druggability_tier"),      # DGIdb-native tier (passthrough)
        "is_druggable_genome": bool((row or {}).get("is_druggable_genome", False)),
        "is_clinically_actionable": bool((row or {}).get("is_clinically_actionable", False)),
        "has_approved_drug": bool((row or {}).get("has_approved_drug", False)),
        "n_drug_interactions": int((row or {}).get("n_drug_interactions") or 0),
        "n_approved_drug_interactions": int((row or {}).get("n_approved_drug_interactions") or 0),
        "n_antineoplastic_interactions": int((row or {}).get("n_antineoplastic_interactions") or 0),
        "gene_categories": (row or {}).get("gene_categories"),
        "known_drug_context": _context(sym, klass, row),
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }


def _context(sym: str, klass: str, row: Optional[dict]) -> Optional[str]:
    if klass == "no_known_drug_evidence":
        return (f"{sym}: absent from DGIdb (no catalogued drug-gene interaction or druggable "
                f"category). A coverage gap — NOT evidence of undruggability.")
    n_int = int((row or {}).get("n_drug_interactions") or 0)
    n_appr = int((row or {}).get("n_approved_drug_interactions") or 0)
    n_antineo = int((row or {}).get("n_antineoplastic_interactions") or 0)
    cats = (row or {}).get("gene_categories") or ""
    if klass == "approved_drug_tractable":
        return (f"{sym}: {n_appr} approved-drug interaction(s) of {n_int} total "
                f"({n_antineo} antineoplastic) in DGIdb — a drug against this target is approved "
                f"(known-drug tractability demonstrated). Categories: {cats}.")
    if klass == "clinically_actionable":
        return (f"{sym}: DGIdb CLINICALLY ACTIONABLE ({n_int} drug interactions, {n_antineo} "
                f"antineoplastic) — a clinically-relevant drug exists. Categories: {cats}.")
    if klass == "druggable_genome":
        return (f"{sym}: in the DGIdb DRUGGABLE GENOME category ({n_int} interactions) — a "
                f"recognized druggable family, no approved/clinically-actionable flag yet. Categories: {cats}.")
    if klass == "interaction_only":
        return (f"{sym}: {n_int} catalogued drug interaction(s) but no druggable-category membership.")
    if klass == "category_only":
        return (f"{sym}: in a DGIdb family category ({cats}) but no catalogued drug interactions.")
    return None
