"""The immune-context CORROBORATION RULER + the skill_report SPINE (2026-09-12, v1.8.0).

Two defects these tests exist to keep fixed:

  RULER  — `_immune_corr` used to return the CONSTANT "moderate" for every measured indication and
           `_immune_signal` always returned `conflict=None`. So headline_block.confidence and
           skill_report.confidence were a CONSTANT "moderate": `strong` and `weak` were UNREACHABLE and
           `derive_confidence`'s conflict cap was dead code. A DISCORDANT PRAD (relative-CD8-hot but
           absolute-TIL-LOW) read exactly as confidently as a corroborated SKCM.
           `test_ruler_is_not_vacuous` is the anti-vacuous-pass guard: it asserts the ladder actually
           SPANS its range on real-shaped inputs, so a future collapse back to a constant fails here.

  SPINE  — `modality_scope` (the TCE `bite_tce` favorability, the ONE thing this skill contributes to the
           composed modality conjunction) was computed but never passed to `build_skill_report`. It rode
           only the LEGACY `claim_record_shadow`, so `tp_facets._modality_scope_by_axis` reached it via
           the fallback leg and standalone `decision.json` carried no bite_tce read at all.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_RUN = Path(__file__).resolve().parents[1] / "scripts" / "run.py"
_spec = importlib.util.spec_from_file_location("immune_context_run_ruler", _RUN)
ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ic)

_HOT_RULE = [{"rule_id": "immune-context-hot-tce-supportive"}]
_INT_RULE = [{"rule_id": "immune-context-intermediate-tce-neutral"}]
_COLD_RULE = [{"rule_id": "immune-context-cold-tce-opposing"}]


def _imm(cls, cd8):
    return {
        "card_id": "immune-context",
        "summary": {
            "immune_context_class": cls,
            "median_cd8_fraction": cd8,
            "median_total_t_cell_fraction": 0.3,
            "n_samples": 400,
        },
    }


def _saltz(cls, pct):
    return {
        "card_id": "tcga-til-fraction-saltz",
        "summary": {"til_fraction_class": cls, "median_til_percentage": pct, "n_samples": 300},
    }


def _coloc(cls):
    return {"card_id": "spatial-tumor-normal-colocalization", "summary": {"spatial_coloc_class": cls}}


def _saltz_missing():
    """`_headline` reads the Saltz card with the STRICT `get_card_field`, so the card is always in the
    emitted list — an indication with no H&E-DL coverage carries a `_missing` stub, not an absent card
    (the mirror-guard contract). Tests that exercise the single-platform tier need that stub, not a
    truncated list, or they'd assert on a KeyError path a real run never takes."""
    return {"card_id": "tcga-til-fraction-saltz", "_missing": True, "summary": {}}


def _headline(cards, rule):
    if not any(c["card_id"] == "tcga-til-fraction-saltz" for c in cards):
        cards = [*cards, _saltz_missing()]
    return ic._headline(cards, rule, ic._verdict(rule))


# ── the ruler: every tier reachable ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "cards,rule,corr,conf,has_conflict",
    [
        # CIBERSORT alone (no Saltz coverage, no coloc product) — honest middle tier.
        pytest.param([_imm("immune_hot", 0.154)], _HOT_RULE, "moderate", "moderate", False, id="single_platform"),
        # absolute H&E-DL TIL AGREES → two orthogonal platforms → the top tier.
        pytest.param(
            [_imm("immune_hot", 0.154), _saltz("til_high", 8.0)], _HOT_RULE, "high", "strong", False, id="til_agrees"
        ),
        # absolute H&E-DL TIL CONTRADICTS (the PRAD shape) → bottom measured tier + a conflict atom.
        pytest.param(
            [_imm("immune_hot", 0.1312), _saltz("til_low", 1.5)], _HOT_RULE, "low", "weak", True, id="til_contradicts"
        ),
        # a MEASURED cold read the absolute TIL agrees with is a CONFIDENT negative, not a weak one.
        pytest.param(
            [_imm("immune_cold", 0.052), _saltz("til_low", 1.1)], _COLD_RULE, "high", "strong", False, id="cold_agrees"
        ),
        # SPATIAL exclusion contradicts a positive bulk read — the most TCE-decisive read there is.
        pytest.param(
            [_imm("immune_intermediate", 0.098), _coloc("immune_excluded")],
            _INT_RULE,
            "low",
            "weak",
            True,
            id="spatial_excluded_contradicts",
        ),
        # SPATIAL immune niche corroborates a positive bulk read.
        pytest.param(
            [_imm("immune_hot", 0.154), _coloc("immune_niche_colocalized")],
            _HOT_RULE,
            "high",
            "strong",
            False,
            id="spatial_inflamed_corroborates",
        ),
        # no cohort at all → nothing to corroborate; confidence must abstain, never read "moderate".
        pytest.param([_imm("data_unavailable", None)], [], "unmeasured", "insufficient", False, id="unmeasured"),
    ],
)
def test_corroboration_ruler_tiers(cards, rule, corr, conf, has_conflict):
    hl = _headline(cards, rule)
    claim = hl["claim_vector"]["IMMUNE"]
    assert claim["corroboration"] == corr
    assert bool(claim["conflict"]) is has_conflict
    assert hl["headline_block"]["confidence"]["level"] == conf
    # the spine must carry the SAME confidence the headline derived (no second computation)
    assert hl["skill_report"]["confidence"]["level"] == conf


def test_ruler_is_not_vacuous():
    """The anti-vacuous-pass guard: the ladder must SPAN its range, not collapse to a constant. This is
    the assertion the pre-2026-09-12 code fails — it emitted only {"moderate"} / {"unmeasured"}."""
    cases = [
        ([_imm("immune_hot", 0.154), _saltz("til_high", 8.0)], _HOT_RULE),
        ([_imm("immune_hot", 0.154)], _HOT_RULE),
        ([_imm("immune_hot", 0.1312), _saltz("til_low", 1.5)], _HOT_RULE),
        ([_imm("data_unavailable", None)], []),
    ]
    levels = {_headline(c, r)["headline_block"]["confidence"]["level"] for c, r in cases}
    assert levels == {"strong", "moderate", "weak", "insufficient"}


def test_conflict_and_caveat_and_tension_share_one_prose_source():
    """orthogonal_discordance_text is the SINGLE builder — a drift between the claim conflict, the
    key_signals caveat and the headline top_tension would be a silent inconsistency for the reader."""
    hl = _headline([_imm("immune_hot", 0.1312), _saltz("til_low", 1.5)], _HOT_RULE)
    conflict = hl["claim_vector"]["IMMUNE"]["conflict"]
    assert conflict == hl["key_signals"]["caveat"]
    assert conflict == hl["headline_block"]["top_tension"]["text"]


# ── the spine: modality_scope + reference_frame ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "cards,rule,fit",
    [
        ([_imm("immune_hot", 0.154)], _HOT_RULE, "favorable"),
        ([_imm("immune_intermediate", 0.098)], _INT_RULE, "conditional"),
        # effector ABSENCE is a TCE-efficacy risk, NOT a veto (CIBERSORT is relative + non-spatial)
        ([_imm("immune_cold", 0.052)], _COLD_RULE, "conditional"),
    ],
)
def test_modality_scope_is_on_the_skill_report_spine(cards, rule, fit):
    hl = _headline(cards, rule)
    assert hl["skill_report"]["modality_scope"] == {"_refinements": {"bite_tce": fit}}


def test_modality_scope_is_silent_when_insufficient():
    hl = _headline([_imm("data_unavailable", None)], [])
    assert hl["skill_report"]["call"] == "insufficient"
    assert hl["skill_report"]["modality_scope"] is None


@pytest.mark.parametrize(
    "extra,why",
    [
        pytest.param(_coloc("immune_excluded"), "spatial exclusion", id="spatial_excluded"),
        pytest.param(_saltz("til_low", 1.5), "absolute-TIL discordance", id="absolute_til_discordant"),
    ],
)
def test_any_orthogonal_contradiction_demotes_bite_tce(extra, why):
    """DEMOTE-ONLY, and driven by the SAME ruler as the prose: whenever an orthogonal platform
    contradicts, the FOR-WHAT projection must not say `favorable` while every text surface says "interpret
    with caution". Caps at `conditional`, never `unfavorable` — the coloc products carry no donor floor,
    CIBERSORT is relative + non-spatial, and the immune rules are `opposing`, never `killer`."""
    hl = _headline([_imm("immune_hot", 0.154), extra], _HOT_RULE)
    assert hl["claim_vector"]["IMMUNE"]["conflict"], f"expected a {why} conflict"
    assert hl["skill_report"]["modality_scope"] == {"_refinements": {"bite_tce": "conditional"}}


def test_orthogonal_corroboration_never_promotes_bite_tce():
    """The cap is one-directional: a favourable spatial phenotype must not upgrade a cold/intermediate
    read (no donor floor on the coloc products — a 1-donor niche cannot mint a TCE-favourable channel)."""
    cold_inflamed = _headline([_imm("immune_cold", 0.052), _coloc("immune_niche_colocalized")], _COLD_RULE)
    assert cold_inflamed["skill_report"]["modality_scope"] == {"_refinements": {"bite_tce": "conditional"}}


@pytest.mark.parametrize(
    "extra",
    [_coloc("immune_excluded"), _saltz("til_low", 1.5), _saltz("til_high", 8.0), _coloc("immune_niche_colocalized")],
)
def test_claim_record_shadow_and_spine_agree_on_modality_scope(extra):
    """One ruler, two carriers: the legacy `_claim_record` shadow (which has cards but no headline, so it
    rebuilds the orthogonal frame via `_orthogonal_reads`) and the skill_report spine must not disagree
    about bite_tce — `tp_facets._modality_scope_by_axis` reads the spine first and the shadow as fallback,
    so a divergence would make the composed answer depend on which leg won."""
    cards = [_imm("immune_hot", 0.154), extra]
    hl = _headline(cards, _HOT_RULE)
    rec = ic._claim_record(cards, _HOT_RULE, ic._verdict(_HOT_RULE))
    assert (rec.get("modality_scope") or {}).get("_refinements") == hl["skill_report"]["modality_scope"]["_refinements"]


def test_reference_frame_ruler_names_the_pan_cancer_percentile():
    """`immune_hot` READS as absolute biology but ENCODES a pan-cancer percentile (the cuts ARE the
    33-study Q1/Q3), which is why clinically-COLD PRAD reads hot. The frame must say so, on the spine."""
    hl = _headline([_imm("immune_hot", 0.1312)], _HOT_RULE)
    frame = hl["skill_report"]["claim_scalars"]["reference_frame"]
    assert "0.1312" in frame
    assert "0.113" in frame and "0.084" in frame  # both named cuts
    assert "RANK" in frame  # the honesty claim, not an absolute-density claim
    assert "LEUKOCYTE" in frame  # the denominator
    # honest sentinel (a string, not null — the evidence_package claim_vector schema is oneOf[str, obj])
    assert (
        _headline([_imm("data_unavailable", None)], [])["skill_report"]["claim_scalars"]["reference_frame"]
        == "unmeasured"
    )


def test_reference_frame_is_not_an_atom_and_does_not_become_a_chip():
    hl = _headline([_imm("immune_hot", 0.1312)], _HOT_RULE)
    assert [c["key"] for c in hl["skill_report"]["claim_chips"]] == ["IMMUNE"]
