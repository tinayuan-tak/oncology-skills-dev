"""target-profile `--emit evidence-package` — first-class `subtype_resolved` block (Option A).

subtype-first-class-evidence-axis spec (EMIT side). Makes per-stratum subtype SIGNALS
machine-readable in the evidence package so the cross-evidence integrator can later reason at
subtype resolution — WITHOUT changing the deterministic spine's deliberate "subtype = context, not
a gate" treatment. Pins:

  1. DEFAULT (no --subtypes) run: `context.subgroup_spec` stays null AND no `subtype_resolved` key
     is added — byte-stable / additive. (The pre-existing emit goldens in
     test_emit_evidence_package.py cover the full byte-shape; this asserts the two new invariants.)
  2. A subtype-scoped run: `context.subgroup_spec` records the strata (no longer hardcoded null); a
     populated `subtype_resolved` block carries per-stratum records (dependency + mutation-frequency
     axes with evidence_state / subgroup_n / n-floor-met / metric) + the convergence facet.
  3. A stratum below its n-floor is carried with subgroup_n_floor_met=false (absence-discipline: it
     must carry no weight downstream) — the SOFT-context invariant's representable form.
  4. When the contracts schema on disk declares `subtype_resolved`, the emitted --subtypes envelope
     validates against it (skills lands AFTER the contracts schema PR; this asserts once it has).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from _skills_common.compose_core import subskill_composition
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT
from _test_support import load_run_py

CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_subtype")
import tp_evidence_package  # noqa: E402
from tp_fanout import SUBTYPE_SHORT  # noqa: E402

_IDENTITY_CARD = {
    "card_id": "target-identity-summary",
    "summary": {"resolved_hgnc_symbol": "KRAS", "resolved_hgnc_id": 6407},
    "interpretation_call": "resolved",
    "provenance": {"method_calls": [], "input_manifest_ids": []},
}


def _sub(card_id, fired_id, gate, verdict_pair, summary=None):
    cards = [
        {
            "card_id": card_id,
            "summary": summary or {"x": 1},
            "interpretation_call": "informative",
            "provenance": {"method_calls": [], "input_manifest_ids": []},
        }
    ]
    fired = [{"rule_id": fired_id}]
    return {
        "skill_dir": f"dir-{gate or 'none'}",
        "cards": cards,
        "fired": fired,
        "verdict": verdict_pair,
        "composition": subskill_composition(card_outputs=cards, fired=fired, gate=gate, verdict_pair=verdict_pair),
    }


def _subtype_sub_result():
    """A production-shaped SUBTYPE_SHORT result: the two subtype-grain cards, each with a
    per_subgroup_metrics list (MSS measured+floor-cleared; MSI_H underpowered / below-floor)."""
    dep_card = {
        "card_id": "subgroup-stratified-dependency",
        "summary": {
            "per_subgroup_metrics": [
                {
                    "stratum": "MSS",
                    "evidence_state": "measured",
                    "subgroup_n": 42,
                    "subgroup_n_floor_met": True,
                    "chronos_median": -0.6,
                },
                {"stratum": "MSI_H", "evidence_state": "underpowered", "subgroup_n": 4, "subgroup_n_floor_met": False},
            ]
        },
        "interpretation_call": "informative",
        "provenance": {"method_calls": [], "input_manifest_ids": []},
    }
    mut_card = {
        "card_id": "subgroup-stratified-mutation-frequency",
        "summary": {
            "per_subgroup_metrics": [
                {
                    "stratum": "MSS",
                    "evidence_state": "measured",
                    "subgroup_n": 310,
                    "subgroup_n_floor_met": True,
                    "mutated_fraction": 0.41,
                },
            ]
        },
        "interpretation_call": "informative",
        "provenance": {"method_calls": [], "input_manifest_ids": []},
    }
    cards = [dep_card, mut_card]
    fired: list = []
    return {
        "skill_dir": None,
        "cards": cards,
        "fired": fired,
        "verdict": ("subtype_specific_non_dependence", "subtype-01"),
        "scope_subtypes": ["MSI_H", "MSS"],
        "composition": subskill_composition(
            card_outputs=cards, fired=fired, gate=None, verdict_pair=("subtype_specific_non_dependence", "subtype-01")
        ),
    }


def _base_sub_results():
    return {
        "expression": _sub("tumor-rna-distribution", "expr-01", None, ("tumor_broadly_expressed", "expr-01")),
        "dependency": _sub(
            "pan-cancer-crispr-dependency-distribution", "dep-01", "dependency", ("selective_dependency", "dep-01")
        ),
    }


def _emit(tmp_path, monkeypatch, *, subtypes, subtype_facet=None, skip_schema=False):
    monkeypatch.setattr(
        tp_evidence_package, "resolve_cards", lambda card_ids, target, indication, **kw: [dict(_IDENTITY_CARD)]
    )
    if skip_schema:
        # Emitter validates the envelope against the contracts checkout's schema. Until the sibling
        # contracts PR (subtype_resolved schema) is on that checkout's main, the new key trips
        # unevaluatedProperties:false. Neutralize ONLY the internal validator so the block-shape
        # assertions run pre-merge; the schema-valid assertion is a separate, guarded test.
        monkeypatch.setattr(tp_evidence_package, "_validate_evidence_package", lambda ep, root: [])
    sub_results = _base_sub_results()
    if subtypes:
        sub_results[SUBTYPE_SHORT] = _subtype_sub_result()
    args = SimpleNamespace(target="KRAS", indication="COADREAD", release_pin=None, out=tmp_path)
    ep_path = tp._write_evidence_package(
        args=args,
        sub_results=sub_results,
        gate_action=None,
        recommendation_gate={"fired": False, "suppressed_vetoes": []},
        confidence_tier={"tier": "moderate"},
        deciding_axis={"basis": "positive_signal", "deciding_axes": [{"short": "dependency"}]},
        validation_summary={
            "n_cards_attempted": 2,
            "n_cards_passed": 2,
            "n_cards_passed_with_warnings": 0,
            "n_cards_failed": 0,
            "n_cards_excluded_by_applies_when": 0,
        },
        subtypes=subtypes,
        subtype_facet=subtype_facet,
    )
    return json.loads(Path(ep_path).read_text())


# ---------- (1) default run: byte-stable / additive ----------


def test_default_run_subgroup_spec_null_and_no_block(tmp_path, monkeypatch):
    ep = _emit(tmp_path, monkeypatch, subtypes=None)
    assert ep["context"]["subgroup_spec"] is None
    assert "subtype_resolved" not in ep


# ---------- (2) subtype-scoped run: populated block ----------


def test_subtypes_run_populates_subgroup_spec_and_block(tmp_path, monkeypatch):
    facet = {
        "verdict": "single_axis_stratification",
        "convergent_subtypes": [],
        "associated_subtypes": [],
        "per_subtype": {},
    }
    ep = _emit(tmp_path, monkeypatch, subtypes=["MSI_H", "MSS"], subtype_facet=facet, skip_schema=True)
    assert ep["context"]["subgroup_spec"] == ["MSI_H", "MSS"]
    block = ep["subtype_resolved"]
    assert block["schema_version"] == 1
    assert block["requested_strata"] == ["MSI_H", "MSS"]
    assert set(block["available_strata"]) == {"MSI_H", "MSS"}
    # convergence facet embedded (previously dropped from the package)
    assert block["convergence_facet"] == facet
    # per-stratum records, sorted by stratum
    strata = {r["stratum"]: r for r in block["per_stratum"]}
    assert set(strata) == {"MSI_H", "MSS"}
    mss = strata["MSS"]
    assert set(mss["axes"]) == {"dependency", "mutation_frequency"}
    assert mss["axes"]["dependency"]["evidence_state"] == "measured"
    assert mss["axes"]["dependency"]["subgroup_n"] == 42
    assert mss["axes"]["dependency"]["subgroup_n_floor_met"] is True
    assert mss["axes"]["dependency"]["metric"] == {"chronos_median": -0.6}
    assert mss["axes"]["mutation_frequency"]["metric"] == {"mutated_fraction": 0.41}


def test_below_floor_stratum_flagged(tmp_path, monkeypatch):
    """MSI_H is underpowered / below n-floor: carried, but subgroup_n_floor_met=false so it carries
    no weight downstream (absence-discipline at stratum grain)."""
    ep = _emit(tmp_path, monkeypatch, subtypes=["MSI_H", "MSS"], skip_schema=True)
    strata = {r["stratum"]: r for r in ep["subtype_resolved"]["per_stratum"]}
    msi_dep = strata["MSI_H"]["axes"]["dependency"]
    assert msi_dep["evidence_state"] == "underpowered"
    assert msi_dep["subgroup_n_floor_met"] is False
    # MSI_H has no mutation-frequency row → axis simply absent (never fabricated)
    assert "mutation_frequency" not in strata["MSI_H"]["axes"]


def test_disclaimer_states_verdict_inert_soft_contract(tmp_path, monkeypatch):
    ep = _emit(tmp_path, monkeypatch, subtypes=["MSS"], skip_schema=True)
    disc = ep["subtype_resolved"]["_disclaimer"].lower()
    assert "not a gate" in disc and "verdict-inert" in disc


# ---------- (4) schema validity (once the contracts schema PR has landed) ----------


def _schema_has_subtype_resolved():
    sp = CONTRACTS / "schemas" / "evidence_package.schema.json"
    if not sp.exists():
        return False
    return "subtype_resolved" in json.loads(sp.read_text()).get("properties", {})


def test_subtypes_envelope_validates_against_schema(tmp_path, monkeypatch):
    if not _schema_has_subtype_resolved():
        pytest.skip(
            "contracts evidence_package.schema.json has no subtype_resolved yet "
            "(sibling PR lands first) — block-shape asserted by the other tests"
        )
    facet = {
        "verdict": "single_axis_stratification",
        "convergent_subtypes": [],
        "associated_subtypes": [],
        "per_subtype": {},
    }
    # do NOT skip schema — the emitter's internal validator must pass (it raises SystemExit otherwise)
    ep = _emit(tmp_path, monkeypatch, subtypes=["MSI_H", "MSS"], subtype_facet=facet, skip_schema=False)
    assert "subtype_resolved" in ep


# ---------- (5) expression / presence axis (2026-08-21) ----------


def test_expression_presence_axis_populated_from_by_subtype_card():
    """The tumor-rna-distribution-by-subtype panorama (under the 'expression' short) now contributes an
    `expression` axis to each stratum record — so the integrator can reason subtype-resolved PRESENCE.
    Uses the reader's own row keys (stratum_id / n_tumor_samples) — n must normalize to subgroup_n and
    bookkeeping keys must NOT leak into the metric."""
    by_subtype_card = {
        "card_id": "tumor-rna-distribution-by-subtype",
        "summary": {
            "subtype_axis_quality": "powered",
            "per_subgroup_metrics": [
                {
                    "stratum_id": "MSS",
                    "evidence_state": "measured",
                    "n_tumor_samples": 193,
                    "subgroup_n_floor_met": True,
                    "match_rate": 0.97,
                    "tumor_expression_class": "tumor_broadly_expressed",
                    "median_log2tpm": 6.2,
                    "subtype_signal": "subtype_enriched",
                    "median_purity": 0.71,
                },
                {
                    "stratum_id": "MSI_H",
                    "evidence_state": "underpowered",
                    "n_tumor_samples": 12,
                    "subgroup_n_floor_met": False,
                    "tumor_expression_class": "data_unavailable",
                },
            ],
        },
        "interpretation_call": "informative",
        "provenance": {"method_calls": [], "input_manifest_ids": []},
    }
    sub_results = {"expression": {"cards": [by_subtype_card]}}
    block = tp_evidence_package._subtype_resolved_block(sub_results, ["MSI_H", "MSS"], None)
    strata = {r["stratum"]: r for r in block["per_stratum"]}
    assert set(strata) == {"MSI_H", "MSS"}
    mss = strata["MSS"]["axes"]["expression"]
    assert mss["evidence_state"] == "measured"
    assert mss["subgroup_n"] == 193  # n_tumor_samples normalized → subgroup_n
    assert mss["subgroup_n_floor_met"] is True
    # metric carries the presence signal, NOT bookkeeping (stratum_id / n_tumor_samples / match_rate)
    assert mss["metric"]["tumor_expression_class"] == "tumor_broadly_expressed"
    assert mss["metric"]["subtype_signal"] == "subtype_enriched"
    assert mss["metric"]["median_purity"] == 0.71
    assert "stratum_id" not in mss["metric"] and "n_tumor_samples" not in mss["metric"]
    # underpowered stratum carried but flagged (absence-discipline)
    assert strata["MSI_H"]["axes"]["expression"]["subgroup_n_floor_met"] is False
