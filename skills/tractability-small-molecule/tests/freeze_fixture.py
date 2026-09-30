#!/usr/bin/env python
"""Freeze a REAL card-summary fixture for the tractability-small-molecule offline verdict-replay.

tractability-small-molecule is VERDICT-BEARING (druggability_snapshot via the shared declarative
resolver) and has a DOCUMENTED history of reader-drift bugs: the T5.1 fix (2026-08-09) caught that
the headline read the WRONG field names (activity_class / concordance_class instead of
prism_activity_class / crispr_prism_concordance_class) so two chemical facts were ALWAYS None and the
LLM prompt was starved — a silent reader drift no synthetic test caught. Its existing tests feed the
resolver SYNTHETIC fired-sets (test_resolver_oracle_equivalence / test_snapshot_ladder), so a card
method RENAMING a field a rule keys on passes green while in production the rule stops firing and the
druggability_snapshot silently changes class. No existing test runs `fired_rules` over a real summary.

This script does the LIVE reads ONCE (needs S3 creds + the sibling repos) and freezes each card summary
to fixtures/<target>_<indication>.yaml; test_tractability_sm_replay.py replays them THROUGH THE REAL
run.py (dispatcher monkeypatched) so the intracellular_intrinsic rule-firing + the shared
tractability_small_molecule resolver + the degrader-lens projection run deterministically +
credential-less in CI. A nightly-live re-freeze (card-behavior-matrix-nightly) catches drift in the
frozen snapshot itself.

Mirror of skills/tumor-selectivity/tests/freeze_fixture.py (same _prune, same shape).

Usage (from a repo checkout with siblings adjacent, AWS creds present):
    pixi run python skills/tractability-small-molecule/tests/freeze_fixture.py --target EGFR --indication COADREAD
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

DEFAULT_TARGET = "EGFR"
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
