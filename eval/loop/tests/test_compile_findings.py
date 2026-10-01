#!/usr/bin/env python3
"""Teeth for eval/loop/compile_findings.py — the cross-run findings compiler + issue emitter.

Covers the load-bearing properties:
  - DEDUP ON STRUCTURAL SIGNATURE: the same (skill, kind, datum-shape) across different (gene, indication)
    pairs is ONE issue candidate carrying BOTH pairs as evidence (not two issues);
  - ISSUE BAR: an all-killed structural finding is log-only (not an issue); a survivor in T2/T3 is eligible;
  - RANKING: T3 above T2, then recurrence;
  - IDEMPOTENT EMIT (injected gh): a new fingerprint CREATES; an existing OPEN one UPDATES (comments) and
    never duplicates; a CLOSED one is skipped; dry-run writes nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parents[1]
if str(_LOOP) not in sys.path:
    sys.path.insert(0, str(_LOOP))

import compile_findings as CF  # noqa: E402


def _finding(kind, target, refs, tier_sev, *, pair, verdict="survives", why="w", frozen=None, reason=None):
    tier, sev = tier_sev
    return {
        "kind": kind,
        "target": target,
        "finding": f"{kind} on {target}",
        "why": why,
        "datum_refs": refs,
        "_tier": {"tier": tier, "severity": sev, "frozen_symbol": frozen},
        "_adversary": {"verdict": verdict, "failure_mode": None, "reason": reason, "confidence": "medium"},
        "_source": {"candidate_key": f"{pair[0]}|{pair[1]}|", "target": pair[0], "indication": pair[1]},
    }


def _report(skill, iter_id, sha, buckets):
    tr = {CF.T1: [], CF.T2: [], CF.T3: []}
    for f in buckets:
        tr[f["_tier"]["tier"]].append(f)
    tiers = {k: len(v) for k, v in {"T1_land": tr[CF.T1], "T2_propose": tr[CF.T2], "T3_adjudicate": tr[CF.T3]}.items()}
    return {
        "schema_version": "1.0",
        "skill": skill,
        "iteration_id": iter_id,
        "run_dir": f"eval/loop/runs/iter-{iter_id}-{sha}",
        "generated_at": "2026-10-01T00:00:00Z",
        "teeth_green": False,
        "roster": {"n_total": 2, "n_dev": 1, "n_held_out": 1},
        "dev": {"tier_report": tr, "tiers": tiers, "adversary": {"ran": True, "n_killed": 0, "n_survived": 0}},
        "held_out": {"convergence": {"converged": False}},
        "ledger": {"chain_ok": True},
    }


def _write(root: Path, report: dict):
    d = root / report["skill"] / report["iteration_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "iteration_report.json").write_text(json.dumps(report))


def _sweep_dir(tmp_path) -> Path:
    root = tmp_path / "iterations"
    # Two runs of the SAME skill: a recurring structural finding on two different pairs (same kind+refs),
    # plus a killed finding, plus a distinct T2 finding.
    recurring_refs = ["l2a.paralog_buffering.property"]
    _write(
        root,
        _report(
            "functional-requirement",
            "iter-001",
            "aaaaaaaa",
            [
                _finding(
                    "missing_relationship",
                    "L2b.paralog x essentiality",
                    recurring_refs,
                    (CF.T3, "S2"),
                    pair=("KRAS", "COADREAD"),
                ),
                _finding(
                    "class_not_supported_by_datum",
                    "L2a.crispr.property",
                    ["l2a.crispr.property"],
                    (CF.T2, "S1"),
                    pair=("KRAS", "COADREAD"),
                    verdict="killed",
                    reason="contract-misread tail class",
                ),
            ],
        ),
    )
    _write(
        root,
        _report(
            "functional-requirement",
            "iter-002",
            "bbbbbbbb",
            [
                _finding(
                    "missing_relationship",
                    "L2b.paralog x essentiality",
                    recurring_refs,
                    (CF.T3, "S2"),
                    pair=("EGFR", "LUAD"),
                ),
                _finding(
                    "surface_unused_signal",
                    "L2b.lineage",
                    ["l2a.lineage.anchors.h"],
                    (CF.T2, "S3"),
                    pair=("EGFR", "LUAD"),
                ),
            ],
        ),
    )
    return root


def test_dedup_on_signature_aggregates_pairs(tmp_path):
    digest = CF.compile_sweep(_sweep_dir(tmp_path), skill="functional-requirement")
    assert digest["n_runs"] == 2
    # 3 unique structural findings: the recurring one (2 pairs), the killed class finding, the lineage one.
    assert digest["n_findings_unique"] == 3
    recurring = next(g for g in digest["findings"] if g["kind"] == "missing_relationship")
    assert recurring["n_pairs"] == 2
    assert {(p["target"], p["indication"]) for p in recurring["pairs"]} == {("KRAS", "COADREAD"), ("EGFR", "LUAD")}


def test_issue_bar_excludes_all_killed_includes_survivors(tmp_path):
    digest = CF.compile_sweep(_sweep_dir(tmp_path))
    by_kind = {g["kind"]: g for g in digest["findings"]}
    assert by_kind["missing_relationship"]["issue_eligible"] is True  # T3 survivor
    assert by_kind["surface_unused_signal"]["issue_eligible"] is True  # T2 survivor
    assert by_kind["class_not_supported_by_datum"]["issue_eligible"] is False  # all instances killed → log-only
    assert digest["n_issue_candidates"] == 2


def test_ranking_puts_t3_before_t2(tmp_path):
    digest = CF.compile_sweep(_sweep_dir(tmp_path))
    eligible = [g for g in digest["findings"] if g["issue_eligible"]]
    assert eligible[0]["kind"] == "missing_relationship"  # T3, 2 pairs ranks first
    assert eligible[0]["max_tier"] == CF.T3


def test_markdown_renders_candidates_and_log_only(tmp_path):
    digest = CF.compile_sweep(_sweep_dir(tmp_path))
    md = CF.render_markdown(digest)
    assert "Issue candidates (ranked)" in md
    assert "KRAS/COADREAD" in md and "EGFR/LUAD" in md
    assert "Log-only" in md  # the killed finding is logged with its kill reason
    assert "contract-misread tail class" in md


def test_write_digest_emits_both_files(tmp_path):
    digest = CF.compile_sweep(_sweep_dir(tmp_path))
    jp, mp = CF.write_digest(digest, tmp_path / "out")
    assert jp.exists() and mp.exists()
    assert json.loads(jp.read_text())["n_issue_candidates"] == 2


# ── idempotent emit with an injected gh backend ────────────────────────────────────────────────────────
class _FakeGh:
    """Records gh invocations; answers `issue list` from a preset {signature: {number,state}} map."""

    def __init__(self, existing: dict):
        self.existing = existing  # signature -> {"number":int,"state":"OPEN"/"CLOSED"}
        self.calls: list[list[str]] = []

    def __call__(self, args: "list[str]") -> str:
        self.calls.append(args)
        if args[0] == "issue" and args[1] == "list":
            # find the fingerprint in the --search arg
            search = args[args.index("--search") + 1]
            sig = search.split(CF._FP_MARKER)[1].split(" in:body")[0].strip()
            hit = self.existing.get(sig)
            return json.dumps([{"number": hit["number"], "state": hit["state"], "title": "x"}]) if hit else "[]"
        return ""


def test_emit_creates_new_and_dry_run_writes_nothing(tmp_path):
    digest = CF.compile_sweep(_sweep_dir(tmp_path))
    gh = _FakeGh(existing={})
    plan = CF.emit_issues(digest, repo="o/r", dry_run=True, gh=gh)
    assert len(plan["created"]) == 2 and plan["dry_run"] is True
    # dry-run: only `issue list` queries, never create/comment
    assert all(c[1] == "list" for c in gh.calls if c[0] == "issue")


def test_emit_updates_open_and_skips_closed(tmp_path):
    digest = CF.compile_sweep(_sweep_dir(tmp_path))
    eligible = [g for g in digest["findings"] if g["issue_eligible"]]
    sig_open = eligible[0]["signature"]
    sig_closed = eligible[1]["signature"]
    gh = _FakeGh(existing={sig_open: {"number": 11, "state": "OPEN"}, sig_closed: {"number": 22, "state": "CLOSED"}})
    plan = CF.emit_issues(digest, repo="o/r", dry_run=False, gh=gh)
    assert plan["updated"] == [{"signature": sig_open, "number": 11}]
    assert plan["skipped_closed"] == [{"signature": sig_closed, "number": 22}]
    assert plan["created"] == []
    # the OPEN one got a comment; the CLOSED one did not; nothing was created
    assert any(c[0] == "issue" and c[1] == "comment" and "11" in c for c in gh.calls)
    assert not any(c[0] == "issue" and c[1] == "create" for c in gh.calls)
