"""opentargets_clingen — P5 Slice 3: dosage-sensitivity safety from ClinGen gene-disease validity.

Reads Open Targets 26.06 `evidence_clingen` (ClinGen curated gene-disease validity, ENSG-keyed,
~2,887 genes × avg 1.6 rows) → dosage_sensitivity_class. The dosage-sensitivity question for
safety: is losing ONE copy pathogenic (haploinsufficiency / autosomal-dominant loss = the highest
degrader/full-inhibition concern), or does disease require BOTH copies lost (recessive = lower
single-allele concern)?

SCHEMA-VERIFIED (2026-07-24): ClinGen has NO explicit dosage column. The signal is DERIVED from
`allelicRequirements` (AR 2,387 / AD 1,709 / XL / MT / SD / UD), gated on `confidence`
(Definitive 2,895 / Strong 98 / Moderate / Limited / Disputed / Refuted).

KEY REDUCTION SUBTLETY: a gene can be BOTH AD and AR across different diseases (BRCA1: AD for
cancer-predisposition, AR for Fanconi anemia). Dosage sensitivity is an ANY-association property:
if the gene has ANY high-confidence AUTOSOMAL-DOMINANT association, losing one copy is pathogenic
for at least that disease → autosomal_dominant_loss (the safety-relevant class). Only when the
gene's high-confidence associations are exclusively recessive → dosage_sufficient.

data_unavailable-safe.
"""
from __future__ import annotations

from typing import Optional

from ..opentargets_common import read_entity, symbol_to_ensembl

METHOD_VERSION = "0.1.0"

# Only high-confidence gene-disease validity counts toward the dosage call (Disputed/Refuted/
# Limited/No-Known are excluded — a disputed dominant claim must not fire a safety concern).
_HIGH_CONFIDENCE = {"Definitive", "Strong"}

# allelicRequirements tokens indicating single-allele (dominant) pathogenicity.
_DOMINANT_TOKENS = {"AD"}          # autosomal dominant — one hit suffices (haploinsufficiency proxy)
_RECESSIVE_TOKENS = {"AR"}         # autosomal recessive — needs both copies
# XL/MT/SD/UD: X-linked / mitochondrial / semidominant / undetermined — not a clean autosomal-
# dosage call; recorded but neither fires the dominant-loss safety concern nor the recessive class.

_FIELDS = ["targetId", "confidence", "allelicRequirements", "diseaseFromSource", "score"]


def _tokens(allelic_requirements) -> set:
    """Normalize the allelicRequirements list (or scalar/None) to a set of upper tokens."""
    if allelic_requirements is None:
        return set()
    if isinstance(allelic_requirements, str):
        items = [allelic_requirements]
    else:
        try:
            items = list(allelic_requirements)
        except TypeError:
            return set()
    return {str(x).strip().upper() for x in items if x is not None and str(x).strip()}


def classify_dosage(rows: list) -> dict:
    """Pure classifier: a gene's ClinGen rows → dosage_sensitivity_class + evidence.

    Fully unit-testable with dict fixtures. Decision (high-confidence rows only):
      1. Keep confidence ∈ {Definitive, Strong}. None → no_clingen_entry.
      2. If ANY high-confidence row is autosomal-dominant (AD) → autosomal_dominant_loss
         (single-allele loss is pathogenic — the haploinsufficiency safety concern).
      3. Else if any high-confidence row is autosomal-recessive (AR) → dosage_sufficient
         (disease needs both copies; lower single-allele safety concern).
      4. Else (only XL/MT/SD/UD high-confidence) → unresolved.
    """
    hc = [r for r in rows if r.get("confidence") in _HIGH_CONFIDENCE]
    if not hc:
        # rows exist but none high-confidence → the gene is in ClinGen but no confident dosage call
        return {"dosage_sensitivity_class": "no_clingen_entry" if not rows else "unresolved",
                "n_high_confidence": 0, "n_total_rows": len(rows),
                "allelic_requirements": sorted({t for r in rows for t in _tokens(r.get("allelicRequirements"))}),
                "top_disease": None, "top_confidence": None}

    ad_rows = [r for r in hc if _tokens(r.get("allelicRequirements")) & _DOMINANT_TOKENS]
    ar_rows = [r for r in hc if _tokens(r.get("allelicRequirements")) & _RECESSIVE_TOKENS]

    if ad_rows:
        cls = "autosomal_dominant_loss"
        pool = ad_rows
    elif ar_rows:
        cls = "dosage_sufficient"
        pool = ar_rows
    else:
        cls = "unresolved"
        pool = hc

    # representative row: prefer Definitive over Strong within the winning pool, for the disease label.
    pool_sorted = sorted(pool, key=lambda r: 0 if r.get("confidence") == "Definitive" else 1)
    top = pool_sorted[0] if pool_sorted else hc[0]

    return {
        "dosage_sensitivity_class": cls,
        "n_high_confidence": len(hc),
        "n_total_rows": len(rows),
        "n_autosomal_dominant": len(ad_rows),
        "n_autosomal_recessive": len(ar_rows),
        "allelic_requirements": sorted({t for r in hc for t in _tokens(r.get("allelicRequirements"))}),
        "top_disease": top.get("diseaseFromSource"),
        "top_confidence": top.get("confidence"),
    }


def read_clingen_dosage(target: str, indication: Optional[str] = None) -> dict:
    """ClinGen dosage-sensitivity safety summary for `target` (HGNC symbol or ENSG).

    `indication` accepted for signature-uniformity but NOT used — gene-disease validity is per-gene
    across many diseases; top_disease surfaces the dominant-loss disease driving the call.
    """
    ensg = symbol_to_ensembl(target)
    base = {"target": target, "ensembl_gene_id": ensg, "method_version": METHOD_VERSION,
            "source": "opentargets-26-06/evidence_clingen"}
    if ensg is None:
        return {**base, "dosage_sensitivity_class": "insufficient",
                "_note": "target not resolvable to an Ensembl gene id via the OT resolver sidecar"}

    df = read_entity("evidence_clingen", columns=_FIELDS)
    if df.empty:
        return {**base, "dosage_sensitivity_class": "insufficient",
                "_note": "evidence_clingen entity not available"}
    hit = df[df["targetId"] == ensg]
    if hit.empty:
        return {**base, "dosage_sensitivity_class": "no_clingen_entry",
                "n_total_rows": 0, "_note": f"{ensg} has no ClinGen gene-disease validity rows"}

    return {**base, **classify_dosage(hit.to_dict("records"))}


def _main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="OT ClinGen dosage-sensitivity safety for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default=None)
    args = ap.parse_args(argv)
    print(json.dumps(read_clingen_dosage(args.target, args.indication), indent=2, default=str))


if __name__ == "__main__":
    _main()
