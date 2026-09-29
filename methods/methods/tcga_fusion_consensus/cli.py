#!/usr/bin/env python3
"""tcga_fusion_consensus CLI — build the pan-TCGA fusion consensus product.

Reads three ingested TCGA fusion callers, normalizes to sample-level TCGA
barcodes (TCGA-{tss}-{part}-{sample_num}, vial dropped), and emits two parquets:

  1. fusion_consensus_per_sample_gene.parquet
       One row per (sample_key, gene_symbol). Preserves every caller's
       partner-gene list + frame prediction so consumers pick their own
       consensus threshold (caller_count >= 1 / >= 2 / == 3).

  2. sample_coverage.parquet
       One row per (sample_key, caller). Which caller assayed which sample?
       Enables downstream `is_member=false` vs `null` distinction:
         - assayed_by_>=2_callers AND no fusion event -> false
         - assayed_by_1_caller only, no event         -> ambiguous, prefer null

Output schema (fusion_consensus_per_sample_gene):
  sample_key                str  TCGA-tss-part-sampleNum
  gene_symbol               str  gene involved (either 5' or 3')
  tissue                    str  TCGA disease code (LUAD/LUSC/...); majority-vote
                                 across callers, ties broken by TumorFusions
  caller_count              int  0..3 — number of callers reporting this pair
  callers_supporting        list<str>  subset of {tumorfusions, gao_2018, cbioportal}
  partners_tumorfusions     list<str>  distinct partner genes reported by tumorfusions
  partners_gao_2018         list<str>  same, for Gao 2018
  partners_cbioportal       list<str>  same, for cBioPortal
  frame_preds_tumorfusions  list<str>  distinct frame_pred values from tumorfusions
  frame_preds_gao_2018      list<str>  (Gao does not publish frame — always empty/null)
  frame_preds_cbioportal    list<str>  distinct frame_pred values from cBioPortal
  n_events_tumorfusions     int  count of raw event-rows from TumorFusions
  n_events_gao_2018         int  count of raw event-rows from Gao 2018
  n_events_cbioportal       int  count of raw event-rows from cBioPortal

Invocation:
  python -m methods.tcga_fusion_consensus.cli \\
      --tumorfusions-xlsx /path/to/nar-02671-data-e-2017-File007.xlsx \\
      --tumorfusions-samples-xlsx /path/to/nar-02671-data-e-2017-File006.xlsx \\
      --gao-2018-xlsx /path/to/gao-2018-driver-fusions-tableS1-mmc2.xlsx \\
      --cbioportal-dir /path/to/cbioportal/tcga-pancan-atlas-2018/ \\
      --out /path/to/output-dir/
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import click
import pandas as pd

from methods import cell_absence as ca
from methods.tcga_fusion_consensus.read import (
    cbioportal_assayed_samples,
    gao_2018_assayed_samples,
    load_cbioportal_all,
    load_gao_2018,
    load_tumorfusions,
    tumorfusions_assayed_samples,
)

METHOD_VERSION = "0.1.0"


def _majority_tissue(tissues: list) -> str | None:
    """Majority-vote a tissue code; ties broken by insertion order (tumorfusions
    first because it's the most restrictive/highest-precision caller)."""
    non_null = [t for t in tissues if t]
    if not non_null:
        return None
    return Counter(non_null).most_common(1)[0][0]


def _distinct_non_null(vs) -> list:
    """Ordered, distinct, non-null values (for partners / frame_preds lists).

    The `isinstance(v, float)` term the old guard needed was carrying real weight: these values come
    from a groupby-agg `list` over partner_gene / frame_pred, whose missing cell is `None` on pandas 2
    (object dtype) but float `nan` on pandas 3 (the `str` dtype's sentinel), so BOTH terms had to be
    present and the guard was version-dependent by construction. ca.is_missing covers both spellings
    plus pd.NA/pd.NaT, so this list can no longer leak a stringified null into the emitted JSON
    regardless of which pandas the lockfile resolves.
    """
    seen: dict = {}
    for v in vs:
        if ca.is_missing(v):
            continue
        if v not in seen:
            seen[v] = None
    return list(seen)


def build_consensus(events: pd.DataFrame) -> pd.DataFrame:
    """Aggregate long-form per-caller events to per-(sample_key, gene_symbol) rows."""
    # Per-caller sub-aggregations, then merged.
    agg = (
        events.groupby(["sample_key", "gene_symbol", "caller"], dropna=False)
        .agg(
            partners=("partner_gene", list),
            frames=("frame_pred", list),
            tissues=("tissue", list),
            n_events=("event_id", "count"),
        )
        .reset_index()
    )

    # Pivot to per-(sample_key, gene) with per-caller columns.
    def _pivot(caller: str) -> pd.DataFrame:
        sub = agg[agg["caller"] == caller].copy()
        sub[f"partners_{caller}"] = sub["partners"].map(_distinct_non_null)
        sub[f"frame_preds_{caller}"] = sub["frames"].map(_distinct_non_null)
        sub = sub.rename(columns={"n_events": f"n_events_{caller}", "tissues": f"_tissues_{caller}"})
        return sub[
            [
                "sample_key",
                "gene_symbol",
                f"partners_{caller}",
                f"frame_preds_{caller}",
                f"n_events_{caller}",
                f"_tissues_{caller}",
            ]
        ]

    tf = _pivot("tumorfusions")
    gao = _pivot("gao_2018")
    cb = _pivot("cbioportal")
    m = tf.merge(gao, on=["sample_key", "gene_symbol"], how="outer").merge(
        cb, on=["sample_key", "gene_symbol"], how="outer"
    )
    # Fill n_events NaN with 0; empty lists for absent partners/frames.
    for c in ["tumorfusions", "gao_2018", "cbioportal"]:
        m[f"n_events_{c}"] = m[f"n_events_{c}"].fillna(0).astype(int)
        m[f"partners_{c}"] = m[f"partners_{c}"].apply(lambda v: v if isinstance(v, list) else [])
        m[f"frame_preds_{c}"] = m[f"frame_preds_{c}"].apply(lambda v: v if isinstance(v, list) else [])

    # Consensus columns.
    def _support(row) -> list:
        s = []
        if row["n_events_tumorfusions"] > 0:
            s.append("tumorfusions")
        if row["n_events_gao_2018"] > 0:
            s.append("gao_2018")
        if row["n_events_cbioportal"] > 0:
            s.append("cbioportal")
        return s

    m["callers_supporting"] = m.apply(_support, axis=1)
    m["caller_count"] = m["callers_supporting"].map(len)

    # Tissue: majority across callers that reported this (sample, gene).
    def _tissue_row(row) -> str | None:
        vs = []
        for c in ["tumorfusions", "gao_2018", "cbioportal"]:
            v = row.get(f"_tissues_{c}")
            if isinstance(v, list):
                vs.extend([x for x in v if x])
        return _majority_tissue(vs)

    m["tissue"] = m.apply(_tissue_row, axis=1)
    # Drop the private _tissues_* columns.
    m = m.drop(columns=[c for c in m.columns if c.startswith("_tissues_")])
    # Final column order.
    cols = [
        "sample_key",
        "gene_symbol",
        "tissue",
        "caller_count",
        "callers_supporting",
        "partners_tumorfusions",
        "partners_gao_2018",
        "partners_cbioportal",
        "frame_preds_tumorfusions",
        "frame_preds_gao_2018",
        "frame_preds_cbioportal",
        "n_events_tumorfusions",
        "n_events_gao_2018",
        "n_events_cbioportal",
    ]
    return m[cols].sort_values(["sample_key", "gene_symbol"]).reset_index(drop=True)


@click.command()
@click.option("--tumorfusions-xlsx", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--tumorfusions-samples-xlsx",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="File006 sample-manifest for the assayed-samples denominator.",
)
@click.option("--gao-2018-xlsx", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--cbioportal-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Local root under which each study is a subdir with structural_variants.jsonl.gz + samples.jsonl.gz.",
)
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--tissue-filter",
    default=None,
    help="Optional comma-separated TCGA disease codes (e.g. 'LUAD,LUSC') to subset. "
    "If omitted, all 33 pan-TCGA tissues are emitted.",
)
def main(
    tumorfusions_xlsx: Path,
    tumorfusions_samples_xlsx: Path,
    gao_2018_xlsx: Path,
    cbioportal_dir: Path,
    out: Path,
    tissue_filter: str | None,
) -> int:
    out.mkdir(parents=True, exist_ok=True)
    click.echo(f"=== tcga_fusion_consensus v{METHOD_VERSION} ===")
    filt = [t.strip() for t in tissue_filter.split(",")] if tissue_filter else None

    click.echo("  loading TumorFusions events…")
    tf_events = load_tumorfusions(tumorfusions_xlsx)
    click.echo(f"    {len(tf_events):,} long-form rows across {tf_events['sample_key'].nunique()} samples")
    click.echo("  loading Gao 2018 events…")
    gao_events = load_gao_2018(gao_2018_xlsx)
    click.echo(f"    {len(gao_events):,} long-form rows across {gao_events['sample_key'].nunique()} samples")
    click.echo("  loading cBioPortal PanCancer Atlas events (32 studies)…")
    cb_events = load_cbioportal_all(cbioportal_dir)
    click.echo(f"    {len(cb_events):,} long-form rows across {cb_events['sample_key'].nunique()} samples")

    events = pd.concat([tf_events, gao_events, cb_events], ignore_index=True)
    if filt:
        events = events[events["tissue"].isin(filt)]
        click.echo(f"  tissue-filtered to {filt}: {len(events):,} events remaining")

    click.echo("  building consensus (per-(sample_key, gene_symbol))…")
    consensus = build_consensus(events)
    click.echo(f"    {len(consensus):,} (sample, gene) rows")
    click.echo(f"    caller_count distribution: {consensus['caller_count'].value_counts().to_dict()}")

    click.echo("  building sample-coverage (denominator for false-vs-null)…")
    tf_samps = tumorfusions_assayed_samples(tumorfusions_samples_xlsx)
    gao_samps = gao_2018_assayed_samples(gao_2018_xlsx)
    cb_samps = cbioportal_assayed_samples(cbioportal_dir)
    coverage = pd.concat([tf_samps, gao_samps, cb_samps], ignore_index=True).drop_duplicates(
        subset=["sample_key", "caller"]
    )
    if filt:
        coverage = coverage[coverage["tissue"].isin(filt)]
    click.echo(
        f"    {len(coverage):,} (sample, caller) rows | "
        f"{coverage['sample_key'].nunique()} distinct samples across all callers"
    )

    consensus_path = out / "fusion_consensus_per_sample_gene.parquet"
    coverage_path = out / "sample_coverage.parquet"
    consensus.to_parquet(consensus_path, index=False)
    coverage.to_parquet(coverage_path, index=False)
    click.echo(f"  wrote {consensus_path} ({consensus_path.stat().st_size:,} bytes)")
    click.echo(f"  wrote {coverage_path}  ({coverage_path.stat().st_size:,} bytes)")

    # Emit a small provenance JSON alongside for the manifest scaffolder.
    prov = {
        "method": "tcga_fusion_consensus",
        "method_version": METHOD_VERSION,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "tumorfusions_xlsx": str(tumorfusions_xlsx),
            "tumorfusions_samples_xlsx": str(tumorfusions_samples_xlsx),
            "gao_2018_xlsx": str(gao_2018_xlsx),
            "cbioportal_dir": str(cbioportal_dir),
        },
        "tissue_filter": filt,
        "rows_consensus": len(consensus),
        "rows_coverage": len(coverage),
        "caller_count_distribution": {
            int(k): int(v) for k, v in consensus["caller_count"].value_counts().to_dict().items()
        },
    }
    (out / "_provenance.json").write_text(json.dumps(prov, indent=2))
    click.echo("  wrote _provenance.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
