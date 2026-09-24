#!/usr/bin/env python3
"""Quick test script to generate sample figures for tcga_spliceseq_psi.

Run from the repo root:
    PYTHONPATH="$PWD" python methods/onc_methods/tcga_spliceseq_psi/test_figures.py

Requires TARGET_CONTRACTS_PATH environment variable pointing to the
rnd-computational-biology-oncology-target-contracts repo for styling.

Output goes to /tmp/tcga_splicing_figures/
"""

from pathlib import Path
import os
import random

random.seed(42)

# Sample data: AR splicing variability (AR-V7 is a clinically relevant splice variant)
TARGET = "AR"
INDICATION = "PRAD"

# AR has high splicing variability in prostate cancer
TARGET_PSI_STD_INDICATION = 0.28  # High variability
N_VARIABLE_EVENTS_INDICATION = 5
N_SPLICE_EVENTS_INDICATION = 12

# Pan-cancer AR splicing is lower
TARGET_PSI_STD_PANCANCER = 0.15
N_VARIABLE_EVENTS_PANCANCER = 2
N_SPLICE_EVENTS_PANCANCER = 12

# Top variably spliced genes in PRAD (max PSI std)
PRAD_SPLICE_GENES = [
    ("FGFR2", 0.35),
    ("AR", TARGET_PSI_STD_INDICATION),
    ("CD44", 0.25),
    ("EGFR", 0.22),
    ("MET", 0.20),
    ("NTRK1", 0.18),
    ("ERBB2", 0.16),
    ("BRAF", 0.14),
    ("KIT", 0.12),
    ("RET", 0.11),
]
PRAD_SPLICE_GENES += [(f"GENE_{i}", random.uniform(0.05, 0.10)) for i in range(200)]

# Pan-cancer splicing variabilities
PANCANCER_SPLICE_GENES = [
    ("FGFR2", 0.32),
    ("MET", 0.28),
    ("CD44", 0.25),
    ("EGFR", 0.22),
    ("NTRK1", 0.20),
    ("ERBB2", 0.18),
    ("AR", TARGET_PSI_STD_PANCANCER),
    ("BRAF", 0.14),
    ("KIT", 0.12),
    ("RET", 0.11),
]
PANCANCER_SPLICE_GENES += [(f"GENE_{i}", random.uniform(0.05, 0.10)) for i in range(200)]


def main():
    # Import directly from figures module (avoids __init__.py's read.py import)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "figures",
        Path(__file__).parent / "figures.py"
    )
    figures_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(figures_module)
    emit_splicing_variability_pie = figures_module.emit_splicing_variability_pie
    emit_splicing_variability_stacked = figures_module.emit_splicing_variability_stacked

    # Use target-contracts repo from environment variable
    contracts_path = os.environ.get("TARGET_CONTRACTS_PATH")
    if not contracts_path:
        raise EnvironmentError(
            "TARGET_CONTRACTS_PATH environment variable not set. "
            "Point it to your local rnd-computational-biology-oncology-target-contracts repo."
        )
    TARGET_CONTRACTS = Path(contracts_path)

    out_dir = Path("/tmp/tcga_splicing_figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating figures in {out_dir}...")

    # === Test 1: AR splicing variability pie chart ===
    print(f"\n=== Test 1: AR splicing variability pie chart ===")
    print(f"  PRAD max PSI std: {TARGET_PSI_STD_INDICATION:.2f} ({N_VARIABLE_EVENTS_INDICATION}/{N_SPLICE_EVENTS_INDICATION} variable)")
    print(f"  Pan-cancer max PSI std: {TARGET_PSI_STD_PANCANCER:.2f} ({N_VARIABLE_EVENTS_PANCANCER}/{N_SPLICE_EVENTS_PANCANCER} variable)")

    svg1 = emit_splicing_variability_pie(
        TARGET,
        INDICATION,
        TARGET_PSI_STD_INDICATION,
        N_VARIABLE_EVENTS_INDICATION,
        N_SPLICE_EVENTS_INDICATION,
        PRAD_SPLICE_GENES,
        TARGET_PSI_STD_PANCANCER,
        N_VARIABLE_EVENTS_PANCANCER,
        N_SPLICE_EVENTS_PANCANCER,
        PANCANCER_SPLICE_GENES,
        out_dir,
        TARGET_CONTRACTS,
    )
    if svg1:
        print(f"  ✓ Splicing variability pie chart: {svg1}")

    # === Test 2: AR splicing variability stacked bar ===
    print(f"\n=== Test 2: AR splicing variability stacked bar ===")

    svg2 = emit_splicing_variability_stacked(
        TARGET,
        INDICATION,
        TARGET_PSI_STD_INDICATION,
        PRAD_SPLICE_GENES,
        TARGET_PSI_STD_PANCANCER,
        PANCANCER_SPLICE_GENES,
        out_dir,
        TARGET_CONTRACTS,
    )
    if svg2:
        print(f"  ✓ Splicing variability stacked bar: {svg2}")

    # === Test 3: MET splicing (another clinically relevant example) ===
    print(f"\n=== Test 3: MET splicing pie chart (METex14 skipping) ===")

    svg3 = emit_splicing_variability_pie(
        "MET",
        "NSCLC",
        0.20,  # MET has moderate splicing variability
        3,
        8,
        PRAD_SPLICE_GENES,  # Reusing for simplicity
        0.28,
        4,
        8,
        PANCANCER_SPLICE_GENES,
        out_dir,
        TARGET_CONTRACTS,
    )
    if svg3:
        print(f"  ✓ Splicing pie chart (MET): {svg3}")

    print(f"\nFigures saved to: {out_dir}")


if __name__ == "__main__":
    main()
