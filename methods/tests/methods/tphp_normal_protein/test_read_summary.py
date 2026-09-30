"""Credential-less tests for the TPHP normal-tissue-protein reader.

No S3: a synthetic local long/tidy parquet (the derived product's schema — gene_symbol, uniprot_ac,
tissue, tissue_class, median_log2_abundance, median_intensity, n_samples, n_detected,
detection_rate) is read via the `product_path` offline seam. Pins:
  * the emitted summary carries EVERY field the normal-tissue-protein-abundance-tphp card declares
    (the reader-real-field-names drift class the tumor-selectivity replay exists to catch);
  * breadth class is computed on the ADULT tissue count (broad / moderate / restricted reachable);
  * fetal-vs-adult flag + highest-abundance tissue + max/median aggregates are correct;
  * a gene with NO rows → data_unavailable (a genuine coverage gap, absence discipline);
  * a genuine 404-class fault → data_unavailable + _live_read_error (never crashes the compose path);
  * a transient/creds error is RE-RAISED (never masked as an empty normal footprint).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

read = importlib.import_module("onc_methods.tphp_normal_protein.read")

# The fields the normal-tissue-protein-abundance-tphp card declares in outputs.summary_fields — the
# reader MUST emit all of them (the drift guard). Kept explicit so a card/reader divergence fails HERE.
_CARD_SUMMARY_FIELDS = {
    "normal_protein_breadth_class",
    "tphp_normal_protein_liability_class",
    "n_adult_tissues_above_abundance_floor",
    "abundance_floor_log2",
    "n_tissues_detected",
    "n_adult_tissues_detected",
    "n_fetal_groups_detected",
    "n_adult_tissues_total",
    "n_fetal_groups_total",
    "max_median_log2_abundance",
    "median_across_tissues_log2_abundance",
    "highest_abundance_tissue",
    "highest_abundance_tissue_class",
    "fetal_vs_adult_flag",
    "max_detection_rate",
    "uniprot_ac",
    "per_tissue_abundance",
    "method_version",
}
_BREADTH_VOCAB = {
    "broad_normal_protein",
    "moderate_normal_protein",
    "restricted_normal_protein",
    "not_detected_in_normal_protein",
    "data_unavailable",
}
_LIABILITY_VOCAB = {"broad_and_abundant", "detected_not_abundant", "restricted", "data_unavailable"}
_FETAL_VOCAB = {"adult_and_fetal", "adult_only", "fetal_only", "none", "data_unavailable"}

# Fields the reader emits from the v2 substrate that the CARD DOES NOT DECLARE YET (the contracts-side
# leg of this change adds them to outputs.summary_fields). Kept as a SEPARATE set from
# _CARD_SUMMARY_FIELDS on purpose: merging them would hide the fact that reader and card have diverged,
# and _CARD_SUMMARY_FIELDS is asserted as a SUBSET, so a merge would silently pass either way.
_V2_DECLARATION_FIELDS = {
    "n_solid_adult_tissues_detected",
    "n_solid_adult_tissues_above_abundance_floor",
    "n_solid_adult_tissues_total",
    "n_adult_tissues_detected_low_support",
    "n_vital_organs_measurable",
    "n_vital_organs_unmeasurable",
    "vital_organ_min_samples",
}

# HPA-blind vital-organ view (skills #1793) — emitted by the reader; declared on the card by the
# target-contracts leg of the same arc. The CLASS is verdict-bearing there (safety-resolver rung).
_HPA_BLIND_FIELDS = {
    "tphp_hpa_blind_vital_organ_liability_class",
    "n_hpa_blind_vital_organs_above_abundance_floor",
    "hpa_blind_vital_organs_above_floor",
    "hpa_blind_vital_organs_uncovered",
}

_COLS = [
    "gene_symbol",
    "uniprot_ac",
    "tissue",
    "tissue_class",
    "tissue_category",
    "median_log2_abundance",
    "median_intensity",
    "n_samples",
    "n_detected",
    "detection_rate",
]
# A v1-shaped product (no tissue_category) — the reader must still work, defaulting fail-OPEN to solid.
_COLS_V1 = [c for c in _COLS if c != "tissue_category"]


def _write_product(tmp_path, rows, cols=None, name="tphp_normal.parquet") -> Path:
    """rows: list of dicts (product schema). Writes a synthetic long/tidy parquet."""
    cols = cols or _COLS
    df = pd.DataFrame(rows, columns=cols)
    p = tmp_path / name
    df.to_parquet(p, index=False)
    return p


def _row(
    gene,
    tissue,
    tclass,
    log2,
    det_rate=1.0,
    n_samples=5,
    n_detected=5,
    uac="P00533",
    tissue_category="solid_tissue",
):
    return {
        "gene_symbol": gene,
        "uniprot_ac": uac,
        "tissue": tissue,
        "tissue_class": tclass,
        "tissue_category": tissue_category,
        "median_log2_abundance": log2,
        "median_intensity": 2.0**log2,
        "n_samples": n_samples,
        "n_detected": n_detected,
        "detection_rate": det_rate,
    }


def test_summary_shape_matches_card_and_aggregates(tmp_path):
    # EGFR detected in 12 adult tissues (moderate) + 1 fetal group; highest = liver at 9.0.
    rows = [_row("EGFR", f"adult_tissue_{i:02d}", "adult_normal", 3.0 + 0.1 * i) for i in range(12)]
    rows.append(_row("EGFR", "liver", "adult_normal", 9.0))  # the top adult tissue
    rows.append(_row("EGFR", "ectoderm", "fetal", 4.0, det_rate=0.5))
    # a background gene so the pushdown must actually filter on gene_symbol
    rows += [_row("BRAF", f"adult_tissue_{i:02d}", "adult_normal", 1.0) for i in range(3)]
    prod = _write_product(tmp_path, rows)

    out = read.read_target_summary("EGFR", indication="COADREAD", product_path=prod)

    missing = _CARD_SUMMARY_FIELDS - set(out)
    assert not missing, f"reader is missing card-declared summary_fields: {sorted(missing)}"
    assert out["normal_protein_breadth_class"] in _BREADTH_VOCAB
    assert out["tphp_normal_protein_liability_class"] in _LIABILITY_VOCAB
    assert out["fetal_vs_adult_flag"] in _FETAL_VOCAB
    # 13 adult tissues (12 + liver) → moderate (>=10, <35); 1 fetal group.
    assert out["n_adult_tissues_detected"] == 13
    assert out["n_fetal_groups_detected"] == 1
    assert out["n_tissues_detected"] == 14
    assert out["normal_protein_breadth_class"] == "moderate_normal_protein"
    assert out["fetal_vs_adult_flag"] == "adult_and_fetal"
    assert out["highest_abundance_tissue"] == "liver"
    assert out["highest_abundance_tissue_class"] == "adult_normal"
    assert out["max_median_log2_abundance"] == 9.0
    assert out["uniprot_ac"] == "P00533"
    assert out["n_adult_tissues_total"] == read.N_ADULT_TISSUES_TOTAL
    # the display list is sorted by abundance descending and only carries EGFR rows
    assert out["per_tissue_abundance"][0]["tissue"] == "liver"
    assert len(out["per_tissue_abundance"]) == 14
    assert out["method_version"] == read.METHOD_VERSION


def test_broad_breadth_reachable(tmp_path):
    """Detected in >=35 adult tissues → broad_normal_protein (a housekeeping-like broad footprint —
    the on-target-off-tumor liability the tumor-selectivity comparator surfaces)."""
    rows = [_row("ACTB", f"adult_tissue_{i:02d}", "adult_normal", 8.0) for i in range(40)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("ACTB", product_path=prod)
    assert out["normal_protein_breadth_class"] == "broad_normal_protein"
    assert out["fetal_vs_adult_flag"] == "adult_only"


def test_restricted_breadth_reachable(tmp_path):
    rows = [_row("DLL3", "brain", "adult_normal", 5.0), _row("DLL3", "testis", "adult_normal", 4.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("DLL3", product_path=prod)
    assert out["normal_protein_breadth_class"] == "restricted_normal_protein"
    assert out["n_adult_tissues_detected"] == 2


def test_fetal_only_is_not_detected_in_adult(tmp_path):
    rows = [_row("MAGEA3", "endoderm", "fetal", 6.0), _row("MAGEA3", "mesoderm", "fetal", 5.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("MAGEA3", product_path=prod)
    assert out["normal_protein_breadth_class"] == "not_detected_in_normal_protein"
    assert out["fetal_vs_adult_flag"] == "fetal_only"
    assert out["n_adult_tissues_detected"] == 0
    assert out["n_fetal_groups_detected"] == 2


def test_gene_absent_is_data_unavailable(tmp_path):
    rows = [_row("EGFR", "liver", "adult_normal", 9.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("GHOSTGENE", product_path=prod)
    assert out["normal_protein_breadth_class"] == "data_unavailable"
    assert out["fetal_vs_adult_flag"] == "data_unavailable"
    assert out["per_tissue_abundance"] == []
    assert out["max_median_log2_abundance"] is None
    # the gap path still emits every card-declared field (headline/display read via get → None safely)
    assert _CARD_SUMMARY_FIELDS <= set(out)


def test_definitive_absence_degrades_not_crashes(monkeypatch):
    """A genuine 404-class fault → data_unavailable + _live_read_error (honest degrade)."""

    def _boom(*a, **k):
        raise FileNotFoundError("no such key")

    monkeypatch.setattr(read, "load_and_classify", _boom)
    out = read.read_target_summary("EGFR", indication="COADREAD")
    assert out["_live_read_error"] == "tphp_normal_protein_read_failed"
    assert out["normal_protein_breadth_class"] == "data_unavailable"
    assert out["method_version"] == read.METHOD_VERSION


def test_transient_fault_is_reraised(monkeypatch):
    """A transient / non-definitive error must NOT be masked as an empty normal footprint — re-raise
    so the live-read seam surfaces the infra failure (absence discipline)."""

    def _boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(read, "load_and_classify", _boom)
    with pytest.raises(RuntimeError):
        read.read_target_summary("EGFR")


# ── tphp_normal_protein_liability_class (Floor-C abundance gate) ─────────────────────────────────
# broad_and_abundant := (# adult tissues with median_log2_abundance >= ABUNDANCE_FLOOR_LOG2) >=
# BROAD_ABUNDANT_TISSUE_COUNT. This is gated on ABUNDANCE-across-breadth, NOT DIA detection: the whole
# point is that a broadly-DETECTED-but-not-broadly-abundant protein (CEACAM5 archetype: many tissues
# detected, only a few — often a single origin/outlier tissue — abundant) does NOT read broad_and_abundant.
_FLOOR = read.ABUNDANCE_FLOOR_LOG2
_BROAD_ABUND = read.BROAD_ABUNDANT_TISSUE_COUNT


def test_housekeeping_broad_and_abundant(tmp_path):
    """A pan-tissue-abundant protein (GAPDH/KRAS archetype): detected in many adult tissues AND
    ABUNDANT (>= floor) in >= BROAD_ABUNDANT_TISSUE_COUNT of them → broad_and_abundant (the veto fires)."""
    rows = [_row("GAPDH", f"adult_{i:02d}", "adult_normal", _FLOOR + 3.0) for i in range(_BROAD_ABUND + 5)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("GAPDH", product_path=prod)
    assert out["tphp_normal_protein_liability_class"] == "broad_and_abundant"
    assert out["n_adult_tissues_above_abundance_floor"] == _BROAD_ABUND + 5
    # LITERAL, not `== read.ABUNDANCE_FLOOR_LOG2` (which compares the constant to itself and cannot
    # fail). This is the cut of a VERDICT-BEARING class, so moving it should have to move a test that
    # spells the number — and the emitted field is what a consumer reads the classification against.
    assert out["abundance_floor_log2"] == 15.076
    assert out["vital_organ_min_samples"] == 3


def test_broadly_detected_but_not_abundant_is_detected_not_abundant(tmp_path):
    """CEACAM5 archetype: broadly DETECTED (>=35 adult tissues) but abundance clears the floor in only
    a FEW (here 5 — e.g. its eye/origin tissues), the rest detected at trace/moderate BELOW the floor.
    Must read detected_not_abundant, NOT broad_and_abundant — the DIA-detects-broadly-at-trace correction
    and the reason CEACAM5 does not flip to the normal-liability veto."""
    detected = 63
    n_above = 5
    rows = [
        _row("CEACAM5", f"adult_{i:02d}", "adult_normal", (_FLOOR + 4.0) if i < n_above else (_FLOOR - 1.0))
        for i in range(detected)
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("CEACAM5", product_path=prod)
    assert out["n_adult_tissues_detected"] == detected
    assert out["n_adult_tissues_above_abundance_floor"] == n_above
    assert out["tphp_normal_protein_liability_class"] == "detected_not_abundant"
    # sanity: a single high-abundance (origin/outlier) tissue does not make it broadly abundant
    assert out["max_median_log2_abundance"] >= _FLOOR


def test_narrow_footprint_is_restricted(tmp_path):
    """Detected in < BROAD_ADULT_TISSUE_COUNT adult tissues → restricted (narrow footprint), even when
    those few tissues are abundant (FOLR1 archetype)."""
    rows = [_row("FOLR1", f"adult_{i:02d}", "adult_normal", _FLOOR + 2.0) for i in range(9)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("FOLR1", product_path=prod)
    assert out["tphp_normal_protein_liability_class"] == "restricted"


def test_liability_data_unavailable(tmp_path):
    rows = [_row("EGFR", "liver", "adult_normal", 9.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("GHOSTGENE", product_path=prod)
    assert out["tphp_normal_protein_liability_class"] == "data_unavailable"
    assert out["n_adult_tissues_above_abundance_floor"] == 0


# ── tphp_vital_organ_liability_class (T0-3: dose-limiting-organ protein view) ────────────────────
# Orthogonal to the pan-tissue BREADTH class: keys on whether the target is ABUNDANT (>= the same
# calibrated floor) in ANY canonical vital organ, via TPHP_CROSSWALK. TPHP fills the endocrine/vascular
# organs HPA-IHC is blind to (nerve/muscle/blood/adrenal/thyroid).
_VITAL_VOCAB = {"vital_organ_abundant", "vital_organ_low", "no_vital_organ_signal", "data_unavailable"}


def test_vital_organ_abundant_reachable(tmp_path):
    """A target abundant (>= floor) in >=1 canonical vital organ → vital_organ_abundant, with the
    per-organ row mapping the canonical organ to its TPHP organism-part."""
    rows = [
        _row("XYZ", "heart", "adult_normal", _FLOOR + 3.0),
        _row("XYZ", "adrenal gland", "adult_normal", _FLOOR + 1.0),
        _row("XYZ", "skin", "adult_normal", _FLOOR + 5.0),  # non-vital tissue, ignored by the vital view
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("XYZ", product_path=prod)
    assert out["tphp_vital_organ_liability_class"] in _VITAL_VOCAB
    assert out["tphp_vital_organ_liability_class"] == "vital_organ_abundant"
    assert out["n_vital_organs_above_abundance_floor"] == 2  # heart + adrenal_gland (skin is not vital)
    va = {r["organ"]: r for r in out["tphp_vital_organ_abundance"]}
    assert va["heart"]["tissue"] == "heart" and va["heart"]["above_abundance_floor"] is True
    assert va["adrenal_gland"]["tissue"] == "adrenal gland" and va["adrenal_gland"]["above_abundance_floor"] is True
    # an undetected-but-representable vital organ is still listed (detected=False), so the view is complete
    assert va["liver"]["detected"] is False
    # pituitary is None in TPHP_CROSSWALK (not in the panel) → never listed
    assert "pituitary" not in va


def test_vital_organ_view_orthogonal_to_breadth(tmp_path):
    """The value-add: a NARROW-breadth target can still be abundant in a vital organ (a therapeutic-
    window flag the breadth class misses). Detected in only 3 adult tissues (restricted breadth) but
    abundant in liver → tphp_normal_protein_liability_class=restricted YET vital=vital_organ_abundant."""
    rows = [
        _row("NARROW", "liver", "adult_normal", _FLOOR + 4.0),
        _row("NARROW", "skin", "adult_normal", _FLOOR + 2.0),
        _row("NARROW", "esophagus", "adult_normal", _FLOOR + 2.0),
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("NARROW", product_path=prod)
    assert out["tphp_normal_protein_liability_class"] == "restricted"
    assert out["tphp_vital_organ_liability_class"] == "vital_organ_abundant"
    assert out["n_vital_organs_above_abundance_floor"] == 1


def test_vital_organ_low_when_detected_below_floor(tmp_path):
    """Detected in a vital organ but BELOW the abundance floor → vital_organ_low (trace-only)."""
    rows = [_row("TRACE", "kidney", "adult_normal", _FLOOR - 2.0), _row("TRACE", "brain", "adult_normal", _FLOOR - 1.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("TRACE", product_path=prod)
    assert out["tphp_vital_organ_liability_class"] == "vital_organ_low"
    assert out["n_vital_organs_above_abundance_floor"] == 0


def test_no_vital_organ_signal_when_only_non_vital(tmp_path):
    """Detected only in non-vital tissues (skin/esophagus) → no_vital_organ_signal."""
    rows = [
        _row("SKINONLY", "skin", "adult_normal", _FLOOR + 5.0),
        _row("SKINONLY", "esophagus", "adult_normal", _FLOOR + 5.0),
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("SKINONLY", product_path=prod)
    assert out["tphp_vital_organ_liability_class"] == "no_vital_organ_signal"
    assert out["n_vital_organs_above_abundance_floor"] == 0


def test_vital_organ_data_unavailable(tmp_path):
    rows = [_row("EGFR", "liver", "adult_normal", 9.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("GHOSTGENE", product_path=prod)
    assert out["tphp_vital_organ_liability_class"] == "data_unavailable"
    assert out["n_vital_organs_above_abundance_floor"] == 0
    assert out["tphp_vital_organ_abundance"] == []


# ── HPA-blind vital-organ view (skills #1793) ─────────────────────────────────────────────────────
# The vital-organ liability read SCOPED to the organs the verdict-bearing HPA-IHC essential-tissue
# killer cannot represent (nerve/blood/adrenal_gland/thyroid via TPHP; pituitary covered by NEITHER
# panel). The class is routed into a safety-resolver rung in target-contracts, so these tests are the
# methods-side mutation teeth: each fails RED if the subset scoping (or the emit) is reverted.


def test_hpa_blind_abundant_fires_on_thyroid(tmp_path):
    """A target abundant ONLY in an HPA-blind organ (the motivating thyroid case): the blind class
    must read vital_organ_abundant and NAME the organ."""
    rows = [
        _row("TSHRLIKE", "thyroid gland", "adult_normal", _FLOOR + 2.0, n_samples=2, n_detected=2),
        _row("TSHRLIKE", "skin", "adult_normal", _FLOOR - 1.0),
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("TSHRLIKE", product_path=prod)
    assert out["tphp_hpa_blind_vital_organ_liability_class"] == "vital_organ_abundant"
    assert out["n_hpa_blind_vital_organs_above_abundance_floor"] == 1
    assert out["hpa_blind_vital_organs_above_floor"] == ["thyroid"]
    # the thin thyroid arm (n=2 < MIN_SAMPLES_MEASURABLE) must NOT suppress the liability — the
    # measurability label gates ABSENCE claims, never a detected above-floor presence (fail-closed).
    va = {r["organ"]: r for r in out["tphp_vital_organ_abundance"]}
    assert va["thyroid"]["measurable"] is False and va["thyroid"]["above_abundance_floor"] is True


def test_hpa_blind_class_is_scoped_not_the_full_vital_set(tmp_path):
    """THE SUBSET DISCRIMINATOR: abundant in heart (HPA-representable — its killer already covers it)
    must fire the FULL vital class but NOT the HPA-blind class. Reverting the scoping to the full
    organ set (the tempting 'simpler' rung) turns this RED."""
    rows = [_row("HEARTONLY", "heart", "adult_normal", _FLOOR + 4.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("HEARTONLY", product_path=prod)
    assert out["tphp_vital_organ_liability_class"] == "vital_organ_abundant"
    assert out["tphp_hpa_blind_vital_organ_liability_class"] == "no_vital_organ_signal"
    assert out["n_hpa_blind_vital_organs_above_abundance_floor"] == 0
    assert out["hpa_blind_vital_organs_above_floor"] == []


def test_hpa_blind_low_when_detected_below_floor(tmp_path):
    rows = [_row("NERVETRACE", "nerve", "adult_normal", _FLOOR - 2.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("NERVETRACE", product_path=prod)
    assert out["tphp_hpa_blind_vital_organ_liability_class"] == "vital_organ_low"
    assert out["n_hpa_blind_vital_organs_above_abundance_floor"] == 0


def test_hpa_blind_uncovered_names_pituitary(tmp_path):
    """pituitary has NO organism-part in TPHP and no HPA name: covered by NO verdict-bearing protein
    arm. The reader must SAY so (the coverage-caveat datum), never leave it as silent absence."""
    rows = [_row("ANYGENE", "liver", "adult_normal", _FLOOR + 1.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("ANYGENE", product_path=prod)
    assert out["hpa_blind_vital_organs_uncovered"] == ["pituitary"]


def test_hpa_blind_data_unavailable_uncovers_the_whole_blind_set(tmp_path):
    """Gene absent from TPHP: the blind class is data_unavailable and the uncovered list widens to
    the WHOLE HPA-blind set — with no TPHP read, no verdict-bearing protein arm covers ANY of them."""
    rows = [_row("EGFR", "liver", "adult_normal", 9.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("GHOSTGENE", product_path=prod)
    assert out["tphp_hpa_blind_vital_organ_liability_class"] == "data_unavailable"
    assert out["n_hpa_blind_vital_organs_above_abundance_floor"] == 0
    assert out["hpa_blind_vital_organs_above_floor"] == []
    assert out["hpa_blind_vital_organs_uncovered"] == sorted(
        {"nerve", "blood", "adrenal_gland", "pituitary", "thyroid"}
    )


def test_hpa_blind_fields_present_in_both_paths(tmp_path):
    """Emit-shape guard: all four HPA-blind fields present on the data path AND the empty path."""
    prod = _write_product(tmp_path, [_row("EGFR", "liver", "adult_normal", 9.0)])
    for gene in ("EGFR", "GHOSTGENE"):
        out = read.read_target_summary(gene, product_path=prod)
        missing = _HPA_BLIND_FIELDS - set(out)
        assert not missing, f"{gene}: missing HPA-blind fields: {sorted(missing)}"


# ── v2 substrate: tissue_category + solid-tissue counts ──────────────────────────────────────────
# 10 of the 70 adult organism-parts are not solid tissues (4 body fluids, 4 blood_compartment entries
# that are ONE compartment counted four times, hair, plant vessel). The reader LABELS them and emits
# solid-only companion counts; it deliberately does NOT switch the verdict-bearing numerator to
# solid-only, because with an ABSOLUTE cut of 35 that would make the liability veto fire LESS often.


def test_v2_declaration_fields_present_in_both_paths(tmp_path):
    """The v2 declaration fields appear on the populated AND the data_unavailable path — a card/replay
    consumer reading them must never hit a missing key (the shape-stability half of absence discipline)."""
    prod = _write_product(tmp_path, [_row("EGFR", "liver", "adult_normal", 9.0)])
    populated = read.read_target_summary("EGFR", product_path=prod)
    empty = read.read_target_summary("GHOSTGENE", product_path=prod)
    for out, label in ((populated, "populated"), (empty, "data_unavailable")):
        missing = _V2_DECLARATION_FIELDS - set(out)
        assert not missing, f"{label} summary is missing v2 declaration fields: {sorted(missing)}"
    assert populated["n_solid_adult_tissues_total"] == 60
    # per-tissue rows carry the category so a consumer can choose its own denominator
    assert populated["per_tissue_abundance"][0]["tissue_category"] == "solid_tissue"


def test_solid_counts_exclude_non_solid_but_the_verdict_class_does_not(tmp_path):
    """★ The load-bearing NON-change. A target above the floor in exactly BROAD_ABUNDANT_TISSUE_COUNT
    adult parts, 10 of which are the non-solid entries, must STILL read broad_and_abundant — the class
    keys on the ALL-ADULT count. The solid-only count is emitted alongside and is 10 lower.

    Swapping the class numerator to the solid-only count (the intuitive-looking "exclude the fluids"
    fix) turns this target's veto OFF while nothing about its biology changed: with an absolute cut of
    35, removing parts from the numerator can only ever make the liability fire LESS. This test fails
    if anyone makes that swap without also re-deriving the cut."""
    non_solid = [
        ("blood plasma", "body_fluid"),
        ("urine", "body_fluid"),
        ("saliva", "body_fluid"),
        ("tear", "body_fluid"),
        ("blood", "blood_compartment"),
        ("erythrocyte", "blood_compartment"),
        ("leukocyte", "blood_compartment"),
        ("blood platelet", "blood_compartment"),
        ("hair", "non_tissue"),
        ("plant vessel", "unassignable"),
    ]
    n_solid = _BROAD_ABUND - len(non_solid)
    rows = [_row("BORDER", f"solid_{i:02d}", "adult_normal", _FLOOR + 2.0) for i in range(n_solid)]
    rows += [_row("BORDER", t, "adult_normal", _FLOOR + 2.0, tissue_category=cat) for t, cat in non_solid]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("BORDER", product_path=prod)

    assert out["n_adult_tissues_above_abundance_floor"] == _BROAD_ABUND
    assert out["n_solid_adult_tissues_above_abundance_floor"] == n_solid
    assert out["n_solid_adult_tissues_detected"] == n_solid
    assert out["n_adult_tissues_detected"] == _BROAD_ABUND
    assert out["tphp_normal_protein_liability_class"] == "broad_and_abundant"


def test_missing_tissue_category_column_fails_open_to_solid(tmp_path):
    """A v1-shaped product (no tissue_category column) must still classify, defaulting to solid_tissue.
    Fail-OPEN is the safety-correct direction here: an unrecognised part counts toward breadth rather
    than vanishing from the numerator, because vanishing makes the veto quieter."""
    rows = [_row("ACTB", f"adult_{i:02d}", "adult_normal", _FLOOR + 2.0) for i in range(_BROAD_ABUND)]
    prod = _write_product(tmp_path, rows, cols=_COLS_V1, name="v1_shape.parquet")
    out = read.read_target_summary("ACTB", product_path=prod)
    assert out["per_tissue_abundance"][0]["tissue_category"] == "solid_tissue"
    assert out["n_solid_adult_tissues_above_abundance_floor"] == _BROAD_ABUND
    assert out["tphp_normal_protein_liability_class"] == "broad_and_abundant"


# ── vital-organ MEASURABILITY (the n_samples >= 3 gate that must NOT drop organs) ─────────────────


def test_low_support_vital_organs_are_labelled_not_dropped(tmp_path):
    """★ blood (n_samples=1) and thyroid gland (n_samples=2) are below MIN_SAMPLES_MEASURABLE, and
    thyroid is an S1_3_REQUIRED_ORGANS member. They must stay in the panel, be marked measurable=False,
    and — critically — an above-floor value in one must STILL count toward
    n_vital_organs_above_abundance_floor. A support gate that DROPPED them would zero that count and
    read as 'no liability in this organ', re-opening the endocrine safety hole by two organs of 13."""
    rows = [
        _row("LOWN", "thyroid gland", "adult_normal", _FLOOR + 3.0, n_samples=2, n_detected=2),
        _row(
            "LOWN",
            "blood",
            "adult_normal",
            _FLOOR + 4.0,
            n_samples=1,
            n_detected=1,
            tissue_category="blood_compartment",
        ),
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("LOWN", product_path=prod)

    va = {r["organ"]: r for r in out["tphp_vital_organ_abundance"]}
    assert va["thyroid"]["measurable"] is False and va["thyroid"]["n_samples"] == 2
    assert va["blood"]["measurable"] is False and va["blood"]["n_samples"] == 1
    # NOT dropped: both still register as above-floor vital-organ presence.
    assert va["thyroid"]["above_abundance_floor"] is True
    assert va["blood"]["above_abundance_floor"] is True
    assert out["n_vital_organs_above_abundance_floor"] == 2
    assert out["tphp_vital_organ_liability_class"] == "vital_organ_abundant"
    # 15 crosswalked organs (+ large intestine, small intestine 2026-09-18); blood + thyroid are still
    # the two the panel cannot power — both gut arms are ABOVE MIN_SAMPLES_MEASURABLE (13 and 10).
    assert out["n_vital_organs_unmeasurable"] == 2
    assert out["n_vital_organs_measurable"] == 13  # 11 -> 13 with the two gut arms
    assert out["n_vital_organs_measurable"] + out["n_vital_organs_unmeasurable"] == len(
        out["tphp_vital_organ_abundance"]
    )


def test_clean_sweep_is_qualified_by_unmeasurable_count(tmp_path):
    """no_vital_organ_signal is NOT a clean sweep: it is silent about the 2 organs the panel cannot
    power. The counts are what let a consumer say 'clean across 13 measurable organs, 2 unknown'
    (11 -> 13 on 2026-09-18: the gut promotion added large intestine n=13 and small intestine n=10,
    both above MIN_SAMPLES_MEASURABLE, so a wider sweep is now claimable — the unmeasurable pair is
    still exactly blood n=1 and thyroid gland n=2)."""
    rows = [_row("SKINONLY", "skin", "adult_normal", _FLOOR + 5.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("SKINONLY", product_path=prod)
    assert out["tphp_vital_organ_liability_class"] == "no_vital_organ_signal"
    assert out["n_vital_organs_unmeasurable"] == 2
    assert out["n_vital_organs_measurable"] == 13


def test_undetected_vital_organ_falls_back_to_cached_arm_size(tmp_path):
    """The product stores DETECTED-only rows, so an organ where the target was not quantified has NO
    row to read n_samples from — exactly the case where 'clean or unmeasurable?' matters. The cached
    panel arm size answers it, and n_samples_source says the value did not come from the data."""
    prod = _write_product(tmp_path, [_row("NOBLOOD", "skin", "adult_normal", _FLOOR + 1.0)])
    out = read.read_target_summary("NOBLOOD", product_path=prod)
    va = {r["organ"]: r for r in out["tphp_vital_organ_abundance"]}
    assert va["blood"]["detected"] is False
    assert va["blood"]["n_samples"] == 1
    assert va["blood"]["n_samples_source"] == "cached_panel_arm_size"
    assert va["blood"]["measurable"] is False
    # a well-powered undetected organ is measurable — absence there IS informative
    assert va["brain"]["n_samples"] == 74 and va["brain"]["measurable"] is True


def test_product_row_arm_size_overrides_the_cache(tmp_path):
    """The cached arm-size table must be SELF-FALSIFYING: when the product carries a row, the ROW wins.
    Otherwise a refreshed product with more donors would be silently overridden by a stale constant."""
    rows = [
        _row(
            "REFRESHED",
            "blood",
            "adult_normal",
            _FLOOR + 1.0,
            n_samples=40,
            n_detected=40,
            tissue_category="blood_compartment",
        )
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("REFRESHED", product_path=prod)
    va = {r["organ"]: r for r in out["tphp_vital_organ_abundance"]}
    assert va["blood"]["n_samples"] == 40, "cached arm size overrode the live product row"
    assert va["blood"]["n_samples_source"] == "product_row"
    assert va["blood"]["measurable"] is True
    assert out["n_vital_organs_unmeasurable"] == 1  # only thyroid gland remains unpowered


def test_low_support_adult_tissue_count(tmp_path):
    """n_adult_tissues_detected_low_support says how much of the breadth count rests on <=2 donors
    (21 of the 70 adult parts panel-wide). Here 4 of 6 detected adult tissues are low-support."""
    rows = [_row("MIXED", f"small_{i}", "adult_normal", _FLOOR + 1.0, n_samples=2, n_detected=2) for i in range(4)]
    rows += [_row("MIXED", f"big_{i}", "adult_normal", _FLOOR + 1.0, n_samples=10, n_detected=10) for i in range(2)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("MIXED", product_path=prod)
    assert out["n_adult_tissues_detected"] == 6
    assert out["n_adult_tissues_detected_low_support"] == 4


def test_recompute_floor_cli_reports_drift(tmp_path, capsys):
    """The --recompute-floor CLI is the ONLY caller of compute_abundance_floor. Before it existed the
    derivation of a verdict-bearing safety cut was unreachable code, indistinguishable from a magic
    number. Pins that the flag runs, reports the re-derived value against the cached constant, and
    does NOT mutate the constant."""
    import json

    rows = [_row("G", f"t{i:03d}", "adult_normal", float(v)) for i, v in enumerate(range(1, 100))]
    prod = _write_product(tmp_path, rows)
    rc = read._main(["--recompute-floor", "--percentile", "50", "--product-path", str(prod)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recomputed_abundance_floor_log2"] == pytest.approx(50.0, abs=1.0)
    assert payload["cached_abundance_floor_log2"] == 15.076
    assert payload["drift"] == pytest.approx(payload["recomputed_abundance_floor_log2"] - 15.076, abs=1e-6)
    assert read.ABUNDANCE_FLOOR_LOG2 == 15.076, "the CLI must be read-only"


def test_compute_abundance_floor_recalibration(tmp_path):
    """compute_abundance_floor recomputes the global per-tissue percentile from the product's own
    distribution (adult tissues only; fetal excluded). The p50 of 1..99 is 50."""
    rows = [_row("G", f"t{i:03d}", "adult_normal", float(v)) for i, v in enumerate(range(1, 100))] + [
        _row("G", "fetal_x", "fetal", 999.0)
    ]  # fetal ignored by the floor computation
    prod = _write_product(tmp_path, rows)
    assert read.compute_abundance_floor(product_path=prod, percentile=50) == pytest.approx(50.0, abs=1.0)
    assert read.compute_abundance_floor(product_path=prod, percentile=75) == pytest.approx(75.0, abs=1.0)


# ── ABUNDANCE READ-OUT IS ORGANS ONLY (NON_TISSUE_ABUNDANCE_CATEGORIES) ────────────────────────────
# Before this filter the three abundance fields were a category-BLIND argmax over all 74 parts, while
# the same module already filtered by category for its breadth denominators. Measured off the live v2
# product: 2558 of 13261 genes (19.3%) named a non-organ part as their highest-abundance normal
# TISSUE — 1505 body_fluid, 547 blood_compartment, 399 non_tissue (hair), 107 unassignable. CDH17
# read `plant vessel` (18.16), MSLN `tear`, FOLR1 `saliva`, GPC3 `urine`.


def test_body_fluid_is_not_named_as_the_highest_abundance_tissue(tmp_path):
    """The MSLN/FOLR1 shape: a body fluid outranks every organ on abundance.

    Anti-vacuity is built in — `tear` is the unfiltered argmax by 3.0 log2, so this test can only
    pass because the filter exists, and it reds on a category-blind selector.
    """
    rows = [
        _row("MSLN", "tear", "adult_normal", 19.4, tissue_category="body_fluid"),
        _row("MSLN", "seminal vesicle", "adult_normal", 17.5),
        _row("MSLN", "lung", "adult_normal", 16.0),
    ]
    out = read.read_target_summary("MSLN", product_path=_write_product(tmp_path, rows))
    assert out["highest_abundance_tissue"] == "seminal vesicle"
    assert out["max_median_log2_abundance"] == 17.5
    # the displaced part is still IN the display list — narrowing the read-out never hides a row
    assert "tear" in {t["tissue"] for t in out["per_tissue_abundance"]}
    assert out["n_adult_tissues_detected"] == 3, "breadth counts keep every part (fail-OPEN, by design)"


@pytest.mark.parametrize(
    "category,part",
    [
        ("body_fluid", "saliva"),
        ("blood_compartment", "erythrocyte"),
        ("non_tissue", "hair"),
        ("unassignable", "plant vessel"),
    ],
)
def test_every_non_organ_category_is_excluded_from_the_readout(tmp_path, category, part):
    """All FOUR excluded categories, not just the one that motivated the fix.

    `non_tissue` (hair, 399 genes) and `blood_compartment` (547) are together larger than
    `unassignable` (107) by an order of magnitude, so a fix aimed only at `plant vessel` would have
    closed the smallest of the four holes.
    """
    rows = [
        _row("GENE1", part, "adult_normal", 20.0, tissue_category=category),
        _row("GENE1", "liver", "adult_normal", 12.0),
    ]
    out = read.read_target_summary("GENE1", product_path=_write_product(tmp_path, rows))
    assert out["highest_abundance_tissue"] == "liver"
    assert out["max_median_log2_abundance"] == 12.0


def test_a_fetal_germ_layer_can_still_be_the_highest_abundance_tissue(tmp_path):
    """⚠️ REGRESSION GUARD ON THE FIX'S OWN SHAPE — do not turn this into an allow-list.

    `tissue_category` and `tissue_class` partition each other (`fetal_germ_layer` <-> `fetal`), so
    filtering to `solid_tissue` ALONE would make `highest_abundance_tissue_class == "fetal"`
    unreachable and leave half the card's declared `adult_normal | fetal` vocabulary permanently
    dead. Measured on the live product: 922 of 13261 genes top out on a fetal group.
    """
    rows = [
        _row("MAGEA3", "blood plasma", "adult_normal", 18.0, tissue_category="body_fluid"),
        _row("MAGEA3", "endoderm", "fetal", 15.0, tissue_category="fetal_germ_layer"),
        _row("MAGEA3", "testis", "adult_normal", 9.0),
    ]
    out = read.read_target_summary("MAGEA3", product_path=_write_product(tmp_path, rows))
    assert out["highest_abundance_tissue"] == "endoderm"
    assert out["highest_abundance_tissue_class"] == "fetal"
    assert out["max_median_log2_abundance"] == 15.0


def test_median_can_never_exceed_the_max_across_the_readout_population(tmp_path):
    """The card's invariant: `highest_abundance_tissue` is "the tissue carrying
    max_median_log2_abundance". All three abundance fields therefore derive from ONE population.

    Narrowing the max while leaving the median over all 74 parts would let the MEDIAN EXCEED THE MAX
    — measured on the live product, that state would have been reachable for 77 genes. This fixture
    is one of them in miniature: the two body fluids at 30.0 drag an all-parts median to 15.0, above
    the organs-only max of 12.0.
    """
    rows = [
        _row("GENE2", "urine", "adult_normal", 30.0, tissue_category="body_fluid"),
        _row("GENE2", "blood plasma", "adult_normal", 30.0, tissue_category="body_fluid"),
        _row("GENE2", "liver", "adult_normal", 12.0),
        _row("GENE2", "lung", "adult_normal", 3.0),
    ]
    out = read.read_target_summary("GENE2", product_path=_write_product(tmp_path, rows))
    assert out["max_median_log2_abundance"] == 12.0
    assert out["median_across_tissues_log2_abundance"] == 7.5, "median over the 2 ORGANS, not all 4 parts"
    assert out["median_across_tissues_log2_abundance"] <= out["max_median_log2_abundance"]
    # the anti-vacuity arm: the unfiltered median WOULD have broken the invariant
    all_parts_median = 21.0  # median(30.0, 30.0, 12.0, 3.0)
    assert all_parts_median > out["max_median_log2_abundance"]


def test_organ_free_detection_nulls_the_abundance_readout_but_not_the_breadth(tmp_path):
    """THE FIX'S OWN FAIL DIRECTION, measured: 105 of 13261 genes (0.8%) are detected ONLY in
    non-organ parts, so their abundance read-out becomes None where it used to name a fluid.

    None is the honest answer — there is no organ abundance to report — and it is the same token the
    absent-gene path already emits. Breadth is deliberately UNCHANGED: it keeps every part and still
    says the protein was seen, so a consumer can tell "no organ abundance" from "gene not found".
    """
    rows = [
        _row("GENE3", "blood plasma", "adult_normal", 14.0, tissue_category="body_fluid"),
        _row("GENE3", "leukocyte", "adult_normal", 13.0, tissue_category="blood_compartment"),
    ]
    out = read.read_target_summary("GENE3", product_path=_write_product(tmp_path, rows))
    assert out["highest_abundance_tissue"] is None
    assert out["highest_abundance_tissue_class"] is None
    assert out["max_median_log2_abundance"] is None
    assert out["median_across_tissues_log2_abundance"] is None
    # NOT data_unavailable — the gene WAS found, in 2 adult parts
    assert out["normal_protein_breadth_class"] == "restricted_normal_protein"
    assert out["n_adult_tissues_detected"] == 2
    assert out["max_detection_rate"] == 1.0, "detection breadth keeps every part"


def test_a_missing_tissue_category_still_counts_as_an_organ(tmp_path):
    """v1-substrate compatibility: an absent `tissue_category` fails OPEN to solid_tissue at the
    `tcat` assignment, so a v1 product read through this reader keeps its whole read-out population
    rather than silently emptying it."""
    rows = [_row("GENE4", "liver", "adult_normal", 9.0, tissue_category=None)]
    out = read.read_target_summary("GENE4", product_path=_write_product(tmp_path, rows))
    assert out["highest_abundance_tissue"] == "liver"
    assert out["max_median_log2_abundance"] == 9.0
