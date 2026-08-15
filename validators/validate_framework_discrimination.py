#!/usr/bin/env python3
"""validate_framework_discrimination.py — the framework's OWN predictive-validity harness (gap #5).

The meta-gap the framework never measured: does its nomination actually DISCRIMINATE clinically-validated
targets (approved / advanced) from failed / declined ones — and on the axis that actually DECIDED each
target's fate, or only on home-turf lanes?

This is NOT a per-target gate test (that is tests/calibration/test_known_target_calibration.py, which
asserts must_not_veto / abstention per target). This is the AGGREGATE discrimination report over the
curated `reference_profiles` in vocabularies/known_target_calibration_set.yaml — each entry already
carries its clinical `outcome`, the `deciding_axis` that settled it, whether the framework is
`deciding_axis_coverage` blind/partial/captured on that axis, the verdict-vs-outcome `agreement`, and a
`severity`. The harness rolls those curated labels into quantified validity metrics so every future
framework change is MEASURED against known outcomes (did coverage/agreement improve? did a dangerous
false-positive clear?), not argued.

Run:  python3 validators/validate_framework_discrimination.py [--json] [--set <path>]
      Exits non-zero if the curated metrics regress past the documented floors (--check).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("PyYAML required\n")
    raise

_DEFAULT_SET = Path(__file__).resolve().parent.parent / "vocabularies" / "known_target_calibration_set.yaml"

# Documented regression FLOORS (the framework must not get WORSE on known targets). Current values as of
# the 2026-08-14 curation; a fix that improves discrimination raises these. --check enforces them.
_FLOORS = {
    "max_dangerous_false_positives": 4,   # ADAR1 / RBM39 / CLDN18.2_LRRC15 / EGFR_cMET_VEGF
    # The DRUG-BACKED regression floor: silent-FNs whose clinical outcome is an APPROVED drug — the
    # unambiguous losses (the framework would veto a marketed drug's target). This is the meaningful
    # "would-veto-a-drug" guard. Program-status silent-FNs (advanced/active) are reported separately
    # and deliberately NOT floored: "advanced as a Takeda program" != "high-quality target" — e.g.
    # MARK2/3 advanced organizationally but never beat YAP/TAZ on efficacy, so counting it as a
    # framework loss (and flooring against it) would calibrate the guard on unvalidated labels.
    "max_approved_silent_false_negatives": 5,   # PARP1 / BCL2 / XPO1 / PSMB5 / CDK4_6
    "max_silent_false_negatives": 12,     # total (approved + advanced/active); informational soft guard
    "min_approved_agreement_rate": 0.25,  # currently 5/18 = 0.28
}

_POSITIVE_OUTCOMES = {"approved_class", "approved"}
_ADVANCED_OUTCOMES = {"advanced", "active"}
_AGREE_LABELS = {"agree", "agree_fragile", "agree_conditional"}


def outcome_class(outcome: str) -> str:
    if outcome in _POSITIVE_OUTCOMES:
        return "positive_approved"
    if outcome in _ADVANCED_OUTCOMES:
        return "advanced_active"
    return "negative_declined"


def deciding_axis_family(axis: str) -> str:
    """Group deciding_axis into the missing-CAPABILITY families so we can rank which un-wired axis costs
    the most known targets (load-bearingness)."""
    ax = axis or ""
    if re.search(r"SL|synthetic|paralog|partner|circuit|reciprocal", ax):
        return "synthetic_lethal / partner_conditional"
    if re.search(r"window|pan_essential|cell_state|proteotoxic|buffered|addiction_MCL", ax):
        return "cell_state_window / pan_essential_buffered"
    if re.search(r"E2|density|internaliz|topology|shed|glycan|avidity|bispecific|antigen|surface|B2|A2|F_", ax):
        return "surface_antigen_biology (density/topology/avidity)"
    if re.search(r"IO|interferon|TME|immune|inflammasome|CAF|secreted", ax):
        return "IO / TME / immune_context"
    if re.search(r"clinical|precedent|license|belzutifan", ax):
        return "clinical_precedent (license_blocked)"
    if re.search(r"degrader|E3|glue|neomorph", ax):
        return "modality_feasibility (degrader/glue/neomorph)"
    if re.search(r"mutation|ITD|V600|covalent|pocket|switch", ax):
        return "captured_lane (mutation/pocket)"
    return f"other: {ax}"


def compute_metrics(profiles: dict) -> dict:
    items = list(profiles.items())
    n = len(items)
    by_outcome = Counter(outcome_class(v["outcome"]) for _, v in items)
    by_coverage = Counter(v.get("deciding_axis_coverage") for _, v in items)
    by_agreement = Counter(v.get("agreement") for _, v in items)
    by_severity = Counter(v.get("severity") for _, v in items)

    approved = [v for _, v in items if outcome_class(v["outcome"]) == "positive_approved"]
    approved_captured = [v for v in approved if v.get("deciding_axis_coverage") == "captured"]
    approved_agree = [v for v in approved if v.get("agreement") in _AGREE_LABELS]

    dfp = [k for k, v in items if v.get("severity") == "dangerous_false_positive"]
    sfn = [k for k, v in items if v.get("severity") == "silent_false_negative"]
    # Split silent-FNs by outcome TRUST: an approved-drug loss is unambiguous; an advanced/active
    # program is program-status, not a validated quality signal, so it must not be conflated with a
    # drug loss (nor flooded into the drug-backed regression guard).
    sfn_by_outcome = {
        "positive_approved": [k for k, v in items
                              if v.get("severity") == "silent_false_negative"
                              and outcome_class(v["outcome"]) == "positive_approved"],
        "advanced_active": [k for k, v in items
                            if v.get("severity") == "silent_false_negative"
                            and outcome_class(v["outcome"]) == "advanced_active"],
    }

    blind = [v for _, v in items if v.get("deciding_axis_coverage") == "blind"]
    load = Counter(deciding_axis_family(v["deciding_axis"]) for v in blind)

    return {
        "n_targets": n,
        "by_outcome": dict(by_outcome),
        "by_deciding_axis_coverage": dict(by_coverage),
        "by_agreement": dict(by_agreement),
        "by_severity": dict(by_severity),
        "n_approved": len(approved),
        "approved_deciding_axis_capture_rate": round(len(approved_captured) / len(approved), 3) if approved else None,
        "approved_verdict_agreement_rate": round(len(approved_agree) / len(approved), 3) if approved else None,
        "blind_rate": round(len(blind) / n, 3) if n else None,
        "dangerous_false_positives": dfp,
        "silent_false_negatives": sfn,
        "silent_false_negatives_by_outcome": sfn_by_outcome,
        "blind_axis_load_bearingness": dict(load.most_common()),
    }


def render_report(m: dict) -> str:
    L = []
    L.append("=" * 78)
    L.append("FRAMEWORK PREDICTIVE-VALIDITY / DISCRIMINATION HARNESS (scientific-gap #5)")
    L.append("=" * 78)
    L.append(f"Curated known-target cohort: {m['n_targets']} targets")
    L.append(f"  by clinical outcome: {m['by_outcome']}")
    L.append("")
    L.append(f"DECIDING-AXIS COVERAGE (is the framework even reading the axis that decided the target?):")
    L.append(f"  {m['by_deciding_axis_coverage']}")
    L.append(f"  → BLIND on the deciding axis for {int(round(m['blind_rate']*100))}% of known targets.")
    L.append("")
    L.append(f"APPROVED-DRUG DISCRIMINATION (n={m['n_approved']}):")
    L.append(f"  deciding-axis CAPTURED rate: {m['approved_deciding_axis_capture_rate']}  "
             f"(the axis that made it a drug is one the framework reads)")
    L.append(f"  verdict AGREES-with-outcome rate: {m['approved_verdict_agreement_rate']}")
    L.append("")
    L.append(f"ERROR INVENTORY (the actionable failure list):")
    L.append(f"  dangerous false-positives ({len(m['dangerous_false_positives'])}) — framework would ADVANCE a clinical FAILURE:")
    L.append(f"    {m['dangerous_false_positives']}")
    sfn_by = m["silent_false_negatives_by_outcome"]
    L.append(f"  silent false-negatives ({len(m['silent_false_negatives'])}) — framework would VETO a validated target:")
    L.append(f"    approved-drug losses (DRUG-BACKED, floored) [{len(sfn_by['positive_approved'])}]:")
    L.append(f"      {sfn_by['positive_approved']}")
    L.append(f"    advanced/active (program-status, PENDING RE-GRADE — NOT floored) [{len(sfn_by['advanced_active'])}]:")
    L.append(f"      {sfn_by['advanced_active']}")
    L.append("")
    L.append(f"LOAD-BEARINGNESS — which MISSING axis costs the most blind known targets (build-priority order):")
    for fam, n in m["blind_axis_load_bearingness"].items():
        L.append(f"  {n:3}  {fam}")
    L.append("=" * 78)
    return "\n".join(L)


def check_floors(m: dict) -> list:
    """Return a list of regression violations against the documented floors (empty = OK)."""
    v = []
    if len(m["dangerous_false_positives"]) > _FLOORS["max_dangerous_false_positives"]:
        v.append(f"dangerous_false_positives {len(m['dangerous_false_positives'])} > floor {_FLOORS['max_dangerous_false_positives']}")
    n_approved_sfn = len(m["silent_false_negatives_by_outcome"]["positive_approved"])
    if n_approved_sfn > _FLOORS["max_approved_silent_false_negatives"]:
        v.append(f"approved_silent_false_negatives {n_approved_sfn} > floor {_FLOORS['max_approved_silent_false_negatives']} "
                 f"(a marketed-drug target would be vetoed)")
    if len(m["silent_false_negatives"]) > _FLOORS["max_silent_false_negatives"]:
        v.append(f"silent_false_negatives {len(m['silent_false_negatives'])} > floor {_FLOORS['max_silent_false_negatives']}")
    rate = m["approved_verdict_agreement_rate"]
    if rate is not None and rate < _FLOORS["min_approved_agreement_rate"]:
        v.append(f"approved_verdict_agreement_rate {rate} < floor {_FLOORS['min_approved_agreement_rate']}")
    return v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", type=Path, default=_DEFAULT_SET, help="path to known_target_calibration_set.yaml")
    ap.add_argument("--json", action="store_true", help="emit metrics as JSON instead of the report")
    ap.add_argument("--check", action="store_true", help="exit non-zero if metrics regress past documented floors")
    args = ap.parse_args(argv)

    spec = yaml.safe_load(args.set.read_text()) or {}
    profiles = spec.get("reference_profiles") or {}
    if not profiles:
        sys.stderr.write(f"no reference_profiles in {args.set}\n")
        return 2
    m = compute_metrics(profiles)

    if args.json:
        print(json.dumps(m, indent=2))
    else:
        print(render_report(m))

    if args.check:
        violations = check_floors(m)
        if violations:
            sys.stderr.write("REGRESSION vs documented floors:\n  - " + "\n  - ".join(violations) + "\n")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
