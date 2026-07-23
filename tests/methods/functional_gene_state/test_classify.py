"""functional_gene_state pure two-hit classifier — the biology truth table. No S3 (dict fixtures)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.functional_gene_state.classify import (  # noqa: E402
    SampleEvidence, classify_functional_state, summarize_states, FUNCTIONAL_STATES,
)


def _c(**kw) -> str:
    return classify_functional_state(SampleEvidence(**kw))


# ── biallelic-genetic: completed two-hit events ──────────────────────────────
def test_homdel_is_biallelic_regardless_of_mutation():
    assert _c(has_mutation=False, cn_class="homdel") == "biallelic-genetic"
    assert _c(has_mutation=True, cn_class="homdel") == "biallelic-genetic"


def test_mutation_plus_single_copy_loss_is_biallelic():
    # a hit + loss of the other allele = both alleles inactivated
    assert _c(has_mutation=True, cn_class="loss") == "biallelic-genetic"


def test_mutation_plus_loh_at_locus_is_biallelic():
    # copy-neutral LOH: the mutant allele duplicated, wild-type lost → both alleles mutant
    assert _c(has_mutation=True, cn_class="neutral", loh_at_locus=True) == "biallelic-genetic"


# ── monoallelic: exactly one hit ─────────────────────────────────────────────
def test_het_mutation_copy_neutral_no_loh_is_monoallelic():
    assert _c(has_mutation=True, cn_class="neutral", loh_at_locus=False) == "monoallelic"
    assert _c(has_mutation=True, cn_class="gain", loh_at_locus=False) == "monoallelic"


def test_single_copy_loss_no_mutation_is_monoallelic():
    assert _c(has_mutation=False, cn_class="loss") == "monoallelic"


# ── wt: no hits ──────────────────────────────────────────────────────────────
def test_no_mutation_no_loss_is_wt():
    assert _c(has_mutation=False, cn_class="neutral") == "wt"
    assert _c(has_mutation=False, cn_class="gain") == "wt"
    assert _c(has_mutation=False, cn_class=None) == "wt"


# ── uncertain: signals present but second hit undeterminable ─────────────────
def test_mutation_unknown_background_is_uncertain():
    # mutation but CN not measured and LOH not determinable (model-side copy-neutral case)
    assert _c(has_mutation=True, cn_class=None, loh_at_locus=None) == "uncertain"
    # mutation, copy-neutral, LOH could-not-be-determined → cannot exclude a hidden 2nd hit
    assert _c(has_mutation=True, cn_class="neutral", loh_at_locus=None) == "uncertain"


def test_all_states_are_in_vocabulary():
    # exhaustive-ish sweep: every combination lands in the declared vocabulary
    for has_mut in (True, False):
        for cn in ("homdel", "loss", "neutral", "gain", None):
            for loh in (True, False, None):
                s = _c(has_mutation=has_mut, cn_class=cn, loh_at_locus=loh)
                assert s in FUNCTIONAL_STATES, (has_mut, cn, loh, s)


# ── summary rollup ───────────────────────────────────────────────────────────
def test_summarize_biallelic_fraction_excludes_uncertain_from_denominator():
    states = (["biallelic-genetic"] * 2 + ["monoallelic"] * 3 + ["wt"] * 4 + ["uncertain"] * 1)
    summ = summarize_states(states)
    assert summ["n_samples"] == 10
    assert summ["n_determinable"] == 9           # 10 − 1 uncertain
    assert summ["state_counts"]["biallelic-genetic"] == 2
    assert summ["fraction_biallelic"] == pytest.approx(2 / 9)
    # any-alteration = NOT-wt over ALL samples: 10 − 4 wt = 6 (the lone `uncertain` carries a hit)
    assert summ["fraction_any_alteration"] == pytest.approx(6 / 10)


def test_summarize_empty():
    summ = summarize_states([])
    assert summ["n_samples"] == 0
    assert summ["fraction_biallelic"] is None
    assert summ["fraction_any_alteration"] is None


# ── Phase-2 epigenetic states ────────────────────────────────────────────────
def test_summarize_biallelic_epigenetic_counts_toward_biallelic_fraction():
    # biallelic+epigenetic and biallelic-genetic both count as completed two-hit events
    states = ["biallelic-genetic", "biallelic+epigenetic", "epigenetic", "wt"]
    summ = summarize_states(states)
    assert summ["state_counts"]["biallelic-genetic"] == 1
    assert summ["state_counts"]["biallelic+epigenetic"] == 1
    assert summ["state_counts"]["epigenetic"] == 1
    assert summ["n_determinable"] == 4  # no uncertain
    assert summ["fraction_biallelic"] == pytest.approx(2 / 4)


def test_summarize_epigenetic_only_not_biallelic():
    # pure epigenetic silencing (no genetic hit) is a hit but not biallelic inactivation
    states = ["epigenetic", "wt", "wt"]
    summ = summarize_states(states)
    assert summ["fraction_biallelic"] == pytest.approx(0.0)
    assert summ["fraction_any_alteration"] == pytest.approx(1 / 3)


def test_methylation_state_upgrade_logic():
    """Verify the Phase-2 upgrade rules directly (no S3) via read_model_states_per_model
    monkey-patched to return fixture data."""
    from methods.functional_gene_state import read as fgs_read

    # Patch all four data-fetching functions with fixtures
    def _damaging(_fn, _t):
        return {"ACH-A": True, "ACH-B": False, "ACH-C": False}

    def _cn(_t):
        # ACH-A: has mutation + CN loss → biallelic-genetic (methylation is redundant)
        # ACH-B: wt genetic, but methylated → epigenetic
        # ACH-C: monoallelic (loss, no mutation) + methylated → biallelic+epigenetic
        return {"ACH-A": 0.5,   # cn loss (between HOMDEL_MAX and LOSS_MAX)
                "ACH-B": 0.9,   # neutral
                "ACH-C": 0.5}   # cn loss

    def _meth(_t):
        return {"ACH-A": True, "ACH-B": True, "ACH-C": True}

    orig_dam = fgs_read._read_depmap_mut_matrix
    orig_hot = fgs_read._read_depmap_mut_matrix
    orig_cn = fgs_read._read_depmap_cn
    orig_meth = fgs_read._read_model_methylation

    try:
        fgs_read._read_depmap_mut_matrix = _damaging
        fgs_read._read_depmap_cn = _cn
        fgs_read._read_model_methylation = _meth

        result = fgs_read.read_model_states_per_model("TESTGENE")
    finally:
        fgs_read._read_depmap_mut_matrix = orig_dam
        fgs_read._read_depmap_cn = orig_cn
        fgs_read._read_model_methylation = orig_meth

    assert result["ACH-A"]["state"] == "biallelic-genetic"    # genetic already biallelic; meth redundant
    assert result["ACH-B"]["state"] == "epigenetic"            # wt genetic + methylated → epigenetic
    assert result["ACH-C"]["state"] == "biallelic+epigenetic"  # monoallelic + methylated → biallelic
    assert result["ACH-B"]["is_methylated"] is True
    assert result["ACH-A"]["is_methylated"] is True
