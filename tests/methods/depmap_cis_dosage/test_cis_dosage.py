"""depmap_cis_dosage.compute_cis_dosage — hermetic (synthetic CN + TPM, no S3).

Pins the cis-dosage coupling classifier: does the target's own relative CN predict its own log2TPM
across the panel? A strong POSITIVE CN↔TPM correlation → cn_dosage_coupled_* (amplification-driven
overexpression, ERBB2/MYC); CN varies but expression is flat/random → cn_dosage_uncoupled (the
informative negative: expression is copy-number-INDEPENDENT); a near-diploid panel with no CN variance
→ cn_invariant_panel (untestable, distinct from uncoupled); too few jointly-measured lines →
data_unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_cis_dosage.cli import (  # noqa: E402
    compute_cis_dosage, AMPLIFICATION_THRESHOLD,
)


def _coupled_panel(n=120, *, slope=2.0, noise=0.3, seed=0):
    """CN spread across [1.0, 3.0]; TPM = slope*CN + noise → strong positive CN↔TPM coupling."""
    import random
    rng = random.Random(seed)
    cn, tpm = {}, {}
    for i in range(n):
        c = 1.0 + 2.0 * (i / (n - 1))            # deterministic CN spread 1.0..3.0
        m = f"ACH-{i:05d}"
        cn[m] = c
        tpm[m] = slope * c + rng.uniform(-noise, noise)
    return cn, tpm


def test_coupled_strong():
    """CN strongly predicts expression (near-linear) → cn_dosage_coupled_strong (ERBB2/MYC signature)."""
    cn, tpm = _coupled_panel(noise=0.3)
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] == "cn_dosage_coupled_strong"
    assert s["cn_expr_spearman_r"] >= 0.4
    assert s["cn_expr_spearman_p"] <= 0.01
    assert s["n_amplified"] > 0                    # some lines above the 1.5 focal-amp threshold
    assert s["delta_log2tpm_amplified_vs_neutral"] > 0   # amplified lines over-express (dosage effect)
    assert s["amplification_threshold_relative_cn"] == AMPLIFICATION_THRESHOLD


def test_coupled_moderate():
    """A real but noisier CN→expression trend lands in the moderate band (0.25 <= r < 0.4).
    noise=2.5 gives Spearman r ~ 0.34 (empirically pinned; CN spread is only 2.0 relative-CN units)."""
    cn, tpm = _coupled_panel(n=140, slope=1.0, noise=2.5, seed=7)
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] == "cn_dosage_coupled_moderate"
    assert 0.25 <= s["cn_expr_spearman_r"] < 0.4


def test_uncoupled_when_expression_flat_but_cn_varies():
    """CN varies across the panel but expression is random/independent → cn_dosage_uncoupled (the
    informative negative: trans/lineage-regulated expression, NOT amplification-driven)."""
    import random
    rng = random.Random(3)
    cn, tpm = {}, {}
    for i in range(120):
        m = f"ACH-{i:05d}"
        cn[m] = 1.0 + 2.0 * (i / 119)              # real CN spread
        tpm[m] = 6.0 + rng.uniform(-1.0, 1.0)      # expression independent of CN
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] == "cn_dosage_uncoupled"
    assert s["relative_cn_iqr"] >= 0.2             # CN variance IS present (so not invariant)


def test_cn_invariant_panel_is_not_uncoupled():
    """Near-diploid panel (no CN variance) → cn_invariant_panel (untestable), NOT cn_dosage_uncoupled.
    The honest-abstention bin: absence of CN variance means the cis-dosage question can't be asked."""
    import random
    rng = random.Random(5)
    cn, tpm = {}, {}
    for i in range(120):
        m = f"ACH-{i:05d}"
        cn[m] = 1.0 + rng.uniform(-0.02, 0.02)     # essentially diploid everywhere (IQR << 0.2)
        tpm[m] = 6.0 + rng.uniform(-1.0, 1.0)
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] == "cn_invariant_panel"
    assert s["relative_cn_iqr"] < 0.2
    assert s["cn_expr_spearman_r"] is None         # correlation not computed on an untestable panel


def test_data_unavailable_when_too_few_lines():
    """Fewer than min_cell_lines (50) jointly-measured lines → data_unavailable (wide-CI guard)."""
    cn, tpm = _coupled_panel(n=20)
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] == "data_unavailable"
    assert s["n_cell_lines_evaluated"] == 20


def test_only_jointly_measured_lines_are_evaluated():
    """Lines with CN-only or TPM-only are excluded from the evaluated universe."""
    cn, tpm = _coupled_panel(n=120)
    cn["ACH-99990"] = 2.5          # CN-only, no TPM
    tpm["ACH-99991"] = 8.0         # TPM-only, no CN
    s = compute_cis_dosage(cn, tpm)
    assert s["n_cell_lines_evaluated"] == 120      # the two singletons dropped
