"""Pure roll-up + classifier for spatial tumour–normal co-localization (no S3, no squidpy).

Consumes per-(gene, donor, neighbor_cell_type) rows from spatial-coloc-tumor-{indication}-v1 and
rolls them up DONOR-is-replicate (cross-donor median, never cell-weighted) to a per-neighbour and
per-compartment neighbourhood-enrichment summary + a primary `spatial_coloc_class`.

The biology: for a target on malignant cells, which compartments sit in its spatial neighbourhood?
enrichment_vs_random > 1 = the target-positive malignant cells are spatially CO-LOCALIZED with that
neighbour compartment (vs the malignant baseline); < 1 = segregated.
"""
from __future__ import annotations

import re

# Neighbour cell-type -> compartment. Explicit labels from the landed spatial atlases + a token fallback.
# GSE303070 CosMx (Manual_toplevel_pred): Macro/Mono/DC/Plasma/Granulo/B/ILC/TCD8/TCD4/Mast/TZBTB16/Tgd/NK,
#   Fibro/Peri/SmoothMuscle/Schwann, Endo, Epi. GSE308624 gastric CosMx (cell_type): Cancer_cell (malignant),
#   Fibroblast, SMC, B_cell, T_cell, Mocrophage (sic — misspelled in source), Endothelial, DC.
_NEIGHBOR_COMPARTMENT = {
    "Macro": "immune", "Mono": "immune", "DC": "immune", "Plasma": "immune", "Granulo": "immune",
    "B": "immune", "ILC": "immune", "TCD8": "immune", "TCD4": "immune", "Mast": "immune",
    "TZBTB16": "immune", "Tgd": "immune", "NK": "immune",
    "Fibro": "stromal", "Peri": "stromal", "SmoothMuscle": "stromal", "Schwann": "stromal",
    "Endo": "endothelial",
    "Epi": "epithelial_normal",
    # GSE308624 gastric labels
    "Fibroblast": "stromal", "SMC": "stromal",
    "B_cell": "immune", "T_cell": "immune", "Mocrophage": "immune", "Macrophage": "immune",
    "Plasma_cell": "immune",
    "Endothelial": "endothelial",
    # GSE280634 PDAC Xenium labels (CAF variants tokenize to a single glued token the fallback misses;
    # 'Epithelial (ADM-like)' = acinar-to-ductal metaplasia = normal-ish epithelium)
    "myCAF": "stromal", "iCAF": "stromal", "apCAF": "stromal",
    "Smooth muscle": "stromal", "Proliferative fibroblast": "stromal",
    "T cell": "immune", "Mast cell": "immune", "B, Plasma cell": "immune",
    "Epithelial (ADM-like)": "epithelial_normal",
    # GSE280318 Visium HD COADREAD DeconvolutionLabel1 (fine labels the token fallback misses/misroutes)
    "vSM": "stromal", "SM Stress Response": "stromal", "Vascular Fibroblast": "stromal",
    "Adipocyte": "stromal", "Unknown III (SM)": "stromal",
    "Proliferating Macrophages": "immune", "Proliferating Immune II": "immune", "mRegDC": "immune",
    "Neuroendocrine": "epithelial_normal", "Enteric Glial": "other",
}
_COORDINATED_MIN = 1.15      # per-compartment enrichment >= => spatially co-localized
_SEGREGATED_MAX = 0.85       # <= => spatially segregated
_COMPARTMENT_ORDER = ["immune", "stromal", "endothelial", "epithelial_normal", "other"]

# TOKEN-based fallback vocabularies (matched against WHOLE tokens of the label, never substrings — a
# substring fallback misroutes 'Basal'/'Tuft'/'Tumor' to immune via a bare 'T'/'B'. Tokens are the
# label split on non-alphanumerics + lowercased; single-letter tokens t/b/nk are matched as tokens
# only, so 'T_cell'->{t,cell}->immune but 'Basal'->{basal}->epithelial_normal).
_IMMUNE_TOKENS = {"t", "b", "nk", "nkt", "tcd4", "tcd8", "tgd", "treg", "tcell", "bcell", "cd4", "cd8",
                  "cd3", "macro", "macrophage", "mocrophage", "mono", "monocyte", "dc", "pdc", "cdc",
                  "plasma", "plasmablast", "granulo", "granulocyte", "mast", "ilc", "neutrophil",
                  "basophil", "eosinophil", "mdsc", "lymphocyte", "lymphoid", "myeloid", "leukocyte",
                  "immune", "tam", "tumb", "tzbtb16", "microglia", "kupffer", "langerhans"}
_STROMAL_TOKENS = {"fibro", "fibroblast", "caf", "peri", "pericyte", "smc", "muscle", "smoothmuscle",
                   "schwann", "stellate", "stroma", "stromal", "myofibroblast", "mesenchymal", "myocyte"}
_ENDO_TOKENS = {"endo", "endothelial", "endothelium", "vascular", "lymphatic", "vessel", "vec", "lec"}
_EPI_NORMAL_TOKENS = {"epi", "epithelial", "epithelium", "enterocyte", "goblet", "tuft", "paneth",
                      "club", "ciliated", "basal", "hepatocyte", "acinar", "ductal", "secretory",
                      "squamous", "keratinocyte", "melanocyte", "pneumocyte", "alveolar", "colonocyte",
                      "enteroendocrine", "mucous", "parietal", "chief", "foveolar", "urothelial"}


def compartment_of_neighbor(cell_type: str) -> str:
    """Map a neighbour cell-type label to a compartment. Explicit atlas labels win; otherwise a
    TOKEN-based fallback (whole-token match, NOT substring — 'Basal'/'Tuft' must not read as immune).
    Unknown -> 'other' (never guessed into immune/stromal)."""
    ct = str(cell_type)
    if ct in _NEIGHBOR_COMPARTMENT:
        return _NEIGHBOR_COMPARTMENT[ct]
    toks = {t for t in re.split(r"[^A-Za-z0-9]+", ct.lower()) if t}
    low = ct.lower()
    # endothelial + stromal first (they contain glued forms like 'SmoothMuscle'); then immune; then epi.
    if toks & _ENDO_TOKENS or low.startswith("endo"):
        return "endothelial"
    if toks & _STROMAL_TOKENS or any(s in low for s in ("fibro", "muscle", "pericyte", "schwann", "stellate")):
        return "stromal"
    if toks & _IMMUNE_TOKENS:
        return "immune"
    if toks & _EPI_NORMAL_TOKENS or low.startswith("epi"):
        return "epithelial_normal"
    return "other"


def _median(xs):
    xs = sorted(v for v in xs if v is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def neighbor_summary(rows) -> dict:
    """rows: iterable of dicts with donor_id, neighbor_cell_type, adjacency_fraction,
    enrichment_vs_random, target_pos_fraction, dataset_id. Returns per-neighbour cross-donor medians
    + provenance counts. Empty dict if no rows."""
    rows = list(rows)
    if not rows:
        return {}
    by_ct: dict[str, dict] = {}
    for r in rows:
        by_ct.setdefault(str(r["neighbor_cell_type"]), {"enr": [], "adj": []})
        by_ct[str(r["neighbor_cell_type"])]["enr"].append(r.get("enrichment_vs_random"))
        by_ct[str(r["neighbor_cell_type"])]["adj"].append(r.get("adjacency_fraction"))
    out = {}
    for ct, d in by_ct.items():
        out[ct] = {
            "compartment": compartment_of_neighbor(ct),
            "median_enrichment": _median(d["enr"]),
            "median_adjacency_fraction": _median(d["adj"]),
        }
    return out


def classify_spatial_coloc(nsum: dict, rows) -> dict:
    """Primary spatial_coloc_class + per-compartment enrichment/adjacency + provenance.

    Per-compartment enrichment = median over that compartment's neighbour types of their cross-donor
    median enrichment; adjacency = SUM over the compartment's types of median_adjacency_fraction (the
    fraction of a target-positive malignant cell's neighbours that are that compartment)."""
    rows = list(rows)
    if not nsum:
        return {"spatial_coloc_class": "data_unavailable", "top_enriched_compartment": None,
                "top_enriched_value": None, "per_compartment": {}, "per_neighbor": [],
                "immune_adjacency_fraction": None, "stromal_adjacency_fraction": None,
                "normal_epithelium_adjacency_fraction": None, "n_donors": 0, "n_datasets": 0}
    comp_enr: dict[str, list] = {}
    comp_adj: dict[str, float] = {}
    for ct, d in nsum.items():
        c = d["compartment"]
        comp_enr.setdefault(c, []).append(d["median_enrichment"])
        comp_adj[c] = comp_adj.get(c, 0.0) + (d["median_adjacency_fraction"] or 0.0)
    per_compartment = {c: {"enrichment": _median(comp_enr[c]),
                           "adjacency_fraction": round(comp_adj.get(c, 0.0), 5)}
                       for c in comp_enr}
    # top-enriched compartment for the headline — over the MEANINGFUL compartments (immune / stromal /
    # endothelial / epithelial_normal). 'other' (a marker-inference catch-all for poorly-typed cells,
    # esp. in mode-C products) is EXCLUDED from the headline ranking so it never masks a real signal
    # (e.g. an immune_excluded call); it stays in per_compartment for transparency.
    ranked = sorted(((c, per_compartment[c]["enrichment"]) for c in per_compartment
                     if per_compartment[c]["enrichment"] is not None and c not in ("other", "malignant")),
                    key=lambda kv: kv[1], reverse=True)
    top_c, top_v = (ranked[0] if ranked else (None, None))
    _CLASS = {"immune": "immune_niche_colocalized", "stromal": "stromal_niche_colocalized",
              "endothelial": "endothelial_niche_colocalized",
              "epithelial_normal": "normal_epithelium_adjacent", "other": "other_niche_colocalized"}
    immune_enr = (per_compartment.get("immune") or {}).get("enrichment")
    if top_v is None:
        cls = "data_unavailable"
    elif top_v >= _COORDINATED_MIN:
        cls = _CLASS.get(top_c, "other_niche_colocalized")
    elif immune_enr is not None and immune_enr <= _SEGREGATED_MAX:
        # target-positive malignant cells are DEPLETED of immune neighbours vs baseline — the target
        # marks immune-cold / immune-excluded tumour regions (a TCE liability: no effector T cells nearby).
        cls = "immune_excluded"
    else:
        cls = "no_spatial_preference"
    per_neighbor = sorted(
        [{"neighbor_cell_type": ct, **d} for ct, d in nsum.items()],
        key=lambda x: (x["median_enrichment"] is None, -(x["median_enrichment"] or 0.0)))
    return {
        "spatial_coloc_class": cls,
        "top_enriched_compartment": top_c,
        "top_enriched_value": round(top_v, 4) if top_v is not None else None,
        "per_compartment": per_compartment,
        "per_neighbor": per_neighbor,
        "immune_adjacency_fraction": per_compartment.get("immune", {}).get("adjacency_fraction"),
        "stromal_adjacency_fraction": per_compartment.get("stromal", {}).get("adjacency_fraction"),
        "normal_epithelium_adjacency_fraction": per_compartment.get("epithelial_normal", {}).get("adjacency_fraction"),
        "n_donors": len({str(r["donor_id"]) for r in rows}),
        "n_datasets": len({str(r["dataset_id"]) for r in rows}),
    }
