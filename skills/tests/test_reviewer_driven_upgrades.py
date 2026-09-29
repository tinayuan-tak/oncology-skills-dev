"""Framework tests for the arch + content upgrades (2026-07-08).

Consolidates verification tests 6-9 from the plan + a benchmark scaffold test
+ ontology-coverage + license-attestation checks. These tests enforce the
disciplines added in Layer 0 (arch disciplines) + Layer 2 (methods) + Layer 5
(rules/rubric) + Layer 6 (skill graduations).

Test index:
    test_composed_card_dependency_graph        — composed-card dependency graph enforcement
    test_lens_conditional_field_split          — lens-conditional field split enforcement
    test_isoform_selective_warning             — isoform-selective warning enforcement (ERBB2 fires)
    test_on_dependency_status_validation       — on_dependency_status enforcement
    test_signor_moa_ontology_classification    — 21-class MoA taxonomy works
    test_tmbed_license_attestation             — TMbed Apache-2.0 attested in analysis-methods
    test_panel_intersect_fisher_row_schema     — panel-intersect Fisher discipline
    test_all_new_cards_validate                — 11 cards structurally clean
    test_modality_rubric_weights_sum_to_100    — rubric integrity
    test_clinical_precedent_benchmark_shape    — anchor set structure
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR))

# SK#2063 consolidation: target-contracts + analysis-methods are IN-TREE (contracts/, methods/
# under the repo root = SKILLS_DIR.parent). Honor the *_ROOT env vars CI sets, else resolve
# in-tree. data-catalog is still a separate sibling repo (env var, else adjacent checkout).
_REPO_ROOT = SKILLS_DIR.parent
TARGET_CONTRACTS_ROOT = Path(os.environ.get("TARGET_CONTRACTS_ROOT", _REPO_ROOT / "contracts"))
ANALYSIS_METHODS_ROOT = Path(os.environ.get("ANALYSIS_METHODS_ROOT", _REPO_ROOT / "methods"))
DATA_CATALOG_ROOT = Path(
    os.environ.get(
        "DATA_CATALOG_ROOT",
        SKILLS_DIR.parent.parent / "rnd-computational-biology-oncology-data-catalog",
    )
)


# ---------------------------------------------------------------------------
# Composed-card dependency graph
# ---------------------------------------------------------------------------


def test_composed_card_dependency_graph():
    """The composed adc-tce-modality-fit + surface-abundance-density cards
    declare `derived_from:` upstream card_ids; the upstream cards must exist.
    This is the composed-card graph walk in verification form.
    """
    cards_dir = TARGET_CONTRACTS_ROOT / "cards"
    existing_card_ids = set()
    for cf in cards_dir.glob("*.card.yaml"):
        data = yaml.safe_load(cf.read_text())
        existing_card_ids.add(data["card_id"])

    composed_cards_to_check = [
        "adc-tce-modality-fit",
        "surface-abundance-density",
    ]
    for card_id in composed_cards_to_check:
        path = cards_dir / f"{card_id}.card.yaml"
        assert path.exists(), f"expected composed card {card_id} not found"
        data = yaml.safe_load(path.read_text())
        derived_from = data.get("derived_from", [])
        assert derived_from, f"{card_id} must declare derived_from (composed-card semantics)"
        for entry in derived_from:
            upstream_id = entry["card_id"] if isinstance(entry, dict) else entry
            assert upstream_id in existing_card_ids, (
                f"{card_id} derived_from references unknown card '{upstream_id}'; "
                f"existing card_ids: {sorted(existing_card_ids)}"
            )


# ---------------------------------------------------------------------------
# Lens-conditional field split
# ---------------------------------------------------------------------------


def test_lens_conditional_field_split():
    """adc-tce-modality-fit card must have summary_fields that include BOTH
    bare-string entries (biology-agnostic) AND object entries with
    `lens_conditional_on: modality` (letter grades).
    """
    path = TARGET_CONTRACTS_ROOT / "cards" / "adc-tce-modality-fit.card.yaml"
    data = yaml.safe_load(path.read_text())
    fields = data["outputs"]["summary_fields"]

    n_bare = sum(1 for f in fields if isinstance(f, str))
    n_object_lens = sum(1 for f in fields if isinstance(f, dict) and f.get("lens_conditional_on") == "modality")
    assert n_bare >= 3, f"expected biology-agnostic bare fields, got {n_bare}"
    assert n_object_lens >= 4, (
        f"expected >=4 lens_conditional_on=modality fields "
        f"(adc_grade, adc_score, tce_grade, tce_score), got {n_object_lens}"
    )


# ---------------------------------------------------------------------------
# Isoform-selective warning
# ---------------------------------------------------------------------------


def test_isoform_selective_warning_fires_on_known_targets():
    """The isoform-selective vocabulary must fire on the 8 clinically-
    precedented alt-isoform archetypes and return None on generic non-alt-
    isoform targets.
    """
    from _skills_common.isoform_selective_targets import check_target, known_targets

    # Positive controls
    for target, expected_isoform_fragment in [
        ("ERBB2", "p95HER2"),
        ("AR", "AR-V7"),
        ("MET", "exon 14"),
        ("EGFR", "vIII"),
    ]:
        w = check_target(target)
        assert w is not None, f"expected isoform warning for {target}, got None"
        assert expected_isoform_fragment in w.dominant_isoform, (
            f"{target} warning missing '{expected_isoform_fragment}': got {w.dominant_isoform!r}"
        )

    # Negative controls
    for target in ["KRAS", "TP53", "MYC", "ALB"]:
        assert check_target(target) is None, f"unexpected isoform warning for {target}"

    # Coverage: at least 8 targets curated in v1
    assert len(known_targets()) >= 8, f"isoform vocabulary should have >= 8 targets; got {len(known_targets())}"


# ---------------------------------------------------------------------------
# on_dependency_status validation
# ---------------------------------------------------------------------------


def test_on_dependency_status_field_validates():
    """Composition-schema: on_dependency_status field is optional,
    validates when present, references only cards in cards_used.
    """
    from _skills_common.composition_schema import DEPENDENCY_STATUS_BEHAVIORS, validate

    valid = {
        "data_mode": "derived_read",
        "phase": ["G"],
        "cards_used": ["gnomad-lof-constraint", "normal-tissue-liability"],
        "rules_scope": ["gnomad-lof-constraint"],
        "synthesis": ["rule_engine"],
        "output_shape": ["data_package"],
        "steps_covered": [1, 2, 3, 4, 6],
        "status": "partial",
        "on_dependency_status": {"normal-tissue-liability": "skip_section"},
    }
    comp = validate(valid, skill_name="test_skill")
    assert comp.on_dependency_status == {"normal-tissue-liability": "skip_section"}

    # Invalid behavior value
    from _skills_common.composition_schema import CompositionError

    with pytest.raises(CompositionError):
        validate(
            {**valid, "on_dependency_status": {"normal-tissue-liability": "unknown_behavior"}},
            skill_name="test_bad_behavior",
        )

    # References card not in cards_used
    with pytest.raises(CompositionError):
        validate({**valid, "on_dependency_status": {"some-other-card": "skip_section"}}, skill_name="test_bad_ref")

    # Coverage: all three behavior values are valid
    for behavior in DEPENDENCY_STATUS_BEHAVIORS:
        v = {**valid, "on_dependency_status": {"normal-tissue-liability": behavior}}
        comp = validate(v, skill_name=f"test_{behavior}")
        assert comp.on_dependency_status["normal-tissue-liability"] == behavior


# ---------------------------------------------------------------------------
# SIGNOR MoA ontology coverage
# ---------------------------------------------------------------------------


def test_signor_moa_ontology_classification():
    """21-class MoA taxonomy correctly classifies canonical SIGNOR mechanisms."""
    ANALYSIS_METHODS_ROOT = SKILLS_DIR.parent.parent / "rnd-computational-biology-oncology-analysis-methods"
    sys.path.insert(0, str(ANALYSIS_METHODS_ROOT))
    from methods.signor_mechanism_network.moa_ontology import (
        ONTOLOGY_VERSION,
        classify_edge,
        known_moa_classes,
    )

    assert ONTOLOGY_VERSION == "1.0.0"
    assert len(known_moa_classes()) >= 21, f"expected >= 21 MoA classes, got {len(known_moa_classes())}"

    # Positive cases
    cases = [
        ("gtpase-activating protein", "upstream", "upstream_gap_modulation"),
        ("phosphorylation", "upstream", "upstream_kinase_modulation"),
        ("phosphorylation", "downstream", "downstream_pd_kinase"),
        ("binding", "upstream", "molecular_glue_disruptor"),
        ("binding", "downstream", "downstream_pd_marker"),
        ("BINDING", "DOWNSTREAM", "downstream_pd_marker"),  # case-insensitive
    ]
    for mech, direction, expected_class in cases:
        cls = classify_edge(mech, direction)
        assert cls is not None, f"({mech!r}, {direction!r}) returned None"
        assert cls.moa_class == expected_class, (
            f"({mech!r}, {direction!r}) → got {cls.moa_class!r}, expected {expected_class!r}"
        )

    # Negative case: unmapped mechanism returns None
    assert classify_edge("some-novel-mechanism-xyz", "upstream") is None


# ---------------------------------------------------------------------------
# TMbed license attestation
# ---------------------------------------------------------------------------


def test_tmbed_license_attestation():
    """TMbed's Apache-2.0 license must be attested machine-checkably.

    TMbed is a software TOOL (wrapped by analysis-methods
    methods/topology_predictions_tmbed/), not a redistributed dataset — modeling it as a
    data-catalog *source* manifest was tried and deliberately reverted in data-catalog,
    and the Derived-manifest schema carries no license field. So the tool's
    license posture is attested beside the wrapper in LICENSE_ATTRIBUTION.yaml, which this
    test verifies.
    """
    attestation = ANALYSIS_METHODS_ROOT / "methods/topology_predictions_tmbed/LICENSE_ATTRIBUTION.yaml"
    assert attestation.exists(), (
        f"TMbed license attestation missing at {attestation} — the tool license must be "
        f"attested in analysis-methods (data-catalog #111->#113: TMbed is a tool, not a source)."
    )
    data = yaml.safe_load(attestation.read_text())

    # The wrapped predictor (TMbed) is Apache-2.0.
    tool = data.get("tool", {})
    assert tool.get("license_spdx_id") == "Apache-2.0", (
        f"tool.license_spdx_id must be Apache-2.0; got {tool.get('license_spdx_id')!r}"
    )
    # Its ProtT5-XL-U50 encoder dependency is CC-BY-4.0 — attest it too.
    deps = {d.get("name"): d for d in data.get("dependencies", [])}
    assert deps.get("ProtT5-XL-U50", {}).get("license_spdx_id") == "CC-BY-4.0", (
        f"ProtT5-XL-U50 dependency must be attested CC-BY-4.0; got "
        f"{deps.get('ProtT5-XL-U50', {}).get('license_spdx_id')!r}"
    )


# ---------------------------------------------------------------------------
# Fisher panel-intersect discipline
# ---------------------------------------------------------------------------


def test_panel_intersect_fisher_row_schema():
    """The co-mutation card's row schema must declare pooled_eligible + source
    (per-source vs pooled). This is the panel-intersect discipline.
    """
    manifest = DATA_CATALOG_ROOT / "manifests/derived/pancohort-cooccurrence-fisher-v1.yaml"
    data = yaml.safe_load(manifest.read_text())

    schema = data["parquet_schema"]
    field_names = {f["name"] for f in schema}

    assert "pooled_eligible" in field_names, (
        "co-mutation derived manifest must expose pooled_eligible field "
        "(reviewer BLOCKER fix); pooled Q-values only valid when both target "
        "and partner on all GENIE panels."
    )
    assert "source" in field_names, (
        "co-mutation derived manifest must expose source field "
        "(tcga_mc3 | genie_19_public | pooled) — per-source Q-values are "
        "required when pooled_eligible=False."
    )


# ---------------------------------------------------------------------------
# All new cards validate
# ---------------------------------------------------------------------------

NEW_CARDS = [
    "signaling-network-mechanism",
    "co-mutation-and-mutual-exclusivity",
    "surface-topology-and-ptm",
    "surfaceome-family-classification",
    "structure-features-static",
    "adc-tce-modality-fit",
    "surfaceome-cohort-ranking",
    "tumor-protein-abundance-cptac",
    "surface-abundance-density",
    "paralog-buffering",
    "gnomad-lof-constraint",
]


@pytest.mark.parametrize("card_id", NEW_CARDS)
def test_all_new_cards_validate(card_id):
    """Each of the 11 new cards must validate against card.schema.json."""
    import subprocess

    validator = TARGET_CONTRACTS_ROOT / "validators/validate_cards.py"
    card_path = TARGET_CONTRACTS_ROOT / "cards" / f"{card_id}.card.yaml"

    result = subprocess.run(
        [sys.executable, str(validator), str(card_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"validate_cards.py failed on {card_id}:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Modality rubric integrity
# ---------------------------------------------------------------------------


def test_modality_rubric_weights_sum_to_100():
    """ADC + TCE rubric weights must each sum to exactly 100 (invariant for
    score-to-percentage conversion)."""
    rubric_path = SKILLS_DIR / "_skills_common/modality_rubric.yaml"
    data = yaml.safe_load(rubric_path.read_text())

    for modality in ["adc_rubric", "tce_rubric"]:
        weights = data[modality]["weights"]
        total = sum(w["weight"] for w in weights.values())
        assert total == 100, (
            f"{modality} weights must sum to 100; got {total}. Weights: "
            f"{ {k: v['weight'] for k, v in weights.items()} }"
        )

    # Grade thresholds strictly ordered
    for modality in ["adc_rubric", "tce_rubric"]:
        thresholds = data[modality]["grade_thresholds"]
        assert thresholds["A"] > thresholds["B"] > thresholds["C"] > thresholds["D"], (
            f"{modality} grade thresholds must be A > B > C > D; got {thresholds}"
        )


# ---------------------------------------------------------------------------
# Clinical-precedent benchmark shape
# ---------------------------------------------------------------------------


def test_a4_dispatcher_runtime_consumer():
    """The shared dispatcher's _apply_on_dependency_status function honors
    the on_dependency_status map — applies skip_section / emit_with_caveat /
    fail per the SKILL.md composition contract. This test is a UNIT test of
    the dispatcher, not an end-to-end skill test, because it exercises the
    runtime consumer directly with synthetic card_outputs.
    """
    from _skills_common.dispatcher import _apply_on_dependency_status

    # Synthetic card outputs — mix of present + missing
    cards = [
        {"card_id": "card-a", "summary": {"x": 1}, "_missing": False},
        {"card_id": "card-b", "summary": {}, "_missing": True},
        {"card_id": "card-c", "summary": {}, "_missing": True},
    ]

    # behavior: skip missing card-b, emit-with-caveat for missing card-c
    on_dep = {
        "card-b": "skip_section",
        "card-c": "emit_with_caveat",
    }

    surviving, skipped, caveats = _apply_on_dependency_status(cards, on_dep)

    # card-a always present; card-b skipped; card-c retained with caveat
    surviving_ids = {c["card_id"] for c in surviving}
    assert surviving_ids == {"card-a", "card-c"}, f"expected {{card-a, card-c}} surviving, got {surviving_ids}"
    assert skipped == ["card-b"], f"expected ['card-b'] skipped, got {skipped}"
    assert len(caveats) == 1, f"expected 1 caveat, got {len(caveats)}"
    assert "card-c" in caveats[0], f"caveat should mention card-c: {caveats[0]}"

    # Empty on_dep = no-op (default retain all)
    surviving2, skipped2, caveats2 = _apply_on_dependency_status(cards, {})
    assert len(surviving2) == 3
    assert skipped2 == []
    assert caveats2 == []

    # fail behavior raises
    with pytest.raises(RuntimeError, match="'fail'"):
        _apply_on_dependency_status(cards, {"card-b": "fail"})


def test_clinical_precedent_benchmark_shape():
    """The ADC/TCE clinical-precedent anchor set must have enough targets to
    support the AUROC >= 0.80 verification gate."""
    benchmark_path = TARGET_CONTRACTS_ROOT / "vocabularies/adc_tce_clinical_precedent_benchmark.yaml"
    data = yaml.safe_load(benchmark_path.read_text())

    adc_anchors = data.get("adc_positive_anchors", {})
    tce_anchors = data.get("tce_positive_anchors", {})
    negative_anchors = data.get("negative_anchors", {})

    # Plan mandate: ~30 ADC + ~20 TCE anchors + few negatives
    assert len(adc_anchors) >= 20, (
        f"ADC anchor set should have >= 20 targets for the AUROC gate; got {len(adc_anchors)}"
    )
    assert len(tce_anchors) >= 15, f"TCE anchor set should have >= 15 targets; got {len(tce_anchors)}"
    assert len(negative_anchors) >= 3, f"Negative-anchor set should have >= 3 targets; got {len(negative_anchors)}"

    # AUROC gate must be at least 0.80 per plan
    assert data["verification"]["minimum_auroc"] >= 0.80, (
        f"minimum_auroc gate must be >= 0.80 per plan; got {data['verification']['minimum_auroc']}"
    )
