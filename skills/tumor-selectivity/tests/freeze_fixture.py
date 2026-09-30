#!/usr/bin/env python
"""Freeze a REAL card-summary fixture for the tumor-selectivity offline verdict-replay.

tumor-selectivity is VERDICT-BEARING, and its only test (test_verdict.py) feeds `_verdict` /
`_headline` SYNTHETIC inputs (hand-built `fired` rule-id lists + fabricated card summaries carrying
the run.py field names). Those tests are tautological w.r.t. reader drift: if a card method RENAMES
an output field, the synthetic test still uses the run.py key and passes green, while in production
(a) the `_headline` `get`-reads resolve to None SILENTLY, and — worse for this skill — (b) a rule
that keys the renamed field stops firing, so the resolver verdict collapses (a selective call →
insufficient) OR a normal-breadth VETO rule stops firing (a broadly-normal gene reads as
tumor_selective — a FALSE POSITIVE, the failure mode this skill's veto exists to prevent). No test
runs `fired_rules` over a real summary.

This script does the LIVE reads ONCE (needs S3 creds + the sibling repos) and freezes each card
summary (one per entry in run.py CARDS) to fixtures/<target>_<indication>.yaml;
test_selectivity_replay.py replays them
THROUGH THE REAL run.py (dispatcher monkeypatched) so the resolver verdict + post-resolver veto
clamp + headline drift floors run deterministically + credential-less in PR CI. A nightly-live
re-freeze (card-behavior-matrix-nightly) catches drift in the frozen snapshot itself.

Mirror of skills/tumor-presence/tests/freeze_fixture.py (same _prune, same shape); the skill differs
only in its CARDS roster + that it takes a real --indication.

Usage (from a repo checkout with siblings adjacent, AWS creds present):
    pixi run python skills/tumor-selectivity/tests/freeze_fixture.py            # refreeze CEACAM5/COADREAD
    pixi run python skills/tumor-selectivity/tests/freeze_fixture.py --target TACSTD2 --indication COADREAD
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
