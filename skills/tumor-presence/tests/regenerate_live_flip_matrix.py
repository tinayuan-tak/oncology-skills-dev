#!/usr/bin/env python
"""Regenerate fixtures/subset_high_live_flip_matrix.json — the LIVE-PANEL counterfactual behind the
2026-09-18 subset_high split (target-contracts #809 phase 3b, c3eec12).

WHAT THE MATRIX IS. Every (target, indication) pair on the panel, ranked TWICE with the same skills
code and two interpretation-rule arms:

    arm B = target-contracts as checked out   — broad rule narrowed, `in: [broadly_high, broadly_detected]`
    arm A = the same tree, ONE FIELD MUTATED  — subset_high re-added to the broad rule's `in:` list,
                                               i.e. the PRE-3b overlap state where both rungs fire

The pairs whose verdict differs between the arms are the flip population: the targets whose headline
the split actually moved. Everything else is byte-identical, and that half matters just as much —
a split that silently re-worded 56 unrelated targets would be a regression, not a fix.

WHY IT IS SPLIT INTO TWO MODES. The pipeline is
    (1) measure the panel live   -> tumor_expression_class / high_fraction / detectable_fraction /
                                    distribution_pattern    [needs S3 + AWS_PROFILE=cbg, minutes]
    (2) derive the verdict twice -> fired_rules(...) -> run.py::_verdict(...)   [pure, credential-less]
Only step (1) is irreproducible, so only step (1)'s output is stored as ground truth. The fixture keeps
the MEASUREMENTS and the test re-derives the verdicts through the real rules loader. That is the whole
reason the committed matrix is a regression guard rather than a self-referential copy: storing derived
values and asserting them back would compare a computation against its own output and could never fail.

    --rederive-only   re-run step (2) over the stored measurements. NO credentials. This is what you run
                      after a rules or ladder change, and what you run to see WHY the test went red.
    (default)         re-run step (1) then (2). Needs live credentials and rewrites the measurements.

HISTORY, because it explains an asymmetry a reader will notice. The original run (2026-09-18) used two
real checkouts: A = contracts main 8d0fb9c, B = the #809 worktree a9c5cad. That worktree was pruned when
the PR landed, so a two-checkout generator is no longer runnable — and it no longer needs to be, because
once 3b is on main the narrowed arm IS main and the overlap arm is a one-field mutation of it. The
in-memory synthesis was verified to reproduce BOTH stored columns for all 58 pairs (0 mismatches) against
contracts c475e69, two commits past the tree the matrix was first generated on.

Usage:
    # credential-less: re-derive both verdict columns from the stored measurements
    pixi run python skills/tumor-presence/tests/regenerate_live_flip_matrix.py --rederive-only

    # full: re-measure the panel, then re-derive (needs the onc-compbio bucket)
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
        pixi run python skills/tumor-presence/tests/regenerate_live_flip_matrix.py
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
SKILLS_ROOT = SKILL_DIR.parent
FIXTURE = HERE / "fixtures" / "subset_high_live_flip_matrix.json"

sys.path.insert(0, str(SKILLS_ROOT))

BROAD_RID = "tumor-expression-broadly-high-supportive"
SUBSET_RID = "tumor-expression-subset-high-supportive"
CARD_ID = "tumor-rna-distribution"
# The four card-summary fields the tumor-expression rules read. Stored per pair; nothing else is needed
# to re-derive a verdict, and storing more would invite a reader to believe the fixture is a full card.
MEASURED_FIELDS = ("cls", "high", "det", "pat")


def _sha(root: Path) -> str:
    """DERIVED, never hardcoded — a rebase moves the tree under a hardcoded label and turns an accurate
    provenance cell into a false one."""
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip() or "?"


def _load_rules():
    from _skills_common.paths import target_contracts_root
    from _skills_common.rules_loader import load_interpretation_rules

    root = target_contracts_root()
    # NB: the axis arg must equal the file's own DECLARED axis, which is UNDERSCORED. The kebab form
    # returns None, and a zero-rule load makes every arm below trivially agree.
    rules = load_interpretation_rules("intracellular_intrinsic", contracts_root=root)
    if not rules or len(rules) <= 250:
        raise SystemExit(f"loaded {len(rules or [])} rules from {root} — the loader failed, not the repo")
    return rules, root


def broad_in(rules) -> list[str] | None:
    for r in rules:
        if r.get("rule_id") == BROAD_RID:
            return list((r.get("when") or {}).get("in") or [])
    return None


def arm_a(rules):
    """Synthesize the PRE-3b overlap arm: re-add subset_high to the broad rule's `in:` list.

    Exact-count assert on purpose. If the tree already lists subset_high on the broad rule it predates
    3b, this mutation is a no-op, and both arms would be the same rules list — a counterfactual that
    quietly stopped being one. That is the failure this refuses to produce silently."""
    out = copy.deepcopy(rules)
    restored = 0
    for r in out:
        if r.get("rule_id") == BROAD_RID:
            vals = (r.get("when") or {}).get("in") or []
            if "subset_high" in vals:
                raise SystemExit(
                    f"{BROAD_RID} already lists subset_high — this contracts tree predates 3b (c3eec12), "
                    "so arm A would equal arm B and the matrix would report 0 movers vacuously."
                )
            r["when"]["in"] = [*vals, "subset_high"]
            restored += 1
    if restored != 1:
        raise SystemExit(f"mutated {restored} rules, expected exactly 1 — arm A would not be a control")
    return out


def derive(measurement: dict, rules, tp):
    """measurements -> fired rule ids -> collapsed verdict. The ONLY derivation path; the test uses the
    same two calls, so a divergence between generator and test is not possible by construction."""
    from _skills_common import fired_rules

    card = {
        "card_id": CARD_ID,
        "summary": {
            "tumor_expression_class": measurement["cls"],
            "high_fraction": measurement["high"],
            "detectable_fraction": measurement["det"],
            "distribution_pattern": measurement["pat"],
        },
    }
    fired = fired_rules([card], "intracellular-intrinsic", card_id_filter=[CARD_ID], rules=rules)
    verdict, driver = tp._verdict(fired)
    return verdict, driver, sorted(r["rule_id"] for r in fired)


def measure_panel(pairs: list[tuple[str, str]]) -> list[dict]:
    """Live read of the tumor RNA distribution card for each pair. Needs credentials.

    A pair whose class is None/data_unavailable is EXCLUDED and recorded in `_meta.excluded` rather than
    dropped silently — an unexplained shrink in the row count is indistinguishable from a coverage loss."""
    from _skills_common._live_readers import read_tumor_expression_distribution

    rows = []
    for target, code in pairs:
        try:
            summary = read_tumor_expression_distribution(target, code) or {}
        except Exception as exc:  # a single unreadable pair must not lose the other 57
            rows.append({"target": target, "code": code, "err": repr(exc), "cls": None})
            continue
        rows.append(
            {
                "target": target,
                "code": code,
                "cls": summary.get("tumor_expression_class"),
                "high": summary.get("high_fraction"),
                "det": summary.get("detectable_fraction"),
                "pat": summary.get("distribution_pattern"),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--rederive-only",
        action="store_true",
        help="re-derive both verdict columns from the STORED measurements; no credentials, no re-measure",
    )
    ap.add_argument("--out", default=None, help=f"output path (default {FIXTURE})")
    args = ap.parse_args(argv)
    out_path = Path(args.out) if args.out else FIXTURE

    from _test_support import load_run_py

    tp = load_run_py(SKILL_DIR, "tp_regen_flip_matrix")
    rules_b, contracts_root = _load_rules()
    rules_a = arm_a(rules_b)
    print(f"arm A broad.in = {broad_in(rules_a)}")
    print(f"arm B broad.in = {broad_in(rules_b)}")
    print(f"subset rung present: {any(r.get('rule_id') == SUBSET_RID for r in rules_b)}")

    prior = json.loads(out_path.read_text()) if out_path.exists() else {"_meta": {}, "pairs": []}
    excluded = list(prior.get("_meta", {}).get("excluded") or [])

    if args.rederive_only:
        if not prior["pairs"]:
            raise SystemExit(f"{out_path} has no stored pairs — nothing to re-derive; run without the flag")
        measurements = [
            {k: p[k] for k in MEASURED_FIELDS} | {"target": p["target"], "code": p["code"]} for p in prior["pairs"]
        ]
    else:
        panel = [(p["target"], p["code"]) for p in prior["pairs"]] + [(e["target"], e["code"]) for e in excluded]
        if not panel:
            raise SystemExit("no panel to measure — seed `pairs` or pass a prior fixture via --out")
        raw = measure_panel(panel)
        measurements, excluded = [], []
        for r in raw:
            if r.get("cls") in (None, "data_unavailable"):
                excluded.append({"target": r["target"], "code": r["code"], "reason": r.get("err") or r.get("cls")})
            else:
                measurements.append(r)

    rows, movers = [], []
    for m in measurements:
        va, da, fa = derive(m, rules_a, tp)
        vb, db, fb = derive(m, rules_b, tp)
        row = {
            "target": m["target"],
            "code": m["code"],
            **{k: m[k] for k in MEASURED_FIELDS},
            "A": va,
            "B": vb,
            "drvA": da,
            "drvB": db,
            "firedA": fa,
            "firedB": fb,
        }
        rows.append(row)
        if va != vb:
            movers.append(row)

    non_mover_classes = dict(sorted(collections.Counter(r["cls"] for r in rows if r["A"] == r["B"]).items()))
    meta = dict(prior.get("_meta") or {})
    meta.update(
        {
            "regenerated_by": "skills/tumor-presence/tests/regenerate_live_flip_matrix.py",
            "skills_sha": _sha(SKILLS_ROOT),
            "contracts_sha": _sha(contracts_root),
            "arm_a": f"synthesized in-process from contracts {_sha(contracts_root)} by re-adding "
            f"subset_high to {BROAD_RID}",
            "arm_b": f"contracts {_sha(contracts_root)} as checked out",
            "measured": {
                "pairs_ranked": len(rows),
                "movers": len(movers),
                "byte_identical": len(rows) - len(movers),
                "targets": len({r["target"] for r in rows}),
                "indications": len({r["code"] for r in rows}),
                "non_mover_classes": non_mover_classes,
            },
            "excluded": excluded,
        }
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"_meta": meta, "pairs": rows}, indent=1) + "\n")

    print(f"\npairs ranked: {len(rows)}   MOVERS: {len(movers)}   byte-identical: {len(rows) - len(movers)}")
    for m in movers:
        print(f"  {m['target']:9s} {m['code']:8s} cls={m['cls']:12s} high={m['high']:.3f}")
        print(f"      A {m['A']:30s} via {m['drvA']}")
        print(f"      B {m['B']:30s} via {m['drvB']}")
    print(f"\nnon-movers by class: {non_mover_classes}")
    print(f"excluded: {excluded}")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
