"""CASE-027-D1: the VERDICT-INERT `mechanism_verdict_currency` note (v1.11.0).

The mechanism_verdict is a signaling-network ANNOTATION-DENSITY class. For a target whose therapeutic
mechanism is NOT signaling-network-mediated (surface antigen / neomorphic-metabolic enzyme / structural
protein / synthetic-lethal partner), a partial/sparse verdict is expected BY CONSTRUCTION — it is
characterized in a DIFFERENT currency. This note names that mis-read risk without asserting a class
(this skill has no thesis; the class lives in target-profile's mechanism_mismatch dimension).

It is a CONSTANT scale-disclaimer, not an evidence-firing heuristic — so, unlike `curation_gap_note`, it
has no over-call risk and it also covers the bare-thin / no-corroborating-signal case that fires no
curation_gap_note. These tests pin: fires for exactly the under-reads verdicts, silent for
well_characterized, verdict-inert (authoritative=verdict), and closes the bare-thin gap.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

RUN = load_run_py(SKILL_DIR, "mech_run_currency")

# The five CASE-027-D1 pairs are all non-signaling drivers; every one resolves to a below-rich verdict.
_UNDER_READS = ("partial", "sparse", "data_unavailable", "insufficient")


# ── FIRES: the under-reads verdicts ──────────────────────────────────────────────────────────────────
def test_fires_for_every_under_reads_verdict():
    """Anti-vacuity: the note fires for the whole under-reads set, and every fire carries the currency
    statement + the verdict-inert authority marker."""
    for v in _UNDER_READS:
        c = RUN._mechanism_verdict_currency(v)
        assert c is not None, f"{v}: currency note did not fire"
        assert c["reason"] == "mechanism_verdict_is_signaling_annotation_density_currency"
        assert c["authoritative"] == "verdict"
        assert c["not_a_target_quality_call"] is True
        assert v in c["note"]
        assert "annotation density" in c["measures"].lower()


def test_note_names_the_currency_mismatch_and_the_alternative_currencies():
    """The note must name that mechanism_verdict is the WRONG currency for a non-signaling class and point
    to the target's OWN currency (so a reader does not mis-read partial as a poor target)."""
    c = RUN._mechanism_verdict_currency("partial")
    note = c["note"]
    assert "WRONG CURRENCY" in note
    # names each non-signaling mechanism class the panel surfaced
    for token in ("SURFACE ANTIGEN", "NEOMORPHIC", "STRUCTURAL", "SYNTHETIC-LETHAL"):
        assert token in note, f"missing mechanism-class token {token!r}"
    # points to the class-asserting home (target-profile) — this skill cannot assert the class
    assert "mechanism_mismatch" in note
    assert "authoritative and unchanged" in note


# ── SILENT: no under-read to name ────────────────────────────────────────────────────────────────────
def test_silent_for_well_characterized():
    """A rich network is not mis-read as poor, so there is no currency mismatch to name."""
    assert RUN._mechanism_verdict_currency("well_characterized") is None


def test_silent_for_unknown_or_missing_verdict():
    for v in (None, "", "some_future_rung", "has_pd_marker"):
        assert RUN._mechanism_verdict_currency(v) is None


# ── the residual gap curation_gap_note leaves: bare-thin / no co-occurring signal ─────────────────────
def test_covers_the_bare_thin_no_signal_gap_that_curation_gap_note_misses():
    """curation_gap_note returns None for a thin network with NO corroborating signal (proven by its own
    test_curation_gap_none_when_thin_but_no_operative_signal); the currency note still fires there, so the
    below-rich verdict is never left unqualified."""
    assert RUN._curation_gap_note("sparse", "data_unavailable", None, "not_measured", 0) is None
    assert RUN._mechanism_verdict_currency("sparse") is not None


# ── verdict-inert wiring: it rides the headline but never the resolver ────────────────────────────────
def test_is_in_the_synthesis_facet_keys():
    """The note must propagate on the composed facet (target-profile reads _SYNTHESIS_FACET_KEYS)."""
    assert "mechanism_verdict_currency" in RUN._SYNTHESIS_FACET_KEYS
