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
    return {"measurement": measurement, "sample_context": sample_context,
            "verdict": verdict, "driving_rule_id": None, "evidence_state": evidence_state}


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
        "bulk_protein_ms/tumor": _bucket("bulk_protein_ms", "tumor", "data_unavailable",
                                         evidence_state="data_unavailable"),
    }
    conflict, _, buckets = tp._headline_conflict("tumor_broadly_expressed", pm)
    assert conflict is False and buckets == []


# ── abundance_floor_flag ───────────────────────────────────────────────────────────────────────
def _cards(**pct_by_card):
    """Minimal cards list carrying only allgene_percentile_class for the level-anchor cards."""
    return [{"card_id": cid, "summary": {"allgene_percentile_class": klass}}
            for cid, klass in pct_by_card.items()]


def test_abundance_floor_fires_on_bottom_decile_level_lens():
    """UNOPPOSED single-lens case: presence-positive, cell-line PROTEIN bottom-decile, and NO orthogonal
    protein contradiction (no ProCan / IHC in this minimal card set). A high RNA anchor does NOT override
    a protein floor (RNA != protein), so the HARD floor fires and names the low lens."""
    cards = _cards(**{"tumor-rna-distribution": "top_1pct",
                      "cellline-rna-distribution": "mid",
                      "cellline-protein-abundance": "bottom_decile"})
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed")
    assert flag == "present_low_abundance"
    assert [x["card_id"] for x in lenses] == ["cellline-protein-abundance"]
    assert lenses[0]["quorum"] == "single_lens_unopposed"


def test_abundance_floor_single_lens_demoted_by_orthogonal_protein():
    """QUORUM (P0): a LONE bottom-decile PROTEIN panel orthogonally contradicted by the 2nd protein
    platform (ProCan `mid`) is a detection-sensitivity artifact — demoted to the SOFT single-lens flag
    (still named + overriding evidence recorded), NOT a hard floor. This is the true EPCAM shape."""
    cards = _cards(**{"tumor-rna-distribution": "top_1pct",
                      "cellline-rna-distribution": "mid",
                      "cellline-protein-abundance": "bottom_decile",
                      "cellline-protein-abundance-procan": "mid"})
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed")
    assert flag == "present_low_abundance_single_lens"
    assert lenses[0]["card_id"] == "cellline-protein-abundance"
    assert lenses[0]["quorum"] == "single_lens_overridden"
    assert any("ProCan" in o for o in (lenses[0].get("overridden_by") or []))


def test_abundance_floor_multi_lens_stays_hard():
    """Two independent bottom-decile level lenses = genuine low abundance → HARD floor (multi_lens),
    never demoted regardless of orthogonal signals."""
    cards = _cards(**{"tumor-rna-distribution": "mid",
                      "cellline-rna-distribution": "bottom_decile",
                      "cellline-protein-abundance": "bottom_decile",
                      "cellline-protein-abundance-procan": "mid"})
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed")
    assert flag == "present_low_abundance"
    assert {x["quorum"] for x in lenses} == {"multi_lens"}


def test_abundance_floor_adequate_when_no_bottom_decile_level():
    cards = _cards(**{"tumor-rna-distribution": "top_1pct",
                      "cellline-rna-distribution": "mid",
                      "cellline-protein-abundance": "mid"})
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed")
    assert flag == "adequate_abundance" and lenses == []


# ── #980 surface-class anchor preference (Gygi TMT under-reads the surface/secreted class) ───────
def _ihc_card(klass):
    return {"card_id": "hpa-pathology-cancer-ihc", "summary": {"protein_presence_class": klass}}


def _procan_card(pct, klass="mid"):
    """ProCan card carrying BOTH the raw all-gene percentile (the surface re-anchor's ≥50 bar) and the
    coarse class (the general #965 orthogonal-contradiction check)."""
    return {"card_id": "cellline-protein-abundance-procan",
            "summary": {"allgene_percentile": pct, "allgene_percentile_class": klass}}


def test_surface_class_reanchors_lone_gygi_low_when_procan_at_least_median():
    """#980: for a SURFACE antigen, a lone Gygi bottom-decile whose ProCan reads ≥ median (raw pct ≥ 50)
    is a class under-read, not a floor → re-anchor to adequate (EPCAM 79.7 / CEACAM5 84.3 / MSLN 61.5 /
    TACSTD2 87.0). Contrast the non-surface path (next test), which stays the SOFT single-lens flag —
    the surface gate is the only difference."""
    cards = _cards(**{"tumor-rna-distribution": "top_1pct",
                      "cellline-rna-distribution": "mid",
                      "cellline-protein-abundance": "bottom_decile"}) + [_procan_card(79.7)]
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed", is_surface=True)
    assert flag == "adequate_abundance" and lenses == []


def test_non_surface_gygi_low_procan_recovers_stays_soft_flag_byte_stable():
    """The SAME cards WITHOUT the surface gate keep the general PR #965 behavior (SOFT single-lens flag) —
    proves the surface anchor is the ONLY behavior change (non-surface targets are byte-stable)."""
    cards = _cards(**{"tumor-rna-distribution": "top_1pct",
                      "cellline-rna-distribution": "mid",
                      "cellline-protein-abundance": "bottom_decile"}) + [_procan_card(79.7)]
    flag, _ = tp._abundance_floor(cards, "tumor_broadly_expressed", is_surface=False)
    assert flag == "present_low_abundance_single_lens"


def test_surface_class_does_NOT_rescue_folr1_shape_procan_below_median():
    """DON'T OVERSTATE (the issue's explicit caution): FOLR1 (ProCan 20.8 %ile) / DLL3 (25.7) are
    genuinely lower-abundance even on the better platform — a class-level `mid` check would wrongly rescue
    them. With the ≥50 RAW-percentile bar the surface re-anchor does NOT fire; it falls through to the
    general #965 path → SOFT single-lens flag (ProCan `mid` still contradicts the hard floor). So FOLR1
    keeps an honest low-abundance flag — neither a false `adequate` nor a spurious hard floor."""
    cards = _cards(**{"tumor-rna-distribution": "top_1pct",
                      "cellline-rna-distribution": "mid",
                      "cellline-protein-abundance": "bottom_decile"}) + [_procan_card(20.8)]
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed", is_surface=True)
    assert flag == "present_low_abundance_single_lens"
    assert lenses[0]["quorum"] == "single_lens_overridden"


def test_surface_class_ihc_high_carries_reanchor_when_procan_missing():
    """MUC1-class exception: Gygi low, ProCan absent/low, but IHC detected_high → the surface re-anchor
    still fires (antibody-IHC carries the abundance signal)."""
    cards = _cards(**{"tumor-rna-distribution": "top_1pct",
                      "cellline-rna-distribution": "mid",
                      "cellline-protein-abundance": "bottom_decile"}) + [_ihc_card("ihc_detected_high")]
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed", is_surface=True)
    assert flag == "adequate_abundance" and lenses == []


def test_surface_class_keeps_hard_floor_when_procan_also_bottom_decile_no_ihc():
    """A surface antigen bottom-decile on BOTH Gygi AND ProCan (raw pct absent → below bar) with no
    IHC-high is genuinely low on both platforms — no orthogonal contradiction, so the honest HARD floor
    stands (single_lens_unopposed)."""
    cards = _cards(**{"tumor-rna-distribution": "top_1pct",
                      "cellline-rna-distribution": "mid",
                      "cellline-protein-abundance": "bottom_decile",
                      "cellline-protein-abundance-procan": "bottom_decile"})
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed", is_surface=True)
    assert flag == "present_low_abundance"
    assert lenses[0]["quorum"] == "single_lens_unopposed"


def test_surface_class_does_not_rescue_a_multi_lens_low():
    """A surface antigen ALSO bottom-decile on an RNA level anchor (not just Gygi) is a genuine multi-lens
    low — the surface re-anchor (Gygi-only under-read) does NOT fire; the multi_lens HARD floor stands."""
    cards = _cards(**{"tumor-rna-distribution": "mid",
                      "cellline-rna-distribution": "bottom_decile",
                      "cellline-protein-abundance": "bottom_decile"}) + [_procan_card(79.7)]
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed", is_surface=True)
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
    cards = _cards(**{"tumor-rna-distribution": "bottom_decile",
                      "cellline-rna-distribution": "bottom_decile",
                      "cellline-protein-abundance": "bottom_decile"})
    for v in ("broadly_low_expression", "data_unavailable", "insufficient"):
        flag, lenses = tp._abundance_floor(cards, v)
        assert flag is None and lenses == []


def test_presence_positive_predicate_matches_partition():
    """_is_presence_positive must agree with the collapse's own positive tier (single source of truth):
    every rung _partition_measured calls a positive is presence-positive; every negative/gap is not."""
    pos, neg, gap = tp._partition_measured(tp._VERDICT_RANK)
    assert all(tp._is_presence_positive(v) for _, v in pos)
    assert all(not tp._is_presence_positive(v) for _, v in neg)
    assert all(not tp._is_presence_positive(v) for _, v in gap)
