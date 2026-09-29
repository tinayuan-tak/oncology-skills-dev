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
    AMPLIFICATION_THRESHOLD,
    compute_cis_dosage,
)


def _coupled_panel(n=120, *, slope=2.0, noise=0.3, seed=0):
    """CN spread across [1.0, 3.0]; TPM = slope*CN + noise → strong positive CN↔TPM coupling."""
    import random

    rng = random.Random(seed)
    cn, tpm = {}, {}
    for i in range(n):
        c = 1.0 + 2.0 * (i / (n - 1))  # deterministic CN spread 1.0..3.0
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
    assert s["n_amplified"] > 0  # some lines above the 1.5 focal-amp threshold
    assert s["delta_log2tpm_amplified_vs_neutral"] > 0  # amplified lines over-express (dosage effect)
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
        cn[m] = 1.0 + 2.0 * (i / 119)  # real CN spread
        tpm[m] = 6.0 + rng.uniform(-1.0, 1.0)  # expression independent of CN
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] == "cn_dosage_uncoupled"
    assert s["relative_cn_iqr"] >= 0.2  # CN variance IS present (so not invariant)


def test_cn_invariant_panel_is_not_uncoupled():
    """Near-diploid panel (no CN variation) → cn_invariant_panel (untestable), NOT cn_dosage_uncoupled.
    The honest-abstention bin: absence of CN variation means the cis-dosage question can't be asked."""
    import random

    rng = random.Random(5)
    cn, tpm = {}, {}
    for i in range(120):
        m = f"ACH-{i:05d}"
        cn[m] = 1.0 + rng.uniform(-0.02, 0.02)  # essentially diploid everywhere (p90-p10 << 0.2)
        tpm[m] = 6.0 + rng.uniform(-1.0, 1.0)
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] == "cn_invariant_panel"
    assert s["relative_cn_p10_p90_spread"] < 0.2
    assert s["cn_expr_spearman_r"] is None  # correlation not computed on an untestable panel


def test_focal_amplification_tail_is_testable_not_invariant():
    """REGRESSION (ERBB2 calibration bug 2026-08-20): a focal-amp oncogene is bulk-diploid with an
    amplified TAIL, so its IQR (middle 50%) is ~0 even though the tail carries real coupling signal.
    The invariant gate keys on the p90-p10 spread (tail-sensitive), NOT the IQR, so such a panel is
    correctly TESTABLE (coupled), not mislabeled cn_invariant_panel. Mirrors ERBB2 live: IQR 0.18 but
    Spearman r=0.26 p=1e-15 over 71 amplified lines."""
    import random

    rng = random.Random(9)
    cn, tpm = {}, {}
    i = 0
    for _ in range(100):  # bulk diploid: tight body → small IQR
        m = f"ACH-{i:05d}"
        cn[m] = 1.0 + rng.uniform(-0.05, 0.05)
        tpm[m] = 6.0 + rng.uniform(-0.5, 0.5)
        i += 1
    for _ in range(20):  # amplified tail: high CN AND high expression
        m = f"ACH-{i:05d}"
        amp = rng.uniform(3.0, 12.0)
        cn[m] = amp
        tpm[m] = 9.5 + rng.uniform(-0.5, 0.5)
        i += 1
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] in ("cn_dosage_coupled_strong", "cn_dosage_coupled_moderate"), (
        f"focal-amp tail must be testable+coupled, got {s['cis_dosage_class']}"
    )
    assert s["relative_cn_iqr"] < 0.2  # the IQR IS tiny (the trap the old gate fell into)
    assert s["relative_cn_p10_p90_spread"] >= 0.2  # but the tail-sensitive spread passes
    assert s["cn_expr_spearman_r"] > 0.25


def test_focal_amplification_subset_escape_promotes_diluted_correlation():
    """REGRESSION (ERBB2 silencing-override bug 2026-09-12): a focal-amp oncogene whose amplified subset
    strongly over-expresses, but whose PAN-PANEL Spearman is DILUTED below the 0.25 moderate gate by a
    large lineage-noisy diploid body (ERBB2 live: r=0.23 but +2.28 log2TPM over 155 amplified lines).
    The subset escape must PROMOTE it to coupled via the focal_amplification_subset driver — else a
    spurious minority-methylation call overrides it to a biologically absurd epigenetic-silencing verdict."""
    import random

    rng = random.Random(11)
    cn, tpm = {}, {}
    i = 0
    for _ in range(700):  # large diploid-ish body: CN 0.7..1.45, expression lineage-noisy (NOT CN-tracking)
        m = f"ACH-{i:05d}"
        cn[m] = rng.uniform(0.7, 1.45)
        tpm[m] = rng.uniform(3.0, 8.0)
        i += 1
    for _ in range(30):  # amplified subset: high CN AND strongly over-expressed (the focal-amp tail)
        m = f"ACH-{i:05d}"
        cn[m] = rng.uniform(2.0, 7.0)
        tpm[m] = 9.0 + rng.uniform(-0.5, 0.5)
        i += 1
    s = compute_cis_dosage(cn, tpm)
    assert s["cn_expr_spearman_r"] < 0.25, (
        f"body should dilute pan-panel r below the moderate gate, got {s['cn_expr_spearman_r']}"
    )
    assert s["cis_dosage_class"] in ("cn_dosage_coupled_strong", "cn_dosage_coupled_moderate")
    assert s["cis_dosage_driver"] == "focal_amplification_subset"
    assert s["subset_delta_log2tpm_amplified_vs_neutral"] >= 1.0
    assert s["subset_mannwhitney_p"] <= 0.01


def test_focal_amp_escape_does_not_fire_when_amplified_subset_is_not_overexpressed():
    """The escape only PROMOTES a genuine amplification-driven over-expression. A panel where CN varies
    (incl. an amplified subset) but expression is flat stays cn_dosage_uncoupled — the subset delta is ~0,
    so the focal_amplification_subset driver must NOT fire (guards against over-calling)."""
    import random

    rng = random.Random(13)
    cn, tpm = {}, {}
    i = 0
    for _ in range(120):
        m = f"ACH-{i:05d}"
        cn[m] = rng.uniform(0.7, 1.4)
        tpm[m] = 6.0 + rng.uniform(-1.0, 1.0)
        i += 1
    for _ in range(40):  # amplified subset but expression flat (no dosage effect)
        m = f"ACH-{i:05d}"
        cn[m] = rng.uniform(2.0, 6.0)
        tpm[m] = 6.0 + rng.uniform(-1.0, 1.0)
        i += 1
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] == "cn_dosage_uncoupled"
    assert s["cis_dosage_driver"] is None


def test_pan_panel_coupled_records_driver():
    """A cleanly coupled panel records cis_dosage_driver=pan_panel_correlation (provenance for the path)."""
    cn, tpm = _coupled_panel(noise=0.3)
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] == "cn_dosage_coupled_strong"
    assert s["cis_dosage_driver"] == "pan_panel_correlation"


def test_data_unavailable_when_too_few_lines():
    """Fewer than min_cell_lines (50) jointly-measured lines → data_unavailable (wide-CI guard)."""
    cn, tpm = _coupled_panel(n=20)
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] == "data_unavailable"
    assert s["n_cell_lines_evaluated"] == 20


def test_only_jointly_measured_lines_are_evaluated():
    """Lines with CN-only or TPM-only are excluded from the evaluated universe."""
    cn, tpm = _coupled_panel(n=120)
    cn["ACH-99990"] = 2.5  # CN-only, no TPM
    tpm["ACH-99991"] = 8.0  # TPM-only, no CN
    s = compute_cis_dosage(cn, tpm)
    assert s["n_cell_lines_evaluated"] == 120  # the two singletons dropped


def test_build_merged_data_intersects_and_attaches_lineage():
    """figures.build_merged_data: evaluated = CN ∩ TPM; lineage from model_metadata, else 'unknown'."""
    from methods.depmap_cis_dosage.figures import build_merged_data

    cn = {"ACH-1": 2.0, "ACH-2": 1.0, "ACH-3": 3.0}  # ACH-3 has no TPM → dropped
    tpm = {"ACH-1": 8.0, "ACH-2": 5.0, "ACH-9": 4.0}  # ACH-9 has no CN → dropped
    mm = {"ACH-1": {"OncotreeLineage": "Bowel"}}  # ACH-2 missing → 'unknown'
    merged = build_merged_data(cn, tpm, mm)
    assert [m["cell_line_id"] for m in merged] == ["ACH-1", "ACH-2"]  # sorted intersection
    assert merged[0]["lineage"] == "Bowel" and merged[1]["lineage"] == "unknown"
    assert merged[0]["relative_cn"] == 2.0 and merged[0]["tpm_logp1"] == 8.0


# --- LINEAGE-CONFOUND control + cis_dosage_direction (round-2 panel calibration 2026-09-12) ------------


def _lineage_confounded_amp_panel(seed=21):
    """CDH1-analog: the amplified lines are ONE lineage that expresses the gene highly anyway.

    Live CDH1 (26Q1): pan-panel amplified-vs-neutral median delta +3.26 log2TPM, but the WITHIN-lineage
    delta is -0.70 — the 56 CN-gained lines are epithelial and the comparator largely is not.
    """
    import random

    rng = random.Random(seed)
    cn, tpm, lineage = {}, {}, {}
    i = 0
    for _ in range(30):  # amplified, all epithelial, high expression
        m = f"ACH-{i:05d}"
        cn[m], tpm[m], lineage[m] = rng.uniform(2.0, 5.0), 9.0 + rng.uniform(-0.4, 0.4), "Epithelial"
        i += 1
    for _ in range(40):  # SAME lineage, copy-neutral, expression just as high → within-lineage delta ~0
        m = f"ACH-{i:05d}"
        cn[m], tpm[m], lineage[m] = rng.uniform(0.8, 1.4), 8.9 + rng.uniform(-0.4, 0.4), "Epithelial"
        i += 1
    for _ in range(300):  # other lineages: copy-neutral AND non-expressing (they create the pan delta)
        m = f"ACH-{i:05d}"
        cn[m], tpm[m], lineage[m] = rng.uniform(0.8, 1.4), 5.0 + rng.uniform(-0.8, 0.8), "Other"
        i += 1
    return cn, tpm, lineage


def test_focal_amp_escape_blocked_when_subset_delta_is_lineage_confounded():
    """REGRESSION (CDH1 2026-09-12): the escape must NOT fire on a lineage-restriction artifact.

    Pan-panel the amplified subset over-expresses hugely, but within lineage the delta vanishes, so the
    contrast measured LINEAGE, not cis-dosage. CDH1 read cn_dosage_coupled_strong /
    focal_amplification_subset on exactly this shape.
    """
    cn, tpm, lineage = _lineage_confounded_amp_panel()
    s = compute_cis_dosage(cn, tpm, lineage_by_model=lineage)
    assert s["subset_delta_log2tpm_amplified_vs_neutral"] >= 1.0  # the pan-panel delta IS large
    assert s["subset_within_lineage_delta_log2tpm"] < 1.0  # but it collapses within lineage
    assert s["cis_dosage_class"] == "cn_dosage_uncoupled"
    assert s["cis_dosage_driver"] is None
    assert s["cis_dosage_direction"] is None  # direction is only meaningful for a coupled class


def test_lineage_control_is_only_applied_when_labels_are_supplied():
    """No lineage labels → the escape behaves exactly as in v0.1.0 (no silent behaviour change).

    Same confounded panel as above: without labels the method cannot see the confound and honestly
    reports the uncontrolled call, with the control fields left None.
    """
    cn, tpm, _lineage = _lineage_confounded_amp_panel()
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_driver"] == "focal_amplification_subset"
    assert s["cis_dosage_class"] in ("cn_dosage_coupled_strong", "cn_dosage_coupled_moderate")
    assert s["subset_within_lineage_delta_log2tpm"] is None
    assert s["subset_n_lineages_compared"] is None


def test_focal_amp_escape_survives_lineage_control_for_a_genuine_amplicon():
    """ERBB2-analog: the amplified subset over-expresses WITHIN every lineage (+1.70 within vs +1.64 pan
    live), so the lineage-controlled escape must still promote it. Guards against over-correction."""
    import random

    rng = random.Random(23)
    cn, tpm, lineage = {}, {}, {}
    i = 0
    for lin, base in (("Lung", 5.0), ("Breast", 6.0), ("Bowel", 4.0)):
        for _ in range(15):  # amplified in each lineage, +2 log2TPM over its OWN lineage baseline
            m = f"ACH-{i:05d}"
            cn[m], tpm[m], lineage[m] = rng.uniform(2.0, 6.0), base + 2.0 + rng.uniform(-0.3, 0.3), lin
            i += 1
        for _ in range(60):
            m = f"ACH-{i:05d}"
            cn[m], tpm[m], lineage[m] = rng.uniform(0.8, 1.45), base + rng.uniform(-0.3, 0.3), lin
            i += 1
    s = compute_cis_dosage(cn, tpm, lineage_by_model=lineage)
    assert s["cis_dosage_class"] in ("cn_dosage_coupled_strong", "cn_dosage_coupled_moderate")
    assert s["subset_within_lineage_delta_log2tpm"] >= 1.0
    assert s["subset_n_lineages_compared"] == 3
    assert s["cis_dosage_direction"] == "amplification_coupled"
    assert s["cis_dosage_direction_basis"] == "amplified_vs_deleted_contrast"


def test_direction_is_deletion_coupled_for_a_deleted_suppressor():
    """DIRECTION leg (round-2 panel: BRCA1/APC/STK11/NF1/CDH1/RASSF1 all read cn_dosage_coupled_* while
    the literature calls them LOSS-of-function). A panel whose coupling is carried by DELETED lines
    under-expressing (CDKN2A live: amp +1.46 / del -4.04 within lineage) must read deletion_coupled."""
    import random

    rng = random.Random(29)
    cn, tpm = {}, {}
    i = 0
    for _ in range(120):  # deleted lines, strongly under-expressed
        m = f"ACH-{i:05d}"
        cn[m], tpm[m] = rng.uniform(0.1, 0.7), 2.0 + rng.uniform(-0.4, 0.4)
        i += 1
    for _ in range(200):  # copy-neutral body
        m = f"ACH-{i:05d}"
        cn[m], tpm[m] = rng.uniform(0.8, 1.45), 6.0 + rng.uniform(-0.4, 0.4)
        i += 1
    s = compute_cis_dosage(cn, tpm)
    assert s["cis_dosage_class"] in ("cn_dosage_coupled_strong", "cn_dosage_coupled_moderate")
    assert s["cis_dosage_direction"] == "deletion_coupled"
    assert s["n_deleted"] == 120
    assert s["deleted_subset_delta_log2tpm"] <= -1.0
    assert s["deleted_subset_mannwhitney_p"] <= 0.01


def test_direction_weighs_effect_by_arm_prevalence():
    """When BOTH arms carry a same-signed effect, the winner is |delta| * sqrt(n_arm) — the arms' own
    Mann-Whitney z scaling. Magnitude alone mislabels PTEN (+1.06 on 15 amplified vs -0.76 on 338
    deleted); n alone mislabels MITF (2.30 on 60 vs -0.70 on 369). Here the small-but-larger amplified
    arm (delta ~2, n=25) must LOSE to the prevalent deleted arm (delta ~-1, n=400)."""
    import random

    rng = random.Random(31)
    cn, tpm = {}, {}
    i = 0
    for _ in range(25):
        m = f"ACH-{i:05d}"
        cn[m], tpm[m] = rng.uniform(2.0, 4.0), 8.0 + rng.uniform(-0.3, 0.3)
        i += 1
    for _ in range(400):
        m = f"ACH-{i:05d}"
        cn[m], tpm[m] = rng.uniform(0.2, 0.7), 5.0 + rng.uniform(-0.3, 0.3)
        i += 1
    for _ in range(200):
        m = f"ACH-{i:05d}"
        cn[m], tpm[m] = rng.uniform(0.8, 1.45), 6.0 + rng.uniform(-0.3, 0.3)
        i += 1
    s = compute_cis_dosage(cn, tpm)
    assert s["subset_delta_log2tpm_amplified_vs_neutral"] > 1.0  # amplified arm has the BIGGER delta
    assert s["deleted_subset_delta_log2tpm"] < -0.5  # deleted arm is smaller but far more prevalent
    assert s["cis_dosage_direction"] == "deletion_coupled"


def test_direction_falls_back_to_cn_distribution_asymmetry_when_no_arm_is_powered():
    """A coupled panel with neither a 20-line amplified nor a 20-line deleted arm (CN varies only in the
    0.8-1.45 band) still needs a direction; it comes from which CN tail carries the variation, measured
    off the panel MEDIAN so the fallback is scale-free (relative CN ~1.0, TCGA GISTIC ~0)."""
    cn, tpm = {}, {}
    for i in range(140):
        m = f"ACH-{i:05d}"
        c = 0.8 + 0.65 * (i / 139)
        cn[m], tpm[m] = c, 4.0 * c
    s = compute_cis_dosage(cn, tpm)
    assert s["n_amplified"] == 0 and s["n_deleted"] == 0
    assert s["cis_dosage_direction_basis"] == "cn_distribution_asymmetry"
    assert s["cis_dosage_direction"] in ("amplification_coupled", "deletion_coupled")
