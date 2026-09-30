"""tcga_spliceseq_psi.read — per-(gene, indication) patient splicing summary + builder.

PATIENT arm of the isoform/splice-EXPRESSION axis (roadmap #2). Reads TCGA SpliceSeq
per-event PSI (Percent-Spliced-In) matrices and summarizes, per gene per indication, how
alternatively-spliced / splicing-dysregulated the gene is in patient tumours:

  n_splice_events         — count of annotated alternative-splicing events for the gene
  max_event_psi_std       — max across events of the per-event PSI std across tumours (variability)
  median_event_psi_std    — median of the same (typical variability)
  n_variable_events       — events whose tumour PSI std >= _STD_VARIABLE (meaningfully variable)
  n_tumor_shifted_events  — events with |median tumour PSI - median matched-normal PSI| >= _SHIFT
                            (only when the cohort has matched normals; else data_unavailable)
  dominant_event_splice_type — splice class (ES/AA/AD/RI/AP/AT/ME) of the most-variable event
  splicing_dysregulation_class — highly_variable / tumor_shifted / stable / data_unavailable

The model arm (depmap-isoform-expression-per-gene-v1) says WHICH transcript a cell line
expresses; this says which SPLICE EVENTS vary or shift in patient tumours — the tumour-native
complement. Additive / verdict-inert DISPLAY facet.

Product-first reader (gene-sorted pushdown over the materialized per-(gene,indication) product)
+ a builder that streams the 33 per-tissue SpliceSeq files once (too big to live-read per query).
"""

from __future__ import annotations

import io
import os
import zipfile
from functools import lru_cache
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
# The source snapshot prefix (33 per-tissue PSI zips). Pinned by the source manifest.
SPLICESEQ_SOURCE_PREFIX = "data-catalog/sources/tcga-spliceseq"
PRODUCT_MANIFEST_ID = "tcga-spliceseq-psi-per-gene-v1"

# A splice event counts as "variable" across tumours if its PSI std >= this.
_STD_VARIABLE = 0.10
# An event is "tumour-shifted" if |median tumour PSI - median normal PSI| >= this.
_SHIFT = 0.10
# A gene needs >= this many events to summarize (avoids single-event noise).
_MIN_EVENTS = 1

# Framework-indication -> TCGA/SpliceSeq tissue codes (reused from tcga_fusion_consensus,
# extended with AML->LAML which SpliceSeq serves). The builder ALSO emits per-tissue rows.
_INDICATION_TISSUE = {
    "COADREAD": {"COAD", "READ"},
    "COAD": {"COAD"},
    "READ": {"READ"},
    "NSCLC": {"LUAD", "LUSC"},
    "LUAD": {"LUAD"},
    "LUSC": {"LUSC"},
    "HNSC": {"HNSC"},
    "HNSCC": {"HNSC"},
    "BRCA": {"BRCA"},
    "PRAD": {"PRAD"},
    "PAAD": {"PAAD"},
    "STAD": {"STAD"},
    "OV": {"OV"},
    "GBM": {"GBM"},
    "LGG": {"LGG"},
    "BLCA": {"BLCA"},
    "KIRC": {"KIRC"},
    "KIRP": {"KIRP"},
    "KICH": {"KICH"},
    "LIHC": {"LIHC"},
    "SKCM": {"SKCM"},
    "THCA": {"THCA"},
    "UCEC": {"UCEC"},
    "CESC": {"CESC"},
    "ESCA": {"ESCA"},
    "SARC": {"SARC"},
    "AML": {"LAML"},
    "LAML": {"LAML"},
}
# Composite indications the builder should emit in ADDITION to per-tissue rows.
_COMPOSITE_INDICATIONS = {"COADREAD": {"COAD", "READ"}, "NSCLC": {"LUAD", "LUSC"}, "AML": {"LAML"}}


from onc_methods.target_id_sidecar import ensure_aws_profile


def _boto3():
    import boto3

    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


def _classify(n_variable: int, n_shifted: Optional[int], n_events: int) -> str:
    """Categorical splicing-dysregulation class. tumor_shifted takes precedence (a directional
    tumour-vs-normal change is stronger evidence than mere variability); then highly_variable."""
    if n_events == 0:
        return "data_unavailable"
    if n_shifted is not None and n_shifted >= 1:
        return "tumor_shifted"
    if n_variable >= 1:
        return "highly_variable"
    return "stable"


def _read_from_product(target: str, indication: str) -> Optional[dict]:
    """Fast path: per-(gene, indication) pushdown read of the gene-sorted product. None if absent."""
    try:
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from onc_methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=fs.S3FileSystem(),
            filters=[
                ("gene_symbol", "=", (target or "").strip().upper()),
                ("indication", "=", (indication or "").strip().upper()),
            ],
        )
    except Exception as e:  # noqa: BLE001
        # genuine object-absence → None (data_unavailable; no live fallback for this display facet).
        # Broken-env/transient/creds must NOT be masked as a coverage gap — re-raise → _live_read_error.
        from onc_methods.target_id_sidecar import is_definitively_absent

        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return None
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def spliceseq_summary_for_gene(target: str, indication: str) -> dict:
    """Per-(gene, indication) PATIENT splicing summary. Product-first (gene-sorted pushdown);
    returns data_unavailable when the gene/indication isn't in the product. DISPLAY facet,
    verdict-inert. See module docstring for the field semantics."""
    sym = (target or "").strip()
    ind = (indication or "").strip().upper()
    r = _read_from_product(sym, ind)
    if r is None:
        return _unavailable(f"{sym}/{ind} not in tcga-spliceseq-psi product")
    n_shift = r.get("n_tumor_shifted_events")
    shift_txt = f"; {n_shift} tumour-shifted vs matched normal" if n_shift not in (None,) else "; no matched normals"
    return {
        "splicing_dysregulation_class": r.get("splicing_dysregulation_class"),
        "n_splice_events": r.get("n_splice_events"),
        "max_event_psi_std": r.get("max_event_psi_std"),
        "median_event_psi_std": r.get("median_event_psi_std"),
        "n_variable_events": r.get("n_variable_events"),
        "n_tumor_shifted_events": n_shift,
        "dominant_event_splice_type": r.get("dominant_event_splice_type"),
        "n_tumor_samples": r.get("n_tumor_samples"),
        "n_normal_samples": r.get("n_normal_samples"),
        "splicing_context": (
            f"{sym} in {ind}: {r.get('n_splice_events')} splice events, "
            f"max PSI std {r.get('max_event_psi_std'):.2f} across {r.get('n_tumor_samples')} tumours "
            f"({r.get('n_variable_events')} variable{shift_txt}) — PATIENT alternative-splicing, "
            f"verdict-inert."
            if r.get("max_event_psi_std") is not None
            else f"{sym}/{ind}: splicing summary present"
        ),
        "method_version": "0.1.0",
        "_data_source": "tcga-spliceseq",
    }


def _unavailable(note: str) -> dict:
    return {
        "splicing_dysregulation_class": "data_unavailable",
        "n_splice_events": None,
        "max_event_psi_std": None,
        "median_event_psi_std": None,
        "n_variable_events": None,
        "n_tumor_shifted_events": None,
        "dominant_event_splice_type": None,
        "n_tumor_samples": 0,
        "n_normal_samples": 0,
        "splicing_context": None,
        "method_version": "0.1.0",
        "_data_note": note,
    }


# ------------------------------ builder ------------------------------


def _iter_tissue_events(fh):
    """Yield (symbol, splice_type, tumor_psis[list[float]], normal_psis[list[float]]) per event row.
    fh is a text stream over a PSI_download_<T>.txt file. Skips the clinical-annotation rows
    (empty splice_type). Sample columns start at index 10; `_Norm`-suffixed columns are normals."""
    header = fh.readline().rstrip("\n").split("\t")
    sample_cols = header[10:]
    is_norm = [c.endswith("_Norm") for c in sample_cols]
    for line in fh:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 11 or not parts[2].strip():  # col 2 = splice_type; empty => annotation row
            continue
        sym = parts[0].strip().upper()
        st = parts[2].strip()
        vals = parts[10:]
        tumor, normal = [], []
        for i, v in enumerate(vals):
            if i >= len(is_norm) or v == "" or v == "null" or v == "NA":
                continue
            try:
                f = float(v)
            except ValueError:
                continue
            (normal if is_norm[i] else tumor).append(f)
        yield sym, st, tumor, normal


def build_spliceseq_psi_table(local_dir: Optional[str] = None, tissues: Optional[list] = None):
    """Materialize the gene-sorted per-(gene, indication) splicing-summary product from the 33
    per-tissue SpliceSeq PSI files. For each tissue: accumulate per-(gene) event stats (per-event
    tumour-PSI std + tumour/normal median shift), then roll up to per-(gene, tissue) rows AND the
    composite indications (COADREAD, NSCLC, AML). Gene-sorted output.

    local_dir: dir of extracted/zipped PSI files (tests / avoid re-download); else streams S3."""
    from collections import defaultdict

    import numpy as np
    import pyarrow as pa

    tissues = tissues or sorted({t for s in _INDICATION_TISSUE.values() for t in s})

    # per (tissue, gene) -> list of per-event dicts {st, tstd, shift(None if no normals)}
    by_tissue_gene: dict = defaultdict(lambda: defaultdict(list))
    tissue_counts: dict = {}  # tissue -> (n_tumor, n_normal)

    for tissue in tissues:
        stream = _open_tissue(tissue, local_dir)
        if stream is None:
            continue
        fh, n_tumor, n_normal = stream
        tissue_counts[tissue] = (n_tumor, n_normal)
        for sym, st, tumor, normal in _iter_tissue_events(fh):
            tstd = float(np.std(tumor)) if len(tumor) >= 2 else 0.0
            shift = None
            if normal:
                shift = abs(float(np.median(tumor)) - float(np.median(normal))) if tumor else None
            by_tissue_gene[tissue][sym].append({"st": st, "tstd": tstd, "shift": shift})
        fh.close()

    rows = []
    # per-tissue rows
    for tissue, genes in by_tissue_gene.items():
        n_tumor, n_normal = tissue_counts.get(tissue, (0, 0))
        for sym, events in genes.items():
            rows.append(_summarize(sym, tissue, events, n_tumor, n_normal))
    # composite-indication rows (merge the member tissues' event lists)
    for comp, members in _COMPOSITE_INDICATIONS.items():
        merged_genes: dict = defaultdict(list)
        n_tumor = n_normal = 0
        for tissue in members:
            n_t, n_n = tissue_counts.get(tissue, (0, 0))
            n_tumor += n_t
            n_normal += n_n
            for sym, events in by_tissue_gene.get(tissue, {}).items():
                merged_genes[sym].extend(events)
        for sym, events in merged_genes.items():
            rows.append(_summarize(sym, comp, events, n_tumor, n_normal))

    rows.sort(key=lambda r: (r["gene_symbol"], r["indication"]))  # gene-keyed physical sort
    return pa.Table.from_pylist(rows, schema=_schema())


def _summarize(sym: str, indication: str, events: list, n_tumor: int, n_normal: int) -> dict:
    import numpy as np

    stds = [e["tstd"] for e in events]
    shifts = [e["shift"] for e in events if e["shift"] is not None]
    n_variable = sum(1 for s in stds if s >= _STD_VARIABLE)
    n_shifted = sum(1 for s in shifts if s >= _SHIFT) if n_normal > 0 else None
    dom = max(events, key=lambda e: e["tstd"]) if events else None
    return {
        "gene_symbol": sym,
        "indication": indication,
        "splicing_dysregulation_class": _classify(n_variable, n_shifted, len(events)),
        "n_splice_events": len(events),
        "max_event_psi_std": float(max(stds)) if stds else None,
        "median_event_psi_std": float(np.median(stds)) if stds else None,
        "n_variable_events": n_variable,
        "n_tumor_shifted_events": n_shifted,
        "dominant_event_splice_type": dom["st"] if dom else None,
        "n_tumor_samples": int(n_tumor),
        "n_normal_samples": int(n_normal),
    }


def _open_tissue(tissue: str, local_dir: Optional[str]):
    """Return (text_stream, n_tumor_cols, n_normal_cols) for a tissue, or None if missing.
    Reads a local .zip/.txt if local_dir given, else the S3 snapshot zip."""
    import glob

    raw = None
    if local_dir:
        # accept PSI_download_<T>.zip or .txt
        z = glob.glob(os.path.join(local_dir, f"PSI_download_{tissue}.zip"))
        t = glob.glob(os.path.join(local_dir, f"PSI_download_{tissue}.txt"))
        if z:
            raw = open(z[0], "rb").read()
        elif t:
            fh = open(t[0], "r")
            header = _peek_header(t[0])
            return fh, header[0], header[1]
        else:
            return None
    else:
        ensure_aws_profile()
        key = f"{SPLICESEQ_SOURCE_PREFIX}/{_snapshot_dir()}/PSI_download_{tissue}.zip"
        try:
            raw = _boto3().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
        except Exception:  # absence-discipline: exempt -- build-time per-tissue materialization; a missing/unreadable tissue zip is skipped by the aggregator (build_spliceseq_table), not a card-facing read
            return None
    zf = zipfile.ZipFile(io.BytesIO(raw))
    inner = next(n for n in zf.namelist() if n.startswith(f"PSI_download_{tissue}"))
    fh = io.TextIOWrapper(zf.open(inner), encoding="utf-8", errors="replace")
    # peek header for counts without consuming (re-open a second handle)
    hz = zipfile.ZipFile(io.BytesIO(raw))
    with io.TextIOWrapper(hz.open(inner), encoding="utf-8", errors="replace") as hh:
        header = hh.readline().rstrip("\n").split("\t")
    sample_cols = header[10:]
    n_norm = sum(1 for c in sample_cols if c.endswith("_Norm"))
    return fh, len(sample_cols) - n_norm, n_norm


def _peek_header(path: str):
    with open(path) as fh:
        header = fh.readline().rstrip("\n").split("\t")
    sample_cols = header[10:]
    n_norm = sum(1 for c in sample_cols if c.endswith("_Norm"))
    return len(sample_cols) - n_norm, n_norm


@lru_cache(maxsize=1)
def _snapshot_dir() -> str:
    """Resolve the snapshot subdir under the source prefix via the source manifest, else newest S3."""
    try:
        from onc_methods.catalog_query.read import load_manifest

        m = load_manifest("tcga-spliceseq-v2")
        uri = m.get("s3_uri", "")
        # s3://bucket/.../tcga-spliceseq/<dir>/  -> <dir>
        parts = uri.rstrip("/").split("/")
        if "tcga-spliceseq" in parts:
            return parts[parts.index("tcga-spliceseq") + 1]
    except Exception:  # noqa: BLE001
        pass
    # fallback: list the prefix and take the lexically-max snapshot dir
    ensure_aws_profile()
    resp = _boto3().list_objects_v2(Bucket=S3_BUCKET, Prefix=f"{SPLICESEQ_SOURCE_PREFIX}/", Delimiter="/")
    dirs = [p["Prefix"].rstrip("/").split("/")[-1] for p in resp.get("CommonPrefixes", [])]
    return sorted(dirs)[-1] if dirs else "v2-snapshot"


def _schema():
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("indication", pa.string()),
            pa.field("splicing_dysregulation_class", pa.string()),
            pa.field("n_splice_events", pa.int64()),
            pa.field("max_event_psi_std", pa.float64()),
            pa.field("median_event_psi_std", pa.float64()),
            pa.field("n_variable_events", pa.int64()),
            pa.field("n_tumor_shifted_events", pa.int64()),
            pa.field("dominant_event_splice_type", pa.string()),
            pa.field("n_tumor_samples", pa.int64()),
            pa.field("n_normal_samples", pa.int64()),
        ]
    )
