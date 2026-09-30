"""Drift-guard: the signaling-network-mechanism card's coverage-quality signal
(moa_ontology_unmapped_fraction) must reach the machine-readable headline (issue #1807, carved
slice — the fraction-lift only, NOT the confirmation-caveat wiring which remains open on #1807).

The card emits moa_ontology_unmapped_fraction (contracts/cards/signaling-network-mechanism.card.yaml,
warning_predicate at unmapped_fraction > 0.05) as a data-quality/audit metric, but before this fix it
was stamped only into provenance.yaml prose — no skill run.py read it via get_card_field, so a
downstream consumer of the headline spine had no machine-readable access to the coverage-quality
signal. Verdict-INERT: mechanism_verdict never keys on this field.

Offline: pure _headline over synthetic cards, no S3/reader.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

me = load_run_py(Path(__file__).resolve().parent.parent, "me_run")


def _cards(mechanism_summary):
    """All cards the skill declares (empty summaries) with the mechanism card populated — so every
    get_card_field lookup in _headline resolves."""
    cards = [{"card_id": cid, "summary": {}} for cid in me.CARDS]
    for c in cards:
        if c["card_id"] == "signaling-network-mechanism":
            c["summary"] = dict(mechanism_summary)
    return cards


def test_headline_carries_moa_ontology_unmapped_fraction():
    h = me._headline(_cards({"moa_ontology_unmapped_fraction": 0.0422}), [], None)
    assert h["moa_ontology_unmapped_fraction"] == 0.0422


def test_moa_ontology_unmapped_fraction_degrades_to_none_when_card_empty():
    h = me._headline(_cards({}), [], None)
    assert h["moa_ontology_unmapped_fraction"] is None


def test_moa_ontology_unmapped_fraction_is_verdict_inert():
    """Display-only: mechanism_verdict identical regardless of the coverage-quality value."""
    vp = ("well_characterized", "some-rule")
    low = me._headline(_cards({"moa_ontology_unmapped_fraction": 0.0}), [], vp)
    high = me._headline(_cards({"moa_ontology_unmapped_fraction": 0.9}), [], vp)
    assert low["mechanism_verdict"] == high["mechanism_verdict"] == "well_characterized"
    assert low["moa_ontology_unmapped_fraction"] != high["moa_ontology_unmapped_fraction"]
