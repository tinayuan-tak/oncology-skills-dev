"""Regression: read._compute._keep must partition arms at the SAME focal cut the kernel uses.

Bug: the `_keep` closure routed lines with relative CN > FOCAL_AMP (1.5) into the amplified arm,
but compute_cn_stratification classifies amplified at FOCAL_AMP_HIGH (2.0). In the RUNG-2 ladder path
(lineage-mutant vs PAN-WT), a shallow-gain (1.5–2.0) out-of-lineage line was therefore sent to the
lineage-restricted amplified arm, failed the `m in mut_models` check, and was DROPPED from the pan-WT
comparator — even though the kernel counts it as neutral. That shrinks/biases the WT arm and hence
delta_chronos. The fix aligns `_keep` to FOCAL_AMP_HIGH so shallow-gain lines land in the (pan) WT arm.

Hermetic: the DepMap Chronos + CN loaders are monkeypatched with a synthetic panel engineered to
force RUNG 2, with 10 shallow-gain (cn=1.7) out-of-lineage lines whose presence in n_neutral is the
tell (35 without the fix, 45 with it)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_cn_dependency import read as _r  # noqa: E402


def _synthetic_panel():
    import random
    rng = random.Random(7)
    chronos, cn, meta = {}, {}, {}
    i = 0
    # 6 in-lineage (Bowel) FOCAL-amp dependent lines (cn=3.0) — enough mutants, but NO in-lineage
    # neutral → RUNG 1 (within-lineage) is WT-underpowered → falls through to RUNG 2.
    for _ in range(6):
        m = f"ACH-{i:05d}"; chronos[m] = -1.2 + rng.uniform(-0.05, 0.05); cn[m] = 3.0
        meta[m] = {"OncotreeLineage": "Bowel"}; i += 1
    # 35 out-of-lineage clearly-neutral lines (cn=1.0) — the uncontested pan-WT comparator.
    for _ in range(35):
        m = f"ACH-{i:05d}"; chronos[m] = 0.0 + rng.uniform(-0.05, 0.05); cn[m] = 1.0
        meta[m] = {"OncotreeLineage": "Lung"}; i += 1
    # 10 out-of-lineage SHALLOW-GAIN lines (cn=1.7): kernel-neutral (<2.0). These belong in the WT
    # arm. Under the bug they were misrouted to the amplified arm and dropped.
    for _ in range(10):
        m = f"ACH-{i:05d}"; chronos[m] = 0.0 + rng.uniform(-0.05, 0.05); cn[m] = 1.7
        meta[m] = {"OncotreeLineage": "Lung"}; i += 1
    return chronos, cn, meta


def test_shallow_gain_stays_in_pan_wt_arm(monkeypatch):
    chronos, cn, meta = _synthetic_panel()

    from methods.depmap_chronos_distribution import cli as c1cli
    from methods.depmap_cn_distribution import cli as cncli
    monkeypatch.setattr(c1cli, "load_depmap_files",
                        lambda release_pin, target_symbol: (chronos, meta, []))
    monkeypatch.setattr(cncli, "load_cn_files",
                        lambda release_pin, target_symbol: (cn, {}, "WES", []))

    s = _r.read_cn_stratified_dependency("ERBB2", "COADREAD")

    # RUNG 2 fired (lineage mutant vs pan WT).
    assert s["evidence_scope"] == "within_indication_mut_vs_pan_wt"
    assert s["n_amplified"] == 6                      # only the cn=3.0 focal lines are amplified
    # THE REGRESSION: all 45 kernel-neutral lines (35 @1.0 + 10 shallow @1.7) are in the WT arm.
    # With the pre-fix FOCAL_AMP(1.5) threshold this was 35 (the shallow-gain 10 were dropped).
    assert s["n_neutral"] == 45
    assert s["cn_stratification_class"] == "amplified_strongly_dependent"
    assert s["amplification_threshold_relative_cn"] == 2.0
