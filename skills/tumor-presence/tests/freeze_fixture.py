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

_FIELD_BYTES_CAP = 3000  # replace list/dict field values larger than this with a compact sentinel


def _load_cards_from_runpy() -> list[str]:
    """Import the skill's run.py and return its CARDS literal (single source of truth)."""
    spec = importlib.util.spec_from_file_location("_tp_run", SKILL_DIR / "scripts" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # top-level only; no __main__ side effects
    return list(mod.CARDS)


def _prune(summary):
    """Shrink the committed fixture by replacing OVERSIZED list/dict payloads the verdict + headline
    never key on with a compact scalar sentinel. Every field KEY is preserved (so a reader RENAMING a
    field is still caught); only list/dict values above the cap are replaced; scalars + the `n_*`
    counts + `*_class` values the rules/headline read always survive. Replacing with a SCALAR keeps
    write_package's list-of-dict CSV emitter from choking on a non-record element. (Identical rule to
    target-intrinsic's freezer.)"""
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
        except Exception as e:  # noqa: BLE001 — record, never abort the freeze
            summary = {"_freeze_error": f"{type(e).__name__}: {e}"}
        frozen[card] = _prune(summary) if summary is not None else {"_dispatcher_returned_none": True}
    return frozen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="EPCAM")
    ap.add_argument("--indication", default="COADREAD")
    ap.add_argument(
        "--out", default=None, help="fixture path (default fixtures/<target>_<indication>.yaml, lowercased)"
    )
    args = ap.parse_args()

    out = Path(args.out) if args.out else (HERE / "fixtures" / f"{args.target.lower()}_{args.indication.lower()}.yaml")
    if not out.is_absolute():
        out = HERE / out
    out.parent.mkdir(parents=True, exist_ok=True)

    read_live = _import_dispatcher()
    print(f"freezing {args.target}/{args.indication} tumor-presence dossier → {out} …", flush=True)
    frozen = freeze(args.target, args.indication, read_live)
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
