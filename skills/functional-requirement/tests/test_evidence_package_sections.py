"""PR-1b of epic SK#2210 / #1507 — the DEPENDENCY generalisation of the tumor-presence L2a export (SK#1941).

Mirror of `skills/on-target-safety-liability/tests/test_evidence_package_sections.py` (the PR-1a seed),
with the divergences THIS domain forces (each one is asserted, not assumed):

  * THREE sections, not four. The dependency within-domain L3d story object is Wave-2a (PR-2a), not built
    yet, so `l3d` is ABSENT — the pin below asserts its absence rather than silently omitting it from the
    expected set, so the day PR-2a adds it that is a deliberate decision, not an unnoticed schema drift.
  * DEFAULT valence — NO `valence` marker. Safety is inverse-valence and had to mint `valence: liability`;
    dependency is the default frame (a strong dependency is the signal sought), so every entry's
    `comparability` carries NO `valence` key. The pin below asserts that absence, because a future
    `valence: efficacy` would be an ungoverned second token (the property-catalog ENTRY_KEYS are closed
    and cannot enforce it) — the drift the safety seed's comment warns 1b-1e against.
  * NO `interpretation` provenance object anywhere. Every dependency class is a VERBATIM card read; there
    is no skills-side multi-arm disjunction to name (contrast safety's `_normaltissue_sig`). The pin
    asserts the object is absent on every entry, so a future disjunction-resolved class is deliberate.
  * BYTE-STABLE OMISSION is exercised directly: the `not_dependent_in_indication` fixture resolves only
    three of the six source cards, so it must emit exactly those three entries — a source with no card
    emits NO entry. (The safety seed's five fixtures all resolved every source, so it never tested this.)

Substrate: the frozen dossiers of `test_functional_requirement_replay.py` are replayed THROUGH THE REAL
run.py, so these pins run over the production wiring (claim-vector build -> `_evidence_sections` ->
envelope) and not over a stored copy of their own output. The KRAS decision golden carries a claim_vector
but freezing derived values that can never fail is not the test; the frozen card summaries are the
irreproducible L1 INPUT and everything above them is re-derived on every run.

The four clauses of the presence template, kept in order:

  1. FIDELITY / RECONSTRUCTABILITY — `_evidence_sections(headline)` lifts content already on the decision
     headline into the named sections, and every section reconstructs DOWNWARD to L1.
  2. SCHEMA — a package assembled WITH the sections validates against
     contracts/schemas/evidence_package.schema.json (whose unevaluatedProperties:false would else reject).
  3. ADDITIVITY — assembling with evidence_sections=None yields EXACTLY the base top-level key set, and
     assembling WITH the sections adds ONLY the three section keys while every shared key stays identical.
  4. CONTRACT COHERENCE — contracts/vocabularies/property_catalog/dependency.yaml declares exactly the
     properties the producer emits.
"""

from __future__ import annotations

import copy
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
SCRIPTS = SKILL_DIR / "scripts"
for p in (str(SKILLS_ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common.dependency_claims import (  # noqa: E402
    _SOURCE_PROPERTY_RECIPES_DEPENDENCY,
    DEPENDENCY_CLAIM_SPEC,
)
from _skills_common.envelope import assemble_evidence_package  # noqa: E402
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT  # noqa: E402
from _test_support import load_run_py  # noqa: E402

_RUN = load_run_py(SKILL_DIR, "_fr_run_sections")
_evidence_sections = _RUN._evidence_sections

RUN_PY = SCRIPTS / "run.py"
FIXTURES = SKILL_DIR / "tests" / "fixtures"
CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))
PKG_SCHEMA = json.loads((CONTRACTS / "schemas" / "evidence_package.schema.json").read_text())
DEPENDENCY_CATALOG = CONTRACTS / "vocabularies" / "property_catalog" / "dependency.yaml"

# Dependency exports THREE of the schema's four named sections. `l3d` is deliberately not one of them.
_SECTION_NAMES = ("source_properties", "integrated_properties", "local_composites")
_ABSENT_SECTIONS = ("l3d",)
# The base top-level key set of an assembled evidence package (pre-SK#1941 shape).
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
_RECIPE_NAMES = {r["name"] for r in _SOURCE_PROPERTY_RECIPES_DEPENDENCY}
_AXIS_KEYS = {spec.axis_key for spec in DEPENDENCY_CLAIM_SPEC}
_SKILL_CARDS = set(_RUN.CARDS)

# (fixture_id, target, indication). KRAS resolves ALL SIX source cards (the full-coverage case);
# not_dependent_in_indication resolves only three, so it exercises byte-stable omission.
PAIRS = [
    ("kras_coadread", "KRAS", "COADREAD"),
    ("not_dependent_in_indication", "SYNTHNDEP", "COADREAD"),
]
_PRIMARY = PAIRS[0]  # KRAS — the full-coverage fixture, all six source properties resolved
# The three source cards the negative fixture resolves (the other three cards are absent → omitted).
_PARTIAL = (
    "not_dependent_in_indication",
    {"crispr_essentiality", "rnai_essentiality", "dependency_lineage_selectivity"},
)


def _real_summary(s) -> bool:
    return isinstance(s, dict) and bool(s) and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none")


_DECISION_CACHE: dict = {}


def _decision(pair_id: str, target: str, indication: str) -> dict:
    """Replay a frozen dossier through the REAL run.py (only the live dispatcher is patched)."""
    if pair_id in _DECISION_CACHE:
        return _DECISION_CACHE[pair_id]
    fx = FIXTURES / f"{pair_id}.yaml"
    if not fx.exists():
        pytest.skip(f"no frozen fixture at {fx} — run freeze_fixture.py against live S3")
    frozen = yaml.safe_load(fx.read_text()) or {}

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target_, indication_, *args, **kwargs):
            s = frozen.get(card_id)
            return copy.deepcopy(s) if _real_summary(s) else None

        return _read_live

    out_dir = Path(tempfile.mkdtemp(prefix=f"fr-sections-{pair_id}-"))
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--indication", indication, "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the {pair_id} replay"
    finally:
        mp.undo()
    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"run.py wrote no decision.json on the {pair_id} replay"
    d = json.loads(decision_path.read_text())
    _DECISION_CACHE[pair_id] = d
    return d


def _headline(pair) -> dict:
    return _decision(*pair)["headline"]


def _island_card_ids(island: dict) -> list:
    """The L1 cards an L2b island rests on. card_id sits either directly on a source or under
    source.provenance — a consumer reads it at either depth."""
    out = []
    for s in (island.get("provenance") or {}).get("sources") or []:
        cid = s.get("card_id") or (s.get("provenance") or {}).get("card_id")
        if cid:
            out.append(cid)
    return out


def _assemble(evidence_sections):
    """Assemble a schema-valid dependency package (deterministic), optionally with the named sections."""
    card_outputs = [
        {
            "card_id": "target-identity-summary",
            "card_version": "1.0.0",
            "validation_state": "pass",
            "summary": {"resolved_hgnc_symbol": "KRAS", "resolved_hgnc_id": 6407},
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
            "target_symbol": "KRAS",
            "indication": "COADREAD",
            "subgroup_spec": None,
            "data_mode": "exploratory",
            "release_pin": "unpinned",
        },
        card_outputs=card_outputs,
        validation_summary=validation_summary,
        synthesis_block={
            "headline": "functional-requirement: dependency_confirmed (test)",
            "caveats_summary": "test envelope",
        },
        deterministic_timestamps=True,
        framework_version="2.0.0",
        generated_by="skills/functional-requirement@abc1234",
        dashboard_spec_ref="skill:functional-requirement",
        evidence_sections=evidence_sections,
    )


# ── 1. fidelity / reconstructability ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("pair", PAIRS, ids=[p[1].lower() for p in PAIRS])
def test_sections_are_named_and_reconstruct_downward_to_l1(pair):
    sections = _evidence_sections(_headline(pair))
    assert sections is not None
    # Checked BEFORE the exact-set assert below (which would subsume it): an `l3d` on dependency before
    # Wave-2a builds one is the one drift worth naming in its own words.
    for absent in _ABSENT_SECTIONS:
        assert absent not in sections, (
            f"dependency emitted a {absent!r} section — the within-domain story object is Wave-2a (PR-2a); "
            f"adding one is a deliberate decision that must update this pin and the wiring."
        )
    assert set(sections) == set(_SECTION_NAMES), f"expected exactly {_SECTION_NAMES}, got {sorted(sections)}"

    # L2a: every emitted source property is a DECLARED recipe (subset — a source with no card is omitted
    # byte-stably), names the L1 card it resolved from, and that card is one this skill actually reads.
    sp = sections["source_properties"]
    assert sp, f"{pair[1]}: source_properties is empty — this fixture resolves at least one source card"
    assert set(sp) <= _RECIPE_NAMES, (
        f"source_properties emitted an entry no producer recipe declares: {sorted(set(sp) - _RECIPE_NAMES)}"
    )
    for name, entry in sp.items():
        assert entry.get("card_id") in _SKILL_CARDS, (
            f"source_property {name} card_id={entry.get('card_id')!r} is not in this skill's CARDS roster "
            f"— it does not reconstruct to an L1 card this run read"
        )
        assert isinstance(entry.get("property_field"), str) and entry["property_field"], (
            f"source_property {name} does not name the card field its class token came from"
        )
        assert isinstance(entry.get("property"), str) and entry["property"], f"{name} carries no resolved property"
        assert entry["property"] != "data_unavailable", (
            f"{name} exported an unresolved property — the builder must SKIP a source it cannot resolve"
        )
        for a in entry.get("anchors") or []:
            assert set(a) >= {"field", "value", "scale"}, f"{name} anchor is not a typed {{field,value,scale}}: {a}"
            assert isinstance(a["field"], str) and a["field"] and isinstance(a["scale"], str) and a["scale"], (
                f"{name} anchor has an empty field/scale: {a}"
            )

    # DEFAULT VALENCE (the 1b design decision). Every entry's comparability carries the three grain keys
    # and NO `valence` — dependency is the default frame; a `valence: efficacy` would be an ungoverned
    # second token (the catalog ENTRY_KEYS cannot enforce it). This test is the only teeth on that.
    for name, entry in sp.items():
        comp = entry.get("comparability") or {}
        assert "valence" not in comp, (
            f"source_property {name} carries comparability.valence={comp.get('valence')!r} — dependency is "
            f"the DEFAULT-valence domain and must mint no valence token (see dependency.yaml description)."
        )
        assert {"measurement_type", "sample_context", "grain"} <= set(comp), (
            f"source_property {name} comparability is missing a required key: {sorted(comp)}"
        )

    # NO `interpretation` object anywhere: every dependency class is a verbatim card read, so there is no
    # disjunct to name. A future disjunction-resolved class must add the object deliberately and red here.
    for name, entry in sp.items():
        assert "interpretation" not in entry, (
            f"source_property {name} carries an interpretation object — every dependency class is a "
            f"verbatim card read with no skills-side disjunction; a fabricated disjunct_fired asserts "
            f"provenance this domain does not have."
        )

    # L2b: the CRISPR×RNAi essentiality concordance island is present and reconstructs to >= 1 L1 card.
    integrated = sections["integrated_properties"]
    assert "crispr_rnai_essentiality_concordance" in integrated, (
        f"the dependency L2b island must be an integrated property, got {sorted(integrated)}"
    )
    for claim_id, island in integrated.items():
        assert _island_card_ids(island), f"integrated property {claim_id} exposes no reconstructable card_id"

    # local composites: carried inside the domain, epistemic type declared; every claim axis
    # reconstructs via evidence_atom.cite.card_id (where the axis carries an atom on this fixture).
    lc = sections["local_composites"]
    assert lc["epistemic_type"] == "domain_local_composite"
    claims = lc["claims"]
    assert set(claims) <= _AXIS_KEYS, (
        f"local composites emitted an axis not in DEPENDENCY_CLAIM_SPEC: {sorted(set(claims) - _AXIS_KEYS)}"
    )
    for ax, claim in claims.items():
        cite = ((claim.get("evidence_atom") or {}).get("cite")) or {}
        if cite:  # an axis whose source card is absent carries no evidence_atom (byte-stable)
            assert isinstance(cite.get("card_id"), str) and cite["card_id"], (
                f"local composite claim {ax} has an evidence_atom that does not reconstruct to an L1 card_id"
            )


def test_the_full_coverage_fixture_emits_every_declared_source_property():
    """On the rich KRAS fixture (all six source cards resolve) the L2a export is EXACTLY the producer
    roster — the byte-stable-omission subset check above would pass on a builder that silently dropped
    an entry, so full coverage is pinned separately on the one fixture that has it."""
    sp = _evidence_sections(_headline(_PRIMARY))["source_properties"]
    assert set(sp) == _RECIPE_NAMES, (
        f"KRAS source_properties drifted from the producer recipes: missing {sorted(_RECIPE_NAMES - set(sp))}, "
        f"unexpected {sorted(set(sp) - _RECIPE_NAMES)}"
    )


def test_the_partial_fixture_omits_the_absent_sources_bytestably():
    """The omission path the safety seed never exercised: a fixture missing three source cards emits
    exactly the three it resolves — no null, no placeholder entry."""
    pid, expected = _PARTIAL
    sp = _evidence_sections(_headline((pid, "SYNTHNDEP", "COADREAD")))["source_properties"]
    assert set(sp) == expected, (
        f"partial fixture emitted {sorted(set(sp))}, expected exactly the resolvable {sorted(expected)} — "
        f"a source with no card must emit NO entry, not a nulled one."
    )


def test_no_claim_vector_yields_no_sections():
    """No claim_vector on the headline => None => the dispatcher emits a byte-identical package."""
    assert _evidence_sections({}) is None
    assert _evidence_sections({"claim_vector": None}) is None
    assert _evidence_sections("not a dict") is None


# ── 2. schema ────────────────────────────────────────────────────────────────────────────────────
def test_assembled_package_with_sections_validates_against_schema():
    ep = _assemble(_evidence_sections(_headline(_PRIMARY)))
    errors = sorted(e.message for e in Draft202012Validator(PKG_SCHEMA).iter_errors(ep))
    assert errors == [], f"package with named sections failed schema validation: {errors}"
    for name in _SECTION_NAMES:
        assert name in ep, f"assembled package is missing the {name} section"


# ── 3. additivity (verdict-INERT view) ─────────────────────────────────────────────────────────────
def test_sections_are_purely_additive_over_the_base_package():
    base = _assemble(None)
    withsecs = _assemble(_evidence_sections(_headline(_PRIMARY)))

    assert set(base) == _BASE_KEYS, f"the base top-level key set drifted: {sorted(set(base) ^ _BASE_KEYS)}"
    assert set(withsecs) == _BASE_KEYS | set(_SECTION_NAMES), (
        f"assembling with sections added keys beyond the three named sections: "
        f"{sorted(set(withsecs) - (_BASE_KEYS | set(_SECTION_NAMES)))}"
    )
    # every shared key is byte-identical — the sections move nothing else in the package.
    for k in _BASE_KEYS:
        assert json.dumps(base[k], sort_keys=True) == json.dumps(withsecs[k], sort_keys=True), (
            f"shared package key {k!r} changed when sections were added — the export is not additive"
        )


# ── 4. contract coherence (the catalog governs the code it claims to govern) ───────────────────────
def test_the_property_catalog_declares_exactly_what_the_producer_emits():
    """contracts/vocabularies/property_catalog/dependency.yaml is the governance record for this domain's
    L2a properties. If it can name a property the producer never emits (or miss one it does), the
    catalog's determinants / dependence_groups / observables describe a fiction — and every sweep over
    the catalog stays green while doing so."""
    assert DEPENDENCY_CATALOG.exists(), (
        f"{DEPENDENCY_CATALOG} is missing — the whole contracts-side governance of this export, and every "
        f"catalog sweep over it, would be vacuous."
    )
    doc = yaml.safe_load(DEPENDENCY_CATALOG.read_text())
    assert doc["catalog_id"] == "dependency" and doc["kind"] == "l2a_property"
    declared = set(doc["properties"])
    # Literal floor: the two sides below are compared to each other, so a symmetric shrink (a property
    # dropped from BOTH the catalog and the producer) would read green on the comparison alone.
    assert len(declared) >= 6, f"dependency.yaml declares only {len(declared)} properties, expected >= 6"
    assert declared == _RECIPE_NAMES, (
        f"dependency.yaml declares {sorted(declared)} but the producer emits {sorted(_RECIPE_NAMES)}: "
        f"undeclared {sorted(_RECIPE_NAMES - declared)}, fictional {sorted(declared - _RECIPE_NAMES)}"
    )
    for pid, entry in doc["properties"].items():
        recipe = next(r for r in _SOURCE_PROPERTY_RECIPES_DEPENDENCY if r["name"] == pid)
        assert {o.get("card_id") for o in entry["observables"]} == {recipe["card_id"]}, (
            f"dependency.yaml::{pid} observables cite cards the producer does not read for it "
            f"(producer reads {recipe['card_id']!r})"
        )
