#!/usr/bin/env python3
"""eval/loop/compile_findings.py — the subskill-loop CROSS-RUN findings compiler + issue emitter (SK#2303
follow-on to the adversarial-verify stage #2431).

A read-only pass over the committed ``iterations/<skill>/<iter>/iteration_report.json`` files that
compiles every run's tier-routed findings into ONE ranked, deduplicated log, then (opt-in) emits GitHub
issues from the issue-worthy rows — idempotently.

Why this is a separate pass (not part of ``iterate``): the loop is run skill-by-skill, pair-by-pair, and
each run is an expensive LLM pass whose record is already durable (the committed report). Compilation is
pure aggregation over those records — so you run loops whenever, then compile/emit on demand over any
subset, without re-running a single LLM call.

THE ISSUE UNIT is a RECURRING STRUCTURAL FINDING, not a single (gene, indication) hit. The same gap
recurs across pairs (e.g. `paralog_buffering not folded into L2b` on KRAS and EGFR). So findings are
deduplicated on their STRUCTURAL SIGNATURE — ``sha(skill | kind | sorted datum_ref shape)`` — and the
pairs that exhibited it are carried as the finding's EVIDENCE (and its recurrence is a ranking signal).
This serves "fix the pattern, not the instance."

ISSUE BAR (what becomes an issue vs log-only): adversary-SURVIVORS in tiers T2/T3. A finding the
adversarial critic KILLED stays in the log (with its kill reason — an audit trail for the critic) but is
NOT an issue candidate. T1 never routes under STOP-A anyway.

EMIT is two-phase: ``compile`` always writes a durable digest (JSON + Markdown); ``--open`` is a separate
opt-in step that files/updates GitHub issues, deduped on a stable fingerprint marker embedded in each
issue body (``<!-- loop-finding-fp: <fp> -->``) so a re-sweep UPDATES (a comment) rather than DUPLICATES.
The GH backend is INJECTABLE so the emit logic is unit-tested with no live ``gh``.

PROPOSE-ONLY: writes a digest + (opt-in) issues/comments for human adjudication; never a card/rule/method
change, never a verdict. Indexes on the property-layer findings the loop already produced — it adds no new
judgement.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

SCHEMA_VERSION = "1.0"

# tier labels as the report writes them (eval/loop/tiers.py T1/T2/T3).
T1, T2, T3 = "T1_land", "T2_propose", "T3_adjudicate"
_ISSUE_TIERS = (T2, T3)  # issue bar: T2 propose + T3 adjudicate (T1 never routes under STOP-A)

_FP_MARKER = "loop-finding-fp:"  # hidden body marker the --open dedup searches on
_ISSUE_LABEL = "subskill-loop-finding"


# ── signature + fingerprint ───────────────────────────────────────────────────────────────────────────
def datum_shape(datum_refs: "list | None") -> tuple:
    """The target-INDEPENDENT shape of a finding's datum_refs: the field PATHS (which are already gene/
    indication-independent — ``l2a.crispr_essentiality.anchors.median_chronos_panel`` names a field, not a
    value), lower-cased, de-duplicated and sorted. Two findings proposing the same structural change against
    the same fields on different pairs share a shape."""
    out = set()
    for r in datum_refs or []:
        if isinstance(r, str) and r.strip():
            out.add(r.strip().lower())
    return tuple(sorted(out))


def signature(skill: str, kind: "str | None", datum_refs: "list | None") -> str:
    """Structural signature of a finding: sha256(skill | kind | datum-shape)[:12]. The dedup key for an
    ISSUE — findings sharing it are the SAME structural gap seen on (possibly) different pairs."""
    basis = json.dumps([skill or "", kind or "", list(datum_shape(datum_refs))], sort_keys=True)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


# ── report reading ────────────────────────────────────────────────────────────────────────────────────
def iter_report_paths(iterations_root: "Path | str", skill: "str | None" = None) -> "list[Path]":
    """Every ``iteration_report.json`` under ``iterations_root`` (optionally filtered to one skill dir),
    sorted for determinism."""
    root = Path(iterations_root)
    pattern = f"{skill}/*/iteration_report.json" if skill else "*/*/iteration_report.json"
    return sorted(root.glob(pattern))


def _sha_of(run_dir: "str | None") -> "str | None":
    """The trunk SHA a run was emitted at — the trailing token of the run_dir name (iter-<tag>-<sha>)."""
    if not run_dir:
        return None
    return Path(run_dir).name.rsplit("-", 1)[-1] or None


@dataclass
class RunRecord:
    """One iteration_report rolled up to its headline metadata (the 'log of runs')."""

    skill: str
    iteration_id: str
    sha: "str | None"
    generated_at: "str | None"
    teeth_green: bool
    roster: dict
    tiers: dict
    adversary: dict
    convergence_converged: "bool | None"
    ledger_chain_ok: "bool | None"
    report_path: str


def _finding_instances(report: dict, report_path: Path) -> "list[dict]":
    """Flatten a report's DEV tier_report into per-finding instance rows, each carrying its run provenance
    + the (gene, indication) source pair (from the finding's ``_source`` stamp, when present)."""
    skill = report.get("skill") or "?"
    iter_id = report.get("iteration_id") or "?"
    sha = _sha_of(report.get("run_dir"))
    tr = ((report.get("dev") or {}).get("tier_report")) or {}
    rows: list[dict] = []
    for tier in (T1, T2, T3):
        for f in tr.get(tier) or []:
            if not isinstance(f, dict):
                continue
            src = f.get("_source") or {}
            adv = f.get("_adversary") or {}
            rows.append(
                {
                    "skill": skill,
                    "iteration_id": iter_id,
                    "sha": sha,
                    "report_path": str(report_path),
                    "tier": tier,
                    "kind": f.get("kind"),
                    "target": f.get("target"),
                    "finding": f.get("finding"),
                    "why": f.get("why"),
                    "datum_refs": f.get("datum_refs") or [],
                    "severity": (f.get("_tier") or {}).get("severity") or f.get("severity"),
                    "frozen_symbol": (f.get("_tier") or {}).get("frozen_symbol"),
                    "pair_target": src.get("target"),
                    "pair_indication": src.get("indication"),
                    "candidate_key": src.get("candidate_key"),
                    "adversary_verdict": adv.get("verdict"),
                    "adversary_failure_mode": adv.get("failure_mode"),
                    "adversary_reason": adv.get("reason"),
                    "signature": signature(skill, f.get("kind"), f.get("datum_refs")),
                }
            )
    return rows


@dataclass
class IssueCandidate:
    """A deduplicated recurring structural finding = one issue candidate (survivors) or log row."""

    signature: str
    skill: str
    kind: "str | None"
    tiers: list = field(default_factory=list)  # distinct tiers seen
    max_tier: str = T2
    severities: list = field(default_factory=list)
    datum_refs: list = field(default_factory=list)
    representative_finding: str = ""
    representative_why: str = ""
    frozen_symbol: "str | None" = None
    pairs: list = field(default_factory=list)  # [{target, indication, iteration_id, sha, tier}]
    adversary: dict = field(default_factory=dict)  # {n_survived, n_killed, reasons:[...]}
    issue_eligible: bool = False

    def to_jsonable(self) -> dict:
        return {
            "signature": self.signature,
            "skill": self.skill,
            "kind": self.kind,
            "tiers": self.tiers,
            "max_tier": self.max_tier,
            "severities": self.severities,
            "datum_refs": self.datum_refs,
            "representative_finding": self.representative_finding,
            "representative_why": self.representative_why,
            "frozen_symbol": self.frozen_symbol,
            "n_pairs": len(self.pairs),
            "pairs": self.pairs,
            "adversary": self.adversary,
            "issue_eligible": self.issue_eligible,
        }


_TIER_RANK = {T1: 0, T2: 1, T3: 2}


def _group_findings(instances: "list[dict]") -> "list[IssueCandidate]":
    """Group per-finding instances by structural signature into issue candidates; the ISSUE BAR
    (adversary-survivor in T2/T3) sets ``issue_eligible``."""
    groups: dict[str, IssueCandidate] = {}
    for row in instances:
        sig = row["signature"]
        g = groups.get(sig)
        if g is None:
            g = IssueCandidate(signature=sig, skill=row["skill"], kind=row["kind"])
            groups[sig] = g
        tier = row["tier"]
        if tier not in g.tiers:
            g.tiers.append(tier)
        if _TIER_RANK.get(tier, 0) >= _TIER_RANK.get(g.max_tier, 0):
            g.max_tier = tier
            g.representative_finding = row["finding"] or g.representative_finding
            g.representative_why = row["why"] or g.representative_why
            g.datum_refs = row["datum_refs"] or g.datum_refs
            g.frozen_symbol = row["frozen_symbol"] or g.frozen_symbol
        if row["severity"] and row["severity"] not in g.severities:
            g.severities.append(row["severity"])
        g.pairs.append(
            {
                "target": row["pair_target"],
                "indication": row["pair_indication"],
                "iteration_id": row["iteration_id"],
                "sha": row["sha"],
                "tier": tier,
                "adversary_verdict": row["adversary_verdict"],
            }
        )
        adv = g.adversary
        adv.setdefault("n_survived", 0)
        adv.setdefault("n_killed", 0)
        adv.setdefault("kill_reasons", [])
        if row["adversary_verdict"] == "killed":
            adv["n_killed"] += 1
            if row["adversary_reason"]:
                adv["kill_reasons"].append(row["adversary_reason"])
        elif row["adversary_verdict"] == "survives":
            adv["n_survived"] += 1
    # Issue bar: at least one SURVIVING instance (not every instance killed), max tier in T2/T3.
    for g in groups.values():
        survived_somewhere = g.adversary.get("n_survived", 0) > 0 or (
            # if the critic never ran (verdict None everywhere), treat as not-killed → eligible
            g.adversary.get("n_survived", 0) == 0 and g.adversary.get("n_killed", 0) == 0
        )
        g.issue_eligible = survived_somewhere and g.max_tier in _ISSUE_TIERS
    return list(groups.values())


def _rank_key(g: IssueCandidate):
    """Rank: adjudication (T3) above propose (T2); then by recurrence (pairs); then worst severity."""
    sev_rank = {"S1": 3, "S2": 2, "S3": 1}
    worst_sev = max((sev_rank.get(s, 0) for s in g.severities), default=0)
    return (_TIER_RANK.get(g.max_tier, 0), len(g.pairs), worst_sev)


def compile_sweep(
    iterations_root: "Path | str",
    skill: "str | None" = None,
    iters: "Optional[Iterable[str]]" = None,
    since: "str | None" = None,
) -> dict:
    """Read every (filtered) iteration_report under ``iterations_root`` → the sweep digest:
    ``runs`` (the log of runs) + ``findings`` (ranked, deduplicated issue candidates / log rows).

    ``iters`` restricts to specific ``iteration_id``s (so a real ``--open`` can be scoped to one fresh,
    pair-attributed run — e.g. not the older un-attributed samples); ``since`` keeps only runs whose
    ``generated_at`` is lexicographically >= the given ISO timestamp (ISO-8601 UTC sorts as a string)."""
    paths = iter_report_paths(iterations_root, skill=skill)
    iters_set = set(iters) if iters else None
    runs: list[dict] = []
    instances: list[dict] = []
    for p in paths:
        try:
            report = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if iters_set is not None and (report.get("iteration_id") or "") not in iters_set:
            continue
        if since and (report.get("generated_at") or "") < since:
            continue
        dev = report.get("dev") or {}
        runs.append(
            RunRecord(
                skill=report.get("skill") or "?",
                iteration_id=report.get("iteration_id") or "?",
                sha=_sha_of(report.get("run_dir")),
                generated_at=report.get("generated_at"),
                teeth_green=bool(report.get("teeth_green")),
                roster=report.get("roster") or {},
                tiers=dev.get("tiers") or {},
                adversary=dev.get("adversary") or {},
                convergence_converged=((report.get("held_out") or {}).get("convergence") or {}).get("converged"),
                ledger_chain_ok=(report.get("ledger") or {}).get("chain_ok"),
                report_path=str(p),
            ).__dict__
        )
        instances.extend(_finding_instances(report, p))
    groups = _group_findings(instances)
    groups.sort(key=_rank_key, reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "iterations_root": str(iterations_root),
        "skill_filter": skill,
        "n_runs": len(runs),
        "n_instances": len(instances),
        "n_findings_unique": len(groups),
        "n_issue_candidates": sum(1 for g in groups if g.issue_eligible),
        "runs": runs,
        "findings": [g.to_jsonable() for g in groups],
    }


# ── digest rendering ──────────────────────────────────────────────────────────────────────────────────
def render_markdown(digest: dict) -> str:
    lines = [
        "# Subskill-loop findings digest",
        "",
        f"- runs compiled: **{digest['n_runs']}**  ·  finding instances: **{digest['n_instances']}**  ·  "
        f"unique structural findings: **{digest['n_findings_unique']}**  ·  "
        f"issue candidates (survivor, T2/T3): **{digest['n_issue_candidates']}**",
        "",
        "## Runs",
        "",
        "| skill | iter | sha | tiers (T2/T3) | adv killed/surv | converged | chain_ok |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in digest["runs"]:
        t = r["tiers"]
        a = r["adversary"]
        lines.append(
            f"| {r['skill']} | {r['iteration_id']} | {(r['sha'] or '')[:8]} | "
            f"{t.get('T2_propose', 0)}/{t.get('T3_adjudicate', 0)} | "
            f"{a.get('n_killed', '-')}/{a.get('n_survived', '-')} | {r['convergence_converged']} | {r['ledger_chain_ok']} |"
        )
    lines += ["", "## Issue candidates (ranked)", ""]
    cands = [g for g in digest["findings"] if g["issue_eligible"]]
    if not cands:
        lines.append("_none_")
    for i, g in enumerate(cands, 1):
        pairs = ", ".join(f"{p['target']}/{p['indication']}" for p in g["pairs"] if p.get("target")) or "(unattributed)"
        lines += [
            f"### {i}. [{g['max_tier']}] {g['skill']} · {g['kind']}  — `{g['signature']}`",
            f"- **fired on {g['n_pairs']} pair(s):** {pairs}",
            f"- severities: {g['severities'] or '-'}  ·  frozen_symbol: {g['frozen_symbol'] or '-'}",
            f"- datum_refs: {g['datum_refs']}",
            f"- {g['representative_finding']}",
            "",
        ]
    # log-only (killed / below bar)
    log_only = [g for g in digest["findings"] if not g["issue_eligible"]]
    if log_only:
        lines += ["## Log-only (critic-killed or below bar)", ""]
        for g in log_only:
            kr = (g["adversary"].get("kill_reasons") or [None])[0]
            lines.append(
                f"- [{g['max_tier']}] {g['skill']} · {g['kind']} `{g['signature']}` "
                f"(killed={g['adversary'].get('n_killed', 0)}): {(kr or '')[:160]}"
            )
    return "\n".join(lines) + "\n"


def write_digest(digest: dict, out_dir: "Path | str") -> "tuple[Path, Path]":
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jp = out / "findings_digest.json"
    mp = out / "findings_digest.md"
    jp.write_text(json.dumps(digest, indent=1, default=str))
    mp.write_text(render_markdown(digest))
    return jp, mp


# ── issue emission (opt-in; injectable GH backend) ──────────────────────────────────────────────────────
def _issue_title(g: dict) -> str:
    short = (g["representative_finding"] or g["kind"] or "finding").strip().split(". ")[0][:80]
    return f"[subskill-loop][{g['skill']}] {g['kind']}: {short}"


def _issue_body(g: dict) -> str:
    pairs = "\n".join(
        f"- {p['target']}/{p['indication']} ({p['iteration_id']} @ {(p.get('sha') or '')[:8]}, {p['tier']})"
        for p in g["pairs"]
    )
    kill = g["adversary"].get("kill_reasons") or []
    return (
        f"**Structural finding** (subskill-loop {g['skill']}, {g['kind']}, max tier {g['max_tier']}).\n\n"
        f"{g['representative_finding']}\n\n"
        f"**Why:** {g['representative_why']}\n\n"
        f"**datum_refs:** `{g['datum_refs']}`\n\n"
        f"**Fired on {g['n_pairs']} pair(s):**\n{pairs}\n\n"
        f"**Adversarial critic:** survived={g['adversary'].get('n_survived', 0)} "
        f"killed={g['adversary'].get('n_killed', 0)}"
        + (f" (note: killed elsewhere — {kill[0][:200]})" if kill else "")
        + f"\n\nseverities: {g['severities']} · frozen_symbol: {g['frozen_symbol']}\n\n"
        f"<!-- {_FP_MARKER} {g['signature']} -->\n"
        f"_Emitted by eval/loop/compile_findings.py — propose-only; adjudicate via the normal "
        f"card/rule/method channel (STOP-A)._"
    )


def _gh(args: "list[str]") -> str:
    """Default GH backend: a thin `gh` wrapper. Injected-over in tests."""
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def emit_issues(
    digest: dict,
    *,
    repo: "str | None" = None,
    dry_run: bool = True,
    gh: "Optional[Callable[[list[str]], str]]" = None,
) -> dict:
    """File/update a GitHub issue per ISSUE-ELIGIBLE structural finding, idempotently.

    Dedup is on the fingerprint marker (``<!-- loop-finding-fp: <sig> -->``) in the issue body: an existing
    OPEN issue carrying it is UPDATED with a re-sweep comment (never duplicated); a CLOSED one is left alone
    (resolved); otherwise a new issue is created. ``dry_run`` (default) performs no writes and reports the
    plan. ``gh`` is injectable so this is unit-tested with no live gh."""
    call = gh or _gh
    repo_args = ["--repo", repo] if repo else []
    plan = {"created": [], "updated": [], "skipped_closed": [], "dry_run": dry_run}
    for g in digest["findings"]:
        if not g["issue_eligible"]:
            continue
        sig = g["signature"]
        # Search existing issues (any state) carrying this fingerprint marker.
        existing = call(
            [
                "issue",
                "list",
                *repo_args,
                "--state",
                "all",
                "--limit",
                "100",
                "--search",
                f"{_FP_MARKER} {sig} in:body",
                "--json",
                "number,state,title",
            ]
        )
        try:
            found = json.loads(existing) if existing.strip() else []
        except ValueError:
            found = []
        match = next((it for it in found if isinstance(it, dict)), None)
        if match and str(match.get("state", "")).upper() == "OPEN":
            if not dry_run:
                call(
                    [
                        "issue",
                        "comment",
                        str(match["number"]),
                        *repo_args,
                        "--body",
                        f"Re-observed in a fresh sweep — now fired on {g['n_pairs']} pair(s).",
                    ]
                )
            plan["updated"].append({"signature": sig, "number": match["number"]})
        elif match:
            plan["skipped_closed"].append({"signature": sig, "number": match["number"]})
        else:
            if not dry_run:
                call(
                    [
                        "issue",
                        "create",
                        *repo_args,
                        "--label",
                        _ISSUE_LABEL,
                        "--title",
                        _issue_title(g),
                        "--body",
                        _issue_body(g),
                    ]
                )
            plan["created"].append({"signature": sig, "title": _issue_title(g)})
    return plan


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────
def _cli(argv: "Optional[list[str]]" = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Compile subskill-loop findings across runs; optionally emit issues.")
    ap.add_argument("--iterations-root", type=Path, default=Path(__file__).resolve().parent / "iterations")
    ap.add_argument("--skill", default=None, help="restrict to one skill's iteration dir")
    ap.add_argument(
        "--iter",
        dest="iters",
        action="append",
        default=None,
        help="restrict to specific iteration_id(s) (repeatable) — scope a real --open to one fresh run",
    )
    ap.add_argument("--since", default=None, help="keep only runs with generated_at >= this ISO-8601 UTC timestamp")
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent / "sweeps" / "latest")
    ap.add_argument(
        "--open", dest="open_issues", action="store_true", help="emit/update GitHub issues (else digest-only)"
    )
    ap.add_argument("--repo", default=None, help="gh --repo slug for issue emission")
    ap.add_argument("--yes", action="store_true", help="actually write issues (default with --open is a dry-run plan)")
    args = ap.parse_args(argv)

    digest = compile_sweep(args.iterations_root, skill=args.skill, iters=args.iters, since=args.since)
    jp, mp = write_digest(digest, args.out_dir)
    print(
        f"compiled {digest['n_runs']} run(s), {digest['n_findings_unique']} unique finding(s), "
        f"{digest['n_issue_candidates']} issue candidate(s)"
    )
    print(f"  → {jp}\n  → {mp}")

    if args.open_issues:
        plan = emit_issues(digest, repo=args.repo, dry_run=not args.yes)
        tag = "DRY-RUN plan" if not args.yes else "emitted"
        print(
            f"  issues ({tag}): create={len(plan['created'])} update={len(plan['updated'])} "
            f"skip_closed={len(plan['skipped_closed'])}"
        )
        for c in plan["created"]:
            print(f"    + {c['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
