"""Unit test for the presence claim-vector citable atoms (skills/_skills_common/presence_claims.py).
Presence builds its claims MANUALLY (not via ClaimSpec.atom_fn), so this pins that each measured claim
binds its load-bearing card values to {card_id, fields} + entity, and that the key is OMITTED (not
None) when the source card is absent — matching the other axes' atom discipline. Pure; no S3."""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.presence_claims import (  # noqa: E402
    presence_claim_vector,
    presence_claim_vector_by_subtype,
)


def _cards():
    return [
        {
            "card_id": "tumor-rna-distribution",
            "summary": {
                "tumor_expression_class": "broadly_detected",
                "control_position_class": "above_negatives_below_positives",
                "control_position": "above 3/4 positive control(s); above 3/5 negative control(s)",
                "allgene_percentile": 52.5,
                "median_log2tpm": 3.97,
                "distribution_pattern": "continuous",
            },
        },
        {
            "card_id": "tumor-rna-vs-adjacent",
            "summary": {
                "expression_call_class": "modest_upregulation",
                "log2_fc": 0.8,
                "q_value": 1e-16,
                "n_tumor": 624,
            },
        },
        {
            "card_id": "tumor-scrna-celltype-expression",
            "summary": {
                "sc_expression_class": "malignant_subset_detected",
                "malignant_detection_fraction": 0.48,
                "malignant_n_donors": 362,
                "caf_vs_malignant_class": "shared_caf_malignant",
            },
        },
        {
            "card_id": "tumor-elevation-breadth",
            "summary": {
                "tumor_elevation_breadth_class": "multi_tumor_elevated",
                "n_cohorts_elevated": 3,
                "n_cohorts_tested": 10,
            },
        },
    ]


def _headline():
    return {
        "bulk_rna_proxy_quality": "rna_positive_proxy_partial",
        "sc_expression_class": "malignant_subset_detected",
        "sc_malignant_detection_fraction": 0.48,
        "sc_n_donor_groups": 362,
        "tumor_elevation_breadth_class": "multi_tumor_elevated",
        "tumor_elevation_n_cohorts_tested": 10,
    }


def test_presence_atoms_present_and_citable_with_cards():
    vec = presence_claim_vector(_headline(), _cards())
    a = vec["A"]["evidence_atom"]
    assert a["cite"]["card_id"] == "tumor-rna-distribution"
    assert a["values"]["median_log2tpm"] == 3.97
    b = vec["B"]["evidence_atom"]
    assert b["cite"]["card_id"] == "tumor-rna-vs-adjacent" and b["values"]["log2_fc"] == 0.8
    assert vec["C"]["evidence_atom"]["values"]["malignant_detection_fraction"] == 0.48
    assert vec["D"]["evidence_atom"]["cite"]["card_id"] == "tumor-elevation-breadth"
    assert vec["D"]["evidence_atom"]["values"]["n_cohorts_elevated"] == 3


def test_presence_atoms_omitted_without_cards():
    # cards=[] → source cards absent → the evidence_atom KEY is omitted (not None), byte-stable
    vec = presence_claim_vector(_headline(), [])
    for ax in ("A", "B", "C", "D"):
        assert "evidence_atom" not in vec[ax], f"{ax} carries an atom with no source card"


# ── expression_properties: the shared L2 facet, surfaced verdict-inert (P4, SK#1508) ─────────────
# Store the raw resolved facet and RE-DERIVE the surfaced atom in-test: the wiring is a pure
# passthrough, so the atom's values must EQUAL the raw input (a derived fixture cannot fail; the raw
# facet is the irreproducible input). EPCAM-shaped, mirroring the P2 resolver output for a bimodal
# cell-line panel (presence=supported, prevalence=subset, heterogeneity=high).
_RAW_EXPRESSION_PROPERTIES = {
    "presence": "supported",
    "magnitude": "high",
    "prevalence": "subset",
    "heterogeneity": "high",
    "lineage_restriction": "diffuse",
    "selectivity": "unmeasured",
    "localization": "unmeasured",
    "subtype_restriction": "unmeasured",
}


def _cards_with_expression_properties(props=_RAW_EXPRESSION_PROPERTIES):
    cards = _cards()
    cards.append({"card_id": "cellline-rna-distribution", "summary": {"expression_properties": dict(props)}})
    return cards


def test_expression_properties_atom_surfaces_and_is_recoverable():
    vec = presence_claim_vector(_headline(), _cards_with_expression_properties())
    assert "expression_properties" in vec, "the shared L2 facet must surface on the claim vector"
    atom = vec["expression_properties"]["evidence_atom"]
    # Cited to the cell-line arm, with its measurement entity.
    assert atom["cite"]["card_id"] == "cellline-rna-distribution"
    assert atom["cite"]["fields"] == ["expression_properties"]
    assert atom["entity"] == {"measurement_type": "cellline_rna_expression", "sample_context": "cell_line"}
    # FIDELITY INVARIANT: the actual property VALUES are recoverable, not merely a key. Re-derive by
    # equality against the stored raw facet — a passthrough must reproduce it byte-for-byte.
    surfaced = atom["values"]["expression_properties"]
    assert surfaced == _RAW_EXPRESSION_PROPERTIES
    assert surfaced["heterogeneity"] == "high"
    assert surfaced["prevalence"] == "subset"


def test_expression_properties_is_verdict_inert_not_a_claim_tier():
    # A provenance scalar, NOT an A/B/C/D-style claim: no `signal`/`corroboration`, so it is never a
    # chip and never enters any tier arithmetic. And surfacing it must not perturb the four claims.
    base = presence_claim_vector(_headline(), _cards())
    withprops = presence_claim_vector(_headline(), _cards_with_expression_properties())
    ep = withprops["expression_properties"]
    assert "signal" not in ep and "corroboration" not in ep
    for ax in ("A", "B", "C", "D", "homogeneity", "_disclaimer"):
        assert withprops[ax] == base[ax], f"surfacing expression_properties perturbed {ax}"


def test_expression_properties_omitted_when_card_absent():
    # M3 supply-defeat #1: no cellline-rna-distribution card at all → the KEY is omitted (byte-stable),
    # exactly like the A/B/C/D atoms. This is the path the committed replay fixture takes.
    vec = presence_claim_vector(_headline(), _cards())
    assert "expression_properties" not in vec


def test_expression_properties_omitted_when_field_absent():
    # M3 supply-defeat #2: the card is present but emits no expression_properties (e.g. an older run,
    # or a data_unavailable panel the resolver leaves unset) → build_summary_atom returns None → the
    # key is omitted, never a None-valued atom.
    cards = _cards()
    cards.append({"card_id": "cellline-rna-distribution", "summary": {"expression_class": "broadly_moderate"}})
    vec = presence_claim_vector(_headline(), cards)
    assert "expression_properties" not in vec


def test_homogeneity_unmeasured_not_null_without_scrna():
    # No single-cell card (SCLC / NECTIN4-BRCA-pair scRNA = data_unavailable) → homogeneity must be
    # the STRING sentinel "unmeasured", never null. null fails the evidence_package claim_vector schema
    # (oneOf[string, object]) and aborts the envelope emit for every scRNA-less indication.
    hl = {k: v for k, v in _headline().items() if not k.startswith("sc_")}
    vec = presence_claim_vector(hl, [])
    assert vec["homogeneity"] == "unmeasured"
    assert vec["homogeneity"] is not None
    # a real single-cell homogeneity class still passes through verbatim
    vec2 = presence_claim_vector({**hl, "sc_tce_homogeneity_class": "homogeneous"}, [])
    assert vec2["homogeneity"] == "homogeneous"


def test_claim_d_corroboration_inherits_an_unmeasured_signal():
    # `breadth_class: data_unavailable` is not in claim D's signal map, so the signal is "unmeasured" —
    # and the corroboration must follow it. The two ladders read DIFFERENT card fields (signal <- the
    # breadth CLASS, corroboration <- the n-tested COUNT) and nothing coupled them, so a declined claim
    # used to ship a top-rung tier: measured on the n=504 corpus, 30 pairs emitted (unmeasured, high)
    # off `n_tested = 26`, which is the card's cohort ROSTER size (26 on 502 of 504 pairs), not a
    # per-target measurement. "Tested over 26 cohorts, answer withheld" is not a coverage statement.
    hl = {**_headline(), "tumor_elevation_breadth_class": "data_unavailable", "tumor_elevation_n_cohorts_tested": 26}
    d = presence_claim_vector(hl, [])["D"]
    assert d["signal"] == "unmeasured"
    assert d["corroboration"] == "unmeasured", "a tier for a claim never stated is attached to nothing"
    # the same holds when the count is small enough to have laddered to a LOWER rung — this is the one
    # frozen-atlas row (n_tested=3) that became the lone minority class of an otherwise-constant column
    # and drew a 17.2-sigma one-rung displacement on a claim that was never made.
    hl3 = {**hl, "tumor_elevation_n_cohorts_tested": 3}
    assert presence_claim_vector(hl3, [])["D"]["corroboration"] == "unmeasured"
    # a missing breadth class (key absent entirely) takes the same path
    hl_missing = {k: v for k, v in _headline().items() if k != "tumor_elevation_breadth_class"}
    assert presence_claim_vector(hl_missing, [])["D"]["corroboration"] == "unmeasured"


def test_claim_d_corroboration_still_ladders_when_the_claim_is_stated():
    # NEGATIVE CONTROL — passes before AND after the coupling above. A STATED claim keeps the full
    # n_tested ladder verbatim, so the fix cannot be mistaken for "claim D stopped corroborating":
    # 472 of the 504 corpus pairs sit here and must be byte-identical across the change.
    for n, want in (
        (26, "high"),
        (10, "high"),
        (9, "moderate"),
        (5, "moderate"),
        (4, "low"),
        (1, "low"),
        (0, "unmeasured"),
    ):
        hl = {
            **_headline(),
            "tumor_elevation_breadth_class": "multi_tumor_elevated",
            "tumor_elevation_n_cohorts_tested": n,
        }
        d = presence_claim_vector(hl, [])["D"]
        assert d["signal"] == "moderate", "a stated breadth class must still state its signal"
        assert d["corroboration"] == want, f"n_tested={n} must ladder to {want}, not {d['corroboration']}"
    # and every non-unmeasured signal rung reaches the ladder, not just the one above
    for br, sig in (
        ("broadly_tumor_elevated", "strong"),
        ("multi_tumor_elevated", "moderate"),
        ("single_tumor_elevated", "weak"),
        ("not_tumor_elevated", "absent"),
    ):
        hl = {**_headline(), "tumor_elevation_breadth_class": br, "tumor_elevation_n_cohorts_tested": 26}
        d = presence_claim_vector(hl, [])["D"]
        assert (d["signal"], d["corroboration"]) == (sig, "high"), f"{br} must keep its laddered tier"


# ── L2b-1: bulk × single-cell coverage concordance (SK#1517) ─────────────────────────────────────
# A CROSS-SOURCE integration claim: bulk tumor-presence (tumor-rna-distribution) integrated with
# single-cell malignant coverage (tumor-scrna-celltype-expression). Store the RAW source-property
# inputs and RE-DERIVE the claim in-test — a derived fixture cannot fail; the raw properties are the
# irreproducible inputs. Panel of 2: EPCAM (concordant) and TACSTD2/TROP2 (bulk masks low coverage).

# EPCAM/COADREAD (replay-fixture shaped): bulk broadly present + high sc malignant coverage + low escape.
_RAW_EPCAM = {
    "bulk_class": "broadly_high",
    "distribution_pattern": "continuous",
    "coverage_class": "high",
    "escape_class": "escape_risk_low",
}
# TACSTD2/TROP2/COADREAD (tumor-selectivity fixture shaped): bulk broadly present but LOW sc coverage +
# high antigen escape — the population-averaged bulk read masks the malignant fraction that escapes.
_RAW_TACSTD2 = {
    "bulk_class": "broadly_high",
    "distribution_pattern": "continuous",
    "coverage_class": "low",
    "escape_class": "escape_risk_high",
}


def _l2b_cards(
    bulk_class="broadly_high", distribution_pattern="continuous", coverage_class="high", escape_class="escape_risk_low"
):
    """A minimal card set carrying the two SOURCE properties the L2b claim integrates. `coverage_class`
    / `escape_class` set to None omit that field (source-absence / off-scale supply-defeat paths)."""
    trd_summary = {"tumor_expression_class": bulk_class, "distribution_pattern": distribution_pattern}
    sc_summary = {
        "sc_expression_class": "malignant_subset_detected",
        "malignant_detection_fraction": 0.48,
        "malignant_n_donors": 362,
    }
    if coverage_class is not None:
        sc_summary["within_tumor_coverage_class"] = coverage_class
    if escape_class is not None:
        sc_summary["tce_antigen_escape_class"] = escape_class
    return [
        {"card_id": "tumor-rna-distribution", "summary": trd_summary},
        {"card_id": "tumor-scrna-celltype-expression", "summary": sc_summary},
    ]


def test_coverage_concordance_epcam_is_concordant():
    # EPCAM: broad bulk presence AGREES with high single-cell malignant coverage → coverage_concordant,
    # corroborated by escape_risk_low. Re-derive from the stored raw source properties.
    vec = presence_claim_vector(
        _headline(),
        _l2b_cards(
            bulk_class=_RAW_EPCAM["bulk_class"],
            distribution_pattern=_RAW_EPCAM["distribution_pattern"],
            coverage_class=_RAW_EPCAM["coverage_class"],
            escape_class=_RAW_EPCAM["escape_class"],
        ),
    )
    claim = vec["bulk_vs_singlecell_coverage_concordance"]
    assert claim["concordance_class"] == "coverage_concordant"
    assert claim["corroboration"] == "high"  # coverage arm + escape arm both agree (2 measured arms)
    assert claim["integration_method"] == "explicit_deterministic"  # NO llm_inference: reproducible by contract
    # Provenance graph records BOTH source properties, recoverable, + an independence note.
    srcs = {s["property"]: s for s in claim["provenance"]["sources"]}
    assert srcs["bulk_tumor_presence"]["card_id"] == "tumor-rna-distribution"
    assert srcs["bulk_tumor_presence"]["fields"]["tumor_expression_class"] == _RAW_EPCAM["bulk_class"]
    assert srcs["single_cell_malignant_coverage"]["card_id"] == "tumor-scrna-celltype-expression"
    assert (
        srcs["single_cell_malignant_coverage"]["fields"]["within_tumor_coverage_class"] == _RAW_EPCAM["coverage_class"]
    )
    assert srcs["single_cell_malignant_coverage"]["fields"]["tce_antigen_escape_class"] == _RAW_EPCAM["escape_class"]
    assert "independent" in claim["provenance"]["independence_note"].lower()


def test_coverage_concordance_tacstd2_bulk_masks_low_coverage():
    # TACSTD2/TROP2: broad bulk presence COEXISTS with LOW single-cell coverage (+ high antigen escape)
    # → bulk_masks_low_coverage. A bulk-only lens cannot state this — it is a cross-source integration.
    vec = presence_claim_vector(
        _headline(),
        _l2b_cards(
            bulk_class=_RAW_TACSTD2["bulk_class"],
            distribution_pattern=_RAW_TACSTD2["distribution_pattern"],
            coverage_class=_RAW_TACSTD2["coverage_class"],
            escape_class=_RAW_TACSTD2["escape_class"],
        ),
    )
    claim = vec["bulk_vs_singlecell_coverage_concordance"]
    assert claim["concordance_class"] == "bulk_masks_low_coverage"
    assert claim["corroboration"] == "high"  # low coverage + high escape both point the same way
    srcs = {s["property"]: s for s in claim["provenance"]["sources"]}
    assert srcs["single_cell_malignant_coverage"]["fields"]["within_tumor_coverage_class"] == "low"
    assert srcs["single_cell_malignant_coverage"]["fields"]["tce_antigen_escape_class"] == "escape_risk_high"


def test_coverage_concordance_is_verdict_inert():
    # Verdict-INERT: the claim carries NO `signal` key (never a chip, never a tier), and surfacing it
    # must not perturb the four claims / homogeneity / _disclaimer. Toggle ONLY within_tumor_coverage_class
    # — a field the A/B/C/D claims do NOT read — so any A/B/C/D delta would be MY perturbation, not claim C's.
    base = presence_claim_vector(_headline(), _l2b_cards(coverage_class=None))  # no coverage → claim omitted
    withclaim = presence_claim_vector(_headline(), _l2b_cards(coverage_class="high"))
    assert "bulk_vs_singlecell_coverage_concordance" not in base
    claim = withclaim["bulk_vs_singlecell_coverage_concordance"]
    assert "signal" not in claim, "an L2b claim must never carry a signal tier"
    for ax in ("A", "B", "C", "D", "homogeneity", "_disclaimer"):
        assert withclaim[ax] == base[ax], f"surfacing the coverage-concordance claim perturbed {ax}"


def test_coverage_concordance_all_supply_mutation_flip_both_flips_class():
    # M3 (all-supply): to FLIP the concordance class you must defeat EVERY single-cell supply path —
    # flip BOTH coverage AND escape. EPCAM concordant → mutate to TACSTD2-shaped → bulk_masks_low_coverage.
    concordant = presence_claim_vector(_headline(), _l2b_cards(coverage_class="high", escape_class="escape_risk_low"))[
        "bulk_vs_singlecell_coverage_concordance"
    ]
    flipped = presence_claim_vector(_headline(), _l2b_cards(coverage_class="low", escape_class="escape_risk_high"))[
        "bulk_vs_singlecell_coverage_concordance"
    ]
    assert concordant["concordance_class"] == "coverage_concordant"
    assert flipped["concordance_class"] == "bulk_masks_low_coverage", "flipping BOTH sc facets must flip the class"


def test_coverage_concordance_single_supply_mutation_only_degrades():
    # M3-vs-M4 fidelity: flipping ONE arm (escape only) must NOT flip the class — the coverage axis is
    # the primary determinant — but it DEGRADES corroboration (high → low), so the concept survives on
    # the coverage arm. This is the "defeat every supply path" discipline: one flip erodes, it cannot erase.
    both_agree = presence_claim_vector(_headline(), _l2b_cards(coverage_class="high", escape_class="escape_risk_low"))[
        "bulk_vs_singlecell_coverage_concordance"
    ]
    escape_flipped = presence_claim_vector(
        _headline(), _l2b_cards(coverage_class="high", escape_class="escape_risk_high")
    )["bulk_vs_singlecell_coverage_concordance"]
    assert both_agree["corroboration"] == "high"
    assert escape_flipped["concordance_class"] == "coverage_concordant", "flipping only escape must NOT flip the class"
    assert escape_flipped["corroboration"] == "low", "a disagreeing escape arm degrades corroboration"
    # and an OFF-SCALE / absent escape arm drops to single_arm (below the measured-arm floor), not high
    escape_gone = presence_claim_vector(_headline(), _l2b_cards(coverage_class="high", escape_class=None))[
        "bulk_vs_singlecell_coverage_concordance"
    ]
    assert escape_gone["concordance_class"] == "coverage_concordant"
    assert escape_gone["corroboration"] == "single_arm"


def test_coverage_concordance_omitted_when_a_source_is_absent_or_indecisive():
    # Byte-stability: the KEY is omitted (not None) unless BOTH source properties resolve.
    # (a) bulk not broadly present → no claim (subset/absent bulk is off-precondition)
    assert "bulk_vs_singlecell_coverage_concordance" not in presence_claim_vector(
        _headline(), _l2b_cards(bulk_class="subset_high")
    )
    # (b) single-cell coverage card/field absent → no claim
    assert "bulk_vs_singlecell_coverage_concordance" not in presence_claim_vector(
        _headline(), _l2b_cards(coverage_class=None)
    )
    # (c) single-cell coverage neither high nor low (indecisive) → no claim
    assert "bulk_vs_singlecell_coverage_concordance" not in presence_claim_vector(
        _headline(), _l2b_cards(coverage_class="moderate")
    )
    # (d) no cards at all → no claim
    assert "bulk_vs_singlecell_coverage_concordance" not in presence_claim_vector(_headline(), [])


def _by_subtype_cards():
    """A tumor-rna-distribution-by-subtype card mirroring CD274/COADREAD: MSI_H/CMS1/CIMP_High enriched,
    MSS uniform — the per-stratum subtype_signal is set, the rollup carries n_subtypes_enriched=3."""
    return [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_stratification_class": "subtype_enriched",
                "subtype_variance_explained": 0.34,
                "subtype_effect_size_class": "large",
                "which_subtypes_separate": {"highest": "CMS1", "lowest": "CMS2"},
                "n_subtypes_measured": 4,
                "per_subgroup_metrics": [
                    {
                        "stratum_id": "MSI_H",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_enriched",
                        "median_log2tpm": 2.51,
                        "n_tumor_samples": 47,
                        "fraction_tumor_above_normal_p95": 0.4,
                    },
                    {
                        "stratum_id": "CMS1",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_enriched",
                        "median_log2tpm": 2.29,
                        "n_tumor_samples": 90,
                        "fraction_tumor_above_normal_p95": 0.35,
                    },
                    {
                        "stratum_id": "MSS",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_uniform",
                        "median_log2tpm": 1.01,
                        "n_tumor_samples": 205,
                        "fraction_tumor_above_normal_p95": 0.1,
                    },
                ],
            },
        }
    ]


def test_enriched_subtype_identities_are_projected_and_ranked():
    # FACET 1: the enriched-stratum IDENTITIES are surfaced (not just the count), ranked by median desc,
    # and top_enriched_subtype is the data-driven pick (distinct from the query-echo spotlight_subtype).
    cv = presence_claim_vector_by_subtype(_by_subtype_cards())
    ids = [e["stratum"] for e in cv["enriched_subtypes"]]
    assert ids == ["MSI_H", "CMS1"], f"enriched identities MSI_H>CMS1 by median, got {ids}"
    assert "MSS" not in ids  # subtype_uniform is not a positive-selection identity
    assert cv["top_enriched_subtype"] == "MSI_H"
    assert cv["enriched_subtypes"][0]["subtype_signal"] == "subtype_enriched"


def test_no_axis_returns_none_and_empty_enrichment_is_a_list():
    assert presence_claim_vector_by_subtype([]) is None
    cards = [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_stratification_class": "pan_subtype_uniform",
                "n_subtypes_measured": 3,
                "per_subgroup_metrics": [
                    {
                        "stratum_id": "A",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_uniform",
                        "median_log2tpm": 1.0,
                        "n_tumor_samples": 50,
                    }
                ],
            },
        }
    ]
    cv = presence_claim_vector_by_subtype(cards)
    assert cv["enriched_subtypes"] == [] and cv["top_enriched_subtype"] is None  # uniform → empty, never None list
