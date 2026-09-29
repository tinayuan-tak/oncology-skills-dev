#!/usr/bin/env python
"""Freeze a REAL EPCAM/COADREAD card-summary fixture for the tumor-presence offline drift replay.

tumor-presence is VERDICT-BEARING, and every one of its ~46 unit tests feeds `_verdict` /
`_per_modality_verdicts` / `_headline` SYNTHETIC inputs (hand-built `fired` rule-id lists +
fabricated card summaries carrying the run.py field names). That makes them tautological w.r.t.
reader drift: if a card method RENAMES an output field, the synthetic test still uses the run.py
key and passes green, while in production (a) the `_HEADLINE_SPEC`-style `get_card_field` read
resolves to None SILENTLY, and — worse for a verdict-bearing skill — (b) a rule that keys the
renamed field stops firing, collapsing `presence_verdict` to a false-negative
insufficient/data_unavailable. No test runs `fired_rules` over a real summary.

This script does the LIVE reads ONCE (needs S3 creds + the sibling repos) and freezes each of the
14 card summaries to fixtures/epcam_coadread.yaml; test_tumor_presence_replay.py replays them THROUGH
THE REAL run.py (dispatcher monkeypatched) so the verdict + per-modality + headline drift floors run
deterministically + credential-less in PR CI. A nightly-live re-freeze (card-behavior-matrix-nightly)
catches drift in the frozen snapshot itself.

Mirror of skills/target-intrinsic/tests/freeze_fixture.py; the one difference is tumor-presence takes
a real --indication (target-intrinsic is indication-free and passes the PANCANCER sentinel).

Usage (from a repo checkout with siblings adjacent, AWS creds present):
    pixi run python skills/tumor-presence/tests/freeze_fixture.py            # refreeze EPCAM/COADREAD
    pixi run python skills/tumor-presence/tests/freeze_fixture.py --target CEACAM5 --indication COADREAD
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
SKILLS = SKILL_DIR.parent  # .../skills
if str(SKILLS) not in sys.path:  # _skills_common / _test_support resolve from skills/
    sys.path.insert(0, str(SKILLS))

from _skills_common import _import_dispatcher  # noqa: E402
from _test_support import freeze_card_summaries, load_run_py  # noqa: E402

DEFAULT_TARGET = "EPCAM"
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
