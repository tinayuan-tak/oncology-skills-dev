"""depmap_protein_abundance.cli — cell-line protein-abundance distribution + classifier.

The PROTEIN twin of depmap_expression_distribution. Reads the DepMap 26Q1
proteomics Gygi Lab CCLE TMT MS matrix (harmonized_MS_CCLE_Gygi.csv — a
ModelID x UniProt-accession whole-proteome matrix, ~12,558 proteins) and reports
the per-target abundance distribution across cell lines + a per-lineage breakdown.

Emits the `cellline-protein-abundance` card contract fields, primary categorical
`protein_expression_class` ∈ {broadly_high | broadly_moderate | lineage_restricted
| sub_broad_detection | broadly_low | data_unavailable} — the cellline-rna-distribution
distribution vocab PLUS `sub_broad_detection` (NOT the tumor-vs-normal contrast vocab
of tumor-protein-abundance-cptac).

`sub_broad_detection` is the one token this vocab has that the RNA sibling's does not,
and the asymmetry is load-bearing rather than drift: the RNA axis always has a lineage
stratification, so its middle band can fall through to broadly_moderate on a MEASURED
zero (depmap_expression_distribution:352-362). This classifier is shared with the ProCan
reader, whose Sanger SIDM ids have no OncotreeLineage crosswalk, so its stratification is
structurally ABSENT — a case the RNA axis cannot reach and therefore never needed a token
for. See classify_protein_abundance.

Two resolution jobs (both via already-landed catalog artifacts):
  1. target symbol → UniProt accession (the matrix COLUMN) via the source's
     target_resolution sidecar (`native_row_key` = accession,
     `hgnc_primary_symbol_at_resolution` = symbol). Same convention as the
     topology reader — the payload has no symbol column.
  2. ModelID (the matrix ROW) → OncotreeLineage via Model.csv, for the per-lineage
     groupby (read-side, cheap — proteomics is per-ModelID at read time).

MS detection is sparse (shotgun TMT under-samples membrane/low-abundance proteins),
so `fraction_detected` is a first-class signal and `broadly_low` keys off detection
fraction, not just abundance magnitude. A protein absent from the matrix →
`data_unavailable` (coverage gap, NOT a measured negative).
"""

from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from onc_methods.catalog_query.read import bucket_prefix_for

# Canonical indication → DepMap OncotreeLineage map (single source of truth in
# depmap_chronos.cli). Imported here as INDICATION_LINEAGE — do NOT re-fork it
# (guarded by tests/methods/depmap_chronos/test_lineage_map_single_source.py).
# NB: the prior in-module fork carried "OV": "Ovary", a value that does NOT exist
# in DepMap 26Q1 Model.csv (the real lineage is "Ovary/Fallopian Tube"), so the
# ovarian highlight never matched — the canonical map corrects this.
from onc_methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE as INDICATION_LINEAGE

METHOD_VERSION = "0.1.0"

# bucket + source-dir prefixes resolved from the data-catalog manifests (single
# source of truth); MATRIX_KEY + resolver SIDECAR ride off the proteomics prefix.
PROT_SOURCE_MANIFEST_ID = "depmap-consortium-26q1-proteomics"
S3_BUCKET, _PROT_PREFIX = bucket_prefix_for(PROT_SOURCE_MANIFEST_ID)
_PROT_PREFIX = _PROT_PREFIX.rstrip("/")
MATRIX_KEY = f"{_PROT_PREFIX}/harmonized_MS_CCLE_Gygi.csv"
SIDECAR_KEY = f"{_PROT_PREFIX}/harmonized_MS_CCLE_Gygi.csv.target_resolution.parquet"
# Olink FALLBACK (Track C): antibody-NPX proteomics, UniProt-accession cols × ModelID rows (same shape
# as Gygi). Covers surface/secreted antigens the Gygi MS panel misses (MSLN/MUC16/CLDN18…). Its
# symbol→UniProt resolution uses the GENERAL uniprot_hugo mapping (NOT the Gygi-only target_resolution
# sidecar, which cannot resolve a non-Gygi symbol).
OLINK_MATRIX_KEY = f"{_PROT_PREFIX}/harmonized_Olink_2023_best_dilution_v2.csv"
_UNIPROT_MAP_KEY = f"{_PROT_PREFIX}/uniprot_hugo_entrez_id_mapping_26q1.csv"
# Model.csv (ModelID -> OncotreeLineage) lives in the sister RNA/omics source.
_MODEL_PREFIX = bucket_prefix_for("depmap-consortium-26q1")[1].rstrip("/")
MODEL_KEY = f"{_MODEL_PREFIX}/Model.csv"
DEFAULT_AWS_PROFILE = "cbg"

# DERIVED long/tidy pushdown product (parquet-storage-standard, 2026-08-21): replaces the
# whole-wide-CSV read of harmonized_MS_CCLE_Gygi.csv on the LIVE Gygi path. Per-protein pushdown
# (filters=[("uniprot_base","=",accession)]) reads ~1 row group instead of 64 MB; the all-gene
# median null is a precomputed co-located sidecar. Byte-identical summaries to the wide-CSV path.
# The wide-CSV code below is PRESERVED for the offline test seam (matrix_path=) and the Olink
# fallback (matrix_key=OLINK_MATRIX_KEY), which stay on CSV.
DERIVED_PRODUCT_MANIFEST_ID = "depmap-gygi-protein-abundance-per-protein-v1"

# --- card thresholds (mirror cellline-protein-abundance.card.yaml) ---
BROADLY_DETECTED_FRACTION = 0.70  # detected in >70% of panel
LOW_DETECTION_FRACTION = 0.30  # detected in <30% → broadly_low
LINEAGE_RESTRICTED_MIN = 0.10
LINEAGE_RESTRICTED_MAX = 0.70
HIGH_ABUNDANCE_PERCENTILE = 0.70  # see the TWO-POPULATIONS warning below before reusing this
# ⚠️ HIGH_ABUNDANCE_PERCENTILE is applied to TWO DIFFERENT DISTRIBUTIONS in this module. They are not
# two calibrations of one quantity and must not be substituted for each other (#2223):
#   1. CLASSIFICATION (compute_summary, below): p70 of the panel medians of ALL ~12.6k proteins in the
#      Gygi matrix — a CROSS-PROTEIN rank. This is the only one that decides `broadly_high`.
#   2. DISPLAY ONLY (_panel_high_cutoff): p70 of THE TARGET'S OWN detected per-cell-line values — a
#      WITHIN-TARGET rank, which by construction always leaves ~30% of the plotted points above it.
# Measured on DepMap 26Q1 (375 lines x 12558 proteins, #2223): (1) sits at +0.000316 log2 while the
# median within-protein spread across cell lines is 0.79 log2, and dropping a single OncotreeLineage
# moves it by up to 0.0073 — see the adjudication on #2223 and
# tests/fixtures/gygi_panel_composition_flip_matrix.json. NOTHING here is changed by that record; it
# is the evidence an axis decision will be made on.
MIN_LINEAGE_SIZE = 5
# Middle-band (LOW..BROADLY detection) disambiguation: a protein is genuinely
# lineage_restricted only if its detected lines CLUSTER in a minority of lineages;
# a protein detected at a moderate rate ACROSS many lineages is broadly_moderate.
LINEAGE_CONCENTRATION_MAX_LINEAGES = 3  # detected in <= this many lineages → concentrated
LINEAGE_CONCENTRATION_TOP_SHARE = 0.50  # one lineage holds >= this share of detected lines → concentrated


from onc_methods.target_id_sidecar import s3_client


def _prot_s3_filesystem():
    """pyarrow S3FileSystem sharing target_id_sidecar.s3_client()'s preferred-profile→ambient-chain
    fallback (the protein-arm parquet pushdown + null-sidecar reader).

    pyarrow's S3FileSystem honors AWS_PROFILE, so a bare construction raised ProfileNotFound in
    CI/prod/instance-role where the `cbg` developer profile is absent (AWS_PROFILE unset there, and
    the former ensure_aws_profile() setdefault installed `cbg`) — the same latent break s3_client
    fixed for the boto3 arm. Resolve credentials through a boto3 Session (which owns the fallback),
    then hand the frozen credentials to pyarrow so the two clients authenticate identically. When no
    credentials resolve, defer to pyarrow's own default provider chain (unchanged bare behavior)."""
    import boto3
    import pyarrow.fs as pafs
    from botocore.exceptions import ProfileNotFound

    prof = os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    try:
        session = boto3.Session(profile_name=prof)
    except ProfileNotFound:
        # Preferred/default profile absent (CI / prod / instance-role): use the ambient chain. A bare
        # Session() still reads AWS_PROFILE from the env, so strip the bad value first (restored after).
        saved = os.environ.pop("AWS_PROFILE", None)
        try:
            session = boto3.Session()
        finally:
            if saved is not None:
                os.environ["AWS_PROFILE"] = saved
    creds = session.get_credentials()
    if creds is None:
        return pafs.S3FileSystem()
    frozen = creds.get_frozen_credentials()
    return pafs.S3FileSystem(access_key=frozen.access_key, secret_key=frozen.secret_key, session_token=frozen.token)


@lru_cache(maxsize=8)
def _cached_csv(path_or_none, bucket, key):
    """Read a CSV substrate (whole file) ONCE per (path/key) per process (retrieval-opt #3).

    The Gygi MS matrix + Model.csv are large and target-INDEPENDENT — the summary pass and the
    figure pass both read them in full, so without caching one card did ≥2 full reads (the review
    measured the Gygi CSV read twice + Model.csv twice, uncached). Keyed on the identity args only
    (no **kw), so callers must not pass read_csv kwargs through this path — the two large substrates
    here need none. Returns the SHARED DataFrame; callers treat it read-only (they select columns /
    filter, never mutate in place)."""
    import pandas as pd

    if path_or_none is not None:
        return pd.read_csv(path_or_none)
    body = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_csv(io.BytesIO(body))


def _read_csv(path_or_none, bucket, key, **kw):
    import pandas as pd

    # Uncached path preserved for callers that pass read_csv kwargs (e.g. usecols/dtype); the two
    # large target-independent substrates (matrix, Model.csv) go through _cached_csv instead.
    if kw:
        if path_or_none is not None:
            return pd.read_csv(path_or_none, **kw)
        body = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
        return pd.read_csv(io.BytesIO(body), **kw)
    return _cached_csv(path_or_none, bucket, key)


@lru_cache(maxsize=8)
def _read_parquet(path_or_none, bucket, key):
    """Read a parquet substrate (whole file) ONCE per (path/key) per process (retrieval-opt #3).
    The Gygi target_resolution sidecar is read by resolve_accession on both the summary + figure
    pass; caching removes the duplicate read. Returned frame is treated read-only by callers."""
    import pandas as pd

    if path_or_none is not None:
        return pd.read_parquet(path_or_none)
    body = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


@lru_cache(maxsize=1)
def _derived_bucket_key() -> tuple:
    """(bucket, key) of the derived long-parquet payload, resolved from the manifest (never hard-coded)."""
    from onc_methods.catalog_query.read import bucket_key_for

    return bucket_key_for(DERIVED_PRODUCT_MANIFEST_ID)


@lru_cache(maxsize=1)
def _derived_manifest() -> dict:
    from onc_methods.catalog_query.read import load_manifest

    return load_manifest(DERIVED_PRODUCT_MANIFEST_ID)


@lru_cache(maxsize=1)
def _derived_panel_size() -> Optional[int]:
    """Total MS cell lines (detection denominator) — a release constant carried in manifest params
    (NOT recoverable from the detected-only long table)."""
    v = (_derived_manifest().get("parameters", {}) or {}).get("panel_size_n_cell_lines")
    return int(v) if v is not None else None


def _select_abundance_from_table(tbl, accession: str, panel_size) -> tuple:
    """Post-read selection shared by the live + offline paths. `tbl` is a pyarrow Table of the rows
    for one uniprot_base. Returns (abundance_by_model | None, panel_size)."""
    if tbl.num_rows == 0:
        return None, panel_size  # accession not in the Gygi panel -> caller tries Olink fallback
    d = tbl.to_pydict()
    # 'first base-match column' semantics (parity with the wide-CSV load_abundance_column): if
    # isoform-suffixed variants share the base accession, deterministically pick the min uniprot_id.
    uids = sorted(set(d["uniprot_id"]))
    chosen = accession if accession in uids else uids[0]
    out = {m: float(v) for u, m, v in zip(d["uniprot_id"], d["model_id"], d["log2_abundance"]) if u == chosen}
    return (out or None), panel_size


def _load_gygi_abundance_pushdown(accession: str, product_path=None) -> tuple:
    """Gygi path: pushdown-read one protein's per-cell-line abundance from the derived long parquet.
    Returns (abundance_by_model | None, panel_size). `product_path` (offline test seam) reads a local
    parquet with the same filter; None => the live S3 product (cached per accession)."""
    import pyarrow.parquet as pq

    if product_path is not None:
        tbl = pq.read_table(str(product_path), filters=[("uniprot_base", "=", accession)])
        return _select_abundance_from_table(tbl, accession, _derived_panel_size())
    return _load_gygi_abundance_pushdown_live(accession)


@lru_cache(maxsize=128)
def _load_gygi_abundance_pushdown_live(accession: str) -> tuple:
    """LIVE S3 pushdown, cached per accession (a single small row-group slice). A transient failure
    RAISES and is NOT cached, so a later call retries — lru_cache never memoizes exceptions."""
    import pyarrow.parquet as pq

    bucket, key = _derived_bucket_key()
    tbl = pq.read_table(f"{bucket}/{key}", filesystem=_prot_s3_filesystem(), filters=[("uniprot_base", "=", accession)])
    return _select_abundance_from_table(tbl, accession, _derived_panel_size())


def _load_allgene_null_sidecar(null_path=None) -> tuple:
    """All-protein median null: read the precomputed sidecar (one median per raw protein column) in
    full. `null_path` (offline test seam) reads a local parquet; None => the live co-located S3 sidecar
    (cached). Returns a hashable tuple of medians."""
    import pyarrow.parquet as pq

    if null_path is not None:
        tbl = pq.read_table(str(null_path), columns=["median_log2_abundance"])
        return tuple(float(x) for x in tbl.to_pydict()["median_log2_abundance"])
    return _load_allgene_null_sidecar_live()


@lru_cache(maxsize=1)
def _load_allgene_null_sidecar_live() -> tuple:
    import pyarrow.parquet as pq

    bucket, key = _derived_bucket_key()
    null_file = (_derived_manifest().get("parameters", {}) or {}).get(
        "null_sidecar_file", "depmap_gygi_protein_abundance.allgene_null.parquet"
    )
    null_key = key.rsplit("/", 1)[0] + "/" + null_file
    tbl = pq.read_table(f"{bucket}/{null_key}", filesystem=_prot_s3_filesystem(), columns=["median_log2_abundance"])
    return tuple(float(x) for x in tbl.to_pydict()["median_log2_abundance"])


def resolve_accession(target: str, sidecar_path=None) -> Optional[str]:
    """target (HGNC symbol) → UniProt accession (matrix column) via the sidecar.

    The Gygi matrix columns are UniProt accessions (native_row_key); the payload
    carries no symbol column, so we MUST join via the sidecar (same discipline as
    the topology reader)."""
    df = _read_parquet(sidecar_path, S3_BUCKET, SIDECAR_KEY)
    sym = target.strip().upper()
    col = "hgnc_primary_symbol_at_resolution"
    if col not in df.columns or "native_row_key" not in df.columns:
        # SCHEMA DRIFT (or a mis-described/unreadable sidecar), NOT a genuine symbol-absence: a
        # well-formed sidecar always carries these columns. Returning None here would silently mask a
        # broken product as "symbol not resolvable" for EVERY target. Raise so the read.py dispatcher
        # surfaces an honest _live_read_error instead of a framework-wide silent data_unavailable.
        raise ValueError(
            f"Gygi target_resolution sidecar s3://{S3_BUCKET}/{SIDECAR_KEY} missing expected columns "
            f"{col!r}/'native_row_key' (present: {list(df.columns)[:10]}) — schema drift"
        )
    hit = df[df[col].astype(str).str.upper() == sym]
    if not len(hit):
        return None  # symbol not in a WELL-FORMED sidecar → genuine data_unavailable (honest None)
    val = hit.iloc[0]["native_row_key"]
    return str(val) if val is not None and str(val) != "nan" else None


def load_abundance_column(accession: str, matrix_path=None, matrix_key: str = MATRIX_KEY):
    """Return (abundance_by_model, panel_size) for the protein column.

    abundance_by_model = {ModelID: log2_abundance} dropping NaNs (undetected);
    panel_size = total ModelID rows in the matrix (the detection denominator).
    The matrix is ModelID-rows x accession-cols; the first column is the ModelID
    (ACH-*). Returns (None, panel_size) if the accession is absent from the matrix.
    Single read of the matrix (panel size + column come from the same load).
    `matrix_key` selects the source matrix (default Gygi MS; OLINK_MATRIX_KEY for the fallback) —
    both share the ModelID-rows × UniProt-accession-cols shape, so the same column logic applies."""
    # LIVE Gygi path -> derived long parquet via column-pushdown (parquet-storage-standard). A local
    # matrix_path (offline tests) or a non-Gygi matrix_key (Olink fallback) keep the wide-CSV path below.
    if matrix_path is None and matrix_key == MATRIX_KEY:
        return _load_gygi_abundance_pushdown(accession)
    import pandas as pd

    df = _read_csv(matrix_path, S3_BUCKET, matrix_key)
    id_col = df.columns[0]  # unnamed index col holding ACH-* ids
    panel_size = len(df)
    # accession columns may be isoform-suffixed (e.g. Q8WY21-3); prefer the exact
    # canonical accession, else the first column whose base (pre-'-') matches.
    cols = [c for c in df.columns if c != id_col]
    if accession in cols:
        target_col = accession
    else:
        base_matches = [c for c in cols if str(c).split("-")[0] == accession]
        if not base_matches:
            return None, panel_size
        target_col = base_matches[0]
    out = {}
    for _, row in df[[id_col, target_col]].iterrows():
        v = row[target_col]
        if v is not None and pd.notna(v):
            out[str(row[id_col])] = float(v)
    return out, panel_size


import functools

from onc_methods.roots import contracts_root


@functools.lru_cache(maxsize=1)
def _symbol_to_uniprot_map() -> dict:
    """HGNC symbol (upper) -> [UniprotID,...] from the GENERAL uniprot_hugo mapping in the proteomics
    prefix. NOT the Gygi target_resolution sidecar (which only covers Gygi-present symbols) — this
    resolves surface/secreted antigens the Gygi panel misses, so the Olink fallback can find them.
    {} on any failure (fallback then degrades to data_unavailable — honest)."""
    try:
        df = _read_csv(None, S3_BUCKET, _UNIPROT_MAP_KEY)
    except Exception:  # noqa: BLE001
        return {}
    if "Symbol" not in df.columns or "UniprotID" not in df.columns:
        return {}
    m: dict = {}
    for sym, acc in zip(df["Symbol"], df["UniprotID"]):
        if isinstance(sym, str) and isinstance(acc, str):
            m.setdefault(sym.strip().upper(), []).append(acc.strip())
    return m


def load_olink_abundance_column(symbol: str):
    """Olink-NPX FALLBACK: (abundance_by_model, panel_size, accession_used) for a target absent from the
    Gygi MS panel. Resolves symbol→UniProt via the general mapping, then reads the Olink matrix column
    (ModelID-rows × UniProt-cols) via load_abundance_column. Tries each mapped accession; returns the
    first with data. (None, panel_size, None) when the symbol/accession is not Olink-measured."""
    uniprots = _symbol_to_uniprot_map().get(symbol.strip().upper()) or []
    panel_size = 0
    for acc in uniprots:
        col, panel_size = load_abundance_column(acc, matrix_key=OLINK_MATRIX_KEY)
        if col:
            return col, panel_size, acc
    return None, panel_size, None


def load_model_lineage(model_path=None) -> dict:
    """ModelID → OncotreeLineage from Model.csv."""
    df = _read_csv(model_path, S3_BUCKET, MODEL_KEY)
    id_col = "ModelID" if "ModelID" in df.columns else df.columns[0]
    lin_col = "OncotreeLineage" if "OncotreeLineage" in df.columns else None
    if lin_col is None:
        return {}
    return {
        str(r[id_col]): (str(r[lin_col]) if r[lin_col] is not None else None)
        for _, r in df[[id_col, lin_col]].iterrows()
    }


def classify_protein_abundance(
    fraction_detected: float, median_abundance: Optional[float], per_lineage: list, high_cutoff: Optional[float]
) -> str:
    """Distribution vocab (mirrors cellline-rna-distribution's expression_class).

    - broadly_low:        detected in < LOW_DETECTION_FRACTION of the panel with no concentrated
                          lineage signal (MS-absent), OR below LINEAGE_RESTRICTED_MIN (too sparse
                          to call restriction) regardless of concentration
    - broadly_high:       detected in > BROADLY_DETECTED_FRACTION AND median >= panel high cutoff
    - broadly_moderate:   detected broadly (> BROADLY_DETECTED_FRACTION and not high), OR
                          detected in the middle band and MEASURED to be spread across many lineages
    - lineage_restricted: detection in [LINEAGE_RESTRICTED_MIN, LINEAGE_RESTRICTED_MAX] CONCENTRATED
                          in a minority of lineages (consulting per_lineage) — INCLUDING the
                          low-detection sub-band [MIN, LOW_DETECTION_FRACTION): a protein detected
                          in a minority of the pan-cancer panel but clustered in a few lineages is
                          lineage-restricted (a therapeutic-window antigen, e.g. CLDN18), NOT absent
    - sub_broad_detection: detection in [LOW_DETECTION_FRACTION, LINEAGE_RESTRICTED_MAX] with NO
                          per-lineage breakdown available. A DETECTION-BAND statement only, making no
                          lineage claim in either direction — the honest label when the evidence that
                          would separate lineage_restricted from broadly_moderate was never measured
    - data_unavailable:   handled upstream (protein absent from matrix)

    The lineage tokens are claims about lineage; they require per_lineage to be non-empty. Absence of
    the stratification routes to sub_broad_detection (middle band) or broadly_low (low sub-band),
    never to a lineage claim.
    """
    f = fraction_detected
    if f > BROADLY_DETECTED_FRACTION:
        if high_cutoff is not None and median_abundance is not None and median_abundance >= high_cutoff:
            return "broadly_high"
        return "broadly_moderate"
    # Sub-broad band. `lineage_restricted` (concentrated in few lineages) is the correct call for a
    # protein detected in a MINORITY of the pan-cancer panel when the detection clusters in a few
    # lineages — whole-cell shotgun TMT under-samples membrane/low-copy antigens, so a low overall
    # detection fraction is NOT evidence of absence for a genuinely lineage-restricted surface antigen
    # (CLDN18-class). This lineage-concentration check must run BEFORE the low-detection floor, or the
    # `f < LOW_DETECTION_FRACTION → broadly_low` short-circuit pre-empts the [MIN, LOW) band and fires a
    # spurious degrader-killer on exactly those antigens. Below LINEAGE_RESTRICTED_MIN the panel is too
    # sparse to assert restriction, so those fall through to broadly_low regardless of concentration.
    if LINEAGE_RESTRICTED_MIN <= f <= LINEAGE_RESTRICTED_MAX:
        # Both sub-bands require REAL per-lineage evidence before ANY lineage claim: we cannot assert
        # restriction from a detection fraction with no lineage breakdown. Below LOW_DETECTION_FRACTION
        # the fall-through is broadly_low (too sparse to assert anything); in the MIDDLE band it is the
        # lineage-UNTESTED band (see below).
        if f < LOW_DETECTION_FRACTION:
            if per_lineage and _is_lineage_concentrated(per_lineage):
                return "lineage_restricted"
            return "broadly_low"
        if not per_lineage:
            # LINEAGE UNTESTED — not lineage-restricted, and not broadly-moderate either.
            #
            # This branch previously fell to lineage_restricted via _is_lineage_concentrated([]) → True,
            # i.e. it asserted a mechanistic lineage claim from ZERO lineage evidence. ProCan reaches it
            # for every target (Sanger SIDM ids have no OncotreeLineage crosswalk, so the lineage map is
            # always {}), which made the claim vacuous rather than merely optimistic: measured across the
            # 504-package corpus, all 85 of 343 ProCan cards labelled lineage_restricted were EXACTLY the
            # 85 whose fraction_detected fell in this band (set identity, 0 in either difference), so the
            # concentration predicate contributed zero bits and broadly_moderate was unreachable.
            #
            # broadly_moderate is NOT the honest fall-through here: it asserts pan-lineage SPREAD, which
            # is equally unevidenced when the stratification is absent. (The RNA sibling
            # depmap_expression_distribution:352-362 does fall through to broadly_moderate, correctly —
            # there n_lineage_restricted == 0 is a MEASURED zero, not an absent measurement.) So emit the
            # detection band itself and make no lineage claim at all. Gygi carries a real lineage map, so
            # its labels are unchanged (0 of 419 corpus cards reach this branch).
            return "sub_broad_detection"
        if _is_lineage_concentrated(per_lineage):
            return "lineage_restricted"
        return "broadly_moderate"
    # f < LINEAGE_RESTRICTED_MIN → genuinely absent across the panel.
    return "broadly_low"


def _is_lineage_concentrated(per_lineage: list) -> bool:
    """Is the detected-line footprint concentrated in a minority of lineages?

    per_lineage entries carry {'lineage', 'n', ...} where n = detected lines in that lineage
    (lineages below MIN_LINEAGE_SIZE detected lines are already dropped upstream). Concentrated
    iff detection spans few lineages OR one lineage dominates the detected lines.

    An EMPTY breakdown (or one with no detected lines attributed) returns False, because the absence
    of a lineage stratification is not evidence of lineage concentration. This USED to return True —
    "fall back to the historical middle-band label so existing behavior is preserved" — which made the
    predicate unfalsifiable for every caller that never has a lineage map.

    False here means "not established as concentrated", NOT "established as spread". Callers must not
    read it as positive evidence of pan-lineage spread: that is why classify_protein_abundance tests
    `per_lineage` itself and emits the lineage-untested band rather than routing an unmeasured input
    to broadly_moderate.
    """
    if not per_lineage:
        return False
    total = sum(d.get("n", 0) for d in per_lineage)
    if total <= 0:
        return False
    if len(per_lineage) <= LINEAGE_CONCENTRATION_MAX_LINEAGES:
        return True
    top_share = max(d.get("n", 0) for d in per_lineage) / total
    return top_share >= LINEAGE_CONCENTRATION_TOP_SHARE


def _percentiles(values: list) -> dict:
    import statistics

    if not values:
        return {}
    s = sorted(values)

    def pct(p):
        if len(s) == 1:
            return s[0]
        idx = p * (len(s) - 1)
        lo = int(idx)
        frac = idx - lo
        if lo + 1 < len(s):
            return s[lo] * (1 - frac) + s[lo + 1] * frac
        return s[lo]

    return {
        "median": statistics.median(s),
        "p5": pct(0.05),
        "p25": pct(0.25),
        "p75": pct(0.75),
        "p95": pct(0.95),
    }


def _quantile(values: list, q: float) -> Optional[float]:
    """Linear-interpolated q-quantile of `values` (unsorted OK). None on empty input."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    idx = q * (len(s) - 1)
    lo = int(idx)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[min(lo + 1, len(s) - 1)] * frac


def compute_summary(
    target: str,
    abundance_by_model: Optional[dict],
    lineage_by_model: dict,
    n_panel: Optional[int] = None,
    all_protein_medians: Optional[tuple] = None,
) -> dict:
    """Build the cellline-protein-abundance card summary.

    all_protein_medians: the PANEL-WIDE null — every protein's median abundance across the Gygi
    matrix (from _all_protein_median_null). Required for the broadly_high class to be reachable
    (see the high_cutoff note below). The reader passes it; unit tests may pass a synthetic vector."""
    if abundance_by_model is None:
        return {
            "protein_expression_class": "data_unavailable",
            "protein_high_abundance_class_cutoff": None,
            "n_cell_lines_evaluated": 0,
            "n_cell_lines_in_panel": n_panel,
            "fraction_detected": 0.0,
            "median_log2_abundance_panel": None,
            "n_lineages_evaluated": 0,
            "per_lineage_stats": [],
            "n_lineage_restricted_lineages": 0,
            "method_version": METHOD_VERSION,
        }
    vals = list(abundance_by_model.values())
    n_eval = len(vals)
    # panel denominator: total MS lines. If not supplied, use n_eval (detection=1.0
    # would be wrong) — the reader passes the true panel size.
    denom = n_panel if (n_panel and n_panel > 0) else n_eval
    fraction_detected = (n_eval / denom) if denom else 0.0
    pcts = _percentiles(vals)
    median_abund = pcts.get("median")
    # HIGH cutoff for the broadly_high class. This MUST be a PANEL-WIDE (all-protein) reference, not
    # the target's OWN abundance spread. The prior code set high_cutoff = HIGH_ABUNDANCE_PERCENTILE
    # quantile of `vals` (this protein's own per-cell-line values), so broadly_high required
    # `median (p50) >= p70 of the same vector` — mathematically impossible, making broadly_high
    # UNREACHABLE (H3): every uniformly-abundant protein collapsed to broadly_moderate. The correct
    # question is "is this protein's median abundance in the top (1 - HIGH_ABUNDANCE_PERCENTILE) of
    # ALL proteins' medians?" — the same all-protein null already used for the display percentile
    # (target_allgene_percentile). When the null is unavailable (unit test / no matrix), high_cutoff
    # stays None and broadly_high honestly cannot fire (no panel to be "high" relative to).
    #
    # ⚠️ ADJUDICATED, NOT SETTLED (#2223). The H3 fix above is right about the POPULATION; what it
    # cannot fix is that the harmonized Gygi value is a per-protein-CENTRED TMT log2 ratio, so that
    # population is nearly degenerate. Measured on 26Q1 (375 lines x 12558 proteins): sd of the
    # per-protein medians 0.193 vs median within-protein sd 0.793 (ratio 0.24); this p70 lands at
    # +0.000316 log2; 10.5% of all proteins sit within +/-0.01 of it. Consequences, all measured:
    # dropping ONE OncotreeLineage moves 1.0-1.3k of 12558 broadly_high calls (8-10%), a random half
    # panel up to 17%, and ACTB (+0.0297 below GAPDH) lands `broadly_moderate` while GAPDH lands
    # `broadly_high` — the two entries tumor_presence_controls.yaml curates together as the
    # ubiquitously-high CEILING anchor. Choosing a different observable is a product decision and is
    # NOT made here; the evidence is tests/fixtures/gygi_panel_composition_flip_matrix.json.
    high_cutoff = _quantile(list(all_protein_medians), HIGH_ABUNDANCE_PERCENTILE) if all_protein_medians else None

    # per-lineage groupby
    by_lin: dict = {}
    for mid, v in abundance_by_model.items():
        lin = lineage_by_model.get(mid)
        if lin:
            by_lin.setdefault(lin, []).append(v)
    # detection per lineage needs the lineage panel size; approximate detected-only
    # here (lineage denominator = detected lines in that lineage in the MS matrix).
    per_lineage = []
    n_lineage_restricted = 0
    for lin, lv in by_lin.items():
        if len(lv) < MIN_LINEAGE_SIZE:
            continue
        import statistics

        per_lineage.append(
            {
                "lineage": lin,
                "n": len(lv),
                "median_log2_abundance": statistics.median(lv),
                # detection here is within-detected; a true fraction needs lineage panel
                # size (Model.csv total per lineage) — computed by the reader when it has
                # the full model table. Left as n for the card's descriptive table.
            }
        )
    per_lineage.sort(key=lambda d: d["median_log2_abundance"], reverse=True)

    klass = classify_protein_abundance(fraction_detected, median_abund, per_lineage, high_cutoff)
    return {
        "protein_expression_class": klass,
        # The all-protein p70 cutoff that DECIDED protein_expression_class above — carried on the
        # summary so the emitters (#2261) can draw the line that actually classified the target,
        # not just `_panel_high_cutoff`'s within-target spread quantile. None when the all-protein
        # null was unavailable (broadly_high was then honestly unreachable too — same condition).
        "protein_high_abundance_class_cutoff": high_cutoff,
        "n_cell_lines_evaluated": n_eval,
        "n_cell_lines_in_panel": denom,
        "fraction_detected": round(fraction_detected, 4),
        "median_log2_abundance_panel": median_abund,
        "p5_log2_abundance_panel": pcts.get("p5"),
        "p25_log2_abundance_panel": pcts.get("p25"),
        "p75_log2_abundance_panel": pcts.get("p75"),
        "p95_log2_abundance_panel": pcts.get("p95"),
        "log2_abundance_iqr": (pcts.get("p75") - pcts.get("p25"))
        if (pcts.get("p75") is not None and pcts.get("p25") is not None)
        else None,
        # protein_effect_size REMOVED (#1853): it duplicated median_log2_abundance_panel verbatim —
        # a field named for a tumor-vs-normal contrast a cell-line panel (no normal arm) cannot
        # compute. This compute_summary is shared with the ProCan sibling, so both cell-line cards
        # drop the field. (Unchanged on the tumor cards, where a real normal arm exists.)
        "n_lineages_evaluated": len(per_lineage),
        "per_lineage_stats": per_lineage,
        "n_lineage_restricted_lineages": n_lineage_restricted,
        "method_version": METHOD_VERSION,
    }


# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
DEFAULT_TARGET_CONTRACTS = Path(contracts_root())


def _load_takeda_style(target_contracts_dir: Path):
    """Load the Takeda mplstyle + palette module (mirror depmap_expression_distribution)."""

    import matplotlib.pyplot as plt

    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    from oncology_target_contracts.plot_styles import takeda_palette

    return takeda_palette


@lru_cache(maxsize=2)
def _all_protein_median_null(matrix_path=None) -> tuple:
    """Per-protein median-abundance vector across ALL proteins in the Gygi matrix —
    the all-gene null for the cellline-protein-abundance percentile.

    The matrix is WIDE (cell-lines × protein columns), so this is one column-median
    pass (axis=0) over the already-cached matrix. lru_cached (built once). Returned as
    a tuple so it stays hashable/cache-safe. Zero new I/O beyond the matrix read that
    load_abundance_column already does."""
    # LIVE path -> precomputed all-gene median-null sidecar (tiny; no whole-matrix scan). A local
    # matrix_path (offline tests) keeps the wide-matrix column-median pass below.
    if matrix_path is None:
        try:
            return _load_allgene_null_sidecar()
        except Exception as e:
            # Genuine absence (sidecar object gone) -> honest empty null (broadly_high stays
            # unreachable, an honest degradation). A transient/creds/broken-env error must NOT
            # masquerade as absence -- re-raise so the caller surfaces an honest _live_read_error
            # instead of silently narrowing the all-protein null.
            from onc_methods.target_id_sidecar import is_definitively_absent

            if isinstance(e, FileNotFoundError) or is_definitively_absent(e):
                return tuple()
            raise
    try:
        df = _read_csv(matrix_path, S3_BUCKET, MATRIX_KEY)
        id_col = df.columns[0]
        med = df.drop(columns=[id_col]).median(axis=0, numeric_only=True)  # one median per protein col
        return tuple(float(x) for x in med.tolist())
    except Exception:
        return tuple()


@lru_cache(maxsize=2)
def _all_protein_median_null_olink() -> tuple:
    """Per-protein median-NPX vector across ALL proteins in the OLINK matrix — the all-protein null for
    the Olink-fallback path (review G1 follow-up). The Gygi null (_all_protein_median_null) is on the TMT
    log2-ratio scale; Olink NPX is a different scale, so an Olink-sourced call MUST be percentiled /
    high-cutoff-anchored against Olink's own panel, not Gygi's. One column-median pass over the Olink
    matrix; lru_cached. Empty tuple on any read failure (then high_cutoff stays None → broadly_high
    honestly cannot fire, same graceful degrade as the Gygi null)."""
    try:
        df = _read_csv(None, S3_BUCKET, OLINK_MATRIX_KEY)
        id_col = df.columns[0]
        med = df.drop(columns=[id_col]).median(axis=0, numeric_only=True)
        return tuple(float(x) for x in med.tolist())
    except Exception:  # noqa: BLE001
        return tuple()


def target_allgene_percentile(median_abund, matrix_path=None, source: str = "gygi_ms"):
    """Percentile + class of this target's median abundance among ALL proteins' medians.

    `source` selects the all-protein null: the Gygi TMT panel by default, or the Olink NPX panel when the
    call came from the Olink fallback (review G1 follow-up) — the two are different scales, so an
    Olink-sourced median must be ranked against Olink's own panel, not Gygi's."""

    from onc_methods.percentile_null import classify_percentile, percentile_rank

    null_vec = _all_protein_median_null_olink() if source == "olink_npx" else _all_protein_median_null(matrix_path)
    pct = percentile_rank(median_abund, null_vec)
    return pct, classify_percentile(pct)


def _panel_high_cutoff(vals: list) -> Optional[float]:
    """DISPLAY-ONLY reference line: the HIGH_ABUNDANCE_PERCENTILE quantile of `vals` — i.e. of THE
    TARGET'S OWN detected per-cell-line values. It is a WITHIN-TARGET quantile.

    ⚠️ It does NOT mirror compute_summary's `high_cutoff`, and the docstring that said so was wrong
    (corrected under #2223). `high_cutoff` is p70 of ALL proteins' panel medians — a cross-protein
    rank; this is p70 of one protein's own spread. Measured over 338 sampled Gygi proteins, the share
    of a target's own plotted points at/above this line is 0.296-0.333 (median 0.301) for EVERY
    target, because it is a quantile of the data it is drawn on: it carries no information about
    whether the protein is abundant, and it is not the line that decided `protein_expression_class`.
    Pinned by tests/test_panel_relative_high_cut_adjudication.py.

    It is still worth drawing as a SPREAD annotation ("where the top ~30% of this target's lines
    start"), which is why it is kept and relabelled rather than removed. The classification cutoff
    itself is now ALSO drawn alongside it (#2261): compute_summary carries it as
    `protein_high_abundance_class_cutoff`, so the emitters can plot both lines, each labelled with
    the population it is a quantile of.

    MS abundance genuinely has no absolute expressed/highly-expressed threshold like RNA's
    log2(TPM+1) 1.0/5.0 — the harmonized Gygi value is a relative TMT log2 ratio — so a relative
    reference line is the right KIND of line. Which population it is relative to is the point above."""
    if not vals:
        return None
    s = sorted(vals)
    idx = HIGH_ABUNDANCE_PERCENTILE * (len(s) - 1)
    lo = int(idx)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[min(lo + 1, len(s) - 1)] * frac


# protein_expression_class → one-line takeaway. {T} = target.
# EVERY distribution class needs an entry: _protein_take .get()s this map, so a missing token loses its
# takeaway SILENTLY rather than raising. Only data_unavailable is deliberately absent — there is no
# distribution to describe. Guarded by test_every_distribution_class_has_a_takeaway_phrase.
_PROTEIN_PHRASE = {
    "broadly_high": "{T} protein is highly abundant across cancer cell lines.",
    "broadly_moderate": "{T} protein is broadly detected at moderate abundance across cell lines.",
    "lineage_restricted": "{T} protein detection is concentrated in a few lineages.",
    "sub_broad_detection": (
        "{T} protein is detected in a sizeable minority of cell lines; no per-lineage breakdown was "
        "available, so lineage restriction was not tested."
    ),
    "broadly_low": "{T} protein is detected in few cell lines.",
}


def _protein_take(target_symbol, summary):
    p = _PROTEIN_PHRASE.get(summary.get("protein_expression_class"))
    return p.format(T=target_symbol) if p else None


def emit_density_protein(
    abundance_by_model: dict,
    target_symbol: str,
    summary: dict,
    out_dir: Path,
    target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS,
) -> Path:
    """PRIMARY figure: histogram + KDE of log2 protein abundance across detected DepMap lines, in the
    shared grammar. Draws three directly-labeled reference lines (no legend): the target's own
    median, the WITHIN-TARGET p70 spread line (_panel_high_cutoff), and — when
    `summary['protein_high_abundance_class_cutoff']` is available — the cross-protein cutoff that
    actually decided `protein_expression_class` (#2261; previously omitted, #2223). % detected — the
    metric behind the class — carried in provenance + at the median."""
    import matplotlib

    matplotlib.use("Agg")
    import numpy as np
    from scipy.stats import gaussian_kde

    pal = _load_takeda_style(target_contracts_dir)
    out_path = out_dir / "figure_density_protein_abundance.svg"
    vals = np.array(list((abundance_by_model or {}).values()), dtype=float)
    if vals.size == 0 or pal is None:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(
            0.5,
            0.5,
            f"{target_symbol} — not quantified in the Gygi MS panel",
            ha="center",
            va="center",
            fontsize=10,
            color="#777",
        )
        ax.set_axis_off()
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    med = summary.get("median_log2_abundance_panel")
    hi = _panel_high_cutoff(list(vals))
    class_cutoff = summary.get("protein_high_abundance_class_cutoff")
    frac = summary.get("fraction_detected")
    prov = f"DepMap 26Q1  ·  Gygi TMT MS  ·  n={vals.size} detected" + (
        f" ({frac:.0%} of panel)" if frac is not None else ""
    )
    with pal.figure_frame(
        target_symbol,
        None,
        "cell-line protein abundance",
        out_path=out_path,
        kind="scatter",
        provenance=prov,
        takeaway=_protein_take(target_symbol, summary),
    ) as F:
        ax = F.ax
        ax.hist(vals, bins=40, density=True, alpha=0.5, color=pal.TUMOR_FILL, edgecolor="white")
        if vals.size >= 10:
            kde = gaussian_kde(vals)
            xs = np.linspace(vals.min() - 0.2, vals.max() + 0.2, 500)
            ax.plot(xs, kde(xs), color=pal.TUMOR_LINE, linewidth=2)
        # Three reference lines, each labeled with the population it is a quantile of (#2261): the
        # target's own median/p70 sit on the top row (median left, p70 right, so the text never
        # collides); the cross-protein CLASS cutoff — the line that actually decided
        # protein_expression_class — is drawn in a distinct style on a row below so it never reads as
        # a fourth within-target statistic.
        for xv, lab, ha, dx, style in (
            (med, f"target median {med:.1f}" if med is not None else None, "right", -3, pal.REFLINE_NEUTRAL),
            (hi, f"target p70 {hi:.1f}" if hi is not None else None, "left", 3, pal.REFLINE_NEUTRAL),
        ):
            if xv is None:
                continue
            ax.axvline(xv, **style)
            ax.annotate(
                lab,
                xy=(xv, 0.99),
                xycoords=("data", "axes fraction"),
                ha=ha,
                va="top",
                xytext=(dx, -2),
                textcoords="offset points",
                fontsize=8,
                color=pal.INK_MUTED,
            )
        if class_cutoff is not None:
            ax.axvline(class_cutoff, **pal.REFLINE_NOMINAL)
            ax.annotate(
                f"class cutoff {class_cutoff:.2f} (all-protein p70)",
                xy=(class_cutoff, 0.99),
                xycoords=("data", "axes fraction"),
                ha="center",
                va="top",
                xytext=(0, -14),
                textcoords="offset points",
                fontsize=8,
                color=pal.INK_MUTED,
            )
        F.axis_label("x", "Protein abundance", "log2 (Gygi TMT MS, detected lines)")
        F.axis_label("y", "Density")
    return out_path


def emit_lineage_strip_protein(
    abundance_by_model: dict,
    lineage_by_model: dict,
    target_symbol: str,
    summary: dict,
    out_dir: Path,
    target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS,
) -> Path:
    """Per-lineage strip plot of log2 protein abundance, lineages ordered by median desc (n>=5)."""
    import matplotlib

    matplotlib.use("Agg")
    import numpy as np
    import pandas as pd

    pal = _load_takeda_style(target_contracts_dir)
    out_path = out_dir / "figure_lineage_strip_protein.svg"
    records = [
        {"lineage": lineage_by_model.get(mid) or "unknown", "abund": v} for mid, v in (abundance_by_model or {}).items()
    ]
    df = pd.DataFrame(records)
    if df.empty or pal is None:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, f"{target_symbol} — no MS detection", ha="center", va="center", fontsize=10, color="#777")
        ax.set_axis_off()
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    lm = df.groupby("lineage")["abund"].agg(["median", "count"])
    lm = lm[lm["count"] >= MIN_LINEAGE_SIZE].sort_values("median", ascending=False)
    ordered = list(lm.index)
    hi = _panel_high_cutoff(list(df["abund"].values))
    class_cutoff = summary.get("protein_high_abundance_class_cutoff")
    fig_h = min(max(3.8, len(ordered) * 0.24 + 1.4), 7.6)
    with pal.figure_frame(
        target_symbol,
        None,
        "cell-line protein abundance by lineage",
        out_path=out_path,
        figsize=(pal.FIGSIZE_DOUBLE_COLUMN[0], fig_h),
        left=0.24,
        top=1 - 0.72 / fig_h,
        bottom=0.95 / fig_h,
        provenance=f"DepMap 26Q1 Gygi TMT MS  ·  n={len(df)} detected lines  ·  lineages with n≥{MIN_LINEAGE_SIZE}",
        takeaway=_protein_take(target_symbol, summary),
    ) as F:
        ax = F.ax
        for i, lin in enumerate(ordered):
            scores = df[df["lineage"] == lin]["abund"].values
            jitter = np.random.RandomState(42 + i).uniform(-0.15, 0.15, size=len(scores))
            ax.scatter(scores, np.full(len(scores), i) + jitter, alpha=0.5, s=8, color=pal.get_lineage_color(lin))
            ax.scatter([np.median(scores)], [i], color=pal.INK_SECONDARY, s=34, marker="|", zorder=5)
        if hi is not None:
            ax.axvline(hi, **pal.REFLINE_NEUTRAL)
            ax.annotate(
                f"target p70 {hi:.1f}",
                xy=(hi, 0.99),
                xycoords=("data", "axes fraction"),
                ha="center",
                va="top",
                xytext=(0, -2),
                textcoords="offset points",
                fontsize=7.5,
                color=pal.INK_MUTED,
            )  # inside top edge (clears the provenance line)
        if class_cutoff is not None:
            # the cross-protein cutoff that actually decided protein_expression_class (#2261) — a
            # distinct style from the within-target p70 line above so the two are never confused.
            ax.axvline(class_cutoff, **pal.REFLINE_NOMINAL)
            ax.annotate(
                f"class cutoff {class_cutoff:.2f} (all-protein p70)",
                xy=(class_cutoff, 0.99),
                xycoords=("data", "axes fraction"),
                ha="center",
                va="top",
                xytext=(0, -12),
                textcoords="offset points",
                fontsize=7.5,
                color=pal.INK_MUTED,
            )
        ax.set_yticks(range(len(ordered)))
        ax.set_yticklabels(ordered, fontsize=7.5)
        ax.set_ylim(-0.8, len(ordered) - 0.2)
        ax.invert_yaxis()
        ax.grid(axis="x", alpha=0.25, linewidth=0.4)
        ax.grid(axis="y", visible=False)
        F.axis_label("x", "Protein abundance", "log2 (Gygi TMT MS)")
    return out_path


def emit_plot_data_protein(abundance_by_model: dict, lineage_by_model: dict, out_dir: Path) -> Path:
    """Per-cell-line long-format parquet (the card's declared plot_data:
    per_cell_line_protein_abundance_with_lineage_tags) — SAME series the SVGs/plotly draw."""
    import pandas as pd

    rows = [
        {"model_id": mid, "lineage": lineage_by_model.get(mid), "log2_abundance": v}
        for mid, v in (abundance_by_model or {}).items()
    ]
    df = pd.DataFrame(rows)
    out_file = out_dir / "plot_data_protein_abundance.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_plotly_specs(
    abundance_by_model: dict,
    lineage_by_model: dict,
    target_symbol: str,
    summary: dict,
    out_dir: Path,
    target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS,
    indication: str = None,
) -> list:
    """Interactive Plotly siblings (dynamic-dashboard Phase A) built from the SAME
    abundance_by_model the SVGs use — no drift. Writes:
      - figure_density_protein_abundance.plotly.json   (histogram + relative abundance BUCKETS)
      - figure_waterfall_protein_abundance.plotly.json (ranked per-cell-line bars)
      - figure_lineage_protein_abundance.plotly.json   (per-lineage box, n>=5; indication highlighted)
    Mirrors the RNA depmap_expression_distribution emitter (item #2). Protein abundance is on a
    RELATIVE scale (Gygi TMT log2-ratio), so there is correctly no absolute expressed/highly-expressed
    cutoff to shade against as RNA's 1.0/5.0 are. The buckets shade against the target's OWN median and
    its OWN p70 (_panel_high_cutoff) — WITHIN-TARGET quantiles, so every target gets the same
    50/20/30 split of its lines by construction; they describe this target's spread, not abundance.
    The cross-protein cutoff that actually decided `protein_expression_class`
    (summary['protein_high_abundance_class_cutoff']) is drawn as a fourth, distinctly-styled line
    when available (#2261; previously omitted entirely, #2223). Best-effort."""
    try:
        import numpy as np
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001
        print(f"[cellline-protein-abundance] plotly spec emission skipped: {e}", file=__import__("sys").stderr)
        return []
    if not abundance_by_model:
        return []
    written = []
    vals = list(abundance_by_model.values())
    hi = _panel_high_cutoff(vals)
    med = summary.get("median_log2_abundance_panel")
    class_cutoff = summary.get("protein_high_abundance_class_cutoff")
    reflines = [(med, "#888", "dot", "target median"), (hi, "#f0a020", "dash", "target p70")]
    # The cross-protein cutoff that actually decided protein_expression_class (#2261) — a distinct
    # color/dash from the two within-target lines above so it never reads as a third spread statistic.
    if class_cutoff is not None:
        reflines.append((class_cutoff, "#1f6fdb", "solid", "class cutoff (all-protein p70)"))
    # density histogram + RELATIVE abundance buckets (item #2)
    try:
        arr = np.array(vals, dtype=float)
        xmin, xmax = float(arr.min()) - 0.3, float(arr.max()) + 0.3
        fig = go.Figure(
            go.Histogram(
                x=vals,
                histnorm="probability density",
                nbinsx=40,
                marker_color="#0a2540",
                marker_line_color="white",
                marker_line_width=0.5,
                opacity=0.55,
                hovertemplate="log2 abundance %{x:.2f}<br>density %{y:.3f}<extra></extra>",
            )
        )
        # Shade this target's own spread (protein MS has no absolute expressed cutoff): below its
        # median / median→its p70 / ≥ its p70. WITHIN-TARGET bands, not a cross-protein abundance
        # judgement (#2223). Skipped if med/hi absent.
        if med is not None and hi is not None and hi > med:
            for x0, x1, fill, lab in [
                (xmin, med, "rgba(150,160,170,0.10)", "below median"),
                (med, hi, "rgba(240,160,32,0.09)", "moderate"),
                (hi, xmax, "rgba(207,40,40,0.09)", "top ~30% of lines"),
            ]:
                if x1 > x0:
                    fig.add_vrect(
                        x0=x0,
                        x1=x1,
                        fillcolor=fill,
                        line_width=0,
                        layer="below",
                        annotation_text=lab,
                        annotation_position="top",
                        annotation=dict(font_size=9, font_color="#8a94a0"),
                    )
        for xv, col, dash, lab in reflines:
            if xv is not None:
                fig.add_vline(
                    x=xv, line=dict(color=col, dash=dash, width=1.5), annotation_text=lab, annotation_position="top"
                )
        fig.update_layout(
            title=dict(text=f"{target_symbol} — cell-line protein abundance (n={len(vals)} detected)", font_size=13),
            xaxis_title="log2 protein abundance (Gygi TMT MS)",
            yaxis_title="Density",
            template="plotly_white",
            showlegend=False,
            height=300,
            margin=dict(l=54, r=16, t=40, b=44),
            font=dict(size=11),
        )
        (out_dir / "figure_density_protein_abundance.plotly.json").write_text(fig.to_json())
        written.append(
            {
                "id": "density_protein_abundance",
                "path": "figure_density_protein_abundance.plotly.json",
                "type": "plotly",
            }
        )
    except Exception as e:  # noqa: BLE001
        print(f"[cellline-protein-abundance] density plotly skipped: {e}", file=__import__("sys").stderr)
    # ranked waterfall
    try:
        rows = sorted(
            ((mid, v, (lineage_by_model.get(mid) or "unknown")) for mid, v in abundance_by_model.items()),
            key=lambda r: r[1],
        )
        y = [v for _, v, _ in rows]
        names = [mid for mid, _, _ in rows]
        lins = [lg for _, _, lg in rows]
        fig = go.Figure(
            go.Bar(
                x=list(range(len(rows))),
                y=y,
                marker_color="#0a2540",
                customdata=list(zip(names, lins)),
                hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>log2 abundance %{y:.2f}<extra></extra>",
            )
        )
        if hi is not None:
            fig.add_hline(
                y=hi,
                line=dict(color="#f0a020", dash="dash", width=1.5),
                annotation_text="target p70",
                annotation_position="top left",
            )
        if class_cutoff is not None:
            fig.add_hline(
                y=class_cutoff,
                line=dict(color="#1f6fdb", dash="solid", width=1.5),
                annotation_text="class cutoff (all-protein p70)",
                annotation_position="bottom left",
            )
        fig.update_layout(
            title=f"{target_symbol} — cell-line protein abundance (ranked)",
            xaxis_title=f"Cell lines (n={len(rows)}, sorted)",
            yaxis_title="log2 protein abundance",
            template="plotly_white",
            showlegend=False,
            bargap=0,
            margin=dict(l=60, r=20, t=50, b=50),
        )
        (out_dir / "figure_waterfall_protein_abundance.plotly.json").write_text(fig.to_json())
        written.append(
            {
                "id": "waterfall_protein_abundance",
                "path": "figure_waterfall_protein_abundance.plotly.json",
                "type": "plotly",
            }
        )
    except Exception as e:  # noqa: BLE001
        print(f"[cellline-protein-abundance] waterfall plotly skipped: {e}", file=__import__("sys").stderr)
    # per-lineage box (item #2 — mirrors the RNA lineage plot; n>=5, ordered by median, indication
    # lineage highlighted red). The indication-relevant cell-line protein view IS its DepMap lineage.
    try:
        by_lineage: dict = {}
        for mid, v in abundance_by_model.items():
            lg = lineage_by_model.get(mid) or "unknown"
            by_lineage.setdefault(lg, []).append(v)
        lins2 = [(lg, lv) for lg, lv in by_lineage.items() if len(lv) >= 5]
        lins2.sort(key=lambda lv: float(np.median(lv[1])))  # ascending → highest median at top
        target_lineage = INDICATION_LINEAGE.get((indication or "").upper().strip()) if indication else None
        fig = go.Figure()
        for lg, lv in lins2:
            is_target = lg == target_lineage
            fig.add_trace(
                go.Box(
                    x=lv,
                    name=lg,
                    orientation="h",
                    boxpoints="all",
                    jitter=0.4,
                    pointpos=0,
                    marker=dict(size=3, opacity=0.5, color="#cf2828" if is_target else "#0a2540"),
                    line=dict(color="#cf2828" if is_target else "#7fa7c0", width=2 if is_target else 1),
                    hovertemplate=f"{lg}<br>log2 abundance %{{x:.2f}}<extra></extra>",
                )
            )
        for xv, col, dash, lab in reflines:
            if xv is not None:
                fig.add_vline(
                    x=xv, line=dict(color=col, dash=dash, width=1.2), annotation_text=lab, annotation_position="top"
                )
        ttl = f"{target_symbol} — per-lineage protein abundance (n≥5)"
        if target_lineage:
            ttl += f" · {target_lineage} highlighted"
        fig.update_layout(
            title=dict(text=ttl, font_size=13),
            xaxis_title="log2 protein abundance (Gygi TMT MS)",
            template="plotly_white",
            showlegend=False,
            margin=dict(l=130, r=16, t=40, b=40),
            font=dict(size=11),
            height=max(260, 18 * len(lins2) + 70),
        )
        (out_dir / "figure_lineage_protein_abundance.plotly.json").write_text(fig.to_json())
        written.append(
            {
                "id": "lineage_protein_abundance",
                "path": "figure_lineage_protein_abundance.plotly.json",
                "type": "plotly",
            }
        )
    except Exception as e:  # noqa: BLE001
        print(f"[cellline-protein-abundance] lineage plotly skipped: {e}", file=__import__("sys").stderr)
    return written


def load_and_classify(target: str, matrix_path=None, sidecar_path=None, model_path=None, plot_data_out=None) -> dict:
    """Full pipeline for one target: resolve accession → read column → classify.
    Panel size (detection denominator) comes from the same matrix read.

    plot_data_out (figure Stage 1): OPT-IN dir. When set, persists the per-cell-line long frame
    (plot_data_protein_abundance.parquet) here — where abundance_by_model + lineage are in memory —
    so figures.render_from_plot_data draws with NO live read. Default None => byte-identical no-op."""
    acc = resolve_accession(target, sidecar_path=sidecar_path)
    col = None
    panel_size = None
    source = "gygi_ms"
    all_protein_medians = None
    if acc is not None:
        col, panel_size = load_abundance_column(acc, matrix_path=matrix_path)
    if col is None:
        # Gygi whole-cell TMT MISS (target unresolved OR absent from the Gygi matrix). Try the Olink NPX
        # fallback (review G1 follow-up): antibody-based proteomics that covers surface/secreted antigens
        # the shotgun-MS panel systematically under-samples (MSLN/MUC16/CLDN18…). Only used when Gygi is
        # empty, so it never overrides a real Gygi measurement. Classified against the OLINK panel's OWN
        # all-protein null (below) — Olink NPX is a DIFFERENT scale from TMT log2-ratio, so mixing it with
        # the Gygi null would be a cross-assay error. The `protein_abundance_source` field marks which
        # assay produced the call so downstream consumers read it in the right frame.
        ocol, opanel, _oacc = load_olink_abundance_column(target)
        if ocol:
            col, panel_size, source = ocol, opanel, "olink_npx"
            all_protein_medians = _all_protein_median_null_olink()
        else:
            summ = compute_summary(target, None, {}, n_panel=panel_size)
            summ["protein_abundance_source"] = "data_unavailable"
            return summ
    else:
        # PANEL-WIDE Gygi all-protein median null so broadly_high is decided panel-relative (H3 fix):
        # a protein is "broadly_high" when its median is in the top (1-HIGH_ABUNDANCE_PERCENTILE) of ALL
        # proteins, not relative to its own spread. Same cached null as the display percentile.
        all_protein_medians = _all_protein_median_null(matrix_path)
    lineage = load_model_lineage(model_path=model_path)
    summary = compute_summary(target, col, lineage, n_panel=panel_size, all_protein_medians=all_protein_medians)
    summary["protein_abundance_source"] = source
    if plot_data_out is not None:  # figure Stage 1: persist plot_data during resolution (best-effort)
        try:
            _pd = Path(plot_data_out)
            _pd.mkdir(parents=True, exist_ok=True)
            emit_plot_data_protein(col, lineage, _pd)
        except Exception:  # noqa: BLE001 — plot_data persistence is additive; never break resolution
            pass
    return summary


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Cell-line protein-abundance distribution for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--matrix-path", default=None)
    ap.add_argument("--sidecar-path", default=None)
    ap.add_argument("--model-path", default=None)
    args = ap.parse_args(argv)
    out = load_and_classify(
        args.target, matrix_path=args.matrix_path, sidecar_path=args.sidecar_path, model_path=args.model_path
    )
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    _main()
