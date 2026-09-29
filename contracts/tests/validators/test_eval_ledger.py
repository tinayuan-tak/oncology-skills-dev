"""Tests for validators/build_eval_ledger.py — the append-only eval ledger.

Hermetic: builds synthetic nomination.json + evidence_package.json artifacts in tmp_path and drives the
pure build_rows / build_indexes / self_check functions, so it does not depend on live sibling repos.
The final test asserts the COMMITTED ledger self-checks (mirrors framework_health's CI self-check).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "validators"))

import build_eval_ledger as bel  # noqa: E402


def _mk_nomination(root: Path, target, indication, rec, sub, fragility=None, release_pin=None, fragility_nested=False):
    d = root / "docs" / "examples" / f"tp-{target}-{indication}"
    d.mkdir(parents=True, exist_ok=True)
    nm = {
        "skill": "target-profile",
        "skill_version": "1.0.0",
        "target": target,
        "indication": indication,
        "generated_at": "2026-08-12T00:00:00Z",
        "governance": {"data_mode": "live_latest", "release_pin": release_pin or "unpinned"},
        "sub_verdicts": sub,
        "llm_synthesis": {"overall_recommendation": {"value": rec}},
    }
    if fragility:
        # fragility_nested mimics a post-Wave-3 nomination that dropped the top-level `fragility` key and
        # carries it only under target_report.robustness.fragility.
        if fragility_nested:
            nm["target_report"] = {"robustness": {"fragility": fragility}}
        else:
            nm["fragility"] = fragility
    (d / "nomination.json").write_text(json.dumps(nm))


def _mk_ep(root: Path, target, indication, manifests):
    d = root / target / indication / f"ep-{target}-{indication}"
    d.mkdir(parents=True, exist_ok=True)
    ep = {
        "framework_version": "2.0.0",
        "generated_at": "2026-08-01T00:00:00Z",
        "context": {"target": {"symbol": target}, "indication": {"oncotree_code": indication}},
        "governance": {"data_mode": "latest_approved", "release_pin": "unpinned"},
        "cards": [
            {
                "card_id": "c1",
                "validation_state": "pass",
                "interpretation_call": "informative",
                "provenance": {"input_manifest_ids": manifests},
            },
            {"card_id": "c2", "excluded_by_applies_when": True},  # excluded → contributes nothing
        ],
    }
    (d / "evidence_package.json").write_text(json.dumps(ep))


def _mk_scan(root: Path, target_scope, manifests, nominated, n_hits=1, method="arm_loss_sl_scan"):
    d = root / "scans" / f"{method}-{target_scope}"
    d.mkdir(parents=True, exist_ok=True)
    sc = {
        "method": method,
        "method_version": "scan-0.1.0",
        "input_manifest_ids": manifests,
        "target_scope": target_scope,
        "indication_scope": "discovery",
        "n_hits": n_hits,
        "nominated_target_indications": nominated,
        "top_hits": [],
        "parameters": {"min_loss_freq": 0.2, "fdr_alpha": 0.05},
    }
    (d / "arm_loss_sl.input_manifest_ids.json").write_text(json.dumps(sc))


def test_row_from_scan_federates(tmp_path):
    scans = tmp_path / "scans_root"
    _mk_scan(
        scans,
        "KRAS",
        ["pancan-arm-cnv-per-sample-v1", "synlethdb-sl-partners-per-gene-v1"],
        ["MTAP|LUAD", "STK11|LUAD"],
        n_hits=2,
    )
    rows = bel.build_rows({"scans": scans})
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "arm_loss_sl_scan"
    assert r["target"] == "KRAS" and r["indication"] == "discovery"
    assert r["release_pin"] == "unpinned"
    assert r["framework_version"] == "scan-0.1.0"
    assert r["n_hits"] == 2
    assert r["nominated_target_indications"] == ["MTAP|LUAD", "STK11|LUAD"]
    # federation key is sorted + carries the shared products
    assert r["input_manifest_ids"] == ["pancan-arm-cnv-per-sample-v1", "synlethdb-sl-partners-per-gene-v1"]
    assert r["fired_rule_ids"] == []  # discovery scan: no resolver rules
    # core fields non-empty so the row keys + self-checks cleanly
    assert all(r.get(k) not in (None, "") for k in bel._ROW_CORE)


def test_by_manifest_id_links_scan_and_eval(tmp_path):
    """The discovery edge: an evidence_package and a scan that read the SAME product both appear
    under by_manifest_id[that_product] — joining evaluation and discovery layers."""
    products, scans = tmp_path / "products", tmp_path / "scans_root"
    _mk_ep(products, "KRAS", "COADREAD", ["pancan-arm-cnv-per-sample-v1", "tcga-mc3"])
    _mk_scan(scans, "ALL", ["pancan-arm-cnv-per-sample-v1", "synlethdb-sl-partners-per-gene-v1"], ["MTAP|LUAD"])
    rows = bel.build_rows({"products": products, "scans": scans})
    ix = bel.build_indexes(rows)
    shared = ix["by_manifest_id"]["pancan-arm-cnv-per-sample-v1"]
    ep_key = bel.row_key(next(r for r in rows if r["source"] == "evidence_package"))
    scan_key = bel.row_key(next(r for r in rows if r["source"] == "arm_loss_sl_scan"))
    assert ep_key in shared and scan_key in shared  # both layers linked by the shared product
    # products unique to one side map to only that side
    assert ix["by_manifest_id"]["synlethdb-sl-partners-per-gene-v1"] == [scan_key]
    assert ix["by_manifest_id"]["tcga-mc3"] == [ep_key]
    assert ix["n_manifests_indexed"] == 3


def test_self_check_validates_by_manifest_id(tmp_path):
    scans = tmp_path / "scans_root"
    _mk_scan(scans, "ALL", ["m1"], ["X|Y"])
    rows = bel.build_rows({"scans": scans})
    ix = bel.build_indexes(rows)
    lp, ip = tmp_path / "eval_ledger.jsonl", tmp_path / "eval_ledger_index.json"
    lp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    ip.write_text(json.dumps(ix))
    ok, errs = bel.self_check(lp, ip)
    assert ok, errs
    bad = dict(ix)
    bad["by_manifest_id"] = {"m1": ["GHOST|discovery|unpinned|scan-0.1.0|arm_loss_sl_scan"]}
    ip.write_text(json.dumps(bad))
    ok2, errs2 = bel.self_check(lp, ip)
    assert not ok2 and any("by_manifest_id" in e and "unknown row" in e for e in errs2)


def test_build_rows_normalizes_both_sources(tmp_path):
    skills, products = tmp_path / "skills", tmp_path / "products"
    _mk_nomination(
        skills,
        "KRAS",
        "COADREAD",
        "nominate",
        {
            "dependency": {
                "verdict": "lineage_selective",
                "driving_rule_id": "r1",
                "fired_rule_ids": ["r1", "r2"],
                "cards_used": ["c1"],
                "cards_missing": [],
            }
        },
        fragility={"target_index": 0.57, "recommendation_fragility_index": 0.05, "contested": False},
    )
    _mk_ep(products, "KRAS", "COADREAD", ["m1", "m2"])
    rows = bel.build_rows({"skills": skills, "products": products})
    assert len(rows) == 2

    tp = next(r for r in rows if r["source"] == "target_profile")
    assert tp["recommendation"] == "nominate"
    assert tp["fired_rule_ids"] == ["r1", "r2"]
    assert tp["fragility"]["contested"] is False
    assert tp["sub_verdicts"][0]["cards_used"] == ["c1"]  # the #390 reproducibility field
    assert tp["release_pin"] == "unpinned"

    ep = next(r for r in rows if r["source"] == "evidence_package")
    assert ep["input_manifest_ids"] == ["m1", "m2"]  # federation key; excluded card excluded
    assert ep["recommendation"] is None  # evidence_package has no composed rec


def test_build_rows_reads_fragility_from_target_report_when_top_level_absent(tmp_path):
    # Forward-compat: a post-Wave-3 nomination drops the top-level `fragility` key and carries it only under
    # target_report.robustness.fragility. The ledger must still populate the fragility row (same object).
    skills, products = tmp_path / "skills", tmp_path / "products"
    _mk_nomination(
        skills,
        "KRAS",
        "COADREAD",
        "nominate",
        {
            "dependency": {
                "verdict": "lineage_selective",
                "driving_rule_id": "r1",
                "fired_rule_ids": ["r1"],
                "cards_used": [],
                "cards_missing": [],
            }
        },
        fragility={"target_index": 0.57, "recommendation_fragility_index": 0.05, "contested": False},
        fragility_nested=True,
    )
    rows = bel.build_rows({"skills": skills, "products": products})
    tp = next(r for r in rows if r["source"] == "target_profile")
    assert tp["fragility"] == {"target_index": 0.57, "recommendation_fragility_index": 0.05, "contested": False}


def test_indexes_rule_cohort_and_trend(tmp_path):
    skills, products = tmp_path / "skills", tmp_path / "products"
    _mk_nomination(
        skills,
        "KRAS",
        "COADREAD",
        "nominate",
        {
            "dependency": {
                "verdict": "x",
                "driving_rule_id": "r1",
                "fired_rule_ids": ["r1"],
                "cards_used": [],
                "cards_missing": [],
            }
        },
    )
    _mk_ep(products, "KRAS", "COADREAD", ["m1"])
    rows = bel.build_rows({"skills": skills, "products": products})
    ix = bel.build_indexes(rows)
    tp_key = bel.row_key(next(r for r in rows if r["source"] == "target_profile"))
    assert ix["by_rule_id"]["r1"] == [tp_key]  # rule cohort
    trend = ix["by_target_indication"]["KRAS|COADREAD"]  # both sources land under one t×i
    assert {e["source"] for e in trend} == {"target_profile", "evidence_package"}
    assert ix["n_rows"] == 2


def test_self_check_ok_and_detects_tamper(tmp_path):
    skills, products = tmp_path / "skills", tmp_path / "products"
    _mk_nomination(
        skills,
        "KRAS",
        "COADREAD",
        "nominate",
        {
            "dependency": {
                "verdict": "x",
                "driving_rule_id": "r1",
                "fired_rule_ids": ["r1"],
                "cards_used": [],
                "cards_missing": [],
            }
        },
    )
    rows = bel.build_rows({"skills": skills, "products": products})
    ix = bel.build_indexes(rows)
    lp, ip = tmp_path / "eval_ledger.jsonl", tmp_path / "eval_ledger_index.json"
    lp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    ip.write_text(json.dumps(ix))
    ok, errs = bel.self_check(lp, ip)
    assert ok, errs
    # tamper: point an index entry at a row that does not exist → self-check must catch it.
    bad = dict(ix)
    bad["by_rule_id"] = {"r1": ["GHOST|X|unpinned|1.0.0|target_profile"]}
    ip.write_text(json.dumps(bad))
    ok2, errs2 = bel.self_check(lp, ip)
    assert not ok2 and any("unknown row" in e for e in errs2)


def test_committed_ledger_self_consistent():
    """The ledger committed in this repo must pass self-check (mirrors the framework_health CI gate)."""
    ok, errs = bel.self_check(bel.LEDGER_PATH, bel.INDEX_PATH)
    assert ok, errs


def test_resolved_release_digest_propagates_to_row_and_trend():
    """Governance release-fingerprint (2026-08-12): resolved_release_digest + resolved_releases drift
    flow from an evidence_package's governance into the ledger row AND the by_target_indication trend
    entry, and n_stale_families counts drifted families."""
    ep = {
        "framework_version": "2.0.0",
        "generated_at": "2026-08-12T00:00:00Z",
        "context": {"target": {"symbol": "KRAS"}, "indication": {"oncotree_code": "COADREAD"}},
        "governance": {
            "data_mode": "latest_approved",
            "release_pin": "unpinned",
            "resolved_release_digest": "abc123def4567890",
            "resolved_releases": {
                "depmap-chronos": {"used": ["depmap-chronos-25q4"], "head": "depmap-chronos-26q1", "is_stale": True},
                "tcga-mc3": {"used": ["tcga-mc3-v2"], "head": "tcga-mc3-v2", "is_stale": False},
            },
        },
        "cards": [
            {
                "card_id": "c1",
                "validation_state": "pass",
                "interpretation_call": "informative",
                "provenance": {"input_manifest_ids": ["depmap-chronos-25q4", "tcga-mc3-v2"]},
            }
        ],
    }
    row = bel.row_from_evidence_package(Path("ep.json"), ep)
    assert row["resolved_release_digest"] == "abc123def4567890"
    assert row["n_stale_families"] == 1  # only depmap-chronos is stale
    ix = bel.build_indexes([row])
    trend = ix["by_target_indication"]["KRAS|COADREAD"][0]
    assert trend["resolved_release_digest"] == "abc123def4567890"
