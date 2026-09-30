#!/usr/bin/env python
"""Live-capture tool for the pooled-SNV-recurrence T3 recomputation anchors (foamy-bird Stage I).

NOT collected by pytest — it hits S3 (the three cohort products + the pooled product) and needs cbg
creds. Run it by hand to (re)mint the fixtures the OFFLINE test re-derives against:

    cd <analysis-methods primary checkout>
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
        PYTHONPATH=<this worktree> pixi run python \
        <this worktree>/tests/calibration/recomputation/capture_pooled_snv_anchor.py

What it freezes and why (tier T3 = the only tier that proves a NUMBER):
  * The IRREPRODUCIBLE input is the per-cohort {gene: (n_mut, n_cov)} slice for one indication, summed
    across TCGA-MC3 (whole-exome) + AACR GENIE + MSK-CHORD (panels). The MSK-IMPACT MAF behind the
    MSK-CHORD arm was removed upstream (LFS-404'd, backfilled), so this slice cannot be re-fetched — the
    T3 precondition. We store the FULL per-cohort gene set (~20k rows), not just the anchor genes: the
    percentile is ranked against the pooled null of ALL rankable genes, so truncating the fixture would
    collapse the comparator and BE the wrong-denominator / comparator-collapse bug this tier exists to
    catch (read.py:281-282, :322).
  * The test re-derives pooled_mutation_frequency (Σn_mut/Σn_cov), the percentile and the class through
    the REAL methods.pooled_snv_recurrence.read.pooled_recurrence_for_gene (live path) + the shared
    methods.percentile_null helpers. A snapshot of a DERIVED value asserts code reproduces its own output
    and can never fail; this stores the raw INPUT and re-derives.

Cross-check: each re-derived value is compared, AT CAPTURE TIME, against the SHIPPED product
pooled-snv-recurrence-v2 (S3 pushdown). Source → live re-derivation → product must all agree, or the
capture aborts — a divergence is a product-staleness finding, not something to force.

Data provenance: TCGA-MC3 (NIH/GDC), AACR Project GENIE (CC-BY 4.0), MSK-CHORD/MSK-IMPACT — all public
research somatic-mutation resources; only aggregate per-gene mutated/covered COUNTS are stored, no
patient-level data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

import pyarrow as pa
import pyarrow.parquet as pq

import onc_methods.pooled_snv_recurrence.read as pr

INDICATION = "COADREAD"
# Anchors spanning the classifier's four branches, grounded in colorectal-cancer biology:
#   top_1pct    KRAS / APC / TP53  — the canonical recurrent CRC SNV drivers (all three cohorts, ~29k N)
#   top_decile  CTNNB1 / ERBB2     — WNT / HER2, recurrent but below the 1% tail
#   mid         KIT / IDH1         — genuinely mid-recurrence in CRC
#   bottom_dec  CD3D               — an immune-lineage marker, NOT a CRC SNV driver (negative anchor)
ANCHOR_GENES = ["KRAS", "APC", "TP53", "CTNNB1", "ERBB2", "KIT", "IDH1", "CD3D"]

COUNTS_DIR = HERE / "pooled_counts"
ANCHOR_DIR = HERE / "anchors"
COHORT_READERS = {"TCGA-MC3": "_mc3_gene_counts", "GENIE": "_genie_gene_counts", "MSK-CHORD": "_msk_gene_counts"}


def _capture_per_cohort(indication: str) -> dict[str, dict]:
    per_cohort: dict[str, dict] = {}
    for cohort, fn_name in COHORT_READERS.items():
        counts = getattr(pr, fn_name)(indication)
        per_cohort[cohort] = counts
        print(f"  {cohort}: {len(counts)} genes")
    if sum(len(c) for c in per_cohort.values()) == 0:
        raise SystemExit(f"no cohort returned counts for {indication} — check creds / manifests")
    n_multi = sum(1 for c in per_cohort.values() if c)
    if n_multi < 2:
        raise SystemExit(f"only {n_multi} cohort(s) non-empty for {indication} — pooling join not exercised")
    return per_cohort


def _write_counts_parquet(per_cohort: dict[str, dict], path: Path) -> str:
    rows = []
    for cohort, counts in per_cohort.items():
        for gene, (n_mut, n_cov) in counts.items():
            rows.append({"cohort": cohort, "gene_symbol": str(gene), "n_mut": int(n_mut), "n_cov": int(n_cov)})
    rows.sort(key=lambda r: (r["cohort"], r["gene_symbol"]))
    table = pa.Table.from_pylist(
        rows,
        schema=pa.schema(
            [
                pa.field("cohort", pa.string()),
                pa.field("gene_symbol", pa.string()),
                pa.field("n_mut", pa.int64()),
                pa.field("n_cov", pa.int64()),
            ]
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return hashlib.md5(path.read_bytes()).hexdigest()


def _per_cohort_from_parquet(path: Path) -> dict[str, dict]:
    """Round-trip the fixture exactly as the offline test will read it — guards a write/read dtype drift."""
    table = pq.read_table(path).to_pydict()
    out: dict[str, dict] = {}
    for cohort, gene, n_mut, n_cov in zip(
        table["cohort"], table["gene_symbol"], table["n_mut"], table["n_cov"], strict=True
    ):
        out.setdefault(cohort, {})[gene] = (int(n_mut), int(n_cov))
    return out


def _rederive_from_fixture(per_cohort: dict[str, dict], target: str, indication: str) -> dict:
    """Force the LIVE pooled path over the frozen counts — the exact code the offline test runs."""
    import onc_methods.pooled_snv_recurrence.read as p

    orig = (p._pooled_from_product, p._mc3_gene_counts, p._genie_gene_counts, p._msk_gene_counts)
    try:
        p._pooled_from_product = lambda *a, **k: None
        p._mc3_gene_counts = lambda ind: dict(per_cohort.get("TCGA-MC3", {}))
        p._genie_gene_counts = lambda ind: dict(per_cohort.get("GENIE", {}))
        p._msk_gene_counts = lambda ind: dict(per_cohort.get("MSK-CHORD", {}))
        p._pooled_for_indication.cache_clear()
        return p.pooled_recurrence_for_gene(target, indication)
    finally:
        (p._pooled_from_product, p._mc3_gene_counts, p._genie_gene_counts, p._msk_gene_counts) = orig
        p._pooled_for_indication.cache_clear()


def main() -> None:
    print(f"capturing per-cohort SNV counts for {INDICATION} …")
    per_cohort = _capture_per_cohort(INDICATION)
    counts_path = COUNTS_DIR / f"{INDICATION.lower()}__per_cohort_counts.parquet"
    md5 = _write_counts_parquet(per_cohort, counts_path)
    print(f"wrote {counts_path.name} (md5 {md5})")

    reloaded = _per_cohort_from_parquet(counts_path)
    captured_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = {
        "pooled_product_id": pr._POOLED_PRODUCT_ID,
        "cohort_source": {
            "TCGA-MC3": "tcga-mc3-hotspot-frequency-v1 (gene-summary rows)",
            "GENIE": "AACR Project GENIE coverage-correct panel frequencies (CC-BY 4.0)",
            "MSK-CHORD": "MSK-CHORD / MSK-IMPACT panel coverage (upstream MAF removed — irreproducible)",
        },
        "captured_utc": captured_utc,
        "counts_fixture_md5": md5,
    }

    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    for gene in ANCHOR_GENES:
        live = _rederive_from_fixture(reloaded, gene, INDICATION)
        prod = pr._pooled_from_product(gene, INDICATION)
        if prod is None:
            raise SystemExit(f"{gene}: not a rankable row in the shipped product — pick a covered driver")
        # Source → fixture re-derivation → shipped product must all agree.
        for field in (
            "pooled_mutation_frequency",
            "pooled_driver_recurrence_percentile",
            "pooled_driver_recurrence_class",
        ):
            if live[field] != prod[field]:
                raise SystemExit(
                    f"{gene}: fixture re-derivation {field}={live[field]!r} != product {prod[field]!r} — "
                    "product staleness, do not pin"
                )
        anchor = {
            "target": gene,
            "indication": INDICATION,
            "counts_fixture": str(counts_path.relative_to(HERE)),
            "expected_pooled_freq": live["pooled_mutation_frequency"],
            "expected_percentile": live["pooled_driver_recurrence_percentile"],
            "expected_class": live["pooled_driver_recurrence_class"],
            "n_mutated_pooled": live["n_mutated_pooled"],
            "n_covered_pooled": live["n_covered_pooled"],
            "n_ranked_genes": live["n_ranked_genes"],
            "cohorts_contributing": live["cohorts_contributing"],
            "product_cross_ref": {
                "pooled_mutation_frequency": prod["pooled_mutation_frequency"],
                "pooled_driver_recurrence_percentile": prod["pooled_driver_recurrence_percentile"],
                "pooled_driver_recurrence_class": prod["pooled_driver_recurrence_class"],
            },
            "_source": source,
        }
        out = ANCHOR_DIR / f"{gene.lower()}_{INDICATION.lower()}.pooled_snv_recurrence.json"
        out.write_text(json.dumps(anchor, indent=2) + "\n")
        print(
            f"  {gene:8s} freq={live['pooled_mutation_frequency']:.6f} "
            f"pct={live['pooled_driver_recurrence_percentile']} cls={live['pooled_driver_recurrence_class']} "
            f"(n_mut={live['n_mutated_pooled']} n_cov={live['n_covered_pooled']}) → {out.name}"
        )
    print("done.")


if __name__ == "__main__":
    main()
