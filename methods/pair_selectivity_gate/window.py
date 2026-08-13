"""pair_selectivity_gate.window — the single-cell tumor-vs-normal AND-gate window combiner.

The go/no-go for a tumor-intrinsic avidity bispecific. Combines the two single-cell readouts:
  - TUMOR engagement (samecell.confirm_pair_samecell): does the pair co-express on the SAME
    malignant cells (both_fraction) AND coordinated (enrichment >= 1.2)?
  - NORMAL selectivity (normal.normal_max_both): does ANY well-powered normal cell type co-express
    both on the same cell (normal_max_both, over the >=3-donor/>=10-cell support floor)?

A viable AND-gate needs tumor engagement AND normal selectivity — two axes, so the verdict is
categorical (collapsing to one number hides WHY a pair fails), plus a continuous selectivity_margin
(tumor_both - normal_max_both) for ranking.

Verdicts:
  window_open                    tumor coordinated & both>=TAU ; normal selectivity_clean
  window_marginal                tumor coordinated & both>=TAU ; normal borderline
  no_window                      tumor coordinated & both>=TAU ; normal_liability (a normal cell co-expresses both)
  selectivity_unproven           tumor coordinated & both>=TAU ; normal under_powered (thin coverage — NOT a pass)
  insufficient_tumor_engagement  tumor both<TAU or not coordinated (avidity gate won't co-engage the tumor)
  data_unavailable               a required cube is unreadable

Policy (set 2026-08-13): TAU=0.30; window_open REQUIRES same-cell coordination (enrichment>=1.2),
not mere co-presence. under_powered normal is conservatively NOT a pass.
"""
from __future__ import annotations

from methods.pair_selectivity_gate.normal import normal_max_both
from methods.pair_selectivity_gate.samecell import (
    confirm_pair_samecell,
    read_target_samecell_avidity,
)

TUMOR_ENGAGEMENT_MIN = 0.30      # median fraction of malignant cells co-expressing both
_COORDINATED_CALL = "same_cell_coordinated"   # samecell avidity call required for window_open

# verdict rank for target-centric best-partner selection (higher = more viable)
_VERDICT_RANK = {
    "window_open": 5, "window_marginal": 4, "selectivity_unproven": 3,
    "no_window": 2, "insufficient_tumor_engagement": 1, "data_unavailable": 0,
}


def _tumor_engages(tumor: dict) -> bool:
    """Tumor axis passes iff coordinated same-cell co-expression at >= TAU (avidity-gate biology:
    the two antigens must cluster on the SAME malignant cells, not merely both be common)."""
    both = tumor.get("samecell_both_fraction_median")
    return (both is not None and both >= TUMOR_ENGAGEMENT_MIN
            and tumor.get("samecell_avidity_call") == _COORDINATED_CALL)


def pair_selectivity_window(target: str, partner: str, indication: str) -> dict:
    """AND-gate window verdict for one tumor-intrinsic pair in one indication. Never fabricates a
    pass: unreadable cubes -> data_unavailable; thin normal coverage -> selectivity_unproven."""
    tumor = confirm_pair_samecell(target, partner, indication)
    normal = normal_max_both(target, partner)
    t_both = tumor.get("samecell_both_fraction_median")
    n_both = normal.get("normal_max_both_fraction")
    margin = round(t_both - n_both, 4) if (t_both is not None and n_both is not None) else None

    def out(verdict: str) -> dict:
        return {
            "target": target.upper().strip(), "partner": partner.upper().strip(),
            "indication": str(indication).upper().strip(),
            "window_verdict": verdict,
            "selectivity_margin": margin,
            "tumor_both_fraction": t_both,
            "tumor_avidity_call": tumor.get("samecell_avidity_call"),
            "normal_max_both_fraction": n_both,
            "normal_liability_locus": normal.get("normal_liability_locus"),
            "support_floor": normal.get("support_floor"),
            "_tumor": tumor,
            "_normal": normal,
            "_evidence_tier": "single_cell_measured",
        }

    # Tumor axis first (avidity gate must engage the tumor at all).
    if tumor.get("samecell_avidity_call") == "data_unavailable":
        return out("data_unavailable")
    if not _tumor_engages(tumor):
        return out("insufficient_tumor_engagement")

    # Tumor engages — the verdict is now driven by the normal selectivity class.
    nclass = normal.get("normal_selectivity_class")
    return out({
        "selectivity_clean": "window_open",
        "normal_borderline": "window_marginal",
        "normal_liability": "no_window",
        "under_powered": "selectivity_unproven",
        "data_unavailable": "data_unavailable",
    }.get(nclass, "data_unavailable"))


# --- TARGET-CENTRIC (card-facing) ------------------------------------------------------------------
def read_target_selectivity_window(target: str, indication: str) -> dict:
    """Best AND-gate partner for a target in an indication. Scans every partner the tumor same-cell
    cube nominated, computes the window verdict for each, and headlines the most viable
    (verdict rank, then selectivity_margin). data_unavailable-safe."""
    avidity = read_target_samecell_avidity(target, indication)
    partners_in = avidity.get("partners") or []
    if not partners_in:
        return {"target": target, "indication": str(indication).upper().strip(),
                "window_verdict": "data_unavailable", "n_partners_tested": 0,
                "best_partner": None, "best_selectivity_margin": None, "partners": [],
                "_data_note": avidity.get("_data_note", "no tumor same-cell cube for this indication")}
    results = [pair_selectivity_window(target, p["partner"], indication) for p in partners_in]
    results.sort(key=lambda r: (_VERDICT_RANK.get(r["window_verdict"], 0),
                                r["selectivity_margin"] if r["selectivity_margin"] is not None else -1.0),
                 reverse=True)
    best = results[0]
    return {
        "target": target.upper().strip(),
        "indication": str(indication).upper().strip(),
        "window_verdict": best["window_verdict"],
        "n_partners_tested": len(results),
        "n_window_open": sum(1 for r in results if r["window_verdict"] == "window_open"),
        "best_partner": best["partner"],
        "best_selectivity_margin": best["selectivity_margin"],
        "best_normal_liability_locus": best["normal_liability_locus"],
        "partners": [{"partner": r["partner"], "window_verdict": r["window_verdict"],
                      "selectivity_margin": r["selectivity_margin"],
                      "tumor_both_fraction": r["tumor_both_fraction"],
                      "normal_max_both_fraction": r["normal_max_both_fraction"]} for r in results],
        "_evidence_tier": "single_cell_measured",
    }
