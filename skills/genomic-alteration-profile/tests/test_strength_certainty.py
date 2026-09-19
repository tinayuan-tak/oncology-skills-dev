"""genomic-alteration (strength, certainty) sidecar — CERTAINTY_MODEL 3rd axis. Verdict-inert."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

ga = load_run_py(Path(__file__).resolve().parent.parent, "ga_run_sc")


def _cards(civic=None, dep_arm=None, mut_mutated=None, denom=None):
    """Build a card list for the sidecar. `dep_arm` is the ALTERED-arm count the coverage band now reads
    (mutation-stratified-dependency.n_hotspot_mutant); `mut_mutated` is the SNV-spectrum altered arm
    (mutation-type-counts.mut_n_cell_lines_mutated). `denom` supplies n_cell_lines_evaluated — the panel
    TOTAL the pre-2.19.0 code wrongly read — and is retained so a regression back to the denominator is
    caught (see test_coverage_reads_the_altered_arm_not_the_panel_denominator)."""
    c = []
    if civic is not None:
        c.append({"card_id": "variant-level-interpretation", "summary": {"civic_variant_class": civic}})
    dep = {}
    if dep_arm is not None:
        dep["n_hotspot_mutant"] = dep_arm
    if denom is not None:
        dep["n_cell_lines_evaluated"] = denom  # panel denominator — MUST be ignored by coverage
    if dep:
        c.append({"card_id": "mutation-stratified-dependency", "summary": dep})
    if mut_mutated is not None:
        c.append({"card_id": "mutation-type-counts", "summary": {"mut_n_cell_lines_mutated": mut_mutated}})
    return c


def test_driver_with_oncogenic_civic_corroboration():
    sc = ga._strength_certainty(
        _cards(civic="oncogenic", dep_arm=50, denom=1538),
        verdict_pair=("biomarker_stratified_dependency", "mutant-strongly-dependent-supportive"),
    )
    assert sc["strength"] == "strong_positive"
    assert sc["certainty"]["coverage"] == "high"  # 50 mutant lines in the altered arm (>= 30)
    assert sc["certainty"]["corroboration"] == "high"  # CIViC oncogenic
    assert sc["certainty"]["level"] == "high"


def test_civic_uncurated_is_unmeasured_not_low():
    # gene absent from CIViC -> corroboration unmeasured (ignorance), drops from level = coverage.
    # missense_dominant_pattern is a spectrum SHAPE, not a driver: its strength is now `neutral`
    # (v2.19.0), and its coverage reads the mutated arm (mut_n_cell_lines_mutated), not the panel total.
    sc = ga._strength_certainty(
        _cards(civic=None, mut_mutated=15),
        verdict_pair=("missense_dominant_pattern", "mut-missense-dominant-supportive"),
    )
    assert sc["strength"] == "neutral"
    assert sc["certainty"]["corroboration"] == "unmeasured"
    assert sc["certainty"]["level"] == sc["certainty"]["coverage"] == "medium"  # 15 mutated lines -> medium


def test_vus_civic_disagrees_low():
    sc = ga._strength_certainty(
        _cards(civic="vus", denom=50), verdict_pair=("confirmed_driver", "alteration-role-gof-driver-supportive")
    )
    assert sc["certainty"]["coverage"] == "high"  # curated driver defers to corroboration
    assert sc["certainty"]["corroboration"] == "low"  # CIViC does not confirm oncogenicity
    assert sc["certainty"]["level"] == "low"  # weakest-link


def test_insufficient_forces_low():
    sc = ga._strength_certainty([], verdict_pair=("insufficient", None))
    assert sc["strength"] == "none"
    assert sc["certainty"]["level"] == "low"


def test_coverage_reads_the_altered_arm_not_the_panel_denominator():
    """ANTI-VACUITY / anti-regression. The pre-2.19.0 bug read n_cell_lines_evaluated (the ~1500-line
    panel total) so coverage saturated `high` for every measured verdict — a power claim that never
    varied. A thin driving arm inside a huge panel must now read `low`, a powered arm `high`, and the
    two must be DISTINGUISHABLE with the SAME denominator — proving the denominator no longer drives it."""
    thin = ga._strength_certainty(
        _cards(dep_arm=4, denom=1538),
        verdict_pair=("biomarker_stratified_dependency", "mutant-strongly-dependent-supportive"),
    )
    assert thin["certainty"]["coverage"] == "low"  # arm=4 < 10, though the panel denominator is 1538
    powered = ga._strength_certainty(
        _cards(dep_arm=40, denom=1538),
        verdict_pair=("biomarker_stratified_dependency", "mutant-strongly-dependent-supportive"),
    )
    assert powered["certainty"]["coverage"] == "high"  # SAME denominator, arm=40 -> the arm drives it
