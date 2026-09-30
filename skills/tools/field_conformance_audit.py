#!/usr/bin/env python3
"""field_conformance_audit.py — step-0a faithfulness check for the card-surfacing pipeline.

WHY
---
The salience / verdict layer reads a SPECIFIC set of summary fields per
measurement_type (declared in `_skills_common.evidence_salience.SALIENCE_SPECS`),
and the read helpers pin each field's expected TYPE:

    _read_num_field  → numeric (int/float, not bool)      effect/significance/omnibus/n/extra_scalars
    _read_str_field  → string  (a resolver *_class, etc.) categorical[], label_field
    strata_array     → list

But the emitted card summaries are validated against OPEN schemas
(`additionalProperties: true`, nothing `required`) — so a field that is missing,
mistyped, or carries an unmeasured sentinel where a number is expected passes
validation SILENTLY. Any downstream ranking / correlation would then be computed
on unfaithful data. This tool answers, per (measurement_type, field):

  can the framework's OWN reader get a correctly-typed value out of what was emitted?

It reuses the framework's read helpers as the oracle (no reinvented type rules), so
a field it passes is a field the verdict layer can actually read.

SCOPE: this is the STRUCTURE/TYPE half of step 0 — valid on any package cache,
including a stale one, because it only inspects fields that ARE present. The
COVERAGE half (present-vs-measured RATES across a fresh corpus) is
`_skills_common.field_disposition.run_coverage` and needs a clean re-emit.

READ-ONLY. Reports; never writes packages or specs.

USAGE
    python3 field_conformance_audit.py [--packages DIR] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# make `_skills_common` importable whether run from the repo or a worktree
_SKILLS_ROOT = Path(__file__).resolve().parents[1]  # .../skills

from _skills_common import evidence_salience as es  # noqa: E402
from _skills_common import field_disposition as fd  # noqa: E402

# repo-root-relative — this file lives at <repo>/skills/tools/, so parents[1] is <repo>/skills
# and its parent is the repo root (SK#2137: never hardcode $HOME/rnd-... — the archived pre-merge
# clones still exist there and would silently resolve to a stale tree).
_REPO_ROOT = _SKILLS_ROOT.parent
_DEFAULT_PKGS = _REPO_ROOT / "eval" / "known-target-packages"


# ── ANSI ──
def _ok(x):
    return f"\033[32m{x}\033[0m"


def _bad(x):
    return f"\033[31m{x}\033[0m"


def _warn(x):
    return f"\033[33m{x}\033[0m"


def _dim(x):
    return f"\033[2m{x}\033[0m"


def _hdr(x):
    return f"\033[1m\033[36m{x}\033[0m"


def spec_fields(spec: dict):
    """Fields the salience layer reads, grouped by the type its reader expects.
    Returns {"numeric": [...], "string": [...], "array": [...]}."""
    numeric, string, array = [], [], []
    for k in ("effect_field", "significance_field", "omnibus_field", "n_field"):
        if spec.get(k):
            numeric.append(spec[k])
    numeric += list(spec.get("extra_scalars") or [])
    string += list(spec.get("categorical") or [])
    if spec.get("label_field"):
        string.append(spec["label_field"])
    if spec.get("strata_array"):
        array.append(spec["strata_array"])
    # NOTE: 0a scopes to the top-level salience-read slots above. The interpretation-ruler projection
    # fields (value/position/anchor) are verdict-INERT and governed separately, and no observed type
    # defect lives there — so they are intentionally out of scope for this conformance audit.
    dedupe = lambda xs: list(dict.fromkeys(xs))
    return {"numeric": dedupe(numeric), "string": dedupe(string), "array": dedupe(array)}


# conformance verdicts for one (field, summary) pair.
#   WRONGTYPE  = present, non-null, but the WRONG type for how the reader reads it → the real 0a defect
#                (value is there but silently unreadable/misread — the open-schema gap).
#   FALLBACK   = reader satisfied from the capsule, but NOT in the summary structure (mild structural note).
#   UNMEASURED = present but an unmeasured sentinel where a number is read (informational, ~data_unavailable).
#   NA         = absent OR explicit null → NOT a 0a structural defect. Absence is a COVERAGE question (0b,
#                needs a fresh re-emit) and is expected here anyway: a measurement_type's fields are
#                distributed across sibling cards + strata arrays + the capsule, so a given card legitimately
#                lacks most of them. 0a only judges fields that ARE present.
OK, FALLBACK, WRONGTYPE, UNMEASURED, NA = "ok", "ok_via_capsule", "wrong_type", "unmeasured", "n/a"


def classify_numeric(field, summary, cap):
    present = isinstance(summary, dict) and field in summary
    val = summary.get(field) if present else None
    if present and es._inum(val) is not None:
        return OK
    if es._read_num_field(field, summary, cap) is not None:
        return FALLBACK  # readable from the capsule, but not stored in the summary
    if present and val is not None:
        return UNMEASURED if not fd.is_measured(val) else WRONGTYPE
    return NA  # absent or explicit null → coverage/N-A, not a structural type defect


def classify_string(field, summary, cap):
    present = isinstance(summary, dict) and field in summary
    val = summary.get(field) if present else None
    if isinstance(val, str):
        return OK
    if es._read_str_field(field, summary, cap) is not None:
        return FALLBACK
    if present and val is not None:
        return WRONGTYPE  # present, non-null, not a string (bool/number/list/dict) → reader gets nothing
    return NA


def classify_array(field, summary):
    present = isinstance(summary, dict) and field in summary
    val = summary.get(field) if present else None
    if isinstance(val, list):
        return OK
    if present and val is not None:
        return WRONGTYPE
    return NA


def audit(pkg_dir: Path):
    pkgs = sorted(pkg_dir.glob("*.json"))
    # per (measurement_type, field, kind) → Counter of verdicts, plus example offenders
    agg = defaultdict(Counter)
    examples = defaultdict(list)
    n_cards_checked = 0
    specs_seen = set()
    for p in pkgs:
        try:
            d = json.load(open(p))
        except Exception:
            continue
        for c in d.get("cards") or []:
            summary = c.get("summary")
            if not summary:
                continue  # stub (read_error / data_unavailable) → 0b's concern, not structure
            mt = c.get("measurement_type")
            spec = es.SALIENCE_SPECS.get(mt) if mt else None
            if not spec:
                continue  # display-only / no verdict-read fields → out of 0a scope
            specs_seen.add(mt)
            n_cards_checked += 1
            cap = c.get("evidence_capsule") or c.get("capsule") or {}
            fields = spec_fields(spec)
            for f in fields["numeric"]:
                v = classify_numeric(f, summary, cap)
                agg[(mt, f, "num")][v] += 1
                if v == WRONGTYPE:
                    examples[(mt, f, "num")].append(f"{p.stem}={summary.get(f)!r}")
            for f in fields["string"]:
                v = classify_string(f, summary, cap)
                agg[(mt, f, "str")][v] += 1
                if v == WRONGTYPE:
                    examples[(mt, f, "str")].append(f"{p.stem}={summary.get(f)!r}")
            for f in fields["array"]:
                v = classify_array(f, summary)
                agg[(mt, f, "arr")][v] += 1
                if v == WRONGTYPE:
                    examples[(mt, f, "arr")].append(f"{p.stem}={type(summary.get(f)).__name__}")
    return pkgs, agg, examples, n_cards_checked, specs_seen


def report(pkg_dir: Path, as_json: bool):
    pkgs, agg, examples, n_checked, specs_seen = audit(pkg_dir)
    # TRUE 0a defect = a field PRESENT (non-null) in a type the reader cannot consume. Absence is a coverage
    # question (0b); null is N/A. Both are excluded here so the signal is not inflated.
    defects = {k: cnt for k, cnt in agg.items() if cnt.get(WRONGTYPE)}
    fallbacks = {k: cnt for k, cnt in agg.items() if cnt.get(FALLBACK) and not cnt.get(WRONGTYPE)}
    if as_json:
        out = {
            "packages": len(pkgs),
            "cards_checked": n_checked,
            "measurement_types": sorted(specs_seen),
            "wrong_type_defects": [
                {
                    "measurement_type": mt,
                    "field": f,
                    "kind": k,
                    "counts": dict(cnt),
                    "examples": examples.get((mt, f, k), [])[:3],
                }
                for (mt, f, k), cnt in sorted(defects.items())
            ],
            "capsule_only_fields": [
                {"measurement_type": mt, "field": f, "kind": k, "counts": dict(cnt)}
                for (mt, f, k), cnt in sorted(fallbacks.items())
            ],
        }
        print(json.dumps(out, indent=2))
        return 1 if defects else 0

    print(
        _hdr(f"\n═══ FIELD-CONFORMANCE AUDIT (step 0a) — {len(pkgs)} packages, {n_checked} verdict-card instances ═══")
    )
    print(
        _dim(
            f"  {len(specs_seen)} measurement_types with a salience spec · checks fields the verdict layer READS, "
            "using the framework's own read helpers"
        )
    )
    print(
        _dim("  0a = TYPE/STRUCTURE of fields that ARE present. absence/null → coverage (0b, needs a fresh re-emit).")
    )

    if not defects:
        print(_ok("\n  ✓ no wrong-type defects: every present salience-read field is a type the reader can consume."))
    else:
        print(
            _bad(
                f"\n  {len(defects)} (measurement_type, field) WRONG-TYPE defects "
                "— present & non-null but the reader gets NOTHING (the open-schema gap):\n"
            )
        )
        print(f"    {'measurement_type':30s} {'field':34s} {'kind':4s} {'counts':22s} example")
        for (mt, f, k), cnt in sorted(defects.items(), key=lambda kv: -kv[1][WRONGTYPE]):
            counts = " ".join(f"{v}={n}" for v, n in cnt.most_common())
            ex = (examples.get((mt, f, k)) or [""])[0]
            print(f"    {mt:30s} {f:34s} {_bad(k):4s} {counts:22s} {_dim(ex)}")

    if fallbacks:
        print(
            _warn(
                f"\n  {len(fallbacks)} fields readable ONLY via the capsule, not the summary structure "
                "(milder note — reader succeeds, but the summary lacks the field):"
            )
        )
        for mt, f, k in sorted(fallbacks)[:12]:
            print(_dim(f"    {mt} · {f} ({k})"))
        if len(fallbacks) > 12:
            print(_dim(f"    … +{len(fallbacks) - 12} more"))
    return 1 if defects else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Step-0a field-conformance audit for verdict-read card fields.")
    ap.add_argument("--packages", default=str(_DEFAULT_PKGS), help="dir of composed package json files")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args()
    sys.exit(report(Path(a.packages), a.json))
