#!/usr/bin/env python3
"""descriptor_coverage_sidecar.py — publish the descriptor-coverage census as a committed feed.

`field_descriptor.coverage_report()` has computed this census for weeks and NOTHING reads it:
the only non-test reference in the repo is a comment (`risk_projection.py`). That is the
framework-health "invisibility" failure in miniature — a measured signal with no surface — and
this module is the surface: it writes ONE committed `descriptor_coverage.json` that the
target-contracts framework-health probe reads as a health DIMENSION (trending, never a gate).

WHY A SIDECAR AND NOT A CONTRACTS-SIDE RE-DERIVATION
----------------------------------------------------
`field_descriptor` is deliberately DERIVED: it re-expresses `evidence_salience.SALIENCE_SPECS`
(structure) joined with `display_gloss` (semantics) and holds no independent content, "a third
hand-authored copy is exactly what we are avoiding". target-contracts' `probe.py` is pure static
analysis and never imports sibling code, so it cannot call `coverage_report()`. Re-deriving the
join over there in AST would create precisely that third copy, in a second repo, where NO CI job
sees both trees and so nothing could ever compare them.

So the join is shipped as DATA. This is not a new pattern: `probe.subskill_run_health()` already
reads the committed sidecar `_skills_common/subskill_health.json` produced by
`framework_health_smoke.py`, and `probe` does `json.loads` on sibling data at a dozen sites versus
exactly one `ast.parse`. Reading a committed artifact IS probe's dominant idiom.

Kept SEPARATE from `framework_health_smoke.py` on purpose: that harness runs every wired subskill
in a subprocess under a 120s cap, so its `--check` can never be a per-PR required check. This
census is pure in-process constant folding (milliseconds, no I/O, no subprocess), so its `--check`
CAN gate every PR — which is what makes the freshness guarantee enforced rather than aspirational.

NO `generated_at`, AND THEREFORE NO STABLE PROJECTION
-----------------------------------------------------
`framework_health_smoke` needs a `_stable()` projection because it measures wall-clock seconds.
Nothing here is volatile — the census is a pure function of two module constants — so `--check`
compares the WHOLE document. Narrowing a drift basis is only ever justified by real volatility;
a projection that drops nothing is just a place for future drift to hide. Do not add a timestamp
to this artifact: it would be the only volatile field and would force a projection that weakens
every other field's guard.

Usage:
  python -m _skills_common.descriptor_coverage_sidecar          # write descriptor_coverage.json
  python -m _skills_common.descriptor_coverage_sidecar --check  # fail if the committed file is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from _skills_common import display_gloss, field_descriptor

SKILLS_DIR = Path(__file__).resolve().parents[1]  # .../skills
_OUT = SKILLS_DIR / "_skills_common" / "descriptor_coverage.json"

SCHEMA_VERSION = "1.0.0"


def build() -> dict:
    """The census + the rosters a cross-repo consumer needs to classify fields WITHOUT
    re-implementing the descriptor join."""
    catalog = field_descriptor.descriptor_catalog()
    base = field_descriptor.coverage_report()

    # (measurement_type, field) CELLS vs DISTINCT field names. These differ (14 fields are
    # declared by 2-6 measurement_types), so `coverage_report`'s `n_descriptor_fields` is a CELL
    # count despite its name. Both are published under names that cannot be confused, because a
    # consumer that reconciles the wrong one over-counts the roster by 27.
    cells = [(mt, f, d) for mt, fields in catalog.items() for f, d in fields.items()]
    per_field_types = Counter(f for _, f, _ in cells)
    distinct_fields = sorted(per_field_types)
    multi_type_fields = sorted(f for f, n in per_field_types.items() if n > 1)

    # Role of each distinct field. First spec wins on a cross-type name collision — the same
    # precedence `field_descriptor._flat_index()` uses, so `classify_field` and this roster agree.
    role_by_field: dict[str, str] = {}
    for _, field, d in cells:
        role_by_field.setdefault(field, d["role"])

    # GLOSS COVERAGE IN BOTH DIRECTIONS. `coverage_report` only looks one way (a numeric field
    # with no METRIC_GLOSS entry) and that direction is currently COMPLETE, so on its own it is a
    # ratchet at zero, not a trend. The reverse direction is a populated queue nobody measured:
    # fields with a hand-curated (label, units) that NO spec declares, i.e. someone authored
    # display semantics for a field the salience layer cannot see. Those are the static half of
    # "emitted but undeclared" — discoverable with zero runtime data.
    numeric_fields = sorted(f for f in distinct_fields if role_by_field[f] in field_descriptor._NUMERIC_ROLES)
    numeric_with_gloss = [f for f in numeric_fields if f in display_gloss.METRIC_GLOSS]
    gloss_without_descriptor = sorted(set(display_gloss.METRIC_GLOSS) - set(distinct_fields))

    return {
        "schema_version": SCHEMA_VERSION,
        "producer": "descriptor_coverage_sidecar",
        "note": (
            "Descriptor-coverage census over evidence_salience.SALIENCE_SPECS joined with "
            "display_gloss, published for the target-contracts framework-health dashboard. A "
            "TRENDING signal, never a gate. Deterministic pure function of two module constants "
            "(no I/O, no clock) => --check compares the whole document, and this artifact must "
            "never acquire a timestamp. READING NOTES, so a consumer cannot misread it: (1) "
            "`n_descriptor_cells` counts (measurement_type, field) PAIRS; `n_distinct_fields` "
            "counts NAMES; they differ because some fields are declared by several types. (2) "
            "`source_class_counts` is CONSTANT BY CONSTRUCTION -- field_descriptor's "
            "_SOURCE_CLASS_BY_MEASUREMENT_TYPE is empty, so every field classifies as "
            "`instrument` and this tally cannot currently say anything else; do not display it "
            "as a measurement. (3) `n_numeric_fields_without_gloss == 0` is the CURRENT state, "
            "so that direction is a regression ratchet rather than a trend; the live queue is "
            "`gloss_without_descriptor`. (4) An `unclassified` count of ZERO over emitted fields "
            "would mean the classifier is FABRICATING roles, not that coverage is complete "
            "(field_descriptor says so twice) -- so a consumer must not render zero as success. "
            "The emitted-field queue itself is NOT computed here: it needs observed summaries, "
            "which this producer cannot see. The `rosters` block below is what makes it "
            "computable downstream by pure set membership, with no second copy of the join."
        ),
        "summary": {
            "n_measurement_types": len(catalog),
            "n_descriptor_cells": len(cells),
            "n_distinct_fields": len(distinct_fields),
            "n_multi_type_fields": len(multi_type_fields),
            "n_envelope_fields": len(field_descriptor.ENVELOPE_FIELDS),
            "n_atlas_live": base["n_atlas_live"],
            "n_numeric_fields": len(numeric_fields),
            "n_numeric_fields_with_gloss": len(numeric_with_gloss),
            "n_numeric_fields_without_gloss": len(base["numeric_fields_without_gloss"]),
            "n_metric_gloss_entries": len(display_gloss.METRIC_GLOSS),
            "n_gloss_without_descriptor": len(gloss_without_descriptor),
        },
        "role_counts": base["role_counts"],
        "source_class_counts": base["source_class_counts"],
        "numeric_fields_without_gloss": base["numeric_fields_without_gloss"],
        "gloss_without_descriptor": gloss_without_descriptor,
        "multi_type_fields": multi_type_fields,
        "rosters": {
            "declared_fields": distinct_fields,
            "envelope_fields": sorted(field_descriptor.ENVELOPE_FIELDS),
            "roles": sorted(field_descriptor.ROLES),
            "numeric_roles": sorted(field_descriptor._NUMERIC_ROLES),
            "role_by_field": role_by_field,
            "classification_rule": (
                "An emitted field's role is `role_by_field[field]` when present; else `envelope` "
                "when the name is in `envelope_fields` or starts with '_'; else `unclassified` "
                "(the work queue). This mirrors field_descriptor.classify_field exactly, so a "
                "consumer needs set membership only and never re-implements the join."
            ),
        },
        "fields_by_measurement_type": {mt: sorted(fields) for mt, fields in catalog.items()},
    }


def _canonical(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Publish the descriptor-coverage census sidecar.")
    ap.add_argument(
        "--check",
        action="store_true",
        help="fail (exit 1) if the committed descriptor_coverage.json differs from a fresh build",
    )
    args = ap.parse_args(argv)

    report = build()
    fresh = _canonical(report)

    if args.check:
        if not _OUT.exists():
            print(f"  MISSING {_OUT.name} — run without --check to generate.", file=sys.stderr)
            return 1
        try:
            committed = _canonical(json.loads(_OUT.read_text()))
        except json.JSONDecodeError as exc:
            print(f"  UNPARSEABLE {_OUT.name}: {exc}", file=sys.stderr)
            return 1
        if committed != fresh:
            print(
                f"  STALE {_OUT.name} — committed census differs from computed; regenerate with "
                f"`python -m _skills_common.descriptor_coverage_sidecar`.",
                file=sys.stderr,
            )
            return 1
        print(f"  OK {_OUT.name} (fresh)")
        return 0

    _OUT.write_text(fresh + "\n")
    s = report["summary"]
    print(
        f"  wrote {_OUT.name}: {s['n_measurement_types']} measurement_types, "
        f"{s['n_descriptor_cells']} cells / {s['n_distinct_fields']} distinct fields, "
        f"{s['n_numeric_fields_with_gloss']}/{s['n_numeric_fields']} numeric fields glossed"
    )
    if report["gloss_without_descriptor"]:
        # The live queue — say it out loud on every regeneration. These have curated display
        # semantics but no spec, so classify_field() calls each one `unclassified`.
        print(
            f"    queue: {len(report['gloss_without_descriptor'])} METRIC_GLOSS "
            f"entr{'y' if len(report['gloss_without_descriptor']) == 1 else 'ies'} with no "
            f"descriptor: {', '.join(report['gloss_without_descriptor'])}"
        )
    # A populated queue is the EXPECTED state of a coverage dimension that starts partial by
    # design, so it must not fail the producer. This harness fails only on a broken census.
    return 0


if __name__ == "__main__":
    sys.exit(main())
