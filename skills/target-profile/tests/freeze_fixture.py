#!/usr/bin/env python
"""Freeze a REAL card-summary fixture for the target-profile FAN-OUT offline replay.

target-profile is the composed engine: it fans out to 10 sub-skills in-process (_run_sub_skills →
_one_sub_skill), and for EACH sub-skill it (a) resolves that sub-skill's SUB_SKILL_CARDS entry,
(b) applies the gate's card preprocessor (preprocess_cards_for_gate — the genomic family-wise FDR, G1),
(c) fires rules on both axes scoped by card_id_filter, and (d) calls the sub-skill's OWN _verdict
(which carries any post-resolver clamp, e.g. tumor-selectivity's normal-breadth veto, F1). This is the
exact path where the F1 (selectivity veto) / G1 (genomic FDR) / safety (alteration-role downgrade)
seam bugs manifested.

Unlike compose-dashboard, target-profile has NO full-run offline byte-golden (its resolve_cards needs
live S3), so the fan-out MACHINERY was never exercised offline over REAL card summaries with REAL
verdict logic — test_subskill_composition.py monkeypatches away BOTH the data boundary and the verdict
functions, so it tests composition plumbing only.

This script does the LIVE reads ONCE (needs S3 creds + the sibling repos) and freezes the UNION of all
10 sub-skills' cards to fixtures/<target>_<indication>.yaml; test_fanout_replay.py monkeypatches the live
dispatcher to serve the frozen union and runs the REAL _run_sub_skills, asserting each composed
sub-verdict — so the fan-out's preprocess + card_id_filter + per-sub-skill _verdict (incl. clamps) all
run deterministically + credential-less in CI. A nightly-live re-freeze (card-behavior-matrix-nightly)
catches drift in the frozen snapshot itself.

Usage (from a repo checkout with siblings adjacent, AWS creds present):
    pixi run python skills/target-profile/tests/freeze_fixture.py --target KRAS --indication COADREAD
    pixi run python skills/target-profile/tests/freeze_fixture.py --target TACSTD2 --indication COADREAD
"""

from __future__ import annotations

import argparse
import importlib.util
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
from _test_support import prune_oversized  # noqa: E402


def _load_union_cards_from_runpy(sub_skills: list[str] | None = None) -> list[str]:
    """Import target-profile run.py and return the UNION of SUB_SKILL_CARDS entries (single source of
    truth). When `sub_skills` is given, restrict the union to just those sub-skill dirs — the fan-out
    reads any un-frozen card as _missing (→ that sub-skill resolves insufficient), so a fixture scoped
    to the seam-critical sub-skills (selectivity/genomic/safety) keeps the freeze fast while still
    exercising the fan-out machinery (preprocess + card_id_filter + per-sub-skill _verdict) for them."""
    spec = importlib.util.spec_from_file_location("_tp_run", SKILL_DIR / "scripts" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # top-level only; no __main__ side effects
    dirs = sub_skills if sub_skills else list(mod.SUB_SKILL_CARDS.keys())
    union: set[str] = set()
    for d in dirs:
        union.update(mod.SUB_SKILL_CARDS.get(d, []))
    return sorted(union)


def _prune(summary):
    """Shrink the committed fixture by replacing OVERSIZED list/dict payloads the verdicts never key on
    with a compact scalar sentinel. Every field KEY is preserved (so a reader RENAMING a field is still
    caught); only list/dict values above the cap are replaced; scalars + the `*_class` values the rules
    read always survive. (Shared rule; see _test_support.prune_oversized.)"""
    return prune_oversized(summary)


def freeze(target: str, indication: str, read_live) -> dict:
    """Live-read every card in the fan-out union for (target, indication); return {card_id: summary}."""
    frozen: dict = {}
    for card in _load_union_cards_from_runpy():
        try:
            summary = read_live(card, target, indication)
        except Exception as e:  # noqa: BLE001 — record, never abort the freeze
            summary = {"_freeze_error": f"{type(e).__name__}: {e}"}
        frozen[card] = _prune(summary) if summary is not None else {"_dispatcher_returned_none": True}
    return frozen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="KRAS")
    ap.add_argument("--indication", default="COADREAD")
    ap.add_argument(
        "--out", default=None, help="fixture path (default fixtures/<target>_<indication>.yaml, lowercased)"
    )
    ap.add_argument(
        "--sub-skills",
        default=None,
        help="comma-separated sub-skill dirs to restrict the frozen union to "
        "(default: all 10). Un-frozen sub-skills read _missing in the replay.",
    )
    args = ap.parse_args()
    sub_skills = [s.strip() for s in args.sub_skills.split(",")] if args.sub_skills else None

    out = Path(args.out) if args.out else (HERE / "fixtures" / f"{args.target.lower()}_{args.indication.lower()}.yaml")
    if not out.is_absolute():
        out = HERE / out
    out.parent.mkdir(parents=True, exist_ok=True)

    read_live = _import_dispatcher()
    union = _load_union_cards_from_runpy(sub_skills)
    print(
        f"freezing {args.target}/{args.indication} fan-out union ({len(union)} cards"
        + (f", sub-skills={sub_skills}" if sub_skills else "")
        + f") -> {out} ...",
        flush=True,
    )
    frozen = {}
    for card in union:
        try:
            summary = read_live(card, args.target, args.indication)
        except Exception as e:  # noqa: BLE001
            summary = {"_freeze_error": f"{type(e).__name__}: {e}"}
        frozen[card] = _prune(summary) if summary is not None else {"_dispatcher_returned_none": True}
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
