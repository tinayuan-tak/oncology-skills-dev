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
# Priority-anchor lineages get stable, distinctive colors matched to indication
# focus areas. Extended coverage handles the ~28 OncotreeLineage values seen in
# DepMap 26Q1 (was ~12 explicitly mapped; missing lineages collided on default grey).
# Colors chosen from Okabe-Ito + Tol Colorblind + ColorBrewer for colorblind safety.
LINEAGE_COLORS = {
    # ==== Tier-1: priority-indication anchors (Okabe-Ito, high-recognition) ====
    "Bowel": "#D55E00",              # vermillion — COADREAD anchor
    "Lung": "#E69F00",               # orange — NSCLC + SCLC (collapsed in OncotreeLineage)
    "Pancreas": "#009E73",           # bluish green — PDAC anchor
    "Esophagus/Stomach": "#CC79A7",  # reddish purple — GC anchor (canonical OncotreeLineage)
    "Breast": "#56B4E9",             # sky blue

    # ==== Tier-2: common cancer types (Tol-Bright / ColorBrewer accents) ====
    "Liver": "#88CCEE",              # light blue-teal
    "CNS/Brain": "#332288",          # dark indigo (distinct from any blue tier-1)
    "Skin": "#DDCC77",               # tan
    "Ovary/Fallopian Tube": "#AA4499", # magenta-purple
    "Prostate": "#117733",           # dark green (distinct from Pancreas' bluish-green)
    "Kidney": "#882255",             # burgundy
    "Lymphoid": "#44AA99",           # teal
    "Myeloid": "#999933",            # olive
    "Bladder/Urinary Tract": "#661100", # dark brown-red

    # ==== Tier-3: less-common but present in panels ====
    "Head and Neck": "#6699CC",       # dusty blue
    "Bone": "#CC6677",                # rose
    "Soft Tissue": "#DDDDDD",         # very light grey (distinguishable from default)
    "Cervix": "#994455",              # muted plum
    "Uterus": "#EE99AA",              # pink
    "Thyroid": "#004488",             # deep navy
    "Biliary Tract": "#AA7744",       # amber-brown
    "Pleura": "#77AADD",              # pale steel-blue
    "Eye": "#BBCC33",                 # yellow-green
    "Peripheral Nervous System": "#DDDD77", # pale yellow-olive
    "Fibroblast": "#B0B0B0",          # medium grey (fibroblast controls)
    "Testis": "#6B4C93",              # violet
    "Ampulla of Vater": "#7FCC97",    # sea foam
    "Vulva/Vagina": "#EEBBEE",        # light pink
    "Normal": "#000000",              # black (normal cell line reference — always visible)
    "Muscle": "#663333",              # muted mahogany
    "Adrenal Gland": "#DD8855",       # copper

    # ==== Legacy lowercase aliases (backward-compat for synthetic-lineage code paths) ====
    "colorectal": "#D55E00",
    "lung_nsclc": "#E69F00",
    "lung_sclc": "#0072B2",
    "pancreas": "#009E73",
    "gastric": "#CC79A7",
    "breast": "#56B4E9",
    "skin": "#DDCC77",
    "Stomach": "#CC79A7",             # bare "Stomach" kept as legacy; real data uses "Esophagus/Stomach"
}
LINEAGE_DEFAULT_COLOR = "#999999"   # grey — used only when explicit fallback requested

# Extended palette for hash-based deterministic assignment of un-mapped lineages
# (colorblind-friendly; visually distinguishable from tier-1/2/3 mapped colors).
_HASH_FALLBACK_PALETTE = [
    "#5C4D66", "#3F5A50", "#8A5A44", "#4B738C", "#6E4A6E",
    "#8E7B39", "#3E7B7E", "#7A5E4A", "#5B7A4A", "#7E4A5B",
    "#4A7A6E", "#6E5B4A", "#4A6E7A", "#7A6E4A", "#4A4A7A",
]

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
    """Look up the canonical color for a lineage.

    Fallback order:
      1. Explicit LINEAGE_COLORS mapping (~35 lineages, curated colorblind-safe).
      2. Deterministic hash into _HASH_FALLBACK_PALETTE (15 colors) — same lineage
         always gets the same color across cards + across runs, but colors are
         DISTINCT from tier-1/2/3 mapped anchors so mapped-vs-fallback lineages
         don't collide visually.
      3. LINEAGE_DEFAULT_COLOR only for null/empty/None inputs.

    Previously fell back straight to grey — that caused legend collisions when
    2+ unmapped lineages appeared in the same figure (all rendered as #999999).
    """
    if not lineage or not isinstance(lineage, str):
        return LINEAGE_DEFAULT_COLOR
    if lineage in LINEAGE_COLORS:
        return LINEAGE_COLORS[lineage]
    # Deterministic hash — stable across cards + across runs; distinct from anchors.
    # Use built-in hash() would be non-stable across Python runs (randomized in 3.3+),
    # so use a simple checksum for determinism.
    checksum = sum(ord(c) for c in lineage) % len(_HASH_FALLBACK_PALETTE)
    return _HASH_FALLBACK_PALETTE[checksum]


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
