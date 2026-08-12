#!/usr/bin/env python
"""Freeze real card-summary fixtures for the card-behavior matrix (#5).

The matrix asserts, per (pair, card), that the card lands in the correct one of FOUR states —
informative / data_unavailable / measured_negative / not_in_scope — on REAL data. This script does
the LIVE reads (needs S3 creds + the sibling repos) once and freezes each card's summary to a
per-pair fixture; the offline test (test_card_behavior_matrix.py) replays the frozen fixtures so CI
is deterministic + credential-less. A scheduled nightly job re-runs this against live S3 to catch
drift + the reachable-but-dead-reader class (a card that stops firing on real data).

Usage (from a repo checkout with siblings adjacent, AWS creds present):
    python freeze.py                # freeze every pair whose `freeze: pending|refresh`
    python freeze.py --pair kras_coadread   # one pair
    python freeze.py --all          # re-freeze every pair
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent.parent                       # .../skills
for p in (str(SKILLS), str(SKILLS / "compose-dashboard" / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common import _import_dispatcher      # noqa: E402


def freeze_pair(pair: dict, read_live) -> dict:
    """Live-read every card the pair lists; return {card_id: summary|{_error}}."""
    target, indication = pair["target"], pair["indication"]
    subgroups = pair.get("subgroup_spec")           # list | None
    ctx = {"resolved_strata_ids": subgroups, "catalog_status": "resolved_active"} if subgroups else None
    frozen = {}
    for card in sorted({e["card"] for e in pair["expect"]}):
        try:
            summary = read_live(card, target, indication, subgroup_context=ctx) if ctx \
                else read_live(card, target, indication)
        except TypeError:                           # dispatcher predates subgroup_context kwarg
            summary = read_live(card, target, indication)
        except Exception as e:                      # noqa: BLE001 — record, never abort the freeze
            summary = {"_freeze_error": f"{type(e).__name__}: {e}"}
        frozen[card] = summary if summary is not None else {"_dispatcher_returned_none": True}
    return frozen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair"); ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    matrix = yaml.safe_load((HERE / "matrix.yaml").read_text())
    read_live = _import_dispatcher()
    fixtures = HERE / "fixtures"; fixtures.mkdir(exist_ok=True)
    for pair in matrix["pairs"]:
        pid = pair["id"]
        if args.pair and pid != args.pair:
            continue
        if not (args.all or args.pair or pair.get("freeze") in ("pending", "refresh")):
            continue
        print(f"freezing {pid} ({pair['target']}/{pair['indication']}"
              f"{' +subtypes' if pair.get('subgroup_spec') else ''}) …", flush=True)
        frozen = freeze_pair(pair, read_live)
        (fixtures / f"{pid}.yaml").write_text(yaml.safe_dump(frozen, sort_keys=True, default_flow_style=False))
        errs = {c: s.get("_freeze_error") for c, s in frozen.items() if isinstance(s, dict) and s.get("_freeze_error")}
        print(f"  wrote {len(frozen)} cards"
              + (f"; {len(errs)} read-errors: {json.dumps(errs)[:200]}" if errs else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
