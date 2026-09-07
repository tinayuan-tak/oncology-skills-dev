"""synleth_partner_lookup.derive — build the synlethdb-sl-partners-per-gene-v1 product.

Inverts the SynLethDB v3 SL pair-list (Human.SL.detailed.tsv, 37,943 edges) into a
per-gene partner index. SL is SYMMETRIC, so each edge (x, y) contributes y to x's
partner set AND x to y's partner set. Per gene we aggregate:
  - sl_partner_count            (distinct partners)
  - sl_partner_symbols          (sorted list)
  - best_evidence_tier          (strongest rel_source across this gene's edges)
  - n_experimental_partners     (partners with a non-computational rel_source)
  - has_experimental_partner    (bool — the load-bearing quality gate)
  - top_partners                (list of {partner, evidence_tier, pubmed_id, cell_line})

`rel_source` is the evidence-quality field. We rank it: an experimental screen
(CRISPR / GenomeRNAi / High/Low Throughput) is a far stronger "this pooled negative
is not trusted" signal than a Computational Prediction. The card/gate weight
experimental > computational (a computational-only partner suppresses more weakly).

Output: one parquet keyed by gene_symbol (+ entrez_id), written to the derived path;
the read side (read.py) does a point lookup. CC-BY-4.0 source (redistributable).

COVERAGE / provenance caveats (deliberate, disclosed):
  - SynLethDB Tier-2 (Human.computed.SL — deep-learning top-1% predictions) is EXCLUDED
    by design at the source-selection layer; this product indexes only the curated
    Human.SL.detailed edges. A gene with only Tier-2 predicted partners reads as
    no_curated_sl_partner here — a curated-set restriction, not "no SL biology".
  - evidence_tier() is a SUBSTRING-keyword heuristic over rel_source (see markers below).
    A new/renamed v3 rel_source that matches no marker falls to the LEAST-trusted "other"
    tier (see _TIER_RANK). test_evidence_tier_buckets pins the known v3 vocabulary so a
    silent drift into "other" is caught on the next source refresh.
"""

from __future__ import annotations

import io
from collections import defaultdict
from typing import Optional

METHOD_VERSION = "0.1.0"

S3_BUCKET = "onc-compbio"
SL_SOURCE_KEY = ("data-catalog/sources/synlethdb/v3-snapshot-2026-06-30/"
                 "Human.SL.detailed.tsv")
DERIVED_KEY = ("data-catalog/derived/synlethdb-sl-partners-per-gene-v1/"
               "synlethdb_sl_partners_per_gene.parquet")
DEFAULT_AWS_PROFILE = "cbg"

# rel_source → evidence tier rank (higher = stronger). Experimental screens outrank
# computational predictions. Values observed in the v3 table: "CRISPR/CRISPRi",
# "GenomeRNAi", "High Throughput", "Low Throughput", "Computational Prediction",
# "Text Mining" (+ combinations). We bucket to a 3-level ordinal.
_EXPERIMENTAL_MARKERS = ("crispr", "rnai", "throughput", "screen", "shrna", "sirna")
_COMPUTATIONAL_MARKERS = ("computational", "prediction", "text mining", "predicted")


def evidence_tier(rel_source: Optional[str]) -> str:
    """Bucket a rel_source string → {experimental | computational | other}."""
    s = (rel_source or "").strip().lower()
    if not s:
        return "other"
    if any(m in s for m in _EXPERIMENTAL_MARKERS):
        return "experimental"
    if any(m in s for m in _COMPUTATIONAL_MARKERS):
        return "computational"
    return "other"


# An UNRECOGNIZED rel_source ("other" — no experimental/computational marker matched) must NOT
# outrank a KNOWN computational prediction: unknown provenance is the least-trustworthy tier, not a
# middle one. (Was {experimental:2, other:1, computational:0}, which let an unmapped source win the
# best_evidence_tier / top-partner sort over a labelled computational edge.) Build-time only (the
# resulting best_evidence_tier is frozen into the parquet); takes effect on the next re-derive.
_TIER_RANK = {"experimental": 2, "computational": 1, "other": 0}


from methods.target_id_sidecar import ensure_aws_profile


def load_sl_pairs(tsv_path=None):
    """Load the SynLethDB SL pair table (local path or S3)."""
    import pandas as pd
    cols = ["x:START_ID", "x_name", "y:END_ID", "y_name", "rel_source",
            "cell_line", "pubmed_id", "cancer"]
    if tsv_path is not None:
        return pd.read_csv(tsv_path, sep="\t", usecols=cols, dtype=str)
    ensure_aws_profile()
    import boto3
    body = boto3.client("s3").get_object(Bucket=S3_BUCKET, Key=SL_SOURCE_KEY)["Body"].read()
    return pd.read_csv(io.BytesIO(body), sep="\t", usecols=cols, dtype=str)


def build_partner_index(df) -> "list[dict]":
    """Invert the symmetric SL pair-list → per-gene partner records."""
    # gene_symbol → {entrez, partners: {partner_sym: {tier, pubmed, cell_line, entrez}}}
    genes: dict = defaultdict(lambda: {"entrez": None, "partners": {}})

    def _add(gene_sym, gene_entrez, partner_sym, partner_entrez, tier, pubmed, cell_line):
        if not gene_sym or gene_sym == "nan" or not partner_sym or partner_sym == "nan":
            return
        rec = genes[gene_sym]
        if rec["entrez"] is None and gene_entrez and gene_entrez != "nan":
            rec["entrez"] = gene_entrez
        existing = rec["partners"].get(partner_sym)
        # keep the STRONGEST evidence tier seen for this partner
        if existing is None or _TIER_RANK[tier] > _TIER_RANK[existing["evidence_tier"]]:
            rec["partners"][partner_sym] = {
                "partner": partner_sym, "partner_entrez": partner_entrez,
                "evidence_tier": tier,
                "pubmed_id": (pubmed if pubmed and pubmed != "nan" else None),
                "cell_line": (cell_line if cell_line and cell_line != "nan" else None),
            }

    # Column names include non-identifiers ("x:START_ID"), so iterate by explicit
    # column arrays rather than itertuples attribute access.
    x_ents = df["x:START_ID"].tolist()
    x_syms = df["x_name"].tolist()
    y_ents = df["y:END_ID"].tolist()
    y_syms = df["y_name"].tolist()
    rel_sources = df["rel_source"].tolist()
    pubmeds = df["pubmed_id"].tolist()
    cell_lines = df["cell_line"].tolist()
    for i in range(len(df)):
        tier = evidence_tier(rel_sources[i])
        # symmetric: both directions
        _add(x_syms[i], x_ents[i], y_syms[i], y_ents[i], tier, pubmeds[i], cell_lines[i])
        _add(y_syms[i], y_ents[i], x_syms[i], x_ents[i], tier, pubmeds[i], cell_lines[i])

    records = []
    for sym, rec in genes.items():
        partners = list(rec["partners"].values())
        n_exp = sum(1 for p in partners if p["evidence_tier"] == "experimental")
        tiers_present = {p["evidence_tier"] for p in partners}
        best = ("experimental" if "experimental" in tiers_present
                else "other" if "other" in tiers_present else "computational")
        # top partners: experimental first, then by presence of pubmed
        partners_sorted = sorted(
            partners,
            key=lambda p: (_TIER_RANK[p["evidence_tier"]], p["pubmed_id"] is not None),
            reverse=True)
        records.append({
            "gene_symbol": sym,
            "entrez_id": rec["entrez"],
            "sl_partner_count": len(partners),
            "n_experimental_partners": n_exp,
            "has_experimental_partner": n_exp > 0,
            "best_evidence_tier": best,
            "sl_partner_symbols": sorted(p["partner"] for p in partners),
            "top_partners": partners_sorted[:20],
            "method_version": METHOD_VERSION,
        })
    return records


def build_and_write(tsv_path=None, out_path=None):
    """Precompute entrypoint: build the per-gene partner parquet."""
    import pandas as pd
    df = load_sl_pairs(tsv_path)
    records = build_partner_index(df)
    out_df = pd.DataFrame.from_records(records)
    # Sort by gene_symbol before write: the runtime reader does a gene_symbol point-lookup
    # (see read.py docstring), so a gene-sorted product lets pyarrow predicate pushdown prune
    # to ~1 row-group per gene instead of scanning the whole parquet. Written unsorted until now.
    if "gene_symbol" in out_df.columns:
        out_df = out_df.sort_values("gene_symbol", kind="mergesort").reset_index(drop=True)
    if out_path is not None:
        out_df.to_parquet(out_path, index=False)
    return out_df


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Build synlethdb-sl-partners-per-gene-v1.")
    ap.add_argument("--tsv-path", default=None, help="local SL TSV (else S3)")
    ap.add_argument("--out", required=True, help="output parquet path")
    args = ap.parse_args(argv)
    df = build_and_write(tsv_path=args.tsv_path, out_path=args.out)
    print(f"wrote {len(df)} gene rows to {args.out}")


if __name__ == "__main__":
    _main()
