#!/usr/bin/env python
"""Freeze a REAL card-summary fixture for the differentiation-landscape offline verdict-replay.

differentiation-landscape is VERDICT-BEARING (differentiation verdict via the shared declarative
resolver) — its co-occurrence/mutual-exclusivity verdict is driven by the co-mutation-and-mutual-
exclusivity card (panel-intersect-aware Fisher over TCGA MC3 + GENIE). Its only test feeds the resolver
SYNTHETIC fired-sets, so a card method RENAMING a field a rule keys on passes green while in production
the rule stops firing and the verdict silently drops (strong_cooccurring → ns → data_unavailable). No
existing test runs `fired_rules` over a real summary.

This script does the LIVE reads ONCE (needs S3 creds + the sibling repos) and freezes each card summary
to fixtures/<target>_<indication>.yaml; test_differentiation_replay.py replays them THROUGH THE REAL
run.py (dispatcher monkeypatched) so the intracellular_intrinsic rule-firing + the shared differentiation
resolver run deterministically + credential-less in CI. A nightly-live re-freeze
(card-behavior-matrix-nightly) catches drift in the frozen snapshot itself.

Mirror of skills/tumor-selectivity/tests/freeze_fixture.py (same _prune, same shape).

Usage (from a repo checkout with siblings adjacent, AWS creds present):
    pixi run python skills/differentiation-landscape/tests/freeze_fixture.py --target KRAS --indication COADREAD
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
SKILLS = SKILL_DIR.parent                              # .../skills
for p in (str(SKILLS),):     # _skills_common (incl. rehomed _live_readers) resolves from SKILLS
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common import _import_dispatcher           # noqa: E402

_FIELD_BYTES_CAP = 3000   # replace list/dict field values larger than this with a compact sentinel


def _load_cards_from_runpy() -> list[str]:
    """Import the skill's run.py and return its CARDS literal (single source of truth)."""
    spec = importlib.util.spec_from_file_location("_diff_run", SKILL_DIR / "scripts" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                         # top-level only; no __main__ side effects
    return list(mod.CARDS)


def _prune(summary):
    """Shrink the committed fixture by replacing OVERSIZED list/dict payloads the verdict never keys
    on with a compact scalar sentinel. Every field KEY is preserved (so a reader RENAMING a field is
    still caught); only list/dict values above the cap are replaced; scalars + the `*_class` values
    the rules read always survive. (Identical rule to the sibling freezers.)"""
    if not isinstance(summary, dict):
        return summary
    out = {}
    for k, v in summary.items():
        if isinstance(v, (list, dict)) and len(json.dumps(v, default=str)) > _FIELD_BYTES_CAP:
            out[k] = f"__omitted_from_fixture__ ({type(v).__name__}, {len(v)} items)"
        else:
            out[k] = v
    return out


def freeze(target: str, indication: str, read_live) -> dict:
    """Live-read every card the skill consumes for (target, indication); return {card_id: summary}."""
    frozen: dict = {}
    for card in _load_cards_from_runpy():
        try:
            summary = read_live(card, target, indication)
        except Exception as e:                          # noqa: BLE001 — record, never abort the freeze
            summary = {"_freeze_error": f"{type(e).__name__}: {e}"}
        frozen[card] = _prune(summary) if summary is not None else {"_dispatcher_returned_none": True}
    return frozen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="KRAS")
    ap.add_argument("--indication", default="COADREAD")
    ap.add_argument("--out", default=None,
                    help="fixture path (default fixtures/<target>_<indication>.yaml, lowercased)")
    args = ap.parse_args()

    out = Path(args.out) if args.out else (
        HERE / "fixtures" / f"{args.target.lower()}_{args.indication.lower()}.yaml")
    if not out.is_absolute():
        out = HERE / out
    out.parent.mkdir(parents=True, exist_ok=True)

    read_live = _import_dispatcher()
    print(f"freezing {args.target}/{args.indication} differentiation dossier -> {out} ...", flush=True)
    frozen = freeze(args.target, args.indication, read_live)
    out.write_text(yaml.safe_dump(frozen, sort_keys=True, default_flow_style=False))

    errs = {c: s.get("_freeze_error") for c, s in frozen.items()
            if isinstance(s, dict) and s.get("_freeze_error")}
    real = [c for c, s in frozen.items()
            if isinstance(s, dict) and not s.get("_freeze_error")
            and not s.get("_dispatcher_returned_none") and s]
    print(f"  wrote {len(frozen)} cards; {len(real)} with a real summary"
          + (f"; {len(errs)} read-errors: {json.dumps(errs)[:300]}" if errs else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
