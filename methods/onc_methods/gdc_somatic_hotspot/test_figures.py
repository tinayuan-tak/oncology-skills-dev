#!/usr/bin/env python3
"""Quick test script to generate sample figures for gdc_somatic_hotspot.

Run from the repo root:
    PYTHONPATH="$PWD" python methods/onc_methods/gdc_somatic_hotspot/test_figures.py

Requires TARGET_CONTRACTS_PATH environment variable pointing to the
rnd-computational-biology-oncology-target-contracts repo for styling.

Output goes to /tmp/gdc_hotspot_figures/
"""

from pathlib import Path
import os
import random

random.seed(42)

# Sample data (realistic KRAS in COADREAD)
SAMPLE_HOTSPOTS = [
    {"protein_change": "p.G12D", "frequency": 0.142, "n_samples": 58},
    {"protein_change": "p.G12V", "frequency": 0.098, "n_samples": 40},
    {"protein_change": "p.G13D", "frequency": 0.071, "n_samples": 29},
    {"protein_change": "p.G12C", "frequency": 0.024, "n_samples": 10},
    {"protein_change": "p.G12A", "frequency": 0.017, "n_samples": 7},
    {"protein_change": "p.G12S", "frequency": 0.012, "n_samples": 5},
    {"protein_change": "p.Q61H", "frequency": 0.010, "n_samples": 4},
    {"protein_change": "p.A146T", "frequency": 0.007, "n_samples": 3},
]

TARGET = "KRAS"
INDICATION = "COADREAD"
TARGET_FREQUENCY = 0.42  # KRAS is highly mutated in CRC

# Top drivers in CRC (indication-specific)
COADREAD_GENES = [
    ("APC", 0.75),
    ("TP53", 0.55),
    ("KRAS", TARGET_FREQUENCY),
    ("PIK3CA", 0.18),
    ("SMAD4", 0.12),
    ("FBXW7", 0.11),
    ("TCF7L2", 0.10),
    ("NRAS", 0.08),
    ("BRAF", 0.07),
    ("SOX9", 0.06),
]
COADREAD_GENES += [(f"GENE_{i}", random.uniform(0.002, 0.05)) for i in range(1000)]

# Pan-cancer gene frequencies
PAN_CANCER_GENES = [
    ("TP53", 0.42),
    ("PIK3CA", 0.18),
    ("KRAS", 0.15),
    ("PTEN", 0.12),
    ("APC", 0.11),
    ("ARID1A", 0.10),
    ("KMT2D", 0.09),
    ("BRAF", 0.085),
    ("FBXW7", 0.08),
    ("KMT2C", 0.078),
    ("ATM", 0.075),
    ("SMAD4", 0.072),
    ("NF1", 0.07),
    ("RB1", 0.068),
    ("CDKN2A", 0.065),
    ("CTNNB1", 0.063),
    ("EGFR", 0.06),
    ("FAT1", 0.058),
    ("NOTCH1", 0.057),
    ("ERBB2", 0.055),
    ("NFE2L2", 0.054),
    ("STK11", 0.053),
    ("KEAP1", 0.052),
    ("SMARCA4", 0.051),
    ("CREBBP", 0.05),
]
PAN_CANCER_GENES += [(f"GENE_{i}", random.uniform(0.01, 0.049)) for i in range(500)]


def main():
    from methods.gdc_somatic_hotspot.cli import (
        emit_hotspot_lollipop,
        emit_mutation_frequency_stacked,
        emit_mutation_frequency_waterfall,
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

    out_dir = Path("/tmp/gdc_hotspot_figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating figures in {out_dir}...")

    # === Test 1: Hotspot lollipop ===
    print(f"\n=== Test 1: Hotspot lollipop ===")
    svg1 = emit_hotspot_lollipop(
        SAMPLE_HOTSPOTS,
        TARGET,
        INDICATION,
        out_dir,
        TARGET_CONTRACTS,
    )
    if svg1:
        print(f"  ✓ Hotspot lollipop: {svg1}")

    # === Test 2: KRAS stacked (frequent in both) ===
    print(f"\n=== Test 2: KRAS stacked figure ===")
    print(f"  COADREAD: {TARGET_FREQUENCY*100:.1f}%")
    print(f"  Pan-cancer: 15.0%")

    svg2 = emit_mutation_frequency_stacked(
        "KRAS",
        INDICATION,
        TARGET_FREQUENCY,  # 42% in COADREAD
        COADREAD_GENES,
        0.15,  # 15% pan-cancer
        PAN_CANCER_GENES,
        out_dir,
        TARGET_CONTRACTS,
    )
    if svg2:
        print(f"  ✓ Stacked figure (KRAS): {svg2}")

    # === Test 3: JAK2 stacked (rare in both) ===
    print(f"\n=== Test 3: JAK2 stacked figure ===")
    JAK2_COADREAD_FREQ = 0.01  # 1% in COADREAD (below threshold)
    JAK2_PANCANCER_FREQ = 0.03  # 3% pan-cancer (also below threshold)
    print(f"  COADREAD: {JAK2_COADREAD_FREQ*100:.1f}%")
    print(f"  Pan-cancer: {JAK2_PANCANCER_FREQ*100:.1f}%")

    coadread_with_jak2 = COADREAD_GENES + [("JAK2", JAK2_COADREAD_FREQ)]
    pancancer_with_jak2 = PAN_CANCER_GENES + [("JAK2", JAK2_PANCANCER_FREQ)]

    svg3 = emit_mutation_frequency_stacked(
        "JAK2",
        INDICATION,
        JAK2_COADREAD_FREQ,
        coadread_with_jak2,
        JAK2_PANCANCER_FREQ,
        pancancer_with_jak2,
        out_dir,
        TARGET_CONTRACTS,
    )
    if svg3:
        print(f"  ✓ Stacked figure (JAK2): {svg3}")

    # === Test 4: KRAS pie chart figure ===
    print(f"\n=== Test 4: KRAS pie chart figure ===")
    svg4 = emit_mutation_frequency_waterfall(
        "KRAS",
        INDICATION,
        TARGET_FREQUENCY,  # 42% in COADREAD
        COADREAD_GENES,
        0.15,  # 15% pan-cancer
        PAN_CANCER_GENES,
        out_dir,
        TARGET_CONTRACTS,
    )
    if svg4:
        print(f"  ✓ Pie chart figure (KRAS): {svg4}")

    # === Test 5: JAK2 pie chart (rare gene) ===
    print(f"\n=== Test 5: JAK2 pie chart figure ===")
    svg5 = emit_mutation_frequency_waterfall(
        "JAK2",
        INDICATION,
        JAK2_COADREAD_FREQ,
        coadread_with_jak2,
        JAK2_PANCANCER_FREQ,
        pancancer_with_jak2,
        out_dir,
        TARGET_CONTRACTS,
    )
    if svg5:
        print(f"  ✓ Pie chart figure (JAK2): {svg5}")

    # Save plot data
    parquet_path = emit_plot_data(
        SAMPLE_HOTSPOTS,
        TARGET,
        INDICATION,
        TARGET_FREQUENCY,
        COADREAD_GENES,
        out_dir,
    )
    print(f"\n  ✓ Plot data: {parquet_path}")

    print(f"\nFigures saved to: {out_dir}")


if __name__ == "__main__":
    main()
