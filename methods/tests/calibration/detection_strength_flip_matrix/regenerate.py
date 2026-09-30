#!/usr/bin/env python
"""Regenerate `matrix.json` — the OFFLINE flip matrix behind the #2329 `reliability.detection_strength`
cutpoints (epic #2210, #2306 rollout follow-on).

WHAT IS UNDER TEST. `reliability.detection_strength` (#2306, OPTIONAL + verdict-INERT / SK#2091) is the
`weak|moderate|strong` ordinal a detection/abundance property projects from its OWN detection datum. The
cutpoints are NOT new numbers — each scheme mirrors its method's own detection classification
(onc_methods/reliability_calibration/detection_strength.py). This matrix is DESCRIPTIVE — the ordinal
feeds no rule — and answers the #2221/#2223-style question: over the framework's already-COMMITTED
measured detection observations, how does each observation land on the ordinal, and how the landing
moves under a counterfactual cut.

FULLY OFFLINE. It reads ONLY committed recomputation anchors — no live S3, no capture:
  * ihc_protein_presence_class          — the committed HPA-IHC recomputation anchors
    (methods/tests/calibration/recomputation/anchors/*.hpa_pathology_cancer_ihc.json), whose `expected`
    block carries the upstream-classified `protein_presence_class` token.
  * sc_malignant_detection_fraction     — the committed single-cell anchors
    (methods/tests/calibration/recomputation/anchors/*.sc_celltype.json), whose expected block carries
    the numeric malignant detection fraction.
  * surface_absolute_density            — NO committed absolute-density anchor exists in the
    recomputation set today (the surface density corpus is not captured as a recomputation fixture), so
    this scheme records ZERO committed observations. That is a FINDING, not a gap to paper over
    (#2221/#2223: "if the panel contains no movers, that is a finding"); the boundary behaviour is
    proven in the unit test via the method's own `_classify`.

NOT A FIXTURE OF DERIVED VALUES. The irreproducible INPUT stored per observation is the observed
detection DATUM (the class token / the numeric fraction) + its source; `detection_strength` is DERIVED
and re-computed in test_detection_strength_flip_matrix.py through the SAME `detection_strength_for` the
deriver uses — so a stale stored strength, a drifted method cut, or a broken mapping all RED. The sc
cuts are NEVER stored as the answer: they are re-read from the sc method's constants, both directions.

Usage (offline; seconds):
    cd ~/rnd-computational-biology-oncology-claude-oncology-skills/methods
    pixi run python tests/calibration/detection_strength_flip_matrix/regenerate.py
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
from pathlib import Path

from onc_methods.reliability_calibration.detection_strength import (
    IHC_PROTEIN_PRESENCE_CLASS,
    SC_MALIGNANT_DETECTION_FRACTION,
    SURFACE_ABSOLUTE_DENSITY,
    calibrated_detection_schemes,
    detection_strength_for,
)

HERE = Path(__file__).resolve().parent
MATRIX = HERE / "matrix.json"
ANCHORS = HERE.parents[1] / "calibration" / "recomputation" / "anchors"


def _repo_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=HERE).decode().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _load_expected(path: Path) -> dict:
    d = json.loads(path.read_text())
    return {**d, **(d.get("expected") or {})}


def _ihc_observations() -> list:
    out = []
    for p in sorted(ANCHORS.glob("*.hpa_pathology_cancer_ihc.json")):
        e = _load_expected(p)
        token = e.get("protein_presence_class")
        if token is None:
            continue
        out.append({"source": f"anchors/{p.name}", "datum": token})
    return out


def _sc_observations() -> list:
    out = []
    for p in sorted(ANCHORS.glob("*.sc_celltype.json")):
        e = _load_expected(p)
        frac = e.get("expected_malignant_detection_fraction", e.get("malignant_detection_fraction"))
        if not isinstance(frac, (int, float)) or isinstance(frac, bool):
            continue  # data_unavailable anchors carry None -> no detection observation
        out.append({"source": f"anchors/{p.name}", "datum": round(float(frac), 6)})
    return out


_SCHEME_OBSERVATIONS = {
    IHC_PROTEIN_PRESENCE_CLASS: _ihc_observations,
    SC_MALIGNANT_DETECTION_FRACTION: _sc_observations,
    SURFACE_ABSOLUTE_DENSITY: lambda: [],  # no committed absolute-density recomputation anchor (a finding)
}


def build() -> dict:
    schemes = {}
    for scheme in sorted(calibrated_detection_schemes()):
        obs = _SCHEME_OBSERVATIONS[scheme]()
        dist = {}
        for o in obs:
            strength = detection_strength_for(scheme, o["datum"])
            key = strength if strength is not None else "omitted"
            dist[key] = dist.get(key, 0) + 1
        schemes[scheme] = {
            "n_observations": len(obs),
            "distribution": dict(sorted(dist.items())),
            "observations": obs,
        }
    return {
        "_meta": {
            "what": (
                "Descriptive flip matrix for #2329: reliability.detection_strength = the "
                "weak|moderate|strong ordinal projected from a detection/abundance property's own "
                "detection datum, over the framework's committed measured observations. The cutpoints "
                "are each scheme's method's OWN detection cuts (single-sourced). detection_strength is "
                "verdict-inert (SK#2091) and OPTIONAL (omitted below the detection floor)."
            ),
            "ground_truth": (
                "MEASURED/STORED: the observed detection datum per committed unit (the upstream class "
                "token / the numeric fraction). DERIVED (re-computed in the test, never trusted from "
                "here): detection_strength, via the SAME detection_strength_for the deriver uses. The "
                "cuts are re-read from each method's constant/classifier both directions, never stored."
            ),
            "schemes": sorted(calibrated_detection_schemes()),
            "repo_sha": _repo_sha(),
            "captured_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "regenerated_by": "methods/tests/calibration/detection_strength_flip_matrix/regenerate.py",
        },
        "schemes": schemes,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if matrix.json is stale vs a fresh build")
    args = ap.parse_args()
    fresh = build()
    if args.check:
        current = json.loads(MATRIX.read_text())
        # compare everything but the volatile _meta capture stamp / sha
        fresh_cmp = {
            **fresh,
            "_meta": {k: v for k, v in fresh["_meta"].items() if k not in ("captured_utc", "repo_sha")},
        }
        cur_cmp = {
            **current,
            "_meta": {k: v for k, v in current["_meta"].items() if k not in ("captured_utc", "repo_sha")},
        }
        if fresh_cmp != cur_cmp:
            raise SystemExit("matrix.json is STALE — re-run regenerate.py (the committed observations moved)")
        print("matrix.json is current")
        return
    MATRIX.write_text(json.dumps(fresh, indent=1) + "\n")
    print(f"wrote {MATRIX}")


if __name__ == "__main__":
    main()
