#!/usr/bin/env python3
"""harvest_literature — Component 2 of the literature↔deterministic discordance loop.

Runs the opt-in `--literature` lane across the fan-out sub-skills for a set of (target,
indication) pairs, SNAPSHOTS each sub-skill's `literature_synthesis` (joined with its
deterministic sub-verdict + claim_vector) into a pinned corpus, and — optionally — feeds
`build_discordance_ledger` to emit the ranked candidate-gap ledger.

WHY A PINNED SNAPSHOT. The lane is an Opus read of abstracts and is NOT bit-reproducible
(model-default temperature; `_prompt_hash` drifts). So we harvest ONCE into a frozen corpus and
compute/review the ledger against that snapshot — never re-roll the lane live per review. Each
record is stamped with `_model_id` + `_prompt_hash`.

COST. This is the expensive, live half of the loop. It runs the full in-process fan-out
(`_run_sub_skills`) — every wired reader hits live S3 — plus one Opus call per lane. Scope the
lanes with `--literature-scope gating` (the ~gating axes only) to bound Bedrock spend. Keep the
target list to the calibration set (dozens), NOT a blind fleet sweep (see the plan §5).

ENV: `AWS_PROFILE=cbg` (live readers, onc-compbio bucket) + `BEDROCK_AWS_PROFILE=cmp-dev`
(the Opus lane). After a SageMaker restart, re-export PATH for gh/pixi.

Usage:
    AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev pixi run python eval/harvest_literature.py \
        --pairs KRAS/COADREAD,MET/LUAD --literature-scope gating \
        --snapshot-dir eval/literature-snapshots --build-ledger \
        --calibration-set ../rnd-computational-biology-oncology-target-contracts/vocabularies/known_target_calibration_set.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parent
_SKILLS = _EVAL.parents[0] / "skills"
for _p in (str(_EVAL), str(_SKILLS), str(_SKILLS / "target-profile" / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_discordance_ledger as bdl  # noqa: E402


def _normalize_verdict(verdict) -> tuple[str | None, str | None]:
    """res['verdict'] is (verdict_str, driving_rule_id) | None."""
    if isinstance(verdict, (list, tuple)) and verdict:
        return verdict[0], (verdict[1] if len(verdict) > 1 else None)
    return None, None


def _canonical_symbol(target: str) -> str:
    """Map a display/alias symbol (the calibration-set KEY, e.g. HER2/TROP2/BCMA/CD20) to the
    HGNC-canonical gene symbol the gene-keyed data products are keyed by (ERBB2/TACSTD2/TNFRSF17/
    MS4A1). Single-sources run_known_target_panel.TARGET_CANON so the harvest resolves the SAME
    symbol as the nomination backtest — WITHOUT this, the fan-out queried every gene-keyed reader
    (PRISM/DGIdb/ChEMBL/structure) with an ALIAS that matches no HGNC row, so each gene-keyed axis
    read a spurious data-unavailable / no-compounds-found and the ledger logged a phantom
    calibration_gap (CASE-011: HER2/BRCA tractability read chemically_unhit via
    prism-no-compounds-found-neutral, though the resolved ERBB2 run reads chemically_active with 37
    PRISM compounds + 201 DGIdb approved interactions). Canonical / unknown symbols pass through."""
    try:
        from run_known_target_panel import TARGET_CANON
    except Exception:  # noqa: BLE001 — a canon-map import fault must never abort a harvest
        TARGET_CANON = {}
    sym = (target or "").strip()
    return TARGET_CANON.get(sym, sym)


def harvest_pair(target: str, indication: str, *, literature_scope: str = "all",
                 model: str | None = None) -> list[dict]:
    """Run the fan-out with the --literature lane ON and project each sub-skill into a
    normalized harvest record. Records are only produced for sub-skills whose lane actually
    ran (a skill with no narrator lens, or a lit-native skill, is honestly skipped).

    The fan-out runs on the HGNC-canonical symbol (see _canonical_symbol) so gene-keyed readers
    resolve; the record keeps `target` = the ORIGINAL display/alias symbol (the calibration-set
    key) so calibration_gap tagging + the snapshot filename stay keyed by that symbol, mirroring
    run_known_target_panel (curated `name` vs resolved `emit_target`)."""
    from tp_fanout import _run_sub_skills  # imported lazily so --help needs no skills path

    run_symbol = _canonical_symbol(target)
    sub_results = _run_sub_skills(run_symbol, indication,
                                  subskill_literature=True,
                                  subskill_literature_scope=literature_scope,
                                  synthesis_model=model)
    records: list[dict] = []
    for short, res in sub_results.items():
        facet = res.get("synthesis_facet") or {}
        lit = facet.get("literature_synthesis") if isinstance(facet, dict) else None
        if not isinstance(lit, dict) or not lit:
            continue
        v, rule = _normalize_verdict(res.get("verdict"))
        fired = res.get("fired") or []
        fired_ids = [f.get("rule_id") for f in fired if isinstance(f, dict)] if fired else []
        records.append({
            "target": target,
            # HGNC symbol the fan-out actually resolved (== target unless an alias was canonicalized).
            # Audit trail for CASE-011; downstream (build_discordance_ledger) ignores unknown keys.
            "resolved_symbol": run_symbol,
            "indication": indication,
            "skill": res.get("skill_dir") or short,   # skill DIR id (matches atlas-exclusion set)
            "axis_short": short,
            "sub_verdict": {
                "gate": short,
                "verdict": v,
                "driving_rule_id": rule,
                "fired_rule_ids": fired_ids,
            },
            "claim_vector": (facet.get("claim_vector") if isinstance(facet, dict) else None),
            "literature_synthesis": lit,
            "_provenance": {"model_id": lit.get("_model_id"), "prompt_hash": lit.get("_prompt_hash")},
        })
    return records


def _parse_pairs(spec: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for tok in (spec or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        t, _, ind = tok.partition("/")
        out.append((t.strip(), ind.strip()))
    return out


# Ground-truth sections keyed BY TARGET SYMBOL; each value carries `indication`. Composite/multi
# targets (e.g. CDK4_6, EGFR_cMET_VEGF) and `multi` indications are skipped — they are not a
# single (gene, indication) the fan-out can run.
_PAIR_SECTIONS = ("reference_profiles", "known_gap_watchlist", "positive_controls")


def _pairs_from_calibration(path: str | Path) -> list[tuple[str, str]]:
    """(target, indication) pairs from known_target_calibration_set.yaml. The sections are DICTS
    keyed by target symbol (the symbol is the KEY, not a `target:` field). Skips composite targets
    and non-specific `multi` indications; de-dupes."""
    try:
        import yaml  # type: ignore
        doc = yaml.safe_load(Path(path).read_text()) or {}
    except Exception:  # noqa: BLE001
        return []
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for section in _PAIR_SECTIONS:
        sec = doc.get(section)
        if not isinstance(sec, dict):
            continue
        for target, v in sec.items():
            if "_" in target or "." in target:            # composite / fusion pseudo-target — skip
                continue
            ind = v.get("indication") if isinstance(v, dict) else None
            if not ind or ind == "multi":
                continue
            pair = (str(target), str(ind))
            if pair not in seen:
                seen.add(pair)
                out.append(pair)
    return out


def _snapshot_path(snapshot_dir: Path, target: str, indication: str) -> Path:
    return snapshot_dir / f"{target}__{indication}.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", default=None, help="comma list of TARGET/INDICATION (e.g. KRAS/COADREAD,MET/LUAD)")
    ap.add_argument("--calibration-set", default=None,
                    help="known_target_calibration_set.yaml — source of (target,indication) pairs AND calibration_gap tagging")
    ap.add_argument("--use-calibration-pairs", action="store_true",
                    help="derive the pair list from --calibration-set (else --pairs is the source)")
    ap.add_argument("--literature-scope", choices=["all", "gating"], default="all")
    ap.add_argument("--model", default=None, help="override the lane's Bedrock model id")
    ap.add_argument("--snapshot-dir", default="eval/literature-snapshots")
    ap.add_argument("--build-ledger", action="store_true", help="run build_discordance_ledger over the snapshot dir")
    ap.add_argument("--ledger-out", default="eval/discordance_ledger.json")
    a = ap.parse_args(argv)

    if a.use_calibration_pairs and a.calibration_set:
        pairs = _pairs_from_calibration(a.calibration_set)
    else:
        pairs = _parse_pairs(a.pairs or "")
    if not pairs:
        ap.error("no (target, indication) pairs — pass --pairs or --use-calibration-pairs with --calibration-set")

    snapshot_dir = Path(a.snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for target, indication in pairs:
        print(f"[harvest] {target}/{indication} (scope={a.literature_scope}) ...", flush=True)
        try:
            records = harvest_pair(target, indication, literature_scope=a.literature_scope, model=a.model)
        except Exception as e:  # noqa: BLE001 — one pair failing must not lose the others
            print(f"[harvest] !! {target}/{indication} failed: {e}", file=sys.stderr)
            continue
        _snapshot_path(snapshot_dir, target, indication).write_text(json.dumps(records, indent=2))
        total += len(records)
        print(f"[harvest]   {len(records)} lane record(s) snapshotted")

    print(f"[harvest] done — {total} records across {len(pairs)} pair(s) → {snapshot_dir}")

    if a.build_ledger:
        cal = bdl._load_calibration_targets(a.calibration_set) if a.calibration_set else set()
        ledger = bdl.build_ledger(snapshot_dir, cal)
        Path(a.ledger_out).write_text(json.dumps(ledger, indent=2))
        s = ledger["summary"]["by_gap_class"]
        print(f"[ledger] {ledger['n_rows']} rows ({ledger['n_actionable']} actionable) → {a.ledger_out}")
        print(f"[ledger] by_gap_class: {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
