"""hpa_normal_tissue_liability.cli — normal-tissue on-target-off-tumor safety.

Reads the HPA master TSV (hpa-v25-1, already landed + consumed by 8 other cards)
IHC-derived protein-tissue fields and emits the `normal-tissue-liability` card
summary — the dominant biologics on-target-off-tumor safety signal.

Two fields:
  - `Protein tissue distribution` (Not detected | Detected in single | some | many
    | all) — pathologist-scored IHC BREADTH across normal tissues (~96% coverage).
    → normal_tissue_breadth_class (the primary categorical).
  - `Protein tissue specific Intensity` ("intestine: 2.3e5;lymphoid tissue: ...")
    — named-tissue list (~51% coverage, the tissue-enriched subset). Parsed to flag
    ESSENTIAL-tissue expression.

HPA uses a CLOSED 16-name tissue vocabulary in the specific-intensity field, so the
essential-tissue set is an EXACT membership test (no fuzzy matching). A gene absent
from HPA / with no tissue-distribution call → data_unavailable (coverage gap, NOT a
favorable window — do not read absence as safety).
"""

from __future__ import annotations

import sys
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for
from methods.normal_tissue_safety_common import HPA_ESSENTIAL_TISSUES

METHOD_VERSION = "0.2.0"  # 2026-08-24: essential_tissue_flag trichotomy (present/unknown/absent) —
# fix broad-gene killer under-firing + `absent` data-gap overloading

SOURCE_MANIFEST_ID = "hpa-v25-1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, _SOURCE_PREFIX = bucket_prefix_for(SOURCE_MANIFEST_ID)
HPA_KEY = f"{_SOURCE_PREFIX}proteinatlas.tsv.zip"
DEFAULT_AWS_PROFILE = "cbg"

# The HPA master zip was previously re-downloaded from S3 on EVERY call
# (no lru, no disk cache) — paid multiple times per target-profile run (verdict pass + figure pass)
# and every process start. Add a disk cache (download once per machine) + an lru_cache on the parsed
# DataFrame (reuse across calls in a process). Mirrors the depmap_common/parquet.py disk-latch pattern.
HPA_CACHE_DIR = Path.home() / ".cache" / "framework-hpa-v25-1"
HPA_CACHE_ZIP = HPA_CACHE_DIR / "proteinatlas.tsv.zip"

HPA_GENE_COL = "Gene"
HPA_DIST_COL = "Protein tissue distribution"
HPA_SPEC_COL = "Protein tissue specificity"
HPA_INTENSITY_COL = "Protein tissue specific Intensity"

# HPA `Protein tissue distribution` → normal_tissue_breadth_class.
_DIST_TO_CLASS = {
    "detected in all": "broad_normal_expression",
    "detected in many": "broad_normal_expression",
    "detected in some": "moderate_normal_expression",
    "detected in single": "restricted_normal_expression",
    "not detected": "not_detected_in_normal",
}

# Essential-tissue set (exact membership over HPA's closed 16-name vocabulary): life-critical
# tissues where on-target-off-tumor toxicity is catastrophic. The strict-modality (BiTE/TCE/cell)
# killer keys off ANY hit here. SINGLE-SOURCED from
# normal_tissue_safety_common — this ADDS "blood vessel" (was omitted though it IS in HPA's vocab;
# an endothelial-restricted TCE antigen previously escaped the killer). NOTE: thyroid / adrenal /
# pituitary do NOT exist in HPA's 16-name grouped-intensity field, so endocrine coverage here is a
# DATA-SUBSTRATE gap (not a list omission) — the GTEx-RNA + single-cell normal cards cover those.
ESSENTIAL_TISSUES = HPA_ESSENTIAL_TISSUES
# GI epithelium — modality-dependent (ADC non-cleavable may tolerate; BiTE not).
GI_TISSUES = {"intestine", "stomach"}


from methods.target_id_sidecar import ensure_aws_profile


def _ensure_hpa_cached() -> Path:
    """Download the HPA master zip to the local disk cache ONCE per machine; return the local path.
    Second-session / second-call runs are a no-op cache hit (mirrors depmap_common/parquet.py)."""
    HPA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if HPA_CACHE_ZIP.exists() and HPA_CACHE_ZIP.stat().st_size > 0:
        return HPA_CACHE_ZIP
    ensure_aws_profile()
    import boto3

    print(f"[hpa] downloading s3://{S3_BUCKET}/{HPA_KEY} -> {HPA_CACHE_ZIP}", file=sys.stderr)
    boto3.client("s3").download_file(S3_BUCKET, HPA_KEY, str(HPA_CACHE_ZIP))
    return HPA_CACHE_ZIP


def _read_zip_cols(zip_path, cols):
    import pandas as pd

    z = zipfile.ZipFile(zip_path)
    with z.open(z.namelist()[0]) as f:
        return pd.read_csv(f, sep="\t", usecols=cols, dtype=str)


@lru_cache(maxsize=1)
def _read_hpa_cached_default():
    """The default (S3-backed) HPA read — parsed ONCE per process (lru) off the disk cache.
    Only used when no explicit hpa_path override is passed (the live path)."""
    cols = [HPA_GENE_COL, HPA_DIST_COL, HPA_SPEC_COL, HPA_INTENSITY_COL]
    return _read_zip_cols(_ensure_hpa_cached(), cols)


def _read_hpa(hpa_path=None):
    import pandas as pd

    cols = [HPA_GENE_COL, HPA_DIST_COL, HPA_SPEC_COL, HPA_INTENSITY_COL]
    if hpa_path is not None:
        # explicit override (tests / local file) — NOT cached (callers may vary the path)
        p = str(hpa_path)
        if p.endswith(".zip"):
            return _read_zip_cols(p, cols)
        return pd.read_csv(p, sep="\t", usecols=cols, dtype=str)
    # live path: disk-cache the zip + lru-cache the parse (return a copy so callers can't mutate
    # the shared cached frame).
    return _read_hpa_cached_default().copy()


def parse_specific_tissues(intensity_value: Optional[str]) -> list:
    """Parse 'intestine: 2.3e5;lymphoid tissue: 1.1e4' → [{tissue, intensity}]."""
    if not intensity_value or str(intensity_value) == "nan":
        return []
    out = []
    for part in str(intensity_value).split(";"):
        if ":" not in part:
            continue
        name, val = part.rsplit(":", 1)
        name = name.strip().lower()
        try:
            intensity = float(val.strip())
        except (ValueError, AttributeError):
            intensity = None
        if name:
            out.append({"tissue": name, "intensity": intensity})
    return out


def classify_breadth(dist_value: Optional[str]) -> str:
    """Protein tissue distribution → normal_tissue_breadth_class."""
    if dist_value is None or str(dist_value) == "nan":
        return "data_unavailable"
    return _DIST_TO_CLASS.get(str(dist_value).strip().lower(), "data_unavailable")


def compute_summary(gene: str, row: Optional[dict]) -> dict:
    """Build the normal-tissue-liability card summary from an HPA row."""
    if row is None:
        return {
            "normal_tissue_breadth_class": "data_unavailable",
            "essential_tissue_flag": "unknown",  # gene absent from HPA → no data (NOT a measured `absent`)
            "hpa_tissue_distribution": None,
            "hpa_tissue_specificity": None,
            "n_essential_tissues_with_expression": 0,
            "essential_tissues_flagged": [],
            "n_specific_tissues": 0,
            "specific_tissues": [],
            "safety_tissue_flags": [],
            "method_version": METHOD_VERSION,
        }
    dist = row.get(HPA_DIST_COL)
    dist = None if (dist is None or str(dist) == "nan") else str(dist)
    spec = row.get(HPA_SPEC_COL)
    spec = None if (spec is None or str(spec) == "nan") else str(spec)
    breadth = classify_breadth(dist)
    specific = parse_specific_tissues(row.get(HPA_INTENSITY_COL))
    names = {t["tissue"] for t in specific}
    essential = sorted(names & ESSENTIAL_TISSUES)
    gi = sorted(names & GI_TISSUES)

    # essential_tissue_flag trichotomy (2026-08-24 druggability audit). The flag previously derived
    # ONLY from the tissue-ENRICHMENT list (HPA_INTENSITY_COL, ~51% coverage), so a broadly-expressed
    # gene with an empty enrichment list read `absent` and the normal-tissue-essential-bite-killer
    # silently under-fired — exactly for the broadest, riskiest antigens. Two corrections:
    #   present : an essential organ is ENRICHED, OR `Detected in all` (every tissue, incl. all essential
    #             organs, is expressed even when nothing is tissue-enriched). Fires the TCE-safety killer.
    #   unknown : no distribution call (data_unavailable), OR `Detected in many` with no essential
    #             enrichment — we CANNOT assert the essentials are spared, so it must not read as
    #             reassurance (the prior `absent` overloading of a data gap).
    #   absent  : a MEASURED narrow distribution (detected in some/single/not-detected) with no essential
    #             expression — a genuine measured-negative.
    dist_norm = (dist or "").strip().lower()
    detected_in_all = dist_norm == "detected in all"
    if essential or detected_in_all:
        essential_flag = "present"
    elif breadth == "data_unavailable" or dist_norm == "detected in many":
        essential_flag = "unknown"
    else:
        essential_flag = "absent"

    flags = []
    if essential:
        flags.append("essential_tissue")
    elif essential_flag == "present":  # present via broad `Detected in all` detection
        flags.append("essential_from_broad_detection")
    if gi:
        flags.append("gi_tract")
    if breadth == "broad_normal_expression":
        flags.append("broad")

    return {
        "normal_tissue_breadth_class": breadth,
        # Scalar categorical the essential-tissue rule matches with `equals` (the rules
        # engine is categorical-only — no list-membership predicate; so the list→scalar
        # reduction happens here at emit time). present | unknown | absent (see trichotomy above).
        "essential_tissue_flag": essential_flag,
        "hpa_tissue_distribution": dist,
        "hpa_tissue_specificity": spec,
        "n_essential_tissues_with_expression": len(essential),
        "essential_tissues_flagged": essential,
        "n_specific_tissues": len(specific),
        "specific_tissues": specific,
        "safety_tissue_flags": flags,
        "method_version": METHOD_VERSION,
    }


def load_and_classify(gene: str, hpa_path=None) -> dict:
    """Full pipeline: look up the gene's HPA row → normal-tissue-liability summary."""
    df = _read_hpa(hpa_path)
    hit = df[df[HPA_GENE_COL].astype(str).str.upper() == gene.strip().upper()]
    if not len(hit):
        return compute_summary(gene, None)
    return compute_summary(gene, hit.iloc[0].to_dict())


def _load_takeda_style(target_contracts_dir):
    """Load the Takeda mplstyle + palette (idempotent). Returns the palette module."""
    import sys as _sys
    from pathlib import Path as _Path

    import matplotlib.pyplot as plt

    style_path = _Path(target_contracts_dir) / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    _sys.path.insert(0, str(_Path(target_contracts_dir) / "plot_styles"))
    import takeda_palette  # type: ignore

    return takeda_palette


# Breadth is the PRIMARY categorical (the specific-tissue list is ~51%-covered and often sparse —
# a lone bar misrepresents a broadly-expressed gene). Render it as an ordered risk LADDER (more
# normal tissues = more on-target-off-tumor liability), with the target's cell marked, and hang the
# enriched-tissue detail + safety flags off it.
_BREADTH_LADDER = [
    ("not_detected_in_normal", "Not detected"),
    ("restricted_normal_expression", "Single tissue"),
    ("moderate_normal_expression", "Some tissues"),
    ("broad_normal_expression", "Many / all tissues"),
]
# breadth -> fallback badge signal (a safety axis: broad normal footprint argues AGAINST a clean
# therapeutic window; a narrow/absent footprint supports one). An essential-organ hit escalates to
# killer below.
_BREADTH_SIGNAL = {
    "broad_normal_expression": "opposing",
    "moderate_normal_expression": "neutral",
    "restricted_normal_expression": "supportive",
    "not_detected_in_normal": "supportive",
    "data_unavailable": "insufficient",
}


def emit_normal_tissue_bar(summary: dict, target_symbol: str, out_dir, target_contracts_dir, *, status=None):
    """Emit the normal-tissue-liability figure in the shared grammar.

    Hero = a 4-step breadth LADDER (Not detected → Single → Some → Many/all) with the target's IHC
    breadth cell highlighted; below it, the tissue-ENRICHED bars (essential = red, GI = amber, other
    = navy) when the specific-intensity list is populated. Reserved verdict BADGE (top-right) + a
    plain-language takeaway. Summary-driven (no reload).

    status: OPT-IN status dict (takeda_palette.status_for_card over the run's fired_rules); when None,
            a fallback signal is derived from the breadth class (+ essential-organ escalation)."""
    import matplotlib

    matplotlib.use("Agg")
    from pathlib import Path as _Path

    from matplotlib.patches import FancyBboxPatch

    pal = _load_takeda_style(target_contracts_dir)
    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "figure_normal_tissue_expression_heatmap.svg"

    breadth = summary.get("normal_tissue_breadth_class", "data_unavailable")
    specific = summary.get("specific_tissues") or []
    essential_set = set(summary.get("essential_tissues_flagged") or [])
    gi_set = {"intestine", "stomach"}
    flags = summary.get("safety_tissue_flags") or []

    rows = sorted(
        [(t.get("tissue"), t.get("intensity")) for t in specific if t.get("intensity") is not None],
        key=lambda r: r[1],
        reverse=True,
    )

    # takeaway (verdict itself is a REPORT-layer badge, not on the figure); computed before the frame.
    take = None
    if breadth == "broad_normal_expression":
        organ = " incl. GI tract" if any(r[0] in gi_set for r in rows) else ""
        take = f"Broad normal footprint — {target_symbol} spans many normal tissues{organ}."
    elif breadth == "not_detected_in_normal":
        take = f"{target_symbol} protein is not detected in normal tissue — a favorable window."
    elif essential_set:
        take = (
            f"{target_symbol} is expressed in essential organ(s): "
            f"{', '.join(sorted(essential_set))} — a strict-modality safety veto."
        )

    # multi-panel → frame makes only the styled fig (make_ax=False) + owns title/provenance/takeaway
    # + save on exit; the emitter adds the 2-row gridspec (ladder over enriched-tissue bars).
    with pal.figure_frame(
        target_symbol,
        None,
        "normal-tissue protein footprint",
        out_path=out_path,
        kind="tall",
        make_ax=False,
        provenance="HPA v25  ·  IHC (pathologist-scored)",
        takeaway=take,
    ) as F:
        fig = F.fig
        gs = fig.add_gridspec(2, 1, height_ratios=[1.0, max(1.4, 0.4 * len(rows) + 0.6)], hspace=0.6)
        ax_l = fig.add_subplot(gs[0])
        ax_b = fig.add_subplot(gs[1])

        # ---- breadth ladder (sequential DATA ramp: more tissues = darker; target cell bold-bordered) ----
        active_idx = next((i for i, (c, _) in enumerate(_BREADTH_LADDER) if c == breadth), None)
        for i, (cls, lab) in enumerate(_BREADTH_LADDER):
            on = active_idx is not None and i <= active_idx
            is_target = i == active_idx
            base = ["#E7ECEF", "#CBD8DE", "#9DB6C2", "#5B7F99"][i]
            rect = FancyBboxPatch(
                (i, 0),
                0.92,
                1,
                boxstyle="round,pad=0.02,rounding_size=0.06",
                facecolor=base if on else "#F2F4F6",
                edgecolor=("#33383D" if is_target else "#C9CED3"),
                linewidth=1.8 if is_target else 0.6,
                transform=ax_l.transData,
            )
            ax_l.add_patch(rect)
            ax_l.text(
                i + 0.46,
                0.5,
                lab,
                ha="center",
                va="center",
                fontsize=7.5,
                color=("#FFFFFF" if (on and i >= 3) else "#33383D"),
                weight="bold" if is_target else "normal",
            )
        ax_l.set_xlim(-0.1, len(_BREADTH_LADDER))
        ax_l.set_ylim(-0.15, 1.15)
        ax_l.axis("off")
        ax_l.text(0, 1.35, "IHC breadth across normal tissues (HPA) →", fontsize=7.5, color="#5A626A")
        # note 3: show the DATA that decides the highlighted category — HPA's pathologist IHC
        # distribution call (+ specificity), not a computed threshold.
        dist = summary.get("hpa_tissue_distribution")
        spec = summary.get("hpa_tissue_specificity")
        n_spec = summary.get("n_specific_tissues")
        decided = f"decided by HPA IHC call: “{dist}”" if dist else "HPA IHC call unavailable"
        if spec:
            decided += f"   ·   specificity: {spec}"
        if n_spec is not None:
            decided += f"   ·   {n_spec} tissue-enriched"
        ax_l.text(0, -0.42, decided, fontsize=7, color="#8A8F94", va="top", clip_on=False)

        # ---- enriched-tissue bars ----
        if rows:
            labels = [r[0] for r in rows]
            vals = [r[1] / 1e6 for r in rows]  # ×10⁶ → drop 1e7 offset

            def _col(lab):
                if lab in essential_set:
                    return pal.REFLINE_KILLER["color"]  # essential organ = red
                if lab in gi_set:
                    return "#E08214"  # GI tract = amber
                return pal.TUMOR_LINE

            ypos = list(range(len(labels)))
            ax_b.barh(ypos, vals, color=[_col(l) for l in labels], height=0.62, edgecolor="#FFFFFF", linewidth=0.6)
            ax_b.set_yticks(ypos)
            ax_b.set_yticklabels([l.title() for l in labels], fontsize=8)
            ax_b.invert_yaxis()
            # note 4: HPA gives a RELATIVE tissue-enrichment score here (no absolute High/Med/Low per
            # tissue). Make that explicit + carry HPA's own qualitative call (specificity) as the level.
            pal.axis_label(ax_b, "x", "Tissue-enrichment", "HPA relative IHC score (×10⁶) — no absolute H/M/L")
            spec = summary.get("hpa_tissue_specificity")
            if spec:
                ax_b.annotate(
                    f"HPA specificity: {spec}",
                    xy=(0.99, 1.02),
                    xycoords="axes fraction",
                    ha="right",
                    va="bottom",
                    fontsize=7,
                    color=pal.INK_MUTED,
                    clip_on=False,
                )
            ax_b.grid(axis="x", alpha=0.25, linewidth=0.4)
            ax_b.grid(axis="y", visible=False)
            if len(rows) == 1:
                ax_b.set_title(
                    "only 1 tissue is IHC-enriched — breadth (above) carries the signal",
                    fontsize=7,
                    color="#8A8F94",
                    style="italic",
                    loc="left",
                    pad=3,
                )
            from matplotlib.patches import Patch

            leg = []
            if any(l in essential_set for l in labels):
                leg.append(Patch(facecolor=pal.REFLINE_KILLER["color"], label="essential organ"))
            if any(l in gi_set for l in labels):
                leg.append(Patch(facecolor="#E08214", label="GI tract"))
            if leg:
                ax_b.legend(handles=leg, loc="lower right", fontsize=7, frameon=False)
        else:
            ax_b.axis("off")
            note = {
                "broad_normal_expression": "broadly expressed; no single tissue is IHC-enriched",
                "not_detected_in_normal": "not detected in normal tissue — favorable window",
            }.get(breadth, f"breadth: {breadth.replace('_', ' ')}")
            ax_b.text(0.5, 0.6, note, ha="center", va="center", fontsize=9, color="#5A626A")
    return out_path


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="HPA normal-tissue liability for a target.")
    ap.add_argument("--gene", required=True)
    ap.add_argument("--hpa-path", default=None)
    args = ap.parse_args(argv)
    print(json.dumps(load_and_classify(args.gene, hpa_path=args.hpa_path), indent=2, default=str))


if __name__ == "__main__":
    _main()
