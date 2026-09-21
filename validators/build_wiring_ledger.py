#!/usr/bin/env python3
"""build_wiring_ledger.py — I.4: which data-catalog datasets are wired, and which are DARK?

The dataset-grain complement of I.3. I.3 (build_wiring_reconciliation.py) reconciles per CARD:
READS vs DECLARES vs EMITS. This file inverts the axis to per DATASET, over the whole data-catalog
manifest universe, and answers the one number I.4 moves: how many catalog datasets does no method
read? A dark dataset produces no (card_id, field, value) triples — it is invisible to the framework
until a method is extended to read it. "Wire the dark datasets" = shrink `dark`, one PR each; the
I.1 emission ledger and the I.3 reconciliation are the acceptance test for each wiring.

THREE mutually-exclusive statuses per catalog manifest id (they partition the universe):

    read            a routed card's method statically reads it (a catalog_query literal), OR it
                    matches a reader f-string template, OR a read product transitively derives from
                    it (data-catalog `derived_from` lineage). POSITIVE evidence — trustworthy: a
                    concrete read is sound regardless of the card's I.3 confidence tier.
    declared_only   named in some card's `required_inputs[].product_id` (or lineage-upstream of one)
                    but NOT in the read closure. Almost certainly consumed — via a param-passed
                    manifest id, `aws s3 cp`, or a direct `data-catalog/derived/{id}` path, none of
                    which the catalog_query AST oracle can see (the same UNSOUNDNESS that put I.3's
                    confidence gate in place). A DIMENSION, never dark: a card claims it.
    dark            neither read nor declared nor lineage-covered. No card names it at all. THE I.4
                    WORKLIST — the number that moves.

WHY declared_only is NOT folded into dark: the I.3 arc measured that a static reads oracle over this
codebase is unsound (reads escape through param-passed ids / s3 cp / direct paths). Calling a
declared-but-not-statically-read dataset "dark" would ship those extraction artifacts as a worklist —
the exact green-for-the-wrong-reason this plan removes. So the read side is asserted only where it is
POSITIVE (a literal read is real); absence-of-read is downgraded to `declared_only` whenever a card
declares the id, and only the residue no card mentions is called dark.

WHAT EACH HALF OF --self-check CAN AND CANNOT SEE:

  HERMETIC half — CI, no siblings, no credentials. Cannot recompute the universe or the read set
                  (both need data-catalog + analysis-methods + skills). It re-reads TODAY's cards
                  (in-repo) for the declared set and checks: the three lists partition the committed
                  universe, the anti-vacuity floors hold, and no committed-`dark` id is declared by a
                  card today (that in-repo edit must move the id to `declared_only` — regenerate).
  LIVE half     — needs the three siblings. Fully recomputes the ledger and diffs it. Catches
                  READ-side drift the hermetic half is blind to: a method starting/stopping a read,
                  lineage moving, the catalog universe changing. Announced-skip (never silent) when a
                  sibling is absent — the same epistemic position as the checkout-only CI runner.

`dark` is a DIMENSION, not a gate: having a backlog of unwired datasets is not a failure, it is the
I.4 worklist. `--self-check` gates DRIFT (the committed snapshot must equal a regeneration) plus the
anti-vacuity floors, so the number cannot silently change and an empty/broken run cannot read as a
clean repo.

Usage:
    python validators/build_wiring_ledger.py                # regenerate the snapshot (needs siblings)
    python validators/build_wiring_ledger.py --self-check   # CI: hermetic drift gate (+live if present)

Modelled on build_wiring_reconciliation.py / build_emission_ledger.py — committed snapshot +
--self-check, a pattern CI already gates — and imports the I.3 extraction helpers rather than
re-deriving them, so the two ledgers can never disagree about what "read" means.
"""

from __future__ import annotations

import argparse
import glob
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "cards"
SNAPSHOT_PATH = ROOT / "coverage" / "wiring_ledger.yaml"

# Reuse the I.3 reads/lineage/catalog extraction verbatim — a __file__-relative insert, cwd-independent.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_wiring_reconciliation as wr  # noqa: E402

# Anti-vacuity floors. A ledger that saw ~no catalog, or ~no reads, reads identically to a clean repo
# (everything would look dark) — the failure this file exists to remove. Both trip an empty/broken run.
MIN_CATALOG_DATASETS = 400  # measured universe is 534; a big drop means the manifest glob broke
MIN_READ_DATASETS = 40  # measured read closure is ~135; ~0 means the reads oracle broke


# ---------------------------------------------------------------------------
def _all_declared() -> set[str]:
    """Every product_id any card names in required_inputs — over ALL cards, not only routed ones.
    In-repo only (cards/), so the hermetic self-check can recompute it with no sibling."""
    declared: set[str] = set()
    for f in glob.glob(str(CARDS / "**/*.card.yaml"), recursive=True):
        try:
            d = yaml.safe_load(Path(f).read_text()) or {}
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for ri in d.get("required_inputs") or []:
            if isinstance(ri, dict) and isinstance(ri.get("product_id"), str):
                declared.add(ri["product_id"])
    return declared


def _read_closure(cat_ids: set[str], derived_from: dict) -> tuple[set[str], set[str]]:
    """(read closure, literal reads). Union over ALL dispatcher-routed cards of the catalog literals
    their method closure reads, plus reader-template matches, plus the derived_from lineage of both.
    Any card's confidence tier counts: a concrete literal read is positive evidence, sound on its own."""
    card_fn, fndefs = wr.card_to_fn_and_fndefs()
    dirs = wr._methods_dirs()
    lits: set[str] = set()
    templates: set[str] = set()
    for _card, fn in card_fn.items():
        mods = wr.modules_for_fn(fn, fndefs)
        lit, tmpl, _opq, _scanned, _escape = wr.reads_for_card(mods, dirs)
        lits |= {r for r in lit if r in cat_ids}
        templates |= set(tmpl)
    tmpl_res = [wr.tmpl_re(t) for t in templates]
    tmpl_hits = {m for m in cat_ids if any(rx.match(m) for rx in tmpl_res)}
    closure = set(lits) | tmpl_hits
    for r in list(closure):
        closure |= wr.upstreams(r, derived_from)
    return closure, lits


def compute_ledger() -> dict:
    cat_ids, derived_from = wr.load_catalog()
    read_closure, literal_reads = _read_closure(cat_ids, derived_from)

    declared = _all_declared() & cat_ids
    declared_closure = set(declared)
    for d in list(declared_closure):
        declared_closure |= wr.upstreams(d, derived_from)
    declared_closure &= cat_ids
    declared_only = declared_closure - read_closure

    dark = cat_ids - read_closure - declared_only
    dark_by_family = dict(Counter(d.split("-")[0] for d in dark).most_common())

    return {
        "_doc": (
            "I.4 wiring ledger: every data-catalog manifest id by wiring status -- read (a method "
            "reads it / template / lineage), declared_only (a card names it but no static read; "
            "likely consumed via an escape hatch the AST oracle cannot see -- a dimension), or dark "
            "(no card reads OR names it -- the wiring worklist). `dark` is the number I.4 moves. "
            "Regenerate with validators/build_wiring_ledger.py; --self-check gates drift."
        ),
        "sibling_shas": wr._sibling_shas(),
        "n_catalog_datasets": len(cat_ids),
        "counts": {
            "read": len(read_closure),
            "declared_only": len(declared_only),
            "dark": len(dark),
        },
        # literal_reads is the sound floor of `read` (before template/lineage widening) — recorded so a
        # regression in the reads oracle is visible even if lineage keeps the read count up.
        "n_literal_reads": len(literal_reads),
        "dark_by_source_family": dark_by_family,
        "read": sorted(read_closure),
        "declared_only": sorted(declared_only),
        "dark": sorted(dark),
    }


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------
def _partition_errors(snap: dict) -> list[str]:
    """The three lists must partition the committed universe and match the counts — pure arithmetic on
    the committed snapshot, so it catches a hand-edit that drops/moves/dupes an id."""
    errs: list[str] = []
    universe = snap.get("n_catalog_datasets") or 0
    read = set(snap.get("read") or [])
    decl = set(snap.get("declared_only") or [])
    dark = set(snap.get("dark") or [])
    for a, b, na, nb in (
        (read, decl, "read", "declared_only"),
        (read, dark, "read", "dark"),
        (decl, dark, "declared_only", "dark"),
    ):
        overlap = a & b
        if overlap:
            errs.append(f"status lists not disjoint: {na} ∩ {nb} = {sorted(overlap)[:5]} — regenerate")
    total = len(read) + len(decl) + len(dark)
    if total != universe:
        errs.append(
            f"partition broken: read+declared_only+dark = {total} != n_catalog_datasets {universe} "
            f"— a dataset is missing or double-counted; regenerate"
        )
    counts = snap.get("counts") or {}
    for k, s in (("read", read), ("declared_only", decl), ("dark", dark)):
        if counts.get(k) != len(s):
            errs.append(f"counts.{k}={counts.get(k)} != len({k})={len(s)} — the snapshot was hand-edited")
    return errs


def _floors(snap: dict) -> list[str]:
    errs: list[str] = []
    universe = snap.get("n_catalog_datasets") or 0
    read = (snap.get("counts") or {}).get("read") or 0
    dark = (snap.get("counts") or {}).get("dark") or 0
    if universe < MIN_CATALOG_DATASETS:
        errs.append(
            f"vacuous: n_catalog_datasets={universe} < {MIN_CATALOG_DATASETS} — the manifest glob saw "
            f"~no catalog, which reads identically to a clean repo"
        )
    if read < MIN_READ_DATASETS:
        errs.append(
            f"vacuous: read datasets={read} < {MIN_READ_DATASETS} — the reads oracle found ~nothing, "
            f"so every dataset would look dark and the census has no signal"
        )
    if universe and dark >= universe:
        errs.append(f"vacuous: dark={dark} >= n_catalog_datasets={universe} — nothing is wired")
    return errs


def self_check_hermetic(snap: dict) -> list[str]:
    """Partition + floors + one in-repo drift signal. Cannot recompute the universe or read set (both
    need siblings); re-reads TODAY's cards (in-repo) for the declared set and asserts no committed-dark
    id is declared now — that edit must move the id to declared_only. Only the live half proves reads."""
    errs = _partition_errors(snap)
    errs += _floors(snap)
    newly_declared_dark = sorted(_all_declared() & set(snap.get("dark") or []))
    for d in newly_declared_dark:
        errs.append(
            f"declaration drift: card(s) now declare {d} but it is committed as dark — regenerate so "
            f"it moves to declared_only"
        )
    return errs


def self_check_live(snap: dict) -> tuple[list[str], str | None]:
    """Fully recompute and diff. Catches read-side drift the hermetic half is blind to. Announced-skip
    when a sibling is absent — the checkout-only CI runner's epistemic position."""
    if not wr._siblings_available():
        return [], "one or more siblings (analysis-methods/skills/data-catalog) absent"
    fresh = compute_ledger()
    errs: list[str] = []
    if fresh["n_catalog_datasets"] != snap.get("n_catalog_datasets"):
        errs.append(
            f"universe drift: live {fresh['n_catalog_datasets']} vs committed "
            f"{snap.get('n_catalog_datasets')} — the manifest set changed; regenerate"
        )
    for k in ("read", "declared_only", "dark"):
        if sorted(fresh[k]) != sorted(snap.get(k) or []):
            fl, cl = set(fresh[k]), set(snap.get(k) or [])
            added = sorted(fl - cl)[:5]
            removed = sorted(cl - fl)[:5]
            errs.append(f"{k} drift: live +{added} -{removed} vs committed — regenerate")
    return errs, None


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="CI-safe: hermetic drift gate (+ live half when siblings are present)",
    )
    args = ap.parse_args(argv)

    if args.self_check:
        if not SNAPSHOT_PATH.exists():
            print(f"missing {SNAPSHOT_PATH.name} — run without --self-check to generate it")
            return 1
        snap = yaml.safe_load(SNAPSHOT_PATH.read_text()) or {}
        errs = self_check_hermetic(snap)
        print("build_wiring_ledger.py --self-check (hermetic: partition + floors + declaration drift)")
        live_errs, skipped = self_check_live(snap)
        errs += live_errs
        if skipped:
            print(f"  ~ live half SKIPPED: {skipped} (read-side drift unchecked)")
        else:
            print("  + live half: recomputed the ledger from siblings")
        for e in errs:
            print(f"  [DRIFT] {e}")
        print("  OK" if not errs else "  FAILED")
        return 0 if not errs else 1

    if not wr._siblings_available():
        print("cannot regenerate: analysis-methods/skills/data-catalog siblings not all present")
        return 1
    snap = compute_ledger()
    fatal = _floors(snap) + _partition_errors(snap)
    if fatal:
        print("build_wiring_ledger.py: REFUSING to write — fix these first:")
        for e in fatal:
            print(f"  [ERROR] {e}")
        return 1
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(yaml.safe_dump(snap, sort_keys=False, width=100))
    c = snap["counts"]
    print(
        f"wrote {SNAPSHOT_PATH.relative_to(ROOT)} — {snap['n_catalog_datasets']} datasets: "
        f"{c['read']} read / {c['declared_only']} declared_only / {c['dark']} DARK."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
