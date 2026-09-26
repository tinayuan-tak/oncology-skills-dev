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
from _skills_common.subgroup_derivation import _SUBGROUP_N_FLOOR  # noqa: E402  # #1625 single-sourced floor


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


def test_claim_d_rna_only_reads_rna_breadth_not_unmeasured():
    # #1513 F2 (truthy-sentinel): the protein breadth layer emits the TRUTHY string "data_unavailable"
    # on a coverage gap, so the old `br = protein or rna` fallback selected the sentinel and never fell
    # through — a genuine rna_only target (protein gap + RNA broadly elevated across 27 indications) had
    # its RNA breadth silently dropped and claim D read sig="unmeasured". After the fix, absence
    # sentinels are treated as falsy so br falls through to the RNA class → sig="strong".
    hl = {
        **_headline(),
        "tumor_elevation_breadth_class": "data_unavailable",
        "rna_tumor_elevation_breadth_class": "broadly_tumor_elevated",
        "rna_tumor_elevation_n_indications_tested": 27,
    }
    d = presence_claim_vector(hl, [])["D"]
    assert d["signal"] == "strong", "rna_only target must read the RNA breadth, not unmeasured"
    # control: BOTH layers a coverage gap → still unmeasured (no real value to fall through to)
    hl_both_gap = {
        **_headline(),
        "tumor_elevation_breadth_class": "data_unavailable",
        "rna_tumor_elevation_breadth_class": "data_unavailable",
    }
    assert presence_claim_vector(hl_both_gap, [])["D"]["signal"] == "unmeasured"


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
    # G3.1 PRESENTATION fields: the encouraging bulk direction is always present; the qualifying
    # single-cell caveat is NULL when concordant (sc CONFIRMS the broad read). source_support is a
    # uniform per-source map. Both facets agree → corroboration high → NOT boundary-sensitive.
    assert claim["positive_signal"]["source"] == "bulk_tumor_presence"
    assert _RAW_EPCAM["bulk_class"] in claim["positive_signal"]["statement"]
    assert claim["qualifying_signal"] is None, "concordant → no qualifying caveat"
    assert claim["boundary_sensitive"] is False  # escape facet corroborates the class
    # uniform source_support: identical key shape on both sources; provenance_refs resolve into it.
    ss = claim["source_support"]
    assert set(ss) == {"bulk_tumor_presence", "single_cell_malignant_coverage"}
    for key, entry in ss.items():
        assert set(entry) == {"card_id", "stance", "summary", "fields"}, f"{key} non-uniform shape"
    assert claim["positive_signal"]["provenance_ref"] in ss
    assert ss["single_cell_malignant_coverage"]["stance"] == "concordant"


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
    # G3.1 PRESENTATION: the alarming class POPULATES the qualifying single-cell caveat (bulk masks a
    # low-coverage escape fraction) while the encouraging bulk direction stays present. Both facets
    # agree (low coverage + high escape) → corroboration high → the class is NOT boundary-sensitive here.
    assert claim["positive_signal"]["source"] == "bulk_tumor_presence"
    assert claim["qualifying_signal"] is not None, "bulk_masks_low_coverage → a qualifying caveat"
    assert claim["qualifying_signal"]["source"] == "single_cell_malignant_coverage"
    assert "escape" in claim["qualifying_signal"]["statement"].lower()
    assert claim["boundary_sensitive"] is False
    assert claim["source_support"]["single_cell_malignant_coverage"]["stance"] == "qualifying"


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
    # DIRECTIONAL presentation: mutating the SINGLE-CELL source (bulk fixed) changes qualifying_signal
    # (null → populated) while positive_signal (sourced from the unchanged bulk read) is byte-identical.
    assert concordant["qualifying_signal"] is None and flipped["qualifying_signal"] is not None
    assert concordant["positive_signal"] == flipped["positive_signal"], "bulk unchanged → positive_signal stable"


def test_coverage_concordance_bulk_mutation_changes_positive_signal():
    # MIRROR of the single-cell mutation: mutating the BULK source (single-cell fixed) changes
    # positive_signal while the concordance class + qualifying_signal (sc-sourced) are unchanged.
    hi = presence_claim_vector(_headline(), _l2b_cards(bulk_class="broadly_high", coverage_class="high"))[
        "bulk_vs_singlecell_coverage_concordance"
    ]
    mod = presence_claim_vector(_headline(), _l2b_cards(bulk_class="broadly_moderate", coverage_class="high"))[
        "bulk_vs_singlecell_coverage_concordance"
    ]
    assert hi["concordance_class"] == mod["concordance_class"] == "coverage_concordant"
    assert hi["positive_signal"] != mod["positive_signal"], "a different bulk class → a different positive_signal"
    assert "broadly_high" in hi["positive_signal"]["statement"]
    assert "broadly_moderate" in mod["positive_signal"]["statement"]
    assert hi["qualifying_signal"] == mod["qualifying_signal"] is None  # sc unchanged (concordant)


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


def test_coverage_concordance_boundary_sensitivity_tracks_corroboration():
    # Part 6.5 near-boundary discipline: the concordance class is fixed by the LONE coverage token; it is
    # boundary-sensitive UNLESS the orthogonal escape facet corroborates it (corroboration high). A
    # near-boundary perturbation of the sole token could flip a class that rests only on it, so it must be
    # surfaced as boundary-sensitive rather than asserted flat. This is a deterministic read of the
    # already-computed corroboration structure — NOT a calibration layer / CI / continuous margin.
    def _claim(cov, esc):
        return presence_claim_vector(_headline(), _l2b_cards(coverage_class=cov, escape_class=esc))[
            "bulk_vs_singlecell_coverage_concordance"
        ]

    corroborated = _claim("high", "escape_risk_low")  # both facets agree → high
    assert corroborated["corroboration"] == "high" and corroborated["boundary_sensitive"] is False
    lone = _claim("high", None)  # escape off-scale → single_arm → class rests on ONE token
    assert lone["corroboration"] == "single_arm" and lone["boundary_sensitive"] is True
    conflicted = _claim("high", "escape_risk_high")  # escape CONTRADICTS coverage → low
    assert conflicted["corroboration"] == "low" and conflicted["boundary_sensitive"] is True
    # The alarming class, when it rests on a lone token, must ALSO carry the boundary flag (never flat).
    alarming_lone = _claim("low", None)
    assert alarming_lone["concordance_class"] == "bulk_masks_low_coverage"
    assert alarming_lone["boundary_sensitive"] is True
    assert "near-boundary" in alarming_lone["boundary_note"]


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


# ── L2b-4: RNA × MS-protein abundance-MAGNITUDE concordance (SK#1589) ─────────────────────────────
# The FOURTH cross-source integrated claim (grows the epic's M3 vocabulary-reuse 3→4). Integrates an
# independent RNA-abundance read with an independent MASS-SPEC protein-abundance read, comparing each
# source's WITHIN-POPULATION rank CLASS (allgene_percentile_class) mapped to a 3-level magnitude — NEVER
# raw TMT-vs-TPM percentiles (#1512). Grain-anchored (tumor-RNA×CPTAC preferred, cell-line RNA×Gygi/
# ProCan fallback + cross-grain corroborating arm). Store the RAW percentile classes and RE-DERIVE the
# claim in-test — a derived fixture cannot fail; the rank classes are the irreproducible inputs.

# Both grains agree the target ranks HIGH on RNA and HIGH on MS-protein → abundance_concordant, and the
# cell-line grain corroborates the tumor grain (corroboration high).
_RAW_ABUND_CONCORDANT = {
    "tumor_rna": "top_decile",  # → high
    "tumor_protein": "top_decile",  # → high
    "cl_rna": "top_1pct",  # → high
    "cl_gygi": "top_decile",  # → high
    "cl_procan": "top_decile",  # → high
}
# Tumor grain only: RNA ranks HIGH but MS-protein only MID → rna_high_protein_low (a post-transcriptional
# attenuation / low-proxy-quality direction, NOT nullification — the split direction is the datum).
_RAW_ABUND_RNA_HIGH_PROTEIN_LOW = {
    "tumor_rna": "top_decile",  # → high
    "tumor_protein": "mid",  # → moderate
}


def _abund_cards(tumor_rna=None, tumor_protein=None, cl_rna=None, cl_gygi=None, cl_procan=None):
    """Minimal card set carrying `allgene_percentile_class` on the five abundance sources the L2b-4 claim
    integrates. A None arg OMITS that card entirely (source-absence / supply-defeat paths). These cards
    do NOT carry the A/B/C/D-load-bearing fields, so the four claims stay atom-less and byte-stable across
    every abundance permutation — any A/B/C/D delta in the inert test would then be MY perturbation."""
    cards = []

    def _card(cid, cls):
        if cls is not None:
            cards.append({"card_id": cid, "summary": {"allgene_percentile_class": cls}})

    _card("tumor-rna-distribution", tumor_rna)
    _card("tumor-protein-abundance-cptac", tumor_protein)
    _card("cellline-rna-distribution", cl_rna)
    _card("cellline-protein-abundance", cl_gygi)
    _card("cellline-protein-abundance-procan", cl_procan)
    return cards


def test_abundance_concordance_concordant():
    # RNA high AGREES with MS-protein high in the tumor grain → abundance_concordant, corroborated by the
    # independent cell-line grain (also concordant) → corroboration high. Re-derive from raw rank classes.
    vec = presence_claim_vector(_headline(), _abund_cards(**_RAW_ABUND_CONCORDANT))
    claim = vec["abundance_concordance"]
    assert claim["concordance_class"] == "abundance_concordant"
    assert claim["corroboration"] == "high"  # tumor arm + agreeing cell-line grain = 2 measured arms
    assert claim["integration_method"] == "explicit_deterministic"  # NO llm_inference: reproducible by contract
    assert claim["grain"] == "tumor"  # tumor grain preferred over cell-line
    assert claim["rna_magnitude"] == "high" and claim["protein_magnitude"] == "high"
    # Provenance records BOTH modalities in BOTH grains, each recoverable to its raw rank class + level.
    srcs = {(s["grain"], s["property"]): s for s in claim["provenance"]["sources"]}
    assert srcs[("tumor", "rna_abundance_magnitude")]["card_id"] == "tumor-rna-distribution"
    assert srcs[("tumor", "rna_abundance_magnitude")]["fields"]["allgene_percentile_class"] == "top_decile"
    assert srcs[("tumor", "ms_protein_abundance_magnitude")]["card_id"] == "tumor-protein-abundance-cptac"
    assert srcs[("tumor", "rna_abundance_magnitude")]["role"] == "primary"
    assert srcs[("cell_line", "ms_protein_abundance_magnitude")]["role"] == "corroborating"
    # Compared on within-population RANK, independent assays — the #1512 non-comparability discipline.
    note = claim["provenance"]["independence_note"].lower()
    assert "independent" in note and "rank" in note


def test_abundance_concordance_rna_high_protein_low_directional():
    # RNA ranks HIGH but MS-protein only MID (tumor grain, no cell-line read) → rna_high_protein_low: a
    # directional split neither assay states alone. Single grain → no corroborating arm → single_arm.
    hi_lo = presence_claim_vector(_headline(), _abund_cards(**_RAW_ABUND_RNA_HIGH_PROTEIN_LOW))["abundance_concordance"]
    assert hi_lo["concordance_class"] == "rna_high_protein_low"
    assert hi_lo["corroboration"] == "single_arm"  # only the tumor grain resolved
    # The MIRROR direction: RNA mid, protein high → rna_low_protein_high (protein exceeds transcript rank).
    lo_hi = presence_claim_vector(_headline(), _abund_cards(tumor_rna="mid", tumor_protein="top_decile"))[
        "abundance_concordance"
    ]
    assert lo_hi["concordance_class"] == "rna_low_protein_high"


def test_abundance_concordance_is_verdict_inert():
    # Verdict-INERT even WITH the #1594 presentation-support fields: the claim now CARRIES
    # positive_signal / qualifying_signal / source_support / boundary_sensitive (SK#1594 surface), but it
    # must still carry NO `signal` key, and surfacing it must not perturb A/B/C/D / homogeneity /
    # _disclaimer. The presentation fields route NOTHING.
    base = presence_claim_vector(_headline(), _abund_cards(tumor_rna="top_decile"))  # RNA only → claim omitted
    withclaim = presence_claim_vector(_headline(), _abund_cards(tumor_rna="top_decile", tumor_protein="top_decile"))
    assert "abundance_concordance" not in base
    claim = withclaim["abundance_concordance"]
    assert "signal" not in claim, "an L2b claim must never carry a signal tier"
    for pres in ("positive_signal", "qualifying_signal", "source_support", "boundary_sensitive", "boundary_note"):
        assert pres in claim, f"{pres} is a #1594 presentation-support field the surface must carry"
    for ax in ("A", "B", "C", "D", "homogeneity", "_disclaimer"):
        assert withclaim[ax] == base[ax], f"surfacing the abundance-concordance claim perturbed {ax}"


def test_abundance_concordance_presentation_fields_concordant_direction():
    # #1594 surface: when the primary grain is abundance_concordant, positive_signal is present and names
    # the cross-modality AGREEMENT; qualifying_signal is NULL (no directional split to caveat); the uniform
    # source_support map carries BOTH modalities with the identical key shape, each stance `concordant`.
    claim = presence_claim_vector(_headline(), _abund_cards(**_RAW_ABUND_CONCORDANT))["abundance_concordance"]
    assert claim["concordance_class"] == "abundance_concordant"
    assert claim["qualifying_signal"] is None, "concordant → no directional-split caveat"
    pos = claim["positive_signal"]
    assert pos["source"] == "rna_abundance" and pos["provenance_ref"] == "rna_abundance"
    assert "agree" in pos["statement"].lower()
    ss = claim["source_support"]
    assert set(ss) == {"rna_abundance", "ms_protein_abundance"}
    # identical key shape per source (read structurally, not by prose)
    assert set(ss["rna_abundance"]) == set(ss["ms_protein_abundance"])
    assert ss["rna_abundance"]["stance"] == "concordant" and ss["ms_protein_abundance"]["stance"] == "concordant"
    assert ss["rna_abundance"]["fields"]["magnitude_level"] == "high"
    assert claim["boundary_sensitive"] is False, "two agreeing grains → corroboration high → not boundary"


def test_abundance_concordance_presentation_fields_directional_split():
    # #1594 surface: rna_high_protein_low populates qualifying_signal (post-transcriptional attenuation /
    # low proxy-quality), sourced from the protein modality; the mirror direction reverses the stances.
    hi_lo = presence_claim_vector(_headline(), _abund_cards(**_RAW_ABUND_RNA_HIGH_PROTEIN_LOW))["abundance_concordance"]
    assert hi_lo["concordance_class"] == "rna_high_protein_low"
    qual = hi_lo["qualifying_signal"]
    assert qual is not None and qual["source"] == "ms_protein_abundance"
    assert "post-transcriptional" in qual["statement"].lower() or "below" in qual["statement"].lower()
    ss = hi_lo["source_support"]
    assert ss["rna_abundance"]["stance"] == "higher_rank" and ss["ms_protein_abundance"]["stance"] == "lower_rank"
    # single grain (no cross-grain corroboration) → boundary-sensitive
    assert hi_lo["corroboration"] == "single_arm" and hi_lo["boundary_sensitive"] is True
    lo_hi = presence_claim_vector(_headline(), _abund_cards(tumor_rna="mid", tumor_protein="top_decile"))[
        "abundance_concordance"
    ]
    assert lo_hi["concordance_class"] == "rna_low_protein_high"
    assert lo_hi["qualifying_signal"]["source"] == "ms_protein_abundance"
    assert lo_hi["source_support"]["rna_abundance"]["stance"] == "lower_rank"
    assert lo_hi["source_support"]["ms_protein_abundance"]["stance"] == "higher_rank"


def test_abundance_concordance_boundary_sensitive_tracks_corroboration():
    # Deterministic: boundary_sensitive is exactly `corroboration != "high"` — corroborated (two agreeing
    # grains) → False; single grain → True. NOT a new threshold/calibration, just a read of corroboration.
    full = presence_claim_vector(_headline(), _abund_cards(**_RAW_ABUND_CONCORDANT))["abundance_concordance"]
    assert full["corroboration"] == "high" and full["boundary_sensitive"] is False
    single = presence_claim_vector(_headline(), _abund_cards(tumor_rna="top_decile", tumor_protein="top_decile"))[
        "abundance_concordance"
    ]
    assert single["corroboration"] == "single_arm" and single["boundary_sensitive"] is True


def test_abundance_concordance_defeat_every_protein_platform_omits_key():
    # M3 all-supply ERASE: to remove the claim you must defeat EVERY protein platform across BOTH grains
    # (CPTAC + Gygi + ProCan). RNA alone in either grain is <2 modalities → single_modality_only → key
    # OMITTED (byte-stable), matching the A/B/C/D + coverage-concordance atom discipline.
    assert "abundance_concordance" in presence_claim_vector(_headline(), _abund_cards(**_RAW_ABUND_CONCORDANT))
    no_protein = presence_claim_vector(
        _headline(),
        _abund_cards(tumor_rna="top_decile", cl_rna="top_1pct"),  # both RNA reads, zero protein
    )
    assert "abundance_concordance" not in no_protein


def test_abundance_concordance_single_platform_defeat_only_degrades():
    # M3-vs-M4 fidelity: knocking out ONE protein platform must NOT erase the claim — the concept survives
    # on a surviving grain/platform — it only DEGRADES corroboration.
    full = presence_claim_vector(_headline(), _abund_cards(**_RAW_ABUND_CONCORDANT))["abundance_concordance"]
    assert full["corroboration"] == "high"
    # (a) knock out CPTAC only → tumor grain fails, primary FALLS BACK to the cell-line grain; class
    #     survives but there is no second grain to corroborate → single_arm.
    no_cptac = presence_claim_vector(_headline(), _abund_cards(**{**_RAW_ABUND_CONCORDANT, "tumor_protein": None}))[
        "abundance_concordance"
    ]
    assert no_cptac["concordance_class"] == "abundance_concordant", "surviving grain keeps the class"
    assert no_cptac["grain"] == "cell_line"
    assert no_cptac["corroboration"] == "single_arm", "one grain lost → corroboration degrades, not erased"
    # (b) knock out Gygi only → the cell-line grain FALLS THROUGH to ProCan within the grain; both grains
    #     still resolve → corroboration stays high (within-grain platform fallback, never cross-grain).
    no_gygi = presence_claim_vector(_headline(), _abund_cards(**{**_RAW_ABUND_CONCORDANT, "cl_gygi": None}))[
        "abundance_concordance"
    ]
    assert no_gygi["corroboration"] == "high", "cell-line grain survives on ProCan → still corroborated"
    cl_protein_cards = {
        s["card_id"] for s in no_gygi["provenance"]["sources"] if s["property"] == "ms_protein_abundance_magnitude"
    }
    assert "cellline-protein-abundance-procan" in cl_protein_cards, "fell through to ProCan within the grain"


def test_abundance_concordance_omitted_when_a_modality_absent_or_indecisive():
    # Byte-stability: the KEY is omitted (not None) unless at least one grain resolves BOTH modalities.
    # (a) protein present but RNA absent in every grain → no grain resolves → no claim
    assert "abundance_concordance" not in presence_claim_vector(
        _headline(), _abund_cards(tumor_protein="top_decile", cl_gygi="top_decile")
    )
    # (b) an indecisive percentile class (not in the magnitude map) does not resolve a modality
    assert "abundance_concordance" not in presence_claim_vector(
        _headline(), _abund_cards(tumor_rna="unmapped_class", tumor_protein="top_decile")
    )
    # (c) no cards at all → no claim
    assert "abundance_concordance" not in presence_claim_vector(_headline(), [])


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


def test_by_subtype_non_measured_stratum_carries_no_ab_signal():
    """SK#1518. The strata dict used to include EVERY stratum with a stratum_id and compute an A/B
    `signal` from its median/fraction even when the stratum never cleared the power floor
    (evidence_state != "measured"), knocking only `corroboration` to low — so a consumer reading
    `signal` alone over-read a hypothesis-grade stratum as a per-stratum differential. Gate the signal
    on the stratum's own evidence_state (matching subgroup_derivation.py and run.py's non-null-signal
    join). The MEASURED enriched stratum keeps its signal; the NON-measured one reads `unmeasured`."""
    cards = [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_axis_quality": "exploratory",
                "subtype_stratification_class": "subtype_enriched",
                "n_subtypes_measured": 1,
                "per_subgroup_metrics": [
                    {
                        "stratum_id": "MSI_H",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_enriched",
                        "median_log2tpm": 3.2,
                        "n_tumor_samples": 41,
                        "fraction_tumor_above_normal_p95": 0.5,
                    },
                    {
                        # a median survives on a non-measured stratum, but it never cleared the floor —
                        # it must NOT mint a per-stratum differential signal.
                        "stratum_id": "CMS1",
                        "evidence_state": "exploratory",
                        "subtype_signal": None,
                        "median_log2tpm": 2.9,
                        "n_tumor_samples": 12,
                        "fraction_tumor_above_normal_p95": 0.4,
                    },
                ],
            },
        }
    ]
    cv = presence_claim_vector_by_subtype(cards)
    measured = cv["strata"]["MSI_H"]
    unmeasured = cv["strata"]["CMS1"]
    assert measured["A"]["signal"] != "unmeasured", "a MEASURED stratum keeps its abundance signal"
    assert unmeasured["A"]["signal"] == "unmeasured", "a non-measured stratum must not carry an A signal"
    assert unmeasured["B"]["signal"] == "unmeasured", "a non-measured stratum must not carry a B signal"
    assert unmeasured["evidence_state"] == "exploratory"
    # the NAMED enriched pick still surfaces the one MEASURED enriched identity (left unchanged).
    assert cv["top_enriched_subtype"] == "MSI_H"


def test_by_subtype_measured_but_below_n_floor_stratum_carries_no_ab_signal():
    """#1625. The per-stratum A/B signal gate must require BOTH conjuncts its comment claims parity
    with (subgroup_derivation.py:388 `powered = evidence_state == "measured" and n >= _SUBGROUP_N_FLOOR`):
    a stratum can be evidence_state == "measured" AND still fall below the n>=30 power floor, and such a
    stratum must null the A/B signal to "unmeasured" — not merely dim corroboration to "low". 0/2004
    measured strata carry n<30 in the corpus (latent defense-in-depth), so this MUTATION synthesizes the
    below-floor stratum: we store the RAW stratum input (median, fraction, n) and RE-DERIVE the signal
    through the production function, since a fixture of derived signals could never fail. The floor is
    single-sourced from subgroup_derivation so this test tracks the real threshold, not a literal copy."""
    below_floor_n = _SUBGROUP_N_FLOOR - 1  # 29: measured, but under the power floor
    assert below_floor_n < _SUBGROUP_N_FLOOR
    cards = [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_axis_quality": "exploratory",
                "subtype_stratification_class": "subtype_enriched",
                "n_subtypes_measured": 2,
                "per_subgroup_metrics": [
                    {
                        # MEASURED and above the floor — keeps its signal (control).
                        "stratum_id": "MSI_H",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_enriched",
                        "median_log2tpm": 3.2,
                        "n_tumor_samples": 47,
                        "fraction_tumor_above_normal_p95": 0.5,
                    },
                    {
                        # MEASURED but BELOW the n floor — a real median/fraction survives, but it never
                        # cleared the power floor, so both A and B must null to "unmeasured".
                        "stratum_id": "CMS1",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_enriched",
                        "median_log2tpm": 2.9,
                        "n_tumor_samples": below_floor_n,
                        "fraction_tumor_above_normal_p95": 0.4,
                    },
                ],
            },
        }
    ]
    cv = presence_claim_vector_by_subtype(cards)
    powered = cv["strata"]["MSI_H"]
    below = cv["strata"]["CMS1"]
    assert powered["A"]["signal"] != "unmeasured", "a measured, floor-met stratum keeps its abundance signal"
    assert below["A"]["signal"] == "unmeasured", "measured but n<floor must null the A signal"
    assert below["B"]["signal"] == "unmeasured", "measured but n<floor must null the B signal"
    assert below["evidence_state"] == "measured", "evidence_state is unchanged — only the signal is gated"


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


# ── L2b subtype_restriction_concordance (SK#1830) — cross-source SUBTYPE-RESTRICTION ────────────────
from _skills_common.claim_vector_core import cards_by_id as _by_id_for_test  # noqa: E402
from _skills_common.presence_claims import (  # noqa: E402
    _subtype_restriction_concordance_claim,
)


def _minimal_rna_row():
    # a MEASURED, floor-met stratum so presence_claim_vector_by_subtype builds a real strata dict.
    return {
        "stratum_id": "A",
        "evidence_state": "measured",
        "subtype_signal": "subtype_uniform",
        "median_log2tpm": 1.0,
        "n_tumor_samples": 50,
        "fraction_tumor_above_normal_p95": 0.1,
    }


def _sr_cards(
    rna_q="powered",
    rna_cls="subtype_restricted",
    prot_q=None,
    prot_cls=None,
    cl_q=None,
    cl_cls=None,
    rna_var=0.34,
):
    """Build the three by-subtype cards exercising the subtype_restriction_concordance builder's arms.
    Any arm with axis_quality=None is an absent/unresolved arm (its card summary carries no grade)."""
    cards = [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_axis_quality": rna_q,
                "subtype_stratification_class": rna_cls,
                "subtype_variance_explained": rna_var,
                "subtype_effect_size_class": "large",
                "n_subtypes_measured": 4,
                "n_subtypes_enriched": 2,
                "n_subtypes_restricted": 1,
                "per_subgroup_metrics": [_minimal_rna_row()],
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
        {
            "card_id": "cellline-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_axis_quality": cl_q,
                "subtype_stratification_class": cl_cls,
                "n_subtypes_measured": 2,
                "n_subtypes_enriched": 0,
            },
        },
    ]
    return cards


def _sr(**kw):
    return _subtype_restriction_concordance_claim(_by_id_for_test(_sr_cards(**kw)))


def test_subtype_restriction_concordance_both_arms_agree_restricted():
    c = _sr(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="subtype_enriched")
    assert c["concordance_class"] == "subtype_restriction_concordant"
    assert c["corroboration"] == "high"
    assert c["integration_method"] == "explicit_deterministic"
    assert c["concordance_support"]["agreed_direction"] == "subtype_restricted"
    assert c["corroborating_independent_arm_count"] == 2
    assert c["resolved_source_count"] == 2  # tumor RNA + protein (no cell line)
    assert c["boundary_sensitive"] is False
    assert c["qualifying_signal"] is None


def test_subtype_restriction_concordance_both_arms_agree_no_restriction():
    # both powered but pan_subtype_uniform → both agree NO restriction.
    c = _sr(rna_q="powered", rna_cls="pan_subtype_uniform", prot_q="powered", prot_cls="pan_subtype_uniform")
    assert c["concordance_class"] == "subtype_restriction_concordant"
    assert c["concordance_support"]["agreed_direction"] == "no_subtype_restriction"
    assert c["corroboration"] == "high"


def test_subtype_restriction_concordance_protein_masks_rna_only_restriction():
    # RNA sees a restriction, protein powered but uniform → the RNA-only false positive.
    c = _sr(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="pan_subtype_uniform")
    assert c["concordance_class"] == "protein_masks_subtype_restriction"
    assert c["corroboration"] == "low"
    assert c["concordance_support"] == {"restriction_in": "rna", "no_restriction_in": "protein"}
    assert c["boundary_sensitive"] is True
    assert c["qualifying_signal"]["source"] == "protein"


def test_subtype_restriction_concordance_rna_masks_protein_restriction():
    c = _sr(rna_q="powered", rna_cls="pan_subtype_uniform", prot_q="powered", prot_cls="subtype_restricted")
    assert c["concordance_class"] == "rna_masks_subtype_restriction"
    assert c["concordance_support"] == {"restriction_in": "protein", "no_restriction_in": "rna"}
    assert c["corroboration"] == "low"


def test_subtype_restriction_concordance_single_source_only_rna():
    # protein axis not powered (exploratory) → unresolved; only the RNA arm resolves.
    c = _sr(rna_q="powered", rna_cls="subtype_restricted", prot_q="exploratory", prot_cls="subtype_restricted")
    assert c["concordance_class"] == "single_source_only"
    assert c["corroboration"] == "single_arm"
    assert c["concordance_support"]["resolved_by"] == "rna"
    assert c["concordance_support"]["resolved_via_source"] == "tumor_rna"
    assert c["corroborating_independent_arm_count"] == 1
    assert c["resolved_source_count"] == 1


def test_subtype_restriction_concordance_single_source_only_protein():
    # RNA axis not powered → unresolved; only the protein arm resolves.
    c = _sr(rna_q="underpowered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="subtype_restricted")
    assert c["concordance_class"] == "single_source_only"
    assert c["concordance_support"]["resolved_by"] == "protein"
    assert c["concordance_support"]["resolved_via_source"] == "cptac_protein"


def test_subtype_restriction_concordance_cellline_supplies_rna_arm_but_never_a_third_arm():
    # tumor-RNA axis unpowered, cell-line RNA powered → the RNA arm resolves VIA the cell-line sibling,
    # but it is still ONE RNA arm — never an independent third arm.
    c = _sr(
        rna_q="underpowered",
        rna_cls="subtype_restricted",
        prot_q="powered",
        prot_cls="subtype_restricted",
        cl_q="powered",
        cl_cls="subtype_restricted",
    )
    assert c["concordance_class"] == "subtype_restriction_concordant"
    assert c["corroborating_independent_arm_count"] == 2  # RNA layer (via cell line) + protein — NOT 3
    assert c["resolved_source_count"] == 2  # cell-line RNA + protein (tumor RNA unresolved)
    by = {s["source"]: s for s in c["source_support"]}
    assert by["cellline_rna"]["corroboration_eligible"] is False
    assert by["cellline_rna"]["dependence_group"] == "rna"
    # both independent arms resolve → concordant (NOT single_source_only), so the concordance_support
    # carries the agreed direction, not a which-arm split.
    assert c["concordance_support"] == {"agreed_direction": "subtype_restricted"}
    # the tumor-RNA arm shows resolved:False (supplied by the cell-line sibling instead).
    assert by["tumor_rna"]["resolved"] is False


def test_subtype_restriction_concordance_all_supply_paths_mutation():
    # full concordant read.
    full = _sr(
        rna_q="powered",
        rna_cls="subtype_restricted",
        prot_q="powered",
        prot_cls="subtype_restricted",
        cl_q="powered",
        cl_cls="subtype_restricted",
    )
    assert full["concordance_class"] == "subtype_restriction_concordant"
    # defeat the tumor-RNA axis only — cell-line still supplies the RNA arm → NOT degraded.
    no_tumor = _sr(
        rna_q="underpowered",
        rna_cls="subtype_restricted",
        prot_q="powered",
        prot_cls="subtype_restricted",
        cl_q="powered",
        cl_cls="subtype_restricted",
    )
    assert no_tumor["corroborating_independent_arm_count"] == 2
    # defeat BOTH RNA sources — only the protein arm survives → degrade to single_source_only.
    no_rna = _sr(
        rna_q="underpowered",
        rna_cls="subtype_restricted",
        prot_q="powered",
        prot_cls="subtype_restricted",
        cl_q="underpowered",
        cl_cls="subtype_restricted",
    )
    assert no_rna["concordance_class"] == "single_source_only"
    # defeat the protein arm too — EVERY independent supply path defeated → key omitted (byte-stable).
    none = _sr(
        rna_q="underpowered",
        rna_cls="subtype_restricted",
        prot_q="underpowered",
        prot_cls="subtype_restricted",
        cl_q="underpowered",
        cl_cls="subtype_restricted",
    )
    assert none is None


def test_subtype_restriction_concordance_key_omitted_when_neither_independent_arm_resolves():
    cv = presence_claim_vector_by_subtype(
        _sr_cards(rna_q="exploratory", rna_cls="subtype_restricted", prot_q=None, cl_q=None)
    )
    assert "subtype_restriction_concordance" not in cv  # byte-stable omission


def test_subtype_restriction_concordance_grain_is_first_class_and_differs_across_independent_arms():
    c = _sr(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="subtype_restricted")
    by = {s["source"]: s for s in c["source_support"]}
    assert by["tumor_rna"]["grain"] == "bulk_rna_transcript (patient tumor)"
    assert by["cptac_protein"]["grain"] == "ms_protein (patient tumor)"  # arms DIFFER in assay-modality


def test_subtype_restriction_concordance_retained_quantitative_recoverable():
    c = _sr(
        rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="subtype_restricted", rna_var=0.42
    )
    by = {s["source"]: s for s in c["source_support"]}
    assert by["tumor_rna"]["retained_quantitative"]["subtype_variance_explained"] == 0.42
    assert by["tumor_rna"]["retained_quantitative"]["n_subtypes_restricted"] == 1


def test_subtype_restriction_concordance_non_finite_quant_demoted_to_none():
    # a NaN variance-explained must NOT leak into claim_vectors (emission-invariants non-finite rule).
    c = _sr(
        rna_q="powered",
        rna_cls="subtype_restricted",
        prot_q="powered",
        prot_cls="subtype_restricted",
        rna_var=float("nan"),
    )
    by = {s["source"]: s for s in c["source_support"]}
    assert by["tumor_rna"]["retained_quantitative"]["subtype_variance_explained"] is None


def _sr_signal_shape_ok(sig):
    return isinstance(sig, dict) and set(sig) == {"statement", "source", "provenance_ref"}


def test_subtype_restriction_concordance_presentation_signal_shape():
    conc = _sr(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="subtype_restricted")
    assert _sr_signal_shape_ok(conc["positive_signal"])
    assert conc["qualifying_signal"] is None
    masks = _sr(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="pan_subtype_uniform")
    assert _sr_signal_shape_ok(masks["positive_signal"]) and _sr_signal_shape_ok(masks["qualifying_signal"])


def test_subtype_restriction_concordance_is_verdict_inert_and_purely_additive():
    # NO `signal` key, and PURELY ADDITIVE: every pre-existing by-subtype vector key is byte-identical;
    # subtype_restriction_concordance is the ONLY delta.
    cards = _sr_cards(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="subtype_restricted")
    cv = presence_claim_vector_by_subtype(cards)
    claim = cv["subtype_restriction_concordance"]
    assert "signal" not in claim
    assert "verdict-INERT" in claim["_disclaimer"]
    # rebuild WITHOUT any resolving arm (unpowered everything) → the claim is omitted and every other
    # key of the by-subtype vector is byte-identical to the with-claim vector.
    bare = presence_claim_vector_by_subtype(
        _sr_cards(rna_q="powered", rna_cls="subtype_restricted", prot_q="exploratory", cl_q="exploratory")
    )
    # single_source_only here (RNA powered) → still present; strip it to compare the spine.
    common = {k: v for k, v in cv.items() if k != "subtype_restriction_concordance"}
    common_bare = {k: v for k, v in bare.items() if k != "subtype_restriction_concordance"}
    assert common == common_bare  # the rest of the by-subtype vector is untouched by the claim
