"""Test tumor-presence per-(measurement, sample_context) sub-verdicts.

Per MODALITY_TAXONOMY.md, the per-modality view keys buckets
by the (measurement, sample_context) PAIR — `bulk_rna/cell_line`, `bulk_rna/tumor`,
`bulk_protein_ms/cell_line`, `bulk_protein_ms/tumor` — so a cell-line-RNA signal is
never conflated with a tumor-RNA signal (both are `measurement: bulk_rna`).

The refactor is ADDITIVE: the collapsed `presence_verdict` (the audit spine the
target-profile consumer reads as `verdict`) stays byte-stable. These tests pin:
  1. collapsed verdict = same rank ladder as before (consumer contract);
  2. fired rules group by their card's (measurement, sample_context) pair (CARD_CONTEXT);
  3. within-bucket ranking uses the MEASUREMENT's ladder (rule vocab is measurement-scoped);
  4. buckets with no card (sc_rna/tumor, protein_ihc/normal) emit explicit
     data_unavailable — a NAMED gap, never a fabricated negative;
  5. the disagreement case (RNA-high, protein-low) is legible per-bucket while the
     collapsed verdict is unchanged;
  6. THE DEGENERATE CASE: a target-only query (cell-line RNA measured, tumor RNA
     absent) is now HONEST — bulk_rna/cell_line measured + bulk_rna/tumor
     data_unavailable are distinct, not collapsed into one bulk_rna bucket.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run")


def _fr(rule_id, card_id):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x", "value": "y", "signals": {}}


# --- collapsed verdict unchanged (consumer contract) --------------


def test_collapsed_verdict_ranks_across_all_cards():
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("expression-strong-upregulation-supportive", "tumor-rna-vs-adjacent"),
    ]
    assert tp._verdict(fired) == ("broadly_high_expression", "expression-broadly-high-supportive")


def test_collapsed_verdict_no_rules_is_insufficient():
    assert tp._verdict([]) == ("insufficient", None)


# --- per-bucket grouping + within-bucket ranking ----------------------------


def test_bulk_rna_buckets_are_split_by_sample_context():
    """Two bulk_rna cards with DIFFERENT sample_context land in SEPARATE buckets —
    the whole point. Previously both collapsed into one `bulk_rna` key."""
    fired = [
        _fr("expression-strong-upregulation-supportive", "tumor-rna-vs-adjacent"),
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
    ]
    pm = tp._per_modality_verdicts(fired)
    # cell-line RNA: broadly-high (the distribution card)
    assert pm["bulk_rna/cell_line"]["verdict"] == "broadly_high_expression"
    assert pm["bulk_rna/cell_line"]["evidence_state"] == "measured"
    # tumor RNA: strong-upregulation (the tumor-vs-adjacent card) — a DISTINCT bucket
    assert pm["bulk_rna/tumor"]["verdict"] == "strongly_upregulated_in_tumor"
    assert pm["bulk_rna/tumor"]["evidence_state"] == "measured"


def test_degenerate_target_only_case_is_honest():
    """THE degenerate-case fix: a target-only query fires ONLY the cell-line card, so
    bulk_rna/cell_line is measured while bulk_rna/tumor is data_unavailable — no longer
    collapsed into a single bulk_rna bucket that masqueraded as tumor evidence."""
    fired = [_fr("expression-broadly-moderate-neutral", "cellline-rna-distribution")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_rna/cell_line"]["evidence_state"] == "measured"
    assert pm["bulk_rna/cell_line"]["verdict"] == "broadly_moderate_expression"
    assert pm["bulk_rna/tumor"]["evidence_state"] == "data_unavailable"
    assert pm["bulk_rna/tumor"]["verdict"] == "data_unavailable"


def test_protein_bucket_is_separate_from_rna():
    # bulk_protein_ms/tumor fires a REAL protein rule_id ranked against _PROTEIN_RANK.
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("protein-strongly-down-opposing", "tumor-protein-abundance-cptac"),
    ]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_rna/cell_line"]["verdict"] == "broadly_high_expression"
    assert pm["bulk_protein_ms/tumor"]["verdict"] == "protein_strongly_downregulated"
    assert pm["bulk_protein_ms/tumor"]["evidence_state"] == "measured"


def test_protein_only_signal_not_swallowed_C1_regression():
    """Regression guard (2026-07-20): a target with a MEASURED bulk_protein_ms
    signal and NO expression signal must produce a real protein verdict — NOT the
    silent `insufficient` collapse the expression-only ladder caused."""
    # measured cell-line protein presence, no RNA
    pm = tp._per_modality_verdicts([_fr("protein-abundance-broadly-high-supportive", "cellline-protein-abundance")])
    assert pm["bulk_protein_ms/cell_line"]["verdict"] == "protein_broadly_high"
    assert pm["bulk_protein_ms/cell_line"]["verdict"] != "insufficient"
    # a measured protein-absence killer (cell-line broadly_low) must surface, not vanish
    pm2 = tp._per_modality_verdicts(
        [_fr("protein-abundance-broadly-low-degrader-killer", "cellline-protein-abundance")]
    )
    assert pm2["bulk_protein_ms/cell_line"]["verdict"] == "protein_broadly_low"
    # collapsed verdict: a protein-only target resolves instead of collapsing
    v, drv = tp._verdict([_fr("protein-abundance-broadly-high-supportive", "cellline-protein-abundance")])
    assert v == "protein_broadly_high" and drv is not None


def test_measured_protein_outranks_expression_data_unavailable_in_collapsed_spine():
    """Cross-modality-swallow regression: when an expression `data_unavailable` rule fires
    ALONGSIDE a measured protein rule, the collapsed presence_verdict must resolve to the
    measured PROTEIN call — not the expression coverage-gap. The naive
    _EXPRESSION_RANK + _PROTEIN_RANK concatenation ranked expression's data_unavailable ABOVE
    every protein rule, silently discarding the protein signal."""
    # strong protein up + expression data_unavailable (the common target-only-CPTAC case:
    # tumor-rna-vs-adjacent returns data_unavailable for non-COADREAD indications)
    fired = [
        _fr("expression-call-data-unavailable-insufficient", "tumor-rna-vs-adjacent"),
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
    ]
    v, drv = tp._verdict(fired)
    assert v == "protein_strongly_upregulated"
    assert drv == "protein-strongly-up-supportive"

    # a measured protein-absence KILLER (cell-line broadly_low) must likewise survive an expression gap
    fired_killer = [
        _fr("expression-data-unavailable-insufficient", "cellline-rna-distribution"),
        _fr("protein-abundance-broadly-low-degrader-killer", "cellline-protein-abundance"),
    ]
    vk, _ = tp._verdict(fired_killer)
    assert vk == "protein_broadly_low"

    # only when BOTH layers are data_unavailable does the verdict stay data_unavailable
    both_gap = [
        _fr("expression-data-unavailable-insufficient", "cellline-rna-distribution"),
        _fr("protein-data-unavailable-insufficient", "tumor-protein-abundance-cptac"),
    ]
    vg, _ = tp._verdict(both_gap)
    assert vg == "data_unavailable"


def test_measured_expression_still_wins_over_measured_protein_byte_stable():
    """RNA stays the presence backbone: when BOTH a measured expression rule and a measured
    protein rule fire, expression wins first (existing RNA-target verdicts are byte-stable)."""
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
    ]
    v, drv = tp._verdict(fired)
    assert v == "broadly_high_expression"
    assert drv == "expression-broadly-high-supportive"


def test_tumor_elevation_breadth_shares_protein_tumor_bucket():
    """tumor-elevation-breadth is bulk_protein_ms × tumor — SAME bucket as
    the CPTAC per-indication card, ranked against _PROTEIN_RANK."""
    assert tp.CARD_CONTEXT["tumor-elevation-breadth"] == ("bulk_protein_ms", "tumor")
    fired = [_fr("tumor-breadth-broadly-supportive", "tumor-elevation-breadth")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_protein_ms/tumor"]["verdict"] == "broadly_tumor_elevated"
    assert pm["bulk_protein_ms/tumor"]["evidence_state"] == "measured"


def test_breadth_gives_target_only_query_a_tumor_signal():
    """THE payoff: in a target-ONLY query, the per-indication tumor cards
    (CPTAC, tumor-vs-adjacent) don't fire — but breadth DOES (it rolls up over all
    cohorts). So bulk_protein_ms/tumor reads `measured` (broadly_tumor_elevated) even
    though bulk_rna/tumor stays data_unavailable. Breadth is the one tumor-context
    presence signal a target-only query gets."""
    # target-only: cell-line RNA + cell-line protein + breadth fire; no per-indication tumor card
    fired = [
        _fr("expression-broadly-moderate-neutral", "cellline-rna-distribution"),
        _fr("protein-abundance-broadly-high-supportive", "cellline-protein-abundance"),
        _fr("tumor-breadth-multi-supportive", "tumor-elevation-breadth"),
    ]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_protein_ms/tumor"]["evidence_state"] == "measured"
    assert pm["bulk_protein_ms/tumor"]["verdict"] == "multi_tumor_elevated"
    # bulk_rna/tumor still has no card firing → honest data_unavailable
    assert pm["bulk_rna/tumor"]["evidence_state"] == "data_unavailable"


def test_specific_cptac_call_outranks_breadth_in_shared_bucket():
    """When BOTH the per-indication CPTAC strong_up AND pan-cancer breadth fire (a
    target-INDICATION query), the specific per-indication call wins the shared
    bulk_protein_ms/tumor bucket — it is more decision-relevant than breadth."""
    fired = [
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
        _fr("tumor-breadth-broadly-supportive", "tumor-elevation-breadth"),
    ]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_protein_ms/tumor"]["verdict"] == "protein_strongly_upregulated"


def test_breadth_not_elevated_is_neutral_not_killer():
    """A measured 'elevated in no cohort' breadth is NEVER a presence killer (un-elevated
    protein may still be abundantly present). It ranks above the downs/killers but
    resolves to the neutral not_tumor_elevated verdict."""
    pm = tp._per_modality_verdicts([_fr("tumor-breadth-not-elevated-neutral", "tumor-elevation-breadth")])
    assert pm["bulk_protein_ms/tumor"]["verdict"] == "not_tumor_elevated"


def test_celline_proteomics_card_feeds_bulk_protein_ms_cell_line():
    """The cellline-protein-abundance card is bulk_protein_ms × cell_line — its
    fired rule lands in the bulk_protein_ms/cell_line bucket, DISTINCT from CPTAC's
    bulk_protein_ms/tumor bucket."""
    assert tp.CARD_CONTEXT["cellline-protein-abundance"] == ("bulk_protein_ms", "cell_line")
    fired = [_fr("protein-abundance-broadly-high-supportive", "cellline-protein-abundance")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_protein_ms/cell_line"]["evidence_state"] == "measured"
    # CPTAC tumor protein bucket stays data_unavailable (no CPTAC card fired)
    assert pm["bulk_protein_ms/tumor"]["evidence_state"] == "data_unavailable"
    # all bulk_rna buckets stay data_unavailable (no RNA card fired) — axes independent
    assert pm["bulk_rna/cell_line"]["evidence_state"] == "data_unavailable"
    assert pm["bulk_rna/tumor"]["evidence_state"] == "data_unavailable"


def test_genuine_protein_absence_demotes_collapsed_verdict():
    """RNA broadly_high + a MEASURED genuine protein-ABSENCE (cell-line broadly_low, detected in <30% of
    the Gygi MS panel). The protein-absence demotion fires: the collapsed verdict
    is no longer the un-caveated `broadly_high_expression` (which buried the protein contradiction under
    the one word) — it demotes to `present_rna_only_protein_absent` (still a present call; the driving
    RNA rung is retained). The per-bucket breakdown continues to expose the disagreement directly."""
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("protein-abundance-broadly-low-degrader-killer", "cellline-protein-abundance"),
    ]
    v, drv = tp._verdict(fired)
    assert v == tp.PRESENT_RNA_ONLY_PROTEIN_ABSENT
    assert drv == "expression-broadly-high-supportive"  # traceable to the RNA presence rung
    assert tp._is_presence_positive(v)  # still a present call, just caveated
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_rna/cell_line"]["verdict"] != pm["bulk_protein_ms/cell_line"]["verdict"]


def test_protein_down_contrast_does_not_demote_G2b_regression():
    """Tumor-presence expert review: a tumor-vs-normal protein DOWN contrast
    (protein-{strongly,modestly}-down-opposing) is a Phase-B SELECTIVITY signal — the protein was
    MEASURED PRESENT but is lower in tumor than matched normal — NOT absence. It must NOT demote a
    present RNA call to `present_rna_only_protein_absent` (a category error the old demotion committed by
    keying on the whole protein measured-negative tier). The RNA present call stands; the down-contrast
    stays legible per-bucket + via the headline_conflict guard."""
    for down_rid in ("protein-strongly-down-opposing", "protein-modestly-down-opposing"):
        fired = [
            _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
            _fr(down_rid, "tumor-protein-abundance-cptac"),
        ]
        v, drv = tp._verdict(fired)
        assert v == "broadly_high_expression", (
            f"a protein down-CONTRAST ({down_rid}) must not demote a present RNA call to protein_absent; got {v!r}"
        )
        assert drv == "expression-broadly-high-supportive"
        # the down-contrast is still surfaced as a measured negative in its own bucket
        pm = tp._per_modality_verdicts(fired)
        assert pm["bulk_protein_ms/tumor"]["evidence_state"] == "measured"
        assert pm["bulk_protein_ms/tumor"]["verdict"] in (
            "protein_strongly_downregulated",
            "protein_modestly_downregulated",
        )


def test_protein_absence_demotion_requires_all_three_conditions():
    """The demotion fires ONLY on (RNA-lens positive) AND (a genuine protein-ABSENCE rule) AND (no
    protein-positive). Each condition alone leaves the ordinary collapse untouched. The protein-negative
    must be an ABSENCE signal (broadly_low / not_detected), not a down-contrast (see the down-contrast test)."""
    rna = _fr("expression-broadly-high-supportive", "cellline-rna-distribution")
    prot_absent = _fr("protein-abundance-broadly-low-degrader-killer", "cellline-protein-abundance")
    prot_pos = _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac")
    # RNA positive alone → ordinary RNA verdict (no protein absence)
    assert tp._verdict([rna])[0] == "broadly_high_expression"
    # RNA positive + protein ABSENCE + no protein positive → demoted
    assert tp._verdict([rna, prot_absent])[0] == tp.PRESENT_RNA_ONLY_PROTEIN_ABSENT
    # RNA positive + protein absence + protein POSITIVE → NOT demoted (protein corroborates presence)
    assert tp._verdict([rna, prot_absent, prot_pos])[0] == "broadly_high_expression"
    # protein absence WITHOUT an RNA-lens positive → ordinary negative, never demoted-positive
    v, _ = tp._verdict([prot_absent])
    assert v == "protein_broadly_low" and not tp._is_presence_positive(v)


# --- honest gaps: unbuilt substrates are data_unavailable, never negative ---


def test_unbuilt_substrates_are_data_unavailable():
    """After the 2026-08-07 update all buckets are card-backed (no more unbuilt gaps).
    sc_rna/normal is a safety comparator backed by sc-normal-celltype-expression;
    protein_ihc/normal is backed by normal-tissue-liability. When no comparator value is
    available (card absent / data_unavailable), buckets still emit data_unavailable."""
    fired = [_fr("expression-broadly-high-supportive", "cellline-rna-distribution")]
    pm = tp._per_modality_verdicts(fired)
    # protein_ihc/normal and sc_rna/normal are comparator buckets — no presence rule fires for them,
    # so without a card supplying a valid comparator value they remain data_unavailable.
    assert pm["protein_ihc/normal"]["verdict"] == "data_unavailable"
    assert pm["protein_ihc/normal"]["evidence_state"] == "data_unavailable"
    assert pm["sc_rna/normal"]["verdict"] == "data_unavailable"
    assert pm["sc_rna/normal"]["evidence_state"] == "data_unavailable"
    # sc_rna/tumor with no sc rule fired → still data_unavailable (empty bucket), but it is now
    # card-backed: a fired sc rule DOES resolve it (test_sc_rna_bucket_resolves_when_card_fires).
    assert pm["sc_rna/tumor"]["evidence_state"] == "data_unavailable"


# --- sc_rna (2026-08-04): sc_rna/tumor is now card-backed --------------


def test_sc_rna_bucket_resolves_when_card_fires():
    """THE sc_rna payoff: the sc_rna/tumor bucket, formerly a hard-coded named gap, now
    resolves to a real MEASURED verdict when the tumor-scrna-celltype-expression card fires."""
    fired = [_fr("sc-expression-malignant-broadly-detected-supportive", "tumor-scrna-celltype-expression")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["sc_rna/tumor"]["verdict"] == "sc_malignant_detected"
    assert pm["sc_rna/tumor"]["evidence_state"] == "measured"


def test_sc_rna_microenvironment_dominant_is_neutral_measured():
    """microenvironment_dominant is a MEASURED neutral (present but not tumor-cell-intrinsic),
    ranked above broadly_low, never a killer."""
    fired = [_fr("sc-expression-microenvironment-dominant-neutral", "tumor-scrna-celltype-expression")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["sc_rna/tumor"]["verdict"] == "sc_microenvironment_dominant"
    assert pm["sc_rna/tumor"]["evidence_state"] == "measured"


def test_sc_rna_card_context_is_sc_rna_tumor():
    assert tp.CARD_CONTEXT["tumor-scrna-celltype-expression"] == ("sc_rna", "tumor")


def test_sc_rna_only_target_resolves_collapsed_spine_not_insufficient():
    """A target firing ONLY an sc rule (e.g. a COADREAD single-cell read with no bulk cards) now
    resolves the collapsed presence_verdict instead of collapsing to insufficient."""
    v, drv = tp._verdict(
        [_fr("sc-expression-malignant-broadly-detected-supportive", "tumor-scrna-celltype-expression")]
    )
    assert v == "sc_malignant_detected"
    assert drv == "sc-expression-malignant-broadly-detected-supportive"


def test_sc_rna_ranks_below_bulk_backbone_byte_stable():
    """sc_rna measured rules rank BELOW the bulk backbone in the collapsed spine, so a target firing
    BOTH a bulk expression rule and an sc rule keeps its OLD (bulk) verdict — byte-stability."""
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("sc-expression-malignant-broadly-detected-supportive", "tumor-scrna-celltype-expression"),
    ]
    v, drv = tp._verdict(fired)
    assert v == "broadly_high_expression"  # unchanged — bulk backbone wins
    assert drv == "expression-broadly-high-supportive"


def test_sc_rna_data_unavailable_sinks_below_measured():
    """An sc data_unavailable rule must not outrank a measured bulk/protein call in the collapsed
    spine (measured-first invariant extends to the sc gap partition)."""
    fired = [
        _fr("expression-data-unavailable-insufficient", "cellline-rna-distribution"),
        _fr("sc-expression-data-unavailable-insufficient", "tumor-scrna-celltype-expression"),
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
    ]
    v, _ = tp._verdict(fired)
    assert v == "protein_strongly_upregulated"


def test_no_fired_rules_all_buckets_data_unavailable():
    pm = tp._per_modality_verdicts([])
    expected = {tp._ctx_key(m, s) for m, s in tp.ALL_CONTEXTS}
    assert set(pm.keys()) == expected
    for v in pm.values():
        assert v["verdict"] == "data_unavailable"


def test_all_taxonomy_buckets_present():
    pm = tp._per_modality_verdicts([])
    assert set(pm.keys()) == {
        "bulk_rna/cell_line",
        "bulk_rna/tumor",
        "bulk_protein_ms/cell_line",
        "bulk_protein_ms/tumor",
        "sc_rna/tumor",
        "sc_rna/normal",
        "protein_ihc/tumor",  # HPA antibody IHC protein-in-tumor (MS-independent; measured-unruled)
        "protein_ihc/normal",
    }
    # each bucket carries its two axes as explicit fields
    for m, s in tp.ALL_CONTEXTS:
        b = pm[tp._ctx_key(m, s)]
        assert b["measurement"] == m and b["sample_context"] == s


# --- drift guard: CARD_CONTEXT matches the card specs on BOTH axes ----------


def test_card_context_map_covers_all_skill_cards():
    """Every card in CARDS must have a (measurement, sample_context) entry (else it
    silently drops out of the per-bucket view)."""
    for cid in tp.CARDS:
        assert cid in tp.CARD_CONTEXT, f"{cid} missing from CARD_CONTEXT"


_CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")


def test_card_context_matches_target_contracts_specs():
    """Drift guard: CARD_CONTEXT must mirror the `measurement:` + `sample_context:`
    tags in the target-contracts card specs. Graceful-skips if target-contracts is not
    checked out alongside (isolated CI), mirroring the other cross-repo checks."""
    cards_dir = _CONTRACTS / "cards"
    if not cards_dir.is_dir():
        import pytest

        pytest.skip("target-contracts not checked out alongside")
    for cid, (measurement, sample_context) in tp.CARD_CONTEXT.items():
        spec_path = cards_dir / f"{cid}.card.yaml"
        assert spec_path.is_file(), f"card spec missing: {spec_path}"
        spec = yaml.safe_load(spec_path.read_text())
        assert spec.get("measurement") == measurement, (
            f"{cid}: CARD_CONTEXT measurement {measurement!r} != spec {spec.get('measurement')!r}"
        )
        assert spec.get("sample_context") == sample_context, (
            f"{cid}: CARD_CONTEXT sample_context {sample_context!r} != spec {spec.get('sample_context')!r}"
        )


def test_verdict_fn_discoverable_by_composer():
    assert hasattr(tp, "_verdict") or hasattr(tp, "_snapshot")


# --- tumor-RNA now moves the verdict (2026-08-04) -----------------


def test_tumor_rna_distribution_now_resolves_bucket_not_insufficient():
    """tumor-rna-distribution's rule was emitted by a live card but was
    NOT in the ladder, so bulk_rna/tumor resolved `insufficient` on real tumor-RNA data.
    Now it produces a real presence verdict in its bucket."""
    fired = [_fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_rna/tumor"]["verdict"] == "tumor_broadly_expressed"
    assert pm["bulk_rna/tumor"]["evidence_state"] == "measured"
    # and it resolves the collapsed verdict (was insufficient pre-fix)
    v, drv = tp._verdict(fired)
    assert v == "tumor_broadly_expressed"
    assert drv == "tumor-expression-broadly-high-supportive"


def test_tumor_rna_is_appended_below_the_cellline_backbone_byte_stable():
    """The new tumor-RNA rules rank BELOW every pre-existing measured expression rule, so a
    target firing BOTH a cell-line backbone rule and a tumor-RNA rule keeps its OLD verdict
    (byte-stability): the cell-line broadly-high still wins the collapsed spine."""
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
    ]
    v, drv = tp._verdict(fired)
    assert v == "broadly_high_expression"  # unchanged — backbone wins
    assert drv == "expression-broadly-high-supportive"


def test_tumor_presence_outranks_differential_down_read():
    """Absolute tumor PRESENCE (broadly_expressed) outranks the differential tumor-vs-adjacent
    DOWN read: a target present in tumors but modestly lower than adjacent normal is still
    PRESENT — the down signal is a selectivity concern for the modality lens, not an absence."""
    fired = [
        _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
        _fr("expression-modest-downregulation-opposing", "tumor-rna-vs-adjacent"),
    ]
    v, _ = tp._verdict(fired)
    assert v == "tumor_broadly_expressed"


def test_tumor_vs_adjacent_down_reads_now_in_ladder():
    """The tumor-vs-adjacent DOWN rules (previously excluded) now resolve rather than falling
    through to insufficient. Strong-down is the lowest measured tumor-RNA tier (ranks above
    the data_unavailable sink)."""
    v_strong, drv_s = tp._verdict([_fr("expression-strong-downregulation-degrader-killer", "tumor-rna-vs-adjacent")])
    assert v_strong == "strongly_downregulated_in_tumor" and drv_s is not None
    v_modest, _ = tp._verdict([_fr("expression-modest-downregulation-opposing", "tumor-rna-vs-adjacent")])
    assert v_modest == "modestly_downregulated_in_tumor"


# --- subtype scope elevated to the headline (2026-08-04) ----------


def _all_cards_with(subtype_summary):
    """_headline calls get_card_field for EVERY card in CARDS (raises KeyError on a missing id), so a
    headline test must supply the full roster. All empty except the subtype card under test."""
    return [
        {"card_id": cid, "summary": (subtype_summary if cid == "tumor-rna-distribution-by-subtype" else {})}
        for cid in tp.CARDS
    ]


def test_subtype_scope_surfaces_in_headline():
    """The subtype presence landscape (tumor-rna-distribution-by-subtype) is now in
    the headline/audit spine, not just a side table. One-directional facet — it does NOT touch the
    presence_verdict (byte-stable), only adds subtype_* context fields."""
    cards = _all_cards_with(
        {"subtype_axis_available": True, "n_subtypes_measured": 7, "n_subtypes_enriched": 2, "spotlight_subtype": None}
    )
    h = tp._headline(cards, [], ("insufficient", None))
    assert h["subtype_scope_available"] is True
    assert h["n_subtypes_measured"] == 7
    assert h["n_subtypes_enriched"] == 2
    # verdict is untouched by the subtype facet
    assert h["presence_verdict"] == "insufficient"


def test_subtype_scope_degrades_honestly_when_no_shard():
    """No assignment shard (non-COADREAD indication) → subtype_scope_available False, a NAMED gap
    surfaced in the spine rather than a silent omission."""
    cards = _all_cards_with(
        {"subtype_axis_available": False, "n_subtypes_measured": 0, "n_subtypes_enriched": 0, "spotlight_subtype": None}
    )
    h = tp._headline(cards, [], ("broadly_moderate_expression", "expression-broadly-moderate-neutral"))
    assert h["subtype_scope_available"] is False
    assert h["n_subtypes_measured"] == 0
    # presence_verdict still resolves from its own signal, unaffected
    assert h["presence_verdict"] == "broadly_moderate_expression"


# --- 2026-08-11 production review: verdict-integrity regressions ---


def test_protein_modest_down_is_reachable_G1_regression():
    """`protein-modestly-down-opposing` fires (intracellular-intrinsic.rules.yaml:2895) but
    had NO rung in _PROTEIN_RANK, so a MEASURED modest_down protein read collapsed to
    `insufficient` and the verdict `protein_modestly_downregulated` was UNREACHABLE. The
    contracts-side fix (the rule) landed; the skill-side rung never did — a cross-repo half-fix.
    Mirrors the RNA card's laddered `expression-modest-downregulation-opposing`."""
    fired = [_fr("protein-modestly-down-opposing", "tumor-protein-abundance-cptac")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_protein_ms/tumor"]["verdict"] == "protein_modestly_downregulated"
    assert pm["bulk_protein_ms/tumor"]["evidence_state"] == "measured"
    # collapsed spine resolves too (was `insufficient` pre-fix)
    v, drv = tp._verdict(fired)
    assert v == "protein_modestly_downregulated"
    assert drv == "protein-modestly-down-opposing"


def test_sc_normal_comparator_survives_cross_axis_veto_G2_regression():
    """`tvn-sc-normal-critical-organ-veto` is a tumor-SELECTIVITY veto that lives on the
    intracellular axis and keys the sc-normal-celltype-expression card THIS skill dispatches, so
    it FIRES inside tumor-presence and is tagged (sc_rna, normal) via CARD_CONTEXT. Because
    _per_modality_verdicts ranked the fired group BEFORE the comparator branch, the veto (absent
    from _SC_RNA_RANK) collapsed the (sc_rna, normal) COMPARATOR bucket to `insufficient` —
    erasing the normal-tissue comparator readout for exactly the critical-organ targets (FOLR1)
    where it matters. A comparator bucket must read its comparator field regardless of any
    cross-axis rule firing into its context."""
    fired = [_fr("tvn-sc-normal-critical-organ-veto", "sc-normal-celltype-expression")]
    cards = [{"card_id": "sc-normal-celltype-expression", "summary": {"sc_normal_expression_class": "HIGH_LIABILITY"}}]
    b = tp._per_modality_verdicts(fired, cards)["sc_rna/normal"]
    assert b["evidence_state"] == "comparator"
    assert b["verdict"] == "HIGH_LIABILITY"
    assert b["verdict"] != "insufficient"


def test_cellline_broadly_low_does_not_kill_tumor_present_G5_regression():
    """VERDICT-MOVING (pending sign-off): a target broadly-LOW across DepMap cell lines but
    broadly-HIGH in the actual TCGA tumor collapsed to the cell-line degrader-killer
    `broadly_low_expression` — a FALSE-NEGATIVE headline for a tumor-PRESENCE question, because
    the cell-line proxy (`expression-broadly-low-degrader-killer`) outranked the direct tumor
    reading (`tumor-expression-broadly-high-supportive`). The direct tumor-present read must win
    the collapsed spine; cell-line-low stays a legible per-bucket model/modality caveat."""
    fired = [
        _fr("expression-broadly-low-degrader-killer", "cellline-rna-distribution"),
        _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
    ]
    v, drv = tp._verdict(fired)
    assert v == "tumor_broadly_expressed"
    assert drv == "tumor-expression-broadly-high-supportive"
    # per-bucket, both readings stay legible (the taxonomy's whole point)
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_rna/cell_line"]["verdict"] == "broadly_low_expression"
    assert pm["bulk_rna/tumor"]["verdict"] == "tumor_broadly_expressed"

    # the coherent half of the fix: a non-informative tumor-vs-adjacent DIFFERENTIAL likewise must
    # not override a direct absolute tumor-present read in the collapsed spine.
    fired2 = [
        _fr("expression-call-not-informative-degrader-killer", "tumor-rna-vs-adjacent"),
        _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
    ]
    assert tp._verdict(fired2)[0] == "tumor_broadly_expressed"


def test_full_per_modality_golden_spine():
    """GOLDEN (2026-08-11 production review): a representative multi-modality fired-set that
    populates every card-backed bucket, snapshotted so any future ladder/bucket edit surfaces as
    an explicit diff. Deterministic + offline, so the skills-validate CI runs it. Guards the
    presence spine the way the 9 resolver gates are guarded by resolver_golden_snapshots.json."""
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("expression-strong-upregulation-supportive", "tumor-rna-vs-adjacent"),
        _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
        _fr("protein-abundance-broadly-high-supportive", "cellline-protein-abundance"),
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
        _fr("sc-expression-malignant-broadly-detected-supportive", "tumor-scrna-celltype-expression"),
    ]
    cards = [
        {"card_id": "sc-normal-celltype-expression", "summary": {"sc_normal_expression_class": "LOW_LIABILITY"}},
        {"card_id": "normal-tissue-liability", "summary": {"normal_tissue_breadth_class": "restricted"}},
        # HPA antibody IHC protein-in-tumor: surfaced as `measured` with NO rule (measured-unruled),
        # demonstrating the protein_ihc/tumor bucket populating the MS-independent protein leg.
        {"card_id": "hpa-pathology-cancer-ihc", "summary": {"protein_presence_class": "ihc_detected_high"}},
    ]
    pm = tp._per_modality_verdicts(fired, cards)
    assert {k: (v["verdict"], v["evidence_state"]) for k, v in pm.items()} == {
        "bulk_rna/cell_line": ("broadly_high_expression", "measured"),
        "bulk_rna/tumor": ("strongly_upregulated_in_tumor", "measured"),
        "bulk_protein_ms/cell_line": ("protein_broadly_high", "measured"),
        "bulk_protein_ms/tumor": ("protein_strongly_upregulated", "measured"),
        "sc_rna/tumor": ("sc_malignant_detected", "measured"),
        "sc_rna/normal": ("LOW_LIABILITY", "comparator"),
        "protein_ihc/tumor": ("ihc_detected_high", "measured"),  # HPA IHC, measured-unruled (no rule)
        "protein_ihc/normal": ("restricted", "comparator"),
    }
    # collapsed spine: the RNA backbone wins (byte-stable)
    assert tp._verdict(fired)[0] == "broadly_high_expression"


# --- 2026-08-11 production review: RNA tumor-elevation breadth surfaced ---


def test_rna_tumor_elevation_breadth_surfaced_in_headline_G3():
    """The parallel RNA tumor-elevation breadth layer (rna_tumor_elevation_breadth_class, 27
    indications) + breadth_layer_concordance are emitted by tumor-elevation-breadth but were never
    read by _headline — a dead sub-axis that silently discarded a measured RNA-elevation signal for
    the RNA-only indications CPTAC (10 cohorts) does not cover. Now surfaced as verdict-inert
    facets. `rna_only` concordance = protein-coverage-gap breadth, the decision-relevant case."""
    breadth = {
        "rna_tumor_elevation_breadth_class": "broadly_tumor_elevated",
        "rna_n_indications_elevated": 6,
        "rna_n_indications_tested": 20,
        "breadth_layer_concordance": "rna_only",
    }
    cards = [{"card_id": cid, "summary": (breadth if cid == "tumor-elevation-breadth" else {})} for cid in tp.CARDS]
    h = tp._headline(cards, [], ("insufficient", None))
    assert h["rna_tumor_elevation_breadth_class"] == "broadly_tumor_elevated"
    assert h["rna_tumor_elevation_n_indications_elevated"] == 6
    assert h["rna_tumor_elevation_n_indications_tested"] == 20
    assert h["breadth_layer_concordance"] == "rna_only"
    # verdict-inert: the RNA-breadth facet never moves presence_verdict
    assert h["presence_verdict"] == "insufficient"


# --- full-review verdict regressions (2026-08-13) --------------


def test_h2_measured_protein_positive_outranks_rna_killer():
    """A target broadly-LOW in cell-line RNA (a degrader-killer) but strongly-UP in tumor PROTEIN
    must collapse to the measured protein positive, NOT the RNA killer — a false-negative before the
    fix (the RNA killer sat above every protein rung)."""
    fired = [
        _fr("expression-broadly-low-degrader-killer", "cellline-rna-distribution"),
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
    ]
    verdict, drv = tp._verdict(fired)
    assert verdict == "protein_strongly_upregulated", (
        f"measured protein positive must outrank the cell-line-RNA killer; got {verdict!r}"
    )
    assert drv == "protein-strongly-up-supportive"


def test_h2_measured_sc_positive_outranks_protein_killer():
    """sc arm: a measured sc malignant-detected positive outranks a measured protein-absence
    killer (cell-line broadly_low)."""
    fired = [
        _fr("protein-abundance-broadly-low-degrader-killer", "cellline-protein-abundance"),
        _fr("sc-expression-malignant-broadly-detected-supportive", "tumor-scrna-celltype-expression"),
    ]
    verdict, _ = tp._verdict(fired)
    assert verdict == "sc_malignant_detected"


def test_h2_rna_positive_still_wins_over_protein_positive_bytestable():
    """Byte-stability: among POSITIVES, RNA remains the backbone (expr before protein), so an
    established positive-RNA verdict is unchanged."""
    fired = [
        _fr("expression-broadly-moderate-neutral", "cellline-rna-distribution"),
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
    ]
    verdict, _ = tp._verdict(fired)
    assert verdict == "broadly_moderate_expression"


def test_m3_not_informative_does_not_mask_protein_positive():
    """not_informative (a flat tumor-vs-adjacent COVERAGE gap) sinks below all measured, so it can
    never bury a measured protein positive in the collapse."""
    fired = [
        _fr("expression-call-not-informative-degrader-killer", "tumor-rna-vs-adjacent"),
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
    ]
    verdict, _ = tp._verdict(fired)
    assert verdict == "protein_strongly_upregulated"


def test_m3_not_informative_sinks_below_measured_negative():
    """not_informative also sinks below a measured NEGATIVE — a measured protein down-read is more
    informative than a flat RNA differential."""
    fired = [
        _fr("expression-call-not-informative-degrader-killer", "tumor-rna-vs-adjacent"),
        _fr("protein-strongly-down-opposing", "tumor-protein-abundance-cptac"),
    ]
    verdict, _ = tp._verdict(fired)
    assert verdict == "protein_strongly_downregulated"


def test_m3_not_informative_alone_still_reported():
    """This does not change the not_informative-ONLY case: with nothing measured to outrank it, the
    collapse still surfaces not_informative (from the gap tier)."""
    fired = [_fr("expression-call-not-informative-degrader-killer", "tumor-rna-vs-adjacent")]
    verdict, _ = tp._verdict(fired)
    assert verdict == "not_informative"


import pytest as _pytest  # noqa: E402


@_pytest.mark.parametrize("flat_class", ["not_significant", "small_effect", "ns"])
def test_m2_resolved_but_flat_cptac_bucket_is_measured(flat_class):
    """A resolved-but-flat CPTAC class (present, not tumor-elevated) marks the bulk_protein_ms/tumor
    bucket `measured` (protein_present_not_elevated), NOT data_unavailable — 'measured, flat' must not
    read as 'not measured'. These classes fire no rule (deliberately un-ruled), so the bucket is rescued
    off the resolved card directly. 2026-08-14: covers the split vocab (not_significant / small_effect)
    AND the legacy `ns` backward-compat key."""
    cards = [{"card_id": "tumor-protein-abundance-cptac", "summary": {"protein_expression_class": flat_class}}]
    pm = tp._per_modality_verdicts([], cards)  # fires nothing; no breadth either
    b = pm["bulk_protein_ms/tumor"]
    assert b["evidence_state"] == "measured", f"resolved {flat_class} must mark the bucket measured; got {b}"
    assert b["verdict"] == "protein_present_not_elevated"


def test_m2_no_resolved_cptac_stays_data_unavailable():
    """Guard: with NO cptac card resolved (truly not measured), the bucket stays data_unavailable —
    the rescue only fires on a genuinely resolved-but-unruled present read."""
    pm = tp._per_modality_verdicts([], cards=[])
    b = pm["bulk_protein_ms/tumor"]
    assert b["evidence_state"] == "data_unavailable"
    assert b["verdict"] == "data_unavailable"


# --- LENS-DISCORDANCE flag (2026-08-13 multi-pair review) --------------------
# Additive / verdict-inert legibility flag: True only when the collapsed headline is
# cell-line-anchored AND the tumor-tissue RNA lens reads a strictly HIGHER presence tier
# (the case where the one-word verdict UNDERSTATES tumor presence). presence_verdict itself
# is byte-stable — these tests assert the flag, never a verdict change.


def _lens_disc(fired):
    v, drv = tp._verdict(fired)
    return tp._headline_lens_discordance(drv, tp._per_modality_verdicts(fired))


def test_reanchor_resolves_the_cellline_moderate_but_tumor_broad_case():
    """EPCAM/FOLR1/KRAS pattern (cell-line broadly_moderate + tumor broadly-expressed). BEFORE the
    re-anchor the collapsed headline inherited the CELL-LINE lens (broadly_moderate) and the
    cell_line_vs_tumor_discordant flag fired to warn the one-word verdict understated tumor presence.
    AFTER the re-anchor the TUMOR lens wins the headline (tumor_broadly_expressed), so the case is now
    tumor-anchored and the flag is silent — the ladder now FIXES what the flag only FLAGGED. The flag
    thus becomes a standing invariant guard (a True here would mean the ladder regressed)."""
    fired = [
        _fr("expression-broadly-moderate-neutral", "cellline-rna-distribution"),
        _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
    ]
    v, _ = tp._verdict(fired)
    lens, discordant, direction = _lens_disc(fired)
    assert v == "tumor_broadly_expressed"  # re-anchor: tumor lens drives the headline
    assert lens == "bulk_rna/tumor"
    assert discordant is False  # nothing to flag — the headline reflects tumor tissue
    assert direction is None


def test_not_discordant_when_both_lenses_broad():
    """ERBB2/MET pattern: headline already broadly_high (tier 3); tumor tissue is the SAME
    tier, so the lenses agree → no flag (bidirectional check keys on tier inequality)."""
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
    ]
    lens, discordant, direction = _lens_disc(fired)
    assert lens == "bulk_rna/cell_line"
    assert discordant is False
    assert direction is None


def test_discordant_when_cell_line_overstates_tumor():
    """USP8/NSCLC pattern: cell-line RNA fires broadly_high (tier 3) while the tumor-tissue lens
    is only broadly_moderate (tier 2). The one-word headline OVER-states tumor presence — the
    bidirectional guard (INV-2) must flag it with direction=cell_line_overstates_tumor. The RAW
    ladder still collapses to broadly_high_expression (untouched); the cap lives in _headline."""
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr("tumor-expression-broadly-moderate-neutral", "tumor-rna-distribution"),
    ]
    v, _ = tp._verdict(fired)
    lens, discordant, direction = _lens_disc(fired)
    assert v == "broadly_high_expression"  # RAW ladder collapse is untouched
    assert lens == "bulk_rna/cell_line"
    assert discordant is True
    assert direction == "cell_line_overstates_tumor"


def test_not_discordant_when_headline_is_tumor_anchored():
    """CEACAM5 pattern: the headline already came from the TUMOR lens (strong upregulation),
    so there is nothing to flag even though the cell-line lens is lineage_restricted."""
    fired = [
        _fr("expression-lineage-restricted-supportive", "cellline-rna-distribution"),
        _fr("expression-strong-upregulation-supportive", "tumor-rna-vs-adjacent"),
    ]
    lens, discordant, direction = _lens_disc(fired)
    assert lens == "bulk_rna/tumor"
    assert discordant is False
    assert direction is None


def test_not_discordant_when_tumor_lens_unmeasured():
    """Target-only query: cell-line measured, tumor bucket data_unavailable → no tumor tier
    to compare, so the flag stays False (never fabricated off a missing lens)."""
    fired = [_fr("expression-broadly-moderate-neutral", "cellline-rna-distribution")]
    lens, discordant, direction = _lens_disc(fired)
    assert lens == "bulk_rna/cell_line"
    assert discordant is False
    assert direction is None


# --- single-cell detail surfacing (per-compartment / CAF / homogeneity) -----
def _cards_with_sc(sc_summary):
    """All declared cards, with the single-cell tumor card carrying `sc_summary` (the rich per-
    compartment object the method emits) so _headline's get_card_field reads resolve."""
    return [
        {"card_id": cid, "summary": (sc_summary if cid == "tumor-scrna-celltype-expression" else {})}
        for cid in tp.CARDS
    ]


def test_headline_surfaces_single_cell_compartment_caf_and_homogeneity():
    """The method computes a rich single-cell object (per-compartment detection + abundance, the CAF
    confounder, malignant homogeneity); the headline must surface it, not just the class + malignant
    fraction. Guards against the surfacing regressing to the old ~5-scalar view."""
    sc = {
        "sc_expression_class": "malignant_broadly_detected",
        "malignant_detection_fraction": 0.8886,
        "malignant_abundance_log1p_cp10k": 2.08,
        "tce_homogeneity_class": "homogeneous",
        "top_microenvironment_compartment": "stromal",
        "top_microenvironment_detection_fraction": 0.081,
        "caf_vs_malignant_class": "caf_low",
        "caf_detection_fraction": 0.081,
        "caf_compartment_available": True,
        "compartment_detection": {"malignant": 0.889, "stromal": 0.081},
        "per_compartment": [{"compartment": "malignant", "median_detection_fraction": 0.889}],
        "n_compartments_measured": 5,
        "n_donor_groups": 453,
        "n_datasets": 45,
    }
    fired = [_fr("sc-expression-malignant-broadly-detected-supportive", "tumor-scrna-celltype-expression")]
    h = tp._headline(cards=_cards_with_sc(sc), fired=fired, verdict_pair=tp._verdict(fired))
    assert h["sc_tce_homogeneity_class"] == "homogeneous"
    assert h["sc_caf_vs_malignant_class"] == "caf_low"
    assert h["sc_malignant_abundance_log1p_cp10k"] == 2.08
    assert h["sc_top_microenvironment_detection_fraction"] == 0.081
    assert h["sc_n_datasets"] == 45 and h["sc_n_compartments_measured"] == 5
    assert h["sc_compartment_detection"]["malignant"] == 0.889
    assert isinstance(h["sc_per_compartment"], list) and h["sc_per_compartment"]
    # and these flow into the synthesis facet the composed target-profile consumes
    facet = tp._synthesis_facet(cards=_cards_with_sc(sc), fired=fired, verdict_pair=tp._verdict(fired))
    assert facet["sc_tce_homogeneity_class"] == "homogeneous"
    assert facet["sc_caf_vs_malignant_class"] == "caf_low"


def test_headline_surfaces_sc_malignant_cell_and_donor_counts():
    """Follow-up: the total malignant CELLS (+ donors) behind the sc call are surfaced in the headline
    and synthesis facet, so a reader can tell a ~509k-cell COADREAD call from a thin pooled cube (the
    analysis-methods MIN_MALIGNANT_CELLS_TOTAL floor's companion legibility)."""
    sc = {
        "sc_expression_class": "malignant_broadly_detected",
        "malignant_detection_fraction": 0.72,
        "malignant_n_cells": 509919,
        "malignant_n_donors": 45,
    }
    fired = [_fr("sc-expression-malignant-broadly-detected-supportive", "tumor-scrna-celltype-expression")]
    h = tp._headline(cards=_cards_with_sc(sc), fired=fired, verdict_pair=tp._verdict(fired))
    assert h["sc_malignant_n_cells"] == 509919
    assert h["sc_malignant_n_donors"] == 45
    facet = tp._synthesis_facet(cards=_cards_with_sc(sc), fired=fired, verdict_pair=tp._verdict(fired))
    assert facet["sc_malignant_n_cells"] == 509919


def test_headline_summarizes_normal_essential_flags_to_top_n():
    """The bulky normal-tissue safety_essential_flags dict is summarized to a ranked top-N (readable)
    while the full dict is retained verbatim."""
    flags = {f"cell_type_{i}": (0.9 - i * 0.05) for i in range(20)}
    cards = [
        {
            "card_id": cid,
            "summary": ({"safety_essential_flags": flags} if cid == "sc-normal-celltype-expression" else {}),
        }
        for cid in tp.CARDS
    ]
    h = tp._headline(cards=cards, fired=[], verdict_pair=tp._verdict([]))
    top = h["sc_normal_top_essential_cell_types"]
    assert len(top) == 8 and top[0]["cell_type"] == "cell_type_0"  # ranked by detection desc
    assert top[0]["detection_fraction"] >= top[-1]["detection_fraction"]
    assert h["sc_normal_safety_essential_flags"] == flags  # full dict retained


# ── obs-2: evidence_state must not contradict a data_unavailable verdict ─────────────────────────
def test_data_unavailable_only_bucket_is_not_stamped_measured():
    """A bucket whose ONLY fired rungs are data-unavailable resolves to verdict=data_unavailable; its
    evidence_state must be `data_unavailable`, NOT `measured` (the self-contradictory pair seen on
    coverage-thin indications like SKCM: bulk_protein_ms/tumor + sc_rna/tumor)."""
    pm = tp._per_modality_verdicts([_fr("protein-data-unavailable-insufficient", "tumor-protein-abundance-cptac")])
    b = pm[tp._ctx_key("bulk_protein_ms", "tumor")]
    assert b["verdict"] == "data_unavailable"
    assert b["evidence_state"] == "data_unavailable"


def test_not_informative_stays_measured_not_demoted():
    """`not_informative` is a MEASURED-but-flat read (data present, effect flat), NOT a coverage gap — it
    must keep evidence_state=`measured` (only literal data_unavailable is demoted by obs-2)."""
    pm = tp._per_modality_verdicts([_fr("expression-call-not-informative-degrader-killer", "tumor-rna-vs-adjacent")])
    b = pm[tp._ctx_key("bulk_rna", "tumor")]
    assert b["verdict"] == "not_informative" and b["evidence_state"] == "measured"


def test_evidence_state_measured_never_pairs_with_data_unavailable_verdict():
    """Obs-2 invariant guard — the strict skill_report/decision schema does NOT catch this pair (pins
    allow any verdict string alongside any evidence_state enum), so pin it here: across a spread of
    synthetic fired-sets, no bucket may carry evidence_state=`measured` with verdict=`data_unavailable`."""
    firesets = [
        [_fr("protein-data-unavailable-insufficient", "tumor-protein-abundance-cptac")],
        [_fr("sc-expression-data-unavailable-insufficient", "tumor-scrna-celltype-expression")],
        [_fr("expression-broadly-high-supportive", "cellline-rna-distribution")],
        [
            _fr("expression-strong-upregulation-supportive", "tumor-rna-vs-adjacent"),
            _fr("protein-data-unavailable-insufficient", "tumor-protein-abundance-cptac"),
        ],
        [],
    ]
    for fired in firesets:
        for key, b in tp._per_modality_verdicts(fired).items():
            if b.get("evidence_state") == "measured":
                assert b.get("verdict") != "data_unavailable", (key, b)


# --- 2026-09-18 subset_high split (phase 2 of 3): the per-modality spine for the new rung ---


def _subset_split_spine(tumor_rna_rule_id):
    """The golden spine above, minus the tumor-vs-adjacent rung (which feeds the SAME bulk_rna/tumor
    bucket and out-ranks both tumor-expression rungs, so leaving it in would mask the bucket under test),
    parameterised on which tumor-expression rung fires. Returns the (bucket -> (verdict, state)) map plus
    the collapsed verdict."""
    fired = [
        _fr("expression-broadly-high-supportive", "cellline-rna-distribution"),
        _fr(tumor_rna_rule_id, "tumor-rna-distribution"),
        _fr("protein-abundance-broadly-high-supportive", "cellline-protein-abundance"),
        _fr("protein-strongly-up-supportive", "tumor-protein-abundance-cptac"),
        _fr("sc-expression-malignant-broadly-detected-supportive", "tumor-scrna-celltype-expression"),
    ]
    pm = tp._per_modality_verdicts(fired, [])
    return {k: (v["verdict"], v["evidence_state"]) for k, v in pm.items()}, tp._verdict(fired)[0]


def test_subset_high_rung_resolves_the_bulk_rna_tumor_bucket_not_insufficient():
    """GOLDEN, PAIRED. The new rung must populate `bulk_rna/tumor` as a MEASURED positive. Asserted as a
    DIFF against the broad rung on an otherwise byte-identical fired-set, so the only thing that moves is
    the one bucket — a single-sided snapshot would pass just as well against a bucket that had silently
    gone `insufficient`/`data_unavailable`, which is exactly the false-absence failure this rung exists to
    prevent (an unlisted rung is invisible, not low-ranked)."""
    broad_map, broad_collapsed = _subset_split_spine("tumor-expression-broadly-high-supportive")
    subset_map, subset_collapsed = _subset_split_spine("tumor-expression-subset-high-supportive")

    assert broad_map["bulk_rna/tumor"] == ("tumor_broadly_expressed", "measured")
    assert subset_map["bulk_rna/tumor"] == ("tumor_subset_high_expression", "measured")

    moved = {k for k in broad_map if broad_map[k] != subset_map.get(k)}
    assert moved == {"bulk_rna/tumor"}, f"exactly one bucket may move; these moved: {sorted(moved)}"
    assert broad_map.keys() == subset_map.keys(), "the bucket TAXONOMY must not change"

    # The collapsed spine is anchored by the cell-line rung in BOTH cases (rung 1, both-lenses-high), so
    # the headline word is byte-stable here — the subset information rides in the per-modality bucket.
    # `test_reanchor_flip_matrix.py` covers the compensating discordance flag for this same shape.
    assert broad_collapsed == subset_collapsed == "broadly_high_expression"
