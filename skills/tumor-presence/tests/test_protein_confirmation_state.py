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
    """DEFECT 2 (positive direction): an antibody-IHC detection is indication-grain tumor protein.
    NOTE: no fraction/n_patients passed here, so the single-patient guard (v1.24.0) cannot fire —
    ihc_detected_low confirms on absent metadata by design (guard only SUPPRESSES a measured single
    patient). The guard's suppression is covered below with fraction/n supplied."""
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


# --- SINGLE-PATIENT IHC guard (v1.24.0): a lone stained patient is the antibody noise floor ---


def test_ihc_guard_helper_pure_function():
    """_ihc_is_confirmatory: detected_moderate/_high always confirm; ihc_detected_low confirms IFF
    >= 2 detected patients; non-detected classes never confirm."""
    # moderate/high confirm regardless of the (small) count args
    assert tp._ihc_is_confirmatory("ihc_detected_high", 0.9, 11) is True
    assert tp._ihc_is_confirmatory("ihc_detected_moderate", 0.5, 12) is True
    # single-patient low = noise floor → NOT confirmatory (GFAP/COADREAD: 1 of 12)
    assert tp._ihc_is_confirmatory("ihc_detected_low", 1 / 12, 12) is False
    # two-patient low IS confirmatory (reproducible staining)
    assert tp._ihc_is_confirmatory("ihc_detected_low", 2 / 12, 12) is True
    # non-detected / absent / unknown classes are never confirmatory
    for v in ("ihc_not_detected", "data_unavailable", None):
        assert tp._ihc_is_confirmatory(v, 0.9, 11) is False, v


def test_ihc_guard_confirms_on_missing_metadata():
    """The guard only SUPPRESSES a positively-measured single patient — absent fraction/n preserves the
    prior behavior (confirm), so a coverage gap never silently demotes a real detection."""
    assert tp._ihc_is_confirmatory("ihc_detected_low", None, None) is True
    assert tp._ihc_is_confirmatory("ihc_detected_low", 1 / 12, None) is True
    assert tp._ihc_is_confirmatory("ihc_detected_low", None, 12) is True


def test_ihc_detected_patients_is_an_exact_round():
    """n_detected = round(fraction * n); HPA reports integer-over-integer so the round is exact."""
    assert tp._ihc_detected_patients(1 / 12, 12) == 1
    assert tp._ihc_detected_patients(2 / 12, 12) == 2
    assert tp._ihc_detected_patients(0.33, 12) == 4
    assert tp._ihc_detected_patients(None, 12) is None
    assert tp._ihc_detected_patients(0.5, 0) is None
    assert tp._ihc_detected_patients(0.5, None) is None


def test_guard_threshold_is_two():
    """Anti-drift: the confirmatory floor is 2 patients (a single patient is the noise floor). If this
    constant moves, the 23,136-cell single-patient population changes — force a conscious edit."""
    assert tp._IHC_MIN_CONFIRMATORY_DETECTED == 2


def test_single_patient_ihc_low_does_not_confirm_falls_to_untested():
    """DEFECT 3 (GFAP/COADREAD shape): a single-patient ihc_detected_low is NOT confirmation; with no
    other protein evidence the state is untested, not confirmed."""
    pm = _pm(**{"protein_ihc/tumor": _bucket("ihc_detected_low")})
    assert (
        tp._protein_confirmation_state(pm, "broadly_high_expression", ihc_fraction_detected=1 / 12, ihc_n_patients=12)
        == "untested"
    )


def test_single_patient_ihc_low_falls_to_cell_line_only_when_cellline_present():
    """The exact GFAP/COADREAD shape: single-patient IHC + a cell-line MS positive → confirmed_cell_line_only
    (tumor-tissue protein is not confirmed by one stained patient), NOT plain confirmed."""
    pm = _pm(
        **{
            "protein_ihc/tumor": _bucket("ihc_detected_low"),
            "bulk_protein_ms/cell_line": _bucket("protein_broadly_high"),
        }
    )
    assert (
        tp._protein_confirmation_state(pm, "broadly_high_expression", ihc_fraction_detected=1 / 12, ihc_n_patients=12)
        == "confirmed_cell_line_only"
    )


def test_two_patient_ihc_low_still_confirms():
    """Two stained patients is reproducible staining, above the noise floor → confirmed."""
    pm = _pm(**{"protein_ihc/tumor": _bucket("ihc_detected_low")})
    assert (
        tp._protein_confirmation_state(pm, "broadly_high_expression", ihc_fraction_detected=2 / 12, ihc_n_patients=12)
        == "confirmed"
    )


def test_single_patient_guard_does_not_touch_measured_absent():
    """A measured IHC not_detected still reaches measured_absent — the guard only gates DETECTED-low, it
    does not disturb the fix-2 absence path."""
    pm = _pm(**{"protein_ihc/tumor": _bucket("ihc_not_detected")})
    assert (
        tp._protein_confirmation_state(pm, "broadly_high_expression", ihc_fraction_detected=0.0, ihc_n_patients=12)
        == "measured_absent"
    )


def test_headline_single_patient_ihc_low_does_not_confirm_and_verdict_byte_stable():
    """Integration: a single-patient ihc_detected_low card must (a) keep presence_verdict byte-stable,
    (b) still SURFACE the raw IHC atoms + the protein_ihc/tumor bucket verdict, but (c) NOT read
    protein_confirmation_state=confirmed."""
    fired = [_fr("expression-broadly-high-supportive", "cellline-rna-distribution")]
    cards = [{"card_id": cid, "summary": {}} for cid in tp.CARDS]
    for c in cards:
        if c["card_id"] == "hpa-pathology-cancer-ihc":
            c["summary"] = {
                "protein_presence_class": "ihc_detected_low",
                "fraction_detected": 1 / 12,
                "n_patients_total": 12,
            }
    h = tp._headline(cards, fired, tp._verdict(fired))
    assert h["presence_verdict"] == "broadly_high_expression"  # spine byte-stable
    # the raw display atoms + bucket verdict are UNTOUCHED (still surfaced)
    assert h["hpa_ihc_protein_presence_class"] == "ihc_detected_low"
    assert h["presence_verdict_by_modality"]["protein_ihc/tumor"]["verdict"] == "ihc_detected_low"
    # but a single stained patient does not CONFIRM protein-in-tumor
    assert h["protein_confirmation_state"] == "untested"


def test_headline_two_patient_ihc_low_confirms():
    """Contrast to the single-patient case: two stained patients confirm in the headline path."""
    fired = [_fr("expression-broadly-high-supportive", "cellline-rna-distribution")]
    cards = [{"card_id": cid, "summary": {}} for cid in tp.CARDS]
    for c in cards:
        if c["card_id"] == "hpa-pathology-cancer-ihc":
            c["summary"] = {
                "protein_presence_class": "ihc_detected_low",
                "fraction_detected": 2 / 12,
                "n_patients_total": 12,
            }
    h = tp._headline(cards, fired, tp._verdict(fired))
    assert h["protein_confirmation_state"] == "confirmed"


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
