"""opentargets_gene_burden — human-genetics LoF-tolerance safety signal.

Reads Open Targets 26.06 `evidence_gene_burden` (rare-variant burden associations, ENSG-keyed,
~2,091 genes × avg 21 disease/study rows) and emits the `gene-burden-safety` card summary — the
FIRST verdict-moving card.

THE DIRECTION GUARDRAIL: every burden row is LoF-on-target
(`directionOnTarget` is uniformly 'LoF'), so the discriminating signal is `directionOnTrait`:
  - `risk`    → LoF variants INCREASE disease risk → WT-loss is harmful → the safety signal that,
                for a full-KO modality (degrader / full-inhibition SM), warrants a hold.
  - `protect` → LoF variants are PROTECTIVE → drug-positive (loss is beneficial), NOT a safety hold.
  - conflict / null → direction_unresolved (405 genes carry BOTH significant risk+protect rows;
                honest non-firing, never a false hold).
Only `lof_risk_phenotype` fires the WT-loss warning; gof/protective/unresolved are caveats. Composes
with the mutant-selective downgrade (an activating GoF driver drugged mutant-selectively spares the
WT protein the burden signal is about) — wired in the resolver, not here.

Significance from the p-value (pValueMantissa × 10^pValueExponent); `beta` is frequently null so it
is corroborating only, not the gate. data_unavailable-safe.
"""
from __future__ import annotations

from typing import Optional

from ..opentargets_common import read_entity, symbol_to_ensembl, ot_cli_main

METHOD_VERSION = "0.1.0"

# Significance gate for a burden row to count toward the direction call. OT burden studies are
# well-powered; 1e-6 is a conservative exome-wide-ish threshold (44,198 of 44,555 rows pass, so this
# is a floor that excludes only the weakest — the direction call rests on the SIGNIFICANT rows).
_PVALUE_CUTOFF = 1e-6

_FIELDS = ["targetId", "directionOnTrait", "pValueMantissa", "pValueExponent", "beta",
           "diseaseFromSource", "oddsRatio", "ancestry", "statisticalMethod"]


def _pvalue(mantissa, exponent) -> Optional[float]:
    """Compose OT's split p-value (mantissa × 10^exponent). None if either part is missing."""
    if mantissa is None or exponent is None:
        return None
    try:
        return float(mantissa) * (10.0 ** float(exponent))
    except (TypeError, ValueError, OverflowError):
        return None


def classify_burden(rows: list) -> dict:
    """Pure classifier: a gene's burden rows → burden_safety_class + direction evidence.

    `rows` = list of dicts with directionOnTrait + p-value parts (the method's assembled slice).
    Fully unit-testable with dict fixtures, no S3. Decision:
      1. Keep only significant rows (p < cutoff). None → no_burden_signal.
      2. Among significant rows, tally directionOnTrait risk vs protect.
      3. risk-only → lof_risk_phenotype; protect-only → protective;
         both present → direction_unresolved; neither (all null-direction) → direction_unresolved.
    """
    sig = []
    for r in rows:
        pv = _pvalue(r.get("pValueMantissa"), r.get("pValueExponent"))
        if pv is not None and pv < _PVALUE_CUTOFF:
            sig.append((r.get("directionOnTrait"), pv, r))
    if not sig:
        return {"burden_safety_class": "no_burden_signal", "n_significant": 0,
                "n_total_rows": len(rows), "min_pvalue": None, "directions": [],
                "top_disease": None, "direction_on_target": "LoF"}

    risk = [s for s in sig if s[0] == "risk"]
    protect = [s for s in sig if s[0] == "protect"]
    if risk and protect:
        cls = "direction_unresolved"
    elif risk:
        cls = "lof_risk_phenotype"
    elif protect:
        cls = "protective"
    else:
        cls = "direction_unresolved"   # significant rows but all null-direction

    # representative row = the most-significant one of the WINNING direction (for the disease label).
    pool = risk if cls == "lof_risk_phenotype" else protect if cls == "protective" else sig
    pool_sorted = sorted(pool, key=lambda s: s[1])   # ascending p-value
    top = pool_sorted[0] if pool_sorted else sig[0]
    top_row = top[2] if len(top) > 2 else {}

    return {
        "burden_safety_class": cls,
        "n_significant": len(sig),
        "n_total_rows": len(rows),
        "min_pvalue": float(f"{min(s[1] for s in sig):.3g}"),
        "n_risk": len(risk),
        "n_protect": len(protect),
        "directions": sorted({s[0] for s in sig if s[0]}),
        "top_disease": top_row.get("diseaseFromSource"),
        "top_ancestry": top_row.get("ancestry"),
        "top_statistical_method": top_row.get("statisticalMethod"),
        # directionOnTarget is uniformly LoF in OT 26.06 — surfaced so the card records WHY
        # directionOnTrait is the discriminator (see module docstring).
        "direction_on_target": "LoF",
    }


def read_gene_burden(target: str, indication: Optional[str] = None) -> dict:
    """gene-burden safety summary for `target` (HGNC symbol or ENSG).

    `indication` accepted for signature-uniformity but NOT used — burden associations are per-gene
    across many diseases; the card reports the gene-level human-genetics tolerance signal, and the
    top_disease field surfaces which trait drove the call.
    """
    ensg = symbol_to_ensembl(target)
    base = {"target": target, "ensembl_gene_id": ensg, "method_version": METHOD_VERSION,
            "source": "opentargets-26-06/evidence_gene_burden", "pvalue_cutoff": _PVALUE_CUTOFF}
    if ensg is None:
        return {**base, "burden_safety_class": "insufficient",
                "_note": "target not resolvable to an Ensembl gene id via the OT resolver sidecar"}

    df = read_entity("evidence_gene_burden", columns=_FIELDS, filter_col="targetId", filter_val=ensg)
    if df.empty:
        return {**base, "burden_safety_class": "insufficient",
                "_note": "evidence_gene_burden entity not available"}
    hit = df[df["targetId"] == ensg]
    if hit.empty:
        return {**base, "burden_safety_class": "no_burden_signal",
                "n_total_rows": 0, "_note": f"{ensg} has no rare-variant burden rows in OT 26.06"}

    result = classify_burden(hit.to_dict("records"))
    return {**base, **result}


def _main(argv=None):
    ot_cli_main(read_gene_burden, "OT gene-burden human-genetics safety for a target.", argv)


if __name__ == "__main__":
    _main()
