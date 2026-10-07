#!/usr/bin/env python3
"""Quick test script to generate sample figures for tcga_patient_cn.

Run from the repo root:
    PYTHONPATH="$PWD" python methods/onc_methods/tcga_patient_cn/test_figures.py

Requires TARGET_CONTRACTS_PATH environment variable pointing to the
rnd-computational-biology-oncology-target-contracts repo for styling.

Output goes to /tmp/tcga_cn_figures/
"""

from pathlib import Path
import os
import random

random.seed(42)

# Sample data: ERBB2 amplification in BRCA (realistic)
TARGET = "ERBB2"
INDICATION = "BRCA"

# Any-level frequencies (GISTIC >=+1 or <=-1)
TARGET_AMP_ANY_INDICATION = 0.31  # 31% any gain in BRCA
TARGET_AMP_ANY_PANCANCER = 0.08   # 8% any gain pan-cancer
TARGET_DEL_ANY_INDICATION = 0.02  # 2% any loss (rare)
TARGET_DEL_ANY_PANCANCER = 0.03   # 3% any loss pan-cancer

# Focal frequencies (GISTIC +2 or -2)
TARGET_AMP_FOCAL_INDICATION = 0.11  # 11% high-level amp in BRCA (HER2+)
TARGET_AMP_FOCAL_PANCANCER = 0.03   # 3% high-level amp pan-cancer
TARGET_DEL_FOCAL_INDICATION = 0.005 # 0.5% homdel (very rare)
TARGET_DEL_FOCAL_PANCANCER = 0.008  # 0.8% homdel pan-cancer

# Top amplified genes in BRCA - any gain (>=+1)
BRCA_AMP_ANY_GENES = [
    ("MYC", 0.35),
    ("ERBB2", TARGET_AMP_ANY_INDICATION),
    ("CCND1", 0.28),
    ("FGFR1", 0.18),
    ("PIK3CA", 0.15),
    ("MDM2", 0.12),
    ("EGFR", 0.10),
    ("CDK4", 0.09),
    ("MET", 0.08),
    ("KRAS", 0.06),
]
BRCA_AMP_ANY_GENES += [(f"GENE_{i}", random.uniform(0.01, 0.05)) for i in range(500)]

# Top amplified genes in BRCA - focal high-amp (+2)
BRCA_AMP_FOCAL_GENES = [
    ("MYC", 0.18),
    ("ERBB2", TARGET_AMP_FOCAL_INDICATION),
    ("CCND1", 0.12),
    ("MDM2", 0.08),
    ("FGFR1", 0.07),
    ("CDK4", 0.06),
    ("EGFR", 0.05),
    ("PIK3CA", 0.04),
    ("MET", 0.03),
    ("KRAS", 0.02),
]
BRCA_AMP_FOCAL_GENES += [(f"GENE_{i}", random.uniform(0.005, 0.02)) for i in range(500)]

# Pan-cancer amplification frequencies - any gain
PANCANCER_AMP_ANY_GENES = [
    ("MYC", 0.25),
    ("CCND1", 0.18),
    ("EGFR", 0.15),
    ("MDM2", 0.12),
    ("CDK4", 0.10),
    ("ERBB2", TARGET_AMP_ANY_PANCANCER),
    ("FGFR1", 0.07),
    ("MET", 0.065),
    ("PIK3CA", 0.06),
    ("KRAS", 0.055),
]
PANCANCER_AMP_ANY_GENES += [(f"GENE_{i}", random.uniform(0.01, 0.05)) for i in range(500)]

# Pan-cancer amplification frequencies - focal high-amp (+2)
PANCANCER_AMP_FOCAL_GENES = [
    ("MYC", 0.12),
    ("CCND1", 0.08),
    ("EGFR", 0.06),
    ("MDM2", 0.05),
    ("CDK4", 0.04),
    ("ERBB2", TARGET_AMP_FOCAL_PANCANCER),
    ("FGFR1", 0.025),
    ("MET", 0.02),
    ("PIK3CA", 0.018),
    ("KRAS", 0.015),
]
PANCANCER_AMP_FOCAL_GENES += [(f"GENE_{i}", random.uniform(0.005, 0.02)) for i in range(500)]

# Top deleted genes in BRCA - any loss (<=-1)
BRCA_DEL_ANY_GENES = [
    ("TP53", 0.35),
    ("CDKN2A", 0.25),
    ("PTEN", 0.18),
    ("RB1", 0.15),
    ("BRCA1", 0.12),
    ("BRCA2", 0.10),
    ("ATM", 0.08),
    ("NF1", 0.06),
    ("ARID1A", 0.05),
    ("ERBB2", TARGET_DEL_ANY_INDICATION),
]
BRCA_DEL_ANY_GENES += [(f"GENE_{i}", random.uniform(0.01, 0.04)) for i in range(500)]

# Top deleted genes in BRCA - focal homdel (-2)
BRCA_DEL_FOCAL_GENES = [
    ("CDKN2A", 0.15),
    ("PTEN", 0.08),
    ("RB1", 0.06),
    ("TP53", 0.05),
    ("BRCA1", 0.04),
    ("BRCA2", 0.035),
    ("ATM", 0.03),
    ("NF1", 0.02),
    ("ARID1A", 0.015),
    ("ERBB2", TARGET_DEL_FOCAL_INDICATION),
]
BRCA_DEL_FOCAL_GENES += [(f"GENE_{i}", random.uniform(0.002, 0.01)) for i in range(500)]

# Pan-cancer deletion frequencies - any loss
PANCANCER_DEL_ANY_GENES = [
    ("TP53", 0.30),
    ("CDKN2A", 0.28),
    ("PTEN", 0.22),
    ("RB1", 0.18),
    ("BRCA2", 0.12),
    ("ATM", 0.10),
    ("NF1", 0.08),
    ("ARID1A", 0.07),
    ("BRCA1", 0.06),
    ("ERBB2", TARGET_DEL_ANY_PANCANCER),
]
PANCANCER_DEL_ANY_GENES += [(f"GENE_{i}", random.uniform(0.01, 0.05)) for i in range(500)]

# Pan-cancer deletion frequencies - focal homdel (-2)
PANCANCER_DEL_FOCAL_GENES = [
    ("CDKN2A", 0.18),
    ("PTEN", 0.10),
    ("RB1", 0.07),
    ("TP53", 0.04),
    ("BRCA2", 0.035),
    ("ATM", 0.03),
    ("NF1", 0.025),
    ("ARID1A", 0.02),
    ("BRCA1", 0.018),
    ("ERBB2", TARGET_DEL_FOCAL_PANCANCER),
]
PANCANCER_DEL_FOCAL_GENES += [(f"GENE_{i}", random.uniform(0.002, 0.015)) for i in range(500)]


def main():
    from onc_methods.tcga_patient_cn.cli import (
        emit_cn_frequency_pie,
        emit_cn_frequency_stacked,
        emit_plot_data,
    )

    # Use target-contracts repo from environment variable
    contracts_path = os.environ.get("TARGET_CONTRACTS_PATH")
    if not contracts_path:
        raise EnvironmentError(
            "TARGET_CONTRACTS_PATH environment variable not set. "
            "Point it to your local rnd-computational-biology-oncology-target-contracts repo."
        )
    TARGET_CONTRACTS = Path(contracts_path)

    out_dir = Path("/tmp/tcga_cn_figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating figures in {out_dir}...")

    # === Test 1: ERBB2 amplification pie chart ===
    print(f"\n=== Test 1: ERBB2 amplification pie chart ===")
    print(f"  BRCA any gain: {TARGET_AMP_ANY_INDICATION*100:.1f}%, focal +2: {TARGET_AMP_FOCAL_INDICATION*100:.1f}%")
    print(f"  Pan-cancer any gain: {TARGET_AMP_ANY_PANCANCER*100:.1f}%, focal +2: {TARGET_AMP_FOCAL_PANCANCER*100:.1f}%")

    svg1 = emit_cn_frequency_pie(
        TARGET,
        INDICATION,
        TARGET_AMP_ANY_INDICATION,
        TARGET_AMP_FOCAL_INDICATION,
        BRCA_AMP_ANY_GENES,
        TARGET_AMP_ANY_PANCANCER,
        TARGET_AMP_FOCAL_PANCANCER,
        PANCANCER_AMP_ANY_GENES,
        out_dir,
        TARGET_CONTRACTS,
        cn_type="amplification",
    )
    if svg1:
        print(f"  ✓ Amplification pie chart: {svg1}")

    # === Test 2: ERBB2 amplification stacked bar (any gain ≥+1) ===
    print(f"\n=== Test 2: ERBB2 amplification stacked bar (any gain ≥+1) ===")

    svg2 = emit_cn_frequency_stacked(
        TARGET,
        INDICATION,
        TARGET_AMP_ANY_INDICATION,
        BRCA_AMP_ANY_GENES,
        TARGET_AMP_ANY_PANCANCER,
        PANCANCER_AMP_ANY_GENES,
        out_dir,
        TARGET_CONTRACTS,
        cn_type="amplification",
    )
    if svg2:
        print(f"  ✓ Amplification stacked: {svg2}")

    # === Test 3: ERBB2 deletion pie chart (rare case) ===
    print(f"\n=== Test 3: ERBB2 deletion pie chart ===")
    print(f"  BRCA any loss: {TARGET_DEL_ANY_INDICATION*100:.1f}%, focal -2: {TARGET_DEL_FOCAL_INDICATION*100:.1f}%")
    print(f"  Pan-cancer any loss: {TARGET_DEL_ANY_PANCANCER*100:.1f}%, focal -2: {TARGET_DEL_FOCAL_PANCANCER*100:.1f}%")

    svg3 = emit_cn_frequency_pie(
        TARGET,
        INDICATION,
        TARGET_DEL_ANY_INDICATION,
        TARGET_DEL_FOCAL_INDICATION,
        BRCA_DEL_ANY_GENES,
        TARGET_DEL_ANY_PANCANCER,
        TARGET_DEL_FOCAL_PANCANCER,
        PANCANCER_DEL_ANY_GENES,
        out_dir,
        TARGET_CONTRACTS,
        cn_type="deletion",
    )
    if svg3:
        print(f"  ✓ Deletion pie chart: {svg3}")

    # === Test 4: ERBB2 deletion stacked bar (any loss ≤-1) ===
    print(f"\n=== Test 4: ERBB2 deletion stacked bar (any loss ≤-1) ===")

    svg4 = emit_cn_frequency_stacked(
        TARGET,
        INDICATION,
        TARGET_DEL_ANY_INDICATION,
        BRCA_DEL_ANY_GENES,
        TARGET_DEL_ANY_PANCANCER,
        PANCANCER_DEL_ANY_GENES,
        out_dir,
        TARGET_CONTRACTS,
        cn_type="deletion",
    )
    if svg4:
        print(f"  ✓ Deletion stacked: {svg4}")

    # === Test 5: Save plot data ===
    parquet_path = emit_plot_data(
        TARGET,
        INDICATION,
        TARGET_AMP_ANY_INDICATION,
        TARGET_DEL_ANY_INDICATION,
        BRCA_AMP_ANY_GENES,
        BRCA_DEL_ANY_GENES,
        out_dir,
    )
    print(f"\n  ✓ Plot data: {parquet_path}")

    print(f"\nFigures saved to: {out_dir}")


if __name__ == "__main__":
    main()
