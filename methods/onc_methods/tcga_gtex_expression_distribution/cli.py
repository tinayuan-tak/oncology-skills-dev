#!/usr/bin/env python3
"""tcga-gtex-expression-distribution CLI — per-sample tumor expression distribution (Q1).

Emits the expression-build bar (Tier1 summary.json + Tier2 plot_data.parquet + Tier3 SVG + plotly,
threaded into the manifest) for the per-sample TUMOR distribution of a target in an indication,
plus the matched-normal GTEx arm for the Q2 fraction-above-normal-percentile overlay.

Reads the two long products via read.py (predicate-pushdown, cached). data_unavailable-safe.

Usage:
    python -m onc_methods.tcga_gtex_expression_distribution.cli \\
        --target KRAS --indication COADREAD --out ~/dev/framework-runs/kras-coadread-exprdist
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from onc_methods.roots import contracts_root

from . import read as _read
from . import stats as _stats

METHOD_VERSION = "0.1.0"
# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
DEFAULT_TARGET_CONTRACTS = os.environ.get("TARGET_CONTRACTS_ROOT") or str(contracts_root())

_TUMOR_FILL, _TUMOR_LINE = "#1f4e79", "#0a2540"
_NORMAL_FILL, _NORMAL_LINE = "#a9c5db", "#5b7f99"

# Per-stratum subtype_signal → (fill, line). Diverging: enriched warm, depleted cool,
# uniform neutral, restricted a distinct accent; underpowered/None = muted grey.
_SIGNAL_COLORS = {
    "subtype_enriched": ("#c0603a", "#8f3f22"),  # warm — elevated vs pooled
    "subtype_restricted": ("#7b5ea7", "#553f7a"),  # accent — present here, absent pooled
    "subtype_depleted": ("#4a7fa5", "#2f5670"),  # cool — reduced vs pooled
    "subtype_uniform": ("#b8bcc0", "#7d8288"),  # neutral — no stratum signal
    None: ("#d9dbdd", "#a9adb1"),  # muted — underpowered (no call)
}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def build_summary(target: str, indication: str, plot_data_out=None) -> dict:
    """Q1 tumor distribution + the Q2 fraction-above-normal-p95/p99 overlay (matched GTEx normal).
    plot_data_out (figure offline seam): forwarded so plot_data_expression_distribution.parquet persists."""
    summary = _read.read_tumor_expression_distribution(target, indication, plot_data_out=plot_data_out)
    tumor = _read.read_tumor_samples(target, indication)
    normal, tissue = _read.read_normal_samples(target, indication)
    summary["matched_normal_tissue"] = tissue
    summary["n_normal_samples"] = len(normal)
    # Q2 headline enrichment metric at p95 + p99 (normal-relative cutoffs).
    for pct in (95, 99):
        fa = _stats.fraction_above_normal_percentile(tumor, normal, pct)
        summary[f"fraction_tumor_above_normal_p{pct}"] = fa["fraction_tumor_above"]
        summary[f"normal_p{pct}_log2tpm"] = fa["normal_pN"]
    summary["distribution_overlap_tumor_normal"] = _stats.distribution_overlap(tumor, normal)
    # Subtype ROLLUP only (COMPUTE-ALL happens in the assembler; the POOLED card carries only the
    # scalars + the FEW decision-relevant non-uniform strata). The full per-stratum panorama belongs
    # on the sibling tumor-rna-distribution-by-subtype card via build_subtype_panorama — cramming
    # all 11 strata into the pooled card overflows the synthesis prompt's per-card char cap and the
    # tail strata get truncated (measured end-to-end). Grain-split: pooled = rollup, subtype = panorama.
    land = _read.read_tumor_expression_subtype_landscape(target, indication)
    for k in (
        "subtype_axis_available",
        "spotlight_subtype",
        "n_subtypes_measured",
        "n_subtypes_enriched",
        "assignment_manifest",
        "_subtype_note",
    ):
        if k in land:
            summary[k] = land[k]
    # a compact digest: only the strata with a non-uniform signal (enriched/restricted/depleted) —
    # the actionable few, bounded, so the pooled card names the subtype story without the full table.
    lscape = land.get("subtype_landscape") or []
    summary["subtype_signals_nonuniform"] = [
        {
            "stratum_id": r["stratum_id"],
            "subtype_signal": r["subtype_signal"],
            "median_log2tpm": r.get("median_log2tpm"),
            "n_tumor_samples": r["n_tumor_samples"],
        }
        for r in lscape
        if r.get("subtype_signal") and r["subtype_signal"] != "subtype_uniform"
    ]
    summary["method_version"] = METHOD_VERSION
    return summary


def build_subtype_panorama(target: str, indication: str, plot_data_out=None) -> dict:
    """The target_subtype-grain panorama for the tumor-rna-distribution-by-subtype card.

    Returns the FULL per-stratum landscape as `per_subgroup_metrics` (the framework's panorama
    record field) plus the cross-stratum rollup scalars — the shape the subtype card declares.
    This is where the complete 11-stratum table lives (its own prompt char-budget), distinct from
    the pooled card's compact rollup. data_unavailable-safe (no shard → empty panorama).
    plot_data_out (figure offline seam): forwarded so plot_data_subtype.parquet (the per-stratum
    per-sample values behind the panel) persists during resolution → the subtype figure renders offline."""
    land = _read.read_tumor_expression_subtype_landscape(target, indication, plot_data_out=plot_data_out)
    return {
        "target": target,
        "indication": indication,
        "subtype_axis_available": land.get("subtype_axis_available", False),
        # subtype_axis_quality (powered|underpowered|empty|unavailable) is the HONEST capability grade the
        # card contract declares and the reader computes, but build_subtype_panorama previously dropped it
        # (only the pooled build_summary + the sibling cell-line panorama projected it), so the tumor-side
        # `subtype_axis_quality` headline field was permanently null. Project it (and the purity-spread
        # confounder the card also declares) so subtype_axis_available:true no longer masks an underpowered
        # axis. Verdict-inert (display-only honesty grade).
        "subtype_axis_quality": land.get("subtype_axis_quality"),
        "purity_source": land.get("purity_source"),  # card-declared; computed in `land` but was not lifted here
        "subtype_purity_spread": land.get("subtype_purity_spread"),
        "spotlight_subtype": land.get("spotlight_subtype"),
        "assignment_manifest": land.get("assignment_manifest"),
        "n_subtypes_measured": land.get("n_subtypes_measured", 0),
        "n_subtypes_enriched": land.get("n_subtypes_enriched", 0),
        # normal-window rollup + comparator provenance (2026-08-04 enrichment) — project the card-level
        # fields the landscape now emits so the summary carries them (the per-stratum window fields ride
        # inside per_subgroup_metrics; these are the cross-stratum rollup + the matched/proxy label).
        "n_subtypes_clearing_normal_window": land.get("n_subtypes_clearing_normal_window"),
        "n_subtypes_clearing_proxy_window_by_tissue": land.get("n_subtypes_clearing_proxy_window_by_tissue"),
        "n_subtypes_restricted": land.get("n_subtypes_restricted"),
        "subtype_stratification_class": land.get("subtype_stratification_class"),
        "matched_normal_tissue": land.get("matched_normal_tissue"),
        "normal_comparator_type": land.get("normal_comparator_type"),
        "proxy_normal_tissues": land.get("proxy_normal_tissues") or [],
        # across-subtype omnibus (Phase 3) — the ANOVA-analogue: is subtype a patient-selection
        # axis for this target, and how strong (ε² variance-explained)? Effect-size class is the
        # decision-relevant field; p is display-only. Run PER-AXIS (B11-S1-2): the flat fields
        # carry the driving (largest-ε²) axis; subtype_omnibus_by_axis is the full breakdown.
        "subtype_omnibus_kruskal_h": land.get("subtype_omnibus_kruskal_h"),
        "subtype_omnibus_p": land.get("subtype_omnibus_p"),
        "subtype_variance_explained": land.get("subtype_variance_explained"),
        "subtype_effect_size_class": land.get("subtype_effect_size_class", "data_unavailable"),
        "which_subtypes_separate": land.get("which_subtypes_separate"),
        "subtype_omnibus_driving_axis": land.get("driving_axis"),
        "subtype_omnibus_by_axis": land.get("subtype_omnibus_by_axis") or [],
        "per_subgroup_metrics": land.get("subtype_landscape") or [],
        **({"_subtype_note": land["_subtype_note"]} if "_subtype_note" in land else {}),
        "method_version": METHOD_VERSION,
    }


def build_selectivity_crossing_summary(target: str, indication: str, plot_data_out=None) -> dict:
    """Q2 (Gate B) — per-sample tumor-vs-normal percentile-crossing selectivity. Thin wrapper over
    read_tumor_vs_normal_percentile_crossing so the dispatcher has a stable build_* entry point
    (mirrors build_summary). plot_data_out (figure offline seam): forwarded so the per-sample
    plot_data persists during resolution."""
    summary = _read.read_tumor_vs_normal_percentile_crossing(target, indication, plot_data_out=plot_data_out)
    summary["method_version"] = METHOD_VERSION
    return summary


def build_selectivity_crossing_subtype_panorama(target: str, indication: str) -> dict:
    """Q2-by-SUBTYPE (Phase B) — per-stratum tumor-vs-normal PERCENTILE-CROSSING selectivity.

    A target may separate from normal ONLY in one molecular subtype (a patient-selection signal the
    pooled crossing averages away). The per-sample subtype landscape reader ALREADY computes the
    per-stratum crossing metrics (fraction_tumor_above_normal_p95/p99 + distribution_overlap) against
    the indication-wide matched normal — this projects those into a crossing-focused panorama and
    classifies each stratum with the SAME pooled vocabulary (_classify_percentile_crossing), so the
    pooled `tumor-vs-normal-percentile-crossing` grain and this subtype grain never diverge.

    Returns `per_subgroup_metrics` (one crossing record per measured stratum) + cross-stratum rollup
    scalars. DESCRIPTIVE (verdict-inert): the tumor-selectivity spine stays keyed to the aggregate
    card + the pooled crossing corroboration; this is a --subtypes panorama. data_unavailable-safe
    (no shard / no matched normal → empty panorama)."""
    land = _read.read_tumor_expression_subtype_landscape(target, indication)
    strata = land.get("subtype_landscape") or []
    per_subgroup = []
    for rec in strata:
        frac95 = rec.get("fraction_tumor_above_normal_p95")
        crossing_class = (
            _read._classify_percentile_crossing(frac95, rec.get("distribution_overlap_tumor_normal"))
            if rec.get("evidence_state") == "measured" and frac95 is not None
            else "data_unavailable"
        )
        per_subgroup.append(
            {
                "stratum_id": rec.get("stratum_id"),
                "evidence_state": rec.get("evidence_state"),
                "n_tumor_samples": rec.get("n_tumor_samples"),
                "percentile_crossing_class": crossing_class,
                "fraction_tumor_above_normal_p95": frac95,
                "fraction_tumor_above_normal_p99": rec.get("fraction_tumor_above_normal_p99"),
                "distribution_overlap_tumor_normal": rec.get("distribution_overlap_tumor_normal"),
            }
        )
    # cross-stratum rollup: is crossing-selectivity a subtype-specific (patient-selection) signal?
    measured = [
        m
        for m in per_subgroup
        if m["evidence_state"] == "measured" and m["fraction_tumor_above_normal_p95"] is not None
    ]
    fracs = [m["fraction_tumor_above_normal_p95"] for m in measured]
    n_strong = sum(1 for m in measured if m["percentile_crossing_class"] == "strongly_tumor_enriched")
    return {
        "target": target,
        "indication": indication,
        "subtype_axis_available": land.get("subtype_axis_available", False),
        "assignment_manifest": land.get("assignment_manifest") or land.get("_assignment_manifest"),
        "matched_normal_tissue": land.get("matched_normal_tissue"),
        "normal_comparator_type": land.get("normal_comparator_type"),
        "n_subtypes_measured": len(measured),
        "n_subtypes_strongly_enriched": n_strong,
        "max_subtype_fraction_above_normal_p95": max(fracs) if fracs else None,
        "min_subtype_fraction_above_normal_p95": min(fracs) if fracs else None,
        # a subtype-specific crossing signal = some strata strongly enriched, others not (range spans a
        # class boundary). Verdict-inert flag; the pooled crossing stays the corroboration of record.
        "crossing_varies_by_subtype": (bool(fracs) and (max(fracs) - min(fracs) >= 0.25)),
        "per_subgroup_metrics": per_subgroup,
        **({"_subtype_note": land["_subtype_note"]} if "_subtype_note" in land else {}),
        "method_version": METHOD_VERSION,
    }


def build_normal_liability_summary(target: str, indication: str = None, plot_data_out=None) -> dict:
    """Q3 (Safety / Surface-modality-fit) — target-grain normal-tissue liability over the GTEx
    atlas. indication is accepted for the CARD_DISPATCHERS contract but NOT consumed (target-grain).
    Thin wrapper over read_normal_tissue_liability. plot_data_out (figure offline seam): forwarded so
    plot_data_normal_tissue_atlas.parquet persists during resolution."""
    summary = _read.read_normal_tissue_liability(target, plot_data_out=plot_data_out)
    summary["method_version"] = METHOD_VERSION
    return summary


# antigen-prevalence card thresholds (mirror antigen-prevalence.card.yaml `thresholds`). A cutoff in
# linear TPM maps into the reader's log2(TPM+1) space as log2(cutoff + 1): TPM 1.0 -> 1.0 and
# TPM 10.0 -> log2(11) ~= 3.4594 (the same anchors stats.expression_fractions uses for
# detectable/moderate). Kept explicit so `cutoff_used_tpm` is truthful and the card's declared
# thresholds are the single source this projection honours.
CLINICAL_RELEVANCE_TPM = 1.0
HIGH_EXPRESSION_TPM = 10.0


def build_antigen_prevalence(target: str, indication: str, plot_data_out=None) -> dict:
    """antigen-prevalence card (DESCRIPTIVE) — patient-selection prevalence: what fraction of an
    indication's tumors express `target` at clinically-relevant / high levels?

    A projection of the SAME per-sample tumor long product build_summary reads (read_tumor_samples ->
    log2(TPM+1) per sample, restricted to the indication's TCGA study/studies) onto the card's two
    fixed clinical TPM cutoffs. Prevalence is a per-SAMPLE count question, so it cannot be recovered
    from the whole-cohort differential the card was formerly (mis-)pointed at — it needs the surviving
    per-sample rows this reader already returns. data_unavailable-safe: no rows -> all-None fractions
    with n_samples 0 (never a spurious 0.0 prevalence).

    plot_data_out is accepted for the figure offline seam (generic-dispatch contract); the
    `prevalence_curve_with_thresholds` emitter is a follow-on, so it is currently inert here."""
    import numpy as np

    values = _read.read_tumor_samples(target, indication)
    a = np.asarray(values, dtype=float)
    a = a[~np.isnan(a)]
    n = int(a.size)
    if n == 0:
        return {
            "fraction_clinically_relevant": None,
            "fraction_high_expression": None,
            "n_samples": 0,
            "median_tpm": None,
            "cutoff_used_tpm": CLINICAL_RELEVANCE_TPM,
            "method_version": METHOD_VERSION,
        }
    clinical_log2 = float(np.log2(CLINICAL_RELEVANCE_TPM + 1.0))
    high_log2 = float(np.log2(HIGH_EXPRESSION_TPM + 1.0))
    # median reported in LINEAR TPM (the card field is median_tpm, not log2): invert log2(TPM+1).
    median_tpm = float(np.power(2.0, float(np.median(a))) - 1.0)
    return {
        "fraction_clinically_relevant": float(np.mean(a >= clinical_log2)),
        "fraction_high_expression": float(np.mean(a >= high_log2)),
        "n_samples": n,
        "median_tpm": round(median_tpm, 4),
        "cutoff_used_tpm": CLINICAL_RELEVANCE_TPM,
        "method_version": METHOD_VERSION,
    }


def emit_plot_data(target: str, indication: str, out_dir: Path, *, presampled=None) -> Path:
    """Tier-2: the per-sample long-format rows behind the figure (tumor + matched normal).

    presampled (figure Stage 6): OPT-IN (tumor, normal, tissue) already-loaded vectors — pass them to
    persist WITHOUT a second read (the resolver already loaded tumor). None = read live (legacy)."""
    import pandas as pd

    if presampled is not None:
        tumor, normal, tissue = presampled
    else:
        tumor = _read.read_tumor_samples(target, indication)
        normal, tissue = _read.read_normal_samples(target, indication)
    rows = [{"group": "tumor", "source": "TCGA", "log2_tpm": v} for v in tumor] + [
        {"group": "normal", "source": f"GTEx:{tissue}", "log2_tpm": v} for v in normal
    ]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)  # per-card dir (plot_data_root/cards/<id>) may not exist yet
    out = out_dir / "plot_data_expression_distribution.parquet"
    pd.DataFrame(rows, columns=["group", "source", "log2_tpm"]).to_parquet(out, index=False)
    return out


def _load_style(contracts_dir):
    try:
        import matplotlib.pyplot as plt

        style = Path(contracts_dir) / "plot_styles" / "takeda_oncology.mplstyle"
        if style.exists():
            plt.style.use(str(style))
    except Exception:  # noqa: BLE001
        pass


def _pal(contracts_dir):
    """Load the mplstyle + return the takeda_palette module (verdict badge / takeaway / colors).
    Idempotent; returns None if the palette is unavailable (draws degrade to no-badge)."""
    _load_style(contracts_dir)
    try:
        from oncology_target_contracts.plot_styles import takeda_palette

        return takeda_palette
    except Exception:  # noqa: BLE001
        return None


# tumor_expression_class -> plain-English phrase for the title (no machine tokens on the figure).
_TUMOR_CLASS_PHRASE = {
    "broadly_high": "RNA is highly expressed across tumors",
    "broadly_detected": "RNA is detected across tumors",
    "subset_high": "RNA is high in a tumor subset",
    "broadly_moderate": "RNA is moderately expressed across tumors",
    "low_or_absent": "RNA is low or absent in tumors",
    "data_unavailable": "tumor RNA expression",
}
# fallback signal when fired_rules aren't threaded in (keeps the badge honest, not a fabricated call).
_TUMOR_CLASS_SIGNAL = {
    "broadly_high": "supportive",
    "broadly_detected": "supportive",
    "subset_high": "supportive",
    "broadly_moderate": "neutral",
    "low_or_absent": "opposing",
    "data_unavailable": "insufficient",
}


def emit_svg(
    target: str,
    indication: str,
    summary: dict,
    out_dir: Path,
    contracts_dir=DEFAULT_TARGET_CONTRACTS,
    *,
    presampled=None,
    status=None,
) -> Path:
    """Tier-3 SVG: tumor vs matched-normal per-sample distribution (box + strip), in the shared
    figure grammar — plain-English title, source subtitle, reserved verdict BADGE (top-right),
    a data-derived one-line takeaway, normal-p95 as a NEUTRAL orientation line.

    presampled: OPT-IN (tumor, normal, tissue) vectors from persisted plot_data → draw OFFLINE.
    status: OPT-IN status dict (from takeda_palette.status_for_card over the run's fired_rules) so
            the badge == the narrative verdict. When None, a fallback signal is derived from the
            card's tumor_expression_class (honest, but the fired-rule route is preferred)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    pal = _pal(contracts_dir)
    out_path = Path(out_dir) / "figure_expression_distribution.svg"

    if presampled is not None:
        tumor, normal, tissue = presampled
    else:
        tumor = _read.read_tumor_samples(target, indication)
        normal, tissue = _read.read_normal_samples(target, indication)
    if not tumor:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(
            0.5,
            0.5,
            f"{target} — no TCGA tumor samples for {indication}",
            ha="center",
            va="center",
            fontsize=10,
            color="#777",
        )
        ax.set_axis_off()
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    if pal is None:  # palette/frame unavailable → minimal honest fallback
        fig, ax = plt.subplots(figsize=(7.0, 3.5))
        ax.boxplot([normal, tumor] if normal else [tumor], orientation="horizontal", showfliers=False)
        ax.set_xlabel("Expression — log2(TPM + 1)")
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    tfill, tline = pal.TUMOR_FILL, pal.TUMOR_LINE
    nfill, nline = pal.NORMAL_FILL, pal.NORMAL_LINE
    # tumor on top, normal below → the eye reads the tumor shift against normal.
    groups, labels, colors = [], [], []
    if normal:
        groups.append(normal)
        labels.append(f"Normal\n({tissue.title()})")
        colors.append((nfill, nline))
    groups.append(tumor)
    labels.append("Tumor")
    colors.append((tfill, tline))

    p95 = summary.get("normal_p95_log2tpm")
    fa95 = summary.get("fraction_tumor_above_normal_p95")
    take = (
        f"{fa95 * 100:.0f}% of {indication} tumors express {target} above the normal 95th percentile."
        if (fa95 is not None and p95 is not None)
        else None
    )

    # figure_frame owns figsize/margins/title/provenance/takeaway + save; the emitter only draws data.
    with pal.figure_frame(
        target,
        indication,
        "tumor vs. normal expression",
        out_path=out_path,
        kind="single",
        provenance=f"TCGA {indication} tumor  ·  GTEx {tissue.title()} normal  ·  recount3 / GENCODE v26",
        takeaway=take,
    ) as F:
        ax = F.ax
        bp = ax.boxplot(
            groups,
            orientation="horizontal",
            widths=0.55,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": "#222", "linewidth": 1.4},
        )
        for patch, (fill, line) in zip(bp["boxes"], colors):
            patch.set(facecolor=fill, edgecolor=line, alpha=0.55, linewidth=1.0)
        for element in ("whiskers", "caps"):
            for artist in bp[element]:
                artist.set(color="#5A626A", linewidth=1.0)
        rng = np.random.default_rng(seed=42)
        for i, (vals, (fill, line)) in enumerate(zip(groups, colors)):
            yy = rng.uniform(i + 1 - 0.15, i + 1 + 0.15, size=len(vals))
            ax.scatter(vals, yy, s=5, color=line, alpha=0.30, edgecolor="none", zorder=3)
        # normal p95 = a NEUTRAL orientation marker (its meaning is carried by the takeaway).
        if p95 is not None:
            ax.axvline(p95, zorder=1, **pal.REFLINE_NEUTRAL)
            ax.annotate(
                "normal p95",
                xy=(p95, 0.5),
                xycoords=("data", "axes fraction"),
                fontsize=7,
                color="#666666",
                ha="center",
                va="bottom",
                xytext=(0, 2),
                textcoords="offset points",
            )
        ax.set_yticks(range(1, len(labels) + 1))
        ax.set_yticklabels(labels, fontsize=8.5)
        ax.set_ylim(0.4, len(labels) + 0.6)
        ax.grid(axis="x", alpha=0.25, linewidth=0.4)
        ax.grid(axis="y", visible=False)
        F.axis_label("x", "Expression", "log2(TPM + 1), per RNA-seq sample")
        F.n_on_boxes([len(g) for g in groups])  # per-sample distribution → n on the boxes
    return out_path


def emit_plotly_specs(
    target: str, indication: str, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS, *, presampled=None
) -> list:
    """Interactive twin — same per-sample values as the SVG (no drift). Best-effort.

    presampled (figure Stage 6): OPT-IN (tumor, normal, tissue) vectors → no live re-read."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001
        _log(f"[expr-dist] plotly skipped: {e}")
        return []
    if presampled is not None:
        tumor, normal, tissue = presampled
    else:
        tumor = _read.read_tumor_samples(target, indication)
        normal, tissue = _read.read_normal_samples(target, indication)
    if not tumor:
        return []
    fig = go.Figure()
    fig.add_trace(
        go.Box(
            x=tumor,
            name=f"TCGA tumor (n={len(tumor)})",
            orientation="h",
            marker_color=_TUMOR_LINE,
            fillcolor=_TUMOR_FILL,
            line=dict(width=1),
            boxpoints="all",
            jitter=0.4,
            pointpos=0,
            marker=dict(size=3, opacity=0.4),
        )
    )
    if normal:
        fig.add_trace(
            go.Box(
                x=normal,
                name=f"GTEx {tissue} (n={len(normal)})",
                orientation="h",
                marker_color=_NORMAL_LINE,
                fillcolor=_NORMAL_FILL,
                line=dict(width=1),
                boxpoints="all",
                jitter=0.4,
                pointpos=0,
                marker=dict(size=3, opacity=0.4),
            )
        )
    fig.update_layout(
        title=f"{target} in {indication} — per-sample expression distribution",
        xaxis_title="log2(TPM + 1) — recount3 / GENCODE v26",
        template="plotly_white",
        margin=dict(l=120, r=40, t=50, b=50),
    )
    (Path(out_dir) / "figure_expression_distribution.plotly.json").write_text(fig.to_json())
    return [
        {
            "id": "expression_distribution_per_sample",
            "path": "figure_expression_distribution.plotly.json",
            "type": "plotly",
        }
    ]


def emit_subtype_svg(
    target: str, indication: str, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS, *, presampled=None
) -> Optional[Path]:
    """Tier-3 SVG for the SUBTYPE card: one box+strip row per molecular subtype, ordered by
    median, colored by subtype_signal (enriched/depleted/restricted/uniform), with the pooled
    median as a dashed reference line. Returns None if the subtype axis is unavailable."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _load_style(contracts_dir)
    data = presampled if presampled is not None else _read.read_tumor_subtype_values(target, indication)
    out_path = Path(out_dir) / "figure_expression_distribution_subtype.svg"
    if not data.get("available") or not data.get("strata"):
        return None
    strata = [s for s in data["strata"] if s["n"] > 0]
    if not strata:
        return None
    fig, ax = plt.subplots(figsize=(7.6, max(3.0, 0.5 * len(strata) + 1.2)))
    groups = [s["values"] for s in strata]
    bp = ax.boxplot(
        groups,
        orientation="horizontal",
        widths=0.6,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "#222", "linewidth": 1.2},
    )
    rng = np.random.default_rng(seed=42)
    labels = []
    for i, s in enumerate(strata):
        fill, line = _SIGNAL_COLORS.get(s["subtype_signal"], _SIGNAL_COLORS[None])
        bp["boxes"][i].set(facecolor=fill, edgecolor=line, alpha=0.55, linewidth=1.0)
        yy = rng.uniform(i + 1 - 0.16, i + 1 + 0.16, size=len(s["values"]))
        ax.scatter(s["values"], yy, s=4, color=line, alpha=0.3, edgecolor="none", zorder=3)
        sig = (s["subtype_signal"] or "underpowered").replace("subtype_", "")
        labels.append(f"{s['stratum_id']}\n(n={s['n']}, {sig})")
    pm = data.get("pooled_median")
    if pm is not None:
        ax.axvline(pm, color="#444", linewidth=1.0, linestyle="--", zorder=1)
        ax.text(pm, len(strata) + 0.5, f"pooled median {pm:.1f}", color="#444", fontsize=7, ha="center", va="bottom")
    ax.set_yticks(range(1, len(labels) + 1))
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlabel("log2(TPM + 1) — recount3 / GENCODE v26 (per sample)")
    ax.set_title(f"{target} in {indication} — expression by molecular subtype")
    ax.grid(axis="x", alpha=0.25, linewidth=0.4)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_subtype_plotly_specs(
    target: str, indication: str, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS, *, presampled=None
) -> list:
    """Interactive twin of the subtype panel — same per-stratum values (no drift). Best-effort.

    presampled (figure Stage 6): OPT-IN read_tumor_subtype_values() dict → no live re-read."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001
        _log(f"[expr-dist-subtype] plotly skipped: {e}")
        return []
    data = presampled if presampled is not None else _read.read_tumor_subtype_values(target, indication)
    strata = [s for s in (data.get("strata") or []) if s["n"] > 0]
    if not data.get("available") or not strata:
        return []
    fig = go.Figure()
    for s in strata:
        fill, line = _SIGNAL_COLORS.get(s["subtype_signal"], _SIGNAL_COLORS[None])
        sig = (s["subtype_signal"] or "underpowered").replace("subtype_", "")
        fig.add_trace(
            go.Box(
                x=s["values"],
                name=f"{s['stratum_id']} (n={s['n']}, {sig})",
                orientation="h",
                marker_color=line,
                fillcolor=fill,
                line=dict(width=1),
                boxpoints="all",
                jitter=0.4,
                pointpos=0,
                marker=dict(size=3, opacity=0.35),
            )
        )
    pm = data.get("pooled_median")
    if pm is not None:
        fig.add_vline(x=pm, line_dash="dash", line_color="#444", annotation_text=f"pooled median {pm:.1f}")
    fig.update_layout(
        title=f"{target} in {indication} — expression by molecular subtype",
        xaxis_title="log2(TPM + 1) — recount3 / GENCODE v26",
        template="plotly_white",
        showlegend=False,
        margin=dict(l=150, r=40, t=50, b=50),
    )
    (Path(out_dir) / "figure_expression_distribution_subtype.plotly.json").write_text(fig.to_json())
    return [
        {
            "id": "expression_distribution_subtype_panel",
            "path": "figure_expression_distribution_subtype.plotly.json",
            "type": "plotly",
        }
    ]


# ---- Q3 normal-tissue-liability atlas figure ----
_CRITICAL_FILL, _CRITICAL_LINE = "#cf2828", "#8f1a1a"  # critical organs — red (liability)
_NONCRIT_FILL, _NONCRIT_LINE = "#a9c5db", "#5b7f99"  # non-critical — muted blue


def emit_liability_svg(
    target: str,
    out_dir: Path,
    contracts_dir=DEFAULT_TARGET_CONTRACTS,
    *,
    indication: Optional[str] = None,
    presampled=None,
) -> Optional[Path]:
    """Tier-3 SVG for the Q3 liability card: per-GTEx-tissue median expression bar (ranked),
    critical organs highlighted red. Optionally shows the tumor median for the indication.

    presampled (figure Stage 6): OPT-IN atlas {tissue: [values]} from persisted plot_data → draw
    OFFLINE with no live re-read. None = read live (legacy)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    from . import stats as _st

    _load_style(contracts_dir)
    atlas = presampled if presampled is not None else _read.read_all_normal_tissues(target)
    out_path = Path(out_dir) / "figure_normal_tissue_liability.svg"
    if not atlas:
        return None
    rows = []
    for tissue, vals in atlas.items():
        arr = np.asarray(vals, dtype=float)
        arr = arr[~np.isnan(arr)]
        if arr.size:
            rows.append((str(tissue).upper(), float(np.median(arr))))
    if not rows:
        return None
    rows.sort(key=lambda r: r[1])
    crit = set(_st.CRITICAL_NORMAL_TISSUES)
    labels = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    colors = [(_CRITICAL_FILL if t in crit else _NONCRIT_FILL) for t in labels]
    edges = [(_CRITICAL_LINE if t in crit else _NONCRIT_LINE) for t in labels]
    fig, ax = plt.subplots(figsize=(7.2, max(3.5, 0.26 * len(rows) + 1.0)))
    ax.barh(range(len(rows)), vals, color=colors, edgecolor=edges, linewidth=0.8, alpha=0.85)

    # Add tumor median line if indication is provided
    tumor_median = None
    if indication:
        tumor_vals = _read.read_tumor_samples(target, indication)
        if tumor_vals:
            tumor_median = float(np.median(tumor_vals))
            ax.axvline(tumor_median, color="#1f4e79", linewidth=1.5, linestyle=":", zorder=3)

    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(labels, fontsize=6.5)
    ax.set_xlabel("median log2(TPM + 1) — GTEx normal (recount3 / GENCODE v26)")

    # Title with indication info if provided
    if indication and tumor_median is not None:
        ax.set_title(f"{target} — normal-tissue expression atlas (critical organs in red)")
        # Add legend for tumor median line
        from matplotlib.lines import Line2D
        legend_handles = [
            Line2D([0], [0], color="#1f4e79", linewidth=1.5, linestyle=":", label=f"{indication} tumor median"),
        ]
        ax.legend(handles=legend_handles, loc="lower right", fontsize=7, frameon=True, framealpha=0.9)
    else:
        ax.set_title(f"{target} — normal-tissue expression atlas (critical organs in red)")

    ax.grid(axis="x", alpha=0.25, linewidth=0.4)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_liability_plotly_specs(
    target: str, out_dir: Path, contracts_dir=DEFAULT_TARGET_CONTRACTS, *, presampled=None
) -> list:
    """Interactive twin of the liability atlas bar (same per-tissue medians). Best-effort.

    presampled (figure Stage 6): OPT-IN atlas {tissue: [values]} → no live re-read."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001
        _log(f"[normal-liability] plotly skipped: {e}")
        return []
    import numpy as np

    from . import stats as _st

    atlas = presampled if presampled is not None else _read.read_all_normal_tissues(target)
    rows = []
    for tissue, vals in (atlas or {}).items():
        arr = np.asarray(vals, dtype=float)
        arr = arr[~np.isnan(arr)]
        if arr.size:
            rows.append((str(tissue).upper(), float(np.median(arr))))
    if not rows:
        return []
    rows.sort(key=lambda r: r[1])
    crit = set(_st.CRITICAL_NORMAL_TISSUES)
    fig = go.Figure(
        go.Bar(
            x=[r[1] for r in rows],
            y=[r[0] for r in rows],
            orientation="h",
            marker_color=[(_CRITICAL_FILL if r[0] in crit else _NONCRIT_FILL) for r in rows],
        )
    )
    fig.add_vline(x=_st.HIGH_LOG2TPM, line_dash="dash", line_color="#444", annotation_text="high cutoff")
    fig.update_layout(
        title=f"{target} — normal-tissue expression atlas (critical organs red)",
        xaxis_title="median log2(TPM + 1) — GTEx normal",
        template="plotly_white",
        margin=dict(l=110, r=40, t=50, b=50),
    )
    (Path(out_dir) / "figure_normal_tissue_liability.plotly.json").write_text(fig.to_json())
    return [
        {"id": "normal_tissue_liability_atlas", "path": "figure_normal_tissue_liability.plotly.json", "type": "plotly"}
    ]


def emit_manifest(
    target: str, indication: str, summary: dict, out_dir: Path, plotly_specs: Optional[list] = None
) -> Path:
    """Tier-describing manifest with the plotly_figures slot (matches the expression bar)."""
    manifest = {
        "method": "tcga_gtex_expression_distribution",
        "method_version": METHOD_VERSION,
        "target": target,
        "indication": indication,
        "tumor_expression_class": summary.get("tumor_expression_class"),
        "n_tumor_samples": summary.get("n_tumor_samples"),
        "artifacts": {
            "summary": "summary.json",
            "plot_data": "plot_data_expression_distribution.parquet",
            "svg": "figure_expression_distribution.svg",
        },
        "plotly_figures": plotly_specs or [],
    }
    out = Path(out_dir) / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2, default=str))
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--target-contracts", default=DEFAULT_TARGET_CONTRACTS)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    summary = build_summary(args.target, args.indication)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_plot_data(args.target, args.indication, args.out)
    emit_svg(args.target, args.indication, summary, args.out, args.target_contracts)
    specs = emit_plotly_specs(args.target, args.indication, args.out, args.target_contracts)
    emit_manifest(args.target, args.indication, summary, args.out, specs)
    _log(
        f"[expr-dist] {args.target}/{args.indication}: "
        f"{summary.get('tumor_expression_class')} "
        f"n={summary.get('n_tumor_samples')} -> {args.out} (plotly {len(specs)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
