#!/usr/bin/env python3
"""Teeth for eval/loop/substrate.py (SK#2303 WI-B).

Acceptance (#2347):
  - real emitted packages for >=3 families spanning BOTH token keys (concordance_class /
    qualifier_class) and BOTH source_support containers (list / dict) assemble with NO shape-loss and
    NO fabricated (family, None) / empty-arm artifacts;
  - a qualifier_class family and a dict-source_support family both survive assembly intact;
  - a mutated normaliser that assumes list-shape FAILS the test (the dict-source_support arms collapse);
  - run_health / read_error are read FIRST — a dead package is NULL-everything, never data.

Fixtures ``{ceacam5,epcam}_coadread_emitted.json`` are REAL ``run.py --emit-envelope`` outputs
(evidence_package + decision.run_health), captured 2026-10-01 against trunk tumor-presence 1.25.0.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_LOOP = Path(__file__).resolve().parents[1]
if str(_LOOP) not in sys.path:
    sys.path.insert(0, str(_LOOP))

import substrate as S  # noqa: E402

_FIX = Path(__file__).resolve().parent / "fixtures"

# The 5 L2b families tumor-presence emits, their token key, and their source_support container shape.
_EXPECTED = {
    "tumor_presence_concordance": ("concordance_class", list),
    "bulk_vs_singlecell_coverage_concordance": ("concordance_class", dict),
    "protein_presence_concordance": ("concordance_class", list),
    "cellline_heterogeneity_lineage_qualifier": ("qualifier_class", type(None)),
    "subtype_restriction_concordance": ("concordance_class", list),
}
_QUALIFIER = "cellline_heterogeneity_lineage_qualifier"
_COVERAGE = "bulk_vs_singlecell_coverage_concordance"


def _load(name: str) -> dict:
    return json.loads((_FIX / f"{name}_coadread_emitted.json").read_text())


def _assemble(name: str) -> dict:
    bundle = _load(name)
    return S.assemble_from_objects(bundle["evidence_package"], bundle["decision"])


@pytest.fixture(params=["ceacam5", "epcam"])
def real_name(request):
    return request.param


# ── the substrate itself ─────────────────────────────────────────────────────────────────────────────
def test_real_package_assembles_live(real_name):
    out = _assemble(real_name)
    assert out["null_everything"] is False
    assert out["run_health"]["n_cards_resolved"] > 0


def test_spans_both_token_keys_and_both_containers(real_name):
    """>=3 families, BOTH token keys, BOTH source_support containers — the acceptance spanning check."""
    bundle = _load(real_name)
    integrated = bundle["evidence_package"]["integrated_properties"]
    out = _assemble(real_name)
    l2b = out["l2b"]
    assert len(l2b) >= 3
    token_keys = {v["token_key"] for v in l2b.values()}
    assert {"concordance_class", "qualifier_class"} <= token_keys
    containers = {type((integrated[f].get("source_support"))) for f in l2b}
    assert dict in containers and list in containers


def test_no_fabricated_none_token_or_phantom_pair(real_name):
    """A hard-coded concordance_class read fabricates a (family, None) pair (plan §5A.7). Every family
    resolves a real token or the loud MISSING_TOKEN sentinel — NEVER a bare None."""
    out = _assemble(real_name)
    for family, v in out["l2b"].items():
        assert v["token"] is not None, family
        assert v["token"] != S.MISSING_TOKEN, family  # all 5 real families carry a token
    assert out["families_missing_token"] == []


def test_raw_island_is_verbatim_no_shape_loss(real_name):
    """The raw island is carried byte-for-byte — the assembler flattens nothing."""
    bundle = _load(real_name)
    integrated = bundle["evidence_package"]["integrated_properties"]
    out = _assemble(real_name)
    for family, v in out["l2b"].items():
        assert v["raw_island"] == integrated[family]


def test_qualifier_family_survives_intact(real_name):
    """The qualifier_class family (no governed concordance enum, no arms) is read as a qualifier, with
    its guards_misread carried into the contract — never misread as a concordance class."""
    out = _assemble(real_name)
    q = out["l2b"][_QUALIFIER]
    assert q["token_key"] == "qualifier_class"
    assert q["token"] == "cellline_heterogeneity_is_cross_lineage"
    assert q["arms"] == []  # a qualifier folds no arms
    contract = out["field_contracts"][_QUALIFIER]
    assert contract["disposition"] == "qualifier"
    assert contract["guards_misread"] == "within_tumour_antigen_negative_escape"


def test_dict_source_support_family_both_arms_survive(real_name):
    """The dict-source_support coverage family keeps BOTH arms (bulk + single-cell) — the ERBB2
    'empty arms' artifact (iterating a dict as a list) does NOT appear."""
    out = _assemble(real_name)
    cov = out["l2b"][_COVERAGE]
    sources = {a["source"] for a in cov["arms"]}
    assert sources == {"bulk_tumor_presence", "single_cell_malignant_coverage"}
    assert all(a["source"] for a in cov["arms"])  # no empty-source arm


def test_list_source_support_arms_carry_datum(real_name):
    """A list-source_support family's arms carry their L1 datum + class (the labels are abstractions to
    audit AGAINST the numbers)."""
    out = _assemble(real_name)
    arms = out["l2b"]["tumor_presence_concordance"]["arms"]
    assert len(arms) >= 1
    bulk = next((a for a in arms if a["source"] == "bulk_rna"), None)
    assert bulk is not None
    assert bulk["class"] is not None
    assert isinstance(bulk["datum"], dict) and bulk["datum"]  # retained_quantitative numbers present


def test_l2a_anchors_are_numbers(real_name):
    """L2a carries the anchor NUMBERS, not just the property label."""
    out = _assemble(real_name)
    assert out["l2a"]  # families present
    some = next(iter(out["l2a"].values()))
    assert "anchors" in some and isinstance(some["anchors"], dict)
    assert any(isinstance(v, (int, float)) for v in some["anchors"].values())


def test_field_contracts_corroboration_and_disposition(real_name):
    """field_contracts carries the corroboration semantics + a governed concordance token's disposition
    semantics (the guardrail that killed the CD274 false positive)."""
    out = _assemble(real_name)
    fc = out["field_contracts"]
    assert fc["_corroboration"] == S.CORROBORATION_CONTRACT
    tp = fc["tumor_presence_concordance"]
    assert tp["disposition"] == "concordant"
    assert tp["disposition_semantics"]  # the one-line disposition definition from the enum


# ── the mutation tooth: a list-assuming normaliser must fail ─────────────────────────────────────────
def _list_only_iter(island: dict):
    """A DELIBERATELY-WRONG normaliser that assumes source_support is always a list. Iterating a dict
    this way yields its KEYS (strings), which the isinstance filter drops ⇒ zero arms. This is the bug
    the production iter_source_support exists to prevent."""
    return [(None, v) for v in (island.get("source_support") or []) if isinstance(v, dict)]


def test_mutated_list_only_normaliser_collapses_dict_arms():
    """TOOTH: the shape-aware primitive reads both arms off a dict-source_support family; a list-only
    normaliser reads ZERO. If someone replaces iter_source_support with a list-only impl, the arm count
    drops and the real-package tests above fail."""
    bundle = _load("ceacam5")
    coverage_island = bundle["evidence_package"]["integrated_properties"][_COVERAGE]
    assert isinstance(coverage_island.get("source_support"), dict)  # premise: this family IS dict-shaped
    assert len(S.iter_source_support(coverage_island)) == 2  # production: both arms
    assert len(_list_only_iter(coverage_island)) == 0  # the mutant: silently empty


def test_mutated_normaliser_fails_assembly(monkeypatch):
    """TOOTH end-to-end: swap in the list-only normaliser and the dict family's arms vanish — exactly
    the regression test_dict_source_support_family_both_arms_survive catches."""
    monkeypatch.setattr(S, "iter_source_support", _list_only_iter)
    out = _assemble("ceacam5")
    assert out["l2b"][_COVERAGE]["arms"] == []  # mutated → empty-arm artifact returns


# ── run_health / read_error read FIRST ───────────────────────────────────────────────────────────────
def test_dead_package_is_null_everything():
    """n_cards_resolved == 0 ⇒ NULL-everything (never data). The L2b sections are present in the package
    but must NOT be read as measurements."""
    bundle = _load("ceacam5")
    ep = bundle["evidence_package"]
    assert ep.get("integrated_properties")  # the sections ARE there
    out = S.assemble_from_objects(ep, {"run_health": {"status": "ok", "n_cards_resolved": 0}})
    assert out["null_everything"] is True
    assert "dead package" in out["null_reason"]
    assert out["l2b"] == {} and out["l2a"] == {} and out["l3"] is None


def test_missing_run_health_is_null_everything():
    """NULL tooth: strip run_health ⇒ cannot vouch the package is live ⇒ NULL-everything, never clean."""
    bundle = _load("ceacam5")
    out = S.assemble_from_objects(bundle["evidence_package"], None)
    assert out["null_everything"] is True
    assert out["null_reason"] == "no run_health section"
    assert out["l2b"] == {}


def test_degraded_status_is_still_data():
    """`degraded` is the NORMAL per-triple state (plan §5A.6), NOT a dead package — status must NOT gate.
    A degraded run with resolved cards assembles its L2b."""
    bundle = _load("ceacam5")
    ep = bundle["evidence_package"]
    out = S.assemble_from_objects(ep, {"run_health": {"status": "degraded", "n_cards_resolved": 16}})
    assert out["null_everything"] is False
    assert len(out["l2b"]) == 5


def test_card_read_error_surfaced():
    """A per-card read_error (reader could not look) is surfaced FIRST, distinct from a measured absence."""
    bundle = _load("ceacam5")
    ep = copy.deepcopy(bundle["evidence_package"])
    ep["cards"].append(
        {"card_id": "tumor-rna-distribution", "availability_state": "read_error", "availability_reason": "s3 timeout"}
    )
    out = S.assemble_from_objects(ep, bundle["decision"])
    assert any(e["card_id"] == "tumor-rna-distribution" for e in out["card_read_errors"])
    assert out["card_read_errors"][0]["availability_state"] == "read_error"
