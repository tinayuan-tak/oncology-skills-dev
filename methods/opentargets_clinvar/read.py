"""opentargets_clinvar — P5 follow-on: germline-pathogenic ClinVar safety leg (a 4th corroborating
human-genetics signal alongside gene_burden / clingen / mouse_phenotype).

Reads Open Targets 26.06 `evidence_eva` (ClinVar, ENSG-keyed, ~17,418 genes × avg 230 variant-level
rows, ~4.0M total) → clinvar_pathogenic_class. The safety question: does the gene carry curated
GERMLINE PATHOGENIC variants — evidence that losing/altering its function causes heritable disease,
a WT-loss safety signal for a full-KO modality?

THREE GATES the data demands (schema-verified 2026-07-24):
  1. PATHOGENICITY — count only `pathogenic` / `likely_pathogenic` clinicalSignificances. The bulk of
     ClinVar is `uncertain significance` (1.7M) + `likely benign` (1.08M) — noise, must NOT fire.
  2. GERMLINE guardrail — gate on alleleOrigins ∈ {germline, inherited, de_novo, maternal, paternal,
     biparental, uniparental}. A SOMATIC pathogenic ClinVar entry is a CANCER-DRIVER signal (the
     opposite axis), NOT a germline-safety signal — exclude it. (3.3M of 4M rows are germline.)
  3. REVIEW-STATUS quality — exclude `no assertion criteria provided` / `no classification provided`
     and (for the confident tier) `conflicting classifications`. ClinVar star-rating discipline.

CORROBORATING, not competing: this fires the SAME human_genetics_safety_concern hold as burden/
clingen/mouse (joins the resolver's when_any_fired set) — a fourth germline leg, mechanism-conditioned
by the mutant-selective downgrade like the others. data_unavailable-safe.
"""
from __future__ import annotations

from typing import Optional

from ..opentargets_common import read_entity, symbol_to_ensembl

METHOD_VERSION = "0.1.0"

_PATHOGENIC = {"pathogenic", "likely_pathogenic", "likely pathogenic"}
# germline-origin tokens (a somatic-only variant is a cancer-driver signal, not germline safety).
_GERMLINE_ORIGINS = {"germline", "inherited", "de_novo", "de novo", "maternal", "paternal",
                     "biparental", "uniparental"}
# review-status strings that are too weak to count (ClinVar 0-star / conflicting).
_WEAK_REVIEW = {"no assertion criteria provided", "no classification provided",
                "conflicting classifications", "conflicting classifications of pathogenicity"}

_FIELDS = ["targetId", "clinicalSignificances", "alleleOrigins", "confidence",
           "variantFunctionalConsequenceId", "diseaseFromSource", "variantRsId"]


def _norm_list(v) -> set:
    """Normalize a list/scalar/None field to a lower-cased token set."""
    if v is None:
        return set()
    items = [v] if isinstance(v, str) else (list(v) if hasattr(v, "__iter__") else [])
    return {str(x).strip().lower() for x in items if x is not None and str(x).strip()}


def _is_pathogenic(sigs: set) -> bool:
    return bool(sigs & _PATHOGENIC)


def _is_germline(origins: set) -> bool:
    return bool(origins & _GERMLINE_ORIGINS)


def classify_clinvar(rows: list) -> dict:
    """Pure classifier: a gene's ClinVar rows → clinvar_pathogenic_class + evidence.

    Fully unit-testable with dict fixtures. Decision (a variant COUNTS iff pathogenic/likely-pathogenic
    AND germline-origin AND not weak-review):
      1. count confident germline-pathogenic variants.
      2. >=1 confident (non-weak-review) germline-pathogenic → germline_pathogenic (the safety signal).
      3. >=1 germline-pathogenic but ALL weak-review → germline_pathogenic_low_review (caveat tier).
      4. rows exist, pathogenic present but all SOMATIC → somatic_only (NOT a germline safety signal).
      5. rows exist, no pathogenic → no_pathogenic_signal. no rows → no_clinvar_entry.
    """
    if not rows:
        return {"clinvar_pathogenic_class": "no_clinvar_entry", "n_rows": 0,
                "n_pathogenic_germline": 0, "n_pathogenic_somatic": 0, "top_disease": None}

    conf_germ_path = []       # confident (non-weak-review) germline-pathogenic
    weak_germ_path = []       # germline-pathogenic but weak review status
    somatic_path = 0          # pathogenic but NOT germline (somatic) — the guardrail-excluded set
    for r in rows:
        sigs = _norm_list(r.get("clinicalSignificances"))
        if not _is_pathogenic(sigs):
            continue
        origins = _norm_list(r.get("alleleOrigins"))
        if _is_germline(origins):
            review = str(r.get("confidence") or "").strip().lower()
            (weak_germ_path if review in _WEAK_REVIEW else conf_germ_path).append(r)
        elif origins:  # pathogenic with a NON-germline (somatic) origin
            somatic_path += 1
        else:  # pathogenic, origin unknown — conservatively treat as weak germline (don't drop)
            weak_germ_path.append(r)

    if conf_germ_path:
        cls, pool = "germline_pathogenic", conf_germ_path
    elif weak_germ_path:
        cls, pool = "germline_pathogenic_low_review", weak_germ_path
    elif somatic_path:
        cls, pool = "somatic_only", []
    else:
        cls, pool = "no_pathogenic_signal", []

    top_disease = None
    if pool:
        # a stable representative disease label (first non-empty)
        for r in pool:
            d = r.get("diseaseFromSource")
            if d:
                top_disease = d
                break

    return {
        "clinvar_pathogenic_class": cls,
        "n_rows": len(rows),
        "n_pathogenic_germline": len(conf_germ_path) + len(weak_germ_path),
        "n_pathogenic_germline_confident": len(conf_germ_path),
        "n_pathogenic_somatic": somatic_path,
        "top_disease": top_disease,
    }


def read_clinvar_pathogenic(target: str, indication: Optional[str] = None) -> dict:
    """ClinVar germline-pathogenic safety summary for `target` (HGNC symbol or ENSG).

    `indication` accepted for signature-uniformity but NOT used — ClinVar variant pathogenicity is
    per-gene across many diseases; top_disease surfaces the driving one.
    """
    ensg = symbol_to_ensembl(target)
    base = {"target": target, "ensembl_gene_id": ensg, "method_version": METHOD_VERSION,
            "source": "opentargets-26-06/evidence_eva"}
    if ensg is None:
        return {**base, "clinvar_pathogenic_class": "insufficient",
                "_note": "target not resolvable to an Ensembl gene id via the OT resolver sidecar"}

    df = read_entity("evidence_eva", columns=_FIELDS)
    if df.empty:
        return {**base, "clinvar_pathogenic_class": "insufficient",
                "_note": "evidence_eva entity not available"}
    hit = df[df["targetId"] == ensg]
    if hit.empty:
        return {**base, "clinvar_pathogenic_class": "no_clinvar_entry",
                "n_rows": 0, "_note": f"{ensg} has no ClinVar variant rows in OT 26.06"}

    return {**base, **classify_clinvar(hit.to_dict("records"))}


def _main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="OT ClinVar germline-pathogenic safety for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default=None)
    args = ap.parse_args(argv)
    print(json.dumps(read_clinvar_pathogenic(args.target, args.indication), indent=2, default=str))


if __name__ == "__main__":
    _main()
