"""opentargets_drug_warning — pharmacovigilance safety CONTEXT for a target (OT 26.06).

Closes the P5 `drug_warning` placeholder axis. Answers: "have drugs that ENGAGE {target} carried FDA
black-box warnings or been withdrawn, and for what toxicity classes?" A per-target pharmacovigilance
prior assembled by joining two OT 26.06 entities on ChEMBL id:
  drug_warning              (chemblIds, warningType {Black Box Warning|Withdrawn}, toxicityClass, year)
  drug_mechanism_of_action  (chemblIds -> targets [ENSG])  — the drug->target bridge

VERDICT-INERT CONTEXT (like target-safety-prioritisation), by design — a drug warning is a CONFOUNDED
on-target signal: a black-box warning can reflect OFF-target / class-effect / formulation toxicity, not
the target's biology. So this ORIENTS the reader (does the target's pharmacology carry warning history?)
but never fires a resolver rung. INFERRED tier.

drug_warning_class (strongest-wins):
  withdrawn_drug      — >=1 engaging drug was WITHDRAWN (the strongest pharmacovigilance flag)
  black_box_warned    — >=1 engaging drug carries an FDA Black Box Warning
  other_warning       — engaging drug(s) warned, neither withdrawn nor black-box
  no_warning          — engaging drug(s) exist in OT MoA but none carry a warning (measured-negative)
  no_targeted_drug    — no OT MoA drug engages the target (coverage gap — NOT evidence of safety)
  insufficient        — target unresolvable to ENSG

data_unavailable-safe. Absence = coverage gap (measured-vs-null discipline), never evidence-against.
"""
from __future__ import annotations

from typing import Optional

from ..opentargets_common import read_entity, symbol_to_ensembl, ot_cli_main

METHOD_VERSION = "0.1.0"

_WITHDRAWN = "withdrawn"
_BLACK_BOX = "black box"


def _as_list(v) -> list:
    """Coerce an OT list-column value (numpy array / list / None / scalar) to a plain list.
    read_entity returns pandas frames where list columns are numpy arrays, so the `x or []`
    idiom raises 'truth value of an array is ambiguous' — this avoids that."""
    if v is None:
        return []
    try:
        return list(v)
    except TypeError:
        return [v]


def _chembls_engaging_target(ensg: str) -> set:
    """ChEMBL ids of drugs whose OT mechanism-of-action targets include this ENSG."""
    df = read_entity("drug_mechanism_of_action", columns=["chemblIds", "targets"])
    out: set = set()
    if df.empty:
        return out
    for row in df.to_dict("records"):
        targets = row.get("targets")
        if targets is None:
            continue
        if ensg in _as_list(targets):
            for c in _as_list(row.get("chemblIds")):
                out.add(c)
    return out


def classify_drug_warning(warnings: list, n_targeted_drugs: int) -> dict:
    """Pure classifier: engaging-drug warning rows -> drug_warning_class + evidence."""
    if n_targeted_drugs == 0:
        return {"drug_warning_class": "no_targeted_drug", "n_targeted_drugs": 0,
                "n_targeted_warned_drugs": 0,
                "has_black_box": False, "has_withdrawn": False, "toxicity_classes": [],
                "warning_types": []}
    wtypes = {str(w.get("warningType") or "").strip().lower() for w in warnings}
    # isinstance str guard: toxicityClass can be NaN (float) — NaN is truthy, so a bare truthy
    # check let str(NaN) == "nan" leak into the label set. Keep only real string labels.
    tox = sorted({w["toxicityClass"].strip() for w in warnings
                  if isinstance(w.get("toxicityClass"), str) and w["toxicityClass"].strip()})
    has_withdrawn = any(_WITHDRAWN in w for w in wtypes)
    has_black_box = any(_BLACK_BOX in w for w in wtypes)
    if has_withdrawn:
        cls = "withdrawn_drug"
    elif has_black_box:
        cls = "black_box_warned"
    elif warnings:
        cls = "other_warning"
    else:
        cls = "no_warning"
    return {"drug_warning_class": cls,
            "n_targeted_warned_drugs": len({c for w in warnings for c in _as_list(w.get("chemblIds"))}),
            "has_black_box": has_black_box, "has_withdrawn": has_withdrawn,
            "toxicity_classes": tox, "warning_types": sorted(t for t in wtypes if t)}


def read_drug_warning(target: str, indication: Optional[str] = None) -> dict:
    """Per-target pharmacovigilance safety CONTEXT (verdict-inert). `indication` unused (per-gene)."""
    ensg = symbol_to_ensembl(target)
    base = {"target": target, "ensembl_gene_id": ensg, "method_version": METHOD_VERSION,
            "source": "opentargets-26-06/drug_warning + drug_mechanism_of_action", "evidence_tier": "inferred"}
    if ensg is None:
        return {**base, "drug_warning_class": "insufficient",
                "_note": "target not resolvable to an Ensembl gene id via the OT resolver sidecar"}
    chembls = _chembls_engaging_target(ensg)
    if not chembls:
        return {**base, **classify_drug_warning([], 0),
                "_note": f"no OT mechanism-of-action drug engages {ensg} (coverage gap, not evidence of safety)"}
    dw = read_entity("drug_warning", columns=["chemblIds", "warningType", "toxicityClass", "year"])
    warnings = []
    if not dw.empty:
        for row in dw.to_dict("records"):
            if chembls.intersection(set(_as_list(row.get("chemblIds")))):
                warnings.append(row)
    return {**base, "n_targeted_drugs": len(chembls), **classify_drug_warning(warnings, len(chembls))}


def _main(argv=None):
    ot_cli_main(read_drug_warning, "OT pharmacovigilance (drug-warning) safety context for a target.", argv)


if __name__ == "__main__":
    _main()
