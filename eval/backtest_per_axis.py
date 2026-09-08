#!/usr/bin/env python3
"""backtest_per_axis — score the composed target-profile backtest PER CLAIM-VECTOR AXIS.

Consistent with the discordance ledger's v2 design (build_discordance_ledger: compare per claim-vector
AXIS, not the reduced verdict). Where the verdict-level backtest asks "did the composed call match the
outcome?", this asks the sharper per-axis question:

  * AXIS-ATTRIBUTION — does the framework DECIDE on the same axis FAMILY as the ground-truth deciding_axis
    (target-contracts reference_profiles)? A right call for the WRONG axis is a latent gap; a hold on the
    RIGHT axis for a declined target is a right-for-the-right-reason win.
  * PER-AXIS CAPTURE — for every claim-vector axis (the 15 fan-out sub-verdicts), is it measured or blind?
  * OUTCOME POLARITY — the composed recommendation vs the program outcome (kept as context, NOT the unit).

INPUT: a directory of composed `nomination.json` files (target-profile --verdict-only output) + the
reference_profiles section of known_target_calibration_set.yaml. READ-ONLY; emits a JSON + a table.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

# Coarse claim-vector-axis FAMILIES — the shared vocabulary both the ground-truth deciding_axis DESCRIPTOR
# (free text, e.g. partner_conditional_SL_SMARCA4) and the composed deciding-axis SHORT (a sub-skill id,
# e.g. 'safety') map into, so the two are comparable. Order matters (first match wins).
_DESC_FAMILY = [
    (r"SL|synthetic|paralog|partner|circuit|reciprocal|addiction|pan_essential|window|buffered|proteotoxic|dependenc", "dependency"),
    (r"E2|A2|B2|F_|density|internaliz|topology|shed|glycan|avidity|bispecific|antigen|surface", "surface"),
    (r"constrained|normal_liability|normal_tissue|safety|cardiotox|no_therapeutic_window", "safety"),
    (r"covalent|pocket|switch|druggable|tractab|SM_dependency", "tractability"),
    (r"mutation|ITD|V600|hotspot|amplif|fusion", "genomic"),
    (r"IO|interferon|TME|immune|inflammasome|CAF|secreted|exvivo_inflammatory", "immune_tme"),
    (r"clinical|precedent|license|belzutifan", "clinical_precedent"),
    (r"degrader|E3|glue|neomorph", "modality_feasibility"),
]
# composed deciding-axis SHORT (sub-skill id) -> family
_SHORT_FAMILY = {
    "dependency": "dependency", "safety": "safety", "surface_modality": "surface",
    "tractability_sm": "tractability", "genomic_alteration": "genomic", "immune_context": "immune_tme",
    "differentiation": "genomic", "mechanism": "tractability", "selectivity": "surface",
    "expression": "surface", "cis_coherence": "genomic",
}


def _family_of_descriptor(desc: str) -> str:
    d = desc or ""
    for pat, fam in _DESC_FAMILY:
        if re.search(pat, d, re.I):
            return fam
    return f"other:{d}"


def _outcome_polarity(outcome: str) -> str:
    o = (outcome or "").lower()
    if o in ("approved_class", "advanced", "active"):
        return "positive"          # should NOT hit a clean veto (hold may be defensible)
    if o in ("declined", "killed"):
        return "negative"          # veto/hold is the correct call
    return "unknown"


# reference_profiles keys some targets as compound / non-HGNC symbols; map the run target → ref key.
_REF_ALIAS = {"CDK4": "CDK4_6", "CDK6": "CDK4_6", "MARK2": "MARK2_3", "MARK3": "MARK2_3", "EPAS1": "HIF2A"}


def _load_reference_profiles(cal_path: str | Path) -> dict:
    import yaml  # type: ignore
    return (yaml.safe_load(Path(cal_path).read_text()) or {}).get("reference_profiles") or {}


def score_target(nom: dict, ref: dict) -> dict:
    """One per-axis backtest row for a target, given its composed nomination.json + reference_profiles entry."""
    tc = nom.get("target_call") or {}
    gate = tc.get("gate") or {}
    sub = nom.get("sub_verdicts") or {}
    # framework's composed DECIDING axis (the sub-skill that forced the recommendation), if any
    deciding_short = None
    for x in (gate.get("triggered_by") or []):
        deciding_short = x.get("short")
        break
    if deciding_short is None:                      # passed: no veto/hold fired
        for x in (gate.get("suppressed_vetoes") or []):
            deciding_short = x.get("short")         # the axis that WOULD have fired but was suppressed
            break
    fw_family = _SHORT_FAMILY.get(deciding_short, f"none/{deciding_short}")
    ref_family = _family_of_descriptor(ref.get("deciding_axis"))
    rec = gate.get("forced_recommendation")         # hold/veto/None
    pol = _outcome_polarity(ref.get("outcome"))
    # per-axis capture: measured (has a verdict) vs blind/insufficient/None
    per_axis = {}
    for short, v in (sub.items() if isinstance(sub, dict) else []):
        verdict = v.get("verdict") if isinstance(v, dict) else v
        per_axis[short] = verdict
    return {
        "outcome": ref.get("outcome"), "outcome_polarity": pol,
        "ref_deciding_axis": ref.get("deciding_axis"), "ref_family": ref_family,
        "ref_agreement": ref.get("agreement"), "ref_coverage": ref.get("deciding_axis_coverage"),
        "composed_recommendation": rec, "composed_deciding_short": deciding_short, "fw_family": fw_family,
        # THE per-axis test: did the framework decide on the same axis FAMILY as ground truth?
        "axis_attribution_match": (fw_family == ref_family) if deciding_short else None,
        "per_axis_verdicts": per_axis,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nominations", required=True, help="glob for composed nomination.json files")
    ap.add_argument("--calibration-set", required=True, help="known_target_calibration_set.yaml")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    ref_all = _load_reference_profiles(a.calibration_set)
    rows = {}
    for f in sorted(glob.glob(a.nominations)):
        nom = json.loads(Path(f).read_text())
        tgt = nom.get("target")
        ref = ref_all.get(tgt) or ref_all.get(_REF_ALIAS.get(tgt, ""))
        if not ref:
            continue
        rows[tgt] = score_target(nom, ref)
    n = len(rows)
    matched = sum(1 for r in rows.values() if r["axis_attribution_match"] is True)
    scored = sum(1 for r in rows.values() if r["axis_attribution_match"] is not None)
    report = {
        "schema": "backtest_per_axis/v1",
        "n_targets": n,
        "axis_attribution_match_rate": round(matched / scored, 3) if scored else None,
        "n_axis_scored": scored,
        "rows": rows,
    }
    print(f"{'target':10} {'outcome':13} {'ref_family':13} {'fw_family':13} {'rec':6} axis_match")
    for t, r in sorted(rows.items()):
        print(f"{t:10} {str(r['outcome']):13} {str(r['ref_family']):13} {str(r['fw_family']):13} "
              f"{str(r['composed_recommendation']):6} {r['axis_attribution_match']}")
    print(f"\naxis-attribution match rate: {report['axis_attribution_match_rate']} ({matched}/{scored})")
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
