"""Unit test for the presence claim-vector citable atoms (skills/_skills_common/presence_claims.py).
Presence builds its claims MANUALLY (not via ClaimSpec.atom_fn), so this pins that each measured claim
binds its load-bearing card values to {card_id, fields} + entity, and that the key is OMITTED (not
None) when the source card is absent — matching the other axes' atom discipline. Pure; no S3."""

from __future__ import annotations

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


# ── SK#1869: the lineage-dilution QUALIFIER defuses the prototype M2 "context-blind" trap ─────────
# The M2 trap: a lossy reader that sees `heterogeneity=high / prevalence=subset` from the pan-lineage
# CELL-LINE panel in isolation fabricates a within-tumour antigen-negative-ESCAPE concern. The qualifier
# binds the heterogeneity read + the lineage census into the "cross-lineage identity, NOT within-tumour"
# caveat so the misleading fields can never be surfaced bare. Store the RAW cell-line fields and re-derive
# the qualifier in-test (a derived fixture cannot fail; the raw distribution/census is the input).
_M2_TRAP_CELLLINE = {
    # EPCAM-shaped: a bimodal, high-dispersion pan-lineage panel — the exact shape that looks like
    # within-tumour antigen escape to a reader blind to the lineage confound.
    "distribution_pattern": "bimodal",
    "coefficient_of_variation": 1.646,
    "n_lineage_restricted_lineages": 0,
    "n_lineages_evaluated": 28,
    "expression_class": "broadly_moderate",
}


def _cards_with_m2_trap_cellline(summary=_M2_TRAP_CELLLINE):
    cards = _cards()
    cards.append({"card_id": "cellline-rna-distribution", "summary": dict(summary)})
    return cards


def test_lineage_dilution_qualifier_defuses_m2_trap():
    vec = presence_claim_vector(_headline(), _cards_with_m2_trap_cellline())
    assert "cellline_heterogeneity_lineage_qualifier" in vec, (
        "the M2 trap shape (bimodal pan-lineage cell-line panel) must emit the lineage-dilution qualifier"
    )
    q = vec["cellline_heterogeneity_lineage_qualifier"]
    # Verdict-INERT: no signal/corroboration → never a chip, never a tier, never averaged.
    assert "signal" not in q and "corroboration" not in q
    # It BINDS both load-bearing facets — the misleading heterogeneity read AND the lineage context that
    # explains it — so the caveat is recoverable, not merely prose.
    bf = q["bound_fields"]
    assert bf["heterogeneity"] == "high"  # re-derived from the raw bimodal / high-CoV shape
    assert bf["lineage_restriction"] == "diffuse"  # re-derived from the raw lineage census (nlr=0/28)
    assert bf["n_lineages_evaluated"] == 28
    # It NAMES the concrete fabrication it guards against and points at the source that DOES answer the
    # within-tumour escape question — so a downstream reader cannot re-derive the M2 fabrication.
    assert q["guards_misread"] == "within_tumour_antigen_negative_escape"
    assert q["escape_read_source"] == "bulk_vs_singlecell_coverage_concordance"
    assert "LINEAGE IDENTITY" in q["caveat"]
    assert "within-tumour" in q["caveat"]


def test_lineage_dilution_qualifier_is_verdict_inert():
    # Surfacing the qualifier must not perturb the four claims, homogeneity, or the disclaimer.
    base = presence_claim_vector(_headline(), _cards())
    withq = presence_claim_vector(_headline(), _cards_with_m2_trap_cellline())
    for ax in ("A", "B", "C", "D", "homogeneity", "_disclaimer"):
        assert withq[ax] == base[ax], f"surfacing the lineage-dilution qualifier perturbed {ax}"


def test_lineage_dilution_qualifier_omitted_on_a_uniform_panel():
    # MUTATION (fire direction): defeat the misleading read — a uniform, low-dispersion panel has NO trap
    # to defuse → the KEY is omitted (byte-stable), so the qualifier tracks the real heterogeneity signal
    # rather than being always-on.
    uniform = dict(_M2_TRAP_CELLLINE, distribution_pattern="unimodal", coefficient_of_variation=0.2)
    vec = presence_claim_vector(_headline(), _cards_with_m2_trap_cellline(uniform))
    assert "cellline_heterogeneity_lineage_qualifier" not in vec


def test_lineage_dilution_qualifier_binds_the_live_census_not_a_constant():
    # MUTATION (bind direction): move the lineage census so a MAJORITY of lineages are restricted-drivers
    # → the bound lineage_restriction must FOLLOW to `intermediate` (not a hardcoded label), proving the
    # qualifier binds the live census. The heterogeneity trigger (bimodal) is unchanged, so it still fires.
    restricted = dict(_M2_TRAP_CELLLINE, n_lineage_restricted_lineages=20, n_lineages_evaluated=28)
    vec = presence_claim_vector(_headline(), _cards_with_m2_trap_cellline(restricted))
    q = vec["cellline_heterogeneity_lineage_qualifier"]
    assert q["bound_fields"]["lineage_restriction"] == "intermediate"


def test_lineage_dilution_qualifier_omitted_when_cellline_card_absent():
    # No cellline-rna-distribution card at all → the KEY is omitted (byte-stable), matching the atom
    # discipline. This is the path the committed replay fixtures without a cell-line panel take.
    vec = presence_claim_vector(_headline(), _cards())
    assert "cellline_heterogeneity_lineage_qualifier" not in vec


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


# ── SK#1866: each L2b concordance object carries TYPED dependence edges backing its stance strings ──
from _skills_common.dependence_edges import DEPENDENCE_RELATIONS  # noqa: E402


def _only_edge(claim):
    edges = claim["dependence_edges"]
    assert isinstance(edges, list) and len(edges) == 1, edges
    e = edges[0]
    # a typed edge is a from_source→to_source link carrying a relation from the CLOSED vocabulary.
    assert e["relation"] in DEPENDENCE_RELATIONS
    assert set(e) <= {"from_source", "to_source", "relation", "basis"}
    assert {"from_source", "to_source", "relation"} <= set(e)
    return e


def test_coverage_concordance_carries_typed_edge_corroborates_when_concordant():
    claim = presence_claim_vector(_headline(), _l2b_cards(**_RAW_EPCAM))["bulk_vs_singlecell_coverage_concordance"]
    e = _only_edge(claim)
    # single-cell malignant-coverage source CORROBORATES the anchoring bulk-presence source; the typed
    # edge backs the source_support `concordant` stance without re-encoding it as a string.
    assert e == {
        "from_source": "single_cell_malignant_coverage",
        "to_source": "bulk_tumor_presence",
        "relation": "corroborates",
        "basis": "coverage_concordant",
    }
    assert claim["source_support"]["single_cell_malignant_coverage"]["stance"] == "concordant"


def test_coverage_concordance_carries_typed_edge_qualifies_when_bulk_masks():
    claim = presence_claim_vector(_headline(), _l2b_cards(**_RAW_TACSTD2))["bulk_vs_singlecell_coverage_concordance"]
    e = _only_edge(claim)
    # bulk_masks_low_coverage → the single-cell coverage read QUALIFIES the broad bulk read (a caveat on
    # a dimension the population-averaged bulk read is blind to), NOT a present/absent contradiction.
    assert e["relation"] == "qualifies"
    assert e["from_source"] == "single_cell_malignant_coverage" and e["to_source"] == "bulk_tumor_presence"
    assert e["basis"] == "bulk_masks_low_coverage"
    # the typed edge is the first-class backing of the bespoke `qualifying` stance string.
    assert claim["source_support"]["single_cell_malignant_coverage"]["stance"] == "qualifying"


def test_abundance_concordance_carries_typed_edge_over_the_two_modalities():
    conc = presence_claim_vector(_headline(), _abund_cards(**_RAW_ABUND_CONCORDANT))["abundance_concordance"]
    e = _only_edge(conc)
    assert e == {
        "from_source": "ms_protein_abundance",
        "to_source": "rna_abundance",
        "relation": "corroborates",
        "basis": "abundance_concordant",
    }
    # a directional rank split QUALIFIES (tempers) the RNA-implied abundance — never a negation.
    split = presence_claim_vector(_headline(), _abund_cards(**_RAW_ABUND_RNA_HIGH_PROTEIN_LOW))["abundance_concordance"]
    es = _only_edge(split)
    assert es["relation"] == "qualifies" and es["basis"] == "rna_high_protein_low"
    assert es["from_source"] == "ms_protein_abundance" and es["to_source"] == "rna_abundance"


def test_subtype_restriction_concordance_typed_edges_across_dispositions():
    # both independent arms agree → the protein arm CORROBORATES the RNA arm.
    conc = _sr(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="subtype_enriched")
    e = _only_edge(conc)
    assert e == {
        "from_source": "cptac_protein",
        "to_source": "tumor_rna",
        "relation": "corroborates",
        "basis": "subtype_restriction_concordant",
    }
    # protein masks an RNA-only restriction → protein QUALIFIES the RNA restriction (from protein→rna).
    pmask = _sr(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="pan_subtype_uniform")
    ep = _only_edge(pmask)
    assert ep["relation"] == "qualifies"
    assert ep["from_source"] == "cptac_protein" and ep["to_source"] == "tumor_rna"
    assert ep["basis"] == "protein_masks_subtype_restriction"
    # the MIRROR: RNA masks a protein-only restriction → RNA qualifies the protein restriction (rna→prot).
    rmask = _sr(rna_q="powered", rna_cls="pan_subtype_uniform", prot_q="powered", prot_cls="subtype_restricted")
    er = _only_edge(rmask)
    assert er["relation"] == "qualifies"
    assert er["from_source"] == "tumor_rna" and er["to_source"] == "cptac_protein"
    assert er["basis"] == "rna_masks_subtype_restriction"


def test_subtype_restriction_single_source_only_carries_no_cross_source_edge():
    # only one independent arm resolves → the other is a gap → NO edge between two resolved sources.
    c = _sr(rna_q="powered", rna_cls="subtype_restricted", prot_q="exploratory", prot_cls="subtype_restricted")
    assert c["concordance_class"] == "single_source_only"
    assert c["dependence_edges"] == []


def test_subtype_restriction_edge_endpoint_is_the_resolving_rna_source():
    # tumor-RNA unpowered but cell-line RNA supplies the RNA arm → the edge endpoint is the source that
    # actually resolved the RNA layer (cellline_rna), never a resolved:False node.
    c = _sr(
        rna_q="underpowered",
        rna_cls="subtype_restricted",
        prot_q="powered",
        prot_cls="subtype_restricted",
        cl_q="powered",
        cl_cls="subtype_restricted",
    )
    assert c["concordance_class"] == "subtype_restriction_concordant"
    e = _only_edge(c)
    assert e["to_source"] == "cellline_rna" and e["from_source"] == "cptac_protein"


def test_typed_edges_reference_only_declared_source_nodes():
    # every edge endpoint must resolve to a source node the claim actually declares in source_support.
    cov = presence_claim_vector(_headline(), _l2b_cards(**_RAW_EPCAM))["bulk_vs_singlecell_coverage_concordance"]
    cov_nodes = set(cov["source_support"])
    for edge in cov["dependence_edges"]:
        assert {edge["from_source"], edge["to_source"]} <= cov_nodes
    sr = _sr(rna_q="powered", rna_cls="subtype_restricted", prot_q="powered", prot_cls="subtype_restricted")
    sr_nodes = {s["source"] for s in sr["source_support"]}
    for edge in sr["dependence_edges"]:
        assert {edge["from_source"], edge["to_source"]} <= sr_nodes


# ── L2b protein_presence_concordance (SK#1851) — cross-source PROTEIN PRESENCE ──────────────────────
# ANTIBODY-IHC (HPA per-patient staining) x MASS-SPEC (CPTAC TMT primary + Gygi/ProCan cell-line siblings).
from _skills_common.presence_claims import _protein_presence_concordance_claim  # noqa: E402


def _pp_cards(
    ihc_cls="ihc_detected_high",
    ihc_n_high=12,
    ihc_n_medium=0,
    ihc_n_low=0,
    cptac_cls="mid",
    cptac_frac=None,
    gygi_cls=None,
    gygi_frac=None,
    procan_cls=None,
    procan_frac=None,
):
    """Build the four protein-presence cards exercising the builder's two independent arms. An MS source
    with allgene_percentile_class=None and fraction_detected=None is an absent/unresolved arm; a
    fraction_detected==0 is a MEASURED MS non-detection. ihc_cls=None is an absent antibody arm."""
    return [
        {
            "card_id": "hpa-pathology-cancer-ihc",
            "summary": {
                "protein_presence_class": ihc_cls,
                "fraction_detected": 1.0 if ihc_cls in ("ihc_detected_high", "ihc_detected_moderate") else 0.1,
                "staining_score": 3.0,
                "n_high": ihc_n_high,
                "n_medium": ihc_n_medium,
                "n_low": ihc_n_low,
                "n_not_detected": 0,
                "n_patients_total": max(ihc_n_high + ihc_n_medium + ihc_n_low, 1),
                "hpa_cancer_type": "colorectal cancer",
            },
        },
        {
            "card_id": "tumor-protein-abundance-cptac",
            "summary": {
                "allgene_percentile_class": cptac_cls,
                "allgene_percentile": 58.3,
                "fraction_detected": cptac_frac,
            },
        },
        {
            "card_id": "cellline-protein-abundance",
            "summary": {
                "allgene_percentile_class": gygi_cls,
                "allgene_percentile": 8.6,
                "fraction_detected": gygi_frac,
            },
        },
        {
            "card_id": "cellline-protein-abundance-procan",
            "summary": {
                "allgene_percentile_class": procan_cls,
                "allgene_percentile": 79.7,
                "fraction_detected": procan_frac,
            },
        },
    ]


def _pp(**kw):
    return _protein_presence_concordance_claim(_by_id_for_test(_pp_cards(**kw)))


def test_protein_presence_concordance_both_arms_agree_present():
    c = _pp(ihc_cls="ihc_detected_high", cptac_cls="mid")
    assert c["concordance_class"] == "protein_presence_concordant"
    assert c["corroboration"] == "high"
    assert c["integration_method"] == "explicit_deterministic"
    assert c["concordance_support"]["agreed_direction"] == "protein_detected"
    assert c["corroborating_independent_arm_count"] == 2
    assert c["boundary_sensitive"] is False
    assert c["qualifying_signal"] is None
    assert "signal" not in c


def test_protein_presence_concordance_both_arms_agree_absent():
    # antibody not_detected + MS panel-wide fraction_detected==0 → both agree NO detection.
    c = _pp(ihc_cls="ihc_not_detected", cptac_cls=None, cptac_frac=0)
    assert c["concordance_class"] == "protein_presence_concordant"
    assert c["concordance_support"]["agreed_direction"] == "protein_not_detected"
    assert c["corroboration"] == "high"


def test_protein_presence_concordance_antibody_detects_ms_absent():
    # antibody detects, mass-spec measured non-detection → antibody-only presence.
    c = _pp(ihc_cls="ihc_detected_high", cptac_cls=None, cptac_frac=0)
    assert c["concordance_class"] == "antibody_detects_ms_absent"
    assert c["corroboration"] == "low"
    assert c["concordance_support"] == {"detected_in": "antibody", "not_detected_in": "mass_spec"}
    assert c["boundary_sensitive"] is True
    assert c["qualifying_signal"]["source"] == "mass_spec"


def test_protein_presence_concordance_ms_detects_antibody_negative():
    c = _pp(ihc_cls="ihc_not_detected", cptac_cls="mid")
    assert c["concordance_class"] == "ms_detects_antibody_negative"
    assert c["concordance_support"] == {"detected_in": "mass_spec", "not_detected_in": "antibody"}
    assert c["corroboration"] == "low"


def test_protein_presence_concordance_single_source_only_antibody():
    # MS arm entirely a gap (no rank, no fraction) → only the antibody arm resolves.
    c = _pp(ihc_cls="ihc_detected_high", cptac_cls=None)
    assert c["concordance_class"] == "single_source_only"
    assert c["corroboration"] == "single_arm"
    assert c["concordance_support"]["resolved_by"] == "antibody"
    assert c["concordance_support"]["resolved_via_source"] == "antibody_ihc"
    assert c["corroborating_independent_arm_count"] == 1
    assert c["resolved_source_count"] == 1


def test_protein_presence_concordance_single_source_only_mass_spec():
    # antibody a gap (data_unavailable class) → only the MS arm resolves, via CPTAC.
    c = _pp(ihc_cls=None, cptac_cls="mid")
    assert c["concordance_class"] == "single_source_only"
    assert c["concordance_support"]["resolved_by"] == "mass_spec"
    assert c["concordance_support"]["resolved_via_source"] == "cptac_protein"


def test_protein_presence_concordance_single_patient_ihc_low_is_noise_floor():
    # a single-patient ihc_detected_low (n_detected < 2) is the HPA antibody noise floor → NOT a resolved
    # antibody detection; with MS also a gap the whole claim is omitted.
    assert _pp(ihc_cls="ihc_detected_low", ihc_n_high=0, ihc_n_medium=0, ihc_n_low=1, cptac_cls=None) is None
    # two detected patients clears the floor → antibody resolves present.
    c = _pp(ihc_cls="ihc_detected_low", ihc_n_high=0, ihc_n_medium=0, ihc_n_low=2, cptac_cls="mid")
    assert c["concordance_class"] == "protein_presence_concordant"


def test_protein_presence_concordance_gygi_supplies_ms_arm_but_never_a_second_arm():
    # CPTAC a gap, DepMap-Gygi resolves → the MS arm resolves VIA the cell-line sibling, still ONE MS arm.
    c = _pp(ihc_cls="ihc_detected_high", cptac_cls=None, gygi_cls="bottom_decile")
    assert c["concordance_class"] == "protein_presence_concordant"
    assert c["corroborating_independent_arm_count"] == 2  # antibody + MS layer (via Gygi) — NOT 3
    by = {s["source"]: s for s in c["source_support"]}
    assert by["gygi_protein"]["corroboration_eligible"] is False
    assert by["gygi_protein"]["dependence_group"] == "mass_spec"
    assert by["cptac_protein"]["resolved"] is False  # CPTAC unresolved; Gygi supplied the arm


def test_protein_presence_concordance_all_supply_paths_mutation():
    # full concordant read (all MS sources present).
    full = _pp(ihc_cls="ihc_detected_high", cptac_cls="mid", gygi_cls="bottom_decile", procan_cls="mid")
    assert full["concordance_class"] == "protein_presence_concordant"
    assert full["resolved_source_count"] == 4  # antibody + CPTAC + Gygi + ProCan
    assert full["corroborating_independent_arm_count"] == 2
    # defeat CPTAC only — Gygi still supplies the MS arm → NOT degraded.
    no_cptac = _pp(ihc_cls="ihc_detected_high", cptac_cls=None, gygi_cls="bottom_decile", procan_cls="mid")
    assert no_cptac["corroborating_independent_arm_count"] == 2
    # defeat EVERY mass-spec source — only the antibody arm survives → degrade to single_source_only.
    no_ms = _pp(ihc_cls="ihc_detected_high", cptac_cls=None, gygi_cls=None, procan_cls=None)
    assert no_ms["concordance_class"] == "single_source_only"
    # defeat the antibody arm too → EVERY independent supply path defeated → key omitted (byte-stable).
    assert _pp(ihc_cls=None, cptac_cls=None, gygi_cls=None, procan_cls=None) is None


def test_protein_presence_concordance_key_omitted_when_neither_arm_resolves():
    cv = presence_claim_vector(_headline(), _pp_cards(ihc_cls=None, cptac_cls=None, gygi_cls=None, procan_cls=None))
    assert "protein_presence_concordance" not in cv  # byte-stable omission


def test_protein_presence_concordance_grain_is_first_class_and_differs_across_arms():
    c = _pp(ihc_cls="ihc_detected_high", cptac_cls="mid")
    by = {s["source"]: s for s in c["source_support"]}
    assert by["antibody_ihc"]["grain"] == "antibody_ihc (patient tissue microarray)"
    assert by["cptac_protein"]["grain"] == "ms_protein (patient tumor)"  # arms DIFFER in detection technology


def test_protein_presence_concordance_retained_quantitative_recoverable():
    c = _pp(ihc_cls="ihc_detected_high", ihc_n_high=12, cptac_cls="mid")
    by = {s["source"]: s for s in c["source_support"]}
    assert by["antibody_ihc"]["retained_quantitative"]["n_high"] == 12
    assert by["antibody_ihc"]["retained_quantitative"]["fraction_detected"] == 1.0


def test_protein_presence_concordance_non_finite_quant_demoted_to_none():
    cards = _pp_cards(ihc_cls="ihc_detected_high", cptac_cls="mid")
    cards[0]["summary"]["staining_score"] = float("nan")
    c = _protein_presence_concordance_claim(_by_id_for_test(cards))
    by = {s["source"]: s for s in c["source_support"]}
    assert by["antibody_ihc"]["retained_quantitative"]["staining_score"] is None


def test_protein_presence_concordance_presentation_signal_shape():
    conc = _pp(ihc_cls="ihc_detected_high", cptac_cls="mid")
    assert _sr_signal_shape_ok(conc["positive_signal"])
    assert conc["qualifying_signal"] is None
    disagree = _pp(ihc_cls="ihc_detected_high", cptac_cls=None, cptac_frac=0)
    assert _sr_signal_shape_ok(disagree["positive_signal"]) and _sr_signal_shape_ok(disagree["qualifying_signal"])


def test_protein_presence_concordance_is_verdict_inert_and_purely_additive():
    cards = _pp_cards(ihc_cls="ihc_detected_high", cptac_cls="mid")
    cv = presence_claim_vector(_headline(), cards)
    claim = cv["protein_presence_concordance"]
    assert "signal" not in claim
    assert "verdict-INERT" in claim["_disclaimer"]
    # rebuild from the SAME card set with every protein arm defeated → the claim is omitted and every
    # other claim-vector key is byte-identical to the with-claim vector.
    bare = presence_claim_vector(_headline(), _pp_cards(ihc_cls=None, cptac_cls=None, gygi_cls=None, procan_cls=None))
    assert "protein_presence_concordance" not in bare
    # The IHC card also feeds the HEADLINE tumor_presence_concordance node (SK#1867, single_source_only via
    # the antibody arm), so BOTH additive L2b keys are the delta — strip both to compare the spine.
    _l2b = {"protein_presence_concordance", "tumor_presence_concordance"}
    common = {k: v for k, v in cv.items() if k not in _l2b}
    common_bare = {k: v for k, v in bare.items() if k not in _l2b}
    assert common == common_bare


def test_protein_presence_concordance_typed_edges_across_dispositions():
    # concordant → corroborates edge antibody→(resolving MS source); disagree → qualifies; single → none.
    conc = _pp(ihc_cls="ihc_detected_high", cptac_cls="mid")
    e = _only_edge(conc)
    assert e == {
        "from_source": "antibody_ihc",
        "to_source": "cptac_protein",
        "relation": "corroborates",
        "basis": "protein_presence_concordant",
    }
    disagree = _pp(ihc_cls="ihc_detected_high", cptac_cls=None, cptac_frac=0)
    ed = _only_edge(disagree)
    assert ed["relation"] == "qualifies"
    # single_source_only carries NO cross-source edge (the other arm is a gap).
    assert _pp(ihc_cls="ihc_detected_high", cptac_cls=None)["dependence_edges"] == []


def test_protein_presence_concordance_edge_endpoint_is_the_resolving_ms_source():
    # CPTAC unresolved but Gygi supplies the MS arm → the edge endpoint is the source that resolved it.
    c = _pp(ihc_cls="ihc_detected_high", cptac_cls=None, gygi_cls="bottom_decile")
    e = _only_edge(c)
    assert e["to_source"] == "gygi_protein" and e["from_source"] == "antibody_ihc"
    nodes = {s["source"] for s in c["source_support"]}
    assert {e["from_source"], e["to_source"]} <= nodes


# ── HEADLINE L2b tumor_presence_concordance (SK#1867) — the central 3-independent-source presence node ──
# bulk-RNA (tumor-rna-distribution) x single-cell malignant RNA (tumor-scrna-celltype-expression) x
# antibody-IHC (hpa-pathology-cancer-ihc). Three INDEPENDENT measurement groups → independence-group
# corroboration ("3 independent groups → HIGH"). Verdict-inert, additive.
from _skills_common.presence_claims import _tumor_presence_concordance_claim  # noqa: E402


def _tpc_cards(
    bulk_cls="broadly_high",
    sc_cls="malignant_broadly_detected",
    ihc_cls="ihc_detected_high",
    ihc_n_high=12,
):
    """Build the three tumor-presence cards exercising the builder's three INDEPENDENT arms. bulk_cls=None
    / sc_cls=None / ihc_cls=None are absent (unresolved) arms; broadly_low (bulk), microenvironment_dominant
    or broadly_low (sc), ihc_not_detected are MEASURED non-detections."""
    return [
        {
            "card_id": "tumor-rna-distribution",
            "summary": {
                "tumor_expression_class": bulk_cls,
                "high_fraction": 0.82,
                "n_tumor_samples": 300,
                "median_tpm": 45.0,
            },
        },
        {
            "card_id": "tumor-scrna-celltype-expression",
            "summary": {
                "sc_expression_class": sc_cls,
                "malignant_detection_fraction": 0.88,
                "malignant_n_donors": 24,
                "malignant_n_cells": 50912,
            },
        },
        {
            "card_id": "hpa-pathology-cancer-ihc",
            "summary": {
                "protein_presence_class": ihc_cls,
                "fraction_detected": (
                    1.0
                    if ihc_cls in ("ihc_detected_high", "ihc_detected_moderate")
                    else (0.0 if ihc_cls == "ihc_not_detected" else 0.1)
                ),
                "staining_score": 3.0,
                "n_high": ihc_n_high,
                "n_medium": 0,
                "n_low": 0,
                "n_not_detected": 0,
                "n_patients_total": max(ihc_n_high, 1),
                "hpa_cancer_type": "colorectal cancer",
            },
        },
    ]


def _tpc(**kw):
    return _tumor_presence_concordance_claim(_by_id_for_test(_tpc_cards(**kw)))


def test_tumor_presence_concordance_three_independent_groups_agree_present():
    c = _tpc(bulk_cls="broadly_high", sc_cls="malignant_broadly_detected", ihc_cls="ihc_detected_high")
    assert c["concordance_class"] == "tumor_presence_concordant"
    assert c["corroboration"] == "high"  # 3 INDEPENDENT groups agree → HIGH
    assert c["integration_method"] == "explicit_deterministic"
    assert c["concordance_support"]["agreed_direction"] == "present"
    assert set(c["concordance_support"]["agreeing_arms"]) == {"bulk_rna", "sc_malignant", "antibody_ihc"}
    assert c["corroborating_independent_arm_count"] == 3
    assert c["resolved_source_count"] == 3  # no dependent siblings → the two counts coincide
    assert c["boundary_sensitive"] is False
    assert c["qualifying_signal"] is None  # all three resolve → no gap caveat
    assert "signal" not in c
    # three fully-independent groups → three pairwise corroborates edges.
    rels = [e["relation"] for e in c["dependence_edges"]]
    assert rels == ["corroborates", "corroborates", "corroborates"]


def test_tumor_presence_concordance_three_groups_agree_absent():
    c = _tpc(bulk_cls="broadly_low", sc_cls="microenvironment_dominant", ihc_cls="ihc_not_detected")
    assert c["concordance_class"] == "tumor_presence_concordant"
    assert c["concordance_support"]["agreed_direction"] == "measured_not_present"
    assert c["corroboration"] == "high"


def test_tumor_presence_concordance_discordant_when_groups_disagree():
    # bulk + antibody detect, single-cell malignant compartment a MEASURED non-detection → discordant.
    c = _tpc(bulk_cls="broadly_high", sc_cls="microenvironment_dominant", ihc_cls="ihc_detected_high")
    assert c["concordance_class"] == "tumor_presence_discordant"
    assert c["corroboration"] == "low"  # any disagreement → low
    assert set(c["concordance_support"]["detected_in"]) == {"bulk_rna", "antibody_ihc"}
    assert c["concordance_support"]["not_detected_in"] == ["sc_malignant"]
    assert c["boundary_sensitive"] is True
    # pairwise edges: the two detecting arms corroborate; each vs the dissenter qualifies.
    rels = sorted(e["relation"] for e in c["dependence_edges"])
    assert rels == ["corroborates", "qualifies", "qualifies"]


def test_tumor_presence_concordance_two_groups_agree_is_corroborated_with_gap_caveat():
    # exactly two INDEPENDENT arms resolve and agree (>= the arm floor) → concordant + high, with the
    # unresolved arm surfaced as a gap in the qualifying signal.
    c = _tpc(bulk_cls="broadly_high", sc_cls="malignant_broadly_detected", ihc_cls=None)
    assert c["concordance_class"] == "tumor_presence_concordant"
    assert c["corroboration"] == "high"
    assert c["corroborating_independent_arm_count"] == 2
    assert c["qualifying_signal"] is not None and c["qualifying_signal"]["source"] == "antibody_ihc"
    e = _only_edge(c)  # exactly one pairwise edge among the two resolved arms
    assert e["relation"] == "corroborates"
    assert {e["from_source"], e["to_source"]} == {"bulk_rna", "sc_malignant"}


def test_tumor_presence_concordance_single_source_only():
    # only the bulk-RNA arm resolves → a degraded single-group read, never a corroborated presence claim.
    c = _tpc(bulk_cls="broadly_high", sc_cls=None, ihc_cls=None)
    assert c["concordance_class"] == "single_source_only"
    assert c["corroboration"] == "single_arm"
    assert c["concordance_support"]["resolved_by"] == "bulk_rna"
    assert c["concordance_support"]["resolved_present"] is True
    assert c["corroborating_independent_arm_count"] == 1
    assert c["resolved_source_count"] == 1
    assert c["dependence_edges"] == []  # a single resolved arm relates no two sources


def test_tumor_presence_concordance_erasing_the_claim_takes_defeating_all_three_arms():
    # defeat two arms — the third alone still emits (degraded).
    assert _tpc(bulk_cls="broadly_high", sc_cls=None, ihc_cls=None)["concordance_class"] == "single_source_only"
    # defeat ALL THREE independent arms → key omitted (byte-stable).
    assert _tpc(bulk_cls=None, sc_cls=None, ihc_cls=None) is None
    assert _tpc(bulk_cls="data_unavailable", sc_cls="data_unavailable", ihc_cls=None) is None


def test_tumor_presence_concordance_key_omitted_when_no_arm_resolves():
    cv = presence_claim_vector(_headline(), _tpc_cards(bulk_cls=None, sc_cls=None, ihc_cls=None))
    assert "tumor_presence_concordance" not in cv  # byte-stable omission


def test_tumor_presence_concordance_grain_is_first_class_and_differs_across_arms():
    c = _tpc()
    by = {s["source"]: s for s in c["source_support"]}
    assert by["bulk_rna"]["grain"] == "bulk_rna (population-averaged tumor transcriptome)"
    assert by["sc_malignant"]["grain"] == "sc_rna (single-cell MALIGNANT-compartment transcriptome)"
    assert by["antibody_ihc"]["grain"] == "antibody_ihc (patient tissue-microarray immunostaining)"
    # all three arms are INDEPENDENT modalities — every one corroboration-eligible, own group.
    assert all(s["corroboration_eligible"] for s in c["source_support"])
    groups = c["evidence_dependence"]["groups"]
    assert all(g["relationship"] == "independent_modality" for g in groups) and len(groups) == 3


def test_tumor_presence_concordance_retained_quantitative_recoverable():
    c = _tpc()
    by = {s["source"]: s for s in c["source_support"]}
    assert by["bulk_rna"]["retained_quantitative"]["high_fraction"] == 0.82
    assert by["sc_malignant"]["retained_quantitative"]["malignant_n_donors"] == 24
    assert by["antibody_ihc"]["retained_quantitative"]["n_patients_total"] == 12


def test_tumor_presence_concordance_non_finite_quant_demoted_to_none():
    cards = _tpc_cards()
    cards[0]["summary"]["high_fraction"] = float("inf")
    c = _tumor_presence_concordance_claim(_by_id_for_test(cards))
    by = {s["source"]: s for s in c["source_support"]}
    assert by["bulk_rna"]["retained_quantitative"]["high_fraction"] is None


def test_tumor_presence_concordance_presentation_signal_shape():
    conc = _tpc()
    assert _sr_signal_shape_ok(conc["positive_signal"])
    assert conc["qualifying_signal"] is None
    disagree = _tpc(bulk_cls="broadly_high", sc_cls="microenvironment_dominant", ihc_cls="ihc_detected_high")
    assert _sr_signal_shape_ok(disagree["positive_signal"]) and _sr_signal_shape_ok(disagree["qualifying_signal"])


def test_tumor_presence_concordance_typed_edges_reference_only_declared_source_nodes():
    c = _tpc()
    nodes = {s["source"] for s in c["source_support"]}
    for e in c["dependence_edges"]:
        assert {e["from_source"], e["to_source"]} <= nodes
        assert e["relation"] in DEPENDENCE_RELATIONS


def test_tumor_presence_concordance_is_verdict_inert_additive_key():
    # The headline node is a NET-NEW additive L2b key that carries NO `signal` (never a chip/tier), reads no
    # verdict and feeds no rule → the disclaimer names the verdict-inert contract. Unlike the protein family
    # its three arms READ THE SAME CARDS as the base A-D letter claims (bulk RNA / single-cell), so a
    # "defeat every arm and diff the spine" comparison is inapplicable (it would also blank claim A/C); the
    # integration-level byte-stability of presence_verdict / presence_verdict_by_modality / the resolver
    # goldens is proven by the epcam golden replay, not this unit.
    cards = _tpc_cards()
    cv = presence_claim_vector(_headline(), cards)
    claim = cv["tumor_presence_concordance"]
    assert "signal" not in claim
    assert "verdict-INERT" in claim["_disclaimer"]
    # the key is a pure ADDITION: absent from the vector when NO independent arm resolves (byte-stable
    # omission), present only as the extra key when one does.
    bare = presence_claim_vector(_headline(), _tpc_cards(bulk_cls=None, sc_cls=None, ihc_cls=None))
    assert "tumor_presence_concordance" not in bare
    assert "tumor_presence_concordance" in cv


# ── L2a NAMED source_properties map (SK#1939) ──────────────────────────────────────────────────────
def _cards_with_cptac_and_cellline():
    """The base cards + a CPTAC protein arm and a cell-line RNA arm (with a resolved expression_properties
    object) so every one of the six source_properties recipes can resolve."""
    return _cards() + [
        {
            "card_id": "tumor-protein-abundance-cptac",
            "summary": {
                "protein_expression_class": "significant_up",
                "allgene_percentile": 74.1,
                "protein_effect_size": 0.9,
                "protein_bh_q_value": 1e-4,
            },
        },
        {
            "card_id": "cellline-rna-distribution",
            "summary": {
                "expression_class": "broadly_moderate",
                "allgene_percentile": 52.5,
                "expression_properties": {"heterogeneity": "high", "prevalence": "subset"},
            },
        },
    ]


def test_source_properties_surfaces_named_per_source_map():
    """The lifted L2a map surfaces one entry per resolved source/grain, each with card_id + resolved
    property + retained anchors + comparability metadata — the architecture's source_properties shape."""
    vec = presence_claim_vector(_headline(), _cards_with_cptac_and_cellline())
    assert "source_properties" in vec, "the named L2a source_properties map must surface on the claim vector"
    sp = vec["source_properties"]
    # all six source/grain recipes resolve on this maximal fixture
    assert set(sp) == {
        "patient_tumor_abundance",
        "tumor_normal_selectivity",
        "tumor_protein_abundance",
        "malignant_cell_coverage",
        "tumor_elevation_breadth",
        "model_expression_structure",
    }
    pta = sp["patient_tumor_abundance"]
    assert pta["card_id"] == "tumor-rna-distribution"
    assert pta["property"] == "broadly_detected"  # the resolved observational class, read from the card
    assert pta["comparability"] == {
        "measurement_type": "tumor_rna_expression",
        "sample_context": "tumor",
        "grain": "bulk",
    }


def test_source_properties_anchors_are_recoverable_and_two_axis_typed():
    """Each retained anchor binds {field, value, scale} — reconstructable to its L1 card field — and
    carries the two-axis field-disposition typing (semantic_role + interpretation_reach, SK#1525)."""
    vec = presence_claim_vector(_headline(), _cards_with_cptac_and_cellline())
    anchors = {a["field"]: a for a in vec["source_properties"]["patient_tumor_abundance"]["anchors"]}
    # value is the RAW L1 card value (recoverable), not a re-derived tier
    assert anchors["median_log2tpm"]["value"] == 3.97
    assert anchors["median_log2tpm"]["scale"] == "log2_tpm"
    # two-axis disposition typing is sourced from the tumor-presence ledger
    assert anchors["allgene_percentile"]["semantic_role"] in ("signal", "context", "provenance", "display")
    assert anchors["allgene_percentile"]["interpretation_reach"] in (
        "unreached",
        "skills_local",
        "cross_repo_resolver",
    )


def test_source_properties_retains_resolved_expression_properties_object():
    """The cell-line source retains the shared resolved expression_properties object when present
    (recoverable structured property), mirroring the _expression_property_atom passthrough."""
    vec = presence_claim_vector(_headline(), _cards_with_cptac_and_cellline())
    model = vec["source_properties"]["model_expression_structure"]
    assert model["resolved_expression_properties"] == {"heterogeneity": "high", "prevalence": "subset"}


def test_source_properties_is_verdict_inert_and_carries_no_signal_tier():
    """Surfacing source_properties is a PURE ADDITION: it perturbs none of the A/B/C/D claim tiers and
    carries no `signal` key (not a chip, not a tier)."""
    base = presence_claim_vector(_headline(), _cards())
    withsp = presence_claim_vector(_headline(), _cards())
    for ax in ("A", "B", "C", "D", "homogeneity"):
        assert withsp[ax] == base[ax], f"surfacing source_properties perturbed {ax}"
    for entry in withsp["source_properties"].values():
        assert "signal" not in entry and "corroboration" not in entry


def test_source_properties_omitted_when_no_source_resolves():
    """No presence source card ⇒ no entry ⇒ the whole key is omitted, keeping a card-absent run
    byte-stable (matching the A/B/C/D + expression_properties + concordance atom discipline)."""
    vec = presence_claim_vector(_headline(), [])
    assert "source_properties" not in vec


# ── #1516 F1: multi_entity_pooled down-weights claim-C corroboration SYMMETRICALLY with phenotype_proxy ──
# The single-cell reader records its own data-quality tier (malignant_annotation_method / entity_purity).
# claim-C folds it into the (verdict-inert) corroboration. Before #1516, phenotype_proxy/ambient
# DOWN-WEIGHTED corroboration but multi_entity_pooled was a NOTE ONLY — a pooled call (which cannot
# attribute the malignant signal to THIS entity) kept full-strength corroboration. These tests store the
# RAW headline + cards and RE-DERIVE claim-C via the production path (presence_claim_vector); the pooled
# case FAILS on the pre-fix code (pooled corroboration == entity_specific, above phenotype_proxy) and
# PASSES after (pooled corroboration == phenotype_proxy, both a rung below entity_specific).


def _claim_c_corroboration(annotation_method=None, entity_purity=None):
    """Re-derive claim-C corroboration via the production path for a given sc data-quality tier.
    n_donors=362 (>= POWER_HIGH_N=100) so the base reliability is `high`, leaving room for a one-rung
    down-weight to be observable (a base `low` would make _CORR_DOWN a no-op and the test vacuous)."""
    sc_summary = {
        "sc_expression_class": "malignant_broadly_detected",
        "malignant_detection_fraction": 0.72,
        "malignant_n_donors": 362,
        "caf_vs_malignant_class": "malignant_dominant",
    }
    if annotation_method is not None:
        sc_summary["malignant_annotation_method"] = annotation_method
    if entity_purity is not None:
        sc_summary["entity_purity"] = entity_purity
    cards = [{"card_id": "tumor-scrna-celltype-expression", "summary": sc_summary}]
    headline = {
        "sc_expression_class": "malignant_broadly_detected",
        "sc_malignant_detection_fraction": 0.72,
        "sc_malignant_n_donors": 362,
        "sc_malignant_n_cells": 4000,
    }
    return presence_claim_vector(headline, cards)["C"]["corroboration"]


def test_claim_c_base_corroboration_is_high_for_a_clean_curated_entity_specific_call():
    # The instrument's baseline: a curated, entity-specific, well-powered call is high — so a down-weight
    # to `moderate` is a real, observable move (not masked by an already-floored `low`).
    assert _claim_c_corroboration(annotation_method="curated", entity_purity="entity_specific") == "high"


def test_claim_c_multi_entity_pooled_downweights_symmetrically_with_phenotype_proxy():
    # THE MUTATION TOOTH. Pre-fix: pooled was note-only → corroboration stayed `high` (== entity_specific),
    # ABOVE the phenotype_proxy `moderate`. Post-fix: pooled down-weights the SAME degree as phenotype_proxy.
    pooled = _claim_c_corroboration(annotation_method="curated", entity_purity="multi_entity_pooled")
    phenotype = _claim_c_corroboration(annotation_method="phenotype_proxy", entity_purity="entity_specific")
    entity_specific = _claim_c_corroboration(annotation_method="curated", entity_purity="entity_specific")
    assert pooled == phenotype == "moderate", (
        f"multi_entity_pooled ({pooled}) must down-weight claim-C corroboration symmetrically with "
        f"phenotype_proxy ({phenotype}) — #1516 F1"
    )
    assert pooled != entity_specific, "pooled must sit BELOW an entity-specific call's corroboration"


def test_claim_c_phenotype_proxy_downweight_is_unchanged_guard():
    # GUARD: the pre-existing phenotype_proxy down-weight (high → moderate) is not regressed by the F1 edit.
    phenotype = _claim_c_corroboration(annotation_method="phenotype_proxy", entity_purity="entity_specific")
    clean = _claim_c_corroboration(annotation_method="curated", entity_purity="entity_specific")
    assert clean == "high" and phenotype == "moderate", (
        "phenotype_proxy must still down-weight claim-C corroboration one rung below a curated call"
    )
