"""Thesis-typing derivation tests (Step 2a).

derive_thesis maps archetype_core's verdict-inert soft_membership → a governed thesis under the
target_thesis.yaml hard-margin rule, falling back to the curated biology_axis lookup when ambiguous.
It is VERDICT-INERT (emitted onto nomination.json, consumed by NO gate block until Step 2b), and
`unresolved` reproduces today's gate. These pin the derivation against the governed vocab.
"""

from __future__ import annotations

import os
from pathlib import Path

from _test_support import load_run_py

CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run")

_VOCAB = (CONTRACTS / "vocabularies" / "target_thesis.yaml").exists()
import pytest  # noqa: E402

pytestmark = pytest.mark.skipif(not _VOCAB, reason="target_thesis.yaml absent (land contracts 2a first)")


def _ac(**weights):
    return {"soft_membership": dict(weights)}


def test_clean_dominant_mixtures_resolve_to_their_thesis():
    # real-shaped memberships from the finalized corpus
    kras = tp.derive_thesis(_ac(snv_driver=1.0, tsg_loss=0.0), "intracellular_intrinsic", contracts_repo=CONTRACTS)
    assert kras["thesis"] == "oncogene_addiction" and kras["basis"] == "archetype_mixture"
    cdh3 = tp.derive_thesis(
        _ac(expression_surface=0.598, immune_checkpoint=0.208, dependency_essential=0.192),
        "surface_intrinsic",
        contracts_repo=CONTRACTS,
    )
    assert cdh3["thesis"] == "antigen_driven" and cdh3["basis"] == "archetype_mixture"
    egfr = tp.derive_thesis(_ac(amp_driver=0.741, tsg_loss=0.259), "intracellular_intrinsic", contracts_repo=CONTRACTS)
    assert egfr["thesis"] == "oncogene_addiction"
    io = tp.derive_thesis(_ac(immune_checkpoint=0.9, expression_surface=0.1), "extrinsic", contracts_repo=CONTRACTS)
    assert io["thesis"] == "tme_io"


def test_hard_margin_below_threshold_falls_back_to_biology_axis():
    """An ambiguous mixture (no component clears the dominant/separation floor) does NOT route on
    archetype; it falls to the curated biology_axis lookup so the ~20 curated targets never regress."""
    ambig = dict(snv_driver=0.4, amp_driver=0.35, tsg_loss=0.25)  # dominant 0.4 < 0.5 floor
    surf = tp.derive_thesis({"soft_membership": ambig}, "surface_intrinsic", contracts_repo=CONTRACTS)
    assert surf["thesis"] == "antigen_driven" and surf["basis"] == "biology_axis_fallback"
    # separation too thin even with a high dominant → still fall back
    thin = tp.derive_thesis(
        {"soft_membership": {"snv_driver": 0.55, "amp_driver": 0.45}},
        "intracellular_intrinsic",
        contracts_repo=CONTRACTS,
    )
    assert thin["basis"] == "biology_axis_fallback" and thin["thesis"] == "oncogene_addiction"


def test_unresolved_reproduces_todays_behavior():
    # ambiguous mixture + uncurated (unknown) biology axis → unresolved (today's gate, no routing)
    r = tp.derive_thesis(
        {"soft_membership": {"snv_driver": 0.4, "amp_driver": 0.4}}, "unknown", contracts_repo=CONTRACTS
    )
    assert r["thesis"] == "unresolved" and r["basis"] == "unresolved"
    # no membership + no biology axis → unresolved
    assert tp.derive_thesis({}, None, contracts_repo=CONTRACTS)["thesis"] == "unresolved"


def test_no_vocab_is_fail_soft_unresolved(tmp_path):
    """A missing target_thesis.yaml must never fabricate a thesis — it yields unresolved/no_vocab."""
    r = tp.derive_thesis(_ac(snv_driver=1.0), "intracellular_intrinsic", contracts_repo=tmp_path)
    assert r == {"thesis": "unresolved", "basis": "no_vocab"}


def test_control_labels_do_not_route():
    """A housekeeping/control-dominated mixture must not mint a thesis (crosswalk → unresolved), then
    fall back to biology_axis."""
    r = tp.derive_thesis(_ac(control_housekeeping=0.9, snv_driver=0.1), "mixed", contracts_repo=CONTRACTS)
    assert r["thesis"] == "unresolved"


# ── Step 2b refinement: coarse thesis → finer thesis from axis signals ─────────────────────────────
def _sr(**verdicts):
    """sub_results shaped {short: {'verdict': (v, rule)}}."""
    return {s: {"verdict": (v, f"{s}-rule")} for s, v in verdicts.items()}


def test_neomorphic_gof_refinement_fires_on_gof_driver_plus_nondependent():
    """IDH1-class: snv_driver archetype → oncogene_addiction coarse; a confirmed GoF driver whose pooled
    KO is non_dependent refines to neomorphic_gof (subsumes gof_driver_scoped_veto_downgrade)."""
    ac = _ac(snv_driver=1.0)
    for gv in ("confirmed_driver", "multi_class_driver"):
        r = tp.derive_thesis(
            ac,
            "intracellular_intrinsic",
            sub_results=_sr(genomic_alteration=gv, dependency="non_dependent"),
            contracts_repo=CONTRACTS,
        )
        assert r["thesis"] == "neomorphic_gof" and r["basis"] == "step_2b_refinement"
        assert r["refined_from"] == "oncogene_addiction"


def test_kras_stays_oncogene_addiction_not_neomorphic():
    """KRAS guardrail: confirmed_driver but concordant_dependent (NOT non_dependent) → the refinement
    condition fails → stays oncogene_addiction (dependency decides; KRAS golden preserved)."""
    r = tp.derive_thesis(
        _ac(snv_driver=1.0),
        "intracellular_intrinsic",
        sub_results=_sr(genomic_alteration="confirmed_driver", dependency="concordant_dependent"),
        contracts_repo=CONTRACTS,
    )
    assert r["thesis"] == "oncogene_addiction"


def test_refinement_never_overrides_a_surface_thesis():
    """A surface antigen (antigen_driven) is NOT refined to neomorphic_gof even if it happens to carry a
    genomic driver + non_dependent — antigen_driven is not in the rule's `from`."""
    r = tp.derive_thesis(
        _ac(expression_surface=0.9, snv_driver=0.1),
        "surface_intrinsic",
        sub_results=_sr(genomic_alteration="confirmed_driver", dependency="non_dependent"),
        contracts_repo=CONTRACTS,
    )
    assert r["thesis"] == "antigen_driven"


def test_refinement_needs_sub_results_backward_compatible():
    """Without sub_results the coarse thesis stands (the 2a callers keep working)."""
    r = tp.derive_thesis(_ac(snv_driver=1.0), "intracellular_intrinsic", contracts_repo=CONTRACTS)
    assert r["thesis"] == "oncogene_addiction" and r["basis"] == "archetype_mixture"
    # a partial signal (driver present but dependency not non_dependent) also does not refine
    r2 = tp.derive_thesis(
        _ac(snv_driver=1.0),
        "intracellular_intrinsic",
        sub_results=_sr(genomic_alteration="confirmed_driver"),
        contracts_repo=CONTRACTS,
    )
    assert r2["thesis"] == "oncogene_addiction"


def test_partner_conditional_sl_derives_on_measured_arms():
    """End-to-end (Step 2b): a pooled non_dependent target with a MEASURED biomarker-stratified OR
    subtype-restricted dependency derives partner_conditional_sl (nominate-eligible)."""
    ac = _ac(snv_driver=0.9, tsg_loss=0.1)
    r1 = tp.derive_thesis(
        ac,
        "intracellular_intrinsic",
        sub_results=_sr(genomic_alteration="biomarker_stratified_dependency", dependency="non_dependent"),
        contracts_repo=CONTRACTS,
    )
    assert r1["thesis"] == "partner_conditional_sl" and r1["basis"] == "step_2b_refinement"
    r2 = tp.derive_thesis(
        ac,
        "intracellular_intrinsic",
        sub_results=_sr(subtype_fit="subtype_restricted_dependency", dependency="non_dependent"),
        contracts_repo=CONTRACTS,
    )
    assert r2["thesis"] == "partner_conditional_sl"


def test_partner_conditional_sl_needs_the_pooled_non_dependent():
    """A biomarker-stratified target that is ALSO a pooled dependency (concordant) stays
    oncogene_addiction — the refinement fires only on the dilution-artifact (non_dependent) case."""
    r = tp.derive_thesis(
        _ac(snv_driver=1.0),
        "intracellular_intrinsic",
        sub_results=_sr(genomic_alteration="biomarker_stratified_dependency", dependency="concordant_dependent"),
        contracts_repo=CONTRACTS,
    )
    assert r["thesis"] == "oncogene_addiction"
