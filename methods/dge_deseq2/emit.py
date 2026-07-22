"""dge_deseq2.emit — matplotlib figure emitters for DGE-derived cards.

Separate from cli.py (which wraps the R DESeq2 pipeline) so the emitter has no
R dependency. Called from compose-dashboard's _figure_emitters.py at phase-2.

Public API:
    emit_tumor_vs_adjacent_compound(summary, per_sample_data, target, indication,
                                      out_dir, target_contracts_dir) -> Path
    emit_plotly_specs(per_sample_data, contrasts, target, indication, out_dir,
                       target_contracts_dir, basename) -> list   # dynamic-dashboard Phase A
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def _load_takeda_palette(target_contracts_dir: Path):
    import matplotlib.pyplot as plt
    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette
    return takeda_palette


def _placeholder_svg(msg_lines: list, out_path: Path, pal) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    y = 0.7
    for line in msg_lines:
        ax.text(0.5, y, line, transform=ax.transAxes, ha="center",
                 fontsize=10 if y == 0.7 else 8, color="#444" if y == 0.7 else "#777")
        y -= 0.1
    ax.set_axis_off()
    fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_tumor_vs_normal_selectivity_3panel(
    dge_adj_summary: Optional[dict],
    dge_gtex_summary: Optional[dict],
    per_sample_data: Optional[dict],
    target: str,
    indication: str,
    out_dir: Path,
    target_contracts_dir: Path,
) -> Path:
    """Compound 3-panel figure for the tumor-vs-normal-selectivity card.

    Layout (single SVG, side-by-side panels):
      Left (largest): horizontal box + jittered strip of log2(CPM+1) for
        Primary Tumor (navy), Adjacent Normal (ochre), GTEx Normal (gray-blue).
        Individual sample dots overlaid. Group median annotations.
      Middle: horizontal forest of the two log2FC contrasts (tumor-vs-adj +
        tumor-vs-GTEx) with q-value stars, colored by upreg/downreg.
      Right: text-block callout — selectivity_class + values + n's per group.

    Placeholders rendered when per_sample_data is None (no recount3 mapping) or
    lacks the GTEx group (indication has no canonical GTEx tissue).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_tumor_vs_normal_selectivity_3panel.svg"

    if per_sample_data is None:
        return _placeholder_svg([
            f"{target} in {indication} — per-sample expression unavailable",
            "(recount3 does not cover this indication mapping)"
        ], out_path, pal)

    tumor = per_sample_data.get("tumor_samples") or []
    adj = per_sample_data.get("adjacent_samples") or []
    gtex = per_sample_data.get("gtex_samples") or []
    if not tumor and not adj and not gtex:
        return _placeholder_svg([
            f"{target} in {indication} — no samples found",
            f"(gene_ensembl_id={per_sample_data.get('gene_ensembl_id')})"
        ], out_path, pal)

    fig = plt.figure(figsize=(pal.FIGSIZE_DOUBLE_COLUMN[0] * 1.15,
                              pal.FIGSIZE_DOUBLE_COLUMN[1] * 1.1))
    gs = fig.add_gridspec(1, 3, width_ratios=[3.0, 1.6, 1.4], wspace=0.4)
    ax_box = fig.add_subplot(gs[0, 0])
    ax_forest = fig.add_subplot(gs[0, 1])
    ax_txt = fig.add_subplot(gs[0, 2])

    # -------- Panel A: box + strip across 3 groups --------
    # UNIT SELECTION (chain-review #4 fix): prefer log2_tpm (GTEx from the long product has only
    # log2_tpm; keying on log2_cpm dropped GTEx). Also FILTER None — the prior unfiltered
    # [s["log2_cpm"] for s in gtex] produced [None,...] and crashed np.median. (This 3-panel is not
    # the live-wired emitter — the 4-panel is — but it carried the same two defects.)
    def _vals3(samples, unit):
        return [s[unit] for s in samples if s.get(unit) is not None]

    _tpm_avail = bool(_vals3(tumor, "log2_tpm") or _vals3(adj, "log2_tpm") or _vals3(gtex, "log2_tpm"))
    _uk = "log2_tpm" if _tpm_avail else "log2_cpm"
    _unit_label3 = "log2(TPM + 1)" if _tpm_avail else "log2(CPM + 1)"
    tumor_vals = _vals3(tumor, _uk)
    adj_vals = _vals3(adj, _uk)
    gtex_vals = _vals3(gtex, _uk)

    groups = []
    labels = []
    colors = []
    if tumor_vals:
        groups.append(tumor_vals)
        labels.append(f"Primary Tumor\n(n={len(tumor_vals)})")
        colors.append("#0a2540")
    if adj_vals:
        groups.append(adj_vals)
        labels.append(f"Adjacent Normal\n(n={len(adj_vals)})")
        colors.append("#f0a020")
    if gtex_vals:
        groups.append(gtex_vals)
        gtex_tissue = per_sample_data.get("gtex_tissue") or "GTEx"
        labels.append(f"GTEx {gtex_tissue}\n(n={len(gtex_vals)})")
        colors.append("#7fa7c0")

    bp = ax_box.boxplot(
        groups, vert=False, widths=0.55, patch_artist=True,
        showfliers=False, medianprops={"color": "#222", "linewidth": 1.5},
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color); patch.set_alpha(0.35); patch.set_edgecolor(color)
    for whisker in bp["whiskers"]:
        whisker.set_color("#666")
    for cap in bp["caps"]:
        cap.set_color("#666")

    rng = np.random.default_rng(seed=42)
    for i, (vals, color) in enumerate(zip(groups, colors)):
        yy = rng.uniform(i + 1 - 0.15, i + 1 + 0.15, size=len(vals))
        ax_box.scatter(vals, yy, s=6 if len(vals) > 200 else 10, color=color,
                       alpha=0.5, edgecolor="none", zorder=3)

    ax_box.set_yticks(range(1, len(labels) + 1))
    ax_box.set_yticklabels(labels, fontsize=8)
    ax_box.set_xlabel(f"{_unit_label3} — recount3 per-sample RNA-seq", fontsize=8)
    ax_box.set_title(f"{target} expression: tumor vs normal groups in {indication}",
                       fontsize=9)
    ax_box.grid(axis="x", alpha=0.3, linewidth=0.5)
    for i, vals in enumerate(groups):
        med = float(np.median(vals))
        ax_box.text(med, i + 1 - 0.32, f"{med:.2f}", ha="center", va="top",
                     fontsize=7, color="#222", weight="bold")

    # -------- Panel B: forest of the two log2FC contrasts --------
    def _sig_stars(q):
        if q is None or q != q: return ""
        if q < 1e-10: return "***"
        if q < 1e-4: return "**"
        if q < 0.05: return "*"
        return "ns"

    contrasts = []
    if dge_adj_summary and dge_adj_summary.get("log2_fc") is not None:
        contrasts.append({
            "label": "tumor\nvs adj-normal",
            "log2_fc": float(dge_adj_summary["log2_fc"]),
            "q_value": dge_adj_summary.get("q_value"),
        })
    if dge_gtex_summary and dge_gtex_summary.get("log2_fc") is not None:
        contrasts.append({
            "label": "tumor\nvs GTEx-normal",
            "log2_fc": float(dge_gtex_summary["log2_fc"]),
            "q_value": dge_gtex_summary.get("q_value"),
        })

    if contrasts:
        y_pos = list(range(len(contrasts)))[::-1]
        lfcs = [c["log2_fc"] for c in contrasts]
        for y, c in zip(y_pos, contrasts):
            color = "#0a2540" if c["log2_fc"] > 0 else "#cf2828"
            ax_forest.plot([0, c["log2_fc"]], [y, y], color=color, linewidth=2, alpha=0.7)
            ax_forest.scatter([c["log2_fc"]], [y], color=color, s=60, zorder=3,
                                edgecolor="white", linewidth=1)
            stars = _sig_stars(c["q_value"])
            offset = 0.25 if c["log2_fc"] > 0 else -0.25
            ax_forest.text(c["log2_fc"] + offset, y, f"{c['log2_fc']:+.2f}\n{stars}",
                             ha="left" if c["log2_fc"] > 0 else "right",
                             va="center", fontsize=7, color=color)
        ax_forest.axvline(0, color="#333", linewidth=0.7)
        ax_forest.axvline(0.5, color="#888", linestyle=":", linewidth=0.5)
        ax_forest.axvline(-0.5, color="#888", linestyle=":", linewidth=0.5)
        ax_forest.axvline(1.5, color="#0a2540", linestyle="--", linewidth=0.5, alpha=0.5)
        ax_forest.set_yticks(y_pos)
        ax_forest.set_yticklabels([c["label"] for c in contrasts], fontsize=8)
        # Center x-axis around 0 with symmetric range
        max_abs = max(2.0, max(abs(c["log2_fc"]) for c in contrasts) * 1.5)
        ax_forest.set_xlim(-max_abs, max_abs)
        ax_forest.set_xlabel("log2 FC", fontsize=8)
        ax_forest.set_title("DGE contrasts", fontsize=9)
        ax_forest.grid(axis="x", alpha=0.2)
    else:
        ax_forest.text(0.5, 0.5, "No DGE\ncontrasts available",
                        transform=ax_forest.transAxes, ha="center", va="center",
                        fontsize=9, color="#888")
        ax_forest.set_axis_off()

    # -------- Panel C: text callout --------
    ax_txt.set_axis_off()
    log2_fc_adj = (dge_adj_summary or {}).get("log2_fc")
    log2_fc_gtex = (dge_gtex_summary or {}).get("log2_fc")

    # Selectivity class heuristic — mirrors the card spec conventions
    def _selectivity_class(adj_lfc, gtex_lfc):
        """Pick the max log2FC across both contrasts; classify by magnitude."""
        vals = [v for v in [adj_lfc, gtex_lfc] if v is not None and v == v]
        if not vals:
            return "data_unavailable"
        max_lfc = max(vals)
        if max_lfc >= 1.5:
            return "strong_tumor_selective"
        if max_lfc >= 0.5:
            return "modest_tumor_selective"
        if max_lfc < 0.0:
            return "not_selective"
        return "not_informative"

    cls = _selectivity_class(log2_fc_adj, log2_fc_gtex)
    class_color = {
        "strong_tumor_selective":  "#0a2540",
        "modest_tumor_selective":  "#7fa7c0",
        "not_informative":         "#888888",
        "not_selective":           "#cf2828",
        "data_unavailable":        "#bbbbbb",
    }.get(cls, "#444")

    def _fmt(v, spec="+.2f"):
        try: return format(float(v), spec)
        except (TypeError, ValueError): return "NA"

    lines = [
        ("Tumor-vs-normal", "bold", "#222"),
        ("selectivity", "bold", "#222"),
        ("", None, None),
        (f"log2FC vs adj:  {_fmt(log2_fc_adj)}", "normal", "#222"),
        (f"log2FC vs GTEx: {_fmt(log2_fc_gtex)}", "normal", "#222"),
        ("", None, None),
        (f"n_tumor:    {len(tumor_vals)}", "normal", "#222"),
        (f"n_adj:      {len(adj_vals)}", "normal", "#222"),
        (f"n_gtex:     {len(gtex_vals)}", "normal", "#222"),
        ("", None, None),
        ("class", "italic", "#666"),
        (cls.replace("_", " "), "bold", class_color),
    ]
    y = 0.95
    for text, style, color in lines:
        if text == "":
            y -= 0.03
            continue
        weight = "bold" if style == "bold" else "normal"
        fontstyle = "italic" if style == "italic" else "normal"
        ax_txt.text(0.02, y, text, transform=ax_txt.transAxes, ha="left", va="top",
                     fontsize=9 if style != "italic" else 8, weight=weight,
                     style=fontstyle, color=color, family="monospace")
        y -= 0.075

    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def emit_tumor_vs_normal_selectivity_4panel(
    sensitivity_summary: dict,
    per_sample_data: Optional[dict],
    target: str,
    indication: str,
    out_dir: Path,
    target_contracts_dir: Path,
) -> Path:
    """v3 sensitivity-panel figure for the tumor-vs-normal-selectivity card.
    (Function name retains the historical `_4panel` suffix for API stability; the
    middle forest now draws 3 live cells A/B/C — cell D was retired.)

    Layout (single SVG, 3-panel row like v2; the middle forest is 3 rows A/B/C):
      Left:   horizontal box + strip of log2(CPM+1) for Primary Tumor, TCGA
              Adjacent Normal, and GTEx (unchanged from v2).
      Middle: forest of the live cell log2FC estimates (A/B/C; cell D retired) with
              q-value stars, colored by up/down. Cells that disagree on sign vs the
              dominant direction are drawn hollow (discordance flag).
      Right:  sensitivity callout — cells_supporting badge (n/cells_ran),
              dominant_direction, sig_all_cells check, discordant flag, class.

    `sensitivity_summary` is the dict produced by
    `read_tumor_vs_normal_selectivity` (v3 schema); backwards-compatible with
    the v2_two_product_fallback schema (extra cells simply show as missing).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_tumor_vs_normal_selectivity_4panel.svg"

    if per_sample_data is None:
        return _placeholder_svg([
            f"{target} in {indication} — per-sample expression unavailable",
            "(recount3 does not cover this indication mapping)"
        ], out_path, pal)

    tumor = per_sample_data.get("tumor_samples") or []
    adj = per_sample_data.get("adjacent_samples") or []
    gtex = per_sample_data.get("gtex_samples") or []
    if not tumor and not adj and not gtex:
        return _placeholder_svg([
            f"{target} in {indication} — no samples found",
            f"(gene_ensembl_id={per_sample_data.get('gene_ensembl_id')})"
        ], out_path, pal)

    fig = plt.figure(figsize=(pal.FIGSIZE_DOUBLE_COLUMN[0] * 1.2,
                              pal.FIGSIZE_DOUBLE_COLUMN[1] * 1.15))
    gs = fig.add_gridspec(1, 3, width_ratios=[2.8, 2.0, 1.6], wspace=0.45)
    ax_box = fig.add_subplot(gs[0, 0])
    ax_forest = fig.add_subplot(gs[0, 1])
    ax_txt = fig.add_subplot(gs[0, 2])

    # -------- Panel A: box + strip across 3 groups --------
    # UNIT SELECTION (chain-review #4 fix): tumor/adjacent samples carry BOTH log2_cpm and log2_tpm
    # (computed on-demand from recount3 counts), but the GTEx arm now comes from the long TPM product
    # and carries ONLY log2_tpm (log2_cpm is None). The prior code keyed exclusively on log2_cpm, so
    # EVERY GTEx sample was silently dropped from this box panel (and the 3-group figure showed only
    # 2 groups). Plot log2_tpm when it is available for the groups that have data — it is the
    # cross-group-comparable unit anyway (the reason the long products use TPM) — so all three land
    # on ONE genuine TPM axis. Fall back to log2_cpm only when TPM is entirely absent (e.g. a gene
    # with no Gencode-v26 length, where tumor/adj have CPM but GTEx cannot be co-plotted); in that
    # fallback GTEx is legitimately absent (no CPM in the long product) and the axis is labeled CPM.
    def _vals(samples, unit):
        return [s[unit] for s in samples if s.get(unit) is not None]

    tpm_available = bool(_vals(tumor, "log2_tpm") or _vals(adj, "log2_tpm") or _vals(gtex, "log2_tpm"))
    unit_key = "log2_tpm" if tpm_available else "log2_cpm"
    unit_label = "log2(TPM + 1)" if tpm_available else "log2(CPM + 1)"
    tumor_vals = _vals(tumor, unit_key)
    adj_vals   = _vals(adj, unit_key)
    gtex_vals  = _vals(gtex, unit_key)

    groups, labels, colors = [], [], []
    if tumor_vals:
        groups.append(tumor_vals); colors.append("#0a2540")
        labels.append(f"Primary Tumor\n(n={len(tumor_vals)})")
    if adj_vals:
        groups.append(adj_vals); colors.append("#f0a020")
        labels.append(f"TCGA Adjacent\n(n={len(adj_vals)})")
    if gtex_vals:
        groups.append(gtex_vals); colors.append("#7fa7c0")
        tissue = per_sample_data.get("gtex_tissue") or "GTEx"
        labels.append(f"GTEx {tissue}\n(n={len(gtex_vals)})")

    bp = ax_box.boxplot(groups, vert=False, widths=0.55, patch_artist=True,
                        showfliers=False,
                        medianprops={"color": "#222", "linewidth": 1.5})
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color); patch.set_alpha(0.35)
        patch.set_edgecolor(color)
    for whisker in bp["whiskers"]: whisker.set_color("#666")
    for cap in bp["caps"]:         cap.set_color("#666")

    rng = np.random.default_rng(seed=42)
    for i, (vals, color) in enumerate(zip(groups, colors)):
        yy = rng.uniform(i + 1 - 0.15, i + 1 + 0.15, size=len(vals))
        ax_box.scatter(vals, yy, s=6 if len(vals) > 200 else 10, color=color,
                       alpha=0.5, edgecolor="none", zorder=3)
    ax_box.set_yticks(range(1, len(labels) + 1))
    ax_box.set_yticklabels(labels, fontsize=8)
    ax_box.set_xlabel(f"{unit_label} — recount3 per-sample RNA-seq", fontsize=8)
    ax_box.set_title(f"{target} in {indication}", fontsize=9)
    ax_box.grid(axis="x", alpha=0.3, linewidth=0.5)
    for i, vals in enumerate(groups):
        med = float(np.median(vals))
        ax_box.text(med, i + 1 - 0.32, f"{med:.2f}", ha="center", va="top",
                    fontsize=7, color="#222", weight="bold")

    # -------- Panel B: multi-cell forest (A/B/C live; cell D retired) --------
    def _sig_stars(q):
        if q is None or q != q: return ""
        if q < 1e-10: return "***"
        if q < 1e-4:  return "**"
        if q < 0.05:  return "*"
        return "ns"

    # Cell D (GTEx, ComBat(source)) was RETIRED — the reader no longer emits log2fc_cell_d;
    # the forest draws the three live cells A/B/C. See card + 06_four_cell_driver.R:227-244.
    cells = [
        ("A", "TCGA adj-normal\n(raw)",     "log2fc_cell_a", "q_value_cell_a"),
        ("B", "TCGA adj-normal\n(ComBat)",  "log2fc_cell_b", "q_value_cell_b"),
        ("C", "GTEx normal\n(raw joint)",   "log2fc_cell_c", "q_value_cell_c"),
    ]
    rows = []
    for tag, label, lfc_k, q_k in cells:
        lfc = sensitivity_summary.get(lfc_k)
        q   = sensitivity_summary.get(q_k)
        if lfc is None or lfc != lfc:
            continue
        rows.append({"tag": tag, "label": label, "log2_fc": float(lfc),
                     "q_value": q})

    dom = sensitivity_summary.get("dominant_direction")

    if rows:
        y_pos = list(range(len(rows)))[::-1]
        for y, r in zip(y_pos, rows):
            is_up = r["log2_fc"] > 0
            color = "#0a2540" if is_up else "#cf2828"
            # discordant marker: filled if aligned with dominant direction, hollow otherwise
            aligned = (dom == "up" and is_up) or (dom == "down" and not is_up)
            face = color if aligned or not dom else "white"
            ax_forest.plot([0, r["log2_fc"]], [y, y], color=color,
                           linewidth=2, alpha=0.6)
            ax_forest.scatter([r["log2_fc"]], [y], s=70, zorder=3,
                              facecolor=face, edgecolor=color, linewidth=1.5)
            stars = _sig_stars(r["q_value"])
            off = 0.20 if is_up else -0.20
            ax_forest.text(r["log2_fc"] + off, y,
                           f"{r['log2_fc']:+.2f} {stars}",
                           ha="left" if is_up else "right",
                           va="center", fontsize=7, color=color)
        ax_forest.axvline(0, color="#333", linewidth=0.7)
        for x in (-1.5, -0.5, 0.5, 1.5):
            ax_forest.axvline(x, color="#888", linestyle=":", linewidth=0.5)
        ax_forest.set_yticks(y_pos)
        ax_forest.set_yticklabels([f"cell {r['tag']}\n{r['label']}" for r in rows],
                                  fontsize=7)
        max_abs = max(2.0, max(abs(r["log2_fc"]) for r in rows) * 1.4)
        ax_forest.set_xlim(-max_abs, max_abs)
        ax_forest.set_xlabel("log2 FoldChange (tumor vs normal)", fontsize=8)
        ax_forest.set_title("Four-cell sensitivity", fontsize=9)
        ax_forest.grid(axis="x", alpha=0.2)
    else:
        ax_forest.text(0.5, 0.5, "No cells ran",
                       transform=ax_forest.transAxes, ha="center", va="center",
                       fontsize=9, color="#888")
        ax_forest.set_axis_off()

    # -------- Panel C: sensitivity callout --------
    ax_txt.set_axis_off()
    cls = sensitivity_summary.get("selectivity_class") or "data_unavailable"
    supporting = sensitivity_summary.get("cells_supporting")
    ran = sensitivity_summary.get("cells_ran")
    discordant = sensitivity_summary.get("discordant")
    sig_all = sensitivity_summary.get("sig_all_cells")
    max_lfc = sensitivity_summary.get("max_abs_log2fc")

    class_color = {
        "strong_tumor_selective":         "#0a2540",
        "modest_tumor_selective":         "#7fa7c0",
        "discordant_across_comparators":  "#c07a20",
        "not_selective":                  "#cf2828",
        "not_informative":                "#888888",
        "data_unavailable":               "#bbbbbb",
    }.get(cls, "#444")

    def _fmt(v, spec=".2f"):
        try: return format(float(v), spec)
        except (TypeError, ValueError): return "NA"

    def _row(y, label, value, weight="normal", color="#222"):
        ax_txt.text(0.02, y, label, transform=ax_txt.transAxes, ha="left",
                    va="top", fontsize=8, color="#666", family="monospace")
        ax_txt.text(0.55, y, value, transform=ax_txt.transAxes, ha="left",
                    va="top", fontsize=9, color=color, weight=weight,
                    family="monospace")

    y = 0.96
    ax_txt.text(0.02, y, "Sensitivity",  transform=ax_txt.transAxes,
                ha="left", va="top", fontsize=10, weight="bold", color="#222")
    y -= 0.08
    ax_txt.text(0.02, y, "(3-cell DESeq2)", transform=ax_txt.transAxes,
                ha="left", va="top", fontsize=7, style="italic", color="#666")
    y -= 0.09

    if supporting is not None and ran:
        badge = f"{int(supporting)}/{int(ran)}"
        badge_color = "#0a2540" if supporting == ran else "#7fa7c0" if supporting >= 3 else "#888"
        _row(y, "supporting", badge, weight="bold", color=badge_color); y -= 0.08
    _row(y, "dominant",  (dom or "—")); y -= 0.08
    _row(y, "sig(all)",  "yes" if sig_all else "no",
         color="#0a2540" if sig_all else "#666"); y -= 0.08
    _row(y, "discordant", "yes" if discordant else "no",
         weight="bold" if discordant else "normal",
         color="#c07a20" if discordant else "#666"); y -= 0.08
    _row(y, "max|lfc|",  _fmt(max_lfc)); y -= 0.10
    ax_txt.text(0.02, y, "class", transform=ax_txt.transAxes, ha="left",
                va="top", fontsize=7, style="italic", color="#666")
    y -= 0.06
    ax_txt.text(0.02, y, cls.replace("_", " "), transform=ax_txt.transAxes,
                ha="left", va="top", fontsize=9, weight="bold",
                color=class_color, family="monospace")

    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def emit_tumor_vs_adjacent_compound(
    summary: dict,
    per_sample_data: Optional[dict],
    target: str,
    indication: str,
    out_dir: Path,
    target_contracts_dir: Path,
) -> Path:
    """Compound figure for expression-tumor-vs-adjacent card.

    Layout: 2-panel side-by-side.
      Panel A (left, 2/3 width): horizontal box + strip of log2(CPM+1) for
        Primary Tumor vs Solid Tissue Normal, from recount3 per-sample data.
      Panel B (right, 1/3 width): DGE stats callout (log2FC, q-value,
        expression_call_class, n_tumor/n_adjacent) with color-coded class label.

    Placeholder when per_sample_data is None (recount3 unavailable for the
    indication) or empty (no samples matched).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_tumor_vs_adjacent_compound.svg"

    if per_sample_data is None:
        return _placeholder_svg([
            f"{target} in {indication} — per-sample expression unavailable",
            "(recount3 does not cover this indication mapping)"
        ], out_path, pal)

    tumor = per_sample_data.get("tumor_samples") or []
    adj = per_sample_data.get("adjacent_samples") or []
    if not tumor and not adj:
        return _placeholder_svg([
            f"{target} in {indication} — no samples found",
            f"(gene_ensembl_id={per_sample_data.get('gene_ensembl_id')})"
        ], out_path, pal)

    tumor_vals = [s["log2_cpm"] for s in tumor]
    adj_vals = [s["log2_cpm"] for s in adj]

    fig = plt.figure(figsize=(pal.FIGSIZE_DOUBLE_COLUMN[0], pal.FIGSIZE_DOUBLE_COLUMN[1] * 1.1))
    gs = fig.add_gridspec(1, 3, width_ratios=[2, 2, 1.4], wspace=0.35)
    ax_box = fig.add_subplot(gs[0, :2])
    ax_txt = fig.add_subplot(gs[0, 2])

    # --- Panel A: box + strip ---
    groups = []
    labels = []
    colors = []
    if tumor_vals:
        groups.append(tumor_vals)
        labels.append(f"Primary Tumor\n(n={len(tumor_vals)})")
        colors.append("#0a2540")   # navy
    if adj_vals:
        groups.append(adj_vals)
        labels.append(f"Adjacent Normal\n(n={len(adj_vals)})")
        colors.append("#f0a020")   # ochre

    # Horizontal boxplot with fillcolors
    bp = ax_box.boxplot(
        groups, vert=False, widths=0.55, patch_artist=True,
        showfliers=False, medianprops={"color": "#222", "linewidth": 1.5},
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.35)
        patch.set_edgecolor(color)
    for whisker in bp["whiskers"]:
        whisker.set_color("#666")
    for cap in bp["caps"]:
        cap.set_color("#666")

    # Overlay jittered strip
    rng = np.random.default_rng(seed=42)
    for i, (vals, color) in enumerate(zip(groups, colors)):
        yy = rng.uniform(i + 1 - 0.15, i + 1 + 0.15, size=len(vals))
        ax_box.scatter(vals, yy, s=8, color=color, alpha=0.55,
                        edgecolor="none", zorder=3)

    ax_box.set_yticks(range(1, len(labels) + 1))
    ax_box.set_yticklabels(labels, fontsize=8)
    ax_box.set_xlabel("log2(CPM + 1) — recount3 per-sample RNA-seq", fontsize=8)
    ax_box.set_title(f"{target} expression: tumor vs adjacent-normal in {indication}",
                       fontsize=9)
    ax_box.grid(axis="x", alpha=0.3, linewidth=0.5)
    # Group-median markers with values
    for i, vals in enumerate(groups):
        med = float(np.median(vals))
        ax_box.text(med, i + 1 - 0.35, f"{med:.2f}", ha="center",
                     va="top", fontsize=7, color="#222", weight="bold")

    # --- Panel B: DGE stats + class callout ---
    ax_txt.set_axis_off()
    log2_fc = summary.get("log2_fc")
    q_value = summary.get("q_value")
    n_tumor_dge = summary.get("n_tumor")
    n_adj_dge = summary.get("n_adjacent")
    cls = summary.get("expression_call_class", "data_unavailable")
    class_color = {
        "strong_upregulation": "#0a2540",
        "modest_upregulation": "#7fa7c0",
        "not_informative":     "#888888",
        "data_unavailable":    "#bbbbbb",
    }.get(cls, "#444")

    def _fmt(v, spec="+.2f"):
        try: return format(float(v), spec)
        except (TypeError, ValueError): return "NA"

    lines = [
        ("DGE stats", "bold", "#222"),
        ("(tumor vs adjacent-normal)", "italic", "#666"),
        ("", None, None),
        (f"log2 fold-change: {_fmt(log2_fc)}", "normal", "#222"),
        (f"q-value: {_fmt(q_value, '.2e')}", "normal", "#222"),
        (f"n_tumor: {n_tumor_dge if n_tumor_dge is not None else 'NA'}", "normal", "#222"),
        (f"n_adjacent: {n_adj_dge if n_adj_dge is not None else 'NA'}", "normal", "#222"),
        ("", None, None),
        ("class", "italic", "#666"),
        (cls.replace("_", " "), "bold", class_color),
    ]
    y = 0.95
    for text, style, color in lines:
        if text == "":
            y -= 0.03
            continue
        weight = "bold" if style == "bold" else "normal"
        fontstyle = "italic" if style == "italic" else "normal"
        ax_txt.text(0.02, y, text, transform=ax_txt.transAxes, ha="left", va="top",
                     fontsize=9 if style != "italic" else 8, weight=weight,
                     style=fontstyle, color=color)
        y -= 0.09

    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


# --- interactive Plotly figure specs (dynamic-dashboard Phase A) -----------------------------

_GROUP_STYLE = [
    ("tumor_samples", "Primary Tumor", "#0a2540"),      # navy — mirrors the SVG box+strip
    ("adjacent_samples", "Adjacent Normal", "#f0a020"),  # ochre
    ("gtex_samples", "GTEx Normal", "#7fa7c0"),          # gray-blue
]


def emit_plotly_specs(
    per_sample_data: Optional[dict],
    contrasts: Optional[list],
    target: str,
    indication: str,
    out_dir: Path,
    target_contracts_dir: Path,
    basename: str = "tumor_vs_normal",
) -> list:
    """Emit interactive Plotly figure specs SIBLING to the matplotlib DGE SVGs (dynamic-dashboard
    Phase A). Built from the SAME in-memory ``per_sample_data`` (per-sample log2(CPM+1) arrays) and
    ``contrasts`` (the log2FC/q the SVG forest draws) — so the interactive charts cannot drift from
    the static figure. Writes, keyed by ``basename`` so the 3-group and tumor-vs-adjacent call sites
    don't collide:
      - figure_{basename}_groups.plotly.json   (box + jittered strip across the present groups)
      - figure_{basename}_contrasts.plotly.json (horizontal forest of the log2FC contrasts, q stars)

    ``contrasts`` = [{"label": str, "log2_fc": float, "q_value": float|None}, ...] — the caller
    extracts these from the SAME summary dicts the SVG forest uses (no recompute here). fig.to_json()
    (renderer embeds via Plotly.newPlot; NO kaleido). Best-effort — the SVGs are the guaranteed
    artifact; if Plotly is unavailable or there are no samples, returns []."""
    try:
        import numpy as np
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001 — Plotly optional; never block the SVG artifacts
        print(f"[dge_deseq2] plotly spec emission skipped: {e}", file=sys.stderr)
        return []

    if not per_sample_data:
        return []
    present = [(key, label, color) for key, label, color in _GROUP_STYLE
               if per_sample_data.get(key)]
    if not present:
        return []

    written = []

    # --- Box + jittered strip across the present groups (mirrors the SVG box+strip panel) ---
    # UNIT SELECTION (chain-review #4 fix, mirrors the SVG): prefer log2_tpm — the GTEx arm from the
    # long product carries ONLY log2_tpm, so keying on log2_cpm silently dropped every GTEx point.
    # Fall back to log2_cpm only when TPM is entirely absent (GTEx then legitimately absent).
    try:
        fig = go.Figure()
        rng = np.random.default_rng(seed=42)   # deterministic jitter (matches the SVG's seed)
        _tpm_avail = any(s.get("log2_tpm") is not None
                         for key, _l, _c in present for s in per_sample_data[key])
        unit_key = "log2_tpm" if _tpm_avail else "log2_cpm"
        unit_txt = "log2(TPM+1)" if _tpm_avail else "log2(CPM+1)"
        for key, label, color in present:
            vals = [s[unit_key] for s in per_sample_data[key] if s.get(unit_key) is not None]
            if not vals:
                continue
            name = f"{label} (n={len(vals)})"
            fig.add_trace(go.Box(
                y=vals, name=name, boxpoints="all", jitter=0.4, pointpos=0,
                marker=dict(color=color, size=4, opacity=0.5),
                line=dict(color=color), fillcolor=color, opacity=0.55,
                hovertemplate="%{y:.2f} " + unit_txt + "<extra>" + name + "</extra>"))
        gtex_tissue = per_sample_data.get("gtex_tissue")
        subtitle = f" (GTEx {gtex_tissue})" if gtex_tissue else ""
        fig.update_layout(
            title=f"{target} expression — tumor vs normal groups in {indication}{subtitle}",
            yaxis_title=f"{unit_txt.replace('+1)', ' + 1)')} — recount3 per-sample RNA-seq",
            template="plotly_white", showlegend=False, margin=dict(l=60, r=20, t=50, b=60))
        (out_dir / f"figure_{basename}_groups.plotly.json").write_text(fig.to_json())
        written.append({"id": f"{basename}_groups",
                        "path": f"figure_{basename}_groups.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[dge_deseq2] groups plotly skipped: {e}", file=sys.stderr)

    # --- Forest of the log2FC contrasts (mirrors the SVG forest panel; reflines at 0/±0.5) ---
    try:
        rows = [c for c in (contrasts or []) if c.get("log2_fc") is not None]
        if rows:
            labels = [c["label"].replace("\n", " ") for c in rows]
            lfcs = [float(c["log2_fc"]) for c in rows]
            qs = [c.get("q_value") for c in rows]
            colors = ["#0a2540" if v > 0 else "#cf2828" for v in lfcs]  # up navy / down red
            texts = [f"{v:+.2f} {_sig_stars_plotly(q)}" for v, q in zip(lfcs, qs)]
            fig = go.Figure(go.Bar(
                x=lfcs, y=labels, orientation="h", marker_color=colors,
                text=texts, textposition="outside",
                customdata=[[(q if q is not None else float('nan'))] for q in qs],
                hovertemplate="%{y}<br>log2 FC %{x:+.2f}<br>q %{customdata[0]:.2e}<extra></extra>"))
            for xv, dash in [(0.0, "solid"), (0.5, "dot"), (-0.5, "dot")]:
                fig.add_vline(x=xv, line=dict(color="#888" if xv else "#333",
                              dash=dash, width=0.7 if xv else 1.0))
            max_abs = max(2.0, max(abs(v) for v in lfcs) * 1.5)
            fig.update_layout(
                title=f"{target} — DGE contrasts (tumor vs normal) in {indication}",
                xaxis_title="log2 FC", xaxis_range=[-max_abs, max_abs],
                template="plotly_white", showlegend=False, margin=dict(l=120, r=40, t=50, b=50))
            (out_dir / f"figure_{basename}_contrasts.plotly.json").write_text(fig.to_json())
            written.append({"id": f"{basename}_contrasts",
                            "path": f"figure_{basename}_contrasts.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[dge_deseq2] contrasts plotly skipped: {e}", file=sys.stderr)

    return written


def _sig_stars_plotly(q):
    """q-value significance stars — mirrors the SVG forest's _sig_stars thresholds exactly."""
    if q is None or q != q:
        return ""
    if q < 1e-10:
        return "***"
    if q < 1e-4:
        return "**"
    if q < 0.05:
        return "*"
    return "ns"
