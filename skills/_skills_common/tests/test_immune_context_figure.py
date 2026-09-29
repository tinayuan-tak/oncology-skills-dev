"""immune-context figure emitter — closes the FIGURE_DEBT waiver for the `immune-context` card.

The card has DECLARED `figure: immune_context_leukocyte_composition` since v1.0 with no emitter
registered, so every live run attached nothing and target-contracts' validator downgraded the
failure to a warning via KNOWN_FIGURE_DEBT. These tests pin the three things that make the debt
actually cleared rather than nominally cleared:

  1 the descriptor's id matches the card's OWN declared `figure:` string (not a name we invented);
  2 the figure carries the PAN-CANCER RANK frame, because a bare composition bar invites reading
    the class token as an absolute effector density;
  3 the figure ABSTAINS wherever the class abstains — most importantly on the lymphoid
    denominator, where the medians are arithmetically defined and biologically uninterpretable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent  # skills/_skills_common
SKILLS = SKILL_DIR.parent
for p in (str(SKILLS), str(SKILL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _skills_common._figure_emitters import CARD_FIGURE_EMITTERS, emit_figures_for_card  # noqa: E402
from _skills_common.immune_context_claims import _CD8_COLD_MAX, _CD8_HOT_MIN  # noqa: E402
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT  # noqa: E402

_TC = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))

CARD_ID = "immune-context"


def _card_absent():
    return not (_TC / "cards" / f"{CARD_ID}.card.yaml").is_file()


def _live_summary():
    """The shape a LIVE run emits (NECTIN4/BLCA, 2026-09-12) — taken from a real run, not invented:
    a fixture value the producer never emits makes every assertion around it vacuous."""
    return {
        "immune_context_class": "immune_intermediate",
        "median_cd8_fraction": 0.1103,
        "median_total_t_cell_fraction": 0.3222,
        "median_treg_fraction": 0.0154,
        "median_m1_macrophage_fraction": 0.0268,
        "median_m2_macrophage_fraction": 0.2002,
        "cd8_hot_sample_fraction": 0.49,
        "cd8_treg_ratio": 7.173,
        "cd8_m2_ratio": 0.551,
        "n_samples": 433,
        "tumor_studies": ["BLCA"],
        "indication": "BLCA",
    }


def _emit(summary, tmp_path, indication="BLCA"):
    descs = emit_figures_for_card(CARD_ID, summary, tmp_path, "NECTIN4", indication)
    return descs, tmp_path / "cards" / CARD_ID / "figure_immune_context_leukocyte_composition.svg"


def test_an_emitter_is_registered_for_the_card_that_declares_the_figure():
    assert CARD_ID in CARD_FIGURE_EMITTERS


@pytest.mark.skipif(_card_absent(), reason="target-contracts absent")
def test_the_descriptor_id_is_the_name_the_CARD_declares(tmp_path):
    """Parity against the card's own scalar `figure:` declaration. An emitter registered under a
    name the card never declared would clear the validator's card_id check while still leaving the
    rendered evidence package pointing at a figure id nothing produces."""
    doc = yaml.safe_load((_TC / "cards" / f"{CARD_ID}.card.yaml").read_text())
    declared = ((doc.get("outputs") or {}).get("figure")) or None
    assert declared, "the card no longer declares a scalar `figure:` — this parity test needs updating"
    descs, _ = _emit(_live_summary(), tmp_path)
    assert [d["id"] for d in descs if not d.get("dynamic")] == [declared]


def test_the_figure_renders_from_a_live_summary(tmp_path):
    """Non-vacuity partner for the abstention tests below: the happy path must actually produce a
    file, or the `== []` assertions would pass on an emitter that never draws anything."""
    descs, svg = _emit(_live_summary(), tmp_path)
    assert descs and descs[0]["primary"] is True
    assert svg.is_file() and svg.stat().st_size > 2000


def test_the_figure_states_the_PAN_CANCER_RANK_frame(tmp_path):
    """The review finding this figure has to survive: 0.113/0.084 are the 33-study Q3/Q1, so the
    class token is a RANK, not a density — ICI-approved BLCA sits at `immune_intermediate`. A
    composition bar alone would invite exactly the density misreading, so the rank panel (both cuts
    + the words) is load-bearing content, not decoration."""
    _, svg = _emit(_live_summary(), tmp_path)
    txt = svg.read_text()
    # The house style sets svg.fonttype: none, so SVG text is greppable. Assert that FIRST: if the
    # style stops applying, the content assertions below must fail loudly rather than vacuously.
    assert '<g id="text' in txt, "SVG text is not selectable — the content assertions below would be vacuous"
    assert "PAN-CANCER RANK" in txt and "not an absolute effector density" in txt
    assert str(_CD8_HOT_MIN) in txt and str(_CD8_COLD_MAX) in txt, "both pan-cancer cuts must be drawn"
    # ...and the composition axis must say the shares are RELATIVE, not densities per unit tumour.
    assert "LEUKOCYTE POOL" in txt and "relative, not a density" in txt


def test_the_prevalence_read_is_shown_beside_the_median(tmp_path):
    """A cohort median hides bimodality (MSI-H CRC): cd8_hot_sample_fraction is the prevalence read
    the card added for exactly that reason, so the figure must not show the median alone."""
    _, svg = _emit(_live_summary(), tmp_path)
    assert "49% of samples sit ABOVE the hot cut" in svg.read_text()


def test_the_figure_abstains_on_the_lymphoid_denominator(tmp_path):
    """THE important gate. Unlike data_unavailable, a lymphoid cohort HAS medians and they are
    arithmetically valid — the leukocyte denominator is the malignant clone, so "CD8 is 11% of
    leukocytes" describes the tumour itself, not a redirectable effector pool. A bar chart asserts
    that with no room for the caveat the prose carries, so the figure must not draw it."""
    s = {**_live_summary(), "immune_context_class": "lymphoid_denominator_unreliable"}
    descs, svg = _emit(s, tmp_path, indication="DLBCL")
    assert descs == [] and not svg.exists()


def test_the_figure_abstains_when_no_cohort_resolved(tmp_path):
    descs, svg = _emit({**_live_summary(), "immune_context_class": "data_unavailable"}, tmp_path)
    assert descs == [] and not svg.exists()


def test_a_live_read_error_emits_no_figure(tmp_path):
    descs, svg = _emit({"_live_read_error": "ACCESS_DENIED during HeadObject"}, tmp_path)
    assert descs == [] and not svg.exists()


def test_a_suppressor_median_at_the_noise_floor_is_marked_not_drawn_as_a_value(tmp_path):
    """GBM's median Treg of 0.0002 turned CD8:Treg into 176 in an indication its own class token
    calls cold. The card responds by NULLING the ratio; the figure reads that abstention back off
    the summary and annotates the bar, so a bar too short to trust cannot read as a small value."""
    s = {**_live_summary(), "median_treg_fraction": 0.0002, "cd8_treg_ratio": None}
    _, svg = _emit(s, tmp_path)
    assert "at LM22 noise floor" in svg.read_text()
    # and a suppressor the card DID divide by carries no such mark
    assert "cd8_m2_ratio" not in svg.read_text()


def test_pooled_studies_are_named_only_when_they_add_information(tmp_path):
    """COADREAD pools COAD+READ — worth printing. BLCA→[BLCA] restated the indication twice."""
    _, svg = _emit(_live_summary(), tmp_path)
    assert "BLCA leukocyte composition (n=433)" in svg.read_text()
    s = {**_live_summary(), "tumor_studies": ["COAD", "READ"], "n_samples": 626}
    _, svg2 = _emit(s, tmp_path / "pooled", indication="COADREAD")
    assert "COADREAD leukocyte composition — COAD, READ (n=626)" in svg2.read_text()
