#!/usr/bin/env python
"""Regenerate `matrix.json` — the OFFLINE flip matrix behind the #2327 `reliability.powered` floors.

WHAT IS UNDER TEST. `reliability.powered` (#2306, verdict-INERT / SK#2091) is `n_effective >= floor` for
the three property-KINDS whose `n_effective` is a genuine sample size AND whose method encodes a power
floor (see onc_methods/reliability_calibration/powered_floors.py). This matrix is DESCRIPTIVE — `powered`
feeds no rule — and answers the issue's question: over the framework's already-COMMITTED measured
`n_effective` observations, how many properties move `unmeasured -> true/false` at the calibrated floor,
and how the count moves under a counterfactual floor.

FULLY OFFLINE. It reads ONLY committed fixtures — no live S3, no capture — because the measured inputs it
needs (observed `n_effective` values) are already committed:
  * CRISPR panel size (`n_cell_lines_evaluated`) — the 8 committed chronos recomputation anchors
    (methods/tests/calibration/recomputation/anchors/*.chronos_distribution.json) + the CRISPR card in the
    functional-requirement skill fixtures.
  * RNAi panel size (`rnai_n_cell_lines_evaluated`) + every other anchor — the skill card fixtures under
    skills/{functional-requirement,on-target-safety-liability}/tests/fixtures/*.yaml.

NOT A FIXTURE OF DERIVED VALUES. The irreproducible INPUT is the observed `n_effective` per unit; that is
what is stored. `powered` is DERIVED and is re-computed in test_powered_floor_flip_matrix.py from the
stored `n` through the SAME `powered_floor_for` the deriver uses — so a stale stored `powered`, a drifted
method constant, or a broken comparison all RED. The floors are NEVER stored as the answer: they are
re-read from each method's constant, both directions.

Usage (offline; seconds):
    cd ~/rnd-computational-biology-oncology-claude-oncology-skills/methods
    pixi run python tests/calibration/powered_floor_flip_matrix/regenerate.py
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
from pathlib import Path

import yaml

from onc_methods.reliability_calibration.powered_floors import (
    POWERED_FLOOR_UNMEASURED,
    calibrated_kinds,
    powered_floor_for,
)

HERE = Path(__file__).resolve().parent
MATRIX = HERE / "matrix.json"

# Every anchor field #2327 reasoned about, calibrated or not — so the matrix records the WHOLE decision.
ALL_KINDS = sorted(set(calibrated_kinds()) | set(POWERED_FLOOR_UNMEASURED))

# Counterfactual floors — a raised floor per calibrated kind, chosen to strictly exceed the committed
# observations so the descriptive matrix can show the `true -> false` flip the committed data alone
# (all well above the real floor) never exercises. NOT production values; pinned by a test to lie ABOVE
# the max committed observation so the counterfactual is a real flip, not a vacuous no-op.
COUNTERFACTUAL_FLOOR = {
    "n_cell_lines_evaluated": 1600,
    "rnai_n_cell_lines_evaluated": 800,
    "n_partner_deficient": 10_000,
}

_CHRONOS_ANCHORS = "methods/tests/calibration/recomputation/anchors"
_FIXTURE_DIRS = (
    "skills/functional-requirement/tests/fixtures",
    "skills/on-target-safety-liability/tests/fixtures",
)


def _repo_root() -> Path:
    out = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(out.stdout.strip())


def _sha(root: Path) -> str:
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip() or "?"


def _collect_observations(root: Path) -> dict[str, list[dict]]:
    """{anchor_field: [{source, value}, ...]} of every committed observation of a #2327 anchor."""
    obs: dict[str, list[dict]] = {k: [] for k in ALL_KINDS}

    # CRISPR panel size from the authoritative chronos recomputation anchors.
    for p in sorted((root / _CHRONOS_ANCHORS).glob("*.chronos_distribution.json")):
        doc = json.loads(p.read_text())
        v = doc.get("n_cell_lines_evaluated")
        if isinstance(v, int):
            obs["n_cell_lines_evaluated"].append({"source": f"{_CHRONOS_ANCHORS}/{p.name}", "value": v})

    # Every anchor field from the skill card fixtures (top-level mapping keys per card block).
    for d in _FIXTURE_DIRS:
        for p in sorted((root / d).glob("*.yaml")):
            doc = yaml.safe_load(p.read_text())
            for field in ALL_KINDS:
                for value in _find_field(doc, field):
                    if isinstance(value, int) and not isinstance(value, bool):
                        obs[field].append({"source": f"{d}/{p.name}", "value": value})
    return obs


def _find_field(node, field: str):
    """Every value bound to `field` anywhere in a nested fixture mapping/list."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == field:
                yield v
            else:
                yield from _find_field(v, field)
    elif isinstance(node, list):
        for v in node:
            yield from _find_field(v, field)


def _powered(n: int, floor: "int | None") -> "bool | str":
    return (n >= floor) if floor is not None else "unmeasured"


def build(root: Path) -> dict:
    obs = _collect_observations(root)
    kinds: dict[str, dict] = {}
    for kind in ALL_KINDS:
        floor = powered_floor_for(kind)
        values = [o["value"] for o in obs[kind]]
        row = {
            "calibrated": floor is not None,
            "floor": floor,
            "source_constant": {
                "n_cell_lines_evaluated": "onc_methods.depmap_chronos_distribution.cli:PAN_ESSENTIAL_MIN_PANEL_N",
                "rnai_n_cell_lines_evaluated": "onc_methods.depmap_demeter_distribution.cli:RNAI_PAN_ESSENTIAL_MIN_PANEL_N",
                "n_partner_deficient": "onc_methods.depmap_partner_conditional_dependency.cli:MIN_PARTNER_DEFICIENT_CELLS",
            }.get(kind),
            "unmeasured_reason": POWERED_FLOOR_UNMEASURED.get(kind),
            "n_observations": len(values),
            "observations": obs[kind],
            "at_floor": {
                "true": sum(1 for v in values if _powered(v, floor) is True),
                "false": sum(1 for v in values if _powered(v, floor) is False),
                "unmeasured": sum(1 for v in values if _powered(v, floor) == "unmeasured"),
            },
        }
        if floor is not None and values:
            cf = COUNTERFACTUAL_FLOOR[kind]
            row["counterfactual_floor"] = cf
            row["at_counterfactual"] = {
                "true": sum(1 for v in values if _powered(v, cf) is True),
                "false": sum(1 for v in values if _powered(v, cf) is False),
            }
        kinds[kind] = row
    return kinds


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else MATRIX
    root = _repo_root()

    kinds = build(root)
    doc = {
        "_meta": {
            "what": (
                "Descriptive flip matrix for #2327: reliability.powered = (n_effective >= floor) for the "
                "three calibrated property-kinds. Shows, over the framework's committed measured "
                "n_effective observations, how many move unmeasured -> true/false at the calibrated floor "
                "and under a raised counterfactual floor. powered is verdict-inert (SK#2091)."
            ),
            "ground_truth": (
                "MEASURED/STORED: the observed n_effective per committed unit. DERIVED (re-computed in the "
                "test, never trusted from here): powered. The floors are re-read from each method's "
                "constant both directions, never stored as the answer."
            ),
            "calibrated_kinds": sorted(calibrated_kinds()),
            "unmeasured_kinds": sorted(POWERED_FLOOR_UNMEASURED),
            "counterfactual_floors": COUNTERFACTUAL_FLOOR,
            "repo_sha": _sha(root),
            "captured_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "regenerated_by": "methods/tests/calibration/powered_floor_flip_matrix/regenerate.py",
        },
        "kinds": kinds,
    }
    out.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
    calibrated_obs = sum(kinds[k]["n_observations"] for k in calibrated_kinds())
    print(f"wrote {out}  calibrated_kinds={len(calibrated_kinds())}  calibrated_observations={calibrated_obs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
