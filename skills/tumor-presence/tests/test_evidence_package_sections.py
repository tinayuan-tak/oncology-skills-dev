"""SK#1941 — the EXPORTED bounded evidence package's NAMED top-level sections.

The tumor-presence reference vertical exports its evidence package with the doc's named sections
(docs/EVIDENCE_PROPERTY_ARCHITECTURE_L1_L4.md § 'The subskill as a bounded biological evidence package',
:259-275): `source_properties` (L2a), `integrated_properties` (L2b islands), `local_composites`
(carried, epistemic type declared), and `l3d` (the within-domain story, #1940). These pins hold:

  1. FIDELITY / RECONSTRUCTABILITY — `_evidence_sections(headline)` lifts the content already on the
     decision headline into the named sections, and every section reconstructs DOWNWARD to L1:
     source_properties[*].card_id · integrated island provenance.sources[*] card_id ·
     local_composites.claims.{A..D}.evidence_atom.cite.card_id · l3d.provenance.claim_ids → the islands.
  2. SCHEMA — a package assembled WITH the sections validates against
     target-contracts/schemas/evidence_package.schema.json (the sections are declared top-level keys;
     the schema's top-level unevaluatedProperties:false would otherwise reject them).
  3. ADDITIVITY — assembling with evidence_sections=None yields EXACTLY the pre-#1941 top-level key set,
     and assembling WITH the sections adds ONLY the four section keys while every shared key is
     byte-identical. The export is a VIEW; it moves nothing else (verdict-INERT).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
SCRIPTS = SKILL_DIR / "scripts"
for p in (str(SKILLS_ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common.envelope import assemble_evidence_package  # noqa: E402
from run import _evidence_sections  # noqa: E402

GOLDEN = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
PKG_SCHEMA = json.loads((CONTRACTS / "schemas" / "evidence_package.schema.json").read_text())

_SECTION_NAMES = ("source_properties", "integrated_properties", "local_composites", "l3d")
# The pre-#1941 top-level key set of an assembled evidence package.
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
# The concordance islands whose provenance.sources reconstruct down to L1 cards (the heterogeneity
# qualifier is a carried island of a different shape — it need not expose provenance.sources).
_RECONSTRUCTABLE_ISLANDS = {
    "tumor_presence_concordance",
    "abundance_concordance",
    "bulk_vs_singlecell_coverage_concordance",
    "protein_presence_concordance",
}


def _headline() -> dict:
    return json.loads(GOLDEN.read_text())["headline"]


def _island_card_ids(island: dict) -> list:
    """The L1 cards an L2b island rests on. card_id sits either directly on a source (the modality-pair
    islands) or under source.provenance (the central node) — a consumer reads it at either depth."""
    out = []
    for s in (island.get("provenance") or {}).get("sources") or []:
        cid = s.get("card_id") or (s.get("provenance") or {}).get("card_id")
        if cid:
            out.append(cid)
    return out


def _assemble(evidence_sections):
    """Assemble a schema-valid tumor-presence package (deterministic), optionally with the sections."""
    card_outputs = [
        {
            "card_id": "target-identity-summary",
            "card_version": "1.0.0",
            "validation_state": "pass",
            "summary": {"resolved_hgnc_symbol": "EPCAM", "resolved_hgnc_id": 4072},
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
            "target_symbol": "EPCAM",
            "indication": "COADREAD",
            "subgroup_spec": None,
            "data_mode": "exploratory",
            "release_pin": "unpinned",
        },
        card_outputs=card_outputs,
        validation_summary=validation_summary,
        synthesis_block={"headline": "tumor-presence: present (test)", "caveats_summary": "test envelope"},
        deterministic_timestamps=True,
        framework_version="2.0.0",
        generated_by="skills/tumor-presence@abc1234",
        dashboard_spec_ref="skill:tumor-presence",
        evidence_sections=evidence_sections,
    )


# ── 1. fidelity / reconstructability ───────────────────────────────────────────────────────────────
def test_sections_are_named_and_reconstruct_downward_to_l1():
    sections = _evidence_sections(_headline())
    assert sections is not None
    assert set(sections) == set(_SECTION_NAMES), f"expected exactly {_SECTION_NAMES}, got {sorted(sections)}"

    # L2a: every source property names the L1 card it resolved from.
    sp = sections["source_properties"]
    assert sp, "source_properties must be non-empty for EPCAM/COADREAD"
    for name, entry in sp.items():
        assert isinstance(entry.get("card_id"), str) and entry["card_id"], (
            f"source_property {name} does not reconstruct to an L1 card_id"
        )

    # L2b: the central node is present, and each concordance island reconstructs to >= 1 L1 card.
    integrated = sections["integrated_properties"]
    assert "tumor_presence_concordance" in integrated, "the central node #1867 must be an integrated property"
    for claim_id in _RECONSTRUCTABLE_ISLANDS & set(integrated):
        assert _island_card_ids(integrated[claim_id]), (
            f"integrated property {claim_id} exposes no reconstructable card_id"
        )

    # local composites: carried inside the domain, epistemic type declared; claim axes reconstruct via
    # evidence_atom.cite.card_id.
    lc = sections["local_composites"]
    assert lc["epistemic_type"] == "domain_local_composite"
    claims = lc["claims"]
    assert {"A", "B", "C", "D"} <= set(claims)
    for ax in ("A", "B", "C", "D"):
        cite = ((claims[ax].get("evidence_atom") or {}).get("cite")) or {}
        assert isinstance(cite.get("card_id"), str) and cite["card_id"], (
            f"local composite claim {ax} does not reconstruct to an L1 card_id via evidence_atom.cite"
        )

    # L3d: every cited claim_id resolves back into the integrated properties (or the pooled vector).
    l3d = sections["l3d"]
    assert l3d["domain"] == "tumor_presence" and l3d["layer"] == "L3d"
    for p in l3d["provenance"]["claim_ids"]:
        assert p["claim_id"] in integrated or p["claim_id"] in _RECONSTRUCTABLE_ISLANDS, (
            f"l3d cites {p['claim_id']} which does not resolve into the integrated properties"
        )


def test_no_claim_vector_yields_no_sections():
    """No claim_vector on the headline => None => the dispatcher emits a byte-identical (pre-#1941) package."""
    assert _evidence_sections({}) is None
    assert _evidence_sections({"claim_vector": None}) is None
    assert _evidence_sections("not a dict") is None


# ── 2. schema ────────────────────────────────────────────────────────────────────────────────────
def test_assembled_package_with_sections_validates_against_schema():
    ep = _assemble(_evidence_sections(_headline()))
    errors = sorted(e.message for e in Draft202012Validator(PKG_SCHEMA).iter_errors(ep))
    assert errors == [], f"package with named sections failed schema validation: {errors}"
    for name in _SECTION_NAMES:
        assert name in ep, f"assembled package is missing the {name} section"


# ── 3. additivity (verdict-INERT view) ─────────────────────────────────────────────────────────────
def test_sections_are_purely_additive_over_the_base_package():
    base = _assemble(None)
    withsecs = _assemble(_evidence_sections(_headline()))

    assert set(base) == _BASE_KEYS, f"the pre-#1941 top-level key set drifted: {sorted(set(base) - _BASE_KEYS)}"
    assert set(withsecs) == _BASE_KEYS | set(_SECTION_NAMES), (
        f"assembling with sections added keys beyond the four named sections: "
        f"{sorted(set(withsecs) - (_BASE_KEYS | set(_SECTION_NAMES)))}"
    )
    # every shared key is byte-identical — the sections move nothing else in the package.
    for k in _BASE_KEYS:
        assert json.dumps(base[k], sort_keys=True) == json.dumps(withsecs[k], sort_keys=True), (
            f"shared package key {k!r} changed when sections were added — the export is not additive"
        )
