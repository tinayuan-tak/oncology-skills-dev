#!/usr/bin/env python
"""Freeze a REAL card-summary fixture for the surface-modality-fit offline verdict-replay.

surface-modality-fit is VERDICT-BEARING, and its verdict is resolver-native but MULTI-CARD: the
surface_modality resolver combines the composed adc-tce-modality-fit `fit_class` base rung with
KILLER/downgrade rungs (`when_all_fired: [<fit-supportive>, <killer-rule>]`) fed by four liability
cards — normal-tissue-liability (bite_tce killer), sc-normal-celltype-expression (bite_tce killer),
surface-abundance-density (TCE-floor downgrade), shed-ectodomain-liability (shed opposing) — plus the
ihc-not-detected protein killer. NO existing test runs `fired_rules` over a real summary, so a reader
RENAMING a field any of these rungs keys on (fit_class, safety_tissue_flags, the sc-normal liability,
the density floor, the shed class) would SILENTLY drop that killer/downgrade → a TCE-unsafe or shed or
density-limited antigen reads as cleanly both_viable (a FALSE biologics-fit call).

This script does the LIVE reads ONCE (needs S3 creds + the sibling repos) and freezes each card summary
to fixtures/<target>_<indication>.yaml; test_surface_modality_replay.py replays them THROUGH THE REAL
run.py (dispatcher monkeypatched) so the surface_intrinsic rule-firing + the shared surface_modality
resolver (incl. all killer/downgrade combination rungs) run deterministically + credential-less in CI.
A nightly-live re-freeze (card-behavior-matrix-nightly) catches drift in the frozen snapshot itself.

Mirror of skills/tumor-selectivity/tests/freeze_fixture.py (same _prune, same shape).

Usage (from a repo checkout with siblings adjacent, AWS creds present):
    pixi run python skills/surface-modality-fit/tests/freeze_fixture.py --target CEACAM5 --indication COADREAD
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

DEFAULT_TARGET = "CEACAM5"
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
