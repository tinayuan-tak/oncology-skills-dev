#!/usr/bin/env python3
"""Publish per-unit FIELD-READ HEALTH as a committed sidecar.

`field_disposition.census` measures one direction: of the fields a card DECLARES, which are read by
something. Its domain is built from `declared_fields`, so a read of an UNDECLARED field is dropped
before it can be counted — the aperture is structurally blind to it. This sidecar measures the other
direction, reads MINUS declarations, and attributes each read to the unit whose code makes it. That
subtraction is what found the one field in the tree that handed the model `None` on every run
(`clinical-precedent.n_agents_engaging_target`, fixed in #1405): nothing emitted it, nothing declared
it, and one skill read it anyway.

Consumed by the framework-health probe (contracts/validators/framework_health/{probe,rollup}.py) as a
TRENDING dimension, never a gate. It starts partial by design and a populated queue is a REVIEW QUEUE,
so `--check` gates FRESHNESS only and `main()` returns 0 however long the queue is.

★ CARD ROSTER — LIVE, DE-PINNED (#2090). The subtraction needs each card's `outputs.summary_fields`,
which lives in `contracts/`. Contracts is now part of THIS repo (SK#2063 consolidation), so `--check`
rebuilds against the LIVE in-tree `contracts/cards/` and a single CI job sees both trees — a
card+skill change is one atomic PR that reds together. This retires the former committed-roster pin
(the build once fed `rosters.declared_fields` back into itself so a contracts-only edit could not red
an unrelated skills PR — the pre-consolidation "no single CI job sees both repos" era) and its
live-vs-pinned drift advisory. `rosters.declared_fields` is still PUBLISHED — it is the roster the
census was built against, which the dashboard reconciles — but it is a live snapshot, no longer a pin
fed back into `--check`; a contracts card edit now reds `--check` until the sidecar is regenerated in
the same PR.

★ "NO READS DETECTED" IS NOT "CLEAN", and the distinction is load-bearing. `code_readers` recognises
five call shapes; `target-profile` scrapes to zero reads while plainly naming `n_approved` in a spec
dict, and `report_render/ir.py` reads its field names out of a loop variable, invisible to all five.
Collapsing an unmeasured unit into `clean` would report instrument silence as health, so it is a
third disposition. Mirrors `field_disposition`'s SAFETY CONTRACT: an empty set means "no read was
DETECTED", never "this unit reads nothing".

★ CLASSIFICATION ONLY NARROWS, and only where the roster itself justifies it. `meta_key` fires on a
leading underscore because 0 of the 1807 declared fields in the pinned roster start with one, so an
underscore read cannot be a field read. Everything else is `emission_undetermined` — splitting it
into the handoff's `read_of_None` vs `emitted_but_undeclared` needs to know whether a producer
actually emits the field, and the only sound evidence for that is observed packages, which this
producer cannot see (the repo's own fixtures include hand-written synthetic ones, so crediting a
field as emitted because a fixture names it would make the metric measure our own paperwork). The
contracts side owns that half; it has the data-products root. Deliberately NO suppression list — and
that is what shrank the queue from 7 rows to 2. Five of the seven were SCRAPER ARTIFACTS, and because
none of them was waived they stayed legible long enough to be diagnosed and fixed in the scraper
itself: two were the summary CONTAINER HOP and three came from the module-level scope unioning every
function-local card alias in a file (see `_card_aliases` / `_module_top_level`). A waiver would have
recorded them as accepted noise and outlived the limitation that motivated it; leaving them visible
turned the queue into the instrument that found its own instrument bugs. What remains is two rows and
both are real: `competitor-landscape.n_approved` (a genuine gap for the contracts side to resolve) and
one `_schema` meta_key.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from _skills_common import field_disposition as fd

SKILLS_DIR = Path(__file__).resolve().parents[1]
_OUT = SKILLS_DIR / "_skills_common" / "field_read_health.json"
SCHEMA_VERSION = "1.0.0"

#: Top-level dirs under `skills/` that are neither a skill nor the shared library. Caches and the
#: cross-skill test/tooling dirs; they are still SCANNED so the reconciliation stays total.
_NON_UNIT_DIRS = frozenset({"tests", "tools", "__pycache__"})

SHARED_LIBRARY = "_skills_common"

CLASSIFICATION_RULE = (
    "meta_key: field name starts with '_' (no declared field in the pinned roster does, so such a "
    "read cannot be a field read). emission_undetermined: everything else — read_of_None vs "
    "emitted_but_undeclared needs observed-package evidence this producer cannot see."
)

DISPOSITION_RULE = (
    "clean: reads were detected and every one names a declared field. undeclared_reads: at least one "
    "read names a field the card does not declare. no_reads_detected: the scraper found no read at "
    "all — instrument silence, NOT a clean bill of health."
)


def _unit_kind(d: Path) -> str:
    """`skill` / `shared_library` / `other` for a top-level dir under `skills/`."""
    if d.name == SHARED_LIBRARY:
        return "shared_library"
    if d.name.startswith(".") or d.name in _NON_UNIT_DIRS:
        return "other"
    # Same criterion as target-contracts' probe.list_skill_names, so the two agree on what a skill is.
    return "skill" if (d / "SKILL.md").exists() else "other"


def _undeclared(exact: dict, declared: dict) -> dict:
    """`{(card, field): {reader_kind, ...}}` for reads naming a field the card does not declare."""
    out: dict[tuple[str, str], set] = {}
    for kind, pairs in exact.items():
        for card, field in pairs:
            if field not in (declared.get(card) or ()):
                out.setdefault((card, field), set()).add(kind)
    return out


def _classify(field: str) -> str:
    return "meta_key" if field.startswith("_") else "emission_undetermined"


def build(declared: dict | None = None) -> dict:
    """The census. `declared` pins the card roster; omit it to read the live contracts sibling.

    Every unit is scraped SEPARATELY, which is what supplies the attribution `code_readers` discards
    — it returns `{kind: {(card, field)}}` with the reading file projected away. Measured on trunk the
    union of the per-unit scrapes reproduces the whole-tree scrape exactly (508 == 508), because no
    recognised shape currently joins across two top-level dirs. That is a property of today's tree,
    not a guarantee: shape (5) is a two-file join and could straddle a boundary tomorrow. So the
    whole-tree scrape is run as well and the difference is PUBLISHED, turning a silent loss of
    attribution into a visible one.
    """
    declared = fd.declared_fields() if declared is None else dict(declared)
    skills_root = SKILLS_DIR

    whole_exact, _ = fd.code_readers(skills_root, declared=declared)
    whole_pairs = {(k, p) for k, ps in whole_exact.items() for p in ps}

    units: dict[str, dict] = {}
    union: set = set()
    for d in sorted(x for x in skills_root.iterdir() if x.is_dir()):
        exact, _ = fd.code_readers(d, declared=declared)
        union |= {(k, p) for k, ps in exact.items() for p in ps}
        kind = _unit_kind(d)
        n_reads = sum(len(ps) for ps in exact.values())
        if kind == "other" and not n_reads:
            continue  # a cache or the cross-skill test dir, reading nothing — not a reportable unit
        und = _undeclared(exact, declared)
        units[d.name] = {
            "kind": kind,
            "disposition": ("no_reads_detected" if not n_reads else "undeclared_reads" if und else "clean"),
            "n_reads": n_reads,
            "reads_by_kind": {k: len(ps) for k, ps in sorted(exact.items()) if ps},
            "undeclared": [
                {
                    "card": card,
                    "field": field,
                    "reader_kinds": sorted(kinds),
                    "classification": _classify(field),
                }
                for (card, field), kinds in sorted(und.items())
            ],
        }

    queue = [{"unit": name, **row} for name, u in sorted(units.items()) for row in u["undeclared"]]
    dispositions = Counter(u["disposition"] for u in units.values())
    classes = Counter(row["classification"] for row in queue)

    return {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "n_units": len(units),
            "n_clean": dispositions["clean"],
            "n_units_with_undeclared_reads": dispositions["undeclared_reads"],
            "n_no_reads_detected": dispositions["no_reads_detected"],
            "n_reads_detected": len(whole_pairs),
            "n_undeclared_pairs": len(queue),
            "n_meta_key": classes["meta_key"],
            "n_emission_undetermined": classes["emission_undetermined"],
            "attribution_reconciled": union == whole_pairs,
            "n_roster_cards": len(declared),
            "n_roster_fields": sum(len(v) for v in declared.values()),
        },
        "units": units,
        "undeclared_queue": queue,
        "attribution": {
            "reconciled": union == whole_pairs,
            "whole_tree_pairs": len(whole_pairs),
            "per_unit_union_pairs": len(union),
            # DO NOT reconcile this against whole_tree_pairs — it is deliberately larger. The union
            # DEDUPES a (kind, card, field) read by two units; this SUMS the per-unit credits, so two
            # skills reading the same field count twice. Both are correct answers to different
            # questions ("how many distinct reads exist" vs "how much reading does each unit do"), and
            # the reconciliation invariant is union == whole_tree_pairs, never this number.
            "per_unit_read_credits": sum(u["n_reads"] for u in units.values()),
            # Reads the whole-tree scrape found that no single unit's scrape reproduces — a shape
            # joining across two top-level dirs. Non-empty means the per-unit attribution is INCOMPLETE.
            "unattributed": sorted([k, c, f] for k, (c, f) in (whole_pairs - union)),
        },
        "rosters": {
            # The live in-tree contracts roster this census was built against, PUBLISHED so the
            # framework-health dashboard can reconcile against it. De-pinned #2090: `--check` rebuilds
            # against the live roster (contracts is in-tree), so this is a snapshot, not a fed-back pin.
            "declared_fields": {c: sorted(fs) for c, fs in sorted(declared.items())},
            "reader_kinds": sorted(fd.READER_KINDS),
            "classification_rule": CLASSIFICATION_RULE,
            "disposition_rule": DISPOSITION_RULE,
        },
        "note": (
            "Reads MINUS declarations, per unit, for the target-contracts framework-health dashboard. "
            "TRENDING, never a gate: a populated queue is a review queue and this tool returns 0 "
            "however long it is. The queue is NOT split into read_of_None vs emitted_but_undeclared "
            "here — that needs observed-package evidence this producer cannot see, so the contracts "
            "side resolves emission_undetermined against the data-products root. no_reads_detected "
            "means the scraper's five shapes matched nothing, NOT that the unit is clean."
        ),
    }


def _canonical(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check",
        action="store_true",
        help="compare the committed census against a LIVE rebuild (in-tree contracts/cards); nonzero if stale",
    )
    args = ap.parse_args(argv)

    if args.check:
        if not _OUT.exists():
            print(f"STALE {_OUT.name}: not committed", file=sys.stderr)
            return 1
        try:
            committed = json.loads(_OUT.read_text())
        except json.JSONDecodeError as exc:
            print(f"STALE {_OUT.name}: not valid JSON ({exc})", file=sys.stderr)
            return 1
        # De-pinned #2090: rebuild against the LIVE in-tree contracts roster (contracts is in this repo
        # since SK#2063), so a contracts card edit reds this until the sidecar is regenerated in the
        # same PR — the atomic-PR behaviour the consolidation enables.
        if _canonical(committed) != _canonical(build()):
            print(f"STALE {_OUT.name}: differs from a live rebuild — regenerate it", file=sys.stderr)
            return 1
        print(f"OK {_OUT.name} (fresh against the live in-tree contracts roster)")
        return 0

    report = build()
    _OUT.write_text(_canonical(report) + "\n")
    s = report["summary"]
    print(
        f"wrote {_OUT.relative_to(SKILLS_DIR.parent)}: {s['n_units']} units "
        f"({s['n_clean']} clean, {s['n_units_with_undeclared_reads']} with undeclared reads, "
        f"{s['n_no_reads_detected']} no reads detected), {s['n_reads_detected']} reads, "
        f"{s['n_undeclared_pairs']} undeclared pairs, attribution_reconciled={s['attribution_reconciled']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
