#!/usr/bin/env python
"""Freeze a REAL EGFR card-summary fixture for the target-intrinsic offline drift replay.

The sibling test_target_intrinsic_golden.py runs the dossier end-to-end on LIVE S3 and asserts a
field-name-drift floor (headline resolves broadly). That guard is the ONLY thing that catches the
reader-real-field-names bug class (a card method renames an output field → the `_HEADLINE_SPEC`
read resolves to None SILENTLY). But it SKIPS on a credential-less runner, so it never fires in PR
CI — the one environment where a drifting PR would be caught.

This script does the LIVE reads ONCE (needs S3 creds + the sibling repos) and freezes each of the
19 tier:target card summaries to fixtures/egfr.yaml. test_target_intrinsic_replay.py then replays
the frozen summaries THROUGH THE REAL run.py (dispatcher monkeypatched) so the SAME drift floor runs
deterministically + credential-less in PR CI. A nightly-live re-freeze (see freeze.py in
skills/tests/card_behavior_matrix/ for the OIDC pattern) catches drift in the frozen snapshot itself.

Mirror of skills/tests/card_behavior_matrix/freeze.py, scoped to a single target's card roster
(imported from run.py so the fixture stays in lockstep with the skill's CARDS).

Usage (from a repo checkout with siblings adjacent, AWS creds present):
    pixi run python skills/target-intrinsic/tests/freeze_fixture.py            # refreeze EGFR
    pixi run python skills/target-intrinsic/tests/freeze_fixture.py --target EGFR --out fixtures/egfr.yaml
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
for p in (str(SKILLS),):  # _skills_common (incl. rehomed _live_readers) resolves from SKILLS
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common import _import_dispatcher  # noqa: E402
from _test_support import freeze_card_summaries, load_run_py, prune_oversized  # noqa: E402


def _load_cards_from_runpy() -> list[str]:
    """Import the skill's run.py and return its CARDS literal (single source of truth)."""
    return list(load_run_py(SKILL_DIR, "_ti_run").CARDS)


def _prune(summary):
    """Shrink the committed fixture (500K → ~20K on EGFR) by replacing OVERSIZED list/dict payloads
    the dossier headline never reads (e.g. signaling-network-mechanism.kinome_atlas_predictions +
    the full upstream/downstream regulator lists) with a compact scalar sentinel.

    Two invariants make this safe:
      - EVERY field KEY is preserved, so a reader RENAMING a field is still caught by the drift floor
        (the replacement is on the VALUE, not the key).
      - Only list/dict values are ever replaced, and only above the cap. Every `_HEADLINE_SPEC` field
        the drift guard reads is a scalar (`*_class`, `n_*`, booleans) or a SHORT list well under the
        cap, so none is ever touched — the replacement lands only on raw payloads the headline ignores.
        Scalars (and the `n_*` counts, which are separate fields, NOT len(list)) always survive.
    Replacing with a SCALAR (not a truncated list) also keeps write_package's list-of-dict CSV emitter
    from choking on a non-record element. (Shared rule; see _test_support.prune_oversized.)"""
    return prune_oversized(summary)


def freeze(target: str, read_live) -> dict:
    """Live-read every tier:target card the skill consumes; return {card_id: summary|{_error}}.

    Passes the PANCANCER sentinel exactly as run.py does for an indication-free invocation
    (tier:target readers ignore it)."""
    return freeze_card_summaries(_load_cards_from_runpy(), target, "PANCANCER", read_live)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="EGFR")
    ap.add_argument(
        "--out",
        default=str(HERE / "fixtures" / "egfr.yaml"),
        help="fixture path (relative paths resolve under the tests dir)",
    )
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = HERE / out
    out.parent.mkdir(parents=True, exist_ok=True)

    read_live = _import_dispatcher()
    print(f"freezing {args.target} target-intrinsic dossier → {out} …", flush=True)
    frozen = freeze(args.target, read_live)
    out.write_text(yaml.safe_dump(frozen, sort_keys=True, default_flow_style=False))

    errs = {c: s.get("_freeze_error") for c, s in frozen.items() if isinstance(s, dict) and s.get("_freeze_error")}
    real = [
        c
        for c, s in frozen.items()
        if isinstance(s, dict) and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none") and s
    ]
    print(
        f"  wrote {len(frozen)} cards; {len(real)} with a real summary"
        + (f"; {len(errs)} read-errors: {json.dumps(errs)[:300]}" if errs else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
