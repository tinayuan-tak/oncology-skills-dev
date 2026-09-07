"""Verdict-inert `protein_confirmation_state` facet (tumor-presence expert review, finding G5).

The collapsed one-word presence_verdict, for a positive-RNA target, reads `present` while protein may
never have been TESTED (most indications lack CPTAC / cell-line-MS coverage). This facet names whether a
present call is protein-CONFIRMED, measured protein-ABSENT, or protein-UNTESTED (RNA-only) — surfacing
the confidence behind the one word WITHOUT minting a new default spine verdict (the untested case is the
modal case; making it the default word would rewrite the most common presence verdict and conflate
confidence with presence-state). Verdict-inert: presence_verdict is byte-stable.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_g5")


def _bucket(verdict, state="measured"):
    return {"verdict": verdict, "evidence_state": state}


def _pm(**buckets):
    """Build a minimal per_modality dict; unspecified protein buckets default to data_unavailable."""
    base = {
        "bulk_protein_ms/tumor": _bucket("data_unavailable", "data_unavailable"),
        "bulk_protein_ms/cell_line": _bucket("data_unavailable", "data_unavailable"),
    }
    base.update(buckets)
    return base


def test_untested_when_no_protein_bucket_measured():
    """RNA-only present call (both protein buckets data_unavailable) → untested, not silently confirmed."""
    pm = _pm()
    assert tp._protein_confirmation_state(pm, "broadly_high_expression") == "untested"


def test_confirmed_when_tumor_protein_present():
    pm = _pm(**{"bulk_protein_ms/tumor": _bucket("protein_strongly_upregulated")})
    assert tp._protein_confirmation_state(pm, "broadly_high_expression") == "confirmed"


def test_confirmed_includes_present_not_elevated_and_down_contrast():
    # a flat/quantified protein (present_not_elevated) confirms presence
    assert (
        tp._protein_confirmation_state(
            _pm(**{"bulk_protein_ms/tumor": _bucket("protein_present_not_elevated")}), "broadly_high_expression"
        )
        == "confirmed"
    )
    # a tumor-vs-normal DOWN contrast means protein present-but-lower → still confirmed present
    assert (
        tp._protein_confirmation_state(
            _pm(**{"bulk_protein_ms/tumor": _bucket("protein_strongly_downregulated")}), "broadly_high_expression"
        )
        == "confirmed"
    )


def test_measured_absent_when_protein_broadly_low_and_nowhere_present():
    pm = _pm(**{"bulk_protein_ms/cell_line": _bucket("protein_broadly_low")})
    assert tp._protein_confirmation_state(pm, "broadly_high_expression") == "measured_absent"


def test_confirmed_wins_when_tumor_present_but_cellline_absent():
    """Cell-line MS under-samples surface antigens; a tumor-CPTAC-present / cell-line-absent target is
    CONFIRMED present (present-in-any-context wins), never measured_absent."""
    pm = _pm(
        **{
            "bulk_protein_ms/tumor": _bucket("protein_broadly_high"),
            "bulk_protein_ms/cell_line": _bucket("protein_broadly_low"),
        }
    )
    assert tp._protein_confirmation_state(pm, "broadly_high_expression") == "confirmed"


def test_not_applicable_when_verdict_not_positive():
    assert tp._protein_confirmation_state(_pm(), "broadly_low_expression") == "not_applicable"
    assert tp._protein_confirmation_state(_pm(), "data_unavailable") == "not_applicable"
    assert tp._protein_confirmation_state(_pm(), "insufficient") == "not_applicable"


# --- integration: surfaces in the headline + synthesis facet, verdict byte-stable ---


def _fr(rule_id, card_id):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x", "value": "y", "signals": {}}


def test_headline_surfaces_untested_for_rna_only_and_keeps_verdict_byte_stable():
    fired = [_fr("expression-broadly-high-supportive", "cellline-rna-distribution")]
    cards = [{"card_id": cid, "summary": {}} for cid in tp.CARDS]
    h = tp._headline(cards, fired, tp._verdict(fired))
    assert h["presence_verdict"] == "broadly_high_expression"  # spine byte-stable (RNA-only positive)
    assert h["protein_confirmation_state"] == "untested"  # but the untested state is legible
    facet = tp._synthesis_facet(cards, fired, tp._verdict(fired))
    assert facet["protein_confirmation_state"] == "untested"


def test_headline_confirmed_when_protein_positive_fires():
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
    ]
    cards = [{"card_id": cid, "summary": {}} for cid in tp.CARDS]
    h = tp._headline(cards, fired, tp._verdict(fired))
    assert h["protein_confirmation_state"] == "confirmed"
