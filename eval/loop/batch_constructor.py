#!/usr/bin/env python3
"""batch_constructor — coverage-aware triple roster + dev/held-out split for the subskill loop.

WHY THIS EXISTS (epic #2303 Phase-0 WI-F, issue #2348)
Each loop iteration needs a compact batch of `target x indication[,subtype]` triples plus a
deterministic dev/held-out split. The ORIGINAL design (`.claude/plans/subskill-iteration-loop-
2026-09-30.md` S2.1) called for a ~120-candidate live Phase-0 scan followed by greedy set-cover.
The pilot (same plan, S5A.7) retired that design BEFORE it was built: 13 hand-picked triples hit
~75% of the measured L2b surface, with zero scanning. **This module does not scan anything.** It
is a pure selection algorithm over a CALLER-SUPPLIED coverage map — "for candidate X, which
(family, token) pairs are already known to fire" — because computing that map requires running
the skill (epic WI-A, `run_batch.py`, a separate work item with its own session). Coverage here is
dependency-injected on purpose, not fetched live, so this module is testable from a static fixture
and has no coupling to pixi/AWS/Bedrock.

★★ INDEX ON THE PROPERTY LAYERS, NEVER THE VERDICT (SK#2091; plan S0).
A "pair" is always `(family, token)` at the L2a `source_properties` layer (`key, .property`) or the
L2b `integrated_properties` layer (`key, .concordance_class` or, for the one qualifier family,
`.qualifier_class`). Nothing in this module reads, diffs, stratifies, or gates on a verdict token
(`presence_verdict`, `driving_rule_id`, ...) — a verdict is not a kind of coverage.

WHAT THIS MODULE DOES
1. Loads a CANDIDATE UNIVERSE from one or more TSV files (`target\\tindication\\t[stratum]`) — the
   corpus-20260914 `panel_504.tsv` roster (candidates/labels only; stale for critic reads, see the
   plan S1 fact 2) and/or the pilot's hand-picked `~/subskill-loop-pilot/triples.tsv`.
2. Loads a COVERAGE MAP (JSON: candidate key -> list of `[family, token]` pairs already measured
   for that candidate) and a REQUIRED-PAIRS set (the L2b family x token surface the roster must
   cover).
3. Greedily selects the smallest prefix of coverage-known candidates that covers every required
   pair (classic set-cover approximation: at each step, pick the candidate that covers the most
   still-uncovered pairs; ties broken by a deterministic key sort, never dict/set iteration order).
4. Tops the roster up to a target size with stratum quotas (so the batch isn't ONLY the covering
   set — controls and panel archetypes earn slots even after coverage closes).
5. Assigns a deterministic dev / held-out split via `sha256(salt|key) % 100`, with a stratified
   floor so no stratum is held-out-less, pinned/hash-fixed for a given `(candidates, salt)` input
   — i.e. stable across runs and independent of input ORDER or python set/dict iteration order.
6. Emits a `triples.tsv`-style roster (+ split column) and a batch-spec manifest (coverage matrix,
   split rule, provenance) — the committed artifacts `eval/loop/batches/<skill>/batch-<id>.v1.*`
   that a later WI-A/WI-H consume.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
- It does not run a skill, call pixi, or touch AWS/Bedrock. Coverage is an input, not an output.
- It does not invent the required-pairs surface. The caller supplies it (typically derived once,
  by hand or by a future scan, from `property_catalog/` + `concordance_class.enum.yaml` for the
  skill in question) — this module never reads contracts/vocabularies itself.
- It does not treat an un-covering candidate (no coverage data, or coverage data showing it fires
  nothing new) as excluded from the roster outright — quota fill may still include it (e.g. a
  NULL-heavy control whose VALUE is exercising the floor case, not covering a pair).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

Pair = tuple[str, str]


# --------------------------------------------------------------------------------------------- #
# Candidate universe
# --------------------------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Candidate:
    """One `target x indication[,subtype]` triple in the candidate universe."""

    target: str
    indication: str
    subtype: str = ""
    stratum: str = "unlabeled"
    source: str = ""

    @property
    def key(self) -> str:
        """Stable identity string — used for coverage lookup, hashing, and TSV round-trip."""
        return f"{self.target}|{self.indication}|{self.subtype}"


def load_candidates_tsv(path: str | Path, *, source: str = "") -> list[Candidate]:
    """Read a `target\\tindication\\t[stratum]\\t[subtype]` TSV (3- or 4-column; no header row).

    Both `panel_504.tsv` (target, indication, archetype-label) and the pilot's
    `~/subskill-loop-pilot/triples.tsv` (target, indication, role-label) use the 3-column shape —
    this loader accepts both without a format flag.
    """
    out: list[Candidate] = []
    with open(path, newline="") as fh:
        for row in csv.reader(fh, delimiter="\t"):
            if not row or not row[0] or row[0].startswith("#"):
                continue
            target = row[0].strip()
            indication = row[1].strip() if len(row) > 1 else ""
            stratum = row[2].strip() if len(row) > 2 and row[2].strip() else "unlabeled"
            subtype = row[3].strip() if len(row) > 3 else ""
            out.append(
                Candidate(
                    target=target,
                    indication=indication,
                    subtype=subtype,
                    stratum=stratum,
                    source=source,
                )
            )
    return out


def dedupe_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Dedupe by `.key`, first occurrence wins (so an earlier, more-specific source — e.g. the
    pilot's hand-picked roster — takes priority over a later bulk source — e.g. panel_504)."""
    seen: dict[str, Candidate] = {}
    for c in candidates:
        seen.setdefault(c.key, c)
    return list(seen.values())


# --------------------------------------------------------------------------------------------- #
# Coverage map
# --------------------------------------------------------------------------------------------- #


def load_coverage_json(path: str | Path) -> dict[str, frozenset[Pair]]:
    """Load `{candidate_key: [[family, token], ...]}` -> `{candidate_key: frozenset of pairs}`.

    `candidate_key` must match `Candidate.key` (`target|indication|subtype`, empty subtype for a
    whole-cohort triple). A candidate absent from this map is treated as coverage-UNKNOWN, not
    coverage-empty — it can still fill a stratum quota, it just never wins the set-cover step.
    """
    raw = json.loads(Path(path).read_text())
    out: dict[str, frozenset[Pair]] = {}
    for key, pairs in raw.items():
        out[key] = frozenset((str(fam), str(tok)) for fam, tok in pairs)
    return out


def load_required_pairs_json(path: str | Path) -> frozenset[Pair]:
    """Load `[[family, token], ...]` -> frozenset of pairs — the L2b family x token surface a
    roster must cover (plan S2.1; measured tumor-presence surface S5A.7: 6 families / 12 pairs)."""
    raw = json.loads(Path(path).read_text())
    return frozenset((str(fam), str(tok)) for fam, tok in raw)


# --------------------------------------------------------------------------------------------- #
# Greedy set-cover + quota fill
# --------------------------------------------------------------------------------------------- #


@dataclass
class RosterEntry:
    candidate: Candidate
    newly_covered: frozenset[Pair]
    reason: str  # "cover" | "quota" | "seed"


@dataclass
class RosterResult:
    entries: list[RosterEntry]
    covered_pairs: frozenset[Pair]
    required_pairs: frozenset[Pair]
    uncovered_pairs: frozenset[Pair]

    @property
    def coverage_fraction(self) -> float:
        if not self.required_pairs:
            return 1.0
        return len(self.covered_pairs) / len(self.required_pairs)

    def coverage_report(self) -> dict:
        """A reconciliation report: which pair is covered by which candidate(s), with
        denominators — never a bare count (memory: EVERY count needs a denominator)."""
        by_pair: dict[str, list[str]] = {f"{fam}::{tok}": [] for fam, tok in self.required_pairs}
        for entry in self.entries:
            for fam, tok in entry.newly_covered:
                by_pair.setdefault(f"{fam}::{tok}", []).append(entry.candidate.key)
        return {
            "required_pairs_total": len(self.required_pairs),
            "covered_pairs_total": len(self.covered_pairs),
            "coverage_fraction": self.coverage_fraction,
            "uncovered_pairs": sorted(f"{fam}::{tok}" for fam, tok in self.uncovered_pairs),
            "covering_candidate_by_pair": by_pair,
            "roster_size": len(self.entries),
        }


def select_roster(
    candidates: Sequence[Candidate],
    coverage: dict[str, frozenset[Pair]],
    required_pairs: frozenset[Pair],
    *,
    target_min: int = 13,
    target_max: int = 60,
    strata_min: dict[str, int] | None = None,
    seed_keys: Sequence[str] = (),
) -> RosterResult:
    """Greedy coverage-aware roster selection (plan S2.1, shrunk per the pilot — no 120-scan).

    1. SEED: any candidate in `seed_keys` (e.g. the pilot's hand-picked 13) is admitted first, in
       the given order, before the greedy step runs — codifying "13 hand-picked -> ~75% coverage"
       as the roster's base rather than re-discovering it.
    2. COVER: repeatedly admit the remaining coverage-known candidate that covers the most
       currently-uncovered required pairs; stop once every required pair is covered or no
       candidate covers anything new. Ties broken by `candidate.key` ascending (deterministic;
       NEVER by dict/set iteration order).
    3. QUOTA: top up to `target_min` (and no further than `target_max`) by stratum, admitting the
       lowest-key remaining candidate per under-quota stratum, so controls/archetypes that covered
       nothing new still earn roster slots (plan S2.1's "every stratum is a regime, not a verdict
       class").
    """
    by_key = {c.key: c for c in candidates}
    strata_min = dict(strata_min or {})

    admitted: list[RosterEntry] = []
    admitted_keys: set[str] = set()
    covered: set[Pair] = set()

    def admit(key: str, reason: str) -> None:
        cand = by_key[key]
        pairs = coverage.get(key, frozenset())
        new = frozenset(pairs - covered)
        covered.update(new)
        admitted.append(RosterEntry(candidate=cand, newly_covered=new, reason=reason))
        admitted_keys.add(key)

    # 1. SEED
    for key in seed_keys:
        if len(admitted) >= target_max:
            break
        if key in by_key and key not in admitted_keys:
            admit(key, "seed")

    # 2. COVER — greedy set-cover over coverage-known, not-yet-admitted candidates.
    remaining = sorted(
        (k for k in coverage if k in by_key and k not in admitted_keys),
    )
    while covered != required_pairs and remaining and len(admitted) < target_max:
        best_key = None
        best_gain = -1
        for key in remaining:
            gain = len(coverage[key] - covered)
            if gain > best_gain or (gain == best_gain and (best_key is None or key < best_key)):
                best_gain = gain
                best_key = key
        if best_key is None or best_gain <= 0:
            break
        admit(best_key, "cover")
        remaining.remove(best_key)

    # 3. QUOTA — stratum floors, then overall target_min, capped at target_max.
    def strata_counts() -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in admitted:
            counts[e.candidate.stratum] = counts.get(e.candidate.stratum, 0) + 1
        return counts

    pool = sorted(k for k in by_key if k not in admitted_keys)

    def fill_one(predicate) -> bool:
        for key in pool:
            if key in admitted_keys:
                continue
            if predicate(by_key[key]):
                admit(key, "quota")
                return True
        return False

    for stratum, minimum in sorted(strata_min.items()):
        while strata_counts().get(stratum, 0) < minimum and len(admitted) < target_max:
            if not fill_one(lambda c, s=stratum: c.stratum == s):
                break

    while len(admitted) < target_min and len(admitted) < target_max:
        if not fill_one(lambda c: True):
            break

    uncovered = required_pairs - covered
    return RosterResult(
        entries=admitted,
        covered_pairs=frozenset(covered),
        required_pairs=required_pairs,
        uncovered_pairs=frozenset(uncovered),
    )


# --------------------------------------------------------------------------------------------- #
# Deterministic dev / held-out split
# --------------------------------------------------------------------------------------------- #


SplitLabel = str  # "dev" | "held_out"


def _split_hash_pct(key: str, salt: str) -> int:
    """`sha256(salt|key) % 100` — pinned/hash-fixed, independent of python hash-randomization,
    independent of input order, and reproducible from (`key`, `salt`) alone across any run."""
    digest = hashlib.sha256(f"{salt}|{key}".encode("utf-8")).hexdigest()
    return int(digest, 16) % 100


@dataclass
class SplitResult:
    split: dict[str, SplitLabel]  # candidate key -> "dev" | "held_out"
    salt: str
    held_out_fraction: float
    min_per_stratum: int

    def counts(self) -> dict[str, int]:
        return {
            "dev": sum(1 for v in self.split.values() if v == "dev"),
            "held_out": sum(1 for v in self.split.values() if v == "held_out"),
            "total": len(self.split),
        }


def assign_split(
    entries: Sequence[RosterEntry],
    *,
    salt: str = "",
    held_out_fraction: float = 0.30,
    min_per_stratum: int = 2,
) -> SplitResult:
    """Deterministic dev/held-out split, stratified floor, anti-cherry-pick (plan S2.1: "fixed
    before any critic output exists"). Same `(entries, salt, held_out_fraction, min_per_stratum)`
    -> byte-identical split on every call, on every host, regardless of dict/set iteration order
    (every candidate is addressed by its sorted `.key`, never by position)."""
    cutoff = round(held_out_fraction * 100)
    split: dict[str, SplitLabel] = {}
    by_stratum: dict[str, list[str]] = {}
    for e in entries:
        key = e.candidate.key
        split[key] = "held_out" if _split_hash_pct(key, salt) < cutoff else "dev"
        by_stratum.setdefault(e.candidate.stratum, []).append(key)

    # Stratified floor: if a stratum has fewer than `min_per_stratum` held-out members (and has
    # at least that many members at all), promote the lowest-hash-percentile dev member(s) of
    # that stratum into held_out — deterministic (sorted by hash pct, then key), not random.
    for stratum, keys in sorted(by_stratum.items()):
        if len(keys) < min_per_stratum:
            continue
        held = [k for k in keys if split[k] == "held_out"]
        if len(held) >= min_per_stratum:
            continue
        dev_candidates = sorted(
            (k for k in keys if split[k] == "dev"),
            key=lambda k: (_split_hash_pct(k, salt), k),
        )
        for key in dev_candidates:
            if len(held) >= min_per_stratum:
                break
            split[key] = "held_out"
            held.append(key)

    return SplitResult(
        split=split,
        salt=salt,
        held_out_fraction=held_out_fraction,
        min_per_stratum=min_per_stratum,
    )


# --------------------------------------------------------------------------------------------- #
# Output: roster TSV + batch-spec manifest
# --------------------------------------------------------------------------------------------- #


def build_batch_spec(
    roster: RosterResult,
    split: SplitResult,
    *,
    skill: str,
    batch_id: str,
) -> dict:
    """The committed `batch-<id>.v1` manifest: coverage matrix, split rule verbatim, provenance.
    Re-cutting a batch is additive (a new `batch_id`), never an in-place edit (plan S2.1)."""
    return {
        "skill": skill,
        "batch_id": batch_id,
        "coverage": roster.coverage_report(),
        "split_rule": (
            f"sha256(salt|target|indication|subtype) % 100 < {round(split.held_out_fraction * 100)}"
            f" -> held_out (salt={split.salt!r}, min_per_stratum={split.min_per_stratum})"
        ),
        "split_counts": split.counts(),
        "roster": [
            {
                "key": e.candidate.key,
                "target": e.candidate.target,
                "indication": e.candidate.indication,
                "subtype": e.candidate.subtype,
                "stratum": e.candidate.stratum,
                "source": e.candidate.source,
                "reason": e.reason,
                "newly_covered_pairs": [list(p) for p in sorted(e.newly_covered)],
                "split": split.split.get(e.candidate.key, "dev"),
            }
            for e in roster.entries
        ],
    }


def write_roster_tsv(roster: RosterResult, split: SplitResult, path: str | Path) -> None:
    """`triples.tsv`-style output + a `split` column — target\\tindication\\tsubtype\\tstratum\\tsplit."""
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        for e in roster.entries:
            c = e.candidate
            writer.writerow([c.target, c.indication, c.subtype, c.stratum, split.split.get(c.key, "dev")])


def write_batch_spec(spec: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------------------------- #


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--candidates-tsv",
        action="append",
        required=True,
        help="Candidate universe TSV (target, indication, [stratum], [subtype]); repeatable, "
        "first occurrence of a key wins (list the most-trusted/hand-picked source FIRST).",
    )
    p.add_argument("--coverage-json", required=True, help="candidate_key -> [[family,token],...]")
    p.add_argument("--required-pairs-json", required=True, help="[[family,token],...] surface")
    p.add_argument("--seed-tsv", help="Optional TSV whose rows are admitted first (plan S2.1 seed)")
    p.add_argument("--skill", default="tumor-presence")
    p.add_argument("--batch-id", required=True)
    p.add_argument("--salt", default="", help="Split salt (keep stable across re-cuts of a batch)")
    p.add_argument("--held-out-fraction", type=float, default=0.30)
    p.add_argument("--min-per-stratum", type=int, default=2)
    p.add_argument("--target-min", type=int, default=13)
    p.add_argument("--target-max", type=int, default=60)
    p.add_argument("--out-roster", required=True)
    p.add_argument("--out-spec", required=True)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    candidates: list[Candidate] = []
    for tsv in args.candidates_tsv:
        candidates.extend(load_candidates_tsv(tsv, source=Path(tsv).name))
    candidates = dedupe_candidates(candidates)

    seed_keys: list[str] = []
    if args.seed_tsv:
        seed_keys = [c.key for c in load_candidates_tsv(args.seed_tsv)]

    coverage = load_coverage_json(args.coverage_json)
    required_pairs = load_required_pairs_json(args.required_pairs_json)

    roster = select_roster(
        candidates,
        coverage,
        required_pairs,
        target_min=args.target_min,
        target_max=args.target_max,
        strata_min={},
        seed_keys=seed_keys,
    )
    split = assign_split(
        roster.entries,
        salt=args.salt,
        held_out_fraction=args.held_out_fraction,
        min_per_stratum=args.min_per_stratum,
    )

    write_roster_tsv(roster, split, args.out_roster)
    spec = build_batch_spec(roster, split, skill=args.skill, batch_id=args.batch_id)
    write_batch_spec(spec, args.out_spec)

    print(
        f"roster size={len(roster.entries)} coverage={roster.coverage_fraction:.2f} "
        f"({len(roster.covered_pairs)}/{len(roster.required_pairs)}) "
        f"split={split.counts()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
