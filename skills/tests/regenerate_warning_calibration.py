#!/usr/bin/env python3
"""Regenerate ``_skills_common/warning_calibration.json`` — the E2 calibration register.

    python skills/tests/regenerate_warning_calibration.py ~/dev/target-archetype-corpus-<vintage>

For every (card_id, warning_id), measure the firing rate over the corpus (fired / EVALUABLE runs — a run
where the predicate returned None, e.g. a field the card did not emit, is not in the denominator). A
predicate that fires on >90% or <1% of its evaluable runs is NON-DISCRIMINATING: it carries almost no
per-run information, so it is listed as `suppressed` and the dispatcher must NOT emit it as a per-run
warning (E2 — else the warning channel inherits the non-discrimination problem the emission arc diagnoses).
Committed artifact, like the emission baseline: the corpus is not available in CI. Pairs with fewer than
`_MIN_EVALUABLE` evaluable runs are left OUT of the register (too few to calibrate → not suppressed).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILLS.parent / "skills"))

from _skills_common import card_warnings as cw  # noqa: E402
from _skills_common.paths import target_contracts_root  # noqa: E402

_OUT = SKILLS / "_skills_common" / "warning_calibration.json"
_MIN_EVALUABLE = 20
_HIGH = 0.90
_LOW = 0.01


def build(corpus: Path) -> dict:
    contracts = str(target_contracts_root())
    evaluable: dict = defaultdict(int)
    fired: dict = defaultdict(int)
    n_pkgs = 0
    for pkg in sorted(corpus.glob("*/evidence_package.json")):
        try:
            doc = json.loads(pkg.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        n_pkgs += 1
        for card in doc.get("cards") or []:
            cid, summ = card.get("card_id"), card.get("summary")
            if not cid or not isinstance(summ, dict):
                continue
            preds, thr = cw._card_warning_spec(cid, contracts)
            for wid, expr in preds:
                r = cw.evaluate(expr, summ, thr)
                if r is None:
                    continue
                evaluable[(cid, wid)] += 1
                if r:
                    fired[(cid, wid)] += 1
    suppressed = []
    firing_rates = {}
    for key, n in sorted(evaluable.items()):
        rate = fired[key] / n
        firing_rates[f"{key[0]}::{key[1]}"] = {"fired": fired[key], "evaluable": n, "rate": round(rate, 4)}
        if n >= _MIN_EVALUABLE and (rate > _HIGH or rate < _LOW):
            suppressed.append(list(key))
    return {
        "_note": "E2 calibration register — non-discriminating (card_id, warning_id) NOT emitted per-run.",
        "n_packages": n_pkgs,
        "thresholds": {"high": _HIGH, "low": _LOW, "min_evaluable": _MIN_EVALUABLE},
        "suppressed": suppressed,
        "firing_rates": firing_rates,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    reg = build(Path(sys.argv[1]).expanduser())
    _OUT.write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n")
    print(f"wrote {_OUT} — {len(reg['suppressed'])} suppressed of {len(reg['firing_rates'])} evaluable pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
