#!/usr/bin/env python
"""Freeze a REAL KRAS/COADREAD card-summary fixture for the functional-requirement offline replay.

functional-requirement is verdict-bearing but all its existing tests feed `_verdict` SYNTHETIC
fired-rule lists — tautological w.r.t. reader-field drift. This skill has already shipped TWO silent
field-name drift bugs (v1.3.1). This freezer does the LIVE reads once (S3 + siblings) and freezes each
card summary to fixtures/kras_coadread.yaml; test_functional_requirement_replay.py replays them THROUGH
THE REAL run.py (dispatcher monkeypatched) so drift is caught deterministically + credential-less in PR CI.

Mirror of skills/tumor-selectivity/tests/freeze_fixture.py (indication-scoped). KRAS/COADREAD is the
canonical dependency reference (bimodal → concordant_dependent; also the compose-dashboard
engine-equivalence anchor), stable across the 2026-08-13 classifier fixes (bimodal, unaffected by the
non_essential/RNAi-bimodality changes).

Usage (repo checkout with siblings adjacent, AWS creds present):
    pixi run python skills/functional-requirement/tests/freeze_fixture.py            # refreeze KRAS/COADREAD
    pixi run python skills/functional-requirement/tests/freeze_fixture.py --target MET --indication COADREAD
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent

from _skills_common import _import_dispatcher  # noqa: E402
from _test_support import freeze_card_summaries, load_run_py  # noqa: E402

DEFAULT_TARGET = "KRAS"
DEFAULT_INDICATION = "COADREAD"


def _cards() -> list[str]:
    """The skill's card roster, read once from run.py (single source of truth)."""
    return list(load_run_py(SKILL_DIR).CARDS)


def freeze(target: str, indication: str, read_live) -> dict:
    """Live-read + prune every card summary for (target, indication). See _test_support.freeze_card_summaries."""
    return freeze_card_summaries(_cards(), target, indication, read_live)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--indication", default=DEFAULT_INDICATION)
    ap.add_argument(
        "--out", default=None, help="fixture path (default fixtures/<target>_<indication>.yaml, lowercased)"
    )
    args = ap.parse_args()
    out = Path(args.out) if args.out else (HERE / "fixtures" / f"{args.target.lower()}_{args.indication.lower()}.yaml")
    if not out.is_absolute():
        out = HERE / out
    out.parent.mkdir(parents=True, exist_ok=True)
    read_live = _import_dispatcher()
    print(f"freezing {args.target}/{args.indication} {SKILL_DIR.name} dossier -> {out} ...", flush=True)
    frozen = freeze(args.target, args.indication, read_live)
    out.write_text(yaml.safe_dump(frozen, sort_keys=True, default_flow_style=False))
    real = [
        c
        for c, s in frozen.items()
        if isinstance(s, dict) and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none") and s
    ]
    errs = {c: s.get("_freeze_error") for c, s in frozen.items() if isinstance(s, dict) and s.get("_freeze_error")}
    print(
        f"  wrote {len(frozen)} cards; {len(real)} with a real summary"
        + (f"; errors: {json.dumps(errs)[:300]}" if errs else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
