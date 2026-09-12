#!/usr/bin/env python3
"""diff_discordance_ledger — turn the one-shot ledger into a MONITORED cadence.

Compares a freshly-built discordance ledger against a committed BASELINE of already-seen SHARP
candidate gaps (calibration_gap + verdict_rule_gap — the high-signal classes; blind_spot / staleness
drift run-to-run under the non-reproducible LLM lane, so they are trended by COUNT, not diffed
row-by-row). Surfaces:
  * NEW    — a sharp gap whose key is absent from the baseline (appeared since last run: a framework
             change, a data refresh, or the literature moving) → the actionable signal.
  * RESOLVED — a baseline sharp key absent from the new ledger ON A PAIR THIS RUN ACTUALLY
             RE-EXAMINED (a fix landed, or the lane no longer contradicts) → confirm + prune.
  * UNCOVERED — a baseline sharp key whose (skill, target, indication) was NOT in this run's scope.
             Says nothing. Neither resolved nor regressed; carried forward untouched.
  * blind/staleness COUNT deltas — coarse trend only, and only comparable at equal scope.

Row key = "SKILL|TARGET|INDICATION|AXIS|GAP_CLASS" (claim-vector-axis aligned — see
build_discordance_ledger v2). Exit non-zero when NEW sharp gaps appear (the nightly guard signal).
This is escalate-only + review-queue: it never edits a verdict, never fails a skill run.

SCOPE GUARD (2026-09-12) — the defect this fixes. RESOLVED used to be `baseline_keys - new_keys`
over the WHOLE baseline, with no notion of what the ledger covered. So a legitimately SCOPED run
read as mass remediation: the 20-pair functional-requirement panel diffed against the 7-skill
baseline reported **33 of 33 baseline keys RESOLVED** — 28 belonging to skills the ledger never
ran, and the other 5 to FR pairs outside the panel (CEACAM5/NSCLC, HIF2A/RCC, PARP1/OV,
STEAP1/prostate). Zero were real. `--write-baseline` then compounded it: it rebuilt the baseline
wholesale from that ledger, so one scoped run would DELETE every out-of-scope key — discarding the
review provenance the baseline exists to hold, and re-reporting all of it as NEW on the next full
run. Now RESOLVED is restricted to the ledger's `covered` scope and `--write-baseline` MERGES
(replacing in-scope keys, carrying the rest forward); `--replace-baseline` is the explicit opt-in
for the old wholesale behavior.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SHARP = ("calibration_gap", "verdict_rule_gap")


def _row_key(r: dict) -> str:
    return "|".join(str(r.get(k)) for k in ("skill", "target", "indication", "axis_key", "gap_class"))


def _key_scope(key: str) -> tuple[str, str, str]:
    """The (skill, target, indication) prefix of a row key — the unit a run covers."""
    parts = key.split("|")
    return (parts[0], parts[1], parts[2]) if len(parts) >= 3 else (key, "", "")


def sharp_keys(ledger: dict) -> set[str]:
    return {_row_key(r) for r in ledger.get("rows", []) if r.get("gap_class") in SHARP}


def ledger_scope(ledger: dict) -> tuple[set[tuple[str, str, str]], str]:
    """(covered triples, how they were determined).

    Prefers the ledger's own `covered` field (build_discordance_ledger >= v2.1), which includes
    CONCORDANT pairs. A pre-v2.1 ledger has no such field, so we fall back to the triples its rows
    mention — deliberately CONSERVATIVE: a pair examined and found clean contributes no row, so it
    reads as uncovered and its baseline keys are carried forward rather than declared resolved.
    Under-reporting a fix is recoverable; falsely reporting 33 fixes is not."""
    covered = ledger.get("covered")
    if isinstance(covered, list):
        return {
            tuple(str(x) for x in t)[:3] for t in covered if isinstance(t, (list, tuple)) and len(t) >= 3
        }, "covered"
    return {
        (str(r.get("skill")), str(r.get("target")), str(r.get("indication"))) for r in ledger.get("rows", [])
    }, "rows_fallback"


def _coarse_counts(ledger: dict) -> dict:
    return dict(ledger.get("summary", {}).get("by_gap_class", {}))


def load_baseline(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"schema": "discordance_baseline/v1", "keys": [], "counts": {}}
    return json.loads(p.read_text())


def diff(ledger: dict, baseline: dict) -> dict:
    new_keys = sharp_keys(ledger)
    base_keys = set(baseline.get("keys", []))
    scope, scope_source = ledger_scope(ledger)
    appeared = sorted(new_keys - base_keys)
    # A baseline key can only be RESOLVED if this run re-examined its pair. Everything else is
    # UNCOVERED — the run is silent about it, which is not the same as clean.
    gone = base_keys - new_keys
    resolved = sorted(k for k in gone if _key_scope(k) in scope)
    uncovered = sorted(k for k in gone if _key_scope(k) not in scope)
    # The coarse counts are whole-ledger totals, so they are only comparable when the two runs
    # covered the SAME pairs. A baseline written before scope was recorded has no `scope` → unknown.
    base_scope = baseline.get("scope")
    counts_comparable = (
        None
        if not isinstance(base_scope, list)
        else {tuple(str(x) for x in t)[:3] for t in base_scope if isinstance(t, (list, tuple)) and len(t) >= 3} == scope
    )
    # attach the full row for each appeared key (for the report)
    by_key = {_row_key(r): r for r in ledger.get("rows", []) if r.get("gap_class") in SHARP}
    return {
        "new_sharp_gaps": [by_key[k] for k in appeared],
        "resolved_sharp_gaps": resolved,
        "uncovered_baseline_gaps": uncovered,
        "n_new": len(appeared),
        "n_resolved": len(resolved),
        "n_uncovered": len(uncovered),
        "scope": {
            "n_covered_pairs": len(scope),
            "source": scope_source,
            "baseline_fully_covered": not uncovered,
        },
        "coarse_count_delta": {
            cls: _coarse_counts(ledger).get(cls, 0) - baseline.get("counts", {}).get(cls, 0)
            for cls in set(_coarse_counts(ledger)) | set(baseline.get("counts", {}))
        },
        # False => the delta above mixes a scope change with a real change; do not trend on it.
        "coarse_count_delta_comparable": counts_comparable,
    }


def baseline_from_ledger(ledger: dict, prior: dict | None = None) -> dict:
    """Build the baseline from `ledger`, CARRYING FORWARD any prior key whose pair this ledger did
    not cover (pass `prior=None`, or use --replace-baseline, for the wholesale rewrite).

    Merging is the default because the baseline is review PROVENANCE across the whole fleet, while
    any single ledger is one corpus. A scoped run that rewrote it wholesale would silently drop
    every other skill's reviewed keys."""
    import datetime as _dt

    scope, _src = ledger_scope(ledger)
    keys = sharp_keys(ledger)
    carried: list[str] = []
    if prior:
        carried = sorted(k for k in set(prior.get("keys", [])) if _key_scope(k) not in scope)
        keys = keys | set(carried)
    out = {
        # v2: + `scope` (which pairs the keys/counts describe) and scope-preserving merge.
        "schema": "discordance_baseline/v2",
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "corpus_fingerprint": ledger.get("corpus_fingerprint"),
        "keys": sorted(keys),
        "counts": _coarse_counts(ledger),
        "scope": [list(t) for t in sorted(scope)],
        "note": (
            "SHARP (calibration_gap + verdict_rule_gap) keys seen as of this build; the monitor "
            "flags NEW sharp keys. Prune a key here when its gap is fixed/dismissed (CASE_LOG). "
            "`scope` = the (skill,target,indication) pairs THIS build examined; `counts` describe "
            "only those pairs and are comparable only against a run of the same scope."
        ),
    }
    if prior:
        out["n_carried_forward_out_of_scope"] = len(carried)
        # counts came from a scoped ledger but keys now span a wider set -- say so rather than imply
        # the counts cover the carried-forward pairs too.
        if carried:
            out["counts_note"] = (
                f"counts cover the {len(scope)} pair(s) in `scope` only; {len(carried)} key(s) were "
                f"carried forward from the prior baseline and are NOT reflected in `counts`."
            )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", required=True, help="fresh discordance_ledger.json (v2)")
    ap.add_argument("--baseline", required=True, help="committed eval/discordance_baseline.json")
    ap.add_argument("--out", default=None, help="write the diff report JSON here")
    ap.add_argument(
        "--write-baseline",
        action="store_true",
        help="MERGE --ledger into --baseline and write it (no diff/exit): in-scope keys are replaced, "
        "keys on pairs this ledger did not cover are carried forward",
    )
    ap.add_argument(
        "--replace-baseline",
        action="store_true",
        help="with --write-baseline, discard the prior baseline entirely instead of merging. Only "
        "correct when --ledger covers the WHOLE fleet; on a scoped ledger this deletes other "
        "skills' reviewed keys.",
    )
    ap.add_argument(
        "--fail-on-new", action="store_true", help="exit 1 when NEW sharp gaps appear (the nightly-guard signal)"
    )
    a = ap.parse_args(argv)

    ledger = json.loads(Path(a.ledger).read_text())
    if a.write_baseline:
        prior = None if a.replace_baseline else load_baseline(a.baseline)
        base = baseline_from_ledger(ledger, prior)
        Path(a.baseline).write_text(json.dumps(base, indent=2))
        carried = base.get("n_carried_forward_out_of_scope", 0)
        print(
            f"[baseline] wrote {len(base['keys'])} sharp keys → {a.baseline} "
            f"({len(sharp_keys(ledger))} from this ledger over {len(base['scope'])} covered pair(s)"
            + (f", {carried} carried forward out of scope)" if not a.replace_baseline else ", REPLACED)")
        )
        return 0
    if a.replace_baseline:
        ap.error("--replace-baseline only applies with --write-baseline")

    report = diff(ledger, load_baseline(a.baseline))
    text = json.dumps(report, indent=2)
    if a.out:
        Path(a.out).write_text(text)
    sc = report["scope"]
    print(
        f"[diff] NEW sharp gaps: {report['n_new']} · RESOLVED (re-examined): {report['n_resolved']} · "
        f"UNCOVERED (not in this run's scope): {report['n_uncovered']} · "
        f"scope: {sc['n_covered_pairs']} pair(s) via {sc['source']}"
    )
    comparable = report["coarse_count_delta_comparable"]
    if comparable is False:
        print(
            "[diff] count delta SUPPRESSED — the baseline was built over a different set of pairs, so "
            "the delta would mix a scope change with a real change. Re-baseline at equal scope to trend."
        )
    else:
        print(f"[diff] count delta: {report['coarse_count_delta']}")
        if comparable is None:
            print(
                "[diff] ^ comparability UNKNOWN — this baseline predates `scope` (schema v1), so it does "
                "not record which pairs its counts covered. Treat the delta as untrended until the next "
                "--write-baseline stamps a scope."
            )
    for r in report["new_sharp_gaps"]:
        print(
            f"  NEW [{r['gap_class']}] {r['skill']} {r['target']}/{r['indication']} "
            f"axis={r['axis_key']} claim_signal={r.get('claim_signal')} vcites={r['n_verified_citations']}"
        )
    if a.fail_on_new and report["n_new"] > 0:
        print(
            f"::error title=discordance-monitor::{report['n_new']} NEW sharp discordance(s) — triage + "
            "update eval/CASE_LOG.md, then prune the baseline."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
