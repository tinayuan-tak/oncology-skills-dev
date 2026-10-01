"""Unit tests for `_pathway_activation_confidence_note` (SK#2314 B1, 2026-10-01).

Promotes pathway-activity-context (PROGENy) from pure DISPLAY to a target-conditioned mechanism
CONFIDENCE note, following the coessential-module precedent (functional-requirement
`_dependency_confidence_note`) exactly: a confidence facet raises/lowers CONFIDENCE LANGUAGE only — it
never fires a rule and never moves mechanism_verdict (the resolver keys only on
signaling-network-mechanism's network_class, a card this function never reads).

The conjunction under test: the target's own PROGENy pathway membership (target_pathway_membership)
crossed against which pathways are relatively ACTIVE (z>=+1) or relatively LOW (z<=-1) in this cohort
(relatively_high_pathways / relatively_low_pathways — both already emitted by the card, read verbatim).

Fire-rate matrix (every conjunct measured — a predicate's fire rate != its verdict rate):
  member x high  -> fires POSITIVE  (e.g. Androgen/PRAD, Estrogen/BRCA, Hypoxia/KIRC)
  member x low   -> fires CAUTION (the honest negative)
  member x neither -> silent (None)
  no membership (regardless of high/low) -> silent (None)
  data_unavailable (both lists empty by construction) -> silent (None)
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

RUN = load_run_py(SKILL_DIR, "mech_run_under_test_pathway_activation")


# ── positive: member of a relatively-active pathway ─────────────────────────────────────────────────
def test_androgen_prad_style_fires_positive():
    """AR/PRAD-shaped: target is a responsive gene of Androgen, which is relatively_high in this
    cohort -> positive mechanism-confidence note."""
    c = RUN._pathway_activation_confidence_note(
        "AR",
        ["Androgen"],
        ["Androgen", "Hypoxia"],
        [],
    )
    assert c is not None
    assert c["reason"] == "member_of_relatively_active_pathway"
    assert c["pathways"] == ["Androgen"]
    assert "AR" in c["note"] and "Androgen" in c["note"] and "ACTIVE" in c["note"]


def test_estrogen_brca_style_fires_positive():
    """ESR1/BRCA-shaped: another validated standout cohort."""
    c = RUN._pathway_activation_confidence_note(
        "ESR1",
        ["Estrogen"],
        ["Estrogen"],
        ["p53"],
    )
    assert c is not None
    assert c["reason"] == "member_of_relatively_active_pathway"
    assert c["pathways"] == ["Estrogen"]


# ── honest negative: member of a relatively-low pathway ─────────────────────────────────────────────
def test_member_of_relatively_low_pathway_fires_caution():
    c = RUN._pathway_activation_confidence_note(
        "FOO",
        ["TGFb"],
        [],
        ["TGFb"],
    )
    assert c is not None
    assert c["reason"] == "member_of_relatively_low_pathway"
    assert c["pathways"] == ["TGFb"]
    assert "CAUTION" in c["note"] and "LOW" in c["note"]


# ── silent paths ──────────────────────────────────────────────────────────────────────────────────
def test_no_membership_is_silent_regardless_of_cohort_landscape():
    """A target with no PROGENy membership at all is silent, even if the cohort has standout pathways
    (the conjunction requires BOTH legs; membership alone or activity alone never fires)."""
    assert RUN._pathway_activation_confidence_note("FOO", [], ["Hypoxia"], []) is None
    assert RUN._pathway_activation_confidence_note("FOO", None, ["Hypoxia"], ["TGFb"]) is None


def test_member_but_pathway_neither_extreme_is_silent():
    """Member of a pathway, but that pathway is neither relatively_high nor relatively_low in this
    cohort (an 'average' / profiled read) -> no conjunction, no note."""
    c = RUN._pathway_activation_confidence_note(
        "FOO",
        ["MAPK"],
        ["Hypoxia"],
        ["TGFb"],
    )
    assert c is None


def test_data_unavailable_shaped_input_is_silent():
    """pathway-activity-context data_unavailable: both relatively_high/low lists are empty by
    construction, so even a target with membership (from a different source) is silent — the
    conjunction's SECOND leg (cohort activity) is genuinely absent, not falsely negative."""
    assert RUN._pathway_activation_confidence_note("FOO", ["Androgen"], [], []) is None


# ── never moves the verdict / never a rule — structural guard ───────────────────────────────────────
def test_note_never_asserts_a_verdict_or_rule_field():
    """The returned dict carries only reason/pathways/note — no verdict-shaped or rule-shaped key could
    accidentally be read by a resolver (defence against a future accidental re-wire)."""
    c = RUN._pathway_activation_confidence_note("AR", ["Androgen"], ["Androgen"], [])
    assert set(c.keys()) == {"reason", "pathways", "note"}
