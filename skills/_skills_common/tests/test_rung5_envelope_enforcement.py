"""Rung-5 enforcement (SK#1873, epic #1749 — the LAST open child; parent #1507).

Promote the three rung-4 CONFORMANCE CLAUSES that governed the evidence-property build-out from
per-PR convention into STANDING machine-checkable gates WITH TEETH, evaluated over the WHOLE
concordance-family + production-frame population. The clauses (docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md
"Promotion ladder", rung 5 = Contract-enforced):

  * CLAUSE 1 — Envelope-v0 schema conformance. Every declared concordance-family fold-builder
    (`_*_concordance_claim`) emits the v0 envelope's UNIVERSAL invariants: a deterministic
    integration_method, a relational provenance with named sources + an independence_note, a
    closed-vocabulary corroboration tier, a named concordance_class, NO bare verdict `signal` key
    (verdict-inert), and key-omitted-when-absent (byte-stable None on an empty input). Per-family
    slots the envelope records-but-does-not-force (source_support / grain / the two counts — see the
    doc's "Slots that don't yet fit uniformly" section) are checked for WELL-FORMEDNESS *only where a
    family actually emits them*: a family is never RED for declining an optional slot, but a slot it
    DOES emit must be shaped correctly.

  * CLAUSE 2 — Oracle-declaration. Every concordance fold-builder is DECLARED in the #1704 arm-
    commensurability detector's oracle (one of its `_DECLARED_*_BUILDERS` blocks). An undeclared
    fold-builder is invisible to the commensurability oracle — this gate makes that state RED.

  * CLAUSE 3 — Typed-interface registration. Every module-level `Frame` defined in evidence_frame.py
    is registered in FRAME_REGISTRY, carries an emitted layer in reference_emitted_layers(), and the
    registry passes acyclicity + reach. A Frame defined but left out of the registry (so it evaluates
    NOWHERE, or worse feeds a lower layer undetected) is made RED.

DISCIPLINE (SK#1873 dispatch): each gate must (a) be GREEN on the current conformant population,
(b) go RED on a deliberately-broken addition — the mutation teeth are the whole point — and (c) NOT be
vacuous on an empty subset. The teeth tests exercise the SAME checker functions the population tests
use, so a green population result cannot be "green for the wrong reason" (an inert checker). This suite
is verdict-INERT / byte-stable: it only READS already-emitted artifacts; it mints nothing and moves no
verdict or golden.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # skills/  -> _skills_common
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # tests/ -> sibling detector module

from _skills_common import (  # noqa: E402
    cis_coherence_claims,  # noqa: E402
    dependency_claims,
    genomic_claims,
    presence_claims,
    safety_claims,
    selectivity_claims,
)
from _skills_common import evidence_frame as ef  # noqa: E402
from _skills_common.claim_vector_core import CORROBORATION_ORD  # noqa: E402

_SKILLS_COMMON_DIR = pathlib.Path(__file__).resolve().parents[1]

# The closed corroboration vocabulary, DERIVED from the shared ordering table so it cannot drift from the
# production tiers (high / moderate / single_arm / low / unmeasured / underpowered).
VALID_CORROBORATION = frozenset(CORROBORATION_ORD.keys())


# ==================================================================================================
# The concordance-family registry — the population every clause is evaluated over.
#
# Each entry: family key -> (fold-builder callable, a RESOLVING input that emits the claim, an EMPTY /
# NONE input that must yield None). Inputs are the Explore-verified canonical shapes (SK#1750/1752/
# 1578/1594/1584/1709). This registry is the single source of truth the anti-drift teeth pin against:
# a NEW `_*_concordance_claim` fold-builder that is not added here reds `test_registry_tracks_every_
# concordance_builder_defined_in_the_codebase`.
# ==================================================================================================
ENVELOPE_FAMILIES: dict[str, dict] = {
    "recurrence": {
        "builder": genomic_claims._recurrence_concordance_claim,
        "name": "_recurrence_concordance_claim",
        "resolving": {
            "driver_recurrence_class": "top_1pct",
            "genie_driver_recurrence_class": "top_decile",
            "pooled_driver_recurrence_class": "top_1pct",
        },
        "none": {},
    },
    "selectivity": {
        "builder": selectivity_claims._selectivity_concordance_claim,
        "name": "_selectivity_concordance_claim",
        "resolving": {
            "axis_a_selectivity_class": "strong_tumor_selective",
            "protein_tumor_vs_normal_effect_size": 1.6,
            "protein_tumor_vs_normal_q_value": 0.01,
            "protein_tumor_vs_normal_tphp_effect_size": 1.2,
            "protein_tumor_vs_normal_tphp_q_value": 0.02,
        },
        "none": {"axis_a_selectivity_class": "not_informative"},
    },
    "coverage": {
        "builder": presence_claims._coverage_concordance_claim,
        "name": "_coverage_concordance_claim",
        "resolving": {
            "tumor-rna-distribution": {"tumor_expression_class": "broadly_high", "distribution_pattern": "uniform"},
            "tumor-scrna-celltype-expression": {
                "within_tumor_coverage_class": "high",
                "tce_antigen_escape_class": "escape_risk_low",
            },
        },
        "none": {},
    },
    "abundance": {
        "builder": presence_claims._abundance_concordance_claim,
        "name": "_abundance_concordance_claim",
        "resolving": {
            "tumor-rna-distribution": {"allgene_percentile_class": "top_decile"},
            "tumor-protein-abundance-cptac": {"allgene_percentile_class": "top_decile"},
            "cellline-rna-distribution": {"allgene_percentile_class": "top_decile"},
            "cellline-protein-abundance": {"allgene_percentile_class": "top_decile"},
        },
        "none": {},
    },
    "subtype_restriction": {
        "builder": presence_claims._subtype_restriction_concordance_claim,
        "name": "_subtype_restriction_concordance_claim",
        "resolving": {
            "tumor-rna-distribution-by-subtype": {
                "subtype_axis_quality": "powered",
                "subtype_stratification_class": "subtype_restricted",
            },
            "tumor-protein-distribution-by-subtype": {
                "subtype_axis_quality": "powered",
                "subtype_stratification_class": "subtype_restricted",
            },
            "cellline-rna-distribution-by-subtype": {
                "subtype_axis_quality": "powered",
                "subtype_stratification_class": "subtype_restricted",
            },
        },
        "none": {},
    },
    "protein_presence": {
        "builder": presence_claims._protein_presence_concordance_claim,
        "name": "_protein_presence_concordance_claim",
        "resolving": {
            "hpa-pathology-cancer-ihc": {
                "protein_presence_class": "ihc_detected_high",
                "fraction_detected": 1.0,
                "n_high": 12,
                "n_medium": 0,
                "n_low": 0,
                "n_not_detected": 0,
                "n_patients_total": 12,
            },
            "tumor-protein-abundance-cptac": {"allgene_percentile_class": "mid"},
            "cellline-protein-abundance": {"allgene_percentile_class": "bottom_decile"},
        },
        "none": {},
    },
    "essentiality": {
        "builder": dependency_claims._essentiality_concordance_claim,
        "name": "_essentiality_concordance_claim",
        "resolving": {
            "pan-cancer-crispr-dependency-distribution": {"dependency_class": "common_essential"},
            "pan-cancer-rnai-dependency-distribution": {"rnai_dependency_class": "broadly_dependent"},
        },
        "none": {},
    },
    "normal_liability": {
        "builder": safety_claims._normal_liability_concordance_claim,
        "name": "_normal_liability_concordance_claim",
        "resolving": {
            "normal-tissue-liability-gtex": {"liability_class": "broadly_expressed_normal"},
            "sc-normal-celltype-expression": {"sc_normal_safety_essential_class": "critical_organ_liability"},
            "normal-tissue-liability": {"essential_tissue_flag": "present"},
        },
        "none": {},
    },
    "tumor_presence": {
        "builder": presence_claims._tumor_presence_concordance_claim,
        "name": "_tumor_presence_concordance_claim",
        "resolving": {
            "tumor-rna-distribution": {"tumor_expression_class": "broadly_high"},
            "tumor-scrna-celltype-expression": {"sc_expression_class": "malignant_broadly_detected"},
            "hpa-pathology-cancer-ihc": {
                "protein_presence_class": "ihc_detected_high",
                "fraction_detected": 1.0,
                "n_high": 12,
                "n_medium": 0,
                "n_low": 0,
                "n_not_detected": 0,
                "n_patients_total": 12,
            },
        },
        "none": {},
    },
    "cis_dosage": {
        # SK#1781 — FIRST envelope-v0 concordance family for the cis_coherence domain: cross-GRAIN
        # cell-line model (DepMap) × patient tumour (TCGA) cis-dosage-coupling replication.
        "builder": cis_coherence_claims._cis_dosage_concordance_claim,
        "name": "_cis_dosage_concordance_claim",
        "resolving": {
            "cis-feature-expression-coherence": {
                "cis_dosage_class": "cn_dosage_coupled_strong",
                "cn_expr_spearman_r": 0.78,
                "cn_expr_spearman_p": 1e-9,
                "cn_expr_slope_log2tpm_per_cn": 0.62,
                "delta_log2tpm_amplified_vs_neutral": 2.1,
                "n_amplified": 24,
            },
            "patient-cis-coherence": {
                "patient_cis_dosage_class": "cn_dosage_coupled_moderate",
                "cn_expr_spearman_r": 0.55,
                "cn_expr_spearman_p": 1e-6,
                "delta_log2tpm_amplified_vs_neutral": 1.4,
                "n_amplified": 60,
                "n_cases_expression": 310,
            },
            # SK#1783 — the same-grain PROTEIN modality arm (DepMap-Gygi MS). NOT a new family (count stays
            # 11); it exercises the resolving 3-arm fold (resolved_source_count 3 > independent grains 2).
            "cis-feature-protein-coherence": {
                "cis_protein_dosage_class": "prot_dosage_coupled_strong",
                "cn_prot_spearman_r": 0.61,
                "cn_prot_slope_log2abundance_per_cn": 0.47,
                "delta_log2abundance_amplified_vs_neutral": 1.6,
                "n_paired_models_cn_protein": 210,
            },
        },
        "none": {},
    },
    "methylation_silencing": {
        # SK#1782 — SECOND envelope-v0 concordance family for the cis_coherence domain: cross-GRAIN
        # cell-line model (DepMap) × patient tumour (TCGA) epigenetic-silencing replication. The two grain
        # vocabularies DIFFER, so each token is routed through an explicit class→arm mapping.
        "builder": cis_coherence_claims._methylation_silencing_concordance_claim,
        "name": "_methylation_silencing_concordance_claim",
        "resolving": {
            "cellline-methylation-expression-coherence": {
                "methylation_silencing_class": "silencing_coupled_strong",
                "subset_median_delta_log2tpm": -1.8,
                "subset_mannwhitney_p": 1e-12,
                "lineage_collapse_ratio": 0.72,
                "n_hypermethylated": 34,
            },
            "patient-cis-coherence": {
                "patient_methylation_silencing_class": "epigenetic_silencing",
                "delta_log2tpm_methylated_vs_unmethylated": -1.4,
                "n_methylated": 40,
                "n_unmethylated": 210,
                "n_cases_methylation": 250,
            },
        },
        "none": {},
    },
}

# The known family count. An anti-vacuity floor: if the registry (or the codebase discovery it is pinned
# against) ever collapses to a subset, the `== _EXPECTED_FAMILY_COUNT` assertions catch it rather than a
# shrunken population passing silently.
_EXPECTED_FAMILY_COUNT = 11
_EXPECTED_FRAME_COUNT = 5


# ==================================================================================================
# CLAUSE 1 — Envelope-v0 schema conformance
# ==================================================================================================
class EnvelopeViolation(AssertionError):
    """Raised by `assert_envelope_conformant` when a claim violates a v0 envelope invariant."""


def assert_envelope_conformant(family: str, claim: dict) -> None:
    """The v0-envelope conformance CHECKER — the single code path both the population test and the
    mutation-teeth tests exercise. Universal invariants apply to ALL families; the optional slots
    (source_support / grain / the two counts) are checked for well-formedness ONLY where emitted, per the
    envelope doc's "Slots that don't yet fit uniformly (recorded, not forced)" section."""
    if not isinstance(claim, dict):
        raise EnvelopeViolation(f"{family}: claim is not a dict ({type(claim).__name__})")

    # --- UNIVERSAL invariants (every concordance family) ---------------------------------------------
    if claim.get("integration_method") != "explicit_deterministic":
        raise EnvelopeViolation(
            f"{family}: integration_method must be 'explicit_deterministic' (deterministic, no LLM), "
            f"got {claim.get('integration_method')!r}"
        )
    corr = claim.get("corroboration")
    if corr not in VALID_CORROBORATION:
        raise EnvelopeViolation(
            f"{family}: corroboration {corr!r} not in the closed vocabulary {sorted(VALID_CORROBORATION)}"
        )
    cclass = claim.get("concordance_class")
    if not isinstance(cclass, str) or not cclass:
        raise EnvelopeViolation(f"{family}: concordance_class must be a non-empty str, got {cclass!r}")
    prov = claim.get("provenance")
    if not isinstance(prov, dict):
        raise EnvelopeViolation(f"{family}: provenance must be a dict, got {type(prov).__name__}")
    if not prov.get("sources"):
        raise EnvelopeViolation(f"{family}: provenance.sources must be non-empty (relational provenance)")
    note = prov.get("independence_note")
    if not isinstance(note, str) or not note:
        raise EnvelopeViolation(f"{family}: provenance.independence_note must be a non-empty str")
    # Verdict-inert: a v0 property claim NEVER carries a bare `signal` key (a chip / tier that would route
    # a verdict). Two-directional presentation fields (positive_signal / qualifying_signal) are fine.
    if "signal" in claim:
        raise EnvelopeViolation(f"{family}: a v0 envelope claim must NOT carry a bare 'signal' key (verdict-inert)")

    # --- CONDITIONAL per-slot well-formedness (only where the family emits the slot) ------------------
    if "source_support" in claim:
        ss = claim["source_support"]
        if not ss:
            raise EnvelopeViolation(f"{family}: source_support is present but empty")
        if isinstance(ss, list):
            if not all(isinstance(s, dict) for s in ss):
                raise EnvelopeViolation(f"{family}: source_support list must hold per-source dicts")
        elif not isinstance(ss, dict):
            raise EnvelopeViolation(f"{family}: source_support must be a list or dict, got {type(ss).__name__}")
    if claim.get("grain") is not None and "grain" in claim:
        grain = claim["grain"]
        if not isinstance(grain, str) or not grain:
            raise EnvelopeViolation(f"{family}: grain, when emitted, must be a non-empty str, got {grain!r}")
    if "resolved_source_count" in claim and claim["resolved_source_count"] is not None:
        rsc = claim["resolved_source_count"]
        indep = claim.get("corroborating_independent_arm_count")
        if not isinstance(rsc, int) or not isinstance(indep, int):
            raise EnvelopeViolation(
                f"{family}: the two counts, when emitted, must both be ints (got {rsc!r}, {indep!r})"
            )
        if indep > rsc:
            raise EnvelopeViolation(
                f"{family}: corroborating_independent_arm_count ({indep}) may not exceed resolved_source_count ({rsc}) "
                "— independent arms are a subset of resolved sources"
            )


def test_every_concordance_family_conforms_to_the_envelope():
    """CLAUSE 1, GREEN on the population: each declared family emits an envelope-conformant claim on its
    resolving input, and returns None (key-omitted, byte-stable) on an empty/none input."""
    assert len(ENVELOPE_FAMILIES) == _EXPECTED_FAMILY_COUNT, "registry shrank below the known family count"
    for family, spec in ENVELOPE_FAMILIES.items():
        claim = spec["builder"](spec["resolving"])
        assert claim is not None, f"{family}: resolving input did not emit a claim"
        assert_envelope_conformant(family, claim)
        assert spec["builder"](spec["none"]) is None, (
            f"{family}: empty input must yield None (byte-stable key omission)"
        )


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda c: {**c, "integration_method": "llm_inference"}, id="llm_integration_method"),
        pytest.param(lambda c: {k: v for k, v in c.items() if k != "provenance"}, id="drop_provenance"),
        pytest.param(lambda c: {**c, "provenance": {**c["provenance"], "sources": []}}, id="empty_sources"),
        pytest.param(
            lambda c: {**c, "provenance": {k: v for k, v in c["provenance"].items() if k != "independence_note"}},
            id="drop_independence_note",
        ),
        pytest.param(lambda c: {**c, "corroboration": "definitely"}, id="bad_corroboration_token"),
        pytest.param(lambda c: {**c, "concordance_class": ""}, id="empty_concordance_class"),
        pytest.param(lambda c: {**c, "signal": "strong"}, id="bare_signal_key"),
    ],
)
def test_envelope_checker_bites_a_broken_claim(mutate):
    """CLAUSE 1 mutation teeth: the SAME checker the population test uses must RAISE on each deliberately
    broken envelope invariant. Proves the gate CAN fail (not green-for-the-wrong-reason)."""
    base = genomic_claims._recurrence_concordance_claim(ENVELOPE_FAMILIES["recurrence"]["resolving"])
    broken = mutate(base)
    with pytest.raises(EnvelopeViolation):
        assert_envelope_conformant("recurrence", broken)


def test_conditional_slot_check_bites_a_malformed_optional_slot():
    """CLAUSE 1 mutation teeth (conditional slots): a family that DOES emit an optional slot must emit it
    well-formed. A count inversion and an empty source_support both red — while a family that OMITS the
    slot entirely stays green (proven by the population test above)."""
    base = genomic_claims._recurrence_concordance_claim(ENVELOPE_FAMILIES["recurrence"]["resolving"])
    with pytest.raises(EnvelopeViolation):
        assert_envelope_conformant(
            "recurrence", {**base, "corroborating_independent_arm_count": base["resolved_source_count"] + 5}
        )
    with pytest.raises(EnvelopeViolation):
        assert_envelope_conformant("recurrence", {**base, "source_support": []})


def _discover_concordance_builders() -> set[str]:
    """AST-discover every `def _*_concordance_claim(...)` across the `*claims*.py` population (the same
    file set the #1704 detector sweeps). The anti-drift instrument: a new fold-builder in ANY claims
    module is discovered here and must be registered in ENVELOPE_FAMILIES."""
    found: set[str] = set()
    for path in sorted(_SKILLS_COMMON_DIR.glob("*claims*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name.startswith("_")
                and node.name.endswith("_concordance_claim")
            ):
                found.add(node.name)
    return found


def test_registry_tracks_every_concordance_builder_defined_in_the_codebase():
    """CLAUSE 1 anti-drift teeth + anti-vacuity: the set of `_*_concordance_claim` builders DISCOVERED in
    the codebase must equal the registered set — no undeclared builder escapes the envelope gate, and the
    population is provably non-empty (== the known count, so an empty discovery cannot pass)."""
    discovered = _discover_concordance_builders()
    registered = {spec["name"] for spec in ENVELOPE_FAMILIES.values()}
    assert discovered, "AST discovery found NO concordance builders — the gate would be vacuous"
    assert len(registered) == _EXPECTED_FAMILY_COUNT
    assert discovered == registered, (
        "concordance fold-builder drift: discovered-but-unregistered "
        f"{sorted(discovered - registered)}; registered-but-missing {sorted(registered - discovered)}. "
        "A new family must be added to ENVELOPE_FAMILIES (and pass the envelope + oracle gates)."
    )


# ==================================================================================================
# CLAUSE 2 — Oracle-declaration (cross-link to the #1704 arm-commensurability detector)
# ==================================================================================================
def _declared_oracle_builders() -> set[str]:
    """The UNION of every `_DECLARED_*_BUILDERS` block in the detector oracle — the set of fold-builders
    the arm-commensurability oracle knows about."""
    import test_arm_commensurability_detector as detector  # noqa: PLC0415

    union: set[str] = set()
    for name in dir(detector):
        if name.startswith("_DECLARED") and name.endswith("BUILDERS"):
            union |= set(getattr(detector, name).keys())
    return union


def _undeclared_builders(names: set[str], oracle: set[str]) -> set[str]:
    """The gate predicate: builders present in `names` but ABSENT from the oracle union."""
    return names - oracle


def test_every_concordance_builder_is_declared_in_the_commensurability_oracle():
    """CLAUSE 2, GREEN + anti-vacuity: every registered concordance fold-builder is declared in the
    detector oracle, and the oracle union is provably non-empty."""
    oracle = _declared_oracle_builders()
    assert oracle, "the detector oracle union is empty — the cross-link would be vacuous"
    registered = {spec["name"] for spec in ENVELOPE_FAMILIES.values()}
    undeclared = _undeclared_builders(registered, oracle)
    assert undeclared == set(), (
        f"undeclared concordance fold-builders (invisible to the #1704 commensurability oracle): "
        f"{sorted(undeclared)}. Declare each in the relevant _DECLARED_*_BUILDERS block."
    )


def test_oracle_crosslink_bites_an_undeclared_builder():
    """CLAUSE 2 mutation teeth: the SAME predicate flags a fabricated undeclared builder. Proves the
    cross-link can fail (an undeclared fold-builder would red the population test)."""
    oracle = _declared_oracle_builders()
    assert _undeclared_builders({"_rogue_concordance_claim"}, oracle) == {"_rogue_concordance_claim"}


# ==================================================================================================
# CLAUSE 3 — Typed-interface registration (evidence_frame.py FRAME_REGISTRY)
# ==================================================================================================
def _module_frame_ids() -> dict[str, str]:
    """Reflect every module-level `Frame` INSTANCE in evidence_frame.py -> {attr_name: frame_id}. This is
    the discovery a hardcoded frame-id set cannot do: a NEW `X = Frame(...)` shows up here automatically."""
    return {name: v.frame_id for name, v in vars(ef).items() if isinstance(v, ef.Frame)}


def _unregistered_frame_ids(module_frames: dict[str, str], registry_ids: set[str]) -> set[str]:
    """The gate predicate: frame_ids DEFINED at module scope but ABSENT from FRAME_REGISTRY (a frame that
    would evaluate nowhere / escape the acyclicity + reach audit)."""
    return set(module_frames.values()) - registry_ids


def test_every_module_frame_is_registered_and_layered():
    """CLAUSE 3, GREEN + anti-vacuity: the module-level Frame instances and FRAME_REGISTRY are the SAME
    set (bidirectional), every registered frame carries an emitted layer, and both are the known size."""
    module_frames = _module_frame_ids()
    registry_ids = {f.frame_id for f in ef.FRAME_REGISTRY}
    assert module_frames, "no module-level Frame instances discovered — the gate would be vacuous"
    assert len(registry_ids) == _EXPECTED_FRAME_COUNT
    # No unregistered module frame (would evaluate nowhere).
    assert _unregistered_frame_ids(module_frames, registry_ids) == set(), (
        f"module-level Frame(s) missing from FRAME_REGISTRY: {sorted(set(module_frames.values()) - registry_ids)}"
    )
    # And no registry entry that is not a discoverable module frame (a phantom registration).
    assert registry_ids - set(module_frames.values()) == set(), (
        "FRAME_REGISTRY holds a frame_id not defined at module scope"
    )
    layers = ef.reference_emitted_layers()
    for f in ef.FRAME_REGISTRY:
        assert f.frame_id in layers, f"{f.frame_id}: no emitted layer in reference_emitted_layers()"


def test_frame_registry_passes_acyclicity_and_reach():
    """CLAUSE 3, GREEN: the registered frame graph is a DAG (no decision claim feeds a lower layer) and
    every surfaced typed input reaches >=1 frame (the reach ratchet over the whole registry population)."""
    ef.assert_acyclic(ef.FRAME_REGISTRY, ef.reference_emitted_layers())
    must_reach = tuple(ef.SURFACED_CONCORDANCE_PROPERTIES) + tuple(ef.MODALITY_FIT_PROPERTIES)
    audit = ef.decision_reach_audit(ef.FRAME_REGISTRY, must_reach)
    assert audit["unreached"] == [], f"typed inputs reaching NO frame: {audit['unreached']}"


def test_frame_registration_bites_an_unregistered_module_frame():
    """CLAUSE 3 mutation teeth (discovery): the SAME predicate flags a module scope that defines a Frame
    left out of the registry."""
    rogue = ef.Frame(frame_id="rogue_unregistered_frame", inputs=())
    simulated_module = {**_module_frame_ids(), "ROGUE_FRAME": rogue.frame_id}
    registry_ids = {f.frame_id for f in ef.FRAME_REGISTRY}
    assert _unregistered_frame_ids(simulated_module, registry_ids) == {"rogue_unregistered_frame"}


def test_acyclicity_bites_a_registered_frame_feeding_a_lower_layer():
    """CLAUSE 3 mutation teeth (type-integrity): a rogue DECISION_FRAME added to the registry population
    whose input feeds a lower-layer property must make assert_acyclic RAISE. Proves the registry-level
    acyclicity guard can fail — a decision claim may never feed a lower layer."""
    layers = dict(ef.reference_emitted_layers())
    rogue = ef.Frame(
        frame_id="rogue_decision_into_lower_layer",
        inputs=(
            ef.FrameInput(
                property_id="corroborated_tumor_presence",  # itself a decision_frame layer
                kind=ef.InputKind.CANONICAL_PROPERTY_CLAIM,
                role=ef.Role.REQUIRED,
            ),
        ),
    )
    layers[rogue.frame_id] = rogue.claim_type
    with pytest.raises(ef.FrameCycleError):
        ef.assert_acyclic(tuple(ef.FRAME_REGISTRY) + (rogue,), layers)
