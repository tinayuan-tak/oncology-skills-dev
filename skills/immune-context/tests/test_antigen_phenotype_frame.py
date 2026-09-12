"""`antigen_phenotype_frame` (v1.10.0) — the IHC-anchored antigen-conditioning read.

`ici-response-imvigor210` had been in this skill's CARDS list since v1.4.0 with NONE of its 17
summary_fields read by any consumer — not even its own primary `ici_response_class`. Every run resolved
the card, wrote it to a display CSV and dropped it.

The three things these tests keep fixed:

  1 the field is READ (a whole fetched-and-dropped card is the defect; a frame nobody reads is the same
    defect one layer up, so the assertions go through `skill_report.claim_scalars`, the spine);
  2 the frame is NOT wired as a third orthogonal platform — `immune_phenotype_enriched_in` shares the
    desert/excluded/inflamed vocabulary with `spatial_immune_phenotype` but has a DIFFERENT REFERENT (a
    gene's expression argmax vs a cohort's immune architecture), so it must move neither the
    corroboration tier nor the conflict nor the verdict;
  3 it abstains where it must and NOT where it must not — strata NOT SEPARATED is a real abstention
    (an argmax over three group means always returns a token), but an indication SYNONYM is not: the
    scope-string guard in the first draft silently suppressed the live `urothelial` and `bladder` runs.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_RUN = Path(__file__).resolve().parents[1] / "scripts" / "run.py"
_spec = importlib.util.spec_from_file_location("immune_context_run_antigen", _RUN)
ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ic)

_INT_RULE = [{"rule_id": "immune-context-intermediate-tce-neutral"}]


def _imm(indication="BLCA"):
    """The live NECTIN4/BLCA immune-context shape. `indication` is emitted by this card (verified on a
    live run) and is what the scope guard reads — NOT the ICI card's own `indication` echo, which the
    card documents as landing 2026-09-13 and which today's live summary does not carry."""
    return {
        "card_id": "immune-context",
        "summary": {
            "immune_context_class": "immune_intermediate",
            "median_cd8_fraction": 0.1103,
            "median_total_t_cell_fraction": 0.3222,
            "n_samples": 433,
            "indication": indication,
        },
    }


def _ici(pheno="desert", kw=0.007031, scope="BLCA", **over):
    """Verbatim live NECTIN4/BLCA IMvigor210 values (2026-09-12) — a fixture value the producer never
    emits makes every assertion around it vacuous."""
    s = {
        "ici_response_class": "no_ici_association",
        "immune_phenotype_enriched_in": pheno,
        "kw_p_phenotype": kw,
        "mean_logcpm_desert": 7.2356,
        "mean_logcpm_excluded": 6.8364,
        "mean_logcpm_inflamed": 6.3127,
        "n_responder": 68,
        "n_nonresponder": 230,
        "indication_scope": scope,
    }
    s.update(over)
    return {"card_id": "ici-response-imvigor210", "summary": s}


def _saltz_missing():
    return {"card_id": "tcga-til-fraction-saltz", "_missing": True, "summary": {}}


def _frame(cards):
    hl = ic._headline([*cards, _saltz_missing()], _INT_RULE, ic._verdict(_INT_RULE))
    return hl, hl["skill_report"]["claim_scalars"]["antigen_phenotype_frame"]


# ── 1. the card's fields are actually read ────────────────────────────────────────────────────────
def test_the_previously_unread_ici_card_fields_reach_the_headline():
    hl, _ = _frame([_imm(), _ici()])
    assert hl["antigen_phenotype_enriched_in"] == "desert"
    assert hl["antigen_phenotype_kw_p"] == 0.007031
    assert hl["antigen_phenotype_scope"] == "BLCA"


def test_the_frame_is_on_the_spine_not_only_in_the_headline():
    """A frame that exists only inside `hl` repeats the defect it fixes: `claim_scalars` is what every
    downstream consumer of the skill_report actually sees."""
    hl, frame = _frame([_imm(), _ici()])
    assert frame and frame == hl["claim_vector"]["antigen_phenotype_frame"]


# ── 2. THE LIVE FINDING: NECTIN4 is highest where the T cells are not ─────────────────────────────
def test_a_significant_desert_enrichment_is_named_an_antigen_effector_mismatch():
    _, frame = _frame([_imm(), _ici()])
    assert "ANTIGEN-EFFECTOR MISMATCH" in frame
    assert "`desert`" in frame and "T cells are ABSENT" in frame
    # the per-stratum means must be printed, or the claim is unauditable
    assert "desert 7.2356" in frame and "excluded 6.8364" in frame and "inflamed 6.3127" in frame
    assert "p=0.007031" in frame


def test_excluded_is_distinguished_from_desert_not_collapsed_onto_it():
    """`excluded` is the subtle one: effectors ARE in the tumour, but shut out of the malignant nest.
    Reporting it with desert's wording would throw away the distinction the strata exist to carry."""
    _, frame = _frame([_imm(), _ici(pheno="excluded")])
    assert "ANTIGEN-EFFECTOR MISMATCH" in frame
    assert "SHUT OUT of the malignant nest" in frame
    assert "T cells are ABSENT" not in frame


def test_the_mismatch_is_scoped_to_the_TCE_and_not_read_as_a_target_defect():
    """The whole reason this rides the bite_tce lens: an ADC against the same antigen needs no effectors,
    and enfortumab vedotin is approved in this exact target/indication pair. Without this clause a
    desert enrichment reads as 'NECTIN4 is a bad target', which the clinic falsifies."""
    _, frame = _frame([_imm(), _ici()])
    assert "TCE-efficacy caveat, NOT a target-quality one" in frame
    assert "ADC" in frame


def test_an_inflamed_enrichment_is_the_favourable_read():
    _, frame = _frame([_imm(), _ici(pheno="inflamed")])
    assert "ANTIGEN-EFFECTOR CO-LOCALIZATION" in frame
    assert "MISMATCH" not in frame


# ── 3. the three abstentions, each distinct ───────────────────────────────────────────────────────
@pytest.mark.parametrize("kw", [0.31, 0.0501, None], ids=["clearly_ns", "just_over_the_gate", "no_p_at_all"])
def test_an_unseparated_argmax_makes_no_claim(kw):
    """An argmax over three group means ALWAYS returns a token — without the Kruskal-Wallis p it is a
    coin flip wearing a finding's clothes."""
    _, frame = _frame([_imm(), _ici(kw=kw)])
    assert "NOT SEPARATED" in frame
    assert "MISMATCH" not in frame and "CO-LOCALIZATION" not in frame
    # the token is still reported (auditable), just not claimed
    assert "`desert`" in frame


@pytest.mark.parametrize("asked", ["UROTHELIAL", "BLADDER"])
def test_an_indication_SYNONYM_keeps_the_claim_and_attributes_the_cohort(asked):
    """THE regression this test exists for. An earlier draft ABSTAINED whenever the asked indication did
    not string-match `indication_scope`. Live runs falsified it: `--indication urothelial` and
    `--indication bladder` both resolve the product correctly (phenotype `desert`, scope `BLCA`, kw
    0.007) and were silently suppressed, because the framework's indication vocabulary is fragmented and
    "UROTHELIAL" != "BLCA" as a string. That guard second-guessed the READER's own scope resolver with a
    weaker instrument and turned a real finding into silence.

    Scope is handled by ATTRIBUTION instead: the claim stands, and the prose names whose cohort it is —
    which is the actual defence against relabelling a scoped answer as the caller's indication."""
    _, frame = _frame([_imm(indication=asked), _ici()])
    assert "ANTIGEN-EFFECTOR MISMATCH" in frame, "a legitimate synonym must not be abstained away"
    assert f"asked as {asked}" in frame and "BLCA-scoped IMvigor210 cohort" in frame
    assert f"not a {asked}-specific one" in frame


def test_a_matching_indication_does_not_restate_the_scope_twice():
    """Non-vacuity partner: the attribution clause must be CONDITIONAL, or it is noise on every run."""
    _, frame = _frame([_imm(indication="BLCA"), _ici()])
    assert "asked as" not in frame
    assert "ANTIGEN-EFFECTOR MISMATCH" in frame


def test_an_out_of_scope_indication_reaches_no_phenotype_at_all():
    """The reader's own urothelial guard resolves data_unavailable outside urothelial, so a
    non-urothelial query never carries a phenotype token — verified live on LUAD/EGFR, which returns a
    bare `unmeasured`. This is why the frame needs no scope abstention of its own."""
    _, frame = _frame([_imm(indication="LUAD"), _ici(pheno=None, kw=None)])
    assert frame == "unmeasured"


def test_no_ici_card_is_a_bare_unmeasured():
    _, frame = _frame([_imm()])
    assert frame == "unmeasured"


def test_a_data_unavailable_ici_read_is_unmeasured_not_a_negative():
    """Outside urothelial the reader resolves data_unavailable and emits no phenotype. That is an absent
    MEASUREMENT — it must not read as 'the antigen and the effectors co-localize fine'."""
    _, frame = _frame([_imm(), _ici(pheno=None, kw=None)])
    assert frame == "unmeasured"


# ── 4. non-vacuity: the four branches are genuinely different strings ─────────────────────────────
def test_the_frame_is_not_a_constant():
    """The defect this whole change fixes is a surface that says the same thing regardless of the data
    (v1.8.0's `_immune_corr` returned a constant "moderate" for every indication). Guard against
    reintroducing one here."""
    seen = {
        _frame([_imm(), _ici()])[1],
        _frame([_imm(), _ici(pheno="excluded")])[1],
        _frame([_imm(), _ici(pheno="inflamed")])[1],
        _frame([_imm(), _ici(kw=0.4)])[1],
        _frame([_imm(indication="UROTHELIAL"), _ici()])[1],
        _frame([_imm()])[1],
    }
    assert len(seen) == 6, "at least two branches produced identical prose — the frame is partly vacuous"


# ── 5. THE CATEGORY-ERROR GUARD: it is not an orthogonal platform ─────────────────────────────────
def test_the_ici_phenotype_moves_neither_the_verdict_nor_the_corroboration_tier():
    """`immune_phenotype_enriched_in` shares the desert/excluded/inflamed vocabulary with
    `spatial_immune_phenotype`, so the tempting wiring is `_orthogonal_check`. That would be a category
    error: one is a statement about a COHORT's immune architecture, the other about where a GENE is
    expressed. This pins that the ICI card cannot corroborate or contradict the cohort class — a
    `desert` enrichment (the strongest form of this read) must leave the ruler untouched."""
    base, _ = _frame([_imm()])
    with_ici, frame = _frame([_imm(), _ici()])
    assert "ANTIGEN-EFFECTOR MISMATCH" in frame, "non-vacuity: the frame must actually be making its claim here"

    for k in ("immune_context_verdict", "driving_rule_id", "immune_context_class"):
        assert base[k] == with_ici[k], f"{k} moved on a verdict-INERT display field"
    for k in ("corroboration", "conflict", "signal"):
        assert (base["claim_vector"]["IMMUNE"] or {}).get(k) == (with_ici["claim_vector"]["IMMUNE"] or {}).get(k), (
            f"IMMUNE.{k} moved — the IHC phenotype is being read as an orthogonal platform for the cohort class"
        )
    assert base["skill_report"]["confidence"] == with_ici["skill_report"]["confidence"]
    assert base["skill_report"]["modality_scope"] == with_ici["skill_report"]["modality_scope"]


def test_the_other_three_frames_are_untouched_by_the_ici_card():
    """Byte-stability of the sibling scalars, so a future edit to the shared claim-vector builder cannot
    let the ICI read bleed into the pan-cancer/heterogeneity/suppression frames."""
    base, _ = _frame([_imm()])
    with_ici, _ = _frame([_imm(), _ici()])
    for k in ("reference_frame", "heterogeneity_frame", "suppression_frame"):
        assert base["claim_vector"][k] == with_ici["claim_vector"][k]
