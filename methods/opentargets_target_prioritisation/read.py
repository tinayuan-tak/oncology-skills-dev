"""opentargets_target_prioritisation — the P5 walking-skeleton safety-context reader.

Reads Open Targets 26.06 `target_prioritisation` (ONE row per target, targetId=ENSG) and
emits the `target-safety-prioritisation` card summary — a CONTEXT view of OT's engineered
target-priority scores, NOT a verdict-moving signal (Slice 1 is byte-stable: its rule is
skill-consumed only, never resolver-referenced).

IMPORTANT — these are OT-NORMALIZED PRIORITISATION SCORES, not raw facts. Each column is a
harmonized score in roughly [-1, +1] where the SIGN encodes the prioritisation direction
(OT's convention: higher = more favorable for tractability/safety prioritisation), and some
fields use -1 / null as sentinels. So this card presents them AS OT priors (with the raw
score surfaced), and deliberately does NOT recast e.g. isInMembrane=0.0 as "definitely not a
membrane protein" or geneticConstraint=-0.914 as a raw gnomAD LOEUF. The authoritative
per-fact reads live in the dedicated cards (gnomad-lof-constraint, surfaceome-family, etc.);
this card is the OT-prioritisation orientation layer.

data_unavailable-safe: absent entity / unresolved target -> data_unavailable summary.
"""
from __future__ import annotations

from typing import Optional

from ..opentargets_common import read_entity, symbol_to_ensembl

METHOD_VERSION = "0.1.0"

# The subset of target_prioritisation columns this card surfaces, grouped by theme. All are
# OT-normalized scores unless noted; we pass them through with a light categorical band.
_SAFETY_FIELDS = ["hasSafetyEvent", "geneticConstraint", "mouseKOScore"]
_TRACTABILITY_FIELDS = ["hasPocket", "hasLigand", "hasSmallMoleculeBinder",
                        "hasHighQualityChemicalProbes", "hasTEP"]
_LOCALIZATION_FIELDS = ["isInMembrane", "isSecreted"]
_CONTEXT_FIELDS = ["isCancerDriverGene", "maxClinicalStage", "tissueSpecificity",
                   "celltypeSpecificity", "paralogMaxIdentityPercentage"]
_ALL_FIELDS = ["targetId"] + _SAFETY_FIELDS + _TRACTABILITY_FIELDS + _LOCALIZATION_FIELDS + _CONTEXT_FIELDS


def _band(score: Optional[float]) -> str:
    """Coarse categorical band for an OT-normalized score (context only, NOT a threshold gate).

    OT scores run ~[-1, +1] with higher = more favorable on the prioritisation axis. We band into
    three neutral labels so a rule/skill can reference a categorical without implying a hard cutoff.
    None/NaN -> not_scored (OT did not assign a prioritisation value for this field).
    """
    import math
    if score is None:
        return "not_scored"
    try:
        v = float(score)
    except (TypeError, ValueError):
        return "not_scored"
    if math.isnan(v):
        return "not_scored"
    if v >= 0.5:
        return "favorable"
    if v <= -0.5:
        return "unfavorable"
    return "intermediate"


def read_target_prioritisation(target: str, indication: Optional[str] = None) -> dict:
    """OT target-prioritisation context summary for `target` (HGNC symbol or ENSG).

    `indication` is accepted for signature-uniformity with other cards but is NOT used —
    target_prioritisation is a per-target (indication-agnostic) OT engineered score.
    """
    ensg = symbol_to_ensembl(target)
    base = {"target": target, "ensembl_gene_id": ensg, "method_version": METHOD_VERSION,
            "source": "opentargets-26-06/target_prioritisation"}
    if ensg is None:
        return {**base, "prioritisation_status": "data_unavailable",
                "_note": "target not resolvable to an Ensembl gene id via the OT resolver sidecar"}

    df = read_entity("target_prioritisation", columns=_ALL_FIELDS)
    if df.empty:
        return {**base, "prioritisation_status": "data_unavailable",
                "_note": "target_prioritisation entity not available"}
    hit = df[df["targetId"] == ensg]
    if hit.empty:
        return {**base, "prioritisation_status": "not_in_prioritisation_table",
                "_note": f"{ensg} absent from OT target_prioritisation (78,691 targets scored)"}

    row = hit.iloc[0].to_dict()

    # Surface each score raw + its context band. The safety-relevant scores get named bands
    # (these are the fields the safety skill orients on); the rest pass through raw.
    def raw(f):
        v = row.get(f)
        try:
            fv = float(v)
            import math
            return None if math.isnan(fv) else round(fv, 4)
        except (TypeError, ValueError):
            return None

    return {
        **base,
        "prioritisation_status": "scored",
        # SAFETY-orientation bands (the card's primary categoricals — context, not verdict).
        "has_safety_event_band": _band(row.get("hasSafetyEvent")),
        "genetic_constraint_band": _band(row.get("geneticConstraint")),
        "mouse_ko_score_band": _band(row.get("mouseKOScore")),
        # raw scores (full precision surfaced for the skill / figure).
        "ot_scores": {f: raw(f) for f in _SAFETY_FIELDS + _TRACTABILITY_FIELDS
                      + _LOCALIZATION_FIELDS + _CONTEXT_FIELDS},
        "_encoding_note": ("OT-normalized prioritisation scores (~[-1,1], higher=more favorable); "
                           "NOT raw facts. Authoritative per-fact reads live in the dedicated cards."),
    }


def _main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="OT target-prioritisation context for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default=None)
    args = ap.parse_args(argv)
    print(json.dumps(read_target_prioritisation(args.target, args.indication), indent=2, default=str))


if __name__ == "__main__":
    _main()
