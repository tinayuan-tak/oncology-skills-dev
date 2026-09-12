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
import re
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


# ── v1.9.0: the SIX previously-invisible card fields ──────────────────────────────────────────────
# The bug: the card declared and the reader emitted these six since card v1.2.0, and NO consumer read
# them. The mirror guard (test_card_output_emission.py) runs card-DECLARES -> reader-EMITS, so a field the
# reader emits and nothing consumes is structurally invisible to it — which is why a full review missed it.
_SIX_CARD_FIELDS = (
    "cd8_hot_sample_fraction",
    "cd8_treg_ratio",
    "cd8_m2_ratio",
    "median_treg_fraction",
    "median_m2_macrophage_fraction",
    "median_m1_macrophage_fraction",
)


def _imm_full(cls, cd8, *, hot_frac=0.31, treg=6.4, m2=1.9, treg_med=0.024, m2_med=0.081, m1_med=0.012):
    card = _imm(cls, cd8)
    card["summary"].update(
        {
            "cd8_hot_sample_fraction": hot_frac,
            "cd8_treg_ratio": treg,
            "cd8_m2_ratio": m2,
            "median_treg_fraction": treg_med,
            "median_m2_macrophage_fraction": m2_med,
            "median_m1_macrophage_fraction": m1_med,
        }
    )
    return card


@pytest.mark.parametrize("field", _SIX_CARD_FIELDS)
def test_every_emitted_card_field_reaches_a_consumer(field):
    """Each of the six must land on the headline AND on the citable claim atom. A field on the card that
    no consumer reads is data the framework paid to compute and then threw away."""
    hl = _headline([_imm_full("immune_intermediate", 0.0981)], _INT_RULE)
    assert hl.get(field) is not None, f"{field} never reaches the headline"
    atom = hl["claim_vector"]["IMMUNE"]["evidence_atom"]
    assert field in atom["values"], f"{field} is not on the citable atom"
    assert field in atom["cite"]["fields"], f"{field} is on the atom but not CITABLE"
    assert field in ic._SYNTHESIS_FACET_KEYS, f"{field} is absent from the composed synthesis facet"


def test_heterogeneity_frame_names_the_hot_minority_the_median_hides():
    """The MSI-H CRC shape and the reason this field exists: the pooled median reads intermediate while a
    substantial minority of patients clears the hot cut — the population a TCE would be developed FOR."""
    hl = _headline([_imm_full("immune_intermediate", 0.0981, hot_frac=0.31)], _INT_RULE)
    frame = hl["skill_report"]["claim_scalars"]["heterogeneity_frame"]
    assert "31.0%" in frame  # prevalence, stated as a percentage of samples
    assert "0.113" in frame  # gauged against the SAME cut that produced the class
    assert "MINORITY" in frame
    assert "does NOT move" in frame  # the non-gating promise, in the text the reader sees


def test_heterogeneity_frame_flags_a_hot_cohort_most_patients_do_not_clear():
    hl = _headline([_imm_full("immune_hot", 0.154, hot_frac=0.42)], _HOT_RULE)
    frame = hl["skill_report"]["claim_scalars"]["heterogeneity_frame"]
    assert "FEWER THAN HALF" in frame


def test_suppression_frame_abstains_at_the_lm22_noise_floor_rather_than_dividing():
    """The GBM shape: a suppressor median at the noise floor (0.0002) is an ABSENT denominator, not a small
    one. The reader nulls the ratio; the frame must say so and NOT invent a suppression read."""
    hl = _headline(
        [_imm_full("immune_cold", 0.052, treg=None, m2=None, treg_med=0.0002, m2_med=0.0009)],
        _COLD_RULE,
    )
    frame = hl["skill_report"]["claim_scalars"]["suppression_frame"]
    assert "noise floor" in frame and "ABSTAIN" in frame
    assert "176" not in frame  # the number the un-floored ratio would have produced


def test_suppression_frame_reports_but_never_demotes():
    """Non-gating is the whole scope of this PR: no pan-cancer distribution exists for these ratios, so a
    high suppressor load is REPORTED and the verdict + bite_tce channel are untouched."""
    heavy = _headline([_imm_full("immune_hot", 0.154, treg=1.2, m2=0.4)], _HOT_RULE)
    light = _headline([_imm_full("immune_hot", 0.154, treg=13.8, m2=6.0)], _HOT_RULE)
    assert "CD8:Treg=1.2" in heavy["skill_report"]["claim_scalars"]["suppression_frame"]
    assert heavy["immune_context_verdict"] == light["immune_context_verdict"] == "immune_hot"
    assert heavy["skill_report"]["modality_scope"] == light["skill_report"]["modality_scope"]
    assert heavy["headline_block"]["confidence"]["level"] == light["headline_block"]["confidence"]["level"]


def test_the_new_frames_are_scalars_not_chips():
    hl = _headline([_imm_full("immune_hot", 0.154)], _HOT_RULE)
    assert [c["key"] for c in hl["skill_report"]["claim_chips"]] == ["IMMUNE"]
    for k in ("reference_frame", "heterogeneity_frame", "suppression_frame"):
        assert isinstance(hl["skill_report"]["claim_scalars"][k], str)


# ── v1.9.0: the FOURTH class token ────────────────────────────────────────────────────────────────
_LYMPHOID_RULE = [{"rule_id": "immune-context-lymphoid-denominator-uninterpretable"}]


def _lymphoid_card():
    """What the reader actually emits for DLBC/LAML/THYM: the class token, the median WITHHELD.

    n_samples is 0 because that is what a LIVE DLBCL run emits, verified 2026-09-12 — the guard fires on the
    resolved study codes BEFORE the per-sample read, so no rows are ever loaded and the summariser is handed
    an empty list. An earlier draft of this fixture said 48 (DLBC's true cohort size), which is exactly why
    no test caught the frame rendering "the cohort exists (DLBC, n=0)" against the real reader."""
    return {
        "card_id": "immune-context",
        "summary": {
            "immune_context_class": "lymphoid_denominator_unreliable",
            "median_cd8_fraction": None,
            "median_total_t_cell_fraction": None,
            "n_samples": 0,
            "tumor_studies": ["DLBC"],
        },
    }


def test_the_lymphoid_token_is_its_own_verdict_not_a_bare_insufficient():
    """The bug: with no rule and no _RULE_TO_VERDICT entry the token fired nothing and fell through to
    `insufficient` — INDISTINGUISHABLE from "no cohort". The whole value of the token is that distinction."""
    hl = _headline([_lymphoid_card()], _LYMPHOID_RULE)
    assert hl["immune_context_verdict"] == "lymphoid_denominator_unreliable"
    assert hl["driving_rule_id"] == "immune-context-lymphoid-denominator-uninterpretable"
    no_cohort = _headline([_imm("data_unavailable", None)], [])
    assert hl["immune_context_verdict"] != no_cohort["immune_context_verdict"]
    assert hl["headline_block"]["verdict"]["phrase"] != no_cohort["headline_block"]["verdict"]["phrase"]


def test_the_lymphoid_token_is_never_read_as_measured_effector_absence():
    """An uninterpretable DENOMINATOR is an absent MEASUREMENT. Reading it as effector absence would
    manufacture a TCE-efficacy risk in exactly the malignancies where TCEs are the validated modality
    (glofitamab / mosunetuzumab in DLBCL) — so: `unmeasured` not `absent`, neutral badge not red, and NO
    contribution to the bite_tce channel (matching the rule's own bite_tce: neutral)."""
    hl = _headline([_lymphoid_card()], _LYMPHOID_RULE)
    assert hl["claim_vector"]["IMMUNE"]["signal"] == "unmeasured"
    assert hl["headline_block"]["verdict"]["polarity"] == "neutral"
    assert hl["skill_report"]["modality_scope"] is None
    cold = _headline([_imm("immune_cold", 0.052)], _COLD_RULE)
    assert cold["skill_report"]["modality_scope"] is not None  # the non-vacuity partner: cold DOES speak


def test_the_lymphoid_frame_says_why_instead_of_the_bare_unmeasured_sentinel():
    """`data_unavailable` -> "unmeasured" (no cohort). The lymphoid token -> a cohort EXISTS and its frame
    does not apply. Collapsing the second onto the first here would discard, at the last surface, exactly
    the distinction the card vocabulary and the rule both went to the trouble of preserving."""
    scalars = _headline([_lymphoid_card()], _LYMPHOID_RULE)["skill_report"]["claim_scalars"]
    frame = scalars["reference_frame"]
    assert frame != "unmeasured"
    assert "DOES NOT APPLY" in frame and "WITHHELD" in frame
    assert "absent MEASUREMENT" in frame
    for k in ("heterogeneity_frame", "suppression_frame"):
        assert "uninterpretable" in scalars[k], f"{k} must not gauge a withheld median"


def test_the_lymphoid_frame_never_quotes_a_sample_count_beside_the_cohort_exists_claim():
    """Caught by a live DLBCL run, not by this suite: the frame asserted "the cohort exists (DLBC, n=0)" and
    then refuted itself in the same parenthesis. n_samples is a NOT-READ sentinel for these cohorts (the
    guard precedes the read by design), so it is not a cohort size and must never be rendered as one. The
    "cohort EXISTS" claim rests on the STUDY CODES resolving, which is what the line may cite."""
    frame = _headline([_lymphoid_card()], _LYMPHOID_RULE)["skill_report"]["claim_scalars"]["reference_frame"]
    assert not re.search(r"\bn\s*=", frame), f"no sample count belongs in the lymphoid frame: {frame}"
    assert "0 samples" not in frame
    # ...and the claim itself survives, resting on the study codes rather than on a count (case-insensitive:
    # this test is about the number, not about how the sentence is capitalised).
    assert "exists" in frame.lower() and "DLBC" in frame


def test_the_lymphoid_verdict_raises_a_tension_rather_than_reading_as_nothing_notable():
    """A neutral badge with a silent top_tension reads as "nothing notable" when the notable thing is that
    the axis cannot speak at all. The immune_cold branch can never fire here (the class is withheld)."""
    tension = _headline([_lymphoid_card()], _LYMPHOID_RULE)["headline_block"]["top_tension"]
    assert tension and "uninterpretable" in tension["text"]
    assert "not a measured effector absence" in tension["text"]


def test_the_lymphoid_verdict_leaves_the_positive_read_caveats_silent():
    """The bulk-inflation and spatial-localization caveats argue about a POSITIVE bulk read. On a withheld
    median they must stay None rather than reason about a number that does not exist."""
    hl = _headline([_lymphoid_card()], _LYMPHOID_RULE)
    assert hl["immune_confirmation_caveat"] is None
    assert hl["spatial_localization_caveat"] is None
