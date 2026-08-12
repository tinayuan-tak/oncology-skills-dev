"""tcga_mc3_signatures.signatures — COSMIC SBS signature → biological-process mapping.

The biologically load-bearing content of the axis: which COSMIC v3.x SBS signatures belong to each
interpretable mutational PROCESS. Per-sample refit against the full COSMIC catalog overfits onto
artifact/unknown signatures (SBS49/53/…); binning to these process classes and aggregating per
indication discards that noise and yields a stable, interpretable cohort facet.

Refs: COSMIC Mutational Signatures v3.x (Alexandrov 2020, Nat.); standard aetiology assignments.
"""
from __future__ import annotations

# COSMIC v3.x SBS signature → process class. Only aetiology-assigned signatures are mapped;
# unmapped signatures (incl. artifact/unknown SBS27/43/45-60) are intentionally treated as noise.
SIGNATURE_TO_PROCESS: dict[str, str] = {
    # APOBEC cytidine-deaminase
    "SBS2": "apobec", "SBS13": "apobec",
    # Mismatch-repair deficiency / MSI
    "SBS6": "mmr_deficiency", "SBS14": "mmr_deficiency", "SBS15": "mmr_deficiency",
    "SBS20": "mmr_deficiency", "SBS21": "mmr_deficiency", "SBS26": "mmr_deficiency",
    "SBS44": "mmr_deficiency",
    # Homologous-recombination deficiency
    "SBS3": "hrd",
    # Tobacco
    "SBS4": "tobacco", "SBS29": "tobacco",
    # UV
    "SBS7a": "uv", "SBS7b": "uv", "SBS7c": "uv", "SBS7d": "uv", "SBS38": "uv",
    # POLE/POLD proofreading deficiency
    "SBS10a": "pole", "SBS10b": "pole", "SBS10c": "pole", "SBS10d": "pole", "SBS28": "pole",
    # Clock-like (spontaneous deamination / age)
    "SBS1": "clock", "SBS5": "clock",
    # Prior-therapy / exposure (reported but secondary)
    "SBS31": "platinum", "SBS35": "platinum", "SBS11": "temozolomide",
    "SBS32": "azathioprine", "SBS22": "aristolochic_acid", "SBS24": "aflatoxin",
    "SBS9": "pol_eta",
}

# Processes surfaced as cohort classes (interpretable + actionable). `clock` is reported but is a
# near-universal baseline, so it never counts as an "enriched" process for dominance.
INFORMATIVE_PROCESSES = ["apobec", "mmr_deficiency", "hrd", "tobacco", "uv", "pole", "clock"]
NON_BASELINE_PROCESSES = [p for p in INFORMATIVE_PROCESSES if p != "clock"]


def process_of(signature: str) -> str | None:
    return SIGNATURE_TO_PROCESS.get(signature)
