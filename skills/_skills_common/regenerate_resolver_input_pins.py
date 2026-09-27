#!/usr/bin/env python3
"""Regenerate the cross-repo resolver-input pins (resolver_input_pins.yaml, issue #1525).

WHAT. Re-derives, per card, the raw ``summary.get("<field>")`` literals that the analysis-methods
property-resolver module reads, at a chosen analysis-methods commit, and rewrites
``resolver_input_pins.yaml``. The census reads that COMMITTED artifact (never the live AM tree), so the
aperture ratchet stays deterministic in CI and in a credential-less checkout; this regenerator is the
maintenance path when the AM resolver changes which fields it consumes.

NOT A CI TEST. The AM-sibling-gated freshness test
(``tests/test_field_disposition.py::test_resolver_input_pins_match_am_tree``) is what FAILS when this
file goes stale against the pinned commit; run this to fix it, then RE-BANK ``APERTURE_CEILING`` in the
same PR if the orphan count moved.

USAGE
    python3 regenerate_resolver_input_pins.py                 # keep the pinned commit, re-scrape it
    python3 regenerate_resolver_input_pins.py --commit <sha>  # re-pin to a new AM commit and scrape it
    python3 regenerate_resolver_input_pins.py --dry-run       # print, do not write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SKILLS_ROOT = Path(__file__).resolve().parents[1]  # .../skills
if str(_SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILLS_ROOT))

import yaml  # noqa: E402

from _skills_common import field_disposition as fd  # noqa: E402
from _skills_common.paths import analysis_methods_root  # noqa: E402

_PINS = Path(__file__).resolve().parent / fd.RESOLVER_INPUT_PINS_NAME


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--commit", default=None, help="re-pin to this analysis-methods commit (default: keep)")
    ap.add_argument("--dry-run", action="store_true", help="print the regenerated pins, do not write")
    args = ap.parse_args(argv)

    doc = fd.load_resolver_input_pins(_SKILLS_ROOT)
    if not doc.get("resolver_reads"):
        print("resolver_input_pins.yaml has no resolver_reads block to regenerate", file=sys.stderr)
        return 1
    if args.commit:
        doc["analysis_methods_commit"] = args.commit

    scraped = fd.scrape_am_resolver_reads(analysis_methods_root(), doc)
    if scraped is None:
        print(
            f"cannot scrape: analysis-methods sibling absent or commit {doc.get('analysis_methods_commit')} "
            "not present in the local clone. Fetch it first, then re-run.",
            file=sys.stderr,
        )
        return 2

    for card, modules in (doc.get("resolver_reads") or {}).items():
        for module in list(modules):
            modules[module] = scraped.get(card, {}).get(module, [])

    text = (
        _PINS.read_text().split("\nanalysis_methods_commit:", 1)[0]
        + "\nanalysis_methods_commit: "
        + str(doc["analysis_methods_commit"])
        + "\n\nresolver_reads:\n"
        + yaml.safe_dump({"resolver_reads": doc["resolver_reads"]}, sort_keys=True).split("resolver_reads:\n", 1)[1]
    )
    if args.dry_run:
        print(text)
        return 0
    _PINS.write_text(text)
    print(f"wrote {_PINS} (pinned {doc['analysis_methods_commit']}). Re-bank APERTURE_CEILING if it moved.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
