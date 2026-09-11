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
