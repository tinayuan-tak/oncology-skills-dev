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
import importlib.util
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
SKILLS = SKILL_DIR.parent
for p in (str(SKILLS),):     # _skills_common (incl. rehomed _live_readers) resolves from SKILLS
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common import _import_dispatcher   # noqa: E402

_FIELD_BYTES_CAP = 3000


def _load_cards_from_runpy() -> list[str]:
    spec = importlib.util.spec_from_file_location("_fr_run", SKILL_DIR / "scripts" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.CARDS)


def _prune(summary):
    """Replace oversized list/dict payloads (never read by the verdict/headline) with a scalar
    sentinel; keep every KEY (drift still caught) + all scalars. Identical rule to the sibling freezers."""
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
    frozen: dict = {}
    for card in _load_cards_from_runpy():
        try:
            summary = read_live(card, target, indication)
        except Exception as e:                              # noqa: BLE001
            summary = {"_freeze_error": f"{type(e).__name__}: {e}"}
        frozen[card] = _prune(summary) if summary is not None else {"_dispatcher_returned_none": True}
    return frozen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="KRAS")
    ap.add_argument("--indication", default="COADREAD")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = Path(args.out) if args.out else (
        HERE / "fixtures" / f"{args.target.lower()}_{args.indication.lower()}.yaml")
    if not out.is_absolute():
        out = HERE / out
    out.parent.mkdir(parents=True, exist_ok=True)
    read_live = _import_dispatcher()
    print(f"freezing {args.target}/{args.indication} functional-requirement dossier → {out} …", flush=True)
    frozen = freeze(args.target, args.indication, read_live)
    out.write_text(yaml.safe_dump(frozen, sort_keys=True, default_flow_style=False))
    real = [c for c, s in frozen.items()
            if isinstance(s, dict) and not s.get("_freeze_error")
            and not s.get("_dispatcher_returned_none") and s]
    errs = {c: s.get("_freeze_error") for c, s in frozen.items()
            if isinstance(s, dict) and s.get("_freeze_error")}
    print(f"  wrote {len(frozen)} cards; {len(real)} with a real summary"
          + (f"; errors: {json.dumps(errs)[:300]}" if errs else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
