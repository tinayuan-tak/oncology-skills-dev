"""build_eval_ledger.py — the append-only, release-keyed EVAL LEDGER (portfolio memory).

A DERIVED, read-only rollup of every target-evaluation this framework has emitted — the "institutional
memory" the cumulative-KG review called for. It scans the two eval-output families and normalises them
into one keyed row set + two reverse indexes:

  - target-profile `nomination.json`   — the rich spine: per-axis sub-verdicts (verdict, driving_rule_id,
                                          fired_rule_ids, cards_used, cards_missing), the overall
                                          recommendation, and the fragility facet (target_index /
                                          recommendation_fragility_index / contested).
  - compose-dashboard `evidence_package.json` — card-grain: per-card validation_state +
                                          interpretation_call, and the union of `input_manifest_ids`
                                          (the FOREIGN KEY that federates this decision layer to the
                                          data-product / discovery graph).
  - find-mode DISCOVERY scans `*.input_manifest_ids.json` — a portfolio-level nomination pass
                                          (e.g. analysis-methods arm_loss_sl_scan): ONE row/scan
                                          carrying its `input_manifest_ids` union +
                                          `nominated_target_indications`. Its edge into the graph is
                                          the new `by_manifest_id` index: a discovery scan and an
                                          evaluation that read the SAME product are linked there.

WHY (what a single re-run cannot reconstruct): cross-TARGET population structure ("which evaluated
targets fired rule X"), cross-RELEASE trend ("did the verdict flip when the data updated?"),
meta-learning over the nomination gate, and discovery leverage (rank un-evaluated neighbours). See the
`by_rule_id` and `by_target_indication` reverse indexes.

CONTRACT:
  - READ-ONLY derived state. It NEVER feeds the resolvers / gate — reading a prior verdict back into a
    new run would inject non-pinned state into the deterministic spine. This is a rollup, not an input.
  - Keyed by (target, indication, release_pin, framework_version, source). Rows are byte-stable across
    rebuilds because every field is read from the (fixed) artifacts — only the header `built_at` is
    wall-clock. STALENESS is a data-freshness concern owned by the RELEASE_PIN: today most artifacts are
    `unpinned` (target-profile reads live; auto release-resolution is the deferred data-catalog
    follow-on), so the cross-release trend view is degenerate until real pins exist — the machinery is
    correct and lights up when they do.

Mirrors validators/framework_health/build_framework_health.py:
  python validators/build_eval_ledger.py                         # generate health/eval_ledger.*
  python validators/build_eval_ledger.py --check                 # local staleness guard (needs siblings)
  python validators/build_eval_ledger.py --self-check            # CI-safe integrity of committed artifact
  python validators/build_eval_ledger.py --skills-repo P --products-root Q
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

CONTRACTS_REPO = Path(__file__).resolve().parents[1]
SIBLINGS = CONTRACTS_REPO.parent
HEALTH_DIR = CONTRACTS_REPO / "health"
LEDGER_PATH = HEALTH_DIR / "eval_ledger.jsonl"
INDEX_PATH = HEALTH_DIR / "eval_ledger_index.json"

_ROW_CORE = ("source", "target", "indication", "release_pin", "framework_version")


def _default_roots() -> dict[str, Path]:
    products = SIBLINGS / "rnd-computational-biology-oncology-data-products"
    return {
        "skills": SIBLINGS / "rnd-computational-biology-oncology-claude-oncology-skills",
        "products": products,
        # discovery-scan federation sidecars default to the data-products tree (where find-mode
        # outputs are published alongside evidence packages); override with --scans-root.
        "scans": products,
    }


def _unwrap(v):
    """overall_recommendation / confidence may be a bare string or a {value, _source, ...} dict."""
    return v.get("value") if isinstance(v, dict) else v


def row_key(r: dict) -> str:
    """Stable identity of an eval row. release_pin makes cross-release rows distinct (once real pins
    exist); source separates the target-profile and compose-dashboard emissions of the same target."""
    return "|".join(str(r.get(k) or "") for k in
                    ("target", "indication", "release_pin", "framework_version", "source"))


_REPO_PREFIX = "rnd-computational-biology-oncology-"


def _rel(path: Path) -> str:
    """Path from the artifact's repo-name segment onward (e.g. 'data-products/KRAS/.../evidence_package.json').
    Independent of checkout location (home / worktree / symlink) so the committed ledger is byte-stable."""
    parts = path.parts
    for i, seg in enumerate(parts):
        if seg.startswith(_REPO_PREFIX):
            return "/".join((seg[len(_REPO_PREFIX):], *parts[i + 1:]))
    return str(path)


def row_from_nomination(path: Path, nm: dict) -> dict:
    gov = nm.get("governance") or {}
    sub_verdicts, fired_all = [], set()
    for axis, d in (nm.get("sub_verdicts") or {}).items():
        frs = d.get("fired_rule_ids") or []
        fired_all.update(frs)
        sub_verdicts.append({
            "axis": axis, "verdict": d.get("verdict"), "driving_rule_id": d.get("driving_rule_id"),
            "fired_rule_ids": frs,
            "cards_used": d.get("cards_used") or [],       # present on runs >= skills #390
            "cards_missing": d.get("cards_missing") or [],
        })
    # fragility is being relocated from the top-level nomination key onto target_report.robustness.fragility
    # (skills Wave-3 legacy-facet retirement). Read the top-level key first (current runs), else fall back to
    # the target_report nest (post-retirement runs) — the SAME object, so the ledger row is unchanged either way.
    frag = (nm.get("fragility")
            or ((nm.get("target_report") or {}).get("robustness") or {}).get("fragility")
            or {})
    return {
        "source": "target_profile",
        "artifact_path": _rel(path),
        "target": nm.get("target"),
        "indication": nm.get("indication"),
        "release_pin": gov.get("release_pin", "unpinned"),
        "data_mode": gov.get("data_mode"),
        "framework_version": nm.get("skill_version"),
        "generated_at": nm.get("generated_at"),
        "recommendation": _unwrap((nm.get("llm_synthesis") or {}).get("overall_recommendation")),
        "fragility": ({"target_index": frag.get("target_index"),
                       "recommendation_fragility_index": frag.get("recommendation_fragility_index"),
                       "contested": frag.get("contested")} if frag else None),
        "sub_verdicts": sub_verdicts,
        "fired_rule_ids": sorted(fired_all),
        "input_manifest_ids": [],   # nomination.json does not carry manifest ids (evidence_package does)
    }


def row_from_evidence_package(path: Path, ep: dict) -> dict:
    ctx = ep.get("context") or {}
    gov = ep.get("governance") or {}
    manifest_ids, card_calls = set(), []
    for c in ep.get("cards") or []:
        if c.get("excluded_by_applies_when"):
            continue
        manifest_ids.update((c.get("provenance") or {}).get("input_manifest_ids") or [])
        card_calls.append({"card_id": c.get("card_id"),
                           "validation_state": c.get("validation_state"),
                           "interpretation_call": c.get("interpretation_call")})
    return {
        "source": "evidence_package",
        "artifact_path": _rel(path),
        "target": (ctx.get("target") or {}).get("symbol"),
        "indication": (ctx.get("indication") or {}).get("oncotree_code"),
        "release_pin": gov.get("release_pin", "unpinned"),
        "data_mode": gov.get("data_mode"),
        # Governance release fingerprint (2026-08-12): the run's DATA state, resolved from the
        # manifests it read. Makes the cross-release trend meaningful when release_pin is 'unpinned'.
        "resolved_release_digest": gov.get("resolved_release_digest"),
        "n_stale_families": sum(1 for v in (gov.get("resolved_releases") or {}).values()
                                if isinstance(v, dict) and v.get("is_stale")),
        "framework_version": ep.get("framework_version"),
        "generated_at": ep.get("generated_at"),
        # evidence_package synthesis is card-grain (headline/caveats/modality_fit) with no single
        # composed nominate/veto — recorded as None rather than fabricating one.
        "recommendation": None,
        "fragility": None,
        "card_calls": card_calls,
        "fired_rule_ids": [],
        "input_manifest_ids": sorted(manifest_ids),   # FEDERATION KEY to the data-product / discovery graph
    }


def row_from_scan(path: Path, sc: dict) -> dict:
    """Normalise a find-mode DISCOVERY scan's federation sidecar (e.g. arm_loss_sl_scan's
    <out>.input_manifest_ids.json) into ONE ledger row.

    A scan is a portfolio-level nomination pass, not a per-(target,indication) evaluation, so it
    contributes a single row keyed by (target_scope, 'discovery', ...) rather than one row per hit
    (which would flood the ledger). Its VALUE to the ledger is the `input_manifest_ids` union: the
    by_manifest_id index then links this discovery scan to every EVALUATION that read the same data
    products (the cumulative-KG discovery edge). `nominated_target_indications` carries the hit set
    for downstream 'which un-evaluated neighbours did discovery surface?' queries. Sidecar-only
    (JSON) so this reader stays dependency-free."""
    return {
        "source": sc.get("method") or "scan",
        "artifact_path": _rel(path),
        "target": sc.get("target_scope") or "ALL",          # scan scope, not a single target
        "indication": sc.get("indication_scope") or "discovery",
        "release_pin": "unpinned",                            # scans read live products
        "data_mode": "live_latest",
        "framework_version": sc.get("method_version"),
        "generated_at": None,                                 # sidecar carries no wall-clock (byte-stable)
        "recommendation": None,
        "fragility": None,
        "n_hits": sc.get("n_hits"),
        "nominated_target_indications": sc.get("nominated_target_indications") or [],
        "fired_rule_ids": [],                                 # discovery scan: no resolver rules
        "input_manifest_ids": sorted(sc.get("input_manifest_ids") or []),  # FEDERATION KEY
    }


# Discovery-scan federation sidecars carry this marker key (distinguishes them from other JSON).
_SCAN_SIDECAR_SUFFIX = ".input_manifest_ids.json"


def build_rows(roots: dict[str, Path]) -> list[dict]:
    rows: list[dict] = []
    skills = roots.get("skills")
    if skills and skills.exists():
        for p in sorted(skills.rglob("nomination.json")):
            try:
                rows.append(row_from_nomination(p, json.loads(p.read_text())))
            except (OSError, json.JSONDecodeError) as e:
                print(f"  WARN: skip unreadable {p}: {e}", file=sys.stderr)
    products = roots.get("products")
    if products and products.exists():
        for p in sorted(products.rglob("evidence_package.json")):
            try:
                rows.append(row_from_evidence_package(p, json.loads(p.read_text())))
            except (OSError, json.JSONDecodeError) as e:
                print(f"  WARN: skip unreadable {p}: {e}", file=sys.stderr)
    # Discovery-scan sidecars (find-mode products federating via input_manifest_ids).
    scans = roots.get("scans")
    if scans and scans.exists():
        for p in sorted(scans.rglob(f"*{_SCAN_SIDECAR_SUFFIX}")):
            try:
                sc = json.loads(p.read_text())
                if sc.get("method") and "input_manifest_ids" in sc:
                    rows.append(row_from_scan(p, sc))
            except (OSError, json.JSONDecodeError) as e:
                print(f"  WARN: skip unreadable {p}: {e}", file=sys.stderr)
    rows.sort(key=row_key)
    return rows


def build_indexes(rows: list[dict]) -> dict:
    by_rule: dict[str, list[str]] = {}
    by_ti: dict[str, list[dict]] = {}
    by_manifest: dict[str, list[str]] = {}
    for r in rows:
        rk = row_key(r)
        for rid in r.get("fired_rule_ids", []):
            by_rule.setdefault(rid, [])
            if rk not in by_rule[rid]:
                by_rule[rid].append(rk)
        # input_manifest_ids -> rows that read the product (the FEDERATION / discovery-graph edge:
        # joins evaluation rows and discovery-scan rows that share a data product).
        for mid in r.get("input_manifest_ids", []):
            by_manifest.setdefault(mid, [])
            if rk not in by_manifest[mid]:
                by_manifest[mid].append(rk)
        ti = f"{r.get('target')}|{r.get('indication')}"
        by_ti.setdefault(ti, []).append({
            "release_pin": r.get("release_pin"), "source": r.get("source"),
            # data fingerprint: distinguishes runs across catalog releases when release_pin is 'unpinned'
            "resolved_release_digest": r.get("resolved_release_digest"),
            "recommendation": r.get("recommendation"),
            "contested": (r.get("fragility") or {}).get("contested"),
            "generated_at": r.get("generated_at"), "row_key": rk,
        })
    return {
        "n_rows": len(rows),
        "n_rules_indexed": len(by_rule),
        "n_manifests_indexed": len(by_manifest),
        "n_target_indications": len(by_ti),
        # rule_id -> eval rows that fired it (cross-target rule cohorts).
        "by_rule_id": {k: sorted(v) for k, v in sorted(by_rule.items())},
        # manifest_id -> rows (evals + discovery scans) that read it (the data-product federation).
        "by_manifest_id": {k: sorted(v) for k, v in sorted(by_manifest.items())},
        # (target|indication) -> verdict/contested per release+source (the cross-release trend view).
        "by_target_indication": {k: by_ti[k] for k in sorted(by_ti)},
    }


def stable_projection(rows: list[dict], index: dict) -> str:
    """Everything that must be byte-stable across rebuilds (rows are derived from fixed artifacts;
    only the header built_at is wall-clock, and it is excluded here)."""
    return json.dumps({"rows": rows, "index": index}, indent=2, sort_keys=True, default=str)


def self_check(ledger_path: Path, index_path: Path) -> tuple[bool, list[str]]:
    """CI-safe: validate the committed artifact's internal integrity ONLY (no sibling probes)."""
    errs: list[str] = []
    if not ledger_path.exists() or not index_path.exists():
        return False, [f"missing {ledger_path.name} or {index_path.name} — run without --self-check to generate"]
    try:
        rows = [json.loads(ln) for ln in ledger_path.read_text().splitlines() if ln.strip()]
    except json.JSONDecodeError as e:
        return False, [f"[ledger] unparseable JSONL: {e}"]
    try:
        index = json.loads(index_path.read_text())
    except json.JSONDecodeError as e:
        return False, [f"[index] unparseable JSON: {e}"]
    keys = {row_key(r) for r in rows}
    for r in rows:
        missing = [k for k in _ROW_CORE if r.get(k) in (None, "")]
        if missing:
            errs.append(f"[ledger] row {row_key(r)} missing core field(s) {missing}")
    if index.get("n_rows") != len(rows):
        errs.append(f"[index] n_rows {index.get('n_rows')} != {len(rows)} ledger rows")
    for rid, rks in (index.get("by_rule_id") or {}).items():
        for rk in rks:
            if rk not in keys:
                errs.append(f"[index] by_rule_id[{rid}] references unknown row {rk}")
    for mid, rks in (index.get("by_manifest_id") or {}).items():
        for rk in rks:
            if rk not in keys:
                errs.append(f"[index] by_manifest_id[{mid}] references unknown row {rk}")
    for ti, entries in (index.get("by_target_indication") or {}).items():
        for e in entries:
            if e.get("row_key") not in keys:
                errs.append(f"[index] by_target_indication[{ti}] references unknown row {e.get('row_key')}")
    return (not errs), errs


def _resolve_roots(args) -> dict[str, Path]:
    roots = _default_roots()
    if args.skills_repo:
        roots["skills"] = Path(args.skills_repo)
    if args.products_root:
        roots["products"] = Path(args.products_root)
        roots["scans"] = Path(args.products_root)   # scans default to the products tree
    if args.scans_root:
        roots["scans"] = Path(args.scans_root)
    return roots


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build/check the eval ledger (portfolio memory).")
    p.add_argument("--check", action="store_true",
                   help="fail (exit 1) if the committed ledger is stale vs freshly computed "
                        "(needs sibling repos present — local/manual guard)")
    p.add_argument("--self-check", action="store_true",
                   help="CI-safe: validate the committed artifact's internal integrity only "
                        "(no sibling-repo probes)")
    p.add_argument("--skills-repo", type=Path)
    p.add_argument("--products-root", type=Path)
    p.add_argument("--scans-root", type=Path,
                   help="root to scan for discovery-scan federation sidecars "
                        "(*.input_manifest_ids.json); defaults to the products root")
    args = p.parse_args(argv)

    if args.self_check:
        ok, errs = self_check(LEDGER_PATH, INDEX_PATH)
        if ok:
            print(f"  OK {LEDGER_PATH.name} + {INDEX_PATH.name} (self-consistent)")
            return 0
        for e in errs:
            print(f"  FAIL {e}", file=sys.stderr)
        return 1

    roots = _resolve_roots(args)
    missing = [k for k, v in roots.items() if not v.exists()]
    if missing:
        print(f"  WARNING: repo root(s) not found, ledger will be partial: {missing}", file=sys.stderr)

    rows = build_rows(roots)
    index = build_indexes(rows)
    fresh = stable_projection(rows, index)

    if args.check:
        if not LEDGER_PATH.exists() or not INDEX_PATH.exists():
            print(f"  MISSING {LEDGER_PATH.name}/{INDEX_PATH.name} — run without --check to generate.",
                  file=sys.stderr)
            return 1
        prior_rows = [json.loads(ln) for ln in LEDGER_PATH.read_text().splitlines() if ln.strip()]
        prior_index = json.loads(INDEX_PATH.read_text())
        prior_index.pop("built_at", None)
        if stable_projection(prior_rows, prior_index) != fresh:
            print(f"  STALE {LEDGER_PATH.name}/{INDEX_PATH.name} — committed ledger differs; regenerate.",
                  file=sys.stderr)
            return 1
        print(f"  OK {LEDGER_PATH.name} (fresh)")
        return 0

    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows))
    index_out = {"built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), **index}
    INDEX_PATH.write_text(json.dumps(index_out, indent=2, sort_keys=True, default=str))
    print(f"  wrote {LEDGER_PATH.relative_to(CONTRACTS_REPO)}: {index['n_rows']} rows "
          f"({index['n_target_indications']} target×indication, {index['n_rules_indexed']} rules indexed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
