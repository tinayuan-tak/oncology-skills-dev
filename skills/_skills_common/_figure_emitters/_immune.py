"""Immune-context / TME figure emitters.

Part of the _skills_common figure-emitter package. Self-contained: reads the summary the card
already emitted, no method re-run (same pattern as _emit_organoid_crispr_dependency).
"""

from __future__ import annotations

from pathlib import Path  # noqa: F401 — type hints (stringized by future-annotations)

from _skills_common.immune_context_claims import _CD8_COLD_MAX, _CD8_HOT_MIN

from ._common import (  # shared emitter helpers/constants
    TARGET_CONTRACTS,
    _has_live_read_error,
)

# The abstention classes. NEITHER draws a composition bar, for DIFFERENT reasons:
#   data_unavailable              — no cohort resolved, so there are no medians to draw.
#   lymphoid_denominator_unreliable — there IS a cohort and the medians ARE arithmetically defined,
#     which is exactly the trap: in a leukaemia / lymphoma / lymphoid-organ study the LEUKOCYTE
#     denominator IS the malignant clone, so "CD8 is 11% of leukocytes" describes the tumour's own
#     composition, not an effector pool a TCE could redirect. A bar chart states that as a fact with
#     no room for the caveat the text carries, so the figure ABSTAINS where the class abstains.
_ABSTAIN_CLASSES = ("data_unavailable", "lymphoid_denominator_unreliable")

# (label, summary key) for the leukocyte-composition panel, drawn in descending typical magnitude.
_COMPOSITION_ROWS = (
    ("total T cell", "median_total_t_cell_fraction"),
    ("M2 macrophage", "median_m2_macrophage_fraction"),
    ("CD8 T cell", "median_cd8_fraction"),
    ("M1 macrophage", "median_m1_macrophage_fraction"),
    ("Treg", "median_treg_fraction"),
)


def _emit_immune_context_leukocyte_composition(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the immune-context figure declared by the card: the indication's median LEUKOCYTE
    composition beside the PAN-CANCER RANK the class token actually encodes.

    Two panels, because either alone misleads:

      A. composition — the LM22 medians (total T / CD8 / Treg / M1 / M2) as fractions OF THE
         LEUKOCYTE POOL. CIBERSORT LM22 is a RELATIVE deconvolution: these are shares of the
         infiltrate, NOT densities per gram of tumour, and the axis label says so. A suppressor
         median the card judged to be at the LM22 noise floor (it NULLED the matching ratio) is
         drawn hollow and annotated, so a bar too short to trust cannot read as a confident small
         value.

      B. rank — the CD8 median against the pan-cancer Q1/Q3 cuts. This panel is the point of the
         figure. `immune_hot`/`immune_cold` are positions in the 33-TCGA-study distribution, not
         absolute densities, so a composition bar on its own invites the exact misreading the
         review found (ICI-approved BLCA sits at `immune_intermediate`). The panel also plots
         cd8_hot_sample_fraction, because a cohort can be intermediate AT THE MEDIAN while half
         its samples are above the hot cut — the bimodality (MSI-H CRC) that a median hides.

    Gated: _live_read_error → []; an abstaining class (see _ABSTAIN_CLASSES) → []; no CD8 median
    to place on the rank axis → [] (the card still renders numerically without a figure).
    """
    if _has_live_read_error(summary):
        return []
    summary = summary or {}
    if summary.get("immune_context_class") in _ABSTAIN_CLASSES:
        return []
    cd8 = summary.get("median_cd8_fraction")
    if not isinstance(cd8, (int, float)):
        return []

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        style = TARGET_CONTRACTS / "plot_styles" / "takeda_oncology.mplstyle"
        if style.exists():
            plt.style.use(str(style))
    except Exception:  # noqa: BLE001 — style is cosmetic
        pass
    out_dir.mkdir(parents=True, exist_ok=True)

    # A suppressor median is "at the noise floor" when the CARD ITSELF refused to build the ratio
    # that divides by it. Derived from the card's own abstention rather than re-hardcoding
    # classify.MIN_RATIO_DENOMINATOR_FRACTION here — a third copy of that cut would drift.
    floored = {
        "median_treg_fraction": summary.get("cd8_treg_ratio") is None,
        "median_m2_macrophage_fraction": summary.get("cd8_m2_ratio") is None,
    }
    rows = [(lab, k, summary.get(k)) for lab, k in _COMPOSITION_ROWS if isinstance(summary.get(k), (int, float))]

    fig, (ax_c, ax_r) = plt.subplots(
        2, 1, figsize=(6.4, max(3.2, 0.42 * len(rows) + 2.6)), gridspec_kw={"height_ratios": [len(rows) or 1, 2]}
    )

    # ── Panel A: leukocyte composition ───────────────────────────────────────────────────────
    ys = range(len(rows))
    for y, (lab, key, val) in zip(ys, rows):
        at_floor = floored.get(key, False)
        ax_c.barh(
            y,
            float(val),
            color="none" if at_floor else ("#cf2828" if key == "median_cd8_fraction" else "#1f4e79"),
            edgecolor="#0a2540",
            linewidth=0.8,
            hatch="///" if at_floor else None,
            zorder=3,
        )
        txt = f"{float(val):.3f}" + ("  (at LM22 noise floor — ratio abstained)" if at_floor else "")
        ax_c.text(float(val), y, "  " + txt, va="center", fontsize=7.5, color="#333")
    ax_c.set_yticks(list(ys))
    ax_c.set_yticklabels([r[0] for r in rows], fontsize=9)
    ax_c.invert_yaxis()
    ax_c.set_xlim(0, max([float(r[2]) for r in rows] + [0.05]) * 1.45)
    ax_c.set_xlabel("median fraction OF THE LEUKOCYTE POOL (CIBERSORT LM22 — relative, not a density)", fontsize=8)
    n = summary.get("n_samples")
    # Name the POOLED TCGA studies only when they are not just the indication restated (BLCA→[BLCA]);
    # a pooled indication (e.g. COADREAD→[COAD, READ]) is where the study list carries information.
    studies = [s for s in (summary.get("tumor_studies") or []) if s]
    pooled = ", ".join(studies) if studies != [(indication or "").upper()] else ""
    head = f"{indication or ''} leukocyte composition"
    if pooled:
        head += f" — {pooled}"
    if isinstance(n, int) and n > 0:
        head += f" (n={n})"
    ax_c.set_title(
        head + f"\n({target} is not used for the primary call: this is the INDICATION's immune landscape)",
        fontsize=9.5,
    )
    ax_c.grid(axis="x", alpha=0.25, linewidth=0.4)

    # ── Panel B: where the CD8 median sits on the PAN-CANCER axis ────────────────────────────
    ax_r.axvspan(0, _CD8_COLD_MAX, color="#4a76a8", alpha=0.13, zorder=1)
    ax_r.axvspan(_CD8_HOT_MIN, 1.0, color="#cf2828", alpha=0.13, zorder=1)
    # Band labels sit LOW and the median marker HIGH, so the two never collide however close the
    # median lands to a cut (the first draft put both mid-panel and they overprinted illegibly).
    # Each label sits INSIDE the band it names, offset off the cut line — centred on the line, the
    # dashes struck straight through the text.
    for cut, lab, side in (
        (_CD8_COLD_MAX, f"cold ≤ pan-cancer Q1\n{_CD8_COLD_MAX}", "right"),
        (_CD8_HOT_MIN, f"hot ≥ Q3\n{_CD8_HOT_MIN}", "left"),
    ):
        ax_r.axvline(cut, color="#666", linestyle="--", linewidth=0.8, zorder=2)
        ax_r.annotate(
            lab,
            xy=(cut, 0.10),
            xytext=(-4 if side == "right" else 4, 0),
            textcoords="offset points",
            fontsize=6.5,
            color="#555",
            ha=side,
            va="bottom",
        )
    ax_r.plot([float(cd8)], [1.35], marker="D", markersize=9, color="#cf2828", zorder=4)
    ax_r.text(float(cd8), 1.58, f"median CD8 {float(cd8):.4f}", fontsize=8, ha="center", va="bottom", color="#8a1010")
    lo = min(float(cd8), _CD8_COLD_MAX) * 0.75
    hi = max(float(cd8), _CD8_HOT_MIN) * 1.3
    ax_r.set_xlim(lo, hi)
    ax_r.set_ylim(0.0, 2.0)
    hot_frac = summary.get("cd8_hot_sample_fraction")
    if isinstance(hot_frac, (int, float)):
        # Under the axis, not inside the band: this is a statement ABOUT the panel (prevalence vs the
        # median it plots), and inside the band it fought the marker label for the same pixels.
        ax_r.text(
            1.0,
            -0.62,
            # Class-NEUTRAL wording: the earlier draft said "a cohort can be intermediate at the median
            # while a large subset is hot", which is false on the cold and hot cohorts this also renders.
            f"{float(hot_frac):.0%} of samples sit ABOVE the hot cut — prevalence, not central tendency: "
            f"the median above says nothing about how the cohort is spread around the cut",
            transform=ax_r.transAxes,
            fontsize=7,
            ha="right",
            va="top",
            color="#444",
        )
    ax_r.set_yticks([])
    ax_r.set_xlabel("CD8 T-cell fraction — position in the 33-TCGA-study distribution", fontsize=8)
    ax_r.set_title(
        f"class = {summary.get('immune_context_class')}  — a PAN-CANCER RANK, not an absolute effector density",
        fontsize=9,
    )
    ax_r.grid(axis="x", alpha=0.2, linewidth=0.4)

    fig.tight_layout()
    out_path = out_dir / "figure_immune_context_leukocyte_composition.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return [
        {
            "id": "immune_context_leukocyte_composition",
            "path": "figure_immune_context_leukocyte_composition.svg",
            "type": "immune_context_leukocyte_composition_bar",
            "primary": True,
        }
    ]
