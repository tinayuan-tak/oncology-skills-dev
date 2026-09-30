"""PR-1a of epic SK#2210 / #1507 — the SAFETY generalisation of the tumor-presence L2a export (SK#1941).

Mirror of `skills/tumor-presence/tests/test_evidence_package_sections.py`, with the divergences this
domain forces (each one is asserted, not assumed):

  * THREE sections, not four. Safety has no within-domain story object, so `l3d` is ABSENT — the pin
    below asserts its absence rather than silently omitting it from the expected set, because a future
    `l3d` on this skill must be a deliberate decision and not an unnoticed schema drift.
  * INVERSE VALENCE. Safety is a LIABILITY domain: a STRONG read is a CONCERN, never a win. Every
    source property therefore carries `comparability.valence == "liability"` (the 1a pilot marker,
    declared in docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md § (iii)). There is no `valence` slot in the
    catalog's closed ENTRY_KEYS, so the catalog CANNOT enforce it — this test is its only teeth.
  * The `interpretation` provenance object (envelope v1.1 § (ii)) is emitted here for the FIRST time,
    on the one entry whose class token comes out of a real multi-arm disjunction. Two pins below: it
    appears exactly where the producer declares a disjunction and nowhere else, and every one of its
    four declared arms is REACHABLE (a disjunct vocabulary that can only ever emit one token is a
    decoration, not provenance).

Substrate: the frozen dossiers of `test_safety_replay.py` are replayed THROUGH THE REAL run.py, so
these pins run over the production wiring (claim-vector build -> `_evidence_sections` -> envelope) and
not over a stored copy of their own output. The skill has no decision golden carrying a `claim_vector`,
and freezing one would be a fixture of DERIVED values that can never fail; the frozen card summaries
are the irreproducible L1 INPUT and everything above them is re-derived on every run.

The four clauses of the presence template, kept in order:

  1. FIDELITY / RECONSTRUCTABILITY — `_evidence_sections(headline)` lifts content already on the
     decision headline into the named sections, and every section reconstructs DOWNWARD to L1:
     source_properties[*].card_id (and it must name a card this skill actually reads) ·
     integrated island provenance.sources[*].card_id · local_composites.claims[*].evidence_atom.cite.card_id.
  2. SCHEMA — a package assembled WITH the sections validates against
     contracts/schemas/evidence_package.schema.json (whose top-level unevaluatedProperties:false
     would otherwise reject them).
  3. ADDITIVITY — assembling with evidence_sections=None yields EXACTLY the base top-level key set, and
     assembling WITH the sections adds ONLY the three section keys while every shared key stays
     byte-identical. The export is a VIEW; it moves nothing else (verdict-INERT).
  4. CONTRACT COHERENCE — contracts/vocabularies/property_catalog/safety.yaml declares exactly the
     properties the producer emits. Without this the catalog is a parallel document free to drift from
     the code it governs.
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

from _skills_common.envelope import assemble_evidence_package  # noqa: E402
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT  # noqa: E402
from _skills_common.safety_claims import (  # noqa: E402
    _NORMALTISSUE_DISJUNCTS,
    _SAFETY_INTERPRETATION_FNS,
    _SOURCE_PROPERTY_RECIPES_SAFETY,
    SAFETY_CLAIM_SPEC,
    _normaltissue_interpretation,
)
from _test_support import load_run_py  # noqa: E402

_RUN = load_run_py(SKILL_DIR, "_safety_run_sections")
_evidence_sections = _RUN._evidence_sections

RUN_PY = SCRIPTS / "run.py"
FIXTURES = SKILL_DIR / "tests" / "fixtures"
CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))
PKG_SCHEMA = json.loads((CONTRACTS / "schemas" / "evidence_package.schema.json").read_text())
SAFETY_CATALOG = CONTRACTS / "vocabularies" / "property_catalog" / "safety.yaml"

# Safety exports THREE of the schema's four named sections. `l3d` is deliberately not one of them.
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
_RECIPE_NAMES = {r["name"] for r in _SOURCE_PROPERTY_RECIPES_SAFETY}
_AXIS_KEYS = {spec.axis_key for spec in SAFETY_CLAIM_SPEC}
_SKILL_CARDS = set(_RUN.CARDS)

# The same five curated dossiers test_safety_replay.py pins, spanning all four safety verdict classes
# and both alteration directions — so the L2a export is exercised on every verdict path, not one.
PAIRS = [
    ("braf_coadread", "BRAF", "COADREAD"),
    ("egfr_coadread", "EGFR", "COADREAD"),
    ("tp53_coadread", "TP53", "COADREAD"),
    ("vhl_coadread", "VHL", "COADREAD"),
    ("erbb2_brca", "ERBB2", "BRCA"),
]
_PRIMARY = PAIRS[1]  # EGFR — the essential-tissue protein liability, the richest normal-tissue read


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

    out_dir = Path(tempfile.mkdtemp(prefix=f"sections-{pair_id}-"))
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
    """Assemble a schema-valid safety package (deterministic), optionally with the named sections."""
    card_outputs = [
        {
            "card_id": "target-identity-summary",
            "card_version": "1.0.0",
            "validation_state": "pass",
            "summary": {"resolved_hgnc_symbol": "EGFR", "resolved_hgnc_id": 3236},
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
            "target_symbol": "EGFR",
            "indication": "COADREAD",
            "subgroup_spec": None,
            "data_mode": "exploratory",
            "release_pin": "unpinned",
        },
        card_outputs=card_outputs,
        validation_summary=validation_summary,
        synthesis_block={
            "headline": "on-target-safety-liability: normal_tissue_protein_safety_concern (test)",
            "caveats_summary": "test envelope",
        },
        deterministic_timestamps=True,
        framework_version="2.0.0",
        generated_by="skills/on-target-safety-liability@abc1234",
        dashboard_spec_ref="skill:on-target-safety-liability",
        evidence_sections=evidence_sections,
    )


# ── 1. fidelity / reconstructability ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("pair", PAIRS, ids=[p[1].lower() for p in PAIRS])
def test_sections_are_named_and_reconstruct_downward_to_l1(pair):
    sections = _evidence_sections(_headline(pair))
    assert sections is not None
    # Checked BEFORE the exact-set assert below, which would otherwise subsume it and reduce this to an
    # unfailable restatement: an `l3d` on safety is the one drift worth naming in its own words.
    for absent in _ABSENT_SECTIONS:
        assert absent not in sections, (
            f"safety emitted a {absent!r} section — this domain has no within-domain story object; "
            f"adding one is a deliberate decision that must update this pin and the envelope doc."
        )
    assert set(sections) == set(_SECTION_NAMES), f"expected exactly {_SECTION_NAMES}, got {sorted(sections)}"

    # L2a: every declared source property resolved, names the L1 card it resolved from, and that card
    # is one this skill actually reads (a card_id that is merely a non-empty string reconstructs nowhere).
    sp = sections["source_properties"]
    assert set(sp) == _RECIPE_NAMES, (
        f"source_properties drifted from the producer recipes: missing {sorted(_RECIPE_NAMES - set(sp))}, "
        f"unexpected {sorted(set(sp) - _RECIPE_NAMES)}"
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

    # INVERSE VALENCE (the 1a pilot). The catalog's ENTRY_KEYS are closed and carry no `valence` slot,
    # so nothing in contracts/ can enforce this — if it regresses, a consumer holding only the L2a
    # export reads a STRONG liability as a win.
    for name, entry in sp.items():
        assert (entry.get("comparability") or {}).get("valence") == "liability", (
            f"source_property {name} comparability={entry.get('comparability')!r} — every safety L2a "
            f"property must carry valence 'liability'; safety is an INVERSE-valence domain."
        )

    # L2b: the normal-tissue liability island is present and reconstructs to >= 1 L1 card.
    integrated = sections["integrated_properties"]
    assert "normal_liability_concordance" in integrated, (
        f"the safety L2b island must be an integrated property, got {sorted(integrated)}"
    )
    for claim_id, island in integrated.items():
        assert _island_card_ids(island), f"integrated property {claim_id} exposes no reconstructable card_id"

    # local composites: carried inside the domain, epistemic type declared; every claim axis
    # reconstructs via evidence_atom.cite.card_id.
    lc = sections["local_composites"]
    assert lc["epistemic_type"] == "domain_local_composite"
    claims = lc["claims"]
    assert set(claims) == _AXIS_KEYS, (
        f"local composites drifted from SAFETY_CLAIM_SPEC: missing {sorted(_AXIS_KEYS - set(claims))}, "
        f"unexpected {sorted(set(claims) - _AXIS_KEYS)}"
    )
    for ax in sorted(_AXIS_KEYS):
        cite = ((claims[ax].get("evidence_atom") or {}).get("cite")) or {}
        assert isinstance(cite.get("card_id"), str) and cite["card_id"], (
            f"local composite claim {ax} does not reconstruct to an L1 card_id via evidence_atom.cite"
        )


def test_no_claim_vector_yields_no_sections():
    """No claim_vector on the headline => None => the dispatcher emits a byte-identical package."""
    assert _evidence_sections({}) is None
    assert _evidence_sections({"claim_vector": None}) is None
    assert _evidence_sections("not a dict") is None


# ── the `interpretation` provenance object (envelope v1.1 (ii), first live emission) ───────────────
def test_interpretation_is_emitted_exactly_where_the_class_comes_from_a_disjunction():
    """The object records WHICH arm produced a class token. It belongs on the entries whose producer
    declares a disjunction and NOWHERE else: on a verbatim card read there is no arm to name, and a
    fabricated one would assert provenance the skill does not have."""
    sp = _evidence_sections(_headline(_PRIMARY))["source_properties"]
    carrying = {name for name, entry in sp.items() if "interpretation" in entry}
    # The expected set is a LITERAL, deliberately not `set(_SAFETY_INTERPRETATION_FNS)`: comparing the
    # emission against the very dict that drives it can never fail. Widening the object to a second
    # property is a claim about that property's provenance and must be made here, in the open.
    assert carrying == {"normal_tissue_protein_liability"}, (
        f"interpretation emitted on {sorted(carrying)}; declared for {sorted(_SAFETY_INTERPRETATION_FNS)}"
    )
    for name in carrying:
        interp = sp[name]["interpretation"]
        assert set(interp) == {"function_id", "version", "disjunct_fired"}, (
            f"{name} interpretation shape drifted from envelope v1.1 (ii): {sorted(interp)}"
        )
        assert interp["disjunct_fired"] in _NORMALTISSUE_DISJUNCTS, (
            f"{name} reported disjunct {interp['disjunct_fired']!r}, outside the declared closed set "
            f"{_NORMALTISSUE_DISJUNCTS} — an unknown token tells a consumer nothing."
        )


# The four declared arms, each with the MINIMAL headline that selects it. `essential_tissue_flag`
# outranks the breadth fallback; the TPHP HPA-blind promotion is reported only when it is what LIFTED
# the tier (so the last case pins the precedence, not just the arm).
_ARM_CASES = [
    ("essential_tissue_flag", {"essential_tissue_flag": "present"}),
    ("normal_tissue_breadth_fallback", {"normal_tissue_breadth_class": "broad_normal_expression"}),
    ("tphp_hpa_blind_vital_organ_promotion", {"tphp_hpa_blind_vital_organ_liability_class": "vital_organ_abundant"}),
    ("unmeasured", {}),
]


def test_every_declared_disjunct_has_a_reachability_case():
    """Anti-vacuity for the parametrized test below: a newly declared arm with no case would leave the
    closed set growing while the reachability evidence stayed at four."""
    assert {c[0] for c in _ARM_CASES} == set(_NORMALTISSUE_DISJUNCTS), (
        f"reachability cases {sorted(c[0] for c in _ARM_CASES)} do not cover the declared disjuncts "
        f"{sorted(_NORMALTISSUE_DISJUNCTS)}"
    )


@pytest.mark.parametrize("expected,headline", _ARM_CASES, ids=[c[0] for c in _ARM_CASES])
def test_every_declared_normaltissue_disjunct_is_reachable(expected, headline):
    """Non-degeneracy. A disjunct vocabulary of four tokens where only one is reachable is a
    decoration; the whole point of the object is to distinguish the arms."""
    assert _normaltissue_interpretation(headline)["disjunct_fired"] == expected


def test_the_promotion_arm_is_not_reported_when_it_changed_nothing():
    """Precedence pin mirroring `_normaltissue_sig`: a TPHP HPA-blind vital-organ liability alongside an
    already-strong essential-tissue flag did NOT lift the tier, so the flag arm is what fired. Reporting
    the promotion here would credit the read to a measurement that was not load-bearing."""
    h = {"essential_tissue_flag": "present", "tphp_hpa_blind_vital_organ_liability_class": "vital_organ_abundant"}
    assert _normaltissue_interpretation(h)["disjunct_fired"] == "essential_tissue_flag"


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
    """contracts/vocabularies/property_catalog/safety.yaml is the governance record for this domain's
    L2a properties. If it can name a property the producer never emits (or miss one it does), the
    catalog's determinants / dependence_groups / observables describe a fiction — and every sweep over
    the catalog stays green while doing so."""
    assert SAFETY_CATALOG.exists(), (
        f"{SAFETY_CATALOG} is missing — the whole contracts-side governance of this export, and every "
        f"catalog sweep over it, would be vacuous."
    )
    doc = yaml.safe_load(SAFETY_CATALOG.read_text())
    assert doc["catalog_id"] == "safety" and doc["kind"] == "l2a_property"
    declared = set(doc["properties"])
    # Literal floor: the two sides below are compared to each other, so a symmetric shrink (a property
    # dropped from BOTH the catalog and the producer) would read green on the comparison alone.
    assert len(declared) >= 8, f"safety.yaml declares only {len(declared)} properties, expected >= 8"
    assert declared == _RECIPE_NAMES, (
        f"safety.yaml declares {sorted(declared)} but the producer emits {sorted(_RECIPE_NAMES)}: "
        f"undeclared {sorted(_RECIPE_NAMES - declared)}, fictional {sorted(declared - _RECIPE_NAMES)}"
    )
    for pid, entry in doc["properties"].items():
        recipe = next(r for r in _SOURCE_PROPERTY_RECIPES_SAFETY if r["name"] == pid)
        assert {o.get("card_id") for o in entry["observables"]} == {recipe["card_id"]}, (
            f"safety.yaml::{pid} observables cite cards the producer does not read for it "
            f"(producer reads {recipe['card_id']!r})"
        )
