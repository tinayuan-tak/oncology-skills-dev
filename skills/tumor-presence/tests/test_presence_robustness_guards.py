"""Robustness guards (2026-08-20, VERDICT-INERT). Two additive legibility facets on the presence
headline, unit-tested on the pure helpers (they never touch the collapsed spine):

  * presence_headline_conflict (_headline_conflict) — Principle 1: the positive-over-negative collapse
    can bury a MEASURED presence-negative (e.g. RNA broadly_high but CPTAC protein not_detected) under
    the one-word headline. The flag re-surfaces it. It must fire ONLY when the collapsed verdict is a
    presence-positive AND some other bucket is a MEASURED negative — never on a neutral (e.g. CPTAC
    `ns`/present-not-elevated) and never when the collapsed verdict is itself a negative/gap.

  * abundance_floor_flag (_abundance_floor) — Principle 2 (breadth != level): a presence-positive whose
    absolute abundance LEVEL reads bottom-decile in >=1 lens. The contrast-rank cards (CPTAC,
    RNA-vs-adjacent) are deliberately excluded — a low contrast rank is not low abundance.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_guards")


def _bucket(measurement, sample_context, verdict, evidence_state="measured"):
    return {
        "measurement": measurement,
        "sample_context": sample_context,
        "verdict": verdict,
        "driving_rule_id": None,
        "evidence_state": evidence_state,
    }


# ── presence_headline_conflict ─────────────────────────────────────────────────────────────────
def test_conflict_fires_when_measured_protein_absence_buried_under_rna_positive():
    """The canonical dangerous shape: RNA broadly_high (positive headline) while cell-line MS protein is a
    MEASURED `protein_broadly_low` (the only reachable protein-absence negative — `protein_not_detected`
    was retired, target-contracts #467). The collapse ranks the positive first, so the killer is invisible
    in the one-word verdict — the flag must fire and name the protein bucket."""
    pm = {
        "bulk_rna/cell_line": _bucket("bulk_rna", "cell_line", "broadly_high_expression"),
        "bulk_protein_ms/cell_line": _bucket("bulk_protein_ms", "cell_line", "protein_broadly_low"),
    }
    conflict, note, buckets = tp._headline_conflict("broadly_high_expression", pm)
    assert conflict is True
    assert buckets == ["bulk_protein_ms/cell_line"]
    assert note and "bulk_protein_ms/cell_line" in note


def test_conflict_silent_on_neutral_cptac_not_a_negative():
    """EPCAM/COADREAD shape: CPTAC `protein_present_not_elevated` (a measured NEUTRAL, not a killer).
    No conflict — the flag must not cry wolf on present-but-flat protein."""
    pm = {
        "bulk_rna/tumor": _bucket("bulk_rna", "tumor", "tumor_broadly_expressed"),
        "bulk_protein_ms/tumor": _bucket("bulk_protein_ms", "tumor", "protein_present_not_elevated"),
    }
    conflict, note, buckets = tp._headline_conflict("tumor_broadly_expressed", pm)
    assert conflict is False and note is None and buckets == []


def test_conflict_silent_when_headline_itself_negative_or_gap():
    """When the collapsed verdict is itself a negative (or a gap / insufficient), there is no buried
    killer to surface — the flag is only about a POSITIVE headline hiding a negative."""
    pm = {"bulk_rna/cell_line": _bucket("bulk_rna", "cell_line", "broadly_low_expression")}
    for v in ("broadly_low_expression", "data_unavailable", "insufficient", "not_informative"):
        conflict, note, buckets = tp._headline_conflict(v, pm)
        assert conflict is False and buckets == []


def test_conflict_ignores_unmeasured_negative_lookalike():
    """A data_unavailable bucket is a coverage GAP, never a measured negative — it must not trip the
    conflict flag even under a positive headline."""
    pm = {
        "bulk_rna/tumor": _bucket("bulk_rna", "tumor", "tumor_broadly_expressed"),
        "bulk_protein_ms/tumor": _bucket(
            "bulk_protein_ms", "tumor", "data_unavailable", evidence_state="data_unavailable"
        ),
    }
    conflict, _, buckets = tp._headline_conflict("tumor_broadly_expressed", pm)
    assert conflict is False and buckets == []


# ── abundance_floor_flag ───────────────────────────────────────────────────────────────────────
def _cards(**pct_by_card):
    """Minimal cards list carrying only allgene_percentile_class for the level-anchor cards."""
    return [{"card_id": cid, "summary": {"allgene_percentile_class": klass}} for cid, klass in pct_by_card.items()]


def _pm(verdict, rule_id="tumor-expression-broadly-high-supportive"):
    """Minimal per-modality MATRIX holding ONE ladder bucket (driving_rule_id set) at `verdict`.

    `_abundance_floor` reads its positivity gate from this matrix, not from the Route-A collapsed
    scalar (SK#1984 Stage-2 thinning, Step 2a). `driving_rule_id` must be truthy — a comparator /
    measured-unruled bucket fires no ladder rung and is excluded from the gate by design."""
    return {
        "bulk_rna/tumor": {
            "measurement": "bulk_rna",
            "sample_context": "tumor",
            "verdict": verdict,
            "driving_rule_id": rule_id,
            "evidence_state": "measured",
        }
    }


def test_abundance_floor_fires_on_bottom_decile_level_lens():
    """UNOPPOSED single-lens case: presence-positive, cell-line PROTEIN bottom-decile, and NO orthogonal
    protein contradiction (no ProCan / IHC in this minimal card set). A high RNA anchor does NOT override
    a protein floor (RNA != protein), so the HARD floor fires and names the low lens."""
    cards = _cards(
        **{
            "tumor-rna-distribution": "top_1pct",
            "cellline-rna-distribution": "mid",
            "cellline-protein-abundance": "bottom_decile",
        }
    )
    flag, lenses = tp._abundance_floor(cards, _pm("tumor_broadly_expressed"))
    assert flag == "present_low_abundance"
    assert [x["card_id"] for x in lenses] == ["cellline-protein-abundance"]
    assert lenses[0]["quorum"] == "single_lens_unopposed"


def test_abundance_floor_single_lens_demoted_by_orthogonal_protein():
    """QUORUM (P0): a LONE bottom-decile PROTEIN panel orthogonally contradicted by the 2nd protein
    platform (ProCan `mid`) is a detection-sensitivity artifact — demoted to the SOFT single-lens flag
    (still named + overriding evidence recorded), NOT a hard floor. This is the true EPCAM shape."""
    cards = _cards(
        **{
            "tumor-rna-distribution": "top_1pct",
            "cellline-rna-distribution": "mid",
            "cellline-protein-abundance": "bottom_decile",
            "cellline-protein-abundance-procan": "mid",
        }
    )
    flag, lenses = tp._abundance_floor(cards, _pm("tumor_broadly_expressed"))
    assert flag == "present_low_abundance_single_lens"
    assert lenses[0]["card_id"] == "cellline-protein-abundance"
    assert lenses[0]["quorum"] == "single_lens_overridden"
    assert any("ProCan" in o for o in (lenses[0].get("overridden_by") or []))


def test_abundance_floor_multi_lens_stays_hard():
    """Two independent bottom-decile level lenses = genuine low abundance → HARD floor (multi_lens),
    never demoted regardless of orthogonal signals."""
    cards = _cards(
        **{
            "tumor-rna-distribution": "mid",
            "cellline-rna-distribution": "bottom_decile",
            "cellline-protein-abundance": "bottom_decile",
            "cellline-protein-abundance-procan": "mid",
        }
    )
    flag, lenses = tp._abundance_floor(cards, _pm("tumor_broadly_expressed"))
    assert flag == "present_low_abundance"
    assert {x["quorum"] for x in lenses} == {"multi_lens"}


def test_abundance_floor_adequate_when_no_bottom_decile_level():
    cards = _cards(
        **{
            "tumor-rna-distribution": "top_1pct",
            "cellline-rna-distribution": "mid",
            "cellline-protein-abundance": "mid",
        }
    )
    flag, lenses = tp._abundance_floor(cards, _pm("tumor_broadly_expressed"))
    assert flag == "adequate_abundance" and lenses == []


# ── #980 surface-class anchor preference (Gygi TMT under-reads the surface/secreted class) ───────
def _ihc_card(klass):
    return {"card_id": "hpa-pathology-cancer-ihc", "summary": {"protein_presence_class": klass}}


def _procan_card(pct, klass="mid"):
    """ProCan card carrying BOTH the raw all-gene percentile (the surface re-anchor's ≥50 bar) and the
    coarse class (the general #965 orthogonal-contradiction check)."""
    return {
        "card_id": "cellline-protein-abundance-procan",
        "summary": {"allgene_percentile": pct, "allgene_percentile_class": klass},
    }


def test_surface_class_reanchors_lone_gygi_low_when_procan_at_least_median():
    """#980: for a SURFACE antigen, a lone Gygi bottom-decile whose ProCan reads ≥ median (raw pct ≥ 50)
    is a class under-read, not a floor → re-anchor to adequate (EPCAM 79.7 / CEACAM5 84.3 / MSLN 61.5 /
    TACSTD2 87.0). Contrast the non-surface path (next test), which stays the SOFT single-lens flag —
    the surface gate is the only difference."""
    cards = _cards(
        **{
            "tumor-rna-distribution": "top_1pct",
            "cellline-rna-distribution": "mid",
            "cellline-protein-abundance": "bottom_decile",
        }
    ) + [_procan_card(79.7)]
    flag, lenses = tp._abundance_floor(cards, _pm("tumor_broadly_expressed"), is_surface=True)
    assert flag == "adequate_abundance" and lenses == []


def test_non_surface_gygi_low_procan_recovers_stays_soft_flag_byte_stable():
    """The SAME cards WITHOUT the surface gate keep the general PR #965 behavior (SOFT single-lens flag) —
    proves the surface anchor is the ONLY behavior change (non-surface targets are byte-stable)."""
    cards = _cards(
        **{
            "tumor-rna-distribution": "top_1pct",
            "cellline-rna-distribution": "mid",
            "cellline-protein-abundance": "bottom_decile",
        }
    ) + [_procan_card(79.7)]
    flag, _ = tp._abundance_floor(cards, _pm("tumor_broadly_expressed"), is_surface=False)
    assert flag == "present_low_abundance_single_lens"


def test_surface_class_does_NOT_rescue_folr1_shape_procan_below_median():
    """DON'T OVERSTATE (the issue's explicit caution): FOLR1 (ProCan 20.8 %ile) / DLL3 (25.7) are
    genuinely lower-abundance even on the better platform — a class-level `mid` check would wrongly rescue
    them. With the ≥50 RAW-percentile bar the surface re-anchor does NOT fire; it falls through to the
    general #965 path → SOFT single-lens flag (ProCan `mid` still contradicts the hard floor). So FOLR1
    keeps an honest low-abundance flag — neither a false `adequate` nor a spurious hard floor."""
    cards = _cards(
        **{
            "tumor-rna-distribution": "top_1pct",
            "cellline-rna-distribution": "mid",
            "cellline-protein-abundance": "bottom_decile",
        }
    ) + [_procan_card(20.8)]
    flag, lenses = tp._abundance_floor(cards, _pm("tumor_broadly_expressed"), is_surface=True)
    assert flag == "present_low_abundance_single_lens"
    assert lenses[0]["quorum"] == "single_lens_overridden"


def test_surface_class_ihc_high_carries_reanchor_when_procan_missing():
    """MUC1-class exception: Gygi low, ProCan absent/low, but IHC detected_high → the surface re-anchor
    still fires (antibody-IHC carries the abundance signal)."""
    cards = _cards(
        **{
            "tumor-rna-distribution": "top_1pct",
            "cellline-rna-distribution": "mid",
            "cellline-protein-abundance": "bottom_decile",
        }
    ) + [_ihc_card("ihc_detected_high")]
    flag, lenses = tp._abundance_floor(cards, _pm("tumor_broadly_expressed"), is_surface=True)
    assert flag == "adequate_abundance" and lenses == []


def test_surface_class_keeps_hard_floor_when_procan_also_bottom_decile_no_ihc():
    """A surface antigen bottom-decile on BOTH Gygi AND ProCan (raw pct absent → below bar) with no
    IHC-high is genuinely low on both platforms — no orthogonal contradiction, so the honest HARD floor
    stands (single_lens_unopposed)."""
    cards = _cards(
        **{
            "tumor-rna-distribution": "top_1pct",
            "cellline-rna-distribution": "mid",
            "cellline-protein-abundance": "bottom_decile",
            "cellline-protein-abundance-procan": "bottom_decile",
        }
    )
    flag, lenses = tp._abundance_floor(cards, _pm("tumor_broadly_expressed"), is_surface=True)
    assert flag == "present_low_abundance"
    assert lenses[0]["quorum"] == "single_lens_unopposed"


def test_surface_class_does_not_rescue_a_multi_lens_low():
    """A surface antigen ALSO bottom-decile on an RNA level anchor (not just Gygi) is a genuine multi-lens
    low — the surface re-anchor (Gygi-only under-read) does NOT fire; the multi_lens HARD floor stands."""
    cards = _cards(
        **{
            "tumor-rna-distribution": "mid",
            "cellline-rna-distribution": "bottom_decile",
            "cellline-protein-abundance": "bottom_decile",
        }
    ) + [_procan_card(79.7)]
    flag, lenses = tp._abundance_floor(cards, _pm("tumor_broadly_expressed"), is_surface=True)
    assert flag == "present_low_abundance"
    assert {x["quorum"] for x in lenses} == {"multi_lens"}


def test_surface_secreted_vocab_loads_expected_members():
    """The curated vocab loads and covers the issue panel (EPCAM incl. — biology_axis_curated MISSES it)
    without over-claiming a cytoplasmic control."""
    from _skills_common._live_readers import _load_surface_secreted_antigens

    v = _load_surface_secreted_antigens()
    assert {"EPCAM", "CEACAM5", "FOLR1", "MSLN", "TACSTD2", "DLL3", "MUC1"} <= v
    assert "KRAS" not in v and "ACTB" not in v


def test_abundance_floor_none_when_not_positive():
    """A negative / gap / insufficient headline gets no abundance-floor read (nothing to qualify)."""
    cards = _cards(
        **{
            "tumor-rna-distribution": "bottom_decile",
            "cellline-rna-distribution": "bottom_decile",
            "cellline-protein-abundance": "bottom_decile",
        }
    )
    # A matrix whose only ladder bucket is a measured-negative / gap read is non-positive → gated out.
    for v in ("broadly_low_expression", "data_unavailable", "insufficient"):
        flag, lenses = tp._abundance_floor(cards, _pm(v))
        assert flag is None and lenses == []
    # And an EMPTY / all-non-ladder matrix is likewise non-positive (nothing to qualify).
    assert tp._abundance_floor(cards, {}) == (None, [])
    assert tp._abundance_floor(
        cards, {"protein_ihc/tumor": {"verdict": "ihc_detected_high", "driving_rule_id": None}}
    ) == (None, [])


def test_presence_positive_predicate_matches_partition():
    """_is_presence_positive must agree with the collapse's own positive tier (single source of truth):
    every rung _partition_measured calls a positive is presence-positive; every negative/gap is not."""
    pos, neg, gap = tp._partition_measured(tp._VERDICT_RANK)
    assert all(tp._is_presence_positive(v) for _, v in pos)
    assert all(not tp._is_presence_positive(v) for _, v in neg)
    assert all(not tp._is_presence_positive(v) for _, v in gap)


# ── SK#1984 Stage-2 thinning, Step 2a: matrix-derived positivity gate ────────────────────────────
def test_any_modality_presence_positive_reads_only_ladder_buckets():
    """The rule-free gate now feeding _abundance_floor is True iff SOME LADDER bucket (driving_rule_id
    set) is presence-positive, and it IGNORES comparator / measured-unruled buckets (driving_rule_id
    None) — those fire no ladder rung and never entered the collapse."""
    assert tp._any_modality_presence_positive(_pm("tumor_broadly_expressed")) is True
    assert tp._any_modality_presence_positive(_pm("broadly_low_expression")) is False  # measured-negative
    assert tp._any_modality_presence_positive(_pm("data_unavailable")) is False  # coverage gap
    assert tp._any_modality_presence_positive({}) is False
    assert tp._any_modality_presence_positive(None) is False
    # A comparator/unruled bucket whose token would pass _is_presence_positive must NOT count as positive
    # (driving_rule_id None → excluded) — otherwise a normal-tissue HIGH_LIABILITY or IHC-detected read
    # would spuriously gate the tumor abundance floor open.
    assert (
        tp._any_modality_presence_positive(
            {
                "sc_rna/normal": {"verdict": "HIGH_LIABILITY", "driving_rule_id": None},
                "protein_ihc/tumor": {"verdict": "ihc_detected_high", "driving_rule_id": None},
            }
        )
        is False
    )
    # …but a positive ladder bucket alongside those non-ladder buckets DOES count.
    mixed = {"protein_ihc/normal": {"verdict": "broad_normal_expression", "driving_rule_id": None}}
    mixed.update(_pm("tumor_broadly_expressed"))
    assert tp._any_modality_presence_positive(mixed) is True


# A representative card_id per ladder measurement, so a fired rung lands in the right matrix bucket
# (CARD_CONTEXT keys buckets off card_id; _rank_verdict then ranks within that measurement's ladder).
_MEAS_CARD = {
    "bulk_rna": "tumor-rna-distribution",
    "bulk_protein_ms": "tumor-protein-abundance-cptac",
    "sc_rna": "tumor-scrna-celltype-expression",
}
_RUNG_MEAS = {
    **{rid: "bulk_rna" for rid, _ in tp._EXPRESSION_RANK},
    **{rid: "bulk_protein_ms" for rid, _ in tp._PROTEIN_RANK},
    **{rid: "sc_rna" for rid, _ in tp._SC_RNA_RANK},
}


def test_matrix_gate_equals_collapsed_scalar_gate_over_fired_sets():
    """Behavioural equivalence (the whole point of Step 2a): for any fired set, reading presence-
    positivity from the per-modality MATRIX is byte-identical to reading it from the collapsed scalar
    `_verdict(fired)`. Adversarial coverage: each single ladder rung, plus mixed positive+negative pairs
    across measurements (where a within-bucket ladder that was NOT positive-first could diverge)."""
    all_rungs = [rid for rid, _ in tp._VERDICT_RANK]
    singles = [[r] for r in all_rungs]
    # mixed pairs: one positive rung + one negative/gap rung (the divergence-prone shape)
    pos_rids = [rid for rid, v in tp._VERDICT_RANK if tp._is_presence_positive(v)]
    neg_rids = [
        rid for rid, v in tp._VERDICT_RANK if v in tp._MEASURED_NEGATIVE_VERDICTS or v in tp._COLLAPSE_GAP_VERDICTS
    ]
    pairs = [[p, n] for p in pos_rids[:6] for n in neg_rids]
    for combo in singles + pairs + [[], all_rungs]:
        fired = [_fr(r) for r in combo]
        collapsed, _ = tp._verdict(fired)
        per_modality = tp._per_modality_verdicts(fired)
        assert tp._any_modality_presence_positive(per_modality) == tp._is_presence_positive(collapsed), (
            f"gate divergence for fired={combo}: matrix={per_modality} vs collapsed={collapsed!r}"
        )


# ── obs-1: WITHIN-bucket buried measured-negative ────────────────────────────────────────────────
def _fr(rule_id, card_id=None):
    # card_id defaults to a representative card in the rung's ladder measurement, so the rung buckets
    # correctly in _per_modality_verdicts (CARD_CONTEXT keys off card_id); pass it explicitly to place
    # a rung in a specific (measurement, sample_context) bucket.
    return {
        "rule_id": rule_id,
        "card_id": card_id or _MEAS_CARD[_RUNG_MEAS[rule_id]],
        "field": "x",
        "value": "y",
        "signals": {},
    }


def test_conflict_surfaces_within_bucket_buried_negative():
    """Obs-1 (KRAS shape): a measured presence-NEGATIVE that fired in the SAME bucket as a stronger
    co-fired positive is out-ranked WITHIN the bucket, so per_modality (winner-only) hides it and the
    cross-bucket scan never sees it. `tumor-rna-vs-adjacent` modestly_downregulated + `tumor-rna-
    distribution` broadly-high both live in bulk_rna/tumor. Passing `fired` must surface the buried
    negative on presence_headline_conflict."""
    fired = [
        _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution"),
        _fr("expression-modest-downregulation-opposing", "tumor-rna-vs-adjacent"),
    ]
    pm = tp._per_modality_verdicts(fired)
    # the bucket winner is the positive (no cross-bucket negative anywhere)
    assert tp._is_presence_positive(pm[tp._ctx_key("bulk_rna", "tumor")]["verdict"])
    conflict, note, buried = tp._headline_conflict("tumor_broadly_expressed", pm, fired)
    assert conflict is True
    assert any("tumor-rna-vs-adjacent" in b and "modestly_downregulated_in_tumor" in b for b in buried)
    # backward-compat: without `fired` the within-bucket scan can't run → no conflict here
    assert tp._headline_conflict("tumor_broadly_expressed", pm)[0] is False


def test_within_bucket_scan_silent_when_no_co_fired_positive():
    """A bucket with ONLY a measured-negative (no co-fired positive) is a real bucket-negative the
    cross-bucket scan already handles — the within-bucket helper must NOT double-report it."""
    fired = [_fr("expression-modest-downregulation-opposing", "tumor-rna-vs-adjacent")]
    assert tp._within_bucket_buried_negatives(fired) == []
