"""presence_question_table — the 7-question (data · signal · confidence) projection that leads the
tumor-presence dashboard. Verdict-inert; computed from the claim_vector + answer-key card fields.

Hermetic: a fixture headline + cards + an explicit claim_vector (so the test does not depend on the
claim_vector's own computation details) exercise the per-question mapping and the CEACAM5-shaped story
(strong abundance, comparator-discordance window caveat, uniform subtypes, top-1% absolute, malignant-
intrinsic)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

COMMON = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON.parent))  # skills/

from _skills_common.presence_question_table import (
    _top_labels,  # noqa: E402
    presence_question_table,  # noqa: E402
)


def _fixture():
    headline = {"presence_verdict": "tumor_broadly_expressed"}
    cv = {
        "A": {"signal": "strong", "corroboration": "moderate", "evidence": "anchored: top 1% all-gene"},
        "B": {
            "signal": "moderate",
            "corroboration": "moderate",
            "evidence": "CPTAC:up; RNA-DGE:flat",
            "conflict": "comparator discordance: CPTAC elevated but RNA-DGE flat",
        },
        "C": {
            "signal": "strong",
            "corroboration": "high",
            "evidence": "malignant_broadly_detected (malignant frac 0.76, n=446 donors)",
        },
        "D": {"signal": "strong", "corroboration": "moderate", "evidence": "breadth broadly_tumor_elevated"},
        "homogeneity": "homogeneous",
    }
    cards = [
        {
            "card_id": "cellline-rna-distribution",
            "summary": {
                "expression_class": "lineage_restricted",
                "allgene_percentile": 29.6,
                "allgene_percentile_class": "mid",
            },
        },
        {"card_id": "cellline-protein-abundance", "summary": {}, "_missing": True},
        {
            "card_id": "tumor-rna-distribution",
            "summary": {"allgene_percentile": 99.9, "allgene_percentile_class": "top_1pct"},
        },
        {
            "card_id": "tumor-rna-vs-adjacent",
            "summary": {"allgene_percentile": 27.7, "allgene_percentile_class": "mid"},
        },
        {
            "card_id": "tumor-protein-abundance-cptac",
            "summary": {"allgene_percentile": 99.7, "allgene_percentile_class": "top_1pct"},
        },
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_stratification_class": "pan_subtype_uniform",
                "n_subtypes_measured": 14,
                "n_subtypes_enriched": 0,
            },
        },
        {
            "card_id": "cellline-rna-distribution-by-subtype",
            "summary": {"subtype_stratification_class": "pan_subtype_uniform"},
        },
        {
            "card_id": "normal-tissue-liability",
            "summary": {
                "normal_tissue_breadth_class": "broad_normal_expression",
                # real shape + real values (epcam_coadread). NOT intensity-ordered: the producer is a
                # bare split(";") over an HPA string, so the display has to rank it — see
                # test_q3_ranks_tissues_by_intensity_because_the_card_does_not.
                "specific_tissues": [{"tissue": "intestine", "intensity": 20770505.4}],
            },
        },
        {
            # Deliberately NOT in alphabetical order, and one row past the k=3 cap, so an accidental
            # `sorted(...)[:n]` — the alphabetical-starvation failure this census already found once —
            # cannot pass these tests. Real shape: a dict per row, most-elevated first.
            "card_id": "tumor-elevation-breadth",
            "summary": {
                "most_elevated_cohorts": [
                    {"cohort": "OV", "protein_effect_size": 1.49},
                    {"cohort": "BRCA", "protein_effect_size": 1.07},
                    {"cohort": "UCEC", "protein_effect_size": 0.88},
                    {"cohort": "LUAD", "protein_effect_size": 0.51},
                ],
                "rna_most_elevated_indications": [
                    {"indication": "UCEC", "max_abs_log2fc": 7.89},
                    {"indication": "ESCA", "max_abs_log2fc": 5.67},
                ],
            },
        },
        {
            "card_id": "sc-normal-celltype-expression",
            "summary": {"sc_normal_expression_class": "HIGH_LIABILITY", "max_detection_cell_type": "BEST4+ colonocyte"},
        },
        {
            "card_id": "rna-protein-concordance-tumor",
            "summary": {"rna_as_biomarker": "partial_proxy", "rna_protein_r": 0.41, "n_paired_tumors": 90},
        },
        {
            "card_id": "cellline-rna-protein-concordance",
            "summary": {"rna_as_biomarker": "adequate_proxy", "rna_protein_r": 0.74},
        },
        {"card_id": "expression-purity-confound", "summary": {"purity_confound_class": "purity_independent"}},
    ]
    return headline, cards, cv


def _by_id(rows):
    return {r["id"]: r for r in rows}


def test_seven_rows_in_order():
    h, cards, cv = _fixture()
    rows = presence_question_table(h, cards, cv)
    assert [r["id"] for r in rows] == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"]


def test_q1_abundance_from_claim_A_with_cellline_support():
    r = _by_id(presence_question_table(*_fixture()))["Q1"]
    assert r["signal"]["tier"] == "strong" and r["signal"]["polarity"] == "supports"
    assert "lineage_restricted" in r["support"]  # cell-line proxy is the supporting read


def test_q2_support_names_WHICH_cohorts_not_only_how_many():
    """The primary line answers "how many" (4/9 cohorts); the row asks "vs OTHER cancers?", which is a
    question about WHICH ones. `most_elevated_cohorts` / `rna_most_elevated_indications` carried the
    answer on every run and were displayed on none — no generic capsule selector can reach a
    list-valued field, so a question row is the only surface that can show them at all."""
    r = _by_id(presence_question_table(*_fixture()))["Q2"]
    assert "top protein: OV, BRCA, UCEC" in r["support"]
    assert "top RNA: UCEC, ESCA" in r["support"]


def test_q2_support_preserves_emission_order_and_caps_at_three():
    """Both halves matter and fail differently. Emission order IS reading order (the cards emit
    most-elevated first), so alphabetizing would silently promote whichever cohort sorts first — the
    same substitution of NAMING for CONTENT that `sorted(...)[:4]` already caused once in the capsule
    hint scan. The cap keeps a 9-cohort panel from swamping a support line."""
    support = _by_id(presence_question_table(*_fixture()))["Q2"]["support"]
    assert support.index("OV") < support.index("BRCA") < support.index("UCEC"), "cohorts were re-sorted"
    assert "LUAD" not in support, "the 4th cohort leaked past the k=3 cap"


def test_q3_surfaces_window_caveat_from_normal_cards():
    r = _by_id(presence_question_table(*_fixture()))["Q3"]
    # claim B drives the meter; the supporting line carries the discordance + normal-tissue window caveat
    assert "comparator discordance" in r["support"]
    assert "broad_normal_expression" in r["support"] and "HIGH_LIABILITY" in r["support"]
    assert "⚠ window" in r["signal"]["label"]


def test_q3_names_the_normal_tissue_behind_the_breadth_class():
    """`broad_normal_expression` is a grade, not a finding. For a GI target the tissue it grades is
    `intestine` — the tumour's own organ of origin, which is the entire safety content of the row.
    Mirrors the `(max: <cell type>)` shape the single-cell caveat beside it already uses."""
    r = _by_id(presence_question_table(*_fixture()))["Q3"]
    assert "broad_normal_expression (specific: intestine)" in r["support"]


def test_q3_ranks_tissues_by_intensity_because_the_card_does_not():
    """REGRESSION, and the values are the real tacstd2_coadread ones because they are what falsified the
    assumption this test now pins. `normal-tissue-liability.card.yaml` documents `specific_tissues` as
    "parsed from the intensity field" and names NO order; the producer
    (`hpa_normal_tissue_liability/cli.py:parse_specific_tissues`) is a bare `split(";")`. In tacstd2 that
    puts `lung` (2.2e7) AHEAD of the more abundant `salivary gland` (2.4e7) — so an unranked `[:k]` would
    report the alphabetically-first normal tissue as the liability and drop the worst one, on the row a
    reader consults for exactly that. Contrast the Q2 test above, which asserts the OPPOSITE for cohorts:
    those cards do promise "effect-desc", so re-sorting them would be the error there.
    """
    h, cards, cv = _fixture()
    cards = [c for c in cards if c["card_id"] != "normal-tissue-liability"] + [
        {
            "card_id": "normal-tissue-liability",
            "summary": {
                "normal_tissue_breadth_class": "broad_normal_expression",
                "specific_tissues": [
                    {"tissue": "lung", "intensity": 22139708.2},
                    {"tissue": "salivary gland", "intensity": 23989590.1},
                ],
            },
        }
    ]
    support = _by_id(presence_question_table(h, cards, cv))["Q3"]["support"]
    assert "specific: salivary gland, lung" in support, support


def test_q4_uniform_is_neutral_not_a_magnitude():
    r = _by_id(presence_question_table(*_fixture()))["Q4"]
    assert r["signal"]["tier"] == "uniform" and r["signal"]["polarity"] == "neutral"
    assert "uniform" in r["primary"]


def test_q5_level_vs_effect_labeled_and_level_drives_signal():
    r = _by_id(presence_question_table(*_fixture()))["Q5"]
    # LEVEL rank (tumor top-1%) drives the signal; effect ranks (CPTAC) are supporting, labeled distinctly
    assert r["signal"]["tier"] == "strong"
    assert "level:" in r["primary"] and "tumor RNA" in r["primary"]
    assert "effect:" in r["support"] and "CPTAC protein effect" in r["support"]
    assert r["confidence"]["tier"] == "high"


def test_q7_intrinsic_from_claim_C_with_purity_support():
    r = _by_id(presence_question_table(*_fixture()))["Q7"]
    assert r["signal"]["tier"] == "strong"
    assert "purity_independent" in r["support"]


def test_verdict_inert_no_exceptions_on_sparse_headline():
    # a near-empty headline/cards must degrade to unmeasured rows, never raise
    rows = presence_question_table({}, [], {"A": {}, "B": {}, "C": {}, "D": {}})
    assert len(rows) == 7
    assert all(r["signal"]["tier"] == "unmeasured" for r in rows if r["id"] in ("Q1", "Q7"))


def test_q2_and_q3_omit_the_detail_rather_than_inventing_it():
    """The cards these read are OPTIONAL — a target with no CPTAC breadth arm has no
    `tumor-elevation-breadth` card at all. The clause must vanish, never appear empty ("top protein: ")
    and never fabricate a label."""
    h, cards, cv = _fixture()
    thin = [c for c in cards if c["card_id"] not in ("tumor-elevation-breadth", "normal-tissue-liability")]
    rows = _by_id(presence_question_table(h, thin, cv))
    assert "top protein" not in rows["Q2"]["support"] and "top RNA" not in rows["Q2"]["support"]
    assert "specific:" not in rows["Q3"]["support"]
    assert rows["Q2"]["support"], "Q2 lost its breadth-concordance clause too"


# ── _top_labels: the container reader behind both rows ─────────────────────────────────────────────


def test_top_labels_reads_the_dict_row_shape_in_order():
    rows = [{"cohort": "OV"}, {"cohort": "BRCA"}, {"cohort": "UCEC"}, {"cohort": "LUAD"}]
    assert _top_labels(rows, "cohort") == ["OV", "BRCA", "UCEC"]
    assert _top_labels(rows, "cohort", k=1) == ["OV"]


def test_top_labels_degrades_instead_of_raising_on_a_changed_row_shape():
    """These fields feed a VERDICT-INERT display path, so a producer that changes its row shape should
    cost labels, not raise inside a dashboard build. Each input below is a different shape drift."""
    assert _top_labels(["OV", "BRCA"], "cohort") == ["OV", "BRCA"]  # plain strings
    assert _top_labels([{"other_key": "OV"}], "cohort") == []  # key renamed away
    assert _top_labels([{"cohort": None}, {"cohort": 3}, {"cohort": ""}], "cohort") == []  # non-str / empty
    assert _top_labels(None, "cohort") == [] and _top_labels([], "cohort") == []


def test_top_labels_deduplicates_so_a_repeated_label_does_not_eat_the_cap():
    assert _top_labels([{"t": "intestine"}, {"t": "intestine"}, {"t": "colon"}], "t") == ["intestine", "colon"]


def test_top_labels_rank_by_orders_descending_and_only_when_asked():
    """`rank_by` is opt-in precisely so the default cannot silently re-sort a producer-ranked list. Both
    directions are asserted on the SAME input, because a helper that always sorted would pass the first
    assertion alone and quietly break Q2's contract-promised effect-desc order."""
    rows = [{"t": "a", "i": 1.0}, {"t": "b", "i": 3.0}, {"t": "c", "i": 2.0}]
    assert _top_labels(rows, "t", rank_by="i") == ["b", "c", "a"]
    assert _top_labels(rows, "t") == ["a", "b", "c"], "emission order was re-sorted without rank_by"
    assert _top_labels(rows, "t", k=2, rank_by="i") == ["b", "c"], "the cap must apply AFTER ranking"


@pytest.mark.parametrize(
    "bad, why",
    [
        (None, "the producer's own except-branch writes None on an unparseable intensity"),
        ("2.4e7", "a string that merely looks numeric must not be compared against floats"),
        (float("nan"), "NaN compares False against everything, so it has no defined rank"),
        (float("inf"), "inf is a NUMBER: it passes an isna/truthiness guard and wins every comparison"),
        (float("-inf"), "the mirror case, which a naive `> 0` guard would also admit"),
    ],
)
def test_top_labels_rank_by_sorts_unrankable_values_last(bad, why):
    """A row we cannot rank must never DISPLACE a measured one — it may only fill a leftover slot. The
    inf cases are the reason this is a finiteness test and not `v is not None`."""
    rows = [{"t": "unrankable", "i": bad}, {"t": "measured", "i": 1.0}]
    assert _top_labels(rows, "t", k=1, rank_by="i") == ["measured"], why
    assert _top_labels(rows, "t", rank_by="i") == ["measured", "unrankable"], "it should still be shown"


def test_top_labels_rank_by_tolerates_the_shapes_that_have_no_rank_at_all():
    """Same degrade-not-raise contract as the unranked path: a plain-string row and a row missing the
    rank key both sort last rather than raising inside a dashboard build."""
    rows = [{"t": "no-rank-key"}, "bare-string", {"t": "ranked", "i": 5.0}]
    assert _top_labels(rows, "t", rank_by="i")[0] == "ranked"
    assert _top_labels([], "t", rank_by="i") == [] and _top_labels(None, "t", rank_by="i") == []
