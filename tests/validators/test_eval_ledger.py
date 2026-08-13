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


def _mk_nomination(root: Path, target, indication, rec, sub, fragility=None, release_pin=None):
    d = root / "docs" / "examples" / f"tp-{target}-{indication}"
    d.mkdir(parents=True, exist_ok=True)
    nm = {
        "skill": "target-profile", "skill_version": "1.0.0", "target": target, "indication": indication,
        "generated_at": "2026-08-12T00:00:00Z",
        "governance": {"data_mode": "live_latest", "release_pin": release_pin or "unpinned"},
        "sub_verdicts": sub,
        "llm_synthesis": {"overall_recommendation": {"value": rec}},
    }
    if fragility:
        nm["fragility"] = fragility
    (d / "nomination.json").write_text(json.dumps(nm))


def _mk_ep(root: Path, target, indication, manifests):
    d = root / target / indication / f"ep-{target}-{indication}"
    d.mkdir(parents=True, exist_ok=True)
    ep = {
        "framework_version": "2.0.0", "generated_at": "2026-08-01T00:00:00Z",
        "context": {"target": {"symbol": target}, "indication": {"oncotree_code": indication}},
        "governance": {"data_mode": "latest_approved", "release_pin": "unpinned"},
        "cards": [
            {"card_id": "c1", "validation_state": "pass", "interpretation_call": "informative",
             "provenance": {"input_manifest_ids": manifests}},
            {"card_id": "c2", "excluded_by_applies_when": True},   # excluded → contributes nothing
        ],
    }
    (d / "evidence_package.json").write_text(json.dumps(ep))


def test_build_rows_normalizes_both_sources(tmp_path):
    skills, products = tmp_path / "skills", tmp_path / "products"
    _mk_nomination(skills, "KRAS", "COADREAD", "nominate",
                   {"dependency": {"verdict": "lineage_selective", "driving_rule_id": "r1",
                                   "fired_rule_ids": ["r1", "r2"], "cards_used": ["c1"], "cards_missing": []}},
                   fragility={"target_index": 0.57, "recommendation_fragility_index": 0.05, "contested": False})
    _mk_ep(products, "KRAS", "COADREAD", ["m1", "m2"])
    rows = bel.build_rows({"skills": skills, "products": products})
    assert len(rows) == 2

    tp = next(r for r in rows if r["source"] == "target_profile")
    assert tp["recommendation"] == "nominate"
    assert tp["fired_rule_ids"] == ["r1", "r2"]
    assert tp["fragility"]["contested"] is False
    assert tp["sub_verdicts"][0]["cards_used"] == ["c1"]     # the #390 reproducibility field
    assert tp["release_pin"] == "unpinned"

    ep = next(r for r in rows if r["source"] == "evidence_package")
    assert ep["input_manifest_ids"] == ["m1", "m2"]          # federation key; excluded card excluded
    assert ep["recommendation"] is None                      # evidence_package has no composed rec


def test_indexes_rule_cohort_and_trend(tmp_path):
    skills, products = tmp_path / "skills", tmp_path / "products"
    _mk_nomination(skills, "KRAS", "COADREAD", "nominate",
                   {"dependency": {"verdict": "x", "driving_rule_id": "r1", "fired_rule_ids": ["r1"],
                                   "cards_used": [], "cards_missing": []}})
    _mk_ep(products, "KRAS", "COADREAD", ["m1"])
    rows = bel.build_rows({"skills": skills, "products": products})
    ix = bel.build_indexes(rows)
    tp_key = bel.row_key(next(r for r in rows if r["source"] == "target_profile"))
    assert ix["by_rule_id"]["r1"] == [tp_key]                 # rule cohort
    trend = ix["by_target_indication"]["KRAS|COADREAD"]       # both sources land under one t×i
    assert {e["source"] for e in trend} == {"target_profile", "evidence_package"}
    assert ix["n_rows"] == 2


def test_self_check_ok_and_detects_tamper(tmp_path):
    skills, products = tmp_path / "skills", tmp_path / "products"
    _mk_nomination(skills, "KRAS", "COADREAD", "nominate",
                   {"dependency": {"verdict": "x", "driving_rule_id": "r1", "fired_rule_ids": ["r1"],
                                   "cards_used": [], "cards_missing": []}})
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
        "framework_version": "2.0.0", "generated_at": "2026-08-12T00:00:00Z",
        "context": {"target": {"symbol": "KRAS"}, "indication": {"oncotree_code": "COADREAD"}},
        "governance": {
            "data_mode": "latest_approved", "release_pin": "unpinned",
            "resolved_release_digest": "abc123def4567890",
            "resolved_releases": {
                "depmap-chronos": {"used": ["depmap-chronos-25q4"], "head": "depmap-chronos-26q1",
                                   "is_stale": True},
                "tcga-mc3": {"used": ["tcga-mc3-v2"], "head": "tcga-mc3-v2", "is_stale": False},
            },
        },
        "cards": [{"card_id": "c1", "validation_state": "pass", "interpretation_call": "informative",
                   "provenance": {"input_manifest_ids": ["depmap-chronos-25q4", "tcga-mc3-v2"]}}],
    }
    row = bel.row_from_evidence_package(Path("ep.json"), ep)
    assert row["resolved_release_digest"] == "abc123def4567890"
    assert row["n_stale_families"] == 1                       # only depmap-chronos is stale
    ix = bel.build_indexes([row])
    trend = ix["by_target_indication"]["KRAS|COADREAD"][0]
    assert trend["resolved_release_digest"] == "abc123def4567890"
