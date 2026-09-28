"""SK#1982 (epic #1779 B3 / parent #1507) — cis-feature-coherence's EXPORTED bounded evidence package
with NAMED top-level sections.

The domain analog of the tumor-presence reference vertical (#1941). cis-feature-coherence exports its
evidence package with the doc's named sections (docs/EVIDENCE_PROPERTY_ARCHITECTURE_L1_L4.md
:259-275), naming ONLY the layers this domain has realized:

  * `integrated_properties` (L2b) — the three landed concordance islands cis_dosage_concordance (#1781),
    methylation_silencing_concordance (#1782), expression_dependency_concordance (#1784).
  * `l3d` — the within-domain cis-regulatory coherence biology story (#1981).

  There is NO `source_properties` (L2a) or `local_composites` section for this domain yet (the
  LEG-decomposition axes are the resolver's verdict-leg decomposition, not a typed carried-composite
  layer), so those keys are DELIBERATELY OMITTED — the export never fabricates a layer it has not
  realized. A future L2a issue can add them.

These pins hold:

  1. FIDELITY / RECONSTRUCTABILITY — `_evidence_sections(headline)` lifts content already on the decision
     headline into the named sections, and every section reconstructs DOWNWARD to L1:
     integrated island provenance.sources[*] card_id · l3d.provenance.claim_ids → the islands. The
     headline is RE-DERIVED from RAW card inputs through the real run.py (the #1780 replay harness) — never
     a stored derived fixture — so a fixture of derived values can never mask a regression.
  2. OMISSION — source_properties / local_composites are NOT emitted (this domain has not realized them).
  3. SCHEMA — a package assembled WITH the sections validates against
     target-contracts/schemas/evidence_package.schema.json (integrated_properties + l3d are declared
     top-level keys; the schema's top-level unevaluatedProperties:false would otherwise reject them).
  4. ADDITIVITY — assembling with evidence_sections=None yields EXACTLY the base top-level key set, and
     assembling WITH the sections adds ONLY the two section keys while every shared key is byte-identical.
     The export is a VIEW; it moves nothing else (verdict-INERT).
"""

from __future__ import annotations

import copy
import json
import os
import runpy
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
SCRIPTS = SKILL_DIR / "scripts"
RUN_PY = SCRIPTS / "run.py"
FIXTURE_DIR = SKILL_DIR / "tests" / "fixtures"
for p in (str(SKILLS_ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common.envelope import assemble_evidence_package  # noqa: E402
from run import _INTEGRATED_ISLAND_KEYS, _evidence_sections  # noqa: E402

CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
PKG_SCHEMA = json.loads((CONTRACTS / "schemas" / "evidence_package.schema.json").read_text())

# The fixture where all three L2b islands resolve — the richest reconstructability case (probed).
_FULL_FIXTURE = "replay_coherent_cis_driver.yaml"
_SECTION_NAMES = ("integrated_properties", "l3d")
# The base top-level key set of an assembled evidence package (pre-section splice).
_BASE_KEYS = {
    "package_id",
    "framework_version",
    "generated_at",
    "generated_by",
    "context",
    "governance",
    "dashboard_spec_ref",
    "cards",
    "synthesis",
    "renderings",
    "schema_version",
}


def _replay(name: str, tmp_path_factory) -> dict:
    """Replay one raw-input fixture's card summaries through the REAL run.py; return the decision headline.
    Re-derives the claim_vector + biology story in-process (never a stored derived value)."""
    import _skills_common as skc

    fixture = yaml.safe_load((FIXTURE_DIR / name).read_text())
    frozen_cards = fixture["cards"]

    def _factory():
        def _read(card_id, target, indication, *a, **k):
            summary = frozen_cards.get(card_id)
            return copy.deepcopy(summary) if isinstance(summary, dict) else None

        return _read

    out_dir = tmp_path_factory.mktemp("cis-sections")
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _factory)
    mp.setattr(
        sys,
        "argv",
        ["run.py", "--target", fixture["target"], "--indication", fixture["indication"], "--out", str(out_dir)],
    )
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on {name}"
    finally:
        mp.undo()
    return json.loads((out_dir / "decision.json").read_text())["headline"]


@pytest.fixture(scope="module")
def full_headline(tmp_path_factory) -> dict:
    return _replay(_FULL_FIXTURE, tmp_path_factory)


def _island_card_ids(island: dict) -> list:
    """The L1 cards an L2b island rests on — card_id sits under source.provenance for these islands."""
    out = []
    for s in (island.get("provenance") or {}).get("sources") or []:
        cid = s.get("card_id") or (s.get("provenance") or {}).get("card_id")
        if cid:
            out.append(cid)
    return out


def _assemble(headline, evidence_sections):
    """Assemble a schema-valid cis-coherence package (deterministic), optionally with the sections."""
    card_outputs = [
        {
            "card_id": "target-identity-summary",
            "card_version": "1.0.0",
            "validation_state": "pass",
            "summary": {"resolved_hgnc_symbol": "ERBB2", "resolved_hgnc_id": 3430},
            "interpretation_call": "resolved",
            "provenance": {"method_calls": [], "input_manifest_ids": []},
        }
    ]
    validation_summary = {
        "n_cards_attempted": 1,
        "n_cards_passed": 1,
        "n_cards_passed_with_warnings": 0,
        "n_cards_failed": 0,
        "n_cards_excluded_by_applies_when": 0,
    }
    return assemble_evidence_package(
        input_context={
            "target_symbol": "ERBB2",
            "indication": "BRCA",
            "subgroup_spec": None,
            "data_mode": "exploratory",
            "release_pin": "unpinned",
        },
        card_outputs=card_outputs,
        validation_summary=validation_summary,
        synthesis_block={"headline": "cis-coherence: coherent (test)", "caveats_summary": "test envelope"},
        deterministic_timestamps=True,
        framework_version="2.0.0",
        generated_by="skills/cis-feature-coherence@abc1234",
        dashboard_spec_ref="skill:cis-feature-coherence",
        evidence_sections=evidence_sections,
    )


# ── 1. fidelity / reconstructability ────────────────────────────────────────────────────────────────
def test_sections_are_named_and_reconstruct_downward_to_l1(full_headline):
    sections = _evidence_sections(full_headline)
    assert sections is not None
    assert set(sections) == set(_SECTION_NAMES), f"expected exactly {_SECTION_NAMES}, got {sorted(sections)}"

    # L2b: all three concordance islands present (the coherent_cis_driver fixture resolves all three), and
    # each island reconstructs to >= 1 L1 card.
    integrated = sections["integrated_properties"]
    assert set(integrated) == set(_INTEGRATED_ISLAND_KEYS), (
        f"the coherent_cis_driver fixture should resolve all three L2b islands; got {sorted(integrated)}"
    )
    for claim_id, island in integrated.items():
        assert _island_card_ids(island), f"integrated property {claim_id} exposes no reconstructable card_id"

    # L3d: within-domain story present, and every cited claim_id resolves back into the integrated islands.
    l3d = sections["l3d"]
    assert l3d["domain"] == "cis_feature_coherence" and l3d["layer"] == "L3d"
    assert l3d["cross_domain_claims"] == [], "L3d must make no cross-domain claim"
    for p in l3d["provenance"]["claim_ids"]:
        assert p["claim_id"] in integrated, (
            f"l3d cites {p['claim_id']} which does not resolve into the integrated properties"
        )


def test_unrealized_layers_are_omitted_not_fabricated(full_headline):
    """cis-coherence has not realized a typed L2a source_properties map or a local_composites section, so
    the export must NOT emit those keys (naming only realized layers, never fabricating)."""
    sections = _evidence_sections(full_headline)
    assert "source_properties" not in sections
    assert "local_composites" not in sections


def test_no_claim_vector_yields_no_sections():
    """No claim_vector on the headline => None => the dispatcher emits a byte-identical (pre-#1982) package."""
    assert _evidence_sections({}) is None
    assert _evidence_sections({"claim_vector": None}) is None
    assert _evidence_sections("not a dict") is None
    # A claim_vector with no L2b island and no story => still None (the whole export omitted).
    assert _evidence_sections({"claim_vector": {"CIS_DOSAGE": {"signal": "x"}}}) is None


# ── 2. schema ─────────────────────────────────────────────────────────────────────────────────────
def test_assembled_package_with_sections_validates_against_schema(full_headline):
    ep = _assemble(full_headline, _evidence_sections(full_headline))
    errors = sorted(e.message for e in Draft202012Validator(PKG_SCHEMA).iter_errors(ep))
    assert errors == [], f"package with named sections failed schema validation: {errors}"
    for name in _SECTION_NAMES:
        assert name in ep, f"assembled package is missing the {name} section"


# ── 3. additivity (verdict-INERT view) ──────────────────────────────────────────────────────────────
def test_sections_are_purely_additive_over_the_base_package(full_headline):
    base = _assemble(full_headline, None)
    withsecs = _assemble(full_headline, _evidence_sections(full_headline))

    assert set(base) == _BASE_KEYS, f"the base top-level key set drifted: {sorted(set(base) ^ _BASE_KEYS)}"
    assert set(withsecs) == _BASE_KEYS | set(_SECTION_NAMES), (
        f"assembling with sections added keys beyond the named sections: "
        f"{sorted(set(withsecs) - (_BASE_KEYS | set(_SECTION_NAMES)))}"
    )
    # every shared key is byte-identical — the sections move nothing else in the package.
    for k in _BASE_KEYS:
        assert json.dumps(base[k], sort_keys=True) == json.dumps(withsecs[k], sort_keys=True), (
            f"shared package key {k!r} changed when sections were added — the export is not additive"
        )
