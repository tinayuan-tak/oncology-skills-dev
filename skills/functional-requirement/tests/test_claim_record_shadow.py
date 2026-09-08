"""functional-requirement (dependency) factored-record SHADOW builder (M1) — the CERTAINTY reference
axis. Pins the verdict->record mapping (incl. pan_essential = genuine dependency, valence supports),
the guarded certainty, open-world/negative cases, the fired-set cross-check, and schema conformance.
Consumed-by-nothing / verdict-inert."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _test_support import load_run_py

fr = load_run_py(Path(__file__).resolve().parent.parent, "fr_run_shadow")


def _cards(n=40, cc="concordant_dependent"):
    return [
        {
            "card_id": "pan-cancer-crispr-dependency-distribution",
            # carry the crispr floor_cut_ceiling ruler fields so the claim_record magnitude converges to the
            # display key_evidence.interpretation (Stage-3 one-vocabulary check)
            "summary": {
                "n_cell_lines_evaluated": n,
                "fraction_strongly_dependent": 0.4,
                "median_chronos_panel": -0.4574,
                "dep_control_non_essential_floor": -0.038,
                "dep_control_pan_essential_ceiling": -1.499,
                "dep_control_position_class": "between_controls",
            },
        },
        {"card_id": "cross-consortium-dependency", "summary": {"cross_consortium_class": cc}},
    ]


def _fired(*rids):
    return [{"rule_id": r, "card_id": "pan-cancer-crispr-dependency-distribution"} for r in rids]


def test_concordant_dependent_supports_strong_measured_positive():
    rec = fr._claim_record(
        _cards(),
        fired=_fired("crispr-strong-dependent", "cross-consortium-concordant"),
        verdict_pair=("concordant_dependent", "crispr-strong-dependent"),
    )
    assert rec["axis"] == "dependency"
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["availability"] == "measured_positive"
    assert rec["finding"]["magnitude"]["level"] == "strong"
    assert rec["certainty"]["corroboration"] == "high"  # concordant cross-consortium
    assert rec["provenance"]["fired_rule_ids"] == ["crispr-strong-dependent", "cross-consortium-concordant"]


def test_magnitude_converges_to_the_crispr_display_ruler():
    # Stage-3 convergence: the factored record's magnitude carries the SAME value/scale/distance_to_cut
    # as the display key_evidence.interpretation floor_cut_ceiling ruler (median_chronos_panel vs the
    # -0.5 dependency cut), not just an ordinal level.
    mag = fr._claim_record(
        _cards(),
        fired=_fired("crispr-strong-dependent"),
        verdict_pair=("concordant_dependent", "crispr-strong-dependent"),
    )["finding"]["magnitude"]
    assert mag["level"] == "strong"
    assert mag["value"] == -0.4574 and mag["scale"] == "chronos"
    assert mag["distance_to_cut"] == 0.0426  # value - cut = -0.4574 - (-0.5)


def test_magnitude_stays_level_only_when_driving_summary_stripped():
    # a stripped driving-card summary (no ruler fields) -> level-only, no bare number, byte-stable
    cards = [
        {"card_id": "pan-cancer-crispr-dependency-distribution", "summary": {"n_cell_lines_evaluated": 40}},
        {"card_id": "cross-consortium-dependency", "summary": {"cross_consortium_class": "concordant_dependent"}},
    ]
    mag = fr._claim_record(
        cards, fired=_fired("crispr-strong-dependent"), verdict_pair=("concordant_dependent", "crispr-strong-dependent")
    )["finding"]["magnitude"]
    assert mag["level"] == "strong" and mag["value"] is None and mag["scale"] is None


def test_pan_essential_is_a_genuine_dependency_supports():
    # finding ⊥ interpretation: pan_essential IS dependent (supports); its tox downside is a safety concern
    rec = fr._claim_record(_cards(), fired=[], verdict_pair=("pan_essential_killer", None))
    assert rec["finding"]["direction"] == "supports"
    assert rec["finding"]["magnitude"]["level"] == "strong"
    assert rec["finding"]["availability"] == "measured_positive"


def test_non_dependent_is_measured_negative_opposes():
    rec = fr._claim_record(_cards(cc="concordant_non_dependent"), fired=[], verdict_pair=("non_dependent", None))
    assert rec["finding"]["direction"] == "opposes"
    assert rec["finding"]["availability"] == "measured_negative"


def test_insufficient_is_underpowered_neutral():
    rec = fr._claim_record(_cards(n=2), fired=[], verdict_pair=("insufficient_underpowered", None))
    assert rec["finding"]["availability"] == "insufficient"
    assert rec["finding"]["direction"] == "neutral"


def test_none_verdict_open_world_with_guarded_certainty():
    # empty cards → reference certainty hook would raise (get_card_field); the guard degrades gracefully
    rec = fr._claim_record([], fired=[], verdict_pair=(None, None))
    assert rec["finding"]["availability"] == "not_wired"
    assert rec["finding"]["state"] == "unknown" and rec["finding"]["direction"] == "neutral"
    assert rec["certainty"] == {"level": "low", "coverage": "low", "corroboration": "unmeasured", "unknown_mass": 1.0}


def _schema():
    try:
        from _skills_common.scope import DEFAULT_CONTRACTS_REPO
        from jsonschema import Draft202012Validator  # noqa: F401
    except Exception:
        return None
    p = Path(DEFAULT_CONTRACTS_REPO) / "schemas" / "claim_record.schema.json"
    return json.loads(p.read_text()) if p.exists() else None


def test_conforms_to_contract_schema_if_available():
    schema = _schema()
    if schema is None:
        pytest.skip("contracts repo / claim_record.schema.json not available")
    from jsonschema import Draft202012Validator

    for v in (
        "concordant_dependent",
        "broadly_dependent",
        "lineage_selective",
        "pan_essential_killer",
        "non_dependent",
        "discordant",
        "insufficient_underpowered",
        None,
    ):
        rec = fr._claim_record(_cards(), fired=[], verdict_pair=(v, None))
        errs = sorted(Draft202012Validator(schema).iter_errors(rec), key=lambda e: e.path)
        assert not errs, f"{v} -> {[e.message for e in errs]}"
