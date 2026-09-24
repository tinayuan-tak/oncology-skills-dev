#!/usr/bin/env python3
"""Quick test script to generate sample figures for tcga_fusion_consensus.

Run from the repo root:
    PYTHONPATH="$PWD" python methods/onc_methods/tcga_fusion_consensus/test_figures.py

Requires TARGET_CONTRACTS_PATH environment variable pointing to the
rnd-computational-biology-oncology-target-contracts repo for styling.

Output goes to /tmp/tcga_fusion_figures/
"""

from pathlib import Path
import os

# Sample data: ALK fusions in LUAD (realistic)
TARGET = "ALK"
INDICATION = "LUAD"

# ALK is fused in ~5% of LUAD patients
TARGET_FREQ_INDICATION = 0.05  # 5% in LUAD
N_SAMPLES_INDICATION = 25
N_ASSAYED_INDICATION = 500

# Pan-cancer ALK fusion is lower
TARGET_FREQ_PANCANCER = 0.008  # 0.8% pan-cancer
N_SAMPLES_PANCANCER = 80
N_ASSAYED_PANCANCER = 10000

# Top fused genes in LUAD
LUAD_FUSION_GENES = [
    ("ALK", 0.05),
    ("ROS1", 0.02),
    ("RET", 0.015),
    ("NTRK1", 0.01),
    ("FGFR3", 0.008),
    ("MET", 0.006),
    ("BRAF", 0.005),
    ("EGFR", 0.003),
    ("ERBB2", 0.002),
    ("KRAS", 0.001),
]

# Pan-cancer fusion frequencies
PANCANCER_FUSION_GENES = [
    ("TMPRSS2", 0.025),  # PRAD
    ("BCR", 0.015),      # CML
    ("ETV6", 0.012),
    ("EWSR1", 0.010),
    ("ALK", TARGET_FREQ_PANCANCER),
    ("ROS1", 0.006),
    ("PML", 0.005),
    ("RUNX1", 0.004),
    ("MLL", 0.003),
    ("RET", 0.002),
]


def main():
    # Import directly from figures module (avoids __init__.py's read.py import)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "figures",
        Path(__file__).parent / "figures.py"
    )
    figures_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(figures_module)
    emit_fusion_frequency_pie = figures_module.emit_fusion_frequency_pie

    # Use target-contracts repo from environment variable
    contracts_path = os.environ.get("TARGET_CONTRACTS_PATH")
    if not contracts_path:
        raise EnvironmentError(
            "TARGET_CONTRACTS_PATH environment variable not set. "
            "Point it to your local rnd-computational-biology-oncology-target-contracts repo."
        )
    TARGET_CONTRACTS = Path(contracts_path)

    out_dir = Path("/tmp/tcga_fusion_figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating figures in {out_dir}...")

    # === Test 1: ALK fusion pie chart ===
    print(f"\n=== Test 1: ALK fusion pie chart ===")
    print(f"  LUAD: {TARGET_FREQ_INDICATION*100:.1f}% ({N_SAMPLES_INDICATION}/{N_ASSAYED_INDICATION})")
    print(f"  Pan-cancer: {TARGET_FREQ_PANCANCER*100:.2f}% ({N_SAMPLES_PANCANCER}/{N_ASSAYED_PANCANCER})")

    svg1 = emit_fusion_frequency_pie(
        TARGET,
        INDICATION,
        TARGET_FREQ_INDICATION,
        N_SAMPLES_INDICATION,
        N_ASSAYED_INDICATION,
        LUAD_FUSION_GENES,
        TARGET_FREQ_PANCANCER,
        N_SAMPLES_PANCANCER,
        N_ASSAYED_PANCANCER,
        PANCANCER_FUSION_GENES,
        out_dir,
        TARGET_CONTRACTS,
    )
    if svg1:
        print(f"  ✓ Fusion pie chart: {svg1}")

    # === Test 2: NTRK1 fusion (rarer) ===
    print(f"\n=== Test 2: NTRK1 fusion pie chart (rare) ===")
    ntrk1_freq_ind = 0.01
    ntrk1_freq_pan = 0.002

    luad_with_ntrk1 = LUAD_FUSION_GENES.copy()
    pancancer_with_ntrk1 = PANCANCER_FUSION_GENES + [("NTRK1", ntrk1_freq_pan)]

    svg2 = emit_fusion_frequency_pie(
        "NTRK1",
        INDICATION,
        ntrk1_freq_ind,
        5,
        500,
        luad_with_ntrk1,
        ntrk1_freq_pan,
        20,
        10000,
        pancancer_with_ntrk1,
        out_dir,
        TARGET_CONTRACTS,
    )
    if svg2:
        print(f"  ✓ Fusion pie chart (NTRK1): {svg2}")

    print(f"\nFigures saved to: {out_dir}")


if __name__ == "__main__":
    main()
