"""Provenance is MEASUREMENT-grained, not card-grained (Arm A gap 3, #1862).

Before this, a single emitted value was not a self-contained provenanced tuple: its value lived on the
capsule `numeric_anchors`, its n on the sibling `n_basis`, its source on the card-grain `provenance_keys`
(ONE entry per card), and its method on the top-level `provenance.versions`. Attributing a value to its own
dataset/n/method meant a JOIN across three structures, and a card emitting MULTIPLE values could not attribute
each to its own source. This attaches a `provenance` tuple `{source_product_id, n_basis, method_version}` to
EVERY emitted numeric anchor, so the value is self-contained. `source_product_id` resolves through the
measurement_types registry (card_id → measurement_type → evidence_substrate), so a value's source resolves to
a GOVERNED data product rather than a free-text scrape.

Pattern fix in `_skills_common` (every axis's capsules), not tumor-presence — the tests below exercise a
genomic axis alongside the tumor-presence resolution to prove it.
"""

from __future__ import annotations

import pytest
from _skills_common import evidence_capsule as EC  # noqa: E402


def _cn_card():
    # a GENOMIC axis card (copy_number), to prove this is a _skills_common pattern fix, not tumor-presence.
    return [
        {
            "card_id": "copy-number-distribution",
            "summary": {
                "copy_number_class": "recurrently_deleted",
                "cn_recurrent_deletion_score": 0.2016,
                "cn_fraction_deep_deletion": 0.0402,
                "n_samples": 1084,
                "method_version": "1.2.0",
            },
        }
    ]


# ── every emitted anchor carries a value-grain provenance tuple (the pattern fix, all axes) ────────────
def test_every_emitted_anchor_carries_a_provenance_tuple():
    caps = EC.emit_capsules(_cn_card(), "CML")["capsules"]["copy-number-distribution"]
    anchors = caps["numeric_anchors"] or []
    assert anchors, "anti-vacuity: the genomic card must emit numeric_anchors"
    for a in anchors:
        prov = a.get("provenance")
        assert isinstance(prov, dict), f"{a['metric']} emitted with no value-grain provenance"
        # the self-contained tuple: EVERY key present (resolved token or explicit null), never assembled elsewhere
        assert set(prov) == {"source_product_id", "n_basis", "method_version"}


def test_provenance_carries_the_summary_method_version_and_the_card_n_basis():
    """method_version is the card method fingerprint from the summary (the same field `_l2_method_versions`
    folds into the L2 record_revision_id); n_basis MIRRORS the card's own n_basis (they are both
    `_n_basis(summary)`) so the value's n and the card's n are one and the same fact."""
    cap = EC.emit_capsules(_cn_card(), "CML")["capsules"]["copy-number-distribution"]
    for a in cap["numeric_anchors"]:
        assert a["provenance"]["method_version"] == "1.2.0"
        assert a["provenance"]["n_basis"] == cap["n_basis"]  # value-grain n == card-grain n_basis
    assert cap["n_basis"]["n_samples"] == 1084


def test_provenance_is_a_fresh_object_per_anchor_not_an_alias():
    """Each value OWNS its provenance — mutating one anchor's tuple must not bleed into its siblings (the room
    for a future per-value source divergence)."""
    cap = EC.emit_capsules(_cn_card(), "CML")["capsules"]["copy-number-distribution"]
    anchors = cap["numeric_anchors"]
    assert len(anchors) >= 2
    anchors[0]["provenance"]["source_product_id"] = "MUTATED"
    assert anchors[1]["provenance"]["source_product_id"] != "MUTATED"


# ── source_product_id resolves to the GOVERNED data product via measurement_types ──────────────────────
def test_source_product_id_resolves_through_the_measurement_types_registry(monkeypatch):
    """The reconciliation (#1862 bullet 2): source_product_id is the evidence_substrate the card's
    measurement_type is a view of — resolved through measurement_types.substrate_for_card, NOT a free-text
    scrape — so a value's source resolves to a governed data product. Registry-independent here: we stub the
    resolver so the test never depends on a target-contracts checkout / pin."""
    monkeypatch.setattr(EC, "substrate_for_card", lambda cid: ("copy_number_alteration", "governed_cnv_product"))
    prov = EC._measurement_provenance("copy-number-distribution", "copy_number_alteration", _cn_card()[0]["summary"])
    assert prov["source_product_id"] == "governed_cnv_product"


def test_source_product_id_is_explicit_none_when_untagged_or_unreachable(monkeypatch):
    """A skills-only checkout (registry unreachable) or an untagged type yields an EXPLICIT null — the value
    still carries a declared source SLOT, honestly 'not governed here', never a silently missing attribution."""
    monkeypatch.setattr(EC, "substrate_for_card", lambda cid: (None, None))
    prov = EC._measurement_provenance("x", "y", {"method_version": "1.0.0"})
    assert prov["source_product_id"] is None and prov["method_version"] == "1.0.0"


# ── the measurement-grained-provenance invariant, with teeth ───────────────────────────────────────────
def test_assert_measurement_provenanced_refuses_an_unattributed_value():
    """The MUTATION: a value emitted with NO provenance key is un-attributed (provenance silently regressed to
    the card grain) and must be refused."""
    with pytest.raises(ValueError, match="no provenance"):
        EC.assert_measurement_provenanced([{"metric": "cn_score", "value": 0.2, "scale": "fraction"}])


def test_assert_measurement_provenanced_admits_a_declared_tuple_and_a_null_value():
    ok = [
        {"metric": "cn_score", "value": 0.2, "scale": "fraction", "provenance": {"source_product_id": None}},
        {"metric": "absent_field", "value": None},  # a null value needs no provenance
    ]
    assert EC.assert_measurement_provenanced(ok) is ok  # returns unchanged so it can wrap an emission


def test_emit_capsules_output_passes_the_provenance_guard():
    """End-to-end: the real emitter never produces an un-attributed value for any axis."""
    caps = EC.emit_capsules(_cn_card(), "CML")["capsules"]
    for c in caps.values():
        EC.assert_measurement_provenanced(c.get("numeric_anchors") or [])
