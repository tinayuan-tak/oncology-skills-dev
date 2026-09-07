"""tcga_patient_cn.read — per-(gene, indication) patient copy-number prevalence from GISTIC.

Reads the PanCanAtlas GISTIC discrete thresholded calls per gene (-2 homdel / -1 loss / 0 neutral /
+1 gain / +2 high-amp), joins each aliquot to its indication via merged_sample_quality_annotations
(the SAME barcode→cancer-type map tcga_aneuploidy_burden + functional_gene_state use), and summarizes
the cohort amp/del prevalence into a patient_copy_number_class that MIRRORS the DepMap cell-line
copy_number_class vocabulary — so the two are directly comparable as a cross-check.

Additive / verdict-inert: this is a DISPLAY cross-check to the cell-line copy_number_class; it fires
no resolver rung. Reads live per-gene (GISTIC file is gene-rows; one row read per query).
"""

from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
PANCAN_PREFIX = "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27"
GISTIC_KEY = f"{PANCAN_PREFIX}/all_thresholded.by_genes_whitelisted.tsv"
SAMPLE_ANNOT_KEY = f"{PANCAN_PREFIX}/merged_sample_quality_annotations.tsv"

# framework indication → TCGA `cancer type` code(s) (mirrors tcga_aneuploidy_burden.INDICATION_TO_TCGA).
INDICATION_TO_TCGA = {
    "COADREAD": ("COAD", "READ"),
    "COAD": ("COAD",),
    "READ": ("READ",),
    "NSCLC": ("LUAD", "LUSC"),
    "LUAD": ("LUAD",),
    "LUSC": ("LUSC",),
    "PAAD": ("PAAD",),
    "PDAC": ("PAAD",),
    "GC": ("STAD",),
    "STAD": ("STAD",),
    "BRCA": ("BRCA",),
    "HNSC": ("HNSC",),
    "HNSCC": ("HNSC",),
    "ESCA": ("ESCA",),
    "OV": ("OV",),
    "PRAD": ("PRAD",),
    "SKCM": ("SKCM",),
    "UCEC": ("UCEC",),
}
# GISTIC discrete: +1 = low-level gain, +2 = high-level amplification; -1 = shallow loss, -2 = homdel.
# "Amplified" = >= +1 (any gain); "deleted" = <= -1 (any loss). Cohort-recurrence bar = 20% (mirrors
# the DepMap cn distribution's recurrent-event threshold, so patient and cell-line classes are comparable).
_RECURRENT_FRACTION = 0.20
# When BOTH amp and del clear the bar, "mixed" iff neither dominates by more than this ratio.
_DOMINANCE_RATIO = 1.5
# FOCAL categorical (verdict-consensus companion). patient_copy_number_class fires on ANY gain
# (>= +1), which includes arm-level noise (e.g. KRAS 12p arm-gain 23% but only 1% focal). The
# genomic-verdict CN-consensus rung must gate on FOCAL high-level amplification (GISTIC +2), NOT
# arm-level gain — so this emits a CATEGORICAL patient_focal_amplification the rule engine can match
# (equals-only; no numeric thresholds in rules — same discipline as the 2b homdel flag). The
# recurrence bar for FOCAL amp is lower than any-gain because high-level +2 is a stronger event.
_FOCAL_AMP_FRACTION = 0.10  # high-level (+2) in >= 10% of tumours → recurrent_focal_amplification
_FOCAL_HOMDEL_FRACTION = 0.10  # homdel (-2) in >= 10% → recurrent_focal_deletion (the TSG analog)


from methods.target_id_sidecar import ensure_aws_profile


def _s3_read_bytes(key: str) -> bytes:
    import boto3

    ensure_aws_profile()
    s3 = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")
    return s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()


def _barcode_to_patient(sample: str) -> str:
    """GISTIC columns are aliquot barcodes (TCGA-02-0001-01A-...); the annotation table keys on the
    3-segment patient barcode. Truncate to join."""
    parts = str(sample).split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(sample)


@lru_cache(maxsize=1)
def _load_sample_cancer_types() -> dict:
    """{patient_barcode: cancer_type} from merged_sample_quality_annotations — the SHARED barcode→
    cancer-type crosswalk that gates EVERY gene's indication join here and in tcga_aneuploidy_burden.

    A crosswalk either loads or it does NOT (ref methods/target_id_sidecar.read_resolver_sidecar_map):
      * transient / creds / broken-env failure (throttle, ExpiredToken, missing pandas) -> re-raise so
        the live-read seam surfaces an honest _live_read_error rather than collapsing the join;
      * a well-formed read that yields an EMPTY map -> raise too, because returning {} would silently
        collapse every gene's join to "no samples" (the null-strata bug class — mirrors the
        empty-crosswalk guard);
      * ONLY a genuine NoSuchKey/404 on the annotation object is a real absence -> {}.
    """
    import pandas as pd
    from methods.target_id_sidecar import is_definitively_absent

    try:
        raw = _s3_read_bytes(SAMPLE_ANNOT_KEY)
        df = pd.read_csv(io.BytesIO(raw), sep="\t", usecols=["patient_barcode", "cancer type"], dtype=str)
        df = df.dropna(subset=["patient_barcode", "cancer type"])
        out = dict(zip(df["patient_barcode"], df["cancer type"]))
    except Exception as e:  # noqa: BLE001
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return {}
        raise
    if not out:
        raise ValueError(
            f"sample→cancer-type crosswalk s3://{S3_BUCKET}/{SAMPLE_ANNOT_KEY} produced an EMPTY map "
            "(well-formed read, no usable barcode→cancer-type pairs) — a broken/empty product, NOT a "
            "data gap; returning {} here would silently collapse every gene's indication join."
        )
    return out


@lru_cache(maxsize=256)
def _read_gistic_gene(target: str) -> tuple:
    """GISTIC discrete CN for ONE gene: tuple of (aliquot_barcode, int_value). The file is gene-rows;
    we scan for the target row and drop the meta columns. Cached per gene.

    Empty tuple ONLY for genuine absence: a gene not present in the GISTIC calls (empty row), or a
    NoSuchKey/404 on the 589 MB TSV object. A transient / creds / broken-env failure on that read is
    NOT absence -> re-raise so the live-read seam surfaces an honest _live_read_error."""
    import pandas as pd
    from methods.target_id_sidecar import is_definitively_absent

    try:
        raw = _s3_read_bytes(GISTIC_KEY)
        df = pd.read_csv(io.BytesIO(raw), sep="\t", low_memory=False)
        row = df[df["Gene Symbol"] == target]
        if row.empty:
            return tuple()
        meta = {"Gene Symbol", "Locus ID", "Cytoband"}
        vals = row.iloc[0].drop(labels=[c for c in meta if c in row.columns])
        return tuple(
            (str(k), int(v)) for k, v in vals.items() if str(v) not in ("nan", "") and str(v).lstrip("-").isdigit()
        )
    except Exception as e:  # noqa: BLE001
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return tuple()
        raise


def _classify(amp_frac: float, del_frac: float) -> str:
    """Mirror the DepMap copy_number_class vocabulary so patient + cell-line CN are comparable:
    recurrently_amplified / recurrently_deleted / mixed / broadly_neutral."""
    amp_rec = amp_frac >= _RECURRENT_FRACTION
    del_rec = del_frac >= _RECURRENT_FRACTION
    if amp_rec and del_rec:
        # both recurrent → the dominant one wins unless they're balanced (mixed)
        if amp_frac >= del_frac * _DOMINANCE_RATIO:
            return "recurrently_amplified"
        if del_frac >= amp_frac * _DOMINANCE_RATIO:
            return "recurrently_deleted"
        return "mixed"
    if amp_rec:
        return "recurrently_amplified"
    if del_rec:
        return "recurrently_deleted"
    return "broadly_neutral"


def _focal_class(high_amp_frac: float, homdel_frac: float) -> str:
    """FOCAL categorical for the genomic-verdict consensus rung — gates on HIGH-LEVEL (+2) focal
    amplification / homozygous (-2) deletion, NOT arm-level any-gain. equals-matchable by the rule
    engine. recurrent_focal_amplification takes precedence over deletion when both clear (a focal
    high-amp is the actionable oncogene signal); returns focal_neutral when neither is recurrent."""
    amp = high_amp_frac is not None and high_amp_frac >= _FOCAL_AMP_FRACTION
    dele = homdel_frac is not None and homdel_frac >= _FOCAL_HOMDEL_FRACTION
    if amp and dele:
        return "recurrent_focal_amplification" if high_amp_frac >= homdel_frac else "recurrent_focal_deletion"
    if amp:
        return "recurrent_focal_amplification"
    if dele:
        return "recurrent_focal_deletion"
    return "focal_neutral"


# Materialized gene-sorted product (the fast path). Registered as tcga-patient-cn-per-gene-v1; the
# card reads a per-gene pushdown slice (~a few rows) instead of the 589 MB TSV. Live TSV read stays
# as a fallback when the product isn't resolvable.
PRODUCT_MANIFEST_ID = "tcga-patient-cn-per-gene-v1"


def _summarize(vals) -> Optional[dict]:
    """Cohort amp/del summary from a list of GISTIC discrete ints. None if empty."""
    n = len(vals)
    if n == 0:
        return None
    n_amp = sum(1 for v in vals if v >= 1)
    n_highamp = sum(1 for v in vals if v >= 2)
    n_del = sum(1 for v in vals if v <= -1)
    n_homdel = sum(1 for v in vals if v <= -2)
    amp_frac, del_frac = n_amp / n, n_del / n
    high_amp_frac, homdel_frac = n_highamp / n, n_homdel / n
    return {
        "patient_copy_number_class": _classify(amp_frac, del_frac),
        "patient_focal_cn_class": _focal_class(high_amp_frac, homdel_frac),  # verdict-consensus gate (focal only)
        "patient_amplified_fraction": amp_frac,
        "patient_high_amp_fraction": high_amp_frac,
        "patient_deleted_fraction": del_frac,
        "patient_homdel_fraction": homdel_frac,
        "n_samples": n,
    }


def _context(target, indication, s) -> str:
    return (
        f"{indication}: {s['patient_amplified_fraction']:.0%} of {s['n_samples']} TCGA GISTIC "
        f"samples amplify {target} ({s['patient_high_amp_fraction']:.0%} high-level +2), "
        f"{s['patient_deleted_fraction']:.0%} deleted ({s['patient_homdel_fraction']:.0%} homdel) — "
        f"PATIENT tumour CN, the cross-check to the DepMap cell-line copy_number_class. "
        f"Cohort-level, verdict-inert."
    )


def _read_from_product(target: str, indication: str) -> Optional[dict]:
    """Fast path: per-gene pushdown read of the materialized gene-sorted product. Returns the
    summary dict, or None if the product is unresolvable (→ caller falls back to the live TSV)."""
    try:
        import sys as _sys
        from pathlib import Path as _P

        _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs

        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=fs.S3FileSystem(),
            filters=[
                ("gene_symbol", "=", (target or "").strip().upper()),
                ("indication", "=", str(indication or "").upper().strip()),
            ],
        )
    except Exception:  # absence-discipline: exempt -- product absent/unreadable → benign live-TSV fallback in read_patient_cn (_read_gistic_gene), not a dead axis
        return None
    if tbl.num_rows == 0:
        return None
    r = tbl.to_pylist()[0]
    s = {
        k: r[k]
        for k in (
            "patient_copy_number_class",
            "patient_focal_cn_class",
            "patient_amplified_fraction",
            "patient_high_amp_fraction",
            "patient_deleted_fraction",
            "patient_homdel_fraction",
            "n_samples",
        )
    }
    return s


def patient_cn_summary_for_gene(target: str, indication: str) -> dict:
    """Per-(gene, indication) PATIENT copy-number prevalence from TCGA GISTIC. A verdict-inert
    CROSS-CHECK to the cell-line copy_number_class (same vocabulary).

    Product-first (gene-sorted pushdown) then a live full-TSV fallback. Returns
    patient_copy_number_class {recurrently_amplified / recurrently_deleted / mixed / broadly_neutral /
    data_unavailable}, amp/del/high-amp/homdel fractions, n_samples, context. data_unavailable when the
    gene isn't in GISTIC or the indication has no TCGA mapping/samples."""
    codes = INDICATION_TO_TCGA.get(str(indication or "").upper().strip())
    if not codes:
        return _unavailable(f"no TCGA project mapping for indication={indication!r}")

    # Fast path: the materialized product.
    s = _read_from_product(target, indication)
    read_path = "product"
    if s is None:
        # Live fallback: scan the raw GISTIC TSV for this gene.
        read_path = "live_tsv"
        gistic = _read_gistic_gene((target or "").strip())
        if not gistic:
            return _unavailable(f"{target} not found in GISTIC thresholded calls")
        cancer = _load_sample_cancer_types()
        if not cancer:
            return _unavailable("sample→cancer-type annotation unavailable")
        codeset = set(codes)
        vals = [v for aliquot, v in gistic if cancer.get(_barcode_to_patient(aliquot)) in codeset]
        s = _summarize(vals)
        if s is None:
            return _unavailable(f"no GISTIC samples for {indication} ({codes})")

    return {
        **s,
        "patient_cn_context": _context(target, indication, s),
        "method_version": "0.1.0",
        "_data_source": "gdc-pancanatlas-cnv-2018",
        "_read_path": read_path,
    }


def build_patient_cn_table():
    """Materialize the gene-sorted per-(gene, indication) patient-CN product in ONE full-file pass
    (the raw GISTIC TSV is 589 MB — read it once, summarize every gene × every mapped indication).
    VECTORIZED: for each indication, slice the gene×aliquot matrix to that indication's columns and
    compute amp/del/highamp/homdel counts with numpy column ops (no per-gene Python loop).
    Returns a gene-sorted pyarrow Table for tcga-patient-cn-per-gene-v1."""
    import numpy as np
    import pandas as pd
    import pyarrow as pa

    cancer = _load_sample_cancer_types()
    raw = _s3_read_bytes(GISTIC_KEY)
    df = pd.read_csv(io.BytesIO(raw), sep="\t", low_memory=False)
    meta = [c for c in ("Gene Symbol", "Locus ID", "Cytoband") if c in df.columns]
    aliquot_cols = [c for c in df.columns if c not in meta]
    genes = df["Gene Symbol"].astype(str).str.strip().str.upper().to_numpy()
    col_ctype = {c: cancer.get(_barcode_to_patient(c)) for c in aliquot_cols}
    served = sorted(set(INDICATION_TO_TCGA))

    rows = []
    for ind in served:
        codeset = set(INDICATION_TO_TCGA[ind])
        cols = [c for c in aliquot_cols if col_ctype.get(c) in codeset]
        if not cols:
            continue
        # gene × sample matrix for this indication (numeric, NaN where non-integer/missing).
        mat = df[cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype="float32")
        n = np.sum(~np.isnan(mat), axis=1)  # assayed samples per gene
        amp = np.sum(mat >= 1, axis=1)
        highamp = np.sum(mat >= 2, axis=1)
        dele = np.sum(mat <= -1, axis=1)
        homdel = np.sum(mat <= -2, axis=1)
        for i in range(len(genes)):
            gi = genes[i]
            ni = int(n[i])
            if not gi or ni == 0:
                continue
            amp_f, del_f = amp[i] / ni, dele[i] / ni
            high_f, homdel_f = float(highamp[i] / ni), float(homdel[i] / ni)
            rows.append(
                {
                    "gene_symbol": gi,
                    "indication": ind,
                    "patient_copy_number_class": _classify(float(amp_f), float(del_f)),
                    "patient_focal_cn_class": _focal_class(high_f, homdel_f),
                    "patient_amplified_fraction": float(amp_f),
                    "patient_high_amp_fraction": high_f,
                    "patient_deleted_fraction": float(del_f),
                    "patient_homdel_fraction": homdel_f,
                    "n_samples": ni,
                }
            )
    rows.sort(key=lambda r: (r["gene_symbol"], r["indication"]))
    return pa.Table.from_pylist(rows, schema=_schema())


def _schema():
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("indication", pa.string()),
            pa.field("patient_copy_number_class", pa.string()),
            pa.field("patient_focal_cn_class", pa.string()),
            pa.field("patient_amplified_fraction", pa.float64()),
            pa.field("patient_high_amp_fraction", pa.float64()),
            pa.field("patient_deleted_fraction", pa.float64()),
            pa.field("patient_homdel_fraction", pa.float64()),
            pa.field("n_samples", pa.int64()),
        ]
    )


def _unavailable(note: str) -> dict:
    return {
        "patient_copy_number_class": "data_unavailable",
        "patient_focal_cn_class": "data_unavailable",
        "patient_amplified_fraction": None,
        "patient_high_amp_fraction": None,
        "patient_deleted_fraction": None,
        "patient_homdel_fraction": None,
        "n_samples": 0,
        "patient_cn_context": None,
        "method_version": "0.1.0",
        "_data_note": note,
    }
