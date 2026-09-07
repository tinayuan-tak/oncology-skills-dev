"""depmap_cis_protein_dosage.compute_cis_protein_dosage — hermetic (synthetic CN + protein, no S3).

Pins the protein cis-dosage coupling classifier: does the target's own relative CN predict its own Gygi-MS
log2 protein abundance across the panel? A strong POSITIVE CN↔protein correlation → prot_dosage_coupled_*
(amplification-driven over-abundance, ERBB2/MYC); CN varies but protein is flat/random →
prot_dosage_uncoupled (the informative negative: protein is dosage-BUFFERED); a near-diploid panel with no
CN variance → cn_invariant_panel (untestable); too few jointly-measured lines → data_unavailable.

Mirrors tests/methods/depmap_cis_dosage/test_cis_dosage.py (the mRNA sibling) so the two legs stay
directly comparable.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_cis_protein_dosage.cli import (  # noqa: E402
    compute_cis_protein_dosage,
    AMPLIFICATION_THRESHOLD,
    MIN_CELL_LINES_FOR_CORRELATION,
)


def _coupled_panel(n=120, *, slope=2.0, noise=0.3, seed=0):
    """CN spread across [1.0, 3.0]; protein = slope*CN + noise → strong positive CN↔protein coupling."""
    import random

    rng = random.Random(seed)
    cn, prot = {}, {}
    for i in range(n):
        c = 1.0 + 2.0 * (i / (n - 1))  # deterministic CN spread 1.0..3.0
        m = f"ACH-{i:05d}"
        cn[m] = c
        prot[m] = slope * c + rng.uniform(-noise, noise)
    return cn, prot


def test_coupled_strong():
    """CN strongly predicts protein (near-linear) → prot_dosage_coupled_strong (ERBB2/MYC signature)."""
    cn, prot = _coupled_panel(noise=0.3)
    s = compute_cis_protein_dosage(cn, prot)
    assert s["cis_protein_dosage_class"] == "prot_dosage_coupled_strong"
    assert s["cn_prot_spearman_r"] >= 0.4
    assert s["cn_prot_spearman_p"] <= 0.01
    assert s["cn_prot_slope_log2abundance_per_cn"] is not None
    assert s["n_amplified"] > 0  # some lines above the 1.5 focal-amp threshold
    assert s["delta_log2abundance_amplified_vs_neutral"] > 0  # amplified lines over-abundant (dosage effect)
    assert s["amplification_threshold_relative_cn"] == AMPLIFICATION_THRESHOLD


def test_coupled_moderate():
    """A real but noisier CN→protein trend lands in the moderate band (0.25 <= r < 0.4)."""
    cn, prot = _coupled_panel(n=140, slope=1.0, noise=2.5, seed=7)
    s = compute_cis_protein_dosage(cn, prot)
    assert s["cis_protein_dosage_class"] == "prot_dosage_coupled_moderate"
    assert 0.25 <= s["cn_prot_spearman_r"] < 0.4


def test_uncoupled_when_protein_flat_but_cn_varies():
    """CN varies across the panel but protein is random/independent → prot_dosage_uncoupled (the
    informative negative: post-transcriptionally BUFFERED, NOT amplification-driven at the protein level)."""
    import random

    rng = random.Random(3)
    cn, prot = {}, {}
    for i in range(120):
        m = f"ACH-{i:05d}"
        cn[m] = 1.0 + 2.0 * (i / 119)  # real CN spread
        prot[m] = 6.0 + rng.uniform(-1.0, 1.0)  # protein independent of CN (buffered)
    s = compute_cis_protein_dosage(cn, prot)
    assert s["cis_protein_dosage_class"] == "prot_dosage_uncoupled"
    assert s["relative_cn_iqr"] >= 0.2  # CN variance IS present (so not invariant)


def test_cn_invariant_panel_is_not_uncoupled():
    """Near-diploid panel (no CN variation) → cn_invariant_panel (untestable), NOT prot_dosage_uncoupled."""
    import random

    rng = random.Random(5)
    cn, prot = {}, {}
    for i in range(120):
        m = f"ACH-{i:05d}"
        cn[m] = 1.0 + rng.uniform(-0.02, 0.02)  # essentially diploid everywhere (p90-p10 << 0.2)
        prot[m] = 6.0 + rng.uniform(-1.0, 1.0)
    s = compute_cis_protein_dosage(cn, prot)
    assert s["cis_protein_dosage_class"] == "cn_invariant_panel"
    assert s["relative_cn_p10_p90_spread"] < 0.2
    assert s["cn_prot_spearman_r"] is None  # correlation not computed on an untestable panel


def test_focal_amplification_tail_is_testable_not_invariant():
    """REGRESSION (mirrors the mRNA leg's ERBB2 calibration bug): a focal-amp oncogene is bulk-diploid
    with an amplified TAIL, so its IQR (middle 50%) is ~0 even though the tail carries real coupling
    signal. The invariant gate keys on the p90-p10 spread (tail-sensitive), NOT the IQR."""
    import random

    rng = random.Random(9)
    cn, prot = {}, {}
    i = 0
    for _ in range(100):  # bulk diploid: tight body → small IQR
        m = f"ACH-{i:05d}"
        cn[m] = 1.0 + rng.uniform(-0.05, 0.05)
        prot[m] = 6.0 + rng.uniform(-0.5, 0.5)
        i += 1
    for _ in range(20):  # amplified tail: high CN AND high protein
        m = f"ACH-{i:05d}"
        amp = rng.uniform(3.0, 12.0)
        cn[m] = amp
        prot[m] = 9.5 + rng.uniform(-0.5, 0.5)
        i += 1
    s = compute_cis_protein_dosage(cn, prot)
    assert s["cis_protein_dosage_class"] in ("prot_dosage_coupled_strong", "prot_dosage_coupled_moderate"), (
        f"focal-amp tail must be testable+coupled, got {s['cis_protein_dosage_class']}"
    )
    assert s["relative_cn_iqr"] < 0.2  # the IQR IS tiny (the trap the old gate fell into)
    assert s["relative_cn_p10_p90_spread"] >= 0.2  # but the tail-sensitive spread passes
    assert s["cn_prot_spearman_r"] > 0.25


def test_data_unavailable_when_too_few_lines():
    """Fewer than min_cell_lines (30) jointly-measured lines → data_unavailable (wide-CI / sparse-protein guard)."""
    cn, prot = _coupled_panel(n=20)
    s = compute_cis_protein_dosage(cn, prot)
    assert s["cis_protein_dosage_class"] == "data_unavailable"
    assert s["n_paired_models_cn_protein"] == 20


def test_only_jointly_measured_lines_are_evaluated():
    """Lines with CN-only or protein-only are excluded from the evaluated universe."""
    cn, prot = _coupled_panel(n=120)
    cn["ACH-99990"] = 2.5  # CN-only, no protein
    prot["ACH-99991"] = 8.0  # protein-only, no CN
    s = compute_cis_protein_dosage(cn, prot)
    assert s["n_paired_models_cn_protein"] == 120  # the two singletons dropped


def test_min_cell_lines_floor_is_lower_than_mrna_leg():
    """The protein leg's floor (30) is intentionally below the mRNA leg's (50) because Gygi protein
    detection is sparser — pin it so a future edit doesn't silently raise it back."""
    assert MIN_CELL_LINES_FOR_CORRELATION == 30
