"""pair_selectivity_gate.normal — normal-tissue SELECTIVITY GATE for tumor-intrinsic bispecific pairs.

The safety complement to samecell.py (tumor avidity). For a tumor-intrinsic avidity AND-gate
bispecific the therapeutic window is malignant-both (high, from samecell.py) vs normal_max_both (≈0):
does ANY normal cell type, in ANY tissue, co-express BOTH antigens on the same cell?

Reads the pan-tissue cube sc-samecell-coexpr-normal-v1 (grain: tissue × cell_type × dataset_id ×
donor_id; emitted by data-catalog/scripts/aggregate_sc_normal_samecell_coexpr.py). For a pair:
group by (tissue, cell_type), take the cross-donor MEDIAN both_fraction per group, and
normal_max_both = MAX over groups.

SUPPORT FLOOR (load-bearing — see data-catalog specs/sc-normal-samecell-coexpr.md §6.3):
normal_max_both is a MAX, so it is dominated by the THINNEST groups. The coverage audit found 107
groups with ≤1 cell — biologically implausible mislabels (an enterocyte in brain, an alveolar cell
in colon) whose both_fraction ∈ {0,1}; a single co-expressing noise cell would post a spurious
MAXIMAL liability and kill a good pair. So normal_max_both is computed ONLY over groups with
>= MIN_DONORS_NORMAL donors AND >= MIN_CELLS_NORMAL cells. We floor the STATISTIC, not the rows.

If NO group meets the floor the result is `normal_selectivity_class: under_powered` — NOT "clear":
absence of a measurable normal liability under thin coverage is not evidence of safety.
"""
from __future__ import annotations

from functools import lru_cache

from methods.catalog_query.read import s3_uri_for

NORMAL_SAMECELL_MANIFEST = "sc-samecell-coexpr-normal-v1"

# Support floor for a (tissue, cell_type) group to count toward normal_max_both.
# Mirrors sc_normal_expression.stats.MIN_RELIABLE_DONORS; values match the
# data-catalog spec §6.3 + the coverage audit (1,715/2,205 groups pass).
MIN_DONORS_NORMAL = 3
MIN_CELLS_NORMAL = 10

# normal_max_both bands for the selectivity call (RNA co-positivity, a lower bound under dropout).
_LIABILITY_MIN = 0.10   # >= → a real normal cell type co-expresses both (selectivity liability)
_CLEAR_MAX = 0.02       # <= → no normal co-positivity in any well-powered cell type (selectivity-clean)


@lru_cache(maxsize=8)
def _read_normal_cube(manifest_id: str = NORMAL_SAMECELL_MANIFEST):
    """The pan-tissue normal same-cell cube. None if unreadable (cube not landed / no creds)."""
    try:
        uri = s3_uri_for(manifest_id)
    except Exception:  # noqa: BLE001
        return None
    try:
        import pyarrow.fs as fs
        import pyarrow.parquet as pq
        s3fs = fs.S3FileSystem(region="us-east-1")
        return pq.read_table(uri.replace("s3://", ""), filesystem=s3fs).to_pandas()
    except Exception:  # noqa: BLE001
        return None


def _selectivity_class(normal_max_both) -> str:
    if normal_max_both is None:
        return "under_powered"
    if normal_max_both >= _LIABILITY_MIN:
        return "normal_liability"          # a well-powered normal cell type co-expresses both
    if normal_max_both <= _CLEAR_MAX:
        return "selectivity_clean"         # no normal co-positivity anywhere well-powered
    return "normal_borderline"


def _floored_groups(m):
    """Per (tissue, cell_type) group passing the support floor → list of dicts with the cross-donor
    median both_fraction. Pure — operates on a matched-pair DataFrame."""
    import numpy as np
    recs = []
    for (tissue, cell_type), g in m.groupby(["tissue", "cell_type"]):
        n_donors = int(g[["dataset_id", "donor_id"]].drop_duplicates().shape[0])
        n_cells = int(g["n_cells"].sum())
        if n_donors < MIN_DONORS_NORMAL or n_cells < MIN_CELLS_NORMAL:
            continue
        enr = g["enrichment_vs_independence"].dropna()
        recs.append({
            "tissue": str(tissue),
            "cell_type": str(cell_type),
            "both_fraction_median": round(float(np.median(g["both_fraction"])), 4),
            "enrichment_median": round(float(np.median(enr)), 3) if len(enr) else None,
            "n_donors": n_donors,
            "n_cells": n_cells,
        })
    return recs


def normal_max_both(target: str, partner: str) -> dict:
    """Normal-tissue selectivity liability for one pair: MAX cross-donor-median both_fraction over
    (tissue, cell_type) groups passing the support floor. Order-insensitive (A:B == B:A).

    Returns the liability locus (the driving tissue/cell_type) + selectivity class, or a
    data_unavailable / under_powered payload — never a fabricated 'clean'."""
    df = _read_normal_cube()
    if df is None:
        return _unavailable("normal same-cell cube not landed / unreadable")
    a, b = target.upper().strip(), partner.upper().strip()
    m = df[((df["gene_a"] == a) & (df["gene_b"] == b)) | ((df["gene_a"] == b) & (df["gene_b"] == a))]
    if m.empty:
        return _unavailable(f"pair {a}:{b} not scanned in the normal cube")
    n_eval = int(m.groupby(["tissue", "cell_type"]).ngroups)
    groups = _floored_groups(m)
    if not groups:
        return {
            "normal_selectivity_class": "under_powered",
            "normal_max_both_fraction": None,
            "normal_liability_locus": None,
            "n_groups_evaluated": n_eval,
            "n_groups_passed_floor": 0,
            "support_floor": {"min_donors": MIN_DONORS_NORMAL, "min_cells": MIN_CELLS_NORMAL},
            "_data_note": (f"no (tissue,cell_type) group met the support floor "
                           f"(>={MIN_DONORS_NORMAL} donors & >={MIN_CELLS_NORMAL} cells) — "
                           f"normal liability under-powered, NOT evidence of selectivity"),
            "_evidence_tier": "single_cell_measured",
        }
    locus = max(groups, key=lambda d: d["both_fraction_median"])
    nmb = locus["both_fraction_median"]
    return {
        "normal_selectivity_class": _selectivity_class(nmb),
        "normal_max_both_fraction": nmb,
        "normal_liability_locus": locus,
        "n_groups_evaluated": n_eval,
        "n_groups_passed_floor": len(groups),
        "support_floor": {"min_donors": MIN_DONORS_NORMAL, "min_cells": MIN_CELLS_NORMAL},
        "_evidence_tier": "single_cell_measured",
    }


def _unavailable(note: str) -> dict:
    return {
        "normal_selectivity_class": "data_unavailable",
        "normal_max_both_fraction": None,
        "normal_liability_locus": None,
        "n_groups_evaluated": 0,
        "n_groups_passed_floor": 0,
        "support_floor": {"min_donors": MIN_DONORS_NORMAL, "min_cells": MIN_CELLS_NORMAL},
        "_data_note": note,
        "_evidence_tier": "single_cell_measured",
    }


# --- TARGET-CENTRIC (card-facing) ------------------------------------------------------------------
def read_target_normal_selectivity(target: str) -> dict:
    """Normal-tissue selectivity for a target across ALL candidate partners in the normal cube —
    the counterpart to samecell.read_target_samecell_avidity. For each partner, normal_max_both +
    its liability locus. Headline = the WORST partner (highest normal_max_both = biggest safety
    liability), so a caller sees the least-selective partner up front."""
    df = _read_normal_cube()
    if df is None:
        return {"target": target, "normal_selectivity_class": "data_unavailable",
                "n_partners_tested": 0, "worst_partner": None, "worst_normal_max_both": None,
                "partners": [], "_data_note": "normal same-cell cube not landed / unreadable"}
    import numpy as np
    a = target.upper().strip()
    m = df[(df["gene_a"] == a) | (df["gene_b"] == a)]
    if m.empty:
        return {"target": target, "normal_selectivity_class": "data_unavailable",
                "n_partners_tested": 0, "worst_partner": None, "worst_normal_max_both": None,
                "partners": [], "_data_note": f"{a} not scanned in the normal cube"}
    partner_arr = np.where(m["gene_a"].to_numpy() == a, m["gene_b"], m["gene_a"])
    partners = []
    for p in sorted(set(partner_arr)):
        res = normal_max_both(a, str(p))
        partners.append({"partner": str(p),
                         "normal_selectivity_class": res["normal_selectivity_class"],
                         "normal_max_both_fraction": res["normal_max_both_fraction"],
                         "normal_liability_locus": res["normal_liability_locus"]})
    # headline = worst (highest normal_max_both; None sorts last so a measured liability wins)
    scored = [p for p in partners if p["normal_max_both_fraction"] is not None]
    worst = max(scored, key=lambda d: d["normal_max_both_fraction"]) if scored else None
    return {
        "target": target,
        "normal_selectivity_class": worst["normal_selectivity_class"] if worst else "under_powered",
        "n_partners_tested": len(partners),
        "worst_partner": worst["partner"] if worst else None,
        "worst_normal_max_both": worst["normal_max_both_fraction"] if worst else None,
        "worst_liability_locus": worst["normal_liability_locus"] if worst else None,
        "partners": partners,
        "_evidence_tier": "single_cell_measured",
    }
