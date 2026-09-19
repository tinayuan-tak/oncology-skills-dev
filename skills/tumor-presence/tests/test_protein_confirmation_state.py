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


# --- GRAIN (v1.23.0): pan-cancer breadth is not indication-grain confirmation; IHC read symmetrically ---


def test_pan_cancer_breadth_set_is_nonempty_and_derived_from_the_ladder():
    """Anti-vacuity: the exclusion set must actually contain the breadth positives, or fix 1 is a no-op
    that silently re-admits them. Derived from _PROTEIN_RANK's tumor-breadth-* rules."""
    assert "multi_tumor_elevated" in tp._PAN_CANCER_BREADTH_VERDICTS
    assert "broadly_tumor_elevated" in tp._PAN_CANCER_BREADTH_VERDICTS
    # and those breadth positives are (still) members of the present-verdict set they're excluded from —
    # otherwise the exclusion guards nothing.
    assert "multi_tumor_elevated" in tp._PROTEIN_PRESENT_VERDICTS


def test_pan_cancer_breadth_only_is_untested_not_confirmed():
    """DEFECT 1 (GFAP/COADREAD): tumor-elevation-breadth (pan-cancer, target-grain) filling the
    bulk_protein_ms/tumor bucket must NOT read as `confirmed` — indication tumor protein is untested."""
    for breadth_v in ("multi_tumor_elevated", "broadly_tumor_elevated"):
        pm = _pm(**{"bulk_protein_ms/tumor": _bucket(breadth_v)})
        assert tp._protein_confirmation_state(pm, "broadly_high_expression") == "untested", breadth_v


def test_ihc_detected_confirms_in_tumor():
    """DEFECT 2 (positive direction): an antibody-IHC detection is indication-grain tumor protein."""
    for ihc_v in ("ihc_detected_high", "ihc_detected_moderate", "ihc_detected_low"):
        pm = _pm(**{"protein_ihc/tumor": _bucket(ihc_v)})
        assert tp._protein_confirmation_state(pm, "broadly_high_expression") == "confirmed", ihc_v


def test_measured_ihc_not_detected_is_measured_absent_even_under_breadth():
    """DEFECT 2 (CD19/COADREAD): a MEASURED antibody-IHC not_detected is an indication-grain absence and
    must reach `measured_absent`, outranking a pan-cancer-breadth or cell-line positive that masked it."""
    # breadth positive in the tumor bucket + measured IHC absence → measured_absent (was `confirmed`)
    pm = _pm(
        **{
            "bulk_protein_ms/tumor": _bucket("multi_tumor_elevated"),
            "protein_ihc/tumor": _bucket("ihc_not_detected"),
        }
    )
    assert tp._protein_confirmation_state(pm, "broadly_high_expression") == "measured_absent"
    # cell-line MS present + measured IHC absence → measured_absent (indication grain wins)
    pm = _pm(
        **{
            "bulk_protein_ms/cell_line": _bucket("protein_broadly_high"),
            "protein_ihc/tumor": _bucket("ihc_not_detected"),
        }
    )
    assert tp._protein_confirmation_state(pm, "broadly_high_expression") == "measured_absent"


def test_unmeasured_ihc_bucket_is_ignored():
    """An IHC bucket that is data_unavailable (evidence_state != measured) must not be read either way."""
    pm = _pm(**{"protein_ihc/tumor": _bucket("ihc_not_detected", "data_unavailable")})
    assert tp._protein_confirmation_state(pm, "broadly_high_expression") == "untested"


def test_indication_ms_present_still_wins_over_breadth_in_same_bucket():
    """A real CPTAC positive is not shadowed by the breadth exclusion — it is a non-breadth token."""
    pm = _pm(**{"bulk_protein_ms/tumor": _bucket("protein_broadly_high")})
    assert tp._protein_confirmation_state(pm, "broadly_high_expression") == "confirmed"


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
