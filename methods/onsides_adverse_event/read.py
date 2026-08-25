"""onsides_adverse_event.read — per-target OnSIDES adverse-drug-event CONTEXT (verdict-INERT).

Attaches an OnSIDES drug-label adverse-drug-event (ADE) profile to a TARGET GENE by reading the
per-gene rollup onsides-adverse-event-per-gene-v1 (gene-symbol keyed). This is a pharmacovigilance
CONTEXT layer for on-target-safety-liability — per-MedDRA-term ADE granularity beyond Open Targets'
coarse per-target drug-warning boolean. It is a DISPLAY signal, NOT a verdict input (see the two
honest limits below), same posture as the OT drug-warning card.

## Two honest limits (carried, never papered over)

1. FUZZY drug-name->gene join. The per-gene product has NO curated gene column; it is built by a
   normalized drug-NAME string match (OnSIDES ingredient_name -> DGIdb drug_name_norm -> gene_symbol),
   match-rate ~63% of OnSIDES ingredients. DGIdb directional interactions are a RECALL UNION, so a
   multi-target drug attributes its whole ADE list to EVERY gene it engages -> the signal is
   DRUG-LEVEL and class-wide and CANNOT separate on-target from off-target toxicity. Absence
   (no_mapped_drug_ade) is a coverage gap (the fuzzy join mapped no drug to the gene), NEVER evidence
   of safety (measured-vs-null discipline).

2. PER-MedDRA-TERM grain only. Per-organ / System-Organ-Class rollup needs the licensed MedDRA MDHIER
   hierarchy (not in the catalog), so this emits term COUNTS + a boxed-warning severity flag, not a
   per-organ liability map.

onsides_ade_class (first match wins):
  boxed_warning_ade    — >=1 mapped drug carries a BOXED-WARNING ADE (the high-severity signal)
  labeled_ade_profile  — mapped drug(s) with labeled ADE terms, none in a boxed warning
  no_mapped_drug_ade   — gene absent from the product (fuzzy drug->gene join mapped no drug) — a
                        coverage gap, NOT evidence of safety
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

PRODUCT_MANIFEST_ID = "onsides-adverse-event-per-gene-v1"
METHOD_VERSION = "0.1.0"


def _read_onsides_row(target: str) -> Optional[dict]:
    """Pushdown-read the per-gene OnSIDES ADE rollup for one gene symbol. None if unresolvable/absent.

    Absence discipline (mirrors methods/dgidb_drug_gene): a GENUINELY absent object (NoSuchKey/404 or
    pyarrow FileNotFoundError) -> None -> no_mapped_drug_ade (the honest coverage-gap class). A
    transient / creds / broken-env failure is re-raised so the live-read seam surfaces an honest error
    rather than a false "no ADE" for a live gene."""
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
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def _classify(row: Optional[dict]) -> str:
    """Map a per-gene OnSIDES rollup row -> onsides_ade_class (boxed-warning severity hoisted)."""
    if row is None:
        return "no_mapped_drug_ade"
    if bool(row.get("has_boxed_warning")):
        return "boxed_warning_ade"
    if int(row.get("n_meddra_terms") or 0) >= 1 or int(row.get("n_drugs_mapped") or 0) >= 1:
        return "labeled_ade_profile"
    return "no_mapped_drug_ade"


def read_target_summary(target: str, indication: Optional[str] = None,
                        onsides_row: Optional[dict] = None) -> dict:
    """Per-target OnSIDES ADE summary (verdict-INERT context).

    indication is accepted for the generic reader dispatch contract but is IGNORED — OnSIDES ADEs are
    drug-label-derived and indication-independent (a drug's label ADEs are not per-tumor-type).
    onsides_row may be injected for hermetic tests.
    """
    sym = (target or "").strip().upper()
    row = onsides_row if onsides_row is not None else _read_onsides_row(sym)
    klass = _classify(row)
    return {
        "onsides_ade_class": klass,
        "n_drugs_mapped": int((row or {}).get("n_drugs_mapped") or 0),
        "n_meddra_terms": int((row or {}).get("n_meddra_terms") or 0),
        "has_boxed_warning": bool((row or {}).get("has_boxed_warning", False)),
        "n_boxed_warning_terms": int((row or {}).get("n_boxed_warning_terms") or 0),
        "n_high_confidence_terms": int((row or {}).get("n_high_confidence_terms") or 0),
        "example_terms": (row or {}).get("example_terms"),
        "example_boxed_warning_terms": (row or {}).get("example_boxed_warning_terms"),
        "example_drugs": (row or {}).get("example_drugs"),
        "onsides_ade_context": _context(sym, klass, row),
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }


def _context(sym: str, klass: str, row: Optional[dict]) -> Optional[str]:
    if klass == "no_mapped_drug_ade":
        return (f"{sym}: no drug fuzzy-mapped to this gene in the OnSIDES per-gene ADE product "
                f"(the drug-name->gene join found no mapped drug). A coverage gap — NOT evidence of "
                f"safety.")
    n_drugs = int((row or {}).get("n_drugs_mapped") or 0)
    n_terms = int((row or {}).get("n_meddra_terms") or 0)
    n_bw = int((row or {}).get("n_boxed_warning_terms") or 0)
    drugs = (row or {}).get("example_drugs") or ""
    caveat = ("Drug-level, class-wide via a fuzzy drug-name join (recall-union over every gene a drug "
              "engages) — CANNOT separate on-target from off-target; context only, not a verdict input.")
    if klass == "boxed_warning_ade":
        bw_terms = (row or {}).get("example_boxed_warning_terms") or ""
        return (f"{sym}: {n_drugs} mapped drug(s), {n_terms} labeled MedDRA ADE term(s), {n_bw} in a "
                f"BOXED WARNING (e.g. {bw_terms}). Mapped drugs: {drugs}. {caveat}")
    if klass == "labeled_ade_profile":
        terms = (row or {}).get("example_terms") or ""
        return (f"{sym}: {n_drugs} mapped drug(s), {n_terms} labeled MedDRA ADE term(s), no boxed "
                f"warning (e.g. {terms}). Mapped drugs: {drugs}. {caveat}")
    return None
