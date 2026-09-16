#!/usr/bin/env python3
"""Regenerate ``emission_invariants_baseline.json`` from a package corpus.

    python skills/tests/regenerate_emission_invariants_baseline.py ~/dev/target-archetype-corpus-20260915

A baseline you cannot regenerate is a liability: the next person to legitimately shrink the red list has
to hand-edit an artifact they did not produce, and hand-edits are how a ratchet quietly stops meaning
anything. Same reason ``regenerate_resolver_golden.py`` exists next to its snapshot.

★ The baseline deliberately banks a NAMED RED LIST, not a total. A remembered total drifts for reasons
that have nothing to do with the code under test — a peer's merge-ref, a sibling repo parametrizing at
import, a corpus regenerated at a different SHA — and then every author after you is reconciling someone
else's arithmetic. ``(invariant, card_id, field)`` is stable under all of those, so the ratchet can be
one-sided on it: a NEW triple is a regression, a vanished triple is progress and only ever prints a note.

⚠️ Per-invariant ROW and PACKAGE counts are recorded for human diffing and are deliberately NOT asserted
by the ratchet. A count ceiling would red on a corpus regenerated over a different package set, which is
a property of the substrate rather than of the emitters — and a two-sided count ratchet with slack reds
trunk immediately after the PR that banks it lands.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import emission_invariants as ei  # noqa: E402
from _skills_common import field_disposition as fd  # noqa: E402

BASELINE = Path(__file__).resolve().parent / "emission_invariants_baseline.json"


def vintage(corpus: Path) -> dict:
    """Corpus vintage via ``field_disposition.corpus_vintage`` — IMPORTED, never re-parsed.

    ★ This function is two lines because the first attempt at it was twenty, and wrong in a way that
    looked right. Hand-rolling the read guessed at ``provenance.code_sha``, a key no package has, and
    returned ``{"unrecorded": 504}`` — a well-formed dict answering *unknown* for every input, which is
    verbatim the failure mode ``corpus_vintage``'s own docstring exists to record (its predecessor
    path-regexed the directory name and returned 298 of 298 ``unknown`` without anything noticing). The
    real provenance is ``generated_by: "skills/target-profile@<sha>"`` plus ``generated_at``.

    ⚠️ ``dated_from`` is banked deliberately: it reports how many dates came from provenance versus from
    the path fallback, so a corpus silently dated entirely by fallback is VISIBLE in the artifact rather
    than inferred by whoever reads it next. The directory name is a human's claim about a corpus;
    ``generated_at`` is the writer's record of it.

    ★★ It wants PACKAGE FILES, not package directories — and the second attempt passed directories, which
    ``read_text()`` rejects with ``IsADirectoryError``. ``corpus_vintage`` catches that as ``OSError`` and
    falls back to the path regex, so **a caller's type error is absorbed as a data-quality degrade**: the
    return value stayed well-formed and every field was populated, just answered from the directory name.
    Only the ``dated_from`` assertion below distinguished the two. A fallback broad enough to survive an
    unreadable package is broad enough to survive being called wrong, so the caller has to assert the
    SOURCE and not merely the shape.
    """
    v = fd.corpus_vintage(ei.iter_corpus(corpus))
    return {k: v.get(k) for k in ("n", "oldest", "newest", "by_date", "by_sha", "dated_from", "unreadable")}


def build(corpus: Path) -> dict:
    findings = ei.scan_corpus(corpus)
    summary = ei.summarise(findings)
    n_packages = sum(1 for _ in ei.iter_corpus(corpus))
    return {
        "_note": (
            "Pre-state baseline for the emission invariants. ONE-SIDED ratchet on `red_list` only: a "
            "(invariant, card_id, field) triple absent from this list is a regression; a triple here "
            "that no longer fires is progress and prints a note. Counts are for human diffing and are "
            "NOT asserted — see regenerate_emission_invariants_baseline.py for why."
        ),
        "corpus": corpus.name,
        "n_packages": n_packages,
        "vintage": vintage(corpus),
        "heuristics": False,
        "invariants": list(ei.INVARIANTS),
        "fatal_invariants": sorted(ei.FATAL_INVARIANTS),
        "gloss_available": ei.gloss_available(),
        "total_rows": summary["total_rows"],
        "by_invariant": summary["by_invariant"],
        "red_list": [list(t) for t in summary["red_list"]],
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    corpus = Path(argv[1]).expanduser()
    if not corpus.is_dir():
        print(f"not a directory: {corpus}", file=sys.stderr)
        return 1
    data = build(corpus)
    # Liveness before banking anything: a census that dies would bank an EMPTY red list, and an empty
    # red list is a permanently green ratchet. Fail loudly instead.
    assert data["n_packages"] > 0, f"no evidence_package.json found under {corpus}"
    assert data["gloss_available"], "METRIC_GLOSS did not load; the domain invariant would be degraded"
    assert data["red_list"], "zero findings over the whole corpus — verify the scan ran before banking this"
    dated = (data["vintage"].get("dated_from") or {}).get("provenance", 0)
    assert dated == data["n_packages"], (
        f"only {dated} of {data['n_packages']} packages were dated from their own provenance; the rest "
        "fell back to the path regex, so the banked vintage is a claim about the DIRECTORY NAME"
    )
    BASELINE.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(f"wrote {BASELINE}")
    print(f"  {data['n_packages']} packages, {data['total_rows']} rows, {len(data['red_list'])} red-list entries")
    for inv, s in data["by_invariant"].items():
        print(f"  {inv:22s} rows {s['rows']:6d}  pkgs {s['packages']:4d}  pairs {s['card_field_pairs']:4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
