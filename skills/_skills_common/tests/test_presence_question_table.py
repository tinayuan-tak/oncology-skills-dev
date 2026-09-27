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
    _cbyid,  # noqa: E402
    _fmt_r,  # noqa: E402
    _proxy_class,  # noqa: E402
    _q7_intrinsic,  # noqa: E402
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


def test_q2_generality_rna_only_reads_rna_breadth_not_data_unavailable():
    # #1513 F2: the protein breadth layer emits the TRUTHY string "data_unavailable" on a coverage
    # gap, so the old `br = protein or rna` selected the sentinel and the Q2 generality row showed
    # "breadth data_unavailable" for a genuine rna_only target. After the fix, absence sentinels are
    # falsy → Q2 reads the RNA breadth class.
    h = {
        "presence_verdict": "tumor_broadly_expressed",
        "tumor_elevation_breadth_class": "data_unavailable",
        "rna_tumor_elevation_breadth_class": "broadly_tumor_elevated",
    }
    cv = {"A": {}, "B": {}, "C": {}, "D": {"signal": "strong"}}
    q2 = _by_id(presence_question_table(h, [], cv))["Q2"]
    assert "breadth broadly_tumor_elevated" in q2["primary"]
    assert "data_unavailable" not in q2["primary"]


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


# ── Q4: WHICH subtype, when `spotlight_subtype` is a query echo ────────────────────────────────────
#
# `spotlight_subtype` on the tumour card is the `--subtype` CLI value copied verbatim, so it is None on
# every whole-cohort run — measured None in 937 of 937 packages across four corpora, while 32 of 504
# runs had 1-4 ENRICHED strata whose identities Q4 withheld. The same field name on the SIBLING
# cell-line card is a genuine argmax over enriched strata: one token, two meanings, which is why these
# tests pin the two sources APART instead of just pinning "a name appears".

# CDKN2A/HNSC shape, deliberately NOT median-ordered and with a non-enriched stratum mixed in, so an
# accidental `[0]` on emission order (or a filter that forgets `subtype_signal`) cannot pass.
_HNSC_STRATA = [
    {
        "stratum_id": "PIK3CA_mut",
        "subtype_signal": "subtype_enriched",
        "evidence_state": "measured",
        "median_log2tpm": 5.1,
        "n_tumor_samples": 48,
    },
    {
        "stratum_id": "site_oropharyngeal",
        "subtype_signal": "subtype_enriched",
        "evidence_state": "measured",
        "median_log2tpm": 7.4,
        "n_tumor_samples": 79,
    },
    {
        "stratum_id": "subtype_atypical",
        "subtype_signal": "subtype_restricted",
        "evidence_state": "measured",
        "median_log2tpm": 6.2,
        "n_tumor_samples": 31,
    },
    {
        "stratum_id": "HPV_negative",
        "subtype_signal": "not_enriched",
        "evidence_state": "measured",
        "median_log2tpm": 3.0,
        "n_tumor_samples": 120,
    },
]


def _enriched_fixture(strata=None, *, spotlight=None, n_enriched=4, n_measured=11, quality="powered"):
    """The base fixture with its uniform subtype card swapped for an ENRICHED one.

    The subtype claim vector is NOT injected: `presence_question_table` derives it from these same
    cards, so the test enters where a real run enters. Injecting it would leave the wiring untested.
    """
    h, cards, cv = _fixture()
    cards = [c for c in cards if c["card_id"] != "tumor-rna-distribution-by-subtype"]
    summary = {
        "subtype_axis_available": True,
        "subtype_axis_quality": quality,
        "subtype_stratification_class": "subtype_enriched",
        "n_subtypes_measured": n_measured,
        "n_subtypes_enriched": n_enriched,
        "per_subgroup_metrics": _HNSC_STRATA if strata is None else strata,
    }
    if spotlight is not None:
        summary["spotlight_subtype"] = spotlight
    return h, cards + [{"card_id": "tumor-rna-distribution-by-subtype", "summary": summary}], cv


def test_q4_names_the_data_driven_stratum_when_the_query_echo_is_absent():
    """The count alone was the whole row before this: "4/11 enriched" cannot tell a reader whether the
    axis is a usable selection handle, and in CDKN2A/HNSC the withheld identity is `site_oropharyngeal`
    — the HPV-associated site, i.e. precisely the fact the row exists to deliver."""
    r = _by_id(presence_question_table(*_enriched_fixture()))["Q4"]
    assert "(top site_oropharyngeal)" in r["primary"], r["primary"]
    assert "4/11 enriched" in r["primary"], r["primary"]
    assert "spotlight" not in r["primary"], "a data-driven pick must not claim the caller asked for it"
    assert r["signal"]["tier"] == "moderate" and r["signal"]["polarity"] != "neutral"


def test_q4_query_echo_still_wins_and_is_labelled_as_the_callers_pick():
    """When `--subtype` WAS passed, the caller's stratum is the subject of the run and outranks the
    data-driven pick — but it is labelled `spotlight`, never `top`. Collapsing the two labels would make
    the row unable to say whether a human chose the stratum or the data did."""
    r = _by_id(presence_question_table(*_enriched_fixture(spotlight="HPV_positive")))["Q4"]
    assert "(spotlight HPV_positive)" in r["primary"], r["primary"]
    assert "top " not in r["primary"], "the echo must not be relabelled as a data-driven pick"


def test_q4_support_ranks_the_enriched_set_by_median_not_emission_order():
    """`primary` names one stratum; the support line carries the rest, ranked by stratum median so the
    strongest is first. `site_oropharyngeal` is SECOND in emission order and highest by median, so an
    unranked read would report `PIK3CA_mut` as the leader — the alphabetical/emission-order starvation
    this census already found once elsewhere."""
    r = _by_id(presence_question_table(*_enriched_fixture()))["Q4"]
    assert "enriched: site_oropharyngeal, subtype_atypical, PIK3CA_mut" in r["support"], r["support"]
    assert "HPV_negative" not in r["support"], "a not_enriched stratum must not enter the enriched set"


def test_q4_single_enriched_stratum_is_not_repeated_in_support():
    """CCND1/ESCA shape (1/3 enriched). The support clause exists to answer "one stratum or four?", so
    with exactly one it would only echo `primary` — a duplicated name reads as two findings."""
    only = [_HNSC_STRATA[1], _HNSC_STRATA[3]]  # one enriched + one not_enriched
    r = _by_id(presence_question_table(*_enriched_fixture(only, n_enriched=1, n_measured=3)))["Q4"]
    assert "(top site_oropharyngeal)" in r["primary"], r["primary"]
    assert "enriched:" not in r["support"], r["support"]


def test_q4_exploratory_axis_does_not_read_as_a_subtype_differential():
    """SK#1518. `subtype_stratification_class` is derived from the MEASURED strata alone, so a single
    measured-enriched stratum in an `exploratory`-graded family yields `subtype_enriched` while the
    axis-quality grade says the axis is NOT powered (needs >=2 strata >=30). That combination must NOT
    read as a differential — exactly the case the function's :189-190 comment intends to block. Only a
    `powered` axis (test_q4_names_the_data_driven_stratum...) surfaces `moderate`/enriched here."""
    only = [_HNSC_STRATA[1]]  # one measured-enriched stratum; the rest never cleared the floor
    r = _by_id(presence_question_table(*_enriched_fixture(only, n_enriched=1, n_measured=6, quality="exploratory")))[
        "Q4"
    ]
    assert r["signal"]["tier"] == "unmeasured", r["signal"]
    assert r["signal"]["polarity"] == "none", "an exploratory axis must not carry a favourable polarity"
    assert "exploratory" in r["primary"] and "hypothesis-grade" in r["primary"], r["primary"]
    assert "enriched:" not in r["signal"]["label"], "must not label a hypothesis-grade axis as enriched"


def _q4_cellline_fixture(clsub_class, clsub_quality):
    """Base fixture with Card 9 (`cellline-rna-distribution-by-subtype`) set to a given capsule class
    and axis-quality grade, so the Q4 cell-line support bit can be exercised in isolation."""
    h, cards, cv = _fixture()
    for card in cards:
        if card["card_id"] == "cellline-rna-distribution-by-subtype":
            summ = {"subtype_stratification_class": clsub_class}
            if clsub_quality is not None:
                summ["subtype_axis_quality"] = clsub_quality
            card["summary"] = summ
    return h, cards, cv


def test_q4_cellline_support_bit_grades_an_exploratory_capsule_class():
    """SK#1519 (Card 9 reach). The cell-line capsule `subtype_stratification_class` is derived from the
    MEASURED strata alone, so a single measured-enriched DepMap stratum in an `exploratory`-graded family
    yields `subtype_enriched` while Card 9's own `subtype_axis_quality` says the genotype axis is NOT
    powered (no routed family reaches `powered` today). The Q4 support bit must carry that grade instead
    of surfacing the class as a bare differential fact."""
    r = _by_id(presence_question_table(*_q4_cellline_fixture("subtype_enriched", "exploratory")))["Q4"]
    assert "cell-line (genotype axis, exploratory): subtype_enriched" in r["support"], r["support"]
    assert "hypothesis-grade" in r["support"], r["support"]
    # The ungraded, bare-differential form is exactly what this fix removes.
    assert "cell-line (genotype axis): subtype_enriched" not in r["support"], r["support"]


def test_q4_cellline_support_bit_shows_powered_class_verbatim():
    """A `powered` cell-line axis IS a usable cross-subtype differential, so the class reads verbatim —
    the grade caveat must not fire on the one grade that supports the claim."""
    r = _by_id(presence_question_table(*_q4_cellline_fixture("subtype_enriched", "powered")))["Q4"]
    assert "cell-line (genotype axis): subtype_enriched" in r["support"], r["support"]
    assert "hypothesis-grade" not in r["support"], r["support"]


def test_q4_cellline_support_bit_leaves_non_differential_class_verbatim():
    """`pan_subtype_uniform` carries no differential claim, so no grade caveat is needed regardless of
    quality — the bit renders verbatim as before."""
    r = _by_id(presence_question_table(*_q4_cellline_fixture("pan_subtype_uniform", "exploratory")))["Q4"]
    assert "cell-line (genotype axis): pan_subtype_uniform" in r["support"], r["support"]
    assert "hypothesis-grade" not in r["support"], r["support"]


# ── Q6: show the correlation that actually classified ──────────────────────────────────────────────


def _concordance_fixture(tumor_summary):
    h, cards, cv = _fixture()
    cards = [c for c in cards if c["card_id"] != "rna-protein-concordance-tumor"]
    return h, cards + [{"card_id": "rna-protein-concordance-tumor", "summary": tumor_summary}], cv


def test_q6_shows_the_spearman_that_classified_not_the_pearson_beside_it():
    """ALK/NSCLC, real values. The producer classifies on SPEARMAN (its G10 note: the relation is
    monotonic-but-nonlinear and outlier-prone) and keeps `rna_protein_r` as Pearson. Printing the
    Pearson beside a Spearman-derived verdict made the number's own class contradict the label next to
    it in 113 of 375 cell-line rows and 31 of 195 tumor rows."""
    r = _by_id(
        presence_question_table(
            *_concordance_fixture(
                {
                    "rna_as_biomarker": "poor_proxy",
                    "rna_protein_spearman": 0.14,
                    "rna_protein_r": 0.86,
                    "n_paired_tumors": 90,
                }
            )
        )
    )["Q6"]
    assert "poor_proxy (ρ=0.14)" in r["primary"], r["primary"]
    assert "0.86" not in r["primary"], "the classifying metric is the one that belongs beside the class"
    assert "Pearson r=0.86 would read adequate_proxy" in r["support"], r["support"]


def test_q6_pearson_renders_unlabelled_when_it_is_what_classified():
    """No Spearman means the producer fell back to Pearson (`rna_proxy_classified_on`), and then Pearson
    IS the deciding metric — so it renders as a plain `r=` with no divergence caveat. The label tracks
    WHAT DECIDED, not a fixed metric name."""
    r = _by_id(presence_question_table(*_fixture()))["Q6"]  # base fixture has Pearson only
    assert "(r=0.41)" in r["primary"] and "ρ" not in r["primary"], r["primary"]
    assert "would read" not in r["support"], r["support"]


def test_q6_widens_precision_when_two_dp_would_misstate_the_class():
    """CCND1 shape: a Spearman of 0.6972 prints "0.70" at 2 dp — the `adequate_proxy` cut — directly
    beside a `partial_proxy` verdict. 15 of 570 displayable rows in the n=504 corpus round across a cut,
    so this is a routine row, not a corner."""
    r = _by_id(
        presence_question_table(
            *_concordance_fixture(
                {"rna_as_biomarker": "partial_proxy", "rna_protein_spearman": 0.6972, "n_paired_tumors": 90}
            )
        )
    )["Q6"]
    assert "partial_proxy (ρ=0.697)" in r["primary"], r["primary"]
    assert "0.70)" not in r["primary"], "2 dp would print the cut of the class ABOVE this one"


@pytest.mark.parametrize(
    "v, why",
    [
        (0.6972, "measured CCND1 cell-line value: rounds UP across the adequate cut at 2 dp"),
        (0.3954, "measured AKT1/HNSC value: rounds UP across the partial cut at 2 dp"),
        (0.6996, "3 dp is NOT enough here — it prints 0.700, so a fixed 3 dp would still misstate"),
        (0.7, "exactly on a cut: the class must be the producer's >= reading, not a rounding artifact"),
        (0.4, "the lower cut, same reason"),
        (-0.0334, "a negative correlation still has to render at all"),
        (0.0, "zero is a real value, not a missing one"),
    ],
)
def test_fmt_r_never_prints_a_number_of_a_different_class(v, why):
    """The ladder is exact rather than lucky BECAUSE of the producer's precision: `read.py` emits
    `round(spear, 4)` / `round(pear, 4)` at both call sites, so the 4 dp rung is the identity on
    anything it can emit and the loop always terminates on a faithful class."""
    assert _proxy_class(float(_fmt_r(v))) == _proxy_class(v), why
    assert len(_fmt_r(v).split(".")[1]) <= 4, "never print more precision than the producer computed"


def test_fmt_r_keeps_the_common_case_at_two_dp():
    """The widening must be the exception. A number rendered at 3 dp is a signal to the reader that it
    sits near a class cut, so widening everything would destroy that signal."""
    assert _fmt_r(0.41) == "0.41" and _fmt_r(0.14) == "0.14" and _fmt_r(0.86) == "0.86"


# ── Q6: rna_high_protein_low_fraction cited ONLY as a downward departure from the 0.10 null (#1824) ──
#
# The field's NO-INFORMATION value is 0.10 by construction (protein <= the 10th percentile of the SAME
# protein vector; corpus median exactly 0.1000). #1382 (8bd8b67c) decided it may be cited ONLY as a
# one-sided DOWNWARD departure from that labelled null — as concordance evidence — never as a bare
# "RNA misleads in X%" rate. #1532 (7915a8b0) briefly wired it the opposite way; #1824 restores #1382.

_CL_CARD = "cellline-rna-protein-concordance"


def _q6_support_with_cl(cl_summary):
    """Run the real question table with the cell-line concordance card set to `cl_summary` (None ⇒ card
    absent). `cl_summary` is the ONLY supply path reaching the discordant-quadrant caveat, so mutating
    it here defeats every route to the fire condition on line 409/421."""
    h, cards, cv = _fixture()
    cards = [c for c in cards if c["card_id"] != _CL_CARD]
    if cl_summary is not None:
        cards.append({"card_id": _CL_CARD, "summary": cl_summary})
    return _by_id(presence_question_table(h, cards, cv))["Q6"]["support"]


def test_q6_discordance_caveat_does_not_fire_at_the_010_construction_null():
    """The construction null (0.10) and the ±0.005 noise band around it are what independence alone
    gives — the OLD bare-rate consumer fired an alarming "⚠ RNA misleads in 10%" on essentially every
    card at exactly this value. It must now stay silent."""
    for null_ish in (0.10, 0.0999, 0.095, 0.11, 0.1333):  # at / just-below-within-band / above the null
        support = _q6_support_with_cl({"rna_as_biomarker": "adequate_proxy", "rna_high_protein_low_fraction": null_ish})
        assert "misleads" not in support, (null_ish, support)
        assert "RNA↔protein concordant" not in support, f"{null_ish} is not a downward departure: {support}"


def test_q6_discordance_caveat_fires_as_concordance_below_the_null_labelled_with_it():
    """A genuine one-sided DOWNWARD departure (as at AR 0.0000) reads as CONCORDANCE evidence, labelled
    with the 0.10 construction null, and NEVER as a bare 'RNA misleads' rate."""
    for below in (0.0, 0.03, 0.089):  # clearly below the null's ±0.005 band
        support = _q6_support_with_cl({"rna_as_biomarker": "adequate_proxy", "rna_high_protein_low_fraction": below})
        assert "RNA↔protein concordant" in support, (below, support)
        assert "10% independence null" in support, f"must label the construction null: {support}"
        assert "misleads" not in support and "⚠ RNA" not in support, f"never a bare alarming rate: {support}"


def test_q6_discordance_caveat_omits_cleanly_when_the_field_or_card_is_absent():
    """Defeat the remaining supply routes: field None, field missing, and card absent — none may fire
    the caveat or raise."""
    for cl in ({"rna_high_protein_low_fraction": None}, {"rna_as_biomarker": "adequate_proxy"}, None):
        support = _q6_support_with_cl(cl)
        assert "misleads" not in support and "RNA↔protein concordant" not in support, (cl, support)


# ── Q7: SURFACE the L2b bulk×single-cell coverage-concordance signal (SK#1507 G3.1) ─────────────────
#
# The L2b `bulk_vs_singlecell_coverage_concordance` claim (presence_claims.py, emitted by #1517) was
# read by nothing until now. G3.1 SURFACES it as an `integrated_signal` annotation on the Q7 answer —
# verdict-INERT (the row's signal/confidence meter is untouched), attached only when the claim resolves.
# The claim is built by the REAL claim builder so the presentation logic is exercised end-to-end, not
# re-stated here (a re-derived fixture cannot fail).

from _skills_common.presence_claims import presence_claim_vector  # noqa: E402


def _coverage_claim(coverage_class="high", escape_class="escape_risk_low", bulk_class="broadly_high"):
    trd = {"tumor_expression_class": bulk_class, "distribution_pattern": "continuous"}
    sc = {"sc_expression_class": "malignant_subset_detected"}
    if coverage_class is not None:
        sc["within_tumor_coverage_class"] = coverage_class
    if escape_class is not None:
        sc["tce_antigen_escape_class"] = escape_class
    cards = [
        {"card_id": "tumor-rna-distribution", "summary": trd},
        {"card_id": "tumor-scrna-celltype-expression", "summary": sc},
    ]
    return presence_claim_vector({"presence_verdict": "tumor_broadly_expressed"}, cards)[
        "bulk_vs_singlecell_coverage_concordance"
    ]


def _q7_with_coverage_claim(claim):
    h, cards, cv = _fixture()
    if claim is not None:
        cv = {**cv, "bulk_vs_singlecell_coverage_concordance": claim}
    return _by_id(presence_question_table(h, cards, cv))["Q7"]


def test_q7_omits_integrated_signal_when_the_claim_is_absent():
    # Byte-stability: with no coverage claim in the vector (the base fixture), Q7 carries no
    # integrated_signal key at all — the row is unchanged, the meter cells untouched.
    r = _by_id(presence_question_table(*_fixture()))["Q7"]
    assert "integrated_signal" not in r
    # and the meter cells are exactly the pre-existing malignant-intrinsic read
    assert r["signal"]["tier"] == "strong" and r["confidence"]["tier"] == "high"


def test_q7_surfaces_concordant_signal_both_directions_no_meter_change():
    claim = _coverage_claim(coverage_class="high", escape_class="escape_risk_low")
    r = _q7_with_coverage_claim(claim)
    isig = r["integrated_signal"]
    assert isig["kind"] == "bulk_vs_singlecell_coverage_concordance"
    assert isig["concordance_class"] == "coverage_concordant"
    # verdict-INERT surface: the annotation carries NO signal tier / polarity / fill, and the row's own
    # meter cells are the UNCHANGED malignant-intrinsic read (this adds an annotation, never a tier).
    assert "tier" not in isig and "polarity" not in isig and "fill" not in isig
    assert r["signal"]["tier"] == "strong" and r["confidence"]["tier"] == "high"
    # both directions surfaced: the encouraging bulk read present, the qualifying caveat NULL (concordant)
    assert isig["positive_signal"]["source"] == "bulk_tumor_presence"
    assert isig["qualifying_signal"] is None
    assert "CONFIRMS" in isig["headline"] and isig["boundary_sensitive"] is False
    assert set(isig["source_support"]) == {"bulk_tumor_presence", "single_cell_malignant_coverage"}


def test_q7_surfaces_the_qualifying_direction_for_bulk_masks_low_coverage():
    claim = _coverage_claim(coverage_class="low", escape_class="escape_risk_high")
    isig = _q7_with_coverage_claim(claim)["integrated_signal"]
    assert isig["concordance_class"] == "bulk_masks_low_coverage"
    assert isig["qualifying_signal"] is not None
    # the headline names BOTH directions — the encouraging bulk read AND the "However" caveat
    assert "However" in isig["headline"]
    assert isig["boundary_sensitive"] is False  # low coverage + high escape corroborate → not boundary


def test_q7_integrated_signal_flags_boundary_sensitivity_when_class_rests_on_a_lone_token():
    # Part 6.5: an alarming class resting on a single uncorroborated coverage token must be surfaced as
    # boundary-sensitive, never asserted flat — the headline carries the flag the consumer renders.
    claim = _coverage_claim(coverage_class="low", escape_class=None)  # escape off-scale → single_arm
    isig = _q7_with_coverage_claim(claim)["integrated_signal"]
    assert isig["concordance_class"] == "bulk_masks_low_coverage"
    assert isig["boundary_sensitive"] is True
    assert "boundary-sensitive" in isig["headline"]


def _derive_q7_from_cards(coverage_class, escape_class, bulk_class="broadly_high"):
    """Enter where run.py enters: build the row from CARDS with NO pre-built claim_vector, so
    presence_question_table DERIVES the claim itself (presence_question_table.py:432 fallback →
    presence_claim_vector). This proves the surface is wired end-to-end, not merely when a claim is
    hand-injected. The base fixture carries no tumor-scrna card; swap in one with the modern sc fields."""
    h, cards, _cv = _fixture()
    cards = [c for c in cards if c["card_id"] != "tumor-scrna-celltype-expression"]
    for c in cards:
        if c["card_id"] == "tumor-rna-distribution":
            c["summary"] = {
                "tumor_expression_class": bulk_class,
                "distribution_pattern": "continuous",
                "allgene_percentile": 99.9,
                "allgene_percentile_class": "top_1pct",
            }
    sc = {"sc_expression_class": "malignant_subset_detected"}
    if coverage_class is not None:
        sc["within_tumor_coverage_class"] = coverage_class
    if escape_class is not None:
        sc["tce_antigen_escape_class"] = escape_class
    cards.append({"card_id": "tumor-scrna-celltype-expression", "summary": sc})
    # claim_vector=None AND headline carries none → the builder derives it from cards, as run.py does.
    h = {k: v for k, v in h.items() if k != "claim_vector"}
    return _by_id(presence_question_table(h, cards, None))["Q7"]


def test_q7_derives_and_surfaces_the_signal_end_to_end_from_cards():
    # EPCAM-shaped concordant PANEL case, derived (not injected): the run.py path surfaces it.
    r = _derive_q7_from_cards(coverage_class="high", escape_class="escape_risk_low")
    assert r["integrated_signal"]["concordance_class"] == "coverage_concordant"
    assert r["integrated_signal"]["qualifying_signal"] is None


def test_q7_derives_the_lossy_case_and_the_absence_case_from_cards():
    # TACSTD2-shaped lossy PANEL case, derived: the qualifying escape direction is surfaced.
    lossy = _derive_q7_from_cards(coverage_class="low", escape_class="escape_risk_high")
    assert lossy["integrated_signal"]["concordance_class"] == "bulk_masks_low_coverage"
    assert lossy["integrated_signal"]["qualifying_signal"] is not None
    # M3 reach: defeat EVERY single-cell supply path (both sc fields absent) → the claim omits and the
    # row falls back CLEANLY to no integrated_signal (never a fabricated one), the meter cells intact.
    gone = _derive_q7_from_cards(coverage_class=None, escape_class=None)
    assert "integrated_signal" not in gone
    assert gone["question"] == "Is the tumor signal malignant-cell-intrinsic?"


# ── Q6: SURFACE the L2b RNA×MS-protein abundance-MAGNITUDE concordance signal (SK#1594 L2b-4) ────────
#
# The L2b `abundance_concordance` claim (presence_claims.py, built by #1589/#1621) was read by nothing
# until now. SK#1594 SURFACES it as an `integrated_signal` annotation on the Q6 ("Do RNA and protein
# agree?") answer — the magnitude-level RNA↔protein agreement, distinct from Q6's population
# proxy-correlation read. Verdict-INERT (the row's signal/confidence meter is untouched), attached only
# when the claim resolves. The claim is built by the REAL builder so the presentation logic is exercised
# end-to-end, not re-stated here (a re-derived fixture cannot fail).


def _abundance_claim(tumor_rna="top_decile", tumor_protein="top_decile", cl_rna=None, cl_gygi=None, cl_procan=None):
    cards = []

    def _c(cid, cls):
        if cls is not None:
            cards.append({"card_id": cid, "summary": {"allgene_percentile_class": cls}})

    _c("tumor-rna-distribution", tumor_rna)
    _c("tumor-protein-abundance-cptac", tumor_protein)
    _c("cellline-rna-distribution", cl_rna)
    _c("cellline-protein-abundance", cl_gygi)
    _c("cellline-protein-abundance-procan", cl_procan)
    return presence_claim_vector({"presence_verdict": "tumor_broadly_expressed"}, cards)["abundance_concordance"]


def _q6_with_abundance_claim(claim):
    h, cards, cv = _fixture()
    if claim is not None:
        cv = {**cv, "abundance_concordance": claim}
    return _by_id(presence_question_table(h, cards, cv))["Q6"]


def test_q6_omits_integrated_signal_when_the_claim_is_absent():
    # Byte-stability: with no abundance claim in the passed vector, Q6 carries no integrated_signal key.
    r = _by_id(presence_question_table(*_fixture()))["Q6"]
    assert "integrated_signal" not in r


def test_q6_surfaces_concordant_signal_both_directions_no_meter_change():
    # baseline row (no claim) vs enriched row (claim injected): the meter cells must be BYTE-IDENTICAL —
    # the surface adds an annotation, never a tier.
    base = _by_id(presence_question_table(*_fixture()))["Q6"]
    claim = _abundance_claim(
        tumor_rna="top_decile", tumor_protein="top_decile", cl_rna="top_1pct", cl_gygi="top_decile"
    )
    r = _q6_with_abundance_claim(claim)
    assert r["signal"] == base["signal"] and r["confidence"] == base["confidence"]
    isig = r["integrated_signal"]
    assert isig["kind"] == "abundance_concordance"
    assert isig["concordance_class"] == "abundance_concordant"
    # verdict-INERT annotation: no signal tier / polarity / fill on the integrated_signal itself
    assert "tier" not in isig and "polarity" not in isig and "fill" not in isig
    # both directions surfaced: encouraging cross-modality read present, qualifying caveat NULL (concordant)
    assert isig["positive_signal"]["source"] == "rna_abundance"
    assert isig["qualifying_signal"] is None
    assert "same" in isig["headline"].lower() and isig["boundary_sensitive"] is False
    assert set(isig["source_support"]) == {"rna_abundance", "ms_protein_abundance"}


def test_q6_surfaces_the_qualifying_direction_for_rna_high_protein_low():
    claim = _abundance_claim(tumor_rna="top_decile", tumor_protein="mid")  # high vs moderate → rna_high_protein_low
    isig = _q6_with_abundance_claim(claim)["integrated_signal"]
    assert isig["concordance_class"] == "rna_high_protein_low"
    assert isig["qualifying_signal"] is not None
    # the headline names BOTH directions — the encouraging detection read AND the "However" caveat
    assert "However" in isig["headline"]
    assert isig["rna_magnitude"] == "high" and isig["protein_magnitude"] == "moderate"


def test_q6_integrated_signal_flags_boundary_sensitivity_when_class_rests_on_a_lone_grain():
    # A directional split resting on a SINGLE grain (no cross-grain corroboration) must be surfaced as
    # boundary-sensitive, never asserted flat — the headline carries the flag the consumer renders.
    claim = _abundance_claim(tumor_rna="top_decile", tumor_protein="mid")  # tumor grain only → single_arm
    isig = _q6_with_abundance_claim(claim)["integrated_signal"]
    assert isig["corroboration"] == "single_arm"
    assert isig["boundary_sensitive"] is True
    assert "boundary-sensitive" in isig["headline"]


def _derive_q6_from_cards(tumor_rna, tumor_protein):
    """Enter where run.py enters: build the row from CARDS with NO pre-built claim_vector, so
    presence_question_table DERIVES the claim itself (fallback → presence_claim_vector). This proves the
    surface is wired end-to-end, not merely when a claim is hand-injected."""
    h, cards, _cv = _fixture()
    for c in cards:
        if c["card_id"] == "tumor-rna-distribution":
            c["summary"] = {**c["summary"], "allgene_percentile_class": tumor_rna}
        if c["card_id"] == "tumor-protein-abundance-cptac":
            c["summary"] = {**c["summary"], "allgene_percentile_class": tumor_protein}
    h = {k: v for k, v in h.items() if k != "claim_vector"}
    return _by_id(presence_question_table(h, cards, None))["Q6"]


def test_q6_derives_and_surfaces_the_signal_end_to_end_from_cards():
    # concordant PANEL case, derived (not injected): the run.py path surfaces it.
    r = _derive_q6_from_cards(tumor_rna="top_1pct", tumor_protein="top_1pct")
    assert r["integrated_signal"]["concordance_class"] == "abundance_concordant"
    assert r["integrated_signal"]["qualifying_signal"] is None
    # directional PANEL case, derived: the qualifying split direction is surfaced.
    split = _derive_q6_from_cards(tumor_rna="top_1pct", tumor_protein="mid")
    assert split["integrated_signal"]["concordance_class"] == "rna_high_protein_low"
    assert split["integrated_signal"]["qualifying_signal"] is not None


def test_q6_defeat_every_protein_supply_omits_the_row_signal_cleanly():
    # M3 reach: defeat the protein modality (no tumor CPTAC, no cell-line protein) → the claim omits and
    # the row falls back CLEANLY to no integrated_signal (never a fabricated one), meter cells intact.
    h, cards, _cv = _fixture()
    cards = [c for c in cards if c["card_id"] not in ("tumor-protein-abundance-cptac", "cellline-protein-abundance")]
    h = {k: v for k, v in h.items() if k != "claim_vector"}
    r = _by_id(presence_question_table(h, cards, None))["Q6"]
    assert "integrated_signal" not in r
    assert r["question"] == "Do RNA and protein agree?"


# ── Q4: SURFACE the L2b subtype_restriction_concordance signal (SK#1840 L2b->L3) ────────────────────
#
# The L2b `subtype_restriction_concordance` claim (presence_claims.py, built by #1830 on the BY-SUBTYPE
# claim vector) was read by NOTHING until now — a dead-end carrier. SK#1840 SURFACES it as an
# `integrated_signal` annotation on the Q4 ("Do subtypes differ?") answer — the cross-modality (bulk-RNA
# x MS-protein) subtype-restriction agreement, distinct from Q4's within-cohort enrichment read.
# Verdict-INERT (the row's signal/confidence meter is untouched), attached only when the claim resolves.
# The claim is built by the REAL builder so the presentation logic is exercised end-to-end. Read off the
# BY-SUBTYPE vector `sv` (derived inside presence_question_table via presence_claim_vector_by_subtype),
# NOT the pooled `cv`; the injection tests patch the RESOLVING namespace so ONLY the claim key differs.

from _skills_common.claim_vector_core import cards_by_id as _by_id_for_test  # noqa: E402
from _skills_common.presence_claims import (  # noqa: E402
    _subtype_restriction_concordance_claim,
    presence_claim_vector_by_subtype,
)


def _sr_by_subtype_cards(rna_q="powered", rna_cls="subtype_restricted", prot_q=None, prot_cls=None):
    """The three by-subtype cards exercising the subtype_restriction_concordance builder's arms (mirror
    of test_presence_claims._sr_cards). An arm with axis_quality=None is absent/unresolved."""
    return [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_axis_quality": rna_q,
                "subtype_stratification_class": rna_cls,
                "subtype_variance_explained": 0.34,
                "subtype_effect_size_class": "large",
                "n_subtypes_measured": 4,
                "n_subtypes_enriched": 2,
                "n_subtypes_restricted": 1,
                "per_subgroup_metrics": [
                    {
                        "stratum_id": "A",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_uniform",
                        "median_log2tpm": 1.0,
                        "n_tumor_samples": 50,
                        "fraction_tumor_above_normal_p95": 0.1,
                    }
                ],
            },
        },
        {
            "card_id": "tumor-protein-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_axis_quality": prot_q,
                "subtype_stratification_class": prot_cls,
                "n_subtypes_measured": 3,
                "n_subtypes_enriched": 1,
            },
        },
    ]


def _sr_claim(**kw):
    return _subtype_restriction_concordance_claim(_by_id_for_test(_sr_by_subtype_cards(**kw)))


def _q4_with_injected_sv(monkeypatch, claim):
    """Isolate the delta: patch the resolving namespace so the by-subtype vector is the fixture's REAL sv
    with ONLY `subtype_restriction_concordance` added (or absent) — Q4's row content is unchanged, so any
    meter-cell difference would be the claim's doing, and there is none."""
    import _skills_common.presence_claims as pc

    h, cards, cv = _fixture()
    base_sv = presence_claim_vector_by_subtype(cards) or {}
    assert "subtype_restriction_concordance" not in base_sv  # the base fixture does NOT resolve it

    def _patched(_cards):
        sv = dict(base_sv)
        if claim is not None:
            sv["subtype_restriction_concordance"] = claim
        return sv

    monkeypatch.setattr(pc, "presence_claim_vector_by_subtype", _patched)
    return _by_id(presence_question_table(h, cards, cv))["Q4"], base_sv


def test_q4_omits_integrated_signal_when_the_claim_is_absent():
    # Byte-stability: the base fixture's by-subtype axis does not resolve subtype_restriction_concordance,
    # so Q4 carries no integrated_signal key at all — the row is unchanged, meter cells untouched.
    r = _by_id(presence_question_table(*_fixture()))["Q4"]
    assert "integrated_signal" not in r


def test_q4_surfaces_subtype_restriction_concordant_both_directions_no_meter_change(monkeypatch):
    # baseline row (claim absent from sv) vs enriched row (claim injected into sv): the meter cells must be
    # BYTE-IDENTICAL — the surface adds an annotation, never a tier.
    base, _ = _q4_with_injected_sv(monkeypatch, None)
    assert "integrated_signal" not in base
    claim = _sr_claim(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="subtype_enriched")
    r, _ = _q4_with_injected_sv(monkeypatch, claim)
    assert r["signal"] == base["signal"] and r["confidence"] == base["confidence"]
    isig = r["integrated_signal"]
    assert isig["kind"] == "subtype_restriction_concordance"
    assert isig["concordance_class"] == "subtype_restriction_concordant"
    assert isig["provenance_ref"] == "claim_vector_by_subtype.subtype_restriction_concordance"
    # verdict-INERT annotation: no signal tier / polarity / fill on the integrated_signal itself
    assert "tier" not in isig and "polarity" not in isig and "fill" not in isig
    # both directions surfaced: encouraging cross-modality read present, qualifying caveat NULL (concordant)
    assert isig["positive_signal"] is not None
    assert isig["qualifying_signal"] is None
    assert "agree" in isig["headline"].lower() and isig["boundary_sensitive"] is False


def test_q4_surfaces_the_qualifying_direction_for_protein_masks_rna_only(monkeypatch):
    # RNA sees a restriction, protein powered but uniform → the RNA-only false positive. BOTH directions
    # must be surfaced — the encouraging in-modality read AND the "However" discordance caveat.
    claim = _sr_claim(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="pan_subtype_uniform")
    isig = _q4_with_injected_sv(monkeypatch, claim)[0]["integrated_signal"]
    assert isig["concordance_class"] == "protein_masks_subtype_restriction"
    assert isig["qualifying_signal"] is not None
    assert "However" in isig["headline"]


def test_q4_integrated_signal_flags_boundary_sensitivity_when_class_rests_on_a_lone_arm(monkeypatch):
    # A concordance class resting on a SINGLE resolved arm (no cross-modality corroboration) must be
    # surfaced as boundary-sensitive, never asserted flat — the headline carries the flag.
    claim = _sr_claim(rna_q="powered", rna_cls="subtype_restricted", prot_q=None, prot_cls=None)
    isig = _q4_with_injected_sv(monkeypatch, claim)[0]["integrated_signal"]
    assert isig["boundary_sensitive"] is True
    assert "boundary-sensitive" in isig["headline"]


def test_q4_derives_and_surfaces_the_signal_end_to_end_from_cards():
    # Enter where run.py enters: replace the fixture's by-subtype cards with powered arms and pass NO
    # pre-built vector, so presence_question_table DERIVES the by-subtype vector itself and attaches the
    # integrated_signal on Q4. Proves the surface is wired end-to-end, not merely on hand-injected sv.
    h, cards, _cv = _fixture()
    cards = [c for c in cards if c["card_id"] != "tumor-rna-distribution-by-subtype"]
    cards.extend(
        _sr_by_subtype_cards(
            rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="subtype_enriched"
        )
    )
    h = {k: v for k, v in h.items() if k != "claim_vector"}
    r = _by_id(presence_question_table(h, cards, None))["Q4"]
    assert r["integrated_signal"]["concordance_class"] == "subtype_restriction_concordant"
    assert r["integrated_signal"]["kind"] == "subtype_restriction_concordance"


# ── SK#1842 L3→production (2nd domain): corroborated_tumor_presence frame surfacing ─────────────────
def _l3_coverage_claim(state="coverage_concordant", corr="high"):
    """A valid L2b bulk_vs_singlecell_coverage_concordance envelope claim (explicit_deterministic)."""
    return {
        "concordance_class": state,
        "corroboration": corr,
        "integration_method": "explicit_deterministic",
        "positive_signal": {"statement": "bulk reads broadly present"},
        "qualifying_signal": None,
        "boundary_sensitive": False,
        "source_support": {},
    }


def test_l3_presence_frame_signal_attaches_to_q7_when_coverage_resolves():
    """When the L2b coverage concordance anchor resolves, the corroborated_tumor_presence L3 PRESENCE_FRAME
    synthesis surfaces as a verdict-INERT l3_integrated_signal on the Q7 row."""
    h, cards, cv = _fixture()
    cv["bulk_vs_singlecell_coverage_concordance"] = _l3_coverage_claim()
    q7 = _by_id(presence_question_table(h, cards, cv))["Q7"]
    isig = q7["l3_integrated_signal"]
    assert isig["kind"] == "corroborated_tumor_presence"
    assert isig["frame_id"] == "corroborated_tumor_presence"
    assert isig["claim_type"] == "decision_frame"  # L3
    assert isig["provenance_ref"] == "evidence_frame.corroborated_tumor_presence"
    assert isig["integration_method"] == "explicit_deterministic"
    # the anchor coverage claim is a resolved typed input the frame synthesized over
    assert isig["resolved_inputs"].get("bulk_vs_singlecell_coverage_concordance") == "coverage_concordant"
    # verdict-INERT annotation: NEVER a meter cell.
    assert "tier" not in isig and "polarity" not in isig and "fill" not in isig


def test_l3_presence_frame_forward_question_is_the_absent_safety_critical_and_never_a_kill():
    """The frame's CRITICAL_UNKNOWN role (the safety normal_liability_concordance, structurally absent on a
    tumor-presence surface) renders as an L4 forward question — never a kill."""
    h, cards, cv = _fixture()
    cv["bulk_vs_singlecell_coverage_concordance"] = _l3_coverage_claim()
    q7 = _by_id(presence_question_table(h, cards, cv))["Q7"]
    fq = q7["l3_forward_question"]
    assert fq["kind"] == "l4_forward_question"
    assert fq["role"] == "critical_unknown"
    assert fq["unresolved_critical"] == ["normal_liability_concordance"]
    assert "normal_liability_concordance" in fq["question"]
    # the frame routed to a QUESTION (never a HOLD/kill), and the annotation says so.
    assert q7["l3_integrated_signal"]["decision"] == "question"
    assert q7["l3_integrated_signal"]["unresolved_critical"] == ["normal_liability_concordance"]


def test_l3_presence_annotation_omitted_when_coverage_absent_and_never_clobbers_the_l2b_signal():
    """Byte-stable: with no coverage concordance claim on the vector the Q7 row carries neither the L3
    l3_integrated_signal nor the l3_forward_question; and when the claim IS present, attaching the L3 frame
    leaves the row's meter cells AND the existing L2b coverage `integrated_signal` byte-identical to what
    _q7_intrinsic (which knows nothing of the L3 frame) produces."""
    h, cards, cv = _fixture()
    assert "bulk_vs_singlecell_coverage_concordance" not in cv
    bare_q7 = _by_id(presence_question_table(h, cards, cv))["Q7"]
    assert "l3_integrated_signal" not in bare_q7 and "l3_forward_question" not in bare_q7

    cv2 = dict(cv)
    cv2["bulk_vs_singlecell_coverage_concordance"] = _l3_coverage_claim()
    framed_q7 = _by_id(presence_question_table(h, cards, cv2))["Q7"]
    # the L3-augmented row's meter cells + the L2b coverage integrated_signal match the bare _q7_intrinsic
    # output (no L3 knowledge) — the L3 attach added ONLY the distinct l3_* keys.
    ref_q7 = _q7_intrinsic(h, _cbyid(cards), cv2)
    assert framed_q7["signal"] == ref_q7["signal"]
    assert framed_q7["confidence"] == ref_q7["confidence"]
    assert framed_q7["primary"] == ref_q7["primary"] and framed_q7["support"] == ref_q7["support"]
    # the pre-existing L2b coverage projection is untouched (distinct key, never clobbered)
    assert framed_q7["integrated_signal"] == ref_q7["integrated_signal"]
    assert framed_q7["integrated_signal"]["kind"] == "bulk_vs_singlecell_coverage_concordance"
