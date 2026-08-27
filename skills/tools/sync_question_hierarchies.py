#!/usr/bin/env python
"""Generate each skill's question_hierarchy.yaml FROM the governed single source of truth
(target-contracts vocabularies/target_profiling_axes.yaml `question_hierarchies`).

The sub-group/question decomposition is ontology: it is consolidated in target-contracts (where its card
binding via measurement_types.yaml is validated) and MIRRORED into each skill dir as a generated
artifact. This tool regenerates those mirrors; the paired drift test (skills/tests/
test_question_hierarchy_drift.py) fails CI if a committed mirror diverges from contracts — so the
hierarchy is edited in ONE place (contracts) and can never silently drift here.

    python skills/tools/sync_question_hierarchies.py            # --check: report drift, exit 1 if any
    python skills/tools/sync_question_hierarchies.py --write     # rewrite each question_hierarchy.yaml

Requires target-contracts on TARGET_CONTRACTS_ROOT; prints a skip notice and exits 0 without it.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent
CONTRACTS = Path(
    os.environ.get(
        "TARGET_CONTRACTS_ROOT",
        str(SKILLS_DIR.parent.parent / "rnd-computational-biology-oncology-target-contracts"),
    )
)
AXES = CONTRACTS / "vocabularies" / "target_profiling_axes.yaml"

_HEADER = ("# GENERATED from target-contracts vocabularies/target_profiling_axes.yaml "
           "(question_hierarchies).\n"
           "# Do NOT hand-edit: edit the governed source there and run "
           "skills/tools/sync_question_hierarchies.py --write.\n"
           "# The paired drift test (skills/tests/test_question_hierarchy_drift.py) fails CI on divergence.\n")


def contracts_available() -> bool:
    return AXES.exists()


def load_source() -> dict:
    """{skill: {sub_groups, other_lenses?}} — the mirror content each question_hierarchy.yaml should hold."""
    section = (yaml.safe_load(AXES.read_text()) or {}).get("question_hierarchies") or {}
    out = {}
    for skill, spec in section.items():
        doc = {"skill": skill, "sub_groups": spec.get("sub_groups") or []}
        if spec.get("other_lenses"):
            doc["other_lenses"] = spec["other_lenses"]
        out[skill] = doc
    return out


def _render(doc: dict) -> str:
    return _HEADER + yaml.safe_dump(doc, sort_keys=False, width=100, allow_unicode=True)


def _committed(skill: str):
    p = SKILLS_DIR / skill / "question_hierarchy.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else None


def check() -> list:
    """Parsed-structure drift (header/formatting-agnostic): the load-bearing keys must match contracts."""
    drift = []
    for skill, doc in load_source().items():
        got = _committed(skill)
        if got is None:
            drift.append(f"{skill}: no committed question_hierarchy.yaml")
            continue
        if (got.get("sub_groups") != doc["sub_groups"]
                or (got.get("other_lenses") or None) != (doc.get("other_lenses") or None)):
            drift.append(f"{skill}: question_hierarchy.yaml diverges from contracts source")
    return drift


def write() -> int:
    n = 0
    for skill, doc in load_source().items():
        p = SKILLS_DIR / skill / "question_hierarchy.yaml"
        if p.parent.is_dir():
            p.write_text(_render(doc))
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="rewrite each question_hierarchy.yaml from source")
    args = ap.parse_args()
    if not contracts_available():
        print(f"[skip] no target-contracts axes at {AXES} (set TARGET_CONTRACTS_ROOT)")
        return 0
    if args.write:
        print(f"wrote {write()} question_hierarchy.yaml files from contracts")
        return 0
    drift = check()
    if drift:
        print("question_hierarchy drift vs contracts:")
        for d in drift:
            print(f"  - {d}")
        print("run: python skills/tools/sync_question_hierarchies.py --write")
        return 1
    print(f"OK — {len(load_source())} question_hierarchy.yaml mirrors match the contracts source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
