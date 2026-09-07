#!/usr/bin/env python3
"""live_reader_smoke.py — breadth live-data smoke: fail if ANY wired reader hard-errors for a
canonical target, across ALL fan-out sub-skills.

Every PR's CI self-skips live S3, so a data-shape change (a renamed parquet column, a moved shard, a
deleted/renamed manifest) makes a reader return {"_live_read_error": ...} and the sub-verdict silently
degrades to `insufficient` — with all CI green. The existing nightly re-freeze guards this drift class
for 4 skills via per-skill fixtures; this complements it with BREADTH: it runs the full in-process
fan-out (_run_sub_skills) for a canonical target (default KRAS/COADREAD) against REAL data and FAILS on
any `_live_read_error` in ANY of the ~15 wired sub-skills.

`data_unavailable` (the target/indication genuinely has no data for a card) is a LEGITIMATE soft state,
reported as INFO — only the hard `_live_read_error` (a reader that blew up: resolver_not_found /
resolver_error / a raised read) fails the smoke.

Requires live S3 (AWS creds). Intended for the nightly credentialed job (HAVE_AWS), not PR CI.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[1] / "skills"  # eval/ is repo-root; skills/ is its sibling
for _p in (str(_SKILLS), str(_SKILLS / "target-profile" / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tp_fanout import _run_sub_skills  # noqa: E402


def _find_live_read_errors(node, path: str = "") -> list[tuple[str, object]]:
    """Walk a card_output structure, returning (dotted-path, error) for every `_live_read_error`."""
    hits: list[tuple[str, object]] = []
    if isinstance(node, dict):
        if "_live_read_error" in node:
            hits.append((path or "<root>", node["_live_read_error"]))
        for k, v in node.items():
            hits += _find_live_read_errors(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            hits += _find_live_read_errors(v, f"{path}[{i}]")
    return hits


def _mentions_data_unavailable(card: dict) -> bool:
    summary = card.get("summary")
    return isinstance(summary, dict) and any(v == "data_unavailable" for v in summary.values())


def run(target: str, indication: str) -> int:
    print(f"[live-smoke] running the full fan-out for {target}/{indication} against LIVE data ...", flush=True)
    sub_results = _run_sub_skills(target, indication)

    errors: list[tuple[str, str, str, object]] = []  # (short, card_id, path, error)
    n_cards = 0
    n_unavailable = 0
    for short, res in sub_results.items():
        for card in res.get("cards") or []:
            n_cards += 1
            cid = card.get("card_id", "?")
            for p, e in _find_live_read_errors(card):
                errors.append((short, cid, p, e))
            if _mentions_data_unavailable(card):
                n_unavailable += 1

    print(
        f"[live-smoke] {len(sub_results)} sub-skills · {n_cards} card reads · "
        f"{n_unavailable} data_unavailable (info) · {len(errors)} _live_read_error"
    )
    if errors:
        print(
            f"::error title=live-reader-smoke::{len(errors)} reader hard-error(s) for "
            f"{target}/{indication} — a data-shape/shard/manifest change silently broke a live read "
            f"(the sub-verdict would degrade to insufficient with PR CI still green):",
            file=sys.stderr,
        )
        for short, cid, p, e in errors:
            print(f"  - {short} / {cid} / {p}: {e}", file=sys.stderr)
        return 1
    print(f"[live-smoke] OK — no reader hard-errors for {target}/{indication}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", default="KRAS")
    ap.add_argument("--indication", default="COADREAD")
    args = ap.parse_args(argv)
    return run(args.target, args.indication)


if __name__ == "__main__":
    sys.exit(main())
