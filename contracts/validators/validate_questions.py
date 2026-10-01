#!/usr/bin/env python3
"""
validate_questions.py — skill question-registry (questions.yaml) validator.

Two layers (mirrors validate_cards.py):
  (1) Structural — each skills/<skill>/questions.yaml validates against schemas/questions.schema.json.
  (2) Cross-reference — the invariant JSON Schema cannot express: every question's `measurement_types`
      entry must RESOLVE to a real card, i.e. be the measurement_type of at least one card contract in
      cards/. A dangling measurement_type is a card that will never join the question (a silent
      empty-signal row in the evidence_graph dashboard).

CROSS-REPO (historically): questions.yaml lives in the (now in-tree, SK#2063) claude-oncology-skills
repo (like the figure-emission check in validate_cards.py). We locate it via
$CLAUDE_ONCOLOGY_SKILLS_ROOT (default: this repo's own root) and GRACEFULLY SKIP layer-1/2 when that
repo is absent (isolated CI) — the schema itself is always checked for well-formedness.

Usage:
  python validators/validate_questions.py                 # all skills' questions.yaml (+ resolution)
  python validators/validate_questions.py path/to/questions.yaml ...
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parent.parent
CARDS_DIR = REPO / "cards"
# N3-1 #2144 / #2423: since the SK#2063 monorepo consolidation, questions.yaml lives IN-TREE in this
# same repo (claude-oncology-skills), so the default is the in-tree repo root, not a $HOME literal.
SKILLS_REPO = Path(os.environ.get("CLAUDE_ONCOLOGY_SKILLS_ROOT") or REPO.parent)


def _load_schema() -> dict:
    # N3-1 #2144: load via the packaged loader instead of a local SCHEMA_PATH file read.
    from oncology_target_contracts.loader import load_schema

    return load_schema("questions")


def _card_measurement_types() -> set:
    mts = set()
    for f in CARDS_DIR.glob("*.card.yaml"):
        try:
            y = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError:
            continue
        if y.get("measurement_type"):
            mts.add(y["measurement_type"])
    return mts


def validate_questions_file(path: Path, schema: dict, valid_mts: set) -> list:
    """Return a list of error strings ([] == ok) for one questions.yaml."""
    errs: list = []
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        return [f"YAML parse error: {e}"]
    for e in Draft202012Validator(schema).iter_errors(doc):
        loc = ".".join(str(p) for p in e.absolute_path) or "<root>"
        errs.append(f"STRUCTURAL [{loc}]: {e.message}")
    # cross-ref: every declared measurement_type resolves to a real card (skip if cards absent)
    if valid_mts:
        for q in doc.get("questions") or []:
            if not isinstance(q, dict):
                continue
            for mt in q.get("measurement_types") or []:
                if mt not in valid_mts:
                    errs.append(f"UNRESOLVED [{q.get('id')}]: measurement_type '{mt}' matches no card contract")
    return errs


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate skill questions.yaml registries.")
    ap.add_argument("paths", nargs="*", help="explicit questions.yaml files (default: all skills)")
    args = ap.parse_args(argv)

    schema = _load_schema()
    Draft202012Validator.check_schema(schema)

    if args.paths:
        targets = [Path(p) for p in args.paths]
    else:
        pattern = str(SKILLS_REPO / "skills" / "*" / "questions.yaml")
        targets = sorted(Path(p) for p in glob.glob(pattern))
        if not targets:
            print(
                f"⚠ no questions.yaml found under {SKILLS_REPO} — skipping (sibling repo absent). "
                f"Schema well-formedness OK.",
                file=sys.stderr,
            )
            return 0

    valid_mts = _card_measurement_types()
    if not valid_mts:
        print("⚠ no card measurement_types found — skipping the resolution cross-check.", file=sys.stderr)

    ok = True
    for p in targets:
        if not p.exists():
            print(f"✗ {p}: not found", file=sys.stderr)
            ok = False
            continue
        errs = validate_questions_file(p, schema, valid_mts)
        print(f"{'✓' if not errs else '✗'} {p.parent.name}/questions.yaml")
        for e in errs:
            print(f"    {e}")
        ok = ok and not errs
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
