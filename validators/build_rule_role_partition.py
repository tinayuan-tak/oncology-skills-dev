"""build_rule_role_partition.py — M5 of the factored-record migration (VERDICT_REPRESENTATION move #5).

Make the verdict-INERT rules an EXPLICIT display channel instead of silently-dead `signals:`. Every
interpretation rule is classified by ROLE:

  * gating   — its rule_id appears at a keypath that can MOVE A VERDICT (see GATING_KEYPATHS below:
               the `resolve` rungs, plus the `post_resolver_clamp` precedence arms and upgrade
               requirements). It can change what the resolver returns.
  * display  — reachable from NO verdict-moving keypath: it is annotation-only (a claim-vector /
               key-signal / figure input), NOT a verdict driver. Naming them `display` turns "dead
               emitter" into "deliberately non-gating," so the scorecard's I1 (signal-sink coverage)
               and I3 (per-coordinate VOI) are measured only against gating rules.

Because that last sentence means `display` REMOVES a rule from the safety scorecard, mis-classifying a
verdict-driving rule as `display` is a safety-adverse error. Everything below exists to make that
specific mistake loud rather than silent — see the GATING_KEYPATHS note.

The partition is emitted as a committed snapshot (coverage/rule_role_partition.yaml) with a
`--self-check` mode (mirrors build_eval_ledger): a rule gaining/losing verdict-moving consumption
fails CI until the snapshot is consciously regenerated. Low-churn — no per-rule schema edits.

  python validators/build_rule_role_partition.py               # regenerate the snapshot
  python validators/build_rule_role_partition.py --self-check  # CI: fail if the committed snapshot drifted
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RESOLVERS = ROOT / "resolvers"
RULES = ROOT / "interpretation-rules"
PARTITION_PATH = ROOT / "coverage" / "rule_role_partition.yaml"

# ─────────────────────────────────────────────────────────────────────────────────────────────────
# THE RULE-ID KEYPATH TABLE
#
# ★★ This table, and the coverage assertion over it, ARE the M5 fix. The original generator walked
#    `spec["resolve"]` and nothing else. `post_resolver_clamp` — the only rung-bearing block outside
#    `resolve` anywhere in resolvers/ — was therefore invisible, so the five selectivity KILL/liability
#    arms it holds were all classified `display` = verdict-inert while the resolver was minting
#    verdicts from them. A narrow extractor over a population that SPLITS narrows a SAFETY guard.
#
#    The lesson is NOT "add post_resolver_clamp to the list" — that fails again at the next block
#    somebody adds. It is that the keypath set must be DECLARED and its COVERAGE ASSERTED against what
#    the resolvers actually contain, so a new rule_id-bearing keypath fails CI loudly instead of
#    silently shrinking the gating set. `coverage_problems()` is that assertion.
#
# Keypaths are rendered by _keypath(): mapping keys verbatim, list elements as `[]`. The leading
# resolver filename is NOT part of the keypath — these are shapes, not locations.
# ─────────────────────────────────────────────────────────────────────────────────────────────────

#: A rule_id here can change the verdict the resolver returns.
GATING_KEYPATHS = frozenset(
    {
        # `resolve` rungs — first-match ladder; any of these firing selects the rung's verdict.
        "resolve/[]/when_fired",
        "resolve/[]/when_any_fired/[]",
        "resolve/[]/when_all_fired/[]",
        # `post_resolver_clamp` runs AFTER the ladder and REPLACES the verdict (downgrade_only).
        "post_resolver_clamp/precedence/[]/when_fired",
        # ...and its `upgrade` arm promotes not_informative / discordant to a positive verdict, so the
        # AND-of-ORs it requires is verdict-moving too. Bare `[]/[]` because `requires` is a list of
        # lists of rule_ids with no inner key.
        "post_resolver_clamp/upgrade/requires/[]/[]",
    }
)

#: A rule_id here NAMES a rule for provenance or documentation but confers no verdict-moving power of
#: its own. Kept separate rather than folded into GATING because both are currently SUBSETS of the
#: gating set (measured: 0 rules unique to either), and `attribution_problems()` asserts that stays
#: true. Promoting them to gating would hide the day a `driving_rule` names a rule nothing gates on —
#: which is itself a defect worth surfacing, not a reason to widen the safety scorecard.
ATTRIBUTION_KEYPATHS = frozenset(
    {
        # Which rule the rung reports as the driver; always one the rung already keys on.
        "resolve/[]/driving_rule",
        # Declares a clamp arm expected to be inert under the modality lens, with a reason.
        "post_resolver_clamp/modality_conditional/expected_inert_arms/[]/rule_id",
    }
)


def _keypath(path: tuple[str, ...]) -> str:
    return "/".join(path)


def _walk_scalars(node, path: tuple[str, ...] = ()):
    """Yield ``(keypath, value)`` for every string scalar in a nested YAML structure."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_scalars(v, path + (str(k),))
    elif isinstance(node, list):
        for v in node:
            yield from _walk_scalars(v, path + ("[]",))
    elif isinstance(node, str):
        yield _keypath(path), node


def _resolver_docs() -> dict[str, dict]:
    """basename -> parsed resolver spec, for every resolver in resolvers/."""
    out: dict[str, dict] = {}
    for p in sorted(glob.glob(str(RESOLVERS / "*.resolver.yaml"))):
        out[os.path.basename(p)] = yaml.safe_load(Path(p).read_text()) or {}
    return out


def _refs_at(keypaths: frozenset[str]) -> dict[str, set[str]]:
    """rule_id -> set of resolver basenames, for every value found at one of ``keypaths``.

    Deliberately does NOT filter to defined rule_ids: a rung naming a rule that no rules file defines
    is a DANGLING reference, and filtering here would make it invisible (see dangling_problems).
    """
    out: dict[str, set[str]] = {}
    for base, spec in _resolver_docs().items():
        for kp, value in _walk_scalars(spec):
            if kp in keypaths:
                out.setdefault(value, set()).add(base)
    return out


def _rule_definitions() -> dict[str, list[str]]:
    """rule_id -> the rules-file basenames that define it (a list, so duplicates stay visible)."""
    out: dict[str, list[str]] = {}
    for p in sorted(glob.glob(str(RULES / "*.rules.yaml"))):
        base = os.path.basename(p)
        for r in (yaml.safe_load(Path(p).read_text()) or {}).get("rules") or []:
            rid = r.get("rule_id")
            if rid:
                out.setdefault(rid, []).append(base)
    return out


# ── the four checks + the coverage assertion ─────────────────────────────────────────────────────


def coverage_problems() -> list[str]:
    """★ THE ROOT-CAUSE CHECK: every rule_id-valued keypath in resolvers/ must be CLASSIFIED.

    Scans all resolvers for scalars whose value is exactly a defined rule_id, and reports any keypath
    that is in neither GATING_KEYPATHS nor ATTRIBUTION_KEYPATHS. That is how a newly added rung-bearing
    block announces itself instead of silently falling out of the gating set.

    Exact equality against the defined-rule set, never a substring match: a prose `reason:` mentioning
    a rule in passing is not a reference, and a substring match on prose is not a population.
    """
    defined = set(_rule_definitions())
    known = GATING_KEYPATHS | ATTRIBUTION_KEYPATHS
    unclassified: dict[str, set[str]] = {}
    for base, spec in _resolver_docs().items():
        for kp, value in _walk_scalars(spec):
            if value in defined and kp not in known:
                unclassified.setdefault(kp, set()).add(base)
    return [
        f"unclassified rule_id keypath {kp!r} in {sorted(bases)} — a resolver names rule_ids at a "
        f"keypath this generator does not read. Decide whether it can move a verdict and add it to "
        f"GATING_KEYPATHS or ATTRIBUTION_KEYPATHS; leaving it unclassified silently shrinks `gating`."
        for kp, bases in sorted(unclassified.items())
    ]


def dangling_problems() -> list[str]:
    """A verdict-moving keypath names a rule_id that no rules file defines — the rung can never fire."""
    defined = set(_rule_definitions())
    return [
        f"dangling gating reference {rid!r} in {sorted(bases)} — no rules file defines it, so the rung can never fire"
        for rid, bases in sorted(_refs_at(GATING_KEYPATHS).items())
        if rid not in defined
    ]


def duplicate_problems() -> list[str]:
    """The same rule_id defined in more than one rules file.

    Currently zero. It is guarded anyway because the old `dict[rule_id] = basename` build made a
    duplicate SILENTLY overwrite — last file wins, `counts.total` under-reports, and one of the two
    definitions is dead with nothing saying so.
    """
    return [
        f"duplicate rule_id {rid!r} defined in {srcs} — one definition silently shadows the other"
        for rid, srcs in sorted(_rule_definitions().items())
        if len(srcs) > 1
    ]


def attribution_problems() -> list[str]:
    """An ATTRIBUTION keypath names a rule that no verdict-moving keypath references.

    `driving_rule` is what the resolver REPORTS as the cause of its verdict. If it names a rule the
    resolver never actually keys on, the reported provenance is fiction — so this is an error even
    though it moves no verdict.
    """
    gating = set(_refs_at(GATING_KEYPATHS))
    return [
        f"attribution-only reference {rid!r} in {sorted(bases)} is not referenced by any verdict-moving "
        f"keypath — the resolver reports a driver it never keys on"
        for rid, bases in sorted(_refs_at(ATTRIBUTION_KEYPATHS).items())
        if rid not in gating
    ]


def compute_partition() -> dict:
    gating_refs = set(_refs_at(GATING_KEYPATHS))
    rules = _rule_definitions()
    gating = sorted(r for r in rules if r in gating_refs)
    display = sorted(r for r in rules if r not in gating_refs)
    return {
        "_doc": (
            "M5 rule-role partition (VERDICT_REPRESENTATION move #5). gating = reachable from a "
            "verdict-moving resolver keypath (a `resolve` rung, a `post_resolver_clamp` precedence arm, "
            "or a clamp `upgrade` requirement); display = reachable from none of them, i.e. "
            "annotation-only (claim-vector / key-signal / figure input). Regenerate with "
            "build_rule_role_partition.py; --self-check gates drift."
        ),
        # Provenance only — WRITTEN here so a reader can see which mechanisms were read, and so that
        # widening/narrowing the table shows up in the snapshot diff. NEVER read back by the generator:
        # deriving the scope from the snapshot it is checking is how a self-referential guard goes
        # vacuous.
        "gating_keypaths": sorted(GATING_KEYPATHS),
        "attribution_keypaths": sorted(ATTRIBUTION_KEYPATHS),
        "counts": {"total": len(rules), "gating": len(gating), "display": len(display)},
        "gating": gating,
        "display": display,
    }


def _emit_yaml(partition: dict) -> str:
    return yaml.safe_dump(partition, sort_keys=False, width=100)


def self_check() -> tuple[bool, list[str]]:
    if not PARTITION_PATH.exists():
        return False, [f"missing {PARTITION_PATH.name} — run without --self-check to generate it"]
    committed = yaml.safe_load(PARTITION_PATH.read_text()) or {}
    fresh = compute_partition()
    defined = set(_rule_definitions())
    errs: list[str] = []

    # Structural integrity of the live contracts, before any snapshot comparison: a drift message is
    # misleading when the real problem is that a reference dangles or a keypath went unread.
    errs += coverage_problems()
    errs += dangling_problems()
    errs += duplicate_problems()
    errs += attribution_problems()

    # STALE is an ERROR, not a silent shrink: a snapshot entry naming a rule that no longer exists.
    for key in ("gating", "display"):
        for rid in sorted(set(committed.get(key) or []) - defined):
            errs.append(
                f"stale {key} entry {rid!r} — the snapshot names a rule no rules file defines; it was "
                f"deleted or renamed without regenerating"
            )

    # MISDECLARED: a rule the snapshot files on the wrong side of the partition. Reported by DIRECTION,
    # because display->gating is the safety-adverse one (`display` is excluded from the I1/I3 scorecard).
    cg, cd = set(committed.get("gating") or []), set(committed.get("display") or [])
    fg, fd = set(fresh["gating"]), set(fresh["display"])
    for rid in sorted((cd & fg) - (cd - defined)):
        errs.append(
            f"misdeclared {rid!r}: snapshot says display (verdict-inert) but a verdict-moving keypath "
            f"references it — SAFETY-ADVERSE, it is excluded from the I1/I3 scorecard"
        )
    for rid in sorted((cg & fd) - (cg - defined)):
        errs.append(f"misdeclared {rid!r}: snapshot says gating but no verdict-moving keypath references it")

    # Whatever the two passes above did not explain (a genuinely new or deleted rule).
    for key, cset, fset in (("gating", cg, fg), ("display", cd, fd)):
        added, removed = sorted(fset - cset), sorted(cset - fset)
        if (added or removed) and not errs:
            errs.append(
                f"{key} drift: +{added or '[]'} -{removed or '[]'} "
                f"(a rule changed resolver-consumption; regenerate the snapshot consciously)"
            )
    return (not errs), errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="CI-safe: fail if the committed partition drifted from the live contracts",
    )
    args = ap.parse_args(argv)

    if args.self_check:
        ok, errs = self_check()
        print("build_rule_role_partition.py --self-check:")
        for e in errs:
            print(f"  [DRIFT] {e}")
        print("  OK" if ok else "  FAILED")
        return 0 if ok else 1

    # A regenerate that quietly writes a narrowed partition is the failure this whole file is about,
    # so refuse to write one: structural problems are fatal here too, not just under --self-check.
    fatal = coverage_problems() + dangling_problems() + duplicate_problems() + attribution_problems()
    if fatal:
        print("build_rule_role_partition.py: REFUSING to regenerate — fix these first:")
        for e in fatal:
            print(f"  [ERROR] {e}")
        return 1

    partition = compute_partition()
    PARTITION_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARTITION_PATH.write_text(_emit_yaml(partition))
    c = partition["counts"]
    print(
        f"wrote {PARTITION_PATH.relative_to(ROOT)} — {c['gating']} gating / {c['display']} display "
        f"({100 * c['display'] // c['total']}% annotation-only) of {c['total']} rules."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
