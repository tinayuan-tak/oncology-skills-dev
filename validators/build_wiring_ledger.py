#!/usr/bin/env python3
"""build_wiring_ledger.py — I.4: which data-catalog datasets are wired, and which are DARK?

The dataset-grain complement of I.3. I.3 (build_wiring_reconciliation.py) reconciles per CARD:
READS vs DECLARES vs EMITS. This file inverts the axis to per DATASET, over the whole data-catalog
manifest universe, and answers the one number I.4 moves: how many catalog datasets does no method
read? A dark dataset produces no (card_id, field, value) triples — it is invisible to the framework
until a method is extended to read it. "Wire the dark datasets" = shrink `dark`, one PR each; the
I.1 emission ledger and the I.3 reconciliation are the acceptance test for each wiring.

FOUR mutually-exclusive statuses per catalog manifest id (they partition the universe), in
precedence order read > declared_only > referenced_only > dark:

    read            a routed card's method statically reads it (a catalog_query literal), OR it
                    matches a reader f-string template, OR a read product transitively derives from
                    it (data-catalog `derived_from` lineage). POSITIVE evidence — trustworthy: a
                    concrete read is sound regardless of the card's I.3 confidence tier.
    declared_only   named in some card's `required_inputs[].product_id` (or lineage-upstream of one)
                    but NOT in the read closure. Almost certainly consumed — via a param-passed
                    manifest id, `aws s3 cp`, or a direct `data-catalog/derived/{id}` path, none of
                    which the catalog_query AST oracle can see (the same UNSOUNDNESS that put I.3's
                    confidence gate in place). A DIMENSION, never dark: a card claims it.
    referenced_only its literal id appears in analysis-methods / skills .py source, but it is neither
                    a captured read nor a card declaration. A mixed bag that CANNOT be confidently
                    called dark: a param-passed read (`{IND: id}` dict then a variable arg), a
                    dataset a method PRODUCES (build_product/derive), or a stale mention in a comment
                    about a superseded id. A DIMENSION — the residue that needs human triage, the
                    mirror of declared_only for code references. (Measured: 23 ids, incl. 2 genuine
                    escape-hatch reads — coadread-dge-df06320 via an _INDICATION_TO_ADJ_MANIFEST
                    dict, hpa-rna-tissue-consensus-v25-1 via a MANIFEST_ID module constant.)
    dark            ZERO reference anywhere — not read, not declared, and its literal appears in no
                    method/skill source. No code touches it at all. THE I.4 WORKLIST.

WHY declared_only AND referenced_only are NOT folded into dark: the I.3 arc measured that a static
reads oracle over this codebase is unsound (reads escape through param-passed ids / s3 cp / direct
paths). Calling a dataset that is declared, or merely NAMED in code, "dark" would ship those
extraction artifacts as a worklist — the exact green-for-the-wrong-reason this plan removes. So the
read side is asserted only where it is POSITIVE (a literal read is real); absence-of-read is
downgraded to a dimension whenever a card declares the id (declared_only) or any method/skill source
mentions its literal (referenced_only), and only the residue with NO reference is called dark. `dark`
is thus a sound lower bound on the truly-unwired set, not a static-oracle over-count.

WHAT EACH HALF OF --self-check CAN AND CANNOT SEE:

  HERMETIC half — CI, no siblings, no credentials. Cannot recompute the universe, the read set, or the
                  referenced_only split (all need data-catalog + analysis-methods + skills). It re-reads
                  TODAY's cards (in-repo) for the declared set and checks: the four lists partition the
                  committed universe, the anti-vacuity floors hold, and no committed-`dark` OR
                  `referenced_only` id is declared by a card today (that in-repo edit must move the id
                  to `declared_only` — regenerate).
  LIVE half     — needs the three siblings. Fully recomputes the ledger and diffs it. Catches READ-side
                  AND code-reference drift the hermetic half is blind to: a method starting/stopping a
                  read, a source file gaining/losing an id literal, lineage moving, the catalog universe
                  changing. Announced-skip (never silent) when a sibling is absent — the same epistemic
                  position as the checkout-only CI runner.

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


def _referenced_in_code(candidates: set[str]) -> set[str]:
    """Of `candidates`, those whose literal id substring appears in any analysis-methods `methods/**`
    or skills `skills/**` .py source. A NAME reference the catalog_query reads oracle does not count as
    a read: a param-passed id (`{IND: id}` dict then a variable arg), a dataset the method PRODUCES,
    or a stale comment about a superseded id. LIVE-only (needs the two sibling source trees) — the
    hermetic self-check can neither compute nor verify it, so `referenced_only` is a committed list the
    live half re-derives. Reads every source once into a single blob and substring-tests each candidate;
    manifest ids are long hyphenated slugs, so substring collision with unrelated code is negligible."""
    roots = [wr.AM / "methods", wr.vc._SKILLS_REPO / "skills"]
    blobs: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for f in root.rglob("*.py"):
            try:
                blobs.append(f.read_text(errors="ignore"))
            except Exception:
                continue
    source = "\n".join(blobs)
    return {c for c in candidates if c in source}


def compute_ledger() -> dict:
    cat_ids, derived_from = wr.load_catalog()
    read_closure, literal_reads = _read_closure(cat_ids, derived_from)

    declared = _all_declared() & cat_ids
    declared_closure = set(declared)
    for d in list(declared_closure):
        declared_closure |= wr.upstreams(d, derived_from)
    declared_closure &= cat_ids
    declared_only = declared_closure - read_closure

    # Precedence read > declared_only > referenced_only > dark. Of the residue no card reads or
    # declares, split by whether the id's literal is NAMED anywhere in method/skill source — a name is
    # not a captured read, so it cannot be confidently dark (likely a param-passed read the AST oracle
    # cannot see). Only ids with ZERO reference are dark; the census is a sound lower bound, not an
    # AST over-count.
    remaining = cat_ids - read_closure - declared_only
    referenced_only = _referenced_in_code(remaining)
    dark = remaining - referenced_only
    dark_by_family = dict(Counter(d.split("-")[0] for d in dark).most_common())

    return {
        "_doc": (
            "I.4 wiring ledger: every data-catalog manifest id by wiring status -- read (a method "
            "reads it / template / lineage), declared_only (a card names it in required_inputs but no "
            "static read -- likely an escape-hatch read the AST oracle cannot see; a dimension), "
            "referenced_only (its literal id appears in method/skill .py source but is neither a "
            "captured read nor a card declaration -- a param-passed read / produced dataset / stale "
            "mention; a dimension needing triage), or dark (ZERO reference -- no code reads, declares, "
            "OR names it; the wiring worklist). `dark` is the number I.4 moves, a sound lower bound on "
            "the truly-unwired set. Regenerate with validators/build_wiring_ledger.py; --self-check "
            "gates drift."
        ),
        "sibling_shas": wr._sibling_shas(),
        "n_catalog_datasets": len(cat_ids),
        "counts": {
            "read": len(read_closure),
            "declared_only": len(declared_only),
            "referenced_only": len(referenced_only),
            "dark": len(dark),
        },
        # literal_reads is the sound floor of `read` (before template/lineage widening) — recorded so a
        # regression in the reads oracle is visible even if lineage keeps the read count up.
        "n_literal_reads": len(literal_reads),
        "dark_by_source_family": dark_by_family,
        "read": sorted(read_closure),
        "declared_only": sorted(declared_only),
        "referenced_only": sorted(referenced_only),
        "dark": sorted(dark),
    }


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------
def _partition_errors(snap: dict) -> list[str]:
    """The four lists must partition the committed universe and match the counts — pure arithmetic on
    the committed snapshot, so it catches a hand-edit that drops/moves/dupes an id."""
    errs: list[str] = []
    universe = snap.get("n_catalog_datasets") or 0
    buckets = {k: set(snap.get(k) or []) for k in ("read", "declared_only", "referenced_only", "dark")}
    names = list(buckets)
    for i, na in enumerate(names):
        for nb in names[i + 1 :]:
            overlap = buckets[na] & buckets[nb]
            if overlap:
                errs.append(f"status lists not disjoint: {na} ∩ {nb} = {sorted(overlap)[:5]} — regenerate")
    total = sum(len(s) for s in buckets.values())
    if total != universe:
        errs.append(
            f"partition broken: read+declared_only+referenced_only+dark = {total} != "
            f"n_catalog_datasets {universe} — a dataset is missing or double-counted; regenerate"
        )
    counts = snap.get("counts") or {}
    for k, s in buckets.items():
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
    """Partition + floors + one in-repo drift signal. Cannot recompute the universe, the read set, or
    the referenced_only split (all need siblings); re-reads TODAY's cards (in-repo) for the declared set
    and asserts no committed-dark OR committed-referenced_only id is declared now — declared_only has
    precedence, so that in-repo edit must move the id there. Only the live half proves reads/references."""
    errs = _partition_errors(snap)
    errs += _floors(snap)
    declared = _all_declared()
    for bucket in ("dark", "referenced_only"):
        for d in sorted(declared & set(snap.get(bucket) or [])):
            errs.append(
                f"declaration drift: card(s) now declare {d} but it is committed as {bucket} — "
                f"regenerate so it moves to declared_only"
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
    for k in ("read", "declared_only", "referenced_only", "dark"):
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
        f"{c['read']} read / {c['declared_only']} declared_only / {c['referenced_only']} "
        f"referenced_only / {c['dark']} DARK."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
