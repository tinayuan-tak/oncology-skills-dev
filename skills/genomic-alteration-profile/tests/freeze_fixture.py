#!/usr/bin/env python
"""Freeze a REAL card-summary fixture for the genomic-alteration-profile offline verdict-replay.

genomic-alteration-profile is VERDICT-BEARING (multi-class genomic_alteration_profile via the shared
declarative resolver), yet its only tests before this one — test_genomic_alteration_verdict.py +
test_family_wise_fdr.py — feed `_verdict` / `_apply_family_wise_fdr` SYNTHETIC inputs (hand-built
`fired` rule-id lists + fabricated card summaries carrying the run.py field names). Those are
tautological w.r.t. reader drift: if a card method RENAMES an output field, the synthetic test still
uses the run.py key and passes green, while in production a rule that keys the renamed field stops
firing, so the resolver verdict SILENTLY changes class (e.g. a confirmed_driver / biomarker_stratified_
dependency collapses to passenger_pattern / insufficient — the nomination-moving failure mode). No
existing test runs `fired_rules` over a REAL summary for this skill.

This script does the LIVE reads ONCE (needs S3 creds + the sibling repos) and freezes each of the 17
card summaries to fixtures/<target>_<indication>.yaml; test_genomic_replay.py replays them THROUGH THE
REAL run.py (dispatcher monkeypatched) so the family-wise FDR preprocessor + the intracellular_intrinsic
rule-firing + the shared genomic_alteration resolver all execute deterministically + credential-less in
PR CI. A nightly-live re-freeze (card-behavior-matrix-nightly) catches drift in the frozen snapshot itself.

Mirror of skills/tumor-selectivity/tests/freeze_fixture.py (same _prune, same shape); the skill differs
only in its CARDS roster (17 cards) + that a genomic verdict has no post-resolver veto clamp.

Usage (from a repo checkout with siblings adjacent, AWS creds present):
    pixi run python skills/genomic-alteration-profile/tests/freeze_fixture.py            # refreeze KRAS/COADREAD
    pixi run python skills/genomic-alteration-profile/tests/freeze_fixture.py --target BRAF --indication COADREAD
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
for p in (str(SKILLS), str(SKILLS / "compose-dashboard" / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common import _import_dispatcher           # noqa: E402

_FIELD_BYTES_CAP = 3000   # replace list/dict field values larger than this with a compact sentinel


def _load_cards_from_runpy() -> list[str]:
    """Import the skill's run.py and return its CARDS literal (single source of truth)."""
    spec = importlib.util.spec_from_file_location("_gap_run", SKILL_DIR / "scripts" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                         # top-level only; no __main__ side effects
    return list(mod.CARDS)


def _prune(summary):
    """Shrink the committed fixture by replacing OVERSIZED list/dict payloads the verdict never keys
    on with a compact scalar sentinel. Every field KEY is preserved (so a reader RENAMING a field is
    still caught); only list/dict values above the cap are replaced; scalars + the `*_class` values
    the rules read always survive. Replacing with a SCALAR keeps write_package's list-of-dict CSV
    emitter from choking on a non-record element. (Identical rule to the sibling freezers.)"""
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
    print(f"freezing {args.target}/{args.indication} genomic-alteration dossier -> {out} ...", flush=True)
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
