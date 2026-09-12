#!/usr/bin/env python3
"""dispositions — capture the reviewer judgments the framework already makes and currently throws away.

WHY THIS EXISTS
The framework holds ~45,878 golden/stability rows, and every one of them asserts that it agrees with
its PAST SELF. The only rows asserting it was RIGHT are the 32 in `eval/loop_dispositions.yaml`
(n_sharp=29, precision_strict=0.483). Every other correctness judgment a reviewer makes while reading
a run lands in CASE_LOG prose or a PR body, where it cannot be counted, joined, or regressed against.
That asymmetry is why threshold and `priority:` tuning has no measurable objective: the tuner has
45,878 rows of self-agreement and 29 rows of truth.

This module is the missing capture step. It appends ONE JSON object per judgment to
`eval/dispositions.jsonl`, keyed on the SAME 5-tuple fact address the existing YAML uses, so the two
sources join. It is INSTRUMENTATION, not a gate, and it is verdict-INERT by construction: no skill,
card, rule, resolver or golden snapshot reads this file.

WHAT IT DELIBERATELY DOES NOT DO
- It does not pool its judgments with `loop_dispositions.yaml`. Those rows answer "was the flagged gap
  REAL?" (the discordance lane's precision). These rows answer "was the framework's OUTPUT right?"
  Averaging two different questions into one number would manufacture a metric that means nothing —
  `loop_health` reports them as separate sections and `precision_strict` stays defined on the legacy
  rows alone.
- It does not score an abstention as a wrong answer. `unreadable` (the axis was not measurable, the
  framework should have abstained) is a SEPARATE judgment from `wrong_verdict`, and `measuredness`
  is carried on every row. A non-measurement is not a low score — the same invariant that keeps an
  off-axis tier out of a numeric ordinal (`subgroup_derivation.is_measured`).
- It does not present a defect hunt as a rate. Every row records `selection`, and only `sampled` rows
  feed `per_grain_agreement_sampled`. A reviewer filing rows while chasing a known bug selects ON
  being wrong, so that agreement is ~0 by construction; quoting it as the framework's accuracy would
  turn the reviewer's own attention into a measurement. Default is `targeted` — a row whose selection
  was not recorded is assumed NOT to have come from a frame.
- It does not accept a judgment that is meaningless for its grain. `noise` is not a thing a verdict
  can be, and `wrong_verdict` is not a thing a surfaced atom can be; the vocabulary is scoped per
  grain, so a category error is rejected on write rather than silently counted.

GRAINS AND THEIR VOCABULARIES
  verdict     — was this axis verdict right?
                agree | wrong_verdict | wrong_reason | unreadable | missing_call
  atom        — was this surfaced fact worth surfacing?
                signal | restatement | noise | artifact
  precedence  — when two rules matched, which SHOULD have won?
                a_beats_b | b_beats_a | tie

`artifact` is kept distinct from `noise` on purpose: noise is a real measurement not worth surfacing,
an artifact is a pipeline or reference-frame defect masquerading as a finding. They are fixed by
different work and they are the two numbers a salience ranker has to be judged on separately.
"""

from __future__ import annotations

import argparse
import collections
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = 1
DEFAULT_LEDGER = Path(__file__).resolve().parent / "dispositions.jsonl"

# Closed vocabularies. Scoped per grain — a judgment must be legal for the grain it is filed under.
JUDGMENTS_BY_GRAIN: dict[str, tuple[str, ...]] = {
    "verdict": ("agree", "wrong_verdict", "wrong_reason", "unreadable", "missing_call"),
    "atom": ("signal", "restatement", "noise", "artifact"),
    "precedence": ("a_beats_b", "b_beats_a", "tie"),
}
GRAINS: tuple[str, ...] = tuple(JUDGMENTS_BY_GRAIN)
ALL_JUDGMENTS: tuple[str, ...] = tuple(sorted({j for v in JUDGMENTS_BY_GRAIN.values() for j in v}))
MEASUREDNESS: tuple[str, ...] = ("measured", "partial", "blind", "unknown")

# How the row was CHOSEN. Without this, an agreement rate has no denominator: rows filed while
# hunting a known defect are selected ON being wrong, so their agreement is ~0 by construction and
# says nothing about the framework. Default is `targeted` — the pessimistic reading — because a row
# whose selection was not recorded cannot be assumed to have come from a frame.
SELECTION: tuple[str, ...] = ("targeted", "sampled", "replicate_probe")
RATEABLE_SELECTION: tuple[str, ...] = ("sampled",)

# Judgments that assert the framework was RIGHT, per grain. Used by loop_health; kept here so the
# vocabulary and its polarity live in one place and cannot drift apart.
CORRECT_BY_GRAIN: dict[str, tuple[str, ...]] = {
    "verdict": ("agree",),
    "atom": ("signal",),
    "precedence": (),  # a preference is not a correctness claim — it has no "right" pole
}

_REQUIRED = ("grain", "judgment", "skill", "target", "indication", "axis")


class DispositionError(ValueError):
    """A row that cannot be filed: unknown vocabulary token, missing address, or grain mismatch."""


class AppendOnlyViolation(RuntimeError):
    """The ledger's existing bytes changed. Rows are evidence — they are appended, never rewritten."""


def fact_key(row: dict) -> str:
    """The join key, using the SAME `|` convention as loop_dispositions.yaml's row keys.

    `SKILL|TARGET|INDICATION|AXIS|GRAIN`. The legacy YAML's 5th slot is a gap_class; ours is the
    grain. Both are "what kind of claim is this about", so the shapes line up for a join without
    either side pretending to be the other.
    """
    return "|".join(str(row.get(f) or "?") for f in ("skill", "target", "indication", "axis", "grain"))


def validate_row(row: dict) -> dict:
    """Return a normalized row, or raise DispositionError. Rejects — never coerces — unknown tokens.

    Coercing an unrecognized judgment to a default is how a vocabulary silently grows a synonym and
    a count becomes a lie, so every unknown token is a hard failure at the write boundary.
    """
    if not isinstance(row, dict):
        raise DispositionError(f"row must be a dict, got {type(row).__name__}")
    missing = [f for f in _REQUIRED if not row.get(f)]
    if missing:
        raise DispositionError(f"missing required field(s): {missing}")

    grain = row["grain"]
    if grain not in JUDGMENTS_BY_GRAIN:
        raise DispositionError(f"unknown grain {grain!r}; known: {GRAINS}")
    judgment = row["judgment"]
    legal = JUDGMENTS_BY_GRAIN[grain]
    if judgment not in legal:
        extra = ""
        if judgment in ALL_JUDGMENTS:
            extra = f" ({judgment!r} is a real judgment, but not for grain {grain!r})"
        raise DispositionError(f"judgment {judgment!r} is not legal for grain {grain!r}{extra}; legal: {legal}")

    measuredness = row.get("measuredness") or "unknown"
    if measuredness not in MEASUREDNESS:
        raise DispositionError(f"unknown measuredness {measuredness!r}; known: {MEASUREDNESS}")

    selection = row.get("selection") or "targeted"
    if selection not in SELECTION:
        raise DispositionError(f"unknown selection {selection!r}; known: {SELECTION}")

    if grain == "precedence" and judgment in ("a_beats_b", "b_beats_a"):
        if not (row.get("rule_id") and row.get("loser_rule_id")):
            raise DispositionError("a precedence judgment needs both rule_id and loser_rule_id")
        if row["rule_id"] == row["loser_rule_id"]:
            raise DispositionError("rule_id and loser_rule_id are the same rule")

    out: dict[str, Any] = {
        "schema": SCHEMA,
        "ts": row.get("ts") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rater": row.get("rater") or os.environ.get("USER") or "unknown",
        "grain": grain,
        "judgment": judgment,
        "skill": row["skill"],
        "target": row["target"],
        "indication": row["indication"],
        "axis": row["axis"],
        "measuredness": measuredness,
        "selection": selection,
        "is_replicate": bool(row.get("is_replicate")),
        "note": (row.get("note") or "").strip(),
    }
    for opt in ("card_id", "field", "rule_id", "loser_rule_id", "run"):
        if row.get(opt):
            out[opt] = row[opt]
    out["key"] = fact_key(out)
    return out


GENESIS = "genesis"


_CHAIN_FIELDS = ("prev", "content_sha")


def _digest(line: str) -> str:
    """Short sha256 of one serialized row, used to chain rows to their predecessor."""
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()[:16]


def content_sha(rec: dict) -> str:
    """Digest of a row's CONTENT — everything except the two chain fields.

    SCOPE OF WHAT THIS PROVES, stated precisely because an earlier version of this docstring
    overclaimed: `content_sha` is an UNKEYED digest stored in the same file as the data it covers, so
    anyone editing a row can recompute it for free. It therefore catches *careless* corruption — a
    hand edit, a bad merge resolution, a truncated write — and it does NOT catch a deliberate rewrite.

    It is not worthless, though, and the bound is worth knowing exactly: `prev` binds FORWARD, so
    rewriting row i also invalidates row i+1's link. Recomputing row i's digest therefore does not
    save an interior edit — `verify_chain` still fires on the next row. What is unbound in-file is the
    TAIL row, which nothing points at. So the in-file layer covers all but the last row, and the last
    row is covered only by git. Both halves of that are pinned:
    `test_an_INTERIOR_relabel_is_caught_by_the_chain_alone` and
    `test_git_anchor_CATCHES_a_TAIL_relabel_that_recomputes_its_own_digest`.

    **No hash stored inside a file can bind that file's own content.** The only real anchor is
    external: see `verify_provenance`, which compares against what git already has committed. Do not
    read this function as tamper-proofing.
    """
    body = {k: v for k, v in rec.items() if k not in _CHAIN_FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


class ProvenanceGap(RuntimeError):
    """A row that git has committed is missing from the working file. The only non-forgeable check."""


def git_head_rows(path: str | Path) -> list[dict] | None:
    """The ledger's rows as of `HEAD`, or None when git cannot answer (untracked file, no repo).

    Returns None rather than an empty list for "no answer", because those mean opposite things: an
    empty list would assert git has no rows, which would make the provenance check vacuously pass.
    """
    p = Path(path).resolve()
    try:
        top = subprocess.run(
            ["git", "-C", str(p.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if top.returncode != 0:
            return None
        rel = p.relative_to(Path(top.stdout.strip()).resolve())
        blob = subprocess.run(
            ["git", "-C", str(p.parent), "show", f"HEAD:{rel.as_posix()}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if blob.returncode != 0:  # not committed yet — nothing to anchor against
            return None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    out = []
    for ln in blob.stdout.splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                return None
    return out


def verify_provenance(path: str | Path = DEFAULT_LEDGER) -> dict:
    """Assert every judgment git has already committed is STILL in the working file.

    This is the only check here that a determined editor cannot defeat, and the reason is that it does
    not live in the file. `content_sha` and `prev` are both stored alongside the data they cover, so
    both can be recomputed by anyone with an editor; git's object store cannot, short of rewriting
    pushed history where other people would see it.

    One invariant catches BOTH attacks the in-file checks miss:
      - a RELABELLED row changes its content, so its committed `content_sha` goes missing;
      - a DELETED row's `content_sha` goes missing too.
    Reordering is permitted, because a git merge legitimately reorders (see `rechain`).

    Returns a status dict. `anchored: False` means git could not answer — reported honestly rather
    than passing quietly, since an unanchored check is not a passing check.
    """
    head = git_head_rows(path)
    if head is None:
        return {"anchored": False, "reason": "not committed to git yet, or not a git repo", "n_head": 0}
    have = {r.get("content_sha") for r in load(path, strict=False)}
    missing = [r for r in head if r.get("content_sha") not in have]
    if missing:
        lost = [f"{r.get('key')}={r.get('judgment')}" for r in missing]
        raise ProvenanceGap(
            f"{Path(path).name}: {len(missing)} judgment(s) committed in git are GONE from the working "
            f"file: {lost}. A filed judgment is evidence; it is not editable or prunable. If a row was "
            f"filed in error, append a correcting row — do not remove the original."
        )
    return {"anchored": True, "n_head": len(head), "n_working": len(have)}


def append_row(row: dict, path: str | Path = DEFAULT_LEDGER) -> dict:
    """Validate and append ONE row, chained to the digest of the line before it.

    The chain is what makes "append-only" a property rather than a promise. Without it, an edit to
    row 1 is indistinguishable at read time from row 1 always having said that — and in a ledger
    whose entire purpose is to be the only truth signal in the system, silently editable history is
    worse than no history, because it still reads as evidence.
    """
    rec = validate_row(row)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Read-prev-and-append must be ONE critical section. Without the lock, two reviewers appending at
    # once both read the same `prev`, and the loser's row lands on disk with a stale chain link — after
    # which a post-write check can only report corruption it already created. Worse, the CLI would
    # print REFUSED for a row that IS filed, so the reviewer re-files it and the ledger gains a
    # duplicate on top of a broken chain. Detection after the write is a post-mortem, not a guard.
    with p.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            before = fh.read()
            if before and not before.endswith("\n"):
                raise AppendOnlyViolation(f"{p} does not end in a newline — torn write; refusing to append")
            prior = [ln for ln in before.splitlines() if ln.strip()]
            rec["content_sha"] = content_sha(rec)
            rec["prev"] = _digest(prior[-1]) if prior else GENESIS
            line = json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n"
            fh.seek(0, os.SEEK_END)
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return rec


def verify_chain(path: str | Path = DEFAULT_LEDGER) -> int:
    """Walk the `prev` chain. Raises AppendOnlyViolation naming the FIRST line that was rewritten.

    Returns the number of rows verified.
    """
    p = Path(path)
    if not p.exists():
        return 0
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    expected = GENESIS
    for i, raw in enumerate(lines, 1):
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AppendOnlyViolation(f"{p.name}:{i} is not valid JSON: {exc}") from exc
        want_content = content_sha(rec)
        if rec.get("content_sha") != want_content:
            raise AppendOnlyViolation(
                f"{p.name}:{i} content was REWRITTEN after filing: content_sha={rec.get('content_sha')!r}, "
                f"recomputes to {want_content!r}. A re-chain cannot clear this — the row's own content "
                f"is bound independently of its position."
            )
        got = rec.get("prev")
        if got != expected:
            raise AppendOnlyViolation(
                f"{p.name}:{i} breaks the append-only chain: prev={got!r}, expected {expected!r}. "
                f"Line {i - 1 if i > 1 else i} was rewritten or removed after it was filed."
            )
        expected = _digest(raw)
    return len(lines)


def rechain(path: str | Path = DEFAULT_LEDGER, *, dry_run: bool = True) -> list[int]:
    """Recompute `prev` after a GIT MERGE interleaved two branches' appends. Content is never touched.

    Why this has to exist: the ledger is committed, so two reviewers appending on two branches produce
    a conflict whose honest resolution is "keep both hunks" — and that reorders rows, which breaks the
    chain by construction. Without a sanctioned repair, the first person to hit it hand-edits a `prev`
    field, which is precisely the silent rewrite the chain was added to detect. So the repair is
    explicit, visible in a PR diff, and refuses to run on rows it cannot validate.

    Returns the 1-indexed line numbers whose BYTES change (not merely those whose `prev` differed —
    re-serialization can rewrite a hand-edited line too, and a repair tool whose printed scope is
    narrower than its written scope invites a reviewer to skim). `dry_run=True` reports without writing.

    It re-chains ONLY, and it enforces that against git rather than against itself: the multiset of
    `content_sha` values committed at HEAD must still be present. A reorder passes; a relabel or a
    deletion does not. Checking each row against its own recomputed digest — which is what an earlier
    version did — proves nothing, because the digest is unkeyed and recomputing it is free.
    """
    p = Path(path)
    if not p.exists():
        return []
    raw_lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    recs = []
    for i, raw in enumerate(raw_lines, 1):
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DispositionError(f"{p}:{i} is not valid JSON; fix the conflict markers first: {exc}") from exc
        try:
            validate_row(rec)
        except DispositionError as exc:
            raise DispositionError(f"{p}:{i} {exc}; refusing to re-chain an invalid ledger") from exc
        want = content_sha(rec)
        if rec.get("content_sha") != want:
            raise DispositionError(
                f"{p}:{i} content_sha={rec.get('content_sha')!r} but content recomputes to {want!r} — "
                f"this row's content changed without its digest being updated. Refusing: --rechain "
                f"repairs row ORDER, it is not a way to relabel a filed judgment."
            )
        recs.append(rec)

    # THE check that has teeth. Everything above can be satisfied by an editor who recomputes the
    # digests; git cannot. A merge may reorder rows, so the invariant is multiset-preservation, not
    # prefix-equality: same content_sha values, none added, none removed, none altered.
    head = git_head_rows(p)
    if head is not None:
        have = collections.Counter(r.get("content_sha") for r in recs)
        want_counts = collections.Counter(r.get("content_sha") for r in head)
        gone = [sha for sha, n in want_counts.items() if have[sha] < n]
        if gone:
            lost = [f"{r.get('key')}={r.get('judgment')}" for r in head if r.get("content_sha") in gone]
            raise ProvenanceGap(
                f"{p.name}: refusing to re-chain — {len(gone)} judgment(s) committed in git are missing "
                f"from the file: {lost}. --rechain reorders rows; it does not relabel or drop them. If a "
                f"judgment was filed in error, append a correcting row."
            )

    prev_changed: list[int] = []
    out_lines: list[str] = []
    expected = GENESIS
    for i, rec in enumerate(recs, 1):
        if rec.get("prev") != expected:
            prev_changed.append(i)
        rec["prev"] = expected
        line = json.dumps(rec, sort_keys=True, separators=(",", ":"))
        out_lines.append(line)
        expected = _digest(line)

    # Report every line whose BYTES move, which is a superset of prev_changed once re-serialization is
    # in play. Understating this is how a reviewer reads "line 3" and skims a three-line diff.
    changed = [i for i, (old, new) in enumerate(zip(raw_lines, out_lines), 1) if old.strip() != new]
    changed += list(range(len(raw_lines) + 1, len(out_lines) + 1))
    if changed and not dry_run:
        p.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return changed


def load(path: str | Path = DEFAULT_LEDGER, *, strict: bool = True) -> list[dict]:
    """Read the ledger. `strict` re-validates every row AND verifies the chain.

    A hand edit therefore cannot smuggle in an unknown token (validation) or silently revise a filed
    judgment (chain) — the two ways a ledger stops being evidence.
    """
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict] = []
    for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DispositionError(f"{p}:{i} is not valid JSON: {exc}") from exc
        if strict:
            try:
                validate_row(rec)
            except DispositionError as exc:
                raise DispositionError(f"{p}:{i} {exc}") from exc
        rows.append(rec)
    if strict:
        verify_chain(p)
    return rows


def resolve_run_context(run_path: str | Path) -> dict:
    """Read the run's OWN provenance so the reviewer types a judgment, not metadata.

    Returns only fields actually found — never a placeholder. Pins on `skills_repo_sha` /
    `resolved_content_digest` rather than a version string, because a version does not move when a
    corpus does (the atlas re-freeze keeps `feature_schema_version` at 2.0.0 across a 213→297-target
    corpus change; only the sha distinguishes them).
    """
    p = Path(run_path).expanduser().resolve()
    ctx: dict[str, Any] = {"path": str(p)}
    if not p.exists():
        return ctx

    prov = p / "provenance.yaml"
    if prov.exists():
        try:
            import yaml  # type: ignore

            doc = yaml.safe_load(prov.read_text()) or {}
        except Exception:  # noqa: BLE001 — a malformed provenance must not block capture
            doc = {}
        for k in ("skill", "skill_version", "target", "indication", "generated_at"):
            if doc.get(k):
                ctx[k] = doc[k]
        gov = doc.get("governance") or {}
        for k in ("skills_repo_sha", "data_mode", "resolved_release_digest", "resolved_content_digest"):
            if gov.get(k):
                ctx[k] = gov[k]

    for name in ("decision.json", "nomination.json", "evidence_package.json"):
        f = p / name
        if not f.exists():
            continue
        try:
            doc = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        for k in ("skill", "target", "indication", "generated_at"):
            if doc.get(k) and k not in ctx:
                ctx[k] = doc[k]
        gov = doc.get("provenance") or {}
        for k in ("skills_repo_sha", "data_mode", "resolved_release_digest", "resolved_content_digest"):
            if gov.get(k) and k not in ctx:
                ctx[k] = gov[k]
        break
    return ctx


def summarize(rows: Iterable[dict]) -> dict:
    """Counts the ledger can support today. Deliberately NOT a precision scalar over everything.

    Per-grain only: `verdict` agreement and `atom` usefulness are different questions, and a
    `precedence` preference has no correctness pole at all. One pooled number would hide all three.
    """
    rows = list(rows)
    by_grain: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_axis: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_measuredness: collections.Counter = collections.Counter()
    by_selection: collections.Counter = collections.Counter()
    raters: collections.Counter = collections.Counter()
    for r in rows:
        by_grain[r.get("grain", "?")][r.get("judgment", "?")] += 1
        by_axis[r.get("axis", "?")][r.get("judgment", "?")] += 1
        by_measuredness[r.get("measuredness", "unknown")] += 1
        by_selection[r.get("selection", "targeted")] += 1
        raters[r.get("rater", "unknown")] += 1

    def _rates(subset: list[dict]) -> dict[str, Any]:
        grouped: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for r in subset:
            grouped[r.get("grain", "?")][r.get("judgment", "?")] += 1
        out: dict[str, Any] = {}
        for grain, counter in grouped.items():
            n = sum(counter.values())
            good = CORRECT_BY_GRAIN.get(grain, ())
            if not good or not n:
                out[grain] = {"n": n, "agreement": None}
                continue
            out[grain] = {"n": n, "agreement": round(sum(counter.get(g, 0) for g in good) / n, 3)}
        return out

    # There is deliberately NO pooled agreement figure. An earlier version emitted one under
    # `per_grain_agreement`, which on a 3-row defect hunt stated "the framework agrees 0.0% of the
    # time" as the most authoritative-looking key in the file — manufacturing exactly the artefact the
    # module docstring says pooling would manufacture. A warning elsewhere does not fix a name: a name
    # is the only part of this that survives being pasted into a slide. So the all-rows view reports
    # COUNTS only, and the sole ratio in the output is the one computed over a real frame.
    sampled = [r for r in rows if r.get("selection", "targeted") in RATEABLE_SELECTION]
    filed_counts = {
        grain: {"n": sum(c.values()), "n_correct": sum(c.get(g, 0) for g in CORRECT_BY_GRAIN.get(grain, ()))}
        for grain, c in sorted(by_grain.items())
    }

    # Intra-rater self-agreement over replicate rows: the same fact judged twice by the same rater.
    # Without this a comparator cannot tell a real preference from reviewer noise, and its CV score
    # would be reported against an unknown ceiling.
    judged: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for r in rows:
        judged[(r.get("rater", "unknown"), r.get("key", "?"))].append(r.get("judgment", "?"))
    repeated = {k: v for k, v in judged.items() if len(v) > 1}
    consistent = sum(1 for v in repeated.values() if len(set(v)) == 1)

    return {
        "n": len(rows),
        "n_replicate_rows": sum(1 for r in rows if r.get("is_replicate")),
        "by_grain": {g: dict(c) for g, c in sorted(by_grain.items())},
        # Counts, not a rate — see the comment above. The word "agreement" appears in exactly one key.
        "per_grain_filed_counts_all_selections": filed_counts,
        "n_sampled": len(sampled),
        "per_grain_agreement_sampled": _rates(sampled),
        "by_axis": {a: dict(c) for a, c in sorted(by_axis.items())},
        "by_measuredness": dict(by_measuredness),
        "by_selection": dict(by_selection),
        "raters": dict(raters),
        "n_repeated_facts": len(repeated),
        "intra_rater_consistent": consistent,
        "intra_rater_agreement": (round(consistent / len(repeated), 3) if repeated else None),
        "unknown_judgment": sorted(
            {
                r.get("judgment", "?")
                for r in rows
                if r.get("judgment") not in JUDGMENTS_BY_GRAIN.get(r.get("grain", ""), ())
            }
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Append one reviewer judgment to eval/dispositions.jsonl, or summarize the ledger.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--summary", action="store_true", help="print the ledger summary and exit")
    ap.add_argument("--verify", action="store_true", help="verify the append-only chain and exit")
    ap.add_argument(
        "--rechain",
        action="store_true",
        help="recompute `prev` after a git merge interleaved two branches' appends (content untouched)",
    )
    ap.add_argument("--apply", action="store_true", help="with --rechain, actually write (default: dry run)")
    ap.add_argument("--run", help="a run dir under ~/dev/framework-runs/; fills skill/target/indication + sha")
    ap.add_argument("--grain", choices=GRAINS)
    ap.add_argument("--judgment", help=f"one of {ALL_JUDGMENTS} (must be legal for --grain)")
    ap.add_argument("--skill")
    ap.add_argument("--target")
    ap.add_argument("--indication")
    ap.add_argument("--axis")
    ap.add_argument("--measuredness", choices=MEASUREDNESS, default=None)
    ap.add_argument(
        "--selection",
        choices=SELECTION,
        default=None,
        help="how this row was chosen; only `sampled` rows can be quoted as a rate (default targeted)",
    )
    ap.add_argument("--card-id", dest="card_id")
    ap.add_argument("--field")
    ap.add_argument("--rule-id", dest="rule_id")
    ap.add_argument("--loser-rule-id", dest="loser_rule_id")
    ap.add_argument("--rater", default=None)
    ap.add_argument("--note", default="")
    ap.add_argument("--replicate", action="store_true", help="a deliberate re-judgment of a fact already filed")
    a = ap.parse_args(argv)

    if a.verify:
        try:
            n = verify_chain(a.ledger)
        except AppendOnlyViolation as exc:
            print(f"[dispositions] CHAIN BROKEN: {exc}", file=sys.stderr)
            print("[dispositions] if this was a git merge, run --rechain (dry) then --rechain --apply", file=sys.stderr)
            return 2
        # The in-file chain only proves internal consistency; the git anchor is the real check.
        try:
            prov = verify_provenance(a.ledger)
        except ProvenanceGap as exc:
            print(f"[dispositions] PROVENANCE GAP: {exc}", file=sys.stderr)
            return 2
        if prov["anchored"]:
            print(f"[dispositions] chain OK, {n} row(s); git-anchored ({prov['n_head']} committed row(s) all present)")
        else:
            print(
                f"[dispositions] chain OK, {n} row(s); NOT git-anchored ({prov['reason']}) — "
                f"the in-file digests prove internal consistency only, not that nothing was rewritten"
            )
        return 0

    if a.rechain:
        try:
            changed = rechain(a.ledger, dry_run=not a.apply)
        except (DispositionError, ProvenanceGap) as exc:
            # ProvenanceGap is a RuntimeError, so it does NOT fall under DispositionError. Catching only
            # the latter would make the git refusal — the one check that stops this tool from becoming an
            # eraser — surface as a traceback, which reads like a broken tool rather than a refused edit.
            print(f"[dispositions] REFUSED: {exc}", file=sys.stderr)
            return 2
        if not changed:
            print("[dispositions] chain already consistent, nothing to re-chain")
            return 0
        verb = "re-chained" if a.apply else "would re-chain (dry run; pass --apply)"
        print(f"[dispositions] {verb} line(s) {changed} — content unchanged, only `prev` recomputed")
        return 0

    if a.summary:
        # Load NON-strict on purpose. A strict load raises on the first illegal token, so
        # `unknown_judgment` could never populate on the only path anyone actually runs — a field that
        # looks like a detector and cannot fire. Here it reports instead, and the chain/provenance
        # status is carried alongside so a compromised ledger is never summarized as if it were clean.
        s = summarize(load(a.ledger, strict=False))
        try:
            verify_chain(a.ledger)
            s["chain"] = "ok"
        except AppendOnlyViolation as exc:
            s["chain"] = f"BROKEN: {exc}"
        try:
            s["provenance"] = verify_provenance(a.ledger)
        except ProvenanceGap as exc:
            s["provenance"] = {"anchored": True, "gap": str(exc)}
        print(json.dumps(s, indent=2, sort_keys=True))
        bad = s["chain"] != "ok" or "gap" in s.get("provenance", {}) or s["unknown_judgment"]
        return 2 if bad else 0

    if not (a.grain and a.judgment):
        ap.error("--grain and --judgment are required unless --summary/--verify/--rechain")

    row: dict[str, Any] = {
        "grain": a.grain,
        "judgment": a.judgment,
        "skill": a.skill,
        "target": a.target,
        "indication": a.indication,
        "axis": a.axis,
        "measuredness": a.measuredness,
        "selection": a.selection,
        "rater": a.rater,
        "note": a.note,
        "is_replicate": a.replicate,
        "card_id": a.card_id,
        "field": a.field,
        "rule_id": a.rule_id,
        "loser_rule_id": a.loser_rule_id,
    }
    if a.run:
        ctx = resolve_run_context(a.run)
        row["run"] = ctx
        for k in ("skill", "target", "indication"):
            if not row.get(k) and ctx.get(k):
                row[k] = ctx[k]

    try:
        rec = append_row(row, a.ledger)
    except (DispositionError, AppendOnlyViolation) as exc:
        print(f"[dispositions] REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"[dispositions] +1 {rec['grain']}/{rec['judgment']} {rec['key']} → {a.ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
