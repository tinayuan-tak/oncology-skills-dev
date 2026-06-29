"""Shared Takeda oncology framework plotting palette + helpers.

Every card method imports from here to ensure visual consistency across cards.
Combined with takeda_oncology.mplstyle (loaded via plt.style.use), this defines
the framework's complete visual identity.

Usage in a method CLI:
    from pathlib import Path
    import matplotlib.pyplot as plt
    import sys

    contracts_root = Path("/path/to/target-contracts")
    plt.style.use(contracts_root / "plot_styles" / "takeda_oncology.mplstyle")
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    from takeda_palette import LINEAGE_COLORS, get_lineage_color, REFLINE_NEUTRAL
"""

from __future__ import annotations

# ===== Okabe-Ito 8-color palette (colorblind-safe; deuteranopia/protanopia compatible) =====
OKABE_ITO = [
    "#E69F00",   # orange
    "#56B4E9",   # sky blue
    "#009E73",   # bluish green
    "#F0E442",   # yellow
    "#0072B2",   # blue
    "#D55E00",   # vermillion
    "#CC79A7",   # reddish purple
    "#000000",   # black
]

# ===== Canonical lineage → fixed color map (consistency across all cards) =====
# Top-5 priority indications get distinct stable colors. Other lineages map to grey.
# When a card needs more than 5 lineage colors, fall back to OKABE_ITO[5:] for additional.
LINEAGE_COLORS = {
    # Keys MATCH DepMap Model.csv OncotreeLineage categorical exactly so
    # `get_lineage_color(meta["OncotreeLineage"])` works without an adapter.
    # DepMap's OncotreeLineage doesn't distinguish NSCLC vs SCLC at this level
    # (both → "Lung"); use OncotreeSubtype for finer histology when needed.
    "Bowel": "#D55E00",              # vermillion — COADREAD anchor
    "Lung": "#E69F00",               # orange — NSCLC + SCLC (collapsed in OncotreeLineage)
    "Pancreas": "#009E73",           # bluish green — PDAC anchor
    "Stomach": "#CC79A7",            # reddish purple — GC anchor
    # Secondary lineages — applied when present in a panel
    "Breast": "#56B4E9",
    "Ovary/Fallopian Tube": "#9467BD",
    "Prostate": "#8C564B",
    "Kidney": "#E377C2",
    "Skin": "#7F7F7F",
    "Esophagus/Stomach": "#F0E442",  # yellow — distinct from Stomach
    "Liver": "#999933",
    "Biliary Tract": "#117733",
    # Lowercase aliases for backward-compatibility with older code that built
    # synthetic lineage strings using palette-style keys. Resolve to same colors.
    "colorectal": "#D55E00",
    "lung_nsclc": "#E69F00",
    "lung_sclc": "#0072B2",
    "pancreas": "#009E73",
    "gastric": "#CC79A7",
    "breast": "#56B4E9",
    "skin": "#7F7F7F",
}
LINEAGE_DEFAULT_COLOR = "#999999"   # grey — fallback for un-mapped lineages

# ===== Reference-line styles for figure overlays =====
REFLINE_NEUTRAL = {
    "color": "#666666",
    "linestyle": "--",
    "linewidth": 1.0,
    "alpha": 0.7,
}
REFLINE_KILLER = {                  # for "this threshold kills the modality"
    "color": "#B22222",             # deep red
    "linestyle": "--",
    "linewidth": 1.5,
    "alpha": 0.9,
}
REFLINE_GOOD = {                    # for "this threshold supports the modality"
    "color": "#228B22",             # forest green
    "linestyle": ":",
    "linewidth": 1.5,
    "alpha": 0.9,
}
REFLINE_NOMINAL = {                 # neutral guideline (e.g., Chronos = 0)
    "color": "#999999",
    "linestyle": "-",
    "linewidth": 0.8,
    "alpha": 0.5,
}

# ===== Diverging color map for effect-size / log2FC visualizations =====
DIVERGING_CMAP = "RdBu_r"           # red-blue reversed; red=negative, blue=positive
# ===== Sequential color map for Chronos heatmaps =====
SEQUENTIAL_DEPENDENCY_CMAP = "viridis"


def get_lineage_color(lineage: str) -> str:
    """Look up the canonical color for a lineage. Falls back to LINEAGE_DEFAULT_COLOR."""
    return LINEAGE_COLORS.get(lineage, LINEAGE_DEFAULT_COLOR)


# ===== Standard figure sizes (inches) — Cell/Nature conventions =====
FIGSIZE_SINGLE_COLUMN = (3.5, 2.625)
FIGSIZE_SINGLE_COLUMN_TALL = (3.5, 4.0)
FIGSIZE_DOUBLE_COLUMN = (7.0, 3.5)
FIGSIZE_DOUBLE_COLUMN_TALL = (7.0, 5.0)
FIGSIZE_SQUARE = (3.5, 3.5)


# ===== Chronos thresholds (DepMap-published conventions, used as reference lines) =====
CHRONOS_STRONG_DEPENDENCY = -1.0    # "common essentials" cutoff per DepMap
CHRONOS_MODERATE_DEPENDENCY = -0.5
CHRONOS_NO_DEPENDENCY = 0.0


# ===== Provenance text helper =====
def figure_metadata_block(card_id: str, framework_version: str,
                           target: str, indication: str,
                           generated_at: str) -> dict:
    """Return a small metadata dict for embedding into SVG <title>/<desc> for audit trail.
    Used by matplotlib via fig.suptitle or fig._suptitle, or via SVG post-processing."""
    return {
        "card_id": card_id,
        "framework_version": framework_version,
        "target": target,
        "indication": indication,
        "generated_at": generated_at,
    }
