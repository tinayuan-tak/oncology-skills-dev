"""LIVE capture tool for the tumor-rna-vs-adjacent T3 recomputation anchor (#2044, batch B).

NOT collected by pytest (no ``test_`` prefix): it needs live DGE product reads (AWS ``cbg`` creds);
the committed sibling test ``test_tumor_rna_vs_adjacent_recomputation.py`` is fully offline and reads
only the fixtures this tool writes.

WHAT IT FREEZES (the read-path's irreproducible input for tumor-rna-vs-adjacent):
  1. the target's single RAW gene row from the per-indication DESeq2 product (``coadread-dge-df06320``,
     product ``expression-rna-tumor-vs-adjacent``) — log2FoldChange/padj/n_tumor/n_normal/baseMean +
     the provider-call flags. Stored inline in the anchor JSON (a handful of scalars).
  2. the product's ALL-GENE log2FoldChange null vector (~30-34k values, the context-matched null for
     the additive ``allgene_percentile``), committed as a lossless parquet under ``dge_rows/`` and
     SHARED across all anchors for the same manifest.

and RE-DERIVES the card summary through the REAL ``methods.dge_deseq2.read.read_dge_gene_row`` — so
the offline test validates the READ/AGGREGATION path (column normalization, ``expression_call_class``
derivation, all-gene percentile ranking), NOT the upstream DESeq2 run (that provenance belongs to
data-catalog).

BOUNDARY (documented deliberately): the adjacent-arm adequacy logic (``_adjacent_arm_adequacy``, the
PAAD cell-A exclusion, the n<=10 power ceiling — AM #864/#865) lives in the same module but is invoked
ONLY by the four-cell ``{indication}-dge-tumor-vs-normal-sensitivity-v1`` sensitivity readers
(``read_tumor_vs_normal_selectivity`` / ``read_tumor_vs_normal_sensitivity_gene_row``), NOT by
``read_dge_gene_row``. The ``expression-rna-tumor-vs-adjacent`` path this anchor freezes is therefore
NOT subject to that logic; it is not forced onto these anchors.

The card ALSO surfaces ``gtex_log2_fc``/``gtex_q_value`` — those come from a SEPARATE GTEx read
(``read_tumor_vs_gtex_gene_row``) fused skill-side, NOT from ``read_dge_gene_row``. This anchor does
not freeze or reconcile them (a different reader owns them).

Guard (fidelity): the offline re-derivation from the frozen inputs must reproduce the LIVE
``read_dge_gene_row`` call exactly on every field; if the frozen slice lost information the reader
uses, it aborts.

Run:
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
        PYTHONPATH=<analysis-methods-root> python3 <this file>
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent

import onc_methods.dge_deseq2.read as rd

ANCHOR_DIR = HERE / "anchors"
FIXTURE_DIR = HERE / "dge_rows"

# All in COADREAD: the tumor-vs-adjacent product is per-indication and only COADREAD carries a landed
# adjacent (cell A) DESeq2 product (_INDICATION_TO_ADJ_MANIFEST). The anchor set spans expression_call
# branches by choosing genes with different signals in the SAME product (EPCAM flagship + KRAS, a real
# down signal per the reader docstring + ERBB2).
MANIFEST_ID = "coadread-dge-df06320"
INDICATION = "COADREAD"
TARGETS = ["EPCAM", "KRAS", "ERBB2", "TACSTD2"]

# Every field read_dge_gene_row emits (return_field_map=True) except the pure-provenance keys.
_FIELDS = (
    "log2_fc",
    "q_value",
    "n_tumor",
    "n_adjacent",
    "base_mean",
    "is_significant_provider_call",
    "is_actionable_provider_call",
    "is_upregulated_provider_call",
    "expression_call_class",
    "allgene_percentile",
    "allgene_percentile_class",
    "allgene_percentile_context",
)


def _null_fixture_path(manifest_id: str) -> Path:
    return FIXTURE_DIR / f"{manifest_id}__log2fc_null.parquet"


def _write_null_fixture(manifest_id: str, null_vec: tuple) -> tuple[str, str]:
    """Write the all-gene log2FoldChange null as a lossless parquet; return (relative_path, md5)."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = _null_fixture_path(manifest_id)
    table = pa.table({"log2FoldChange": pa.array([float(v) for v in null_vec], type=pa.float64())})
    pq.write_table(table, path)
    rel = str(path.relative_to(HERE))
    return rel, hashlib.md5(path.read_bytes()).hexdigest()


def _offline_rederive(target: str, manifest_id: str, raw_gene_row: dict, null_vec: tuple) -> dict:
    """Re-derive the card summary through the REAL read_dge_gene_row, feeding it ONLY the frozen
    inputs: the raw 1-row gene table (via a patched pq.read_table) and the frozen all-gene null (via a
    patched _allgene_log2fc_null). No S3, no creds."""
    one_row = pa.table({k: pa.array([v]) for k, v in raw_gene_row.items()})

    def _fake_read_table(*_a, **_k):
        return one_row

    with (
        mock.patch.object(rd, "_load_manifest", lambda mid: {"s3_uri": "s3://frozen/anchor.parquet"}),
        mock.patch.object(rd, "_get_s3fs", lambda: None),
        mock.patch.object(rd, "_allgene_log2fc_null", lambda mid, column="log2FoldChange": tuple(null_vec)),
        mock.patch("pyarrow.parquet.read_table", _fake_read_table),
    ):
        return rd.read_dge_gene_row(target, manifest_id, return_field_map=True)


def main() -> None:
    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    classes: set[str] = set()
    n_written = 0
    null_rel: str | None = None
    null_md5: str | None = None
    null_vec: tuple = tuple()

    # The all-gene null is a per-manifest CONSTANT — capture it once and share it.
    null_vec = rd._allgene_log2fc_null(MANIFEST_ID)
    if not null_vec:
        raise SystemExit(f"ABORT: empty all-gene log2FoldChange null for {MANIFEST_ID} (no creds / product missing)")
    null_rel, null_md5 = _write_null_fixture(MANIFEST_ID, null_vec)

    for target in TARGETS:
        raw = rd.read_dge_gene_row(target, MANIFEST_ID, return_field_map=False)
        if raw is None:
            print(f"SKIP {target}: absent from {MANIFEST_ID}", file=sys.stderr)
            continue
        # Drop provenance keys the return_field_map=False path adds; keep only true parquet columns.
        raw_gene_row = {k: v for k, v in raw.items() if not k.startswith("_")}

        live = rd.read_dge_gene_row(target, MANIFEST_ID, return_field_map=True)
        if live is None or live.get("expression_call_class") == "data_unavailable":
            print(f"SKIP {target}: live read data_unavailable", file=sys.stderr)
            continue

        off = _offline_rederive(target, MANIFEST_ID, raw_gene_row, null_vec)
        for f in _FIELDS:
            if off.get(f) != live.get(f):
                raise SystemExit(
                    f"ABORT [{target}]: offline re-derivation != live compute on {f!r}: "
                    f"{off.get(f)!r} != {live.get(f)!r} — the frozen slice lost information"
                )

        classes.add(live["expression_call_class"])
        anchor = {
            "target": target,
            "indication": INDICATION,
            "manifest_id": MANIFEST_ID,
            "product_id": "expression-rna-tumor-vs-adjacent",
            "raw_gene_row": raw_gene_row,
            "null_fixture": null_rel,
            "null_fixture_md5": null_md5,
            "expected_log2_fc": live["log2_fc"],
            "expected_q_value": live["q_value"],
            "expected_n_tumor": live["n_tumor"],
            "expected_n_adjacent": live["n_adjacent"],
            "expected_base_mean": live["base_mean"],
            "expected_is_significant_provider_call": live["is_significant_provider_call"],
            "expected_is_actionable_provider_call": live["is_actionable_provider_call"],
            "expected_is_upregulated_provider_call": live["is_upregulated_provider_call"],
            "expected_expression_call_class": live["expression_call_class"],
            "expected_allgene_percentile": live["allgene_percentile"],
            "expected_allgene_percentile_class": live["allgene_percentile_class"],
            "expected_allgene_percentile_context": live["allgene_percentile_context"],
            "_source": {
                "product": f"{MANIFEST_ID} (expression-rna-tumor-vs-adjacent, TCGA tumor vs TCGA-adjacent DESeq2)",
                "reader": "onc_methods.dge_deseq2.read.read_dge_gene_row",
                "captured_utc": datetime.now(timezone.utc).isoformat(),
                "boundary": (
                    "validates the read/aggregation path (column normalization, expression_call_class "
                    "derivation, all-gene percentile), NOT the upstream DESeq2 run. Adjacent-arm adequacy "
                    "(#864/#865) is NOT on read_dge_gene_row's path (sensitivity-family only). gtex_log2_fc/"
                    "gtex_q_value come from a separate GTEx reader and are not frozen here."
                ),
            },
        }
        (ANCHOR_DIR / f"{target.lower()}_{INDICATION.lower()}.tumor_rna_vs_adjacent.json").write_text(
            json.dumps(anchor, indent=2) + "\n"
        )
        n_written += 1
        print(
            f"  {target:8} log2_fc={live['log2_fc']:+.4f} q={live['q_value']:.2e} "
            f"class={live['expression_call_class']} pct={live['allgene_percentile']}"
        )

    print(f"wrote {n_written} anchor(s); classes spanned ({len(classes)}): {sorted(classes)}")
    print(f"null fixture: {null_rel} md5={null_md5} n={len(null_vec)}")
    if n_written < 2:
        raise SystemExit(f"ABORT: only {n_written} anchor(s) written; need >= 2 (EPCAM/COADREAD + >=1 other)")
    if len(classes) < 2:
        raise SystemExit(f"ABORT: anchor set spans only {len(classes)} expression_call_class branch(es); need >= 2")


if __name__ == "__main__":
    main()
