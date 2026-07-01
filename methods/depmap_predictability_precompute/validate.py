"""depmap_predictability_precompute.validate — anchor-target parity vs DepMap.

Compares our v2 predictability parquet to DepMap's published per-gene
predictability scores (portal artifact `PredictionsCellContextCRISPR.csv` or
`EnsembleCellContextCRISPR.csv`, downloaded manually from
https://depmap.org/portal/data_page — anti-bot gate blocks automated fetch).

Acceptance criteria (from plan file § Phase B validation):
  - median |r_ours − r_depmap| across anchors ≤ 0.10
  - dominant-feature-class agreement on ≥ 7/10 anchors
  - no anchor with delta > 0.20 (individual outlier fail)

Emits a Markdown validation report + a JSON summary. If DepMap CSV is
unavailable, still emits a "reference-not-available" report with our per-gene
scores + top features so the anchor readout is auditable.

Usage:
  # With reference file
  python -m methods.depmap_predictability_precompute.validate \\
      --ours /tmp/e5_v2_smoke/predictability_per_gene.parquet \\
      --depmap-csv ~/dev/framework-runs/e5-validation/PredictionsCellContextCRISPR.csv \\
      --out ~/dev/framework-runs/e5-validation-2026-07-01/

  # Without reference (report our scores only)
  python -m methods.depmap_predictability_precompute.validate \\
      --ours /tmp/e5_v2_smoke/predictability_per_gene.parquet \\
      --out ~/dev/framework-runs/e5-validation-2026-07-01/
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click

# Anchor set from plan file § Phase B
ANCHOR_TARGETS = ["KRAS", "BRAF", "EGFR", "PIK3CA", "TP53",
                    "MYC", "MDM2", "MCL1", "CDK4", "WRN"]

ANCHOR_EXPECTED_CLASS = {
    # Approximate expectation from prior biology / DepMap qualitative reports.
    # These aren't hard truth — they're used as sanity-check hints in the report,
    # not as pass/fail gates.
    "KRAS":   "own_omics_driven (via own_mut_hotspot)",
    "BRAF":   "own_omics_driven (via own_mut_hotspot / lineage_Skin)",
    "EGFR":   "own_omics_driven (via own_mut_hotspot or own_expression)",
    "PIK3CA": "context_or_driver_dependent (co-driver signals; PIK3CA mutation partial)",
    "TP53":   "weakly_predictable or unpredictable (LOF heterogeneity)",
    "MYC":    "own_omics_driven (via own_expression / own_copy_number)",
    "MDM2":   "own_omics_driven (via TP53 status → own_expression amplification)",
    "MCL1":   "context_or_driver_dependent (lineage_hematopoietic co-signal)",
    "CDK4":   "own_omics_driven (via own_copy_number amplification)",
    "WRN":    "context_or_driver_dependent (MSI lineage-conditional biomarker)",
}


def _read_ours(parquet_path: Path) -> "pandas.DataFrame":
    import pyarrow.parquet as pq
    return pq.read_table(parquet_path).to_pandas()


def _read_depmap(csv_path: Path) -> Optional["pandas.DataFrame"]:
    """Read DepMap's per-gene predictability CSV. Expected columns include
    `gene`, `pearson`, `best_model_pearson`, `top_feature_type`. Schema may
    drift between releases; we accept plausible aliases.
    """
    import pandas as pd
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    # Normalize column names
    lower = {c.lower(): c for c in df.columns}
    def _pick(*names):
        for n in names:
            if n in lower:
                return lower[n]
        return None
    gene_col = _pick("gene", "hugosymbol", "gene_symbol", "entity")
    pearson_col = _pick("pearson", "best_pearson", "pearson_best", "correlation")
    top_col = _pick("top_feature", "best_feature", "feature_top")
    if not (gene_col and pearson_col):
        raise click.UsageError(
            f"DepMap CSV at {csv_path} lacks expected columns (gene + pearson). "
            f"Got: {list(df.columns)}"
        )
    df = df.rename(columns={gene_col: "gene", pearson_col: "pearson_depmap"})
    if top_col:
        df = df.rename(columns={top_col: "top_feature_depmap"})
    return df[[c for c in ["gene", "pearson_depmap", "top_feature_depmap"] if c in df.columns]]


def build_anchor_table(ours_df, depmap_df, anchors=ANCHOR_TARGETS):
    """Assemble per-anchor comparison rows."""
    rows = []
    for gene in anchors:
        row = {"gene": gene}
        our_row = ours_df[ours_df["gene_symbol"] == gene]
        if len(our_row) == 0:
            row["ours_r"] = None
            row["ours_r2"] = None
            row["ours_r2_ci"] = None
            row["ours_class"] = "MISSING"
            row["ours_top_feature"] = None
            row["ours_top_class"] = None
            row["ours_xgb_r"] = None
            row["ours_model_agreement"] = None
        else:
            r = our_row.iloc[0]
            row["ours_r"] = float(r["pearson_r_rf"]) if r["pearson_r_rf"] is not None else None
            row["ours_r2"] = float(r["pearson_r_squared_rf"]) if r["pearson_r_squared_rf"] is not None else None
            ci_lo = r.get("pearson_r_squared_rf_ci_lo")
            ci_hi = r.get("pearson_r_squared_rf_ci_hi")
            row["ours_r2_ci"] = (float(ci_lo), float(ci_hi)) if ci_lo is not None else None
            row["ours_class"] = r.get("predictability_class")
            top = r.get("top_features_rf_shap") or []
            row["ours_top_feature"] = top[0]["feature"] if len(top) > 0 else None
            row["ours_top_class"] = top[0]["feature_class"] if len(top) > 0 else None
            row["ours_xgb_r"] = float(r.get("pearson_r_xgb", 0.0)) if r.get("pearson_r_xgb") is not None else None
            row["ours_model_agreement"] = r.get("model_agreement")
        # DepMap side
        if depmap_df is not None:
            dep_row = depmap_df[depmap_df["gene"] == gene]
            if len(dep_row) > 0:
                dep = dep_row.iloc[0]
                row["depmap_r"] = float(dep["pearson_depmap"])
                row["depmap_top_feature"] = dep.get("top_feature_depmap")
            else:
                row["depmap_r"] = None
                row["depmap_top_feature"] = None
        else:
            row["depmap_r"] = None
            row["depmap_top_feature"] = None
        # Delta
        if row["ours_r"] is not None and row["depmap_r"] is not None:
            row["delta_r"] = row["ours_r"] - row["depmap_r"]
            row["abs_delta_r"] = abs(row["delta_r"])
        else:
            row["delta_r"] = None
            row["abs_delta_r"] = None
        row["expected_class_hint"] = ANCHOR_EXPECTED_CLASS.get(gene, "")
        rows.append(row)
    return rows


def _fmt_num(v, prec=2):
    if v is None:
        return "—"
    return f"{v:.{prec}f}"


def build_report_md(rows: list, has_depmap: bool) -> str:
    lines = [
        "# E5 v2 Anchor-Target Validation Report",
        "",
        f"*Generated: {datetime.now(timezone.utc).isoformat()}*",
        "",
    ]
    if has_depmap:
        deltas = [r["abs_delta_r"] for r in rows if r["abs_delta_r"] is not None]
        if deltas:
            import statistics
            med = statistics.median(deltas)
            max_delta = max(deltas)
            n_over_02 = sum(1 for d in deltas if d > 0.20)
            lines.extend([
                "## Summary vs DepMap",
                "",
                f"- Anchors compared: **{len(deltas)}/{len(rows)}**",
                f"- Median |r_ours − r_depmap|: **{med:.3f}** "
                    f"(pass criterion: ≤ 0.10 → {'✓ PASS' if med <= 0.10 else '✗ FAIL'})",
                f"- Max |r_ours − r_depmap|: **{max_delta:.3f}** "
                    f"(pass criterion: no anchor > 0.20 → "
                    f"{'✓ PASS' if n_over_02 == 0 else f'✗ FAIL ({n_over_02} outliers)'})",
                "",
            ])
    else:
        lines.extend([
            "## Reference not available",
            "",
            "DepMap portal CSV (`PredictionsCellContextCRISPR.csv` or "
            "`EnsembleCellContextCRISPR.csv`) was not provided. This report "
            "shows our per-anchor scores only; parity check deferred until the "
            "reference CSV is downloaded from https://depmap.org/portal/data_page.",
            "",
        ])
    lines.extend([
        "## Per-anchor results",
        "",
        "| Gene | ours r (RF) | ours r² [CI] | ours class | ours top feature | ours XGB r | agreement | depmap r | Δr | Expected hint |",
        "|------|-------------|--------------|------------|------------------|-----------|-----------|----------|------|---------------|",
    ])
    for r in rows:
        ci_txt = "—"
        if r["ours_r2_ci"]:
            ci_txt = f"{r['ours_r2']:.2f} [{r['ours_r2_ci'][0]:.2f}, {r['ours_r2_ci'][1]:.2f}]"
        lines.append(
            f"| {r['gene']} | {_fmt_num(r['ours_r'])} | {ci_txt} | "
            f"{r['ours_class'] or '—'} | {r['ours_top_feature'] or '—'} | "
            f"{_fmt_num(r['ours_xgb_r'])} | {r['ours_model_agreement'] or '—'} | "
            f"{_fmt_num(r['depmap_r'])} | {_fmt_num(r['abs_delta_r'], 3)} | "
            f"{r['expected_class_hint']} |"
        )
    lines.extend([
        "",
        "## Interpretation notes",
        "",
        "**Metric alignment.** DepMap reports Pearson r (their portal DB column "
        "literally named `pearson`). We report both r and r². The parity check "
        "is on r; r² and its bootstrap CI are our EXTENSIONS beyond DepMap.",
        "",
        "**Feature-set gaps** (may explain systematic negative deltas vs DepMap):",
        "- Fusion status matrix — not ingested",
        "- RPPA proteomics + RRBS methylation + metabolomics + ssGSEA — not ingested",
        "- OncoKB per-VARIANT annotations — we use per-GENE role list (coarser)",
        "- DepMap's dynamic MatchRelated related-entity lookup — we use static "
            "genome-wide cross-gene features (superset but noisier)",
        "",
        "**Passing criteria** (from plan file):",
        "- Median |Δr| ≤ 0.10 across anchors",
        "- Dominant-feature-class agreement on ≥ 7/10 anchors",
        "- No anchor with |Δr| > 0.20",
        "",
    ])
    return "\n".join(lines)


@click.command()
@click.option("--ours", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to our v2 predictability parquet")
@click.option("--depmap-csv", default=None, type=click.Path(path_type=Path),
              help="Optional path to DepMap portal CSV. If absent, report ours only.")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Output directory for report.md + summary.json")
@click.option("--anchors", default=",".join(ANCHOR_TARGETS), show_default=True,
              help="Comma-separated anchor gene symbols")
def main(ours, depmap_csv, out, anchors):
    out.mkdir(parents=True, exist_ok=True)
    anchor_list = [g.strip() for g in anchors.split(",") if g.strip()]
    ours_df = _read_ours(ours)
    depmap_df = _read_depmap(depmap_csv) if depmap_csv else None
    rows = build_anchor_table(ours_df, depmap_df, anchors=anchor_list)
    report = build_report_md(rows, has_depmap=depmap_df is not None)
    (out / "report.md").write_text(report)
    (out / "summary.json").write_text(json.dumps(rows, indent=2, default=str))
    click.echo(f"Wrote {out / 'report.md'} + {out / 'summary.json'}", err=True)


if __name__ == "__main__":
    main()
