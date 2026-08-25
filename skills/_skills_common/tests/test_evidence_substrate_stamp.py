"""evidence_substrate stamping (cross-evidence roadmap invariant 8 — "independence before certainty").

Pins:
  1. The measurement_types loader helpers (card_measurement_type / evidence_substrate_of /
     substrate_for_card) resolve a card -> its measurement_type -> the type's evidence_substrate,
     driven ENTIRELY by the registry (hermetic fixture via MEASUREMENT_TYPES_YAML).
  2. assemble_evidence_package(stamp_evidence_substrate=True) stamps measurement_type +
     evidence_substrate on each present card entry AND the declared required_product_ids under
     provenance.
  3. The DEFAULT (stamp_evidence_substrate=False) is byte-stable — NO new keys appear, so every
     existing caller (compose-dashboard byte-golden, target-profile --emit, subskill --emit-envelope)
     is byte-identical and keeps validating against the un-updated evidence_package.schema.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import _skills_common.measurement_types as MT  # noqa: E402
from _skills_common.envelope import assemble_evidence_package  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_measurement_types_cache():
    """These tests repoint MEASUREMENT_TYPES_YAML at a hermetic fixture and clear the memoized
    registry readers so the fixture (not the real registry) is used. `monkeypatch.setenv` reverts the
    env var at teardown, but it CANNOT un-poison the lru_cache — so without an explicit teardown clear
    the fixture (or the intentionally-missing-file registry) LEAKS into every later test in the
    session. That silently broke the cross-evidence spine contract guard
    (skills/tests/test_cross_evidence_spine_contract.py), which then saw `cards[].evidence_substrate`
    vanish only when run AFTER this module. Clear on BOTH sides so each test — here and downstream —
    re-reads the real registry."""
    MT._load_registry.cache_clear()
    MT._card_to_type_map.cache_clear()
    yield
    MT._load_registry.cache_clear()
    MT._card_to_type_map.cache_clear()


_FIXTURE_REGISTRY = {
    "schema_version": 1,
    "entity_grain_vocabulary": {"target_indication": {"partition_required": False}},
    "evidence_tiers": ["measured", "inferred", "estimated"],
    "evidence_substrates": {
        "recount3_tcga_gtex_bulk_rna": {"description": "shared recount3 tumor/normal RNA counts"},
    },
    "measurement_types": {
        "tumor_vs_normal_selectivity": {
            "claim": "selectivity",
            "entity_grains": ["target_indication"],
            "evidence_substrate": "recount3_tcga_gtex_bulk_rna",
            "cards": ["tumor-vs-normal-selectivity"],
            "providers": [{"kind": "dataset", "source": "coadread-dge", "evidence_tier": "measured"}],
        },
        # a genuinely-independent singleton (no substrate tag)
        "target_identity": {
            "claim": "identity",
            "entity_grains": ["target_indication"],
            "cards": ["target-identity-summary"],
            "providers": [{"kind": "dataset", "source": "resolver", "evidence_tier": "measured"}],
        },
    },
}


def _point_loader_at(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "measurement_types.yaml"
    reg.write_text(yaml.safe_dump(_FIXTURE_REGISTRY))
    monkeypatch.setenv("MEASUREMENT_TYPES_YAML", str(reg))
    # both memoized readers must be reset so the fixture (not a prior real read) is used
    MT._load_registry.cache_clear()
    MT._card_to_type_map.cache_clear()


def test_loader_resolves_card_type_and_substrate(tmp_path, monkeypatch):
    _point_loader_at(tmp_path, monkeypatch)
    assert MT.card_measurement_type("tumor-vs-normal-selectivity") == "tumor_vs_normal_selectivity"
    assert MT.evidence_substrate_of("tumor_vs_normal_selectivity") == "recount3_tcga_gtex_bulk_rna"
    mt, sub = MT.substrate_for_card("tumor-vs-normal-selectivity")
    assert (mt, sub) == ("tumor_vs_normal_selectivity", "recount3_tcga_gtex_bulk_rna")


def test_untagged_type_has_no_substrate(tmp_path, monkeypatch):
    _point_loader_at(tmp_path, monkeypatch)
    mt, sub = MT.substrate_for_card("target-identity-summary")
    assert mt == "target_identity" and sub is None


def test_unmigrated_card_resolves_to_none(tmp_path, monkeypatch):
    _point_loader_at(tmp_path, monkeypatch)
    assert MT.substrate_for_card("some-card-not-in-any-type") == (None, None)


# --- stamping on the envelope ----------------------------------------------------------------

_CTX = {"target_symbol": "KRAS", "indication": "COADREAD", "data_mode": "exploratory"}
_VS = {"n_cards_attempted": 1, "n_cards_passed": 1, "n_cards_passed_with_warnings": 0,
       "n_cards_failed": 0, "n_cards_excluded_by_applies_when": 0}
_SYN = {"headline": "test headline"}


def _one_card_outputs():
    return [{
        "card_id": "tumor-vs-normal-selectivity",
        "card_version": "1.0.0",
        "validation_state": "pass",
        "summary": {"selectivity_class": "tumor_selective"},
        "interpretation_call": "tumor_selective",
        "provenance": {"method_calls": [], "input_manifest_ids": ["coadread-dge-tumor-vs-normal-sensitivity-v1"]},
    }]


def _assemble(stamp: bool):
    return assemble_evidence_package(
        input_context=_CTX, card_outputs=_one_card_outputs(), validation_summary=_VS,
        synthesis_block=_SYN, deterministic_timestamps=True, framework_version="2.0.0",
        generated_by="skills/test@abc123", dashboard_spec_ref="skill:test",
        stamp_evidence_substrate=stamp,
    )


def test_stamp_on_adds_all_three_fields(tmp_path, monkeypatch):
    _point_loader_at(tmp_path, monkeypatch)
    # required_product_ids reads the card spec's required_inputs; stub it so the test is hermetic
    # (independent of a target-contracts checkout).
    import _skills_common as SC
    monkeypatch.setattr(SC, "card_input_manifest_ids",
                        lambda cid: ("coadread-dge-tumor-vs-normal-sensitivity-v1",))
    ep = _assemble(stamp=True)
    entry = next(c for c in ep["cards"] if c.get("card_id") == "tumor-vs-normal-selectivity")
    assert entry["measurement_type"] == "tumor_vs_normal_selectivity"
    assert entry["evidence_substrate"] == "recount3_tcga_gtex_bulk_rna"
    assert entry["provenance"]["required_product_ids"] == ["coadread-dge-tumor-vs-normal-sensitivity-v1"]


def test_stamp_off_is_byte_stable(tmp_path, monkeypatch):
    """Default: no measurement_type / evidence_substrate / required_product_ids keys anywhere."""
    _point_loader_at(tmp_path, monkeypatch)
    ep = _assemble(stamp=False)
    entry = next(c for c in ep["cards"] if c.get("card_id") == "tumor-vs-normal-selectivity")
    assert "measurement_type" not in entry
    assert "evidence_substrate" not in entry
    assert "required_product_ids" not in entry["provenance"]


def test_stamp_never_raises_when_registry_unreachable(tmp_path, monkeypatch):
    """A skills-only checkout (no reachable registry) stamps nothing and must not crash."""
    monkeypatch.setenv("MEASUREMENT_TYPES_YAML", str(tmp_path / "does-not-exist.yaml"))
    MT._load_registry.cache_clear()
    MT._card_to_type_map.cache_clear()
    ep = _assemble(stamp=True)  # must not raise
    entry = next(c for c in ep["cards"] if c.get("card_id") == "tumor-vs-normal-selectivity")
    assert "evidence_substrate" not in entry  # unresolved -> omitted
