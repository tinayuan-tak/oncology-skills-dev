#!/usr/bin/env python3
"""arm_loss_sl_scan CLI — SL -> arm-loss -> indication discovery scan.

FIND-MODE (not a per-target reader / not a verdict input). Nominates (target, indication)
candidates where a target's curated synthetic-lethal partner sits on a chromosome arm that is
RECURRENTLY LOST in the indication -- the passenger-deletion SL paradigm. See scan.py for the
statistics + the two-product discovery/confirmation division of labor.

Inputs (all catalog manifests; UNION emitted as input_manifest_ids for eval-ledger federation):
  synlethdb-sl-partners-per-gene-v1        SL pairs (top_partners struct: per-pair evidence_tier)
  pancan-arm-cnv-per-sample-v1             per-(sample, arm) loss/gain calls -> DISCOVERY signal
  pancan-genomic-two-hit-per-gene-v1       per-(gene, patient, cancer_type) cn_class -> CONFIRMATION
                                           + patient->indication universe (cancer_type baked in)
  gdc-pancanatlas-cnv-2018                 GISTIC meta (Gene Symbol, Cytoband) -> gene->arm map
                                           (same arm_of() as the arm-CNV product => label-consistent)

Usage:
    python -m methods.arm_loss_sl_scan.cli --target KRAS --out /tmp/kras_arm_loss_sl.parquet
    python -m methods.arm_loss_sl_scan.cli --all-targets --out /tmp/all_arm_loss_sl.parquet \\
        --min-loss-freq 0.25 --fdr-alpha 0.05 --experimental-only
"""
from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

import click

from methods.arm_loss_sl_scan.scan import METHOD_VERSION, SCAN_COLUMNS, sl_arm_scan
from methods.pancan_arm_cnv.read import _patient_of, build_arm_indication_freq, gene_arm_map

DEFAULT_AWS_PROFILE = "cbg"

# Federation key: the manifests this scan reads. Emitted verbatim into the sidecar so the
# target-contracts eval-ledger row_from_scan reader can UNION it into the portfolio graph.
INPUT_MANIFEST_IDS = [
    "synlethdb-sl-partners-per-gene-v1",
    "pancan-arm-cnv-per-sample-v1",
    "pancan-genomic-two-hit-per-gene-v1",
    "gdc-pancanatlas-cnv-2018",
]

# GISTIC meta source (same object the arm-CNV product derives from -> label-consistent arms).
_GISTIC_BUCKET = "onc-compbio"
_GISTIC_KEY = ("data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27/"
               "all_thresholded.by_genes_whitelisted.tsv")
_LOSS_CN_CLASSES = ("homdel", "loss")
_CACHE_DIR = Path.home() / ".cache" / "arm-loss-sl-scan"


def _ensure_profile(profile: str):
    os.environ.setdefault("AWS_PROFILE", profile)


def _bkey(manifest_id: str):
    """(bucket, key) from the data-catalog manifest -- single source of truth for S3 location."""
    from methods.catalog_query.read import bucket_key_for
    return bucket_key_for(manifest_id)


def _load_sl_pairs(target: Optional[str], experimental_only: bool) -> "pd.DataFrame":
    """Explode synlethdb top_partners -> [target, partner, evidence_tier, has_experimental].

    Scans the top_partners struct (<=20 partners/gene, experimental-first) so per-pair evidence
    is faithful and the downstream two-hit read stays bounded. sl_partner_symbols (the full,
    possibly huge, per-pair-tier-less list) is deliberately NOT used here."""
    import pandas as pd
    bucket, key = _bkey("synlethdb-sl-partners-per-gene-v1")
    import boto3
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    df = pd.read_parquet(BytesIO(obj["Body"].read()))
    if target is not None:
        df = df[df["gene_symbol"].astype(str).str.upper() == target.strip().upper()]
    rows = []
    for _, r in df.iterrows():
        tgt = str(r["gene_symbol"]).strip().upper()
        for p in (list(r["top_partners"]) if r["top_partners"] is not None else []):
            pd_ = dict(p)
            tier = pd_.get("evidence_tier")
            is_exp = str(tier).lower() == "experimental"
            if experimental_only and not is_exp:
                continue
            partner = pd_.get("partner")
            if not partner:
                continue
            rows.append({"target": tgt, "partner": str(partner).strip().upper(),
                         "evidence_tier": tier, "has_experimental": is_exp})
    return pd.DataFrame(rows, columns=["target", "partner", "evidence_tier", "has_experimental"]
                        ).drop_duplicates(["target", "partner"]).reset_index(drop=True)


def _load_gene_arm_map() -> dict:
    """gene->arm from GISTIC meta (Gene Symbol, Cytoband). One-time full-object read (the source
    is a wide row-oriented TSV, not column-projectable) -> cached as a tiny parquet thereafter."""
    import pandas as pd
    cache = _CACHE_DIR / "gene_arm_map.parquet"
    if cache.exists():
        m = pd.read_parquet(cache)
        return dict(zip(m["gene_symbol"], m["chromosome_arm"]))
    click.echo("[arm_loss_sl_scan] downloading GISTIC meta for gene->arm (one-time, cached)...",
               err=True)
    import boto3
    obj = boto3.client("s3").get_object(Bucket=_GISTIC_BUCKET, Key=_GISTIC_KEY)
    meta = pd.read_csv(BytesIO(obj["Body"].read()), sep="\t", usecols=["Gene Symbol", "Cytoband"])
    gmap = gene_arm_map(meta)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"gene_symbol": list(gmap), "chromosome_arm": list(gmap.values())}
                 ).to_parquet(cache, index=False)
    return gmap


def _load_arm_calls() -> "pd.DataFrame":
    import pandas as pd
    bucket, key = _bkey("pancan-arm-cnv-per-sample-v1")
    import boto3
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return pd.read_parquet(BytesIO(obj["Body"].read()),
                           columns=["sample_barcode", "chromosome_arm", "arm_call"])


def _load_twohit_universe_and_loss(partners: set) -> "tuple":
    """Read the two-hit product ONCE, projecting only the needed columns.

      barcode_to_indication : {patient_barcode -> cancer_type}  (patient->indication universe)
      ind_patient_totals    : {cancer_type -> n distinct patients}  (confirmation denominators)
      twohit_loss_freq      : {(partner, cancer_type) -> gene-level loss frequency}

    NOTE the two-hit product stores only ALTERED (gene, patient) rows, so its patient universe =
    patients with >=1 alteration (~all TCGA patients); the tiny fraction of alteration-free
    patients slightly deflates denominators. Acceptable for a CONFIRMATION column (not the FDR
    test). cn_class in {homdel, loss} = the loss events."""
    import pyarrow.dataset as ds
    import pyarrow.compute as pc
    bucket, key = _bkey("pancan-genomic-two-hit-per-gene-v1")
    dataset = ds.dataset(f"{bucket}/{key}", filesystem=_arrow_fs(), format="parquet")

    # patient->indication universe (2-col projection over the whole product)
    uni = dataset.to_table(columns=["patient_barcode", "cancer_type"]).to_pandas().drop_duplicates()
    barcode_to_indication = dict(zip(uni["patient_barcode"], uni["cancer_type"]))
    ind_patient_totals = uni.groupby("cancer_type")["patient_barcode"].nunique().to_dict()

    # partner loss events (pushdown on gene_symbol + cn_class)
    twohit_loss_freq = {}
    if partners:
        filt = pc.field("gene_symbol").isin(list(partners)) & pc.field("cn_class").isin(list(_LOSS_CN_CLASSES))
        loss = dataset.to_table(columns=["gene_symbol", "patient_barcode", "cancer_type"],
                                filter=filt).to_pandas().drop_duplicates()
        for (g, ind), grp in loss.groupby(["gene_symbol", "cancer_type"]):
            denom = ind_patient_totals.get(ind, 0)
            if denom:
                twohit_loss_freq[(str(g).strip().upper(), ind)] = round(grp["patient_barcode"].nunique() / denom, 4)
    return barcode_to_indication, ind_patient_totals, twohit_loss_freq


def _arrow_fs():
    import pyarrow.fs as pafs
    return pafs.S3FileSystem()


def _pancan_baseline(arm_calls, barcode_to_indication) -> dict:
    """Pan-cancer per-arm loss frequency over the mapped-to-indication sample universe (so the
    baseline and the per-indication observed frequencies share the same denominator population)."""
    df = arm_calls.copy()
    df["indication"] = df["sample_barcode"].map(
        lambda b: barcode_to_indication.get(b) or barcode_to_indication.get(_patient_of(b)))
    df = df[df["indication"].notna()]
    out = {}
    for arm, g in df.groupby("chromosome_arm"):
        n = len(g)
        out[arm] = round((g["arm_call"] == -1).sum() / n, 6) if n else 0.0
    return out


@click.command()
@click.option("--target", default=None, help="Single target gene (scan its SL partners). Omit with --all-targets.")
@click.option("--all-targets", is_flag=True, help="Scan every gene in the SL product (full sweep; reads more of the two-hit product).")
@click.option("--out", required=True, type=click.Path(path_type=Path), help="Output parquet path.")
@click.option("--min-loss-freq", type=float, default=0.20, show_default=True, help="Actionability floor on observed arm-loss frequency.")
@click.option("--fdr-alpha", type=float, default=0.05, show_default=True, help="BH q-value cutoff.")
@click.option("--experimental-only", is_flag=True, help="Keep only experimentally-supported SL pairs.")
@click.option("--aws-profile", default=DEFAULT_AWS_PROFILE, show_default=True)
def main(target, all_targets, out, min_loss_freq, fdr_alpha, experimental_only, aws_profile):
    """Compose the SL -> arm-loss -> indication nomination scan and write parquet + a
    <out>.input_manifest_ids.json federation sidecar + a caveats sidecar."""
    import pandas as pd
    if not target and not all_targets:
        raise click.UsageError("provide --target GENE or --all-targets")
    _ensure_profile(aws_profile)

    click.echo(f"[arm_loss_sl_scan] loading SL pairs (target={target or 'ALL'}, "
               f"experimental_only={experimental_only})...", err=True)
    sl_pairs = _load_sl_pairs(target, experimental_only)
    if sl_pairs.empty:
        _write_empty(out, "no SL pairs for the requested scope")
        return
    partners = set(sl_pairs["partner"])
    click.echo(f"[arm_loss_sl_scan] {len(sl_pairs)} pairs, {len(partners)} distinct partners; "
               f"reading arm calls + two-hit + gene->arm...", err=True)

    gene_to_arm = _load_gene_arm_map()
    arm_calls = _load_arm_calls()
    barcode_to_indication, _totals, twohit_loss_freq = _load_twohit_universe_and_loss(partners)

    arm_ind_freq = build_arm_indication_freq(arm_calls, barcode_to_indication)
    baseline = _pancan_baseline(arm_calls, barcode_to_indication)

    click.echo("[arm_loss_sl_scan] scanning...", err=True)
    hits = sl_arm_scan(sl_pairs, arm_ind_freq, baseline, gene_to_arm,
                       twohit_loss_freq=twohit_loss_freq,
                       min_loss_freq=min_loss_freq, fdr_alpha=fdr_alpha)

    out.parent.mkdir(parents=True, exist_ok=True)
    hits.to_parquet(out, index=False)
    _write_sidecars(out, n_hits=len(hits), min_loss_freq=min_loss_freq, fdr_alpha=fdr_alpha)
    click.echo(f"[arm_loss_sl_scan] wrote {len(hits)} hits -> {out}", err=True)


def _write_empty(out: Path, reason: str):
    import pandas as pd
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=SCAN_COLUMNS).to_parquet(out, index=False)
    _write_sidecars(out, n_hits=0, note=reason)
    click.echo(f"[arm_loss_sl_scan] {reason}: wrote 0-row scan -> {out}", err=True)


def _write_sidecars(out: Path, n_hits: int, note: str = "", **params):
    """input_manifest_ids federation sidecar (JSON) + a human caveats sidecar."""
    sidecar = out.with_suffix(".input_manifest_ids.json")
    payload = {
        "method": "arm_loss_sl_scan",
        "method_version": METHOD_VERSION,
        "input_manifest_ids": INPUT_MANIFEST_IDS,
        "n_hits": n_hits,
        "parameters": params,
    }
    if note:
        payload["note"] = note
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True))
    caveats = [
        "DISCOVERY nomination scan, NOT a verdict input -- never feeds a resolver. It ranks "
        "(target, indication) candidates by arm-loss enrichment of an SL partner's arm.",
        "arm_loss_freq (DISCOVERY) is arm-level and inferential: a recurrently-lost arm co-deletes "
        "the partner as a passenger. partner_twohit_loss_freq (CONFIRMATION) is the gene-level "
        "co-loss of the specific partner; coloss_concordance='arm_only' flags an arm signal NOT "
        "corroborated at the partner-gene level (treat as weaker).",
        "Statistics: observed arm-loss freq tested one-sided vs the PAN-CANCER arm-loss baseline "
        "(binomial), Benjamini-Hochberg across the full tested set. A hit clears BOTH q<=fdr_alpha "
        "AND the min-loss-freq floor.",
        "Only the top_partners struct (<=20/gene, experimental-first) is scanned; deep-tail "
        "computational-only partners in sl_partner_symbols are not. The two-hit patient universe "
        "is altered-patients-only (~all TCGA), slightly deflating confirmation denominators.",
    ]
    out.with_suffix(".caveats.txt").write_text("\n\n".join(caveats))


if __name__ == "__main__":
    main()
