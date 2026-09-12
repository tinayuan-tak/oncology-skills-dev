"""tcga_gtex_tpm_quantiles.marrow — PRIMARY bone-marrow RNA for the therapeutic-window denominator.

Why this module exists (2026-09-12 substrate audit; window.py finding #1). The window scorer's
essential-organ denominator is a max over GTEx `group` labels in tcga-gtex-tpm-tissue-quantiles-v1.
One of those labels is not a tissue: recount3's GTEx `BONE_MARROW` is the **K-562 erythroleukemia
cell line**, not primary marrow. Measured on the full product:

    marker            GTEx BONE_MARROW (K-562)    HPA consensus bone marrow
    ELANE                              0.06                        3672.00
    MPO                                1.98                        3249.50
    LTF                                0.23                        4021.00
    CAMP                               0.08                        2752.00
    DEFA4                              0.00                        2547.50
    HBG1                          11161.61                            0.30   <- the tell

Every primary neutrophil/granulocyte marker is ~0 while fetal haemoglobin is five orders of
magnitude high. Spearman(K-562, primary marrow) = 0.503 over 13,292 shared genes, with 1,942 genes
>=4x higher in primary marrow — a different biology, not a scale offset. The consequence was
twofold: (a) that label was the essential argmax for **24.2%** of expressed genes, so ~1 gene in 4
had its safety denominator set by a leukaemia line, and (b) the real, dose-limiting marrow
liabilities were INVISIBLE (CD33 / CLEC12A / IL3RA / FLT3 all read ~0 in K-562).

So the marrow slot is REPOINTED here rather than dropped — dropping it would silently delete
myelosuppression, the dose-limiting toxicity for cytotoxic-payload ADCs and for myeloid TCEs, from
the only denominator that gates BiTE/TCE/CAR window calls.

## Substrate choice

`hpa-rna-tissue-consensus-v25-1` (HPA v25.1 consensus per-tissue nTPM; HPA's own reconciliation of
its IHC-paired RNA-seq with GTEx and FANTOM5), tissue label `bone marrow`. Chosen over
`sc-pseudobulk-normal-celltype-bone-marrow-v1` because that product's unit is
`log1p(normalized * 1e4)` mean-of-log CP10K, which cannot enter a max-of-linear-TPM without a
fabricated conversion; HPA nTPM is the same TPM family as the product's recount3 TPM.

## Cross-platform normalization (measured, DOCUMENTED, deliberately NOT applied)

Median(HPA nTPM / GTEx TPM) per gene over 20 tissues present in both vocabularies:

    median 1.188   range 0.753 (testis) .. 2.883 (heart)   median Spearman 0.849

The offset is well inside the window class boundaries (narrow 1x / clean 5x), and no single
coefficient is defensible across a 0.75-2.88 per-tissue spread, so the marrow value is used AS
MEASURED. The residual bias is ~1.2x HIGH, which inflates the denominator — i.e. it errs toward
declaring a marrow liability, the conservative direction for a safety gate. `MARROW_PLATFORM_OFFSET_MEDIAN`
is emitted as provenance so a reader can see the un-applied factor rather than infer none exists.

## Coverage

HPA consensus carries 20,151 gene symbols (protein-coding); the quantiles product carries 41,379
including antisense/pseudogene/lncRNA loci. Absence is therefore EXPECTED for non-coding loci and is
reported as a distinct, definitive state (`gene_absent_from_hpa_consensus`) — never conflated with a
transient read failure (`unavailable`) and never silently scored as marrow == 0.
"""

from __future__ import annotations

import threading
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for

DEFAULT_AWS_PROFILE = "cbg"
MANIFEST_ID = "hpa-rna-tissue-consensus-v25-1"
SOURCE_FILENAME = "rna_tissue_consensus.tsv.zip"
HPA_TISSUE_LABEL = "bone marrow"

# Provenance token emitted on max_essential_normal_organ when marrow sets the denominator. Deliberately
# NOT the bare GTEx group name `BONE_MARROW` — a reader must be able to tell the repointed primary-marrow
# value apart from the discredited cell-line label in any archived run.
MARROW_ORGAN_LABEL = "BONE_MARROW_PRIMARY"
MARROW_SUBSTRATE_ID = f"{MANIFEST_ID}:{HPA_TISSUE_LABEL}"
MARROW_PLATFORM_OFFSET_MEDIAN = 1.19  # measured HPA/GTEx; see module docstring — NOT applied

# substrate states (emitted verbatim as the window scorer's `marrow_substrate`)
SUBSTRATE_PRIMARY = "hpa_primary_marrow"
SUBSTRATE_GENE_ABSENT = "gene_absent_from_hpa_consensus"
SUBSTRATE_UNAVAILABLE = "unavailable"

_LOCK = threading.Lock()
_TABLE: Optional[dict] = None
_LOAD_ERROR: Optional[str] = None


def _load() -> None:
    """Populate the module-level symbol -> marrow nTPM table (once per process).

    On failure leaves `_TABLE` None and records `_LOAD_ERROR`, so the caller can report an HONEST
    `unavailable` substrate instead of a fabricated marrow == 0 (which would read as a clean window).
    """
    global _TABLE, _LOAD_ERROR
    import io

    import boto3
    import pandas as pd

    try:
        # manifest resolution is inside the try on purpose: a missing/renamed manifest must degrade
        # to `unavailable` exactly like a network failure, never raise through the card dispatcher.
        bucket, prefix = bucket_prefix_for(MANIFEST_ID)
        key = f"{prefix}{SOURCE_FILENAME}"
        s3 = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        df = pd.read_csv(
            io.BytesIO(body),
            sep="\t",
            compression="zip",
            usecols=["Gene name", "Tissue", "nTPM"],
        )
    except Exception as exc:  # noqa: BLE001 — any read failure must degrade to `unavailable`, not 0
        _LOAD_ERROR = f"{type(exc).__name__}: {exc}"
        _TABLE = None
        return
    bm = df[df["Tissue"] == HPA_TISSUE_LABEL]
    if bm.empty:
        _LOAD_ERROR = (
            f"{MANIFEST_ID} carries no `{HPA_TISSUE_LABEL}` rows "
            f"(tissue vocabulary changed upstream?) — marrow denominator withheld"
        )
        _TABLE = None
        return
    # a symbol may map to >1 Ensembl gene id; take the MAX (conservative for a safety denominator)
    _TABLE = {
        str(k).upper().strip(): float(v)
        for k, v in bm.groupby("Gene name")["nTPM"].max().items()
        if v == v  # drop NaN
    }
    _LOAD_ERROR = None


def primary_marrow_tpm(symbol: str) -> tuple[Optional[float], str, Optional[str]]:
    """Primary bone-marrow expression for one gene symbol, in nTPM (TPM-family; see module docstring).

    Returns `(tpm, substrate, note)`:
      (float, "hpa_primary_marrow", None)              — value found
      (None,  "gene_absent_from_hpa_consensus", note)  — DEFINITIVE absence (non-coding locus, etc.)
      (None,  "unavailable", note)                     — TRANSIENT: substrate could not be read
    """
    global _TABLE
    with _LOCK:
        if _TABLE is None and _LOAD_ERROR is None:
            _load()
        table, err = _TABLE, _LOAD_ERROR
    if table is None:
        return None, SUBSTRATE_UNAVAILABLE, f"primary-marrow substrate unavailable ({err})"
    val = table.get(str(symbol).upper().strip())
    if val is None:
        return (
            None,
            SUBSTRATE_GENE_ABSENT,
            f"{symbol} is not in {MANIFEST_ID} (protein-coding only; "
            f"marrow excluded from the essential denominator for this gene)",
        )
    return val, SUBSTRATE_PRIMARY, None


def _reset_cache_for_tests() -> None:
    """Clear the process-level substrate cache (tests inject their own table)."""
    global _TABLE, _LOAD_ERROR
    with _LOCK:
        _TABLE = None
        _LOAD_ERROR = None
